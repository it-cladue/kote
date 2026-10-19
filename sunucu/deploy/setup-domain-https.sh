#!/usr/bin/env bash
# Kanıt Paneli — alan adı ile HTTPS (Plesk'in nginx'i üzerinden, Plesk ekranı kullanılmadan).
#
#   bash deploy/setup-domain-https.sh panel.alanadi.com eposta@ornek.com [--dry-run]
#   bash deploy/setup-domain-https.sh --kaldir
#
# Ne yapar:
#   1. Ön kontrol: alan adının bu sunucuya baktığı, 80 portu üzerinden doğrulama yolunun
#      çalıştığı, panelin sağlıklı olduğu ve nginx yapılandırmasının temiz olduğu denetlenir.
#   2. /etc/nginx/conf.d/zz020_kanit-panel.conf dosyası yazılır (yalnız bu alan adı için; Plesk
#      bloklarından sonra yüklenir, varsayılan sunucu olmaz).
#      Plesk'in kendi site dosyalarına, vhost'larına, Apache'ye veya posta ayarlarına dokunulmaz.
#   3. Sertifika, IP sertifikasıyla aynı ayrı Certbot ortamından (/opt/kanit-certbot) ve aynı
#      doğrulanmış webroot yöntemiyle alınır (/opt/kanit-ssl/config altına).
#   4. 443 bloğu eklenir, nginx yeniden yüklenir, https://ALAN/saglik ile doğrulanır.
#   5. Otomatik yenileme zamanlayıcısı (kanit-sertifika.timer) kurulur/güncellenir; hem IP
#      hem alan adı sertifikasını yeniler ve iki nginx'i de yeniden yükler.
# Hata hâlinde yalnız bu betiğin yazdığı nginx dosyası geri alınır; alınmış sertifika kalır (zararsız).
set -Eeuo pipefail
IFS=$'\n\t'

# Test ortamı için ezilebilir değerler (canlı sunucuda değiştirmeyin).
IP="${KANIT_IP:-217.156.123.36}"
CONF="${KANIT_CONF:-/etc/nginx/conf.d/zz020_kanit-panel.conf}"
WEBROOT="${KANIT_WEBROOT:-/var/www/vhosts/default/htdocs}"
CERTBOT="${KANIT_CERTBOT:-/opt/kanit-certbot/bin/certbot}"
SSL_BASE="${KANIT_SSL_BASE:-/opt/kanit-ssl}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
NGINX_SERVICE="${KANIT_NGINX_SERVICE:-nginx.service}"
UNIT_DIR="${KANIT_UNIT_DIR:-/etc/systemd/system}"
PANEL_URL="${KANIT_PANEL_URL:-http://127.0.0.1:18080}"
CURL_EXTRA="${KANIT_CURL_EXTRA:-}"
CERT_NAME='kanit-domain'
CERT_DIR="$SSL_BASE/config/live/$CERT_NAME"
IP_PROXY_SERVICE='kanit-ip-proxy.service'
TIMER_NAME='kanit-sertifika'

if [[ -z "${KANIT_TEST:-}" ]]; then
    PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
fi

DRY_RUN=0
KALDIR=0
DOMAIN=''
EMAIL=''
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --kaldir) KALDIR=1 ;;
        -h|--help)
            sed -n '2,18p' "$0"; exit 0 ;;
        --*) echo "HATA: Bilinmeyen seçenek: $arg (--help)" >&2; exit 2 ;;
        *)
            if [[ -z "$DOMAIN" ]]; then DOMAIN="$arg"
            elif [[ -z "$EMAIL" ]]; then EMAIL="$arg"
            else echo "HATA: Fazla parametre: $arg" >&2; exit 2; fi ;;
    esac
done

fatal() { echo "DUR: $*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }

[[ ${EUID} -eq 0 ]] || fatal 'Bu betik root olarak çalıştırılmalı (PuTTY root oturumu).'
for bin in nginx curl openssl getent install mktemp cat rm date; do
    command -v "$bin" >/dev/null 2>&1 || fatal "Gerekli komut bulunamadı: $bin"
done
NGINX_BIN="$(command -v nginx)"

# ---------------------------------------------------------------- kaldırma
if (( KALDIR )); then
    [[ -f "$CONF" ]] || fatal "Kaldırılacak dosya yok: $CONF"
    rm -f -- "$CONF"
    if "$NGINX_BIN" -t >/dev/null 2>&1; then
        "$SYSTEMCTL" reload "$NGINX_SERVICE" 2>&1 | grep -v 'signal process started' >&2 || true
        bilgi "Alan adı yapılandırması kaldırıldı ($CONF). Sertifika ve yenileme zamanlayıcısı dokunulmadan bırakıldı."
        bilgi "Alan adı artık bu sunucuya bakmayacaksa sertifikayı da silin ki zamanlayıcı boşuna denemesin: $CERTBOT delete --cert-name $CERT_NAME --config-dir $SSL_BASE/config --work-dir $SSL_BASE/work --logs-dir $SSL_BASE/logs"
    else
        fatal 'nginx yapılandırması dosya kaldırıldıktan sonra bile hatalı; Plesk nginx yeniden yüklenmedi. Çıktıyı paylaşın.'
    fi
    exit 0
fi

# ---------------------------------------------------------------- girdi
[[ -n "$DOMAIN" && -n "$EMAIL" ]] || { sed -n '2,5p' "$0"; fatal 'Alan adı ve e-posta gerekli.'; }
DOMAIN="$(LC_ALL=C tr '[:upper:]' '[:lower:]' <<<"$DOMAIN")"
EMAIL="$(LC_ALL=C tr '[:upper:]' '[:lower:]' <<<"$EMAIL")"
[[ "$DOMAIN" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$ ]] || fatal "Alan adı geçersiz görünüyor: $DOMAIN (örnek: panel.alanadi.com)"
[[ "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[a-z]{2,}$ ]] || fatal "E-posta geçersiz görünüyor: $EMAIL"

# ---------------------------------------------------------------- ön kontrol
bilgi "Kanıt Paneli alan adı kurulumu — $DOMAIN"
[[ -x "$CERTBOT" ]] || fatal "Ayrı Certbot bulunamadı: $CERTBOT (IP sertifikası bu ortamla alınmıştı)."
[[ -d "$SSL_BASE/config" ]] || fatal "Sertifika dizini yok: $SSL_BASE/config"
[[ -d "$WEBROOT" ]] || fatal "Doğrulama kökü yok: $WEBROOT (Plesk'in IP için kullandığı varsayılan site dizini)."
if [[ -e "$CONF" ]]; then
    fatal "$CONF zaten var. Önceki kurulum duruyor; yeniden kurmak için önce: bash deploy/setup-domain-https.sh --kaldir"
fi
"$SYSTEMCTL" is-active --quiet "$NGINX_SERVICE" || fatal "Plesk'in nginx servisi ($NGINX_SERVICE) çalışmıyor; önce 'systemctl start nginx' ile açın."
if ! "$NGINX_BIN" -t >/dev/null 2>&1; then
    fatal 'Mevcut nginx yapılandırması zaten hatalı (nginx -t). Hiçbir şey değiştirilmedi; "nginx -t" çıktısını paylaşın.'
fi
[[ "$(curl -fsS --noproxy '*' --connect-timeout 5 --max-time 10 "$PANEL_URL/saglik" 2>/dev/null || true)" == 'OK' ]] \
    || fatal "Panel iç sağlık kontrolü başarısız ($PANEL_URL/saglik). Önce 'systemctl status kanit-web' çıktısına bakın."

# DNS: alan adı bu sunucuya bakmalı.
COZUM="$(getent ahosts "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' ' | sed 's/ $//' || true)"
if [[ "$COZUM" != "$IP" ]]; then
    fatal "DNS kaydı bu sunucuya bakmıyor veya başka adresler de var. $DOMAIN şu an şuraya çözülüyor: ${COZUM:-hiçbir yere}. Beklenen yalnız: $IP. Tek bir A kaydı olmalı (AAAA/IPv6 kaydı olmamalı; Cloudflare kullanıyorsanız bulut simgesi GRİ olmalı). Dışarıdan görünen kaydı şu komutla kontrol edin: dig +short $DOMAIN @1.1.1.1 — 5-10 dk sonra tekrar deneyin."
fi
# Plesk'in IP için varsayılan sunucusu olmalı; yoksa yalnız uyarı (panel bloğu Plesk bloklarından sonra yüklenir).
IP_RE="${IP//./\\.}"
for p in 80 443; do
    if ! "$NGINX_BIN" -T 2>/dev/null | grep -Eq "(^|[[:space:];{])listen[[:space:]]+$IP_RE:$p[^;]*default_server"; then
        bilgi "UYARI: Plesk nginx'te $IP:$p için default_server tanımı görülmedi; IP ile doğrudan açılan istekler Plesk'in ilk bloğuna düşmeye devam eder."
    fi
done

# 80 portu doğrulama yolu: Plesk nginx bu alan adını varsayılan siteye düşürmeli.
CHALLENGE_DIR="$WEBROOT/.well-known/acme-challenge"
install -d -m 755 "$CHALLENGE_DIR"
TOKEN="kanit-dns-test-$(date +%s)-$$"
TEST_FILE="$CHALLENGE_DIR/$TOKEN"
printf 'KANIT_DOGRULAMA_%s' "$TOKEN" > "$TEST_FILE"
chmod 644 "$TEST_FILE"
cleanup_test_file() { rm -f -- "$TEST_FILE"; }
GELEN="$(curl -fsS --noproxy '*' --connect-timeout 8 --max-time 15 "http://$DOMAIN/.well-known/acme-challenge/$TOKEN" 2>/dev/null || true)"
cleanup_test_file
if [[ "$GELEN" != "KANIT_DOGRULAMA_$TOKEN" ]]; then
    fatal "http://$DOMAIN/.well-known/acme-challenge/... üzerinden doğrulama dosyası okunamadı. 80 portu dışarıdan kapalı olabilir veya alan adı başka bir siteye gidiyor. Hiçbir şey değiştirilmedi."
fi

bilgi "Ön kontrol tamam: DNS $DOMAIN -> $IP, 80 portu doğrulama yolu açık, panel sağlıklı, nginx yapılandırması temiz."
bilgi "Yazılacak dosya: $CONF (yalnız bu alan adının bloğu)."
bilgi "Sertifika: $CERT_DIR (Certbot: $CERTBOT, webroot: $WEBROOT)."
bilgi "Dokunulmayacak: Plesk vhost dosyaları, betofficetvguncel.com, Apache, posta, güvenlik duvarı, kanit-ip-proxy (IP:18443 çalışmaya devam eder)."
if (( DRY_RUN )); then
    bilgi 'DRY-RUN_TAMAM: Yalnız kontrol yapıldı; nginx, sertifika ve servisler değiştirilmedi (doğrulama klasöründeki geçici test dosyası silindi).'
    exit 0
fi

# ---------------------------------------------------------------- değişiklikler
CONF_WRITTEN=0
ADIM='hazırlık'
rollback() {
    local code="$1"
    trap - ERR INT TERM
    set +e
    echo "KURULUM_HATASI [$code] — adım: $ADIM. Bu betiğin yazdığı nginx dosyası geri alınıyor." >&2
    cleanup_test_file
    if (( CONF_WRITTEN )) && [[ -f "$CONF" ]]; then
        rm -f -- "$CONF"
        if "$NGINX_BIN" -t >/dev/null 2>&1; then "$SYSTEMCTL" reload "$NGINX_SERVICE" >/dev/null 2>&1 || true; fi
    fi
    echo 'Plesk siteleri, sertifikalar, panel verileri ve IP:18443 erişimi değiştirilmedi. Hata çıktısını paylaşın.' >&2
    exit "$code"
}
trap 'rollback "$?"' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM
# Bu noktadan sonra fatal da geri alma yapar.
fatal() { echo "DUR: $*" >&2; rollback 1; }

nginx_test_ve_yukle() {
    if ! "$NGINX_BIN" -t >/dev/null 2>&1; then
        echo 'nginx yapılandırma denetimi başarısız:' >&2
        "$NGINX_BIN" -t 2>&1 | sed 's/^/   /' >&2 || true
        return 1
    fi
    local cikti
    if ! cikti="$("$SYSTEMCTL" reload "$NGINX_SERVICE" 2>&1)"; then
        echo "nginx yeniden yüklenemedi: $cikti" >&2
        return 1
    fi
    printf '%s\n' "$cikti" | grep -v 'signal process started' >&2 || true
    return 0
}

http_blogu() {
    cat <<NGINX
# Kanıt Paneli — $DOMAIN (bu dosya deploy/setup-domain-https.sh tarafından yazıldı; Plesk üretmez, Plesk ezmez)
server {
    listen $IP:80;
    server_name $DOMAIN;
    # Let's Encrypt doğrulaması: IP sertifikasıyla aynı kök dizin.
    location ^~ /.well-known/acme-challenge/ {
        root $WEBROOT;
        default_type text/plain;
    }
    location / {
        return 301 https://\$host\$request_uri;
    }
}
NGINX
}

https_blogu() {
    cat <<NGINX
server {
    listen $IP:443 ssl;
    server_name $DOMAIN;
    ssl_certificate $CERT_DIR/fullchain.pem;
    ssl_certificate_key $CERT_DIR/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:KANIT_DOMAIN_TLS:10m;
    ssl_session_timeout 1h;
    ssl_session_tickets off;
    server_tokens off;
    client_max_body_size 12m;
    client_body_timeout 60s;
    keepalive_timeout 30s;
    # Her istek panelin kendi giriş ve yetki kontrolünden geçer.
    location / {
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
    }
}
NGINX
}

# 1) Yalnız 80 bloğu (sertifika henüz yok).
ADIM='1/4 nginx 80 bloğu'
CONF_WRITTEN=1
http_blogu > "$CONF"
chmod 644 "$CONF"
nginx_test_ve_yukle
# Yeniden yükleme birkaç saniye sürebilir; yönlendirme görülene kadar kısa aralıklarla denenir.
YONLENDIRME=''
for deneme in 1 2 3 4 5 6 7 8 9 10; do
    YONLENDIRME="$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 --resolve "$DOMAIN:80:$IP" "http://$DOMAIN/" || true)"
    [[ "$YONLENDIRME" == '301' ]] && break
    sleep 1
done
[[ "$YONLENDIRME" == '301' ]] || fatal "80 bloğu yüklendi ama http://$DOMAIN/ beklenen yönlendirmeyi vermedi (HTTP $YONLENDIRME). nginx yeniden yüklemesi uygulanmamış olabilir; 'systemctl status nginx' çıktısını paylaşın."
bilgi "1/4 nginx 80 bloğu eklendi ve yeniden yüklendi."

# 2) Sertifika (varsa yeniden kullanılır; süresi azsa Certbot kendisi yeniler).
ADIM='2/4 sertifika alma'
CERTBOT_LOG="$SSL_BASE/logs/kanit-domain-kurulum.log"
install -d -m 700 "$SSL_BASE/logs"
if [[ -r "$CERT_DIR/fullchain.pem" ]] && openssl x509 -in "$CERT_DIR/fullchain.pem" -checkend 604800 -noout >/dev/null 2>&1 \
   && openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -ext subjectAltName 2>/dev/null | grep -Fq "DNS:$DOMAIN"; then
    bilgi "2/4 Mevcut sertifika kullanılıyor ($CERT_DIR, en az 7 gün geçerli)."
else
    "$CERTBOT" certonly --webroot -w "$WEBROOT" -d "$DOMAIN" --cert-name "$CERT_NAME" \
        --config-dir "$SSL_BASE/config" --work-dir "$SSL_BASE/work" --logs-dir "$SSL_BASE/logs" \
        --non-interactive --agree-tos --no-eff-email -m "$EMAIL" --keep-until-expiring \
        --deploy-hook "$SYSTEMCTL reload $NGINX_SERVICE" >"$CERTBOT_LOG" 2>&1 || {
            echo 'Sertifika alınamadı. Certbot açıklaması:' >&2
            sed 's/^/   /' "$CERTBOT_LOG" >&2 || true
            fatal "Let's Encrypt doğrulaması başarısız. Çoğu zaman sebep: DNS henüz yayılmadı ya da 80 portu dışarıdan kapalı. Günlük: $CERTBOT_LOG"
        }
    [[ -r "$CERT_DIR/fullchain.pem" && -r "$CERT_DIR/privkey.pem" ]] || fatal 'Certbot bitti ama sertifika dosyaları bulunamadı.'
    bilgi "2/4 Sertifika alındı: $CERT_DIR"
fi

# 3) 443 bloğu.
ADIM='3/4 HTTPS bloğu ve sağlık kontrolü'
{ http_blogu; https_blogu; } > "$CONF"
nginx_test_ve_yukle
# shellcheck disable=SC2086
if ! SONUC="$(curl -fsS --noproxy '*' $CURL_EXTRA --retry 10 --retry-connrefused --retry-delay 1 --connect-timeout 5 --max-time 10 \
    --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/saglik" 2>&1)"; then
    fatal "https://$DOMAIN/saglik erişilemedi: $SONUC"
fi
[[ "$SONUC" == 'OK' ]] || fatal "https://$DOMAIN/saglik beklenen OK yanıtını vermedi: $SONUC"
bilgi "3/4 HTTPS doğrulandı: https://$DOMAIN/saglik -> OK"

# 4) Otomatik yenileme: IP ve alan adı sertifikaları birlikte; her iki nginx yeniden yüklenir.
ADIM='4/4 yenileme zamanlayıcısı'
install -d -m 755 "$UNIT_DIR"
cat > "$UNIT_DIR/$TIMER_NAME.service" <<SERVICE
[Unit]
Description=Kanit Paneli sertifika yenileme (IP + alan adi)
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
ExecStart=$CERTBOT renew --quiet --config-dir $SSL_BASE/config --work-dir $SSL_BASE/work --logs-dir $SSL_BASE/logs --deploy-hook "systemctl reload $IP_PROXY_SERVICE; systemctl reload $NGINX_SERVICE"
SERVICE
cat > "$UNIT_DIR/$TIMER_NAME.timer" <<TIMER
[Unit]
Description=Kanit Paneli sertifika yenileme zamanlayicisi
[Timer]
OnCalendar=*-*-* 00/6:17:00
RandomizedDelaySec=20m
Persistent=true
[Install]
WantedBy=timers.target
TIMER
chmod 644 "$UNIT_DIR/$TIMER_NAME.service" "$UNIT_DIR/$TIMER_NAME.timer"
"$SYSTEMCTL" daemon-reload
if ! ZAMANLAYICI="$("$SYSTEMCTL" enable --now "$TIMER_NAME.timer" 2>&1)"; then
    fatal "Yenileme zamanlayıcısı etkinleştirilemedi: $ZAMANLAYICI"
fi
bilgi "4/4 Otomatik yenileme kuruldu: $TIMER_NAME.timer (6 saatte bir kontrol; IP ve alan adı sertifikaları birlikte)."

trap - ERR INT TERM
bilgi ''
bilgi 'ALAN_ADI_HTTPS_TAMAM'
bilgi "Tarayıcı adresi: https://$DOMAIN  (eski görünüm kalırsa Ctrl+F5)"
bilgi "IP adresi de çalışmaya devam eder: https://$IP:18443"
bilgi "Sertifika bitiş: $(openssl x509 -in "$CERT_DIR/fullchain.pem" -noout -enddate | cut -d= -f2)"
bilgi "Kaldırmak için: bash deploy/setup-domain-https.sh --kaldir"
