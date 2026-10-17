#!/usr/bin/env bash
# Yalnız IP HTTPS erişimi. Plesk süreçleri ve sertifika yenilemesi değiştirilmez.
set -Eeuo pipefail
IP='217.156.123.36'
PORT='18443'
BASE='/opt/kanit-ssl'
APP='/opt/kanit-paneli'
CACHE='/var/cache/kanit-ip-proxy'
CONF="$BASE/nginx.conf"
UNIT='/etc/systemd/system/kanit-ip-proxy.service'
CERT="$BASE/config/live/kanit-ip/fullchain.pem"
KEY="$BASE/config/live/kanit-ip/privkey.pem"
ENVFILE="$APP/.env"
ENV_CHANGED=0
CONF_CREATED=0
UNIT_CREATED=0
BACKUP=''
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || fail 'Root oturumu gerekli.'
NGINX=$(command -v nginx) || fail 'Mevcut nginx binary bulunamadı.'
[ -r "$CERT" ] && [ -r "$KEY" ] || fail 'IP sertifikası veya anahtar dosyası bulunamadı.'
[ -f "$ENVFILE" ] || fail 'Panelin .env dosyası bulunamadı.'
getent passwd kanit >/dev/null || fail 'kanit servis hesabı bulunamadı.'
getent group kanit >/dev/null || fail 'kanit servis grubu bulunamadı.'
for file in "$CONF" "$UNIT"; do
    [ ! -e "$file" ] || fail "$file zaten mevcut. Üzerine yazılmadı; çıktıyı paylaşın."
done
if ss -lnt | grep -qE ":${PORT}[[:space:]]"; then
    fail "$PORT portu zaten kullanılıyor."
fi
openssl x509 -in "$CERT" -checkend 3600 -noout || fail 'Sertifika süresi yetersiz.'
openssl x509 -in "$CERT" -noout -ext subjectAltName | grep -Fq "IP Address:$IP" || fail 'Sertifikadaki IP eşleşmiyor.'
[ "$(curl -fsS --connect-timeout 5 --max-time 10 http://127.0.0.1:18080/saglik)" = 'OK' ] || fail 'Yerel panel sağlık kontrolü başarısız.'
BACKUP="/root/kanit-kurulum/ip-https-$(date +%Y%m%d-%H%M%S)-$$"
install -d -m 700 "$BACKUP"
cp -p "$ENVFILE" "$BACKUP/env.before"
rollback() {
    local code="$1"
    trap - ERR
    set +e
    printf '\nKurulum başarısız. Yalnız bu betiğin değişiklikleri geri alınıyor.\n' >&2
    if [ "$UNIT_CREATED" = 1 ]; then
        systemctl disable --now kanit-ip-proxy.service >/dev/null 2>&1
        rm -f "$UNIT"
    fi
    if [ "$CONF_CREATED" = 1 ]; then rm -f "$CONF"; fi
    systemctl daemon-reload
    if [ "$ENV_CHANGED" = 1 ]; then
        cp -p "$BACKUP/env.before" "$ENVFILE"
        systemctl restart kanit-web.service
    fi
    printf 'Sertifikalar, panel verileri ve Plesk yapılandırması silinmedi. Hata çıktısını paylaşın.\n' >&2
    exit "$code"
}
trap 'rollback "$?"' ERR
install -d -m 700 "$BASE/proxy-logs"
install -d -m 755 /run/kanit-ip-proxy
install -d -m 700 -o kanit -g kanit "$CACHE"
for name in client_body proxy fastcgi uwsgi scgi; do
    install -d -m 700 -o kanit -g kanit "$CACHE/$name"
done
CONF_CREATED=1
cat > "$CONF" <<'NGINX_CONFIG'
user kanit kanit;
worker_processes 1;
pid /run/kanit-ip-proxy/nginx.pid;
error_log /opt/kanit-ssl/proxy-logs/error.log warn;
events { worker_connections 512; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server_tokens off;
    access_log /opt/kanit-ssl/proxy-logs/access.log;
    # Hiçbir Plesk temp/cache dizini kullanılmaz veya sahipliği değiştirilmez.
    client_body_temp_path /var/cache/kanit-ip-proxy/client_body;
    proxy_temp_path /var/cache/kanit-ip-proxy/proxy;
    fastcgi_temp_path /var/cache/kanit-ip-proxy/fastcgi;
    uwsgi_temp_path /var/cache/kanit-ip-proxy/uwsgi;
    scgi_temp_path /var/cache/kanit-ip-proxy/scgi;
    server {
        listen 18443 ssl;
        server_name 217.156.123.36;
        ssl_certificate /opt/kanit-ssl/config/live/kanit-ip/fullchain.pem;
        ssl_certificate_key /opt/kanit-ssl/config/live/kanit-ip/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_cache shared:KANIT_IP_TLS:10m;
        ssl_session_timeout 1h;
        ssl_session_tickets off;
        client_max_body_size 12m;
        client_body_timeout 60s;
        keepalive_timeout 30s;
        # Her istek panelin kendi giriş ve yetki kontrolünden geçer.
        location / {
            proxy_pass http://127.0.0.1:18080;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-Host $http_host;
            proxy_set_header X-Forwarded-Port $server_port;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Connection "";
            proxy_read_timeout 120s;
            proxy_send_timeout 120s;
        }
    }
}
NGINX_CONFIG
chmod 600 "$CONF"
# Yalnız ayrı config kullanılır. Plesk nginx.conf ve modül config'leri yüklenmez.
"$NGINX" -t -p "$BASE/" -c "$CONF"
UNIT_CREATED=1
cat > "$UNIT" <<SERVICE_CONFIG
[Unit]
Description=Kanit Paneli Ayrı IP HTTPS Proxy
After=network-online.target kanit-web.service
Wants=network-online.target kanit-web.service
[Service]
Type=simple
ExecStart=$NGINX -p /opt/kanit-ssl/ -c /opt/kanit-ssl/nginx.conf -g "daemon off;"
ExecReload=/bin/kill -HUP \$MAINPID
KillSignal=SIGQUIT
TimeoutStopSec=30
Restart=on-failure
RestartSec=5
RuntimeDirectory=kanit-ip-proxy
RuntimeDirectoryMode=0755
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/run/kanit-ip-proxy /var/cache/kanit-ip-proxy /opt/kanit-ssl/proxy-logs
[Install]
WantedBy=multi-user.target
SERVICE_CONFIG
chmod 644 "$UNIT"
systemd-analyze verify "$UNIT"
ENV_CHANGED=1
python3 - "$ENVFILE" <<'ENV_UPDATE'
import re
import sys
from pathlib import Path
p = Path(sys.argv[1])
text = p.read_text()
for key, value in [('HTTPS', '1'), ('TRUST_PROXY', '1')]:
    pattern = rf'(?m)^{key}=.*$'
    if re.search(pattern, text):
        text = re.sub(pattern, f'{key}={value}', text)
    else:
        text = text.rstrip('\n') + f'\n{key}={value}\n'
p.write_text(text)
ENV_UPDATE
systemctl daemon-reload
systemctl restart kanit-web.service
systemctl enable --now kanit-ip-proxy.service
RESULT=$(curl -fsS --noproxy '*' --retry 10 --retry-connrefused --retry-delay 1 \
    --connect-timeout 5 --max-time 10 \
    --resolve "$IP:$PORT:127.0.0.1" "https://$IP:$PORT/saglik")
[ "$RESULT" = 'OK' ]
trap - ERR
printf '\nHTTPS_SAGLIK_OK\n'
printf 'Tarayıcı adresi: https://%s:%s\n' "$IP" "$PORT"
printf 'Web kullanıcı adı: admin\n'
printf 'Özel ayar yedeği: %s/env.before\n' "$BACKUP"
printf 'Plesk nginx.service veya apache2.service yeniden başlatılmadı.\n'
printf 'Otomatik sertifika yenilemesi isteğiniz üzere henüz kurulmadı.\n'
printf 'Dış erişim yoksa yalnız 18443/TCP güvenlik duvarı kuralı ayrıca kontrol edilecek.\n'
