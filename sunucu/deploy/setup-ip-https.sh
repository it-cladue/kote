#!/usr/bin/env bash
# Kanıt Paneli — yalnız IP ile HTTPS erişimi (ayrı nginx örneği, 18443). Plesk süreçlerine dokunulmaz.
#
#   bash deploy/setup-ip-https.sh [--dry-run]            # ilk kurulum (nginx.conf + kanit-ip-proxy.service)
#   bash deploy/setup-ip-https.sh --servis-guncelle [--dry-run]
#                                                         # mevcut kurulumda yalnız birim dosyasını sertleştirilmiş
#                                                         # sürümle değiştirir (yedek alır, sağlık kontrolü, geri alma)
#   bash deploy/setup-ip-https.sh --yardim
#
# Mevcut kurulumda nginx.conf'a giriş sınırı ve TLS satırlarını eklemek için: bash deploy/nginx-giris-siniri.sh
# Not: Let's Encrypt IP sertifikası kısa ömürlüdür ve bu betik yenileme kurmaz. Kalıcı yol alan adı +
# Cloudflare'dır (deploy/setup-cloudflare-https.sh); alan adı çalışınca 18443 kapatılır:
#   systemctl disable --now kanit-ip-proxy
set -Eeuo pipefail
IFS=$'\n\t'

# Test ortamı için ezilebilir değerler (canlı sunucuda değiştirmeyin).
IP="${KANIT_IP:-217.156.123.36}"
PORT="${KANIT_PORT:-18443}"
BASE="${KANIT_SSL_BASE:-/opt/kanit-ssl}"
APP="${KANIT_APP:-/opt/kanit-paneli}"
CACHE="${KANIT_CACHE:-/var/cache/kanit-ip-proxy}"
RUN_DIR="${KANIT_RUN_DIR:-/run/kanit-ip-proxy}"
UNIT="${KANIT_UNIT:-/etc/systemd/system/kanit-ip-proxy.service}"
CERT="${KANIT_CERT:-$BASE/config/live/kanit-ip/fullchain.pem}"
KEY="${KANIT_KEY:-$BASE/config/live/kanit-ip/privkey.pem}"
MIME_TYPES="${KANIT_MIME_TYPES:-/etc/nginx/mime.types}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
PANEL_URL="${KANIT_PANEL_URL:-http://127.0.0.1:18080}"
BACKUP_ROOT="${KANIT_BACKUP_ROOT:-/root/kanit-kurulum}"
CURL_EXTRA="${KANIT_CURL_EXTRA:-}"
CONF="$BASE/nginx.conf"
ENVFILE="$APP/.env"
SERVICE='kanit-ip-proxy.service'
TLS_CIPHERS='ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305'

if [[ -z "${KANIT_TEST:-}" ]]; then
    PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
fi

DRY_RUN=0
SERVIS_GUNCELLE=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --servis-guncelle) SERVIS_GUNCELLE=1 ;;
        -h|--help|--yardim) sed -n '2,13p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $arg (--yardim)" >&2; exit 2 ;;
    esac
done

fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || fail 'Root oturumu gerekli.'
NGINX=$(command -v nginx) || fail 'Mevcut nginx binary bulunamadı.'
for bin in curl openssl ss install mktemp cmp diff date; do
    command -v "$bin" >/dev/null 2>&1 || fail "Gerekli komut bulunamadı: $bin"
done
getent passwd kanit >/dev/null || fail 'kanit servis hesabı bulunamadı.'
getent group kanit >/dev/null || fail 'kanit servis grubu bulunamadı.'

# nginx >= 1.25.1 ise "http2 on;" yönergesi, daha eskisinde "listen ... ssl http2;" kullanılır.
nginx_http2_yonergesi_var() {
    local surum maj min pat
    surum="$("$NGINX" -v 2>&1 | sed -nE 's#.*nginx/([0-9]+\.[0-9]+\.[0-9]+).*#\1#p')"
    [[ -n "$surum" ]] || return 1
    IFS=. read -r maj min pat <<<"$surum"
    (( maj > 1 || (maj == 1 && (min > 25 || (min == 25 && pat >= 1))) ))
}

proxy_basliklari() {
    cat <<NGINX
            proxy_pass $PANEL_URL;
            proxy_http_version 1.1;
            proxy_set_header Host \$http_host;
            proxy_set_header X-Forwarded-Host \$http_host;
            proxy_set_header X-Forwarded-Port \$server_port;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-For \$remote_addr;
            proxy_set_header X-Real-IP \$remote_addr;
            proxy_set_header Connection "";
            proxy_read_timeout 120s;
            proxy_send_timeout 120s;
NGINX
}

nginx_conf_uret() {
    local listen_blok
    if nginx_http2_yonergesi_var; then
        listen_blok="        listen $PORT ssl;
        http2 on;"
    else
        listen_blok="        listen $PORT ssl http2;"
    fi
    cat <<NGINX
user kanit kanit;
worker_processes 1;
pid $RUN_DIR/nginx.pid;
error_log $BASE/proxy-logs/error.log warn;
events { worker_connections 512; }
http {
    include $MIME_TYPES;
    default_type application/octet-stream;
    server_tokens off;
    access_log $BASE/proxy-logs/access.log;
    # Giriş denemeleri için istemci IP'si başına kenar sınırı (uygulamanın kendi kilidine ek).
    limit_req_zone \$binary_remote_addr zone=kanit_giris:1m rate=10r/m;
    limit_req_status 429;
    # Hiçbir Plesk temp/cache dizini kullanılmaz veya sahipliği değiştirilmez.
    client_body_temp_path $CACHE/client_body;
    proxy_temp_path $CACHE/proxy;
    fastcgi_temp_path $CACHE/fastcgi;
    uwsgi_temp_path $CACHE/uwsgi;
    scgi_temp_path $CACHE/scgi;
    server {
$listen_blok
        server_name $IP;
        ssl_certificate $CERT;
        ssl_certificate_key $KEY;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_prefer_server_ciphers off;
        ssl_ciphers $TLS_CIPHERS;
        ssl_ecdh_curve X25519:prime256v1:secp384r1;
        ssl_session_cache shared:KANIT_IP_TLS:10m;
        ssl_session_timeout 1d;
        ssl_session_tickets off;
        client_max_body_size 64m;
        client_body_timeout 60s;
        keepalive_timeout 30s;
        # Giriş: dakikada 10 deneme, 10 ani istek toleransı; fazlası 429.
        location = /giris {
            limit_req zone=kanit_giris burst=10 nodelay;
$(proxy_basliklari)
        }
        # Her istek panelin kendi giriş ve yetki kontrolünden geçer.
        location / {
$(proxy_basliklari)
        }
    }
}
NGINX
}

# nginx master root başlar (worker'lar nginx.conf ile kanit'e düşer); yetenek kümesi yalnız
# gerekenlerle sınırlıdır: port bağlama, setuid/setgid, günlük/temp sahipliği, dosya erişimi,
# kanit worker'larına sinyal (CAP_KILL). Servis açılmazsa önce CapabilityBoundingSet satırını kaldırın.
unit_uret() {
    cat <<SERVICE_CONFIG
[Unit]
Description=Kanit Paneli Ayrı IP HTTPS Proxy
After=network-online.target kanit-web.service
Wants=network-online.target kanit-web.service
[Service]
Type=simple
ExecStart=$NGINX -p $BASE/ -c $CONF -g "daemon off;"
ExecReload=/bin/kill -HUP \$MAINPID
KillSignal=SIGQUIT
TimeoutStopSec=30
Restart=on-failure
RestartSec=5
RuntimeDirectory=kanit-ip-proxy
RuntimeDirectoryMode=0755
UMask=0077
SyslogIdentifier=kanit-ip-proxy
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=$RUN_DIR $CACHE $BASE/proxy-logs
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
SystemCallArchitectures=native
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_CHOWN CAP_DAC_OVERRIDE CAP_KILL
AmbientCapabilities=
[Install]
WantedBy=multi-user.target
SERVICE_CONFIG
}

sertifika_bitis() {
    openssl x509 -in "$CERT" -noout -enddate 2>/dev/null | cut -d= -f2 || true
}

saglik_https() {
    # shellcheck disable=SC2086
    curl -fsS --noproxy '*' $CURL_EXTRA --retry 10 --retry-connrefused --retry-delay 1 \
        --connect-timeout 5 --max-time 10 \
        --resolve "$IP:$PORT:127.0.0.1" "https://$IP:$PORT/saglik" 2>/dev/null || true
}

# ---------------------------------------------------------------- yalnız birim güncellemesi
if (( SERVIS_GUNCELLE )); then
    [ -f "$UNIT" ] || fail "$UNIT yok; birim güncellemesi yalnız mevcut kurulumda çalışır. İlk kurulum için bayraksız çalıştırın."
    [ -f "$CONF" ] || fail "$CONF yok; mevcut kurulum eksik görünüyor."
    # Bu yolda sağlık kontrolünün amacı birimin/nginx'in ayakta olmasıdır, sertifikanın geçerliliği değil: IP sertifikası
    # dolmuş olabilir ve yenilenmez (bkz. başlık notu). Doğrulama kapalı (-k); gövde yine tam olarak 'OK' olmalıdır.
    CURL_EXTRA="-k${CURL_EXTRA:+ $CURL_EXTRA}"
    if [ -r "$CERT" ] && ! openssl x509 -in "$CERT" -checkend 0 -noout >/dev/null 2>&1; then
        bilgi "Not: IP sertifikası dolmuş (bitiş: $(sertifika_bitis)); sağlık kontrolü sertifika doğrulaması olmadan yapılır. Kalıcı çözüm: deploy/setup-cloudflare-https.sh."
    fi
    YENI_UNIT="$(mktemp)"
    trap 'rm -f -- "$YENI_UNIT"' EXIT
    unit_uret > "$YENI_UNIT"
    if cmp -s "$YENI_UNIT" "$UNIT"; then
        bilgi "BIRIM_GUNCEL: $UNIT zaten sertleştirilmiş sürümle aynı; değişiklik yok."
        exit 0
    fi
    bilgi "Birim farkı ($UNIT -> yeni):"
    diff -u "$UNIT" "$YENI_UNIT" | sed 's/^/   /' || true
    if (( DRY_RUN )); then
        bilgi 'DRY-RUN_TAMAM: Birim dosyası değiştirilmedi, servis yeniden başlatılmadı.'
        exit 0
    fi
    BACKUP="$BACKUP_ROOT/ip-proxy-birim-$(date +%Y%m%d-%H%M%S)-$$"
    install -d -m 700 "$BACKUP"
    cp -p "$UNIT" "$BACKUP/kanit-ip-proxy.service.before"
    geri_al() {
        set +e
        printf 'Birim güncellemesi başarısız; eski birim geri yükleniyor.\n' >&2
        install -m 644 "$BACKUP/kanit-ip-proxy.service.before" "$UNIT"
        "$SYSTEMCTL" daemon-reload
        "$SYSTEMCTL" restart "$SERVICE"
        exit 1
    }
    install -m 644 "$YENI_UNIT" "$UNIT"
    if command -v systemd-analyze >/dev/null 2>&1 && ! systemd-analyze verify "$UNIT"; then geri_al; fi
    "$SYSTEMCTL" daemon-reload || geri_al
    "$SYSTEMCTL" restart "$SERVICE" || geri_al
    SONUC="$(saglik_https)"
    if [ "$SONUC" != 'OK' ]; then
        printf 'https://%s:%s/saglik yeni birimle OK vermedi (yanıt: %s).\n' "$IP" "$PORT" "${SONUC:-boş}" >&2
        geri_al
    fi
    bilgi "BIRIM_GUNCELLENDI: $SERVICE sertleştirilmiş birimle çalışıyor; sağlık OK. Eski birim: $BACKUP/kanit-ip-proxy.service.before"
    bilgi "Sertifika bitiş: $(sertifika_bitis)"
    exit 0
fi

# ---------------------------------------------------------------- ilk kurulum
{ [ -r "$CERT" ] && [ -r "$KEY" ]; } || fail 'IP sertifikası veya anahtar dosyası bulunamadı.'
[ -f "$ENVFILE" ] || fail 'Panelin .env dosyası bulunamadı.'
for file in "$CONF" "$UNIT"; do
    [ ! -e "$file" ] || fail "$file zaten mevcut. Üzerine yazılmadı. Birim için --servis-guncelle, nginx.conf için deploy/nginx-giris-siniri.sh kullanın."
done
if ss -lnt | grep -qE ":${PORT}[[:space:]]"; then
    fail "$PORT portu zaten kullanılıyor."
fi
openssl x509 -in "$CERT" -checkend 3600 -noout >/dev/null || fail "Sertifika süresi yetersiz (bitiş: $(sertifika_bitis)). Kalıcı çözüm: deploy/setup-cloudflare-https.sh."
openssl x509 -in "$CERT" -noout -ext subjectAltName | grep -Fq "IP Address:$IP" || fail 'Sertifikadaki IP eşleşmiyor.'
[ "$(curl -fsS --noproxy '*' --connect-timeout 5 --max-time 10 "$PANEL_URL/saglik" 2>/dev/null || true)" = 'OK' ] || fail 'Yerel panel sağlık kontrolü başarısız.'
if nginx_http2_yonergesi_var; then HTTP2_NOT='http2 on; (nginx >= 1.25.1)'; else HTTP2_NOT='listen ... ssl http2; (nginx < 1.25.1)'; fi
bilgi "Ön kontrol tamam: sertifika $IP için geçerli (bitiş: $(sertifika_bitis)), panel sağlıklı, $PORT boş, HTTP/2: $HTTP2_NOT"
bilgi "Yazılacak: $CONF, $UNIT; .env içinde HTTPS=1 ve TRUST_PROXY=1."
if (( DRY_RUN )); then
    bilgi 'DRY-RUN_TAMAM: Hiçbir dosya veya servis değiştirilmedi.'
    exit 0
fi

ENV_CHANGED=0
CONF_CREATED=0
UNIT_CREATED=0
BACKUP="$BACKUP_ROOT/ip-https-$(date +%Y%m%d-%H%M%S)-$$"
install -d -m 700 "$BACKUP"
cp -p "$ENVFILE" "$BACKUP/env.before"
rollback() {
    local code="$1"
    trap - ERR
    set +e
    printf '\nKurulum başarısız. Yalnız bu betiğin değişiklikleri geri alınıyor.\n' >&2
    if [ "$UNIT_CREATED" = 1 ]; then
        "$SYSTEMCTL" disable --now "$SERVICE" >/dev/null 2>&1
        rm -f "$UNIT"
    fi
    if [ "$CONF_CREATED" = 1 ]; then rm -f "$CONF"; fi
    "$SYSTEMCTL" daemon-reload
    if [ "$ENV_CHANGED" = 1 ]; then
        cp -p "$BACKUP/env.before" "$ENVFILE"
        "$SYSTEMCTL" restart kanit-web.service
    fi
    printf 'Sertifikalar, panel verileri ve Plesk yapılandırması silinmedi. Hata çıktısını paylaşın.\n' >&2
    exit "$code"
}
trap 'rollback "$?"' ERR
install -d -m 700 "$BASE/proxy-logs"
install -d -m 755 "$RUN_DIR"
install -d -m 700 -o kanit -g kanit "$CACHE"
for name in client_body proxy fastcgi uwsgi scgi; do
    install -d -m 700 -o kanit -g kanit "$CACHE/$name"
done
CONF_CREATED=1
nginx_conf_uret > "$CONF"
chmod 600 "$CONF"
# Yalnız ayrı config kullanılır. Plesk nginx.conf ve modül config'leri yüklenmez.
"$NGINX" -t -p "$BASE/" -c "$CONF"
UNIT_CREATED=1
unit_uret > "$UNIT"
chmod 644 "$UNIT"
if command -v systemd-analyze >/dev/null 2>&1; then systemd-analyze verify "$UNIT"; fi
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
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" restart kanit-web.service
"$SYSTEMCTL" enable --now "$SERVICE"
RESULT="$(saglik_https)"
[ "$RESULT" = 'OK' ]
trap - ERR
printf '\nHTTPS_SAGLIK_OK\n'
printf 'Tarayıcı adresi: https://%s:%s\n' "$IP" "$PORT"
printf 'Web kullanıcı adı: admin\n'
printf 'Özel ayar yedeği: %s/env.before\n' "$BACKUP"
printf 'Plesk nginx.service veya apache2.service yeniden başlatılmadı.\n'
printf 'Sertifika bitiş: %s — bu IP sertifikası kısa ömürlüdür ve otomatik yenilenmez. Kalıcı yol: alan adı + Cloudflare (deploy/setup-cloudflare-https.sh); sonra 18443 kapatılır (systemctl disable --now kanit-ip-proxy).\n' "$(sertifika_bitis)"
printf 'Güvenlik duvarı: '; if command -v ufw >/dev/null 2>&1; then ufw status 2>/dev/null | head -1; else printf 'ufw kurulu değil (isteğe bağlı: deploy/setup-firewall.sh)\n'; fi
