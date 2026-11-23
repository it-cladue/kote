#!/usr/bin/env bash
# Kanıt Paneli — alan adı ile HTTPS, Cloudflare (TURUNCU bulut) arkasında. ANA YOL.
#
#   bash deploy/setup-cloudflare-https.sh panel.alanadi.com [--dry-run]
#   bash deploy/setup-cloudflare-https.sh panel.alanadi.com --sertifika origin.pem --anahtar origin.key
#   bash deploy/setup-cloudflare-https.sh panel.alanadi.com --oz-imzali      # soru sormadan 10 yıllık öz imzalı sertifika
#   bash deploy/setup-cloudflare-https.sh --ip-guncelle                      # Cloudflare IP listesini internetten tazele
#   bash deploy/setup-cloudflare-https.sh --kaldir                           # nginx dosyasını kaldır (sertifikalar kalır)
#   seçenekler: --herkese-acik  Cloudflare dışından doğrudan gelen istekleri de kabul et (önerilmez)
#               --kontrol-atla  kurulum sonrası yerel origin kontrolünü atla
#
# Ne yapar: Plesk'in nginx'ine /etc/nginx/conf.d/zz020_kanit-panel.conf yazar (yalnız bu alan adı; Plesk siteleri,
# Apache, posta ve IP:18443 yoluna dokunmaz). Ziyaretçi sertifikasını Cloudflare verir; sunucu tarafında
# Cloudflare Origin CA sertifikası (15 yıl, yenileme yok; Cloudflare panelinden alınır) ya da öz imzalı sertifika
# kullanılır; dosyalar /opt/kanit-ssl/cloudflare/ALAN.pem ve ALAN.key (root 600). Gerçek ziyaretçi IP'si
# CF-Connecting-IP başlığından alınır (set_real_ip_from Cloudflare aralıkları); Cloudflare'ı atlayıp doğrudan IP'ye
# gelen istekler 403 alır. /giris için nginx limit_req (10/dk, gerçek IP). Hata hâlinde yalnız kendi nginx dosyası geri alınır.
#
# Cloudflare tarafında yapılacaklar (betik sonunda da yazdırılır):
#   1. DNS: A kaydı  panel -> 217.156.123.36, bulut TURUNCU (Proxied).
#   2. SSL/TLS -> Overview: Full (strict) (Origin CA ile) ya da Full (öz imzalı ile).
#   3. SSL/TLS -> Edge Certificates: Always Use HTTPS AÇIK.
#   4. SSL/TLS -> Origin Server -> Create Certificate (RSA 2048, 15 yıl, hostname: panel.alanadi.com) -> iki metin
#      bloğunu kaydedin ve bu betiğe --sertifika/--anahtar ile verin ya da sorulduğunda yapıştırın.
set -Eeuo pipefail
IFS=$'\n\t'

# Test ortamı için ezilebilir değerler (canlı sunucuda değiştirmeyin).
IP="${KANIT_IP:-217.156.123.36}"
CONF="${KANIT_CONF:-/etc/nginx/conf.d/zz020_kanit-panel.conf}"
SSL_BASE="${KANIT_SSL_BASE:-/opt/kanit-ssl}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
NGINX_SERVICE="${KANIT_NGINX_SERVICE:-nginx.service}"
PANEL_URL="${KANIT_PANEL_URL:-http://127.0.0.1:18080}"
CURL_EXTRA="${KANIT_CURL_EXTRA:-}"
NGINX_T_ARGS="${KANIT_NGINX_T_ARGS:-}"   # yalnız test: "-c /tmp/x/root.conf -p /tmp/x/"
IFS=' ' read -r -a NGINX_T_DIZI <<<"$NGINX_T_ARGS"
HTTP_PORT="${KANIT_HTTP_PORT:-80}"
HTTPS_PORT="${KANIT_HTTPS_PORT:-443}"
CF_URL_V4="${KANIT_CF_URL_V4:-https://www.cloudflare.com/ips-v4}"
CF_URL_V6="${KANIT_CF_URL_V6:-https://www.cloudflare.com/ips-v6}"
CF_DIR="$SSL_BASE/cloudflare"
ARALIK_DOSYA="$CF_DIR/araliklar.txt"
IPS_CONF="$CF_DIR/ips.conf"
GEO_CONF="$CF_DIR/geo.conf"
TLS_CIPHERS='ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305'

if [[ -z "${KANIT_TEST:-}" ]]; then
    PATH=/usr/sbin:/usr/bin:/sbin:/bin
    export PATH
fi

DRY_RUN=0; KALDIR=0; IP_GUNCELLE=0; OZ_IMZALI=0; HERKESE_ACIK=0; KONTROL_ATLA=0
HOST=''; SERT_DOSYA=''; ANAHTAR_DOSYA=''
while (( $# )); do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --kaldir) KALDIR=1 ;;
        --ip-guncelle) IP_GUNCELLE=1 ;;
        --oz-imzali) OZ_IMZALI=1 ;;
        --herkese-acik) HERKESE_ACIK=1 ;;
        --kontrol-atla) KONTROL_ATLA=1 ;;
        --sertifika) shift; SERT_DOSYA="${1:-}" ;;
        --anahtar) shift; ANAHTAR_DOSYA="${1:-}" ;;
        -h|--help|--yardim) sed -n '2,26p' "$0"; exit 0 ;;
        --*) echo "HATA: Bilinmeyen seçenek: $1 (--yardim)" >&2; exit 2 ;;
        *) if [[ -z "$HOST" ]]; then HOST="$1"; else echo "HATA: Fazla parametre: $1" >&2; exit 2; fi ;;
    esac
    shift
done

fatal() { echo "DUR: $*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }
uyar() { printf 'UYARI: %s\n' "$*" >&2; }

[[ ${EUID} -eq 0 ]] || fatal 'Bu betik root olarak çalıştırılmalı (PuTTY root oturumu).'
for bin in nginx curl openssl getent install mktemp python3 ss cmp date; do
    command -v "$bin" >/dev/null 2>&1 || fatal "Gerekli komut bulunamadı: $bin"
done
NGINX_BIN="$(command -v nginx)"

# ---------------------------------------------------------------- Cloudflare aralıkları
# Gömülü liste (https://www.cloudflare.com/ips/, 2024-2026 arası değişmedi). --ip-guncelle ile tazelenir.
cf_gomulu_araliklar() {
    cat <<'LISTE'
173.245.48.0/20
103.21.244.0/22
103.22.200.0/22
103.31.4.0/22
141.101.64.0/18
108.162.192.0/18
190.93.240.0/20
188.114.96.0/20
197.234.240.0/22
198.41.128.0/17
162.158.0.0/15
104.16.0.0/13
104.24.0.0/14
172.64.0.0/13
131.0.72.0/22
2400:cb00::/32
2606:4700::/32
2803:f800::/32
2405:b500::/32
2405:8100::/32
2a06:98c0::/29
2c0f:f248::/32
LISTE
}

cidr_gecerli() { [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ || "$1" =~ ^[0-9a-fA-F:]+/[0-9]{1,3}$ ]]; }

# araliklar.txt -> ips.conf (set_real_ip_from) ve geo.conf (geo haritası için "aralık 1;")
cf_dosyalarini_uret() {
    local satir
    install -d -m 700 "$CF_DIR"
    [[ -s "$ARALIK_DOSYA" ]] || { cf_gomulu_araliklar > "$ARALIK_DOSYA"; chmod 600 "$ARALIK_DOSYA"; }
    {
        echo '# Cloudflare uç aralıkları (deploy/setup-cloudflare-https.sh; --ip-guncelle ile tazelenir). Elle düzenlemeyin.'
        while IFS= read -r satir; do [[ -n "$satir" ]] && cidr_gecerli "$satir" && echo "set_real_ip_from $satir;"; done < "$ARALIK_DOSYA"
    } > "$IPS_CONF.tmp"
    {
        echo '# Cloudflare uç aralıkları -> 1 (geo haritası). Elle düzenlemeyin.'
        while IFS= read -r satir; do [[ -n "$satir" ]] && cidr_gecerli "$satir" && echo "$satir 1;"; done < "$ARALIK_DOSYA"
    } > "$GEO_CONF.tmp"
    mv -f -- "$IPS_CONF.tmp" "$IPS_CONF"; mv -f -- "$GEO_CONF.tmp" "$GEO_CONF"
    chmod 644 "$IPS_CONF" "$GEO_CONF"
}

# Çözülen adres Cloudflare aralığında mı? Çıktı: cloudflare | sunucu | baska
adres_sinifi() {
    local liste="$ARALIK_DOSYA" gecici=''
    if [[ ! -s "$liste" ]]; then gecici="$(mktemp)"; cf_gomulu_araliklar > "$gecici"; liste="$gecici"; fi
    python3 -I - "$1" "$IP" "$liste" <<'PY'
import ipaddress, sys
adres, sunucu, liste = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    a = ipaddress.ip_address(adres)
except ValueError:
    print("baska"); sys.exit(0)
if adres == sunucu:
    print("sunucu"); sys.exit(0)
for satir in open(liste, encoding="utf-8"):
    satir = satir.strip()
    if not satir:
        continue
    try:
        if a in ipaddress.ip_network(satir, strict=False):
            print("cloudflare"); sys.exit(0)
    except ValueError:
        pass
print("baska")
PY
    [[ -n "$gecici" ]] && rm -f -- "$gecici"
    return 0
}

nginx_t() {
    if [[ -n "$NGINX_T_ARGS" ]]; then "$NGINX_BIN" -t "${NGINX_T_DIZI[@]}"; else "$NGINX_BIN" -t; fi
}

nginx_test_ve_yukle() {
    if ! nginx_t >/dev/null 2>&1; then
        echo 'nginx yapılandırma denetimi başarısız:' >&2
        nginx_t 2>&1 | sed 's/^/   /' >&2 || true
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

# ---------------------------------------------------------------- --ip-guncelle
if (( IP_GUNCELLE )); then
    GECICI="$(mktemp)"; trap 'rm -f -- "$GECICI"' EXIT
    V4="$(curl -fsS --noproxy '*' --max-time 20 "$CF_URL_V4" 2>/dev/null || true)"
    V6="$(curl -fsS --noproxy '*' --max-time 20 "$CF_URL_V6" 2>/dev/null || true)"
    SAY4=0; SAY6=0; : > "$GECICI"
    while IFS= read -r satir; do [[ -n "$satir" ]] && cidr_gecerli "$satir" && [[ "$satir" == *.* ]] && { echo "$satir" >> "$GECICI"; SAY4=$((SAY4+1)); }; done <<<"$V4"
    while IFS= read -r satir; do [[ -n "$satir" ]] && cidr_gecerli "$satir" && [[ "$satir" == *:* ]] && { echo "$satir" >> "$GECICI"; SAY6=$((SAY6+1)); }; done <<<"$V6"
    if (( SAY4 < 5 || SAY6 < 3 )); then
        uyar "Cloudflare listesi indirilemedi ya da eksik (IPv4: $SAY4, IPv6: $SAY6). Mevcut/gömülü liste korunuyor."
        install -d -m 700 "$CF_DIR"
        [[ -s "$ARALIK_DOSYA" ]] || { cf_gomulu_araliklar > "$ARALIK_DOSYA"; chmod 600 "$ARALIK_DOSYA"; }
        cf_dosyalarini_uret
        bilgi "IP_LISTESI_KORUNDU: $ARALIK_DOSYA ($(grep -c . "$ARALIK_DOSYA") aralık)"
        exit 0
    fi
    install -d -m 700 "$CF_DIR"
    if [[ -s "$ARALIK_DOSYA" ]] && cmp -s "$GECICI" "$ARALIK_DOSYA"; then
        bilgi "IP_LISTESI_GUNCEL: $ARALIK_DOSYA değişmedi ($((SAY4+SAY6)) aralık)."
        cf_dosyalarini_uret
        exit 0
    fi
    [[ -s "$ARALIK_DOSYA" ]] && cp -p -- "$ARALIK_DOSYA" "$ARALIK_DOSYA.before-$(date +%Y%m%d-%H%M%S)"
    install -m 600 "$GECICI" "$ARALIK_DOSYA"
    cf_dosyalarini_uret
    if [[ -f "$CONF" ]]; then
        if (( DRY_RUN )); then
            bilgi 'DRY-RUN: liste dosyaları yazıldı, nginx yeniden yüklenmedi.'
        else
            nginx_test_ve_yukle || fatal "Yeni liste nginx denetiminden geçmedi; eski liste: $ARALIK_DOSYA.before-*"
        fi
    fi
    bilgi "IP_LISTESI_GUNCELLENDI: $ARALIK_DOSYA (IPv4: $SAY4, IPv6: $SAY6)."
    exit 0
fi

# ---------------------------------------------------------------- --kaldir
if (( KALDIR )); then
    [[ -f "$CONF" ]] || fatal "Kaldırılacak dosya yok: $CONF"
    rm -f -- "$CONF"
    if nginx_t >/dev/null 2>&1; then
        "$SYSTEMCTL" reload "$NGINX_SERVICE" 2>&1 | grep -v 'signal process started' >&2 || true
        bilgi "Alan adı yapılandırması kaldırıldı ($CONF)."
        bilgi "Sertifika dosyaları silinmedi: $CF_DIR (gerekirse elle: rm -f $CF_DIR/ALAN.pem $CF_DIR/ALAN.key)."
    else
        fatal 'nginx yapılandırması dosya kaldırıldıktan sonra bile hatalı; Plesk nginx yeniden yüklenmedi. Çıktıyı paylaşın.'
    fi
    exit 0
fi

# ---------------------------------------------------------------- girdi
[[ -n "$HOST" ]] || { sed -n '2,10p' "$0"; fatal 'Alan adı gerekli (örnek: panel.alanadi.com).'; }
HOST="$(LC_ALL=C tr '[:upper:]' '[:lower:]' <<<"$HOST")"
[[ "$HOST" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$ ]] || fatal "Alan adı geçersiz görünüyor: $HOST (örnek: panel.alanadi.com)"
if [[ -n "$SERT_DOSYA" || -n "$ANAHTAR_DOSYA" ]]; then
    [[ -n "$SERT_DOSYA" && -n "$ANAHTAR_DOSYA" ]] || fatal '--sertifika ve --anahtar birlikte verilmeli.'
    [[ -r "$SERT_DOSYA" ]] || fatal "Sertifika dosyası okunamıyor: $SERT_DOSYA"
    [[ -r "$ANAHTAR_DOSYA" ]] || fatal "Anahtar dosyası okunamıyor: $ANAHTAR_DOSYA"
    (( OZ_IMZALI )) && fatal '--oz-imzali ile --sertifika birlikte kullanılmaz.'
fi
PEM="$CF_DIR/$HOST.pem"
KEYF="$CF_DIR/$HOST.key"

# ---------------------------------------------------------------- ön kontrol
bilgi "Kanıt Paneli — Cloudflare arkasında alan adı kurulumu: $HOST"
[[ -e "$CONF" ]] && fatal "$CONF zaten var. Yeniden kurmak için önce: bash deploy/setup-cloudflare-https.sh --kaldir  (setup-domain-https.sh kurulumu da aynı dosyayı kullanır)"
"$SYSTEMCTL" is-active --quiet "$NGINX_SERVICE" || fatal "Plesk'in nginx servisi ($NGINX_SERVICE) çalışmıyor; önce 'systemctl start nginx' ile açın."
nginx_t >/dev/null 2>&1 || fatal 'Mevcut nginx yapılandırması zaten hatalı (nginx -t). Hiçbir şey değiştirilmedi; "nginx -t" çıktısını paylaşın.'
[[ "$(curl -fsS --noproxy '*' --connect-timeout 5 --max-time 10 "$PANEL_URL/saglik" 2>/dev/null || true)" == 'OK' ]] \
    || fatal "Panel iç sağlık kontrolü başarısız ($PANEL_URL/saglik). Önce 'systemctl status kanit-web' çıktısına bakın."
if "$NGINX_BIN" -V 2>&1 | grep -q -- '--with-http_realip_module'; then :; else
    fatal 'Bu nginx http_realip_module olmadan derlenmiş; gerçek ziyaretçi IP alınamaz. nginx -V çıktısını paylaşın.'
fi

# DNS: alan adı Cloudflare'a (turuncu bulut) çözülmeli.
COZUM="${KANIT_COZUM-$(getent ahosts "$HOST" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ' | sed 's/ $//' || true)}"
DNS_DURUM='yok'
if [[ -z "$COZUM" ]]; then
    uyar "$HOST şu an çözülmüyor (DNS yayılması sürüyor olabilir). Kurulum devam eder; Cloudflare DNS'te A kaydı panel -> $IP, bulut TURUNCU olmalı."
else
    DNS_DURUM='cloudflare'
    for adres in $COZUM; do
        case "$(adres_sinifi "$adres")" in
            cloudflare) bilgi "DNS: $HOST -> $adres (Cloudflare ucu; turuncu bulut ✓)" ;;
            sunucu) DNS_DURUM='sunucu'; uyar "$HOST doğrudan $adres adresine çözülüyor: bulut GRİ. Bu betik TURUNCU bulut içindir; ya Cloudflare'da bulutu turuncu yapın ya da setup-domain-https.sh (Let's Encrypt) kullanın. Kurulum yine de devam eder; gri bulutta ziyaretçiler 403 alır (--herkese-acik hariç)." ;;
            *) DNS_DURUM='baska'; uyar "$HOST şu an $adres adresine çözülüyor; bu ne Cloudflare ne de bu sunucu. DNS kaydını kontrol edin." ;;
        esac
    done
fi

# nginx >= 1.25.1 ise "http2 on;" yönergesi, daha eskisinde "listen ... ssl http2;" kullanılır.
nginx_http2_yonergesi_var() {
    local surum maj min pat
    surum="$("$NGINX_BIN" -v 2>&1 | sed -nE 's#.*nginx/([0-9]+\.[0-9]+\.[0-9]+).*#\1#p')"
    [[ -n "$surum" ]] || return 1
    IFS=. read -r maj min pat <<<"$surum"
    (( maj > 1 || (maj == 1 && (min > 25 || (min == 25 && pat >= 1))) ))
}

# ---------------------------------------------------------------- sertifika
sertifika_dogrula() { # pem key -> 0 geçerli; hata metni stderr
    local pem="$1" key="$2" p1 p2
    openssl x509 -in "$pem" -noout >/dev/null 2>&1 || { echo 'sertifika PEM olarak okunamadı' >&2; return 1; }
    openssl x509 -in "$pem" -noout -checkend 86400 >/dev/null 2>&1 || { echo "sertifikanın süresi dolmuş/doluyor (bitiş: $(openssl x509 -in "$pem" -noout -enddate 2>/dev/null | cut -d= -f2))" >&2; return 1; }
    openssl pkey -in "$key" -noout >/dev/null 2>&1 || { echo 'özel anahtar PEM olarak okunamadı' >&2; return 1; }
    p1="$(openssl x509 -in "$pem" -noout -pubkey 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1)"
    p2="$(openssl pkey -in "$key" -pubout -outform DER 2>/dev/null | sha256sum | cut -d' ' -f1)"
    [[ -n "$p1" && "$p1" == "$p2" ]] || { echo 'sertifika ile özel anahtar eşleşmiyor' >&2; return 1; }
    return 0
}
san_uyari() {
    local san ust
    san="$(openssl x509 -in "$1" -noout -ext subjectAltName 2>/dev/null || true)"
    ust="${HOST#*.}"
    if ! grep -Eq "DNS:$HOST([^a-z0-9.-]|$)|DNS:\*\.$ust([^a-z0-9.-]|$)" <<<"$san"; then
        uyar "Sertifika $HOST adını kapsamıyor görünüyor (SAN: ${san:-yok}). Cloudflare 'Full (strict)' modunda origin reddedilir; 'Full' ile çalışır."
    fi
}
sertifika_yaz() { # pem_kaynak key_kaynak
    install -d -m 700 "$CF_DIR"
    install -m 600 -o root -g root "$1" "$PEM"
    install -m 600 -o root -g root "$2" "$KEYF"
}
oz_imzali_uret() {
    install -d -m 700 "$CF_DIR"
    openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 -subj "/CN=$HOST" -addext "subjectAltName=DNS:$HOST" \
        -keyout "$KEYF.tmp" -out "$PEM.tmp" >/dev/null 2>&1 || fatal 'Öz imzalı sertifika üretilemedi (openssl req).'
    chmod 600 "$KEYF.tmp" "$PEM.tmp"
    mv -f -- "$PEM.tmp" "$PEM"; mv -f -- "$KEYF.tmp" "$KEYF"
}

SERT_MOD=''   # origin | oz-imzali
if [[ -n "$SERT_DOSYA" ]]; then
    sertifika_dogrula "$SERT_DOSYA" "$ANAHTAR_DOSYA" || fatal "Verilen sertifika/anahtar geçersiz (yukarıdaki neden). Cloudflare Origin Server ekranından iki bloğu yeniden kopyalayın."
    SERT_MOD='origin'
    (( DRY_RUN )) || sertifika_yaz "$SERT_DOSYA" "$ANAHTAR_DOSYA"
    bilgi "Sertifika: verilen dosyalar -> $PEM, $KEYF (bitiş: $(openssl x509 -in "$SERT_DOSYA" -noout -enddate | cut -d= -f2))"
    san_uyari "$SERT_DOSYA"
elif [[ -r "$PEM" && -r "$KEYF" ]] && sertifika_dogrula "$PEM" "$KEYF" 2>/dev/null; then
    if openssl x509 -in "$PEM" -noout -issuer 2>/dev/null | grep -qi 'cloudflare'; then SERT_MOD='origin'; else SERT_MOD='oz-imzali'; fi
    bilgi "Sertifika: mevcut $PEM kullanılıyor ($SERT_MOD; bitiş: $(openssl x509 -in "$PEM" -noout -enddate | cut -d= -f2))"
    san_uyari "$PEM"
elif (( OZ_IMZALI )) || [[ ! -t 0 ]]; then
    SERT_MOD='oz-imzali'
    if (( DRY_RUN )); then bilgi "Sertifika: 10 yıllık öz imzalı üretilecek -> $PEM"; else oz_imzali_uret; bilgi "Sertifika: 10 yıllık öz imzalı üretildi -> $PEM (Cloudflare SSL modu: Full)"; fi
else
    read -r -p 'Cloudflare Origin CA sertifikanız hazır mı? (e = yapıştıracağım / H = öz imzalı üret) ' CEVAP || CEVAP=''
    if [[ "$CEVAP" =~ ^[eEyY] ]]; then
        TMP_PEM="$(mktemp)"; TMP_KEY="$(mktemp)"; chmod 600 "$TMP_PEM" "$TMP_KEY"
        trap 'rm -f -- "$TMP_PEM" "$TMP_KEY"' EXIT
        printf '\nORIGIN CERTIFICATE bloğunu yapıştırın (-----BEGIN CERTIFICATE----- ... -----END CERTIFICATE-----), bitince yeni satırda Ctrl+D:\n'
        cat > "$TMP_PEM"
        printf '\nPRIVATE KEY bloğunu yapıştırın (-----BEGIN PRIVATE KEY----- ... -----END PRIVATE KEY-----), bitince yeni satırda Ctrl+D:\n'
        cat > "$TMP_KEY"
        sertifika_dogrula "$TMP_PEM" "$TMP_KEY" || fatal 'Yapıştırılan sertifika/anahtar geçersiz (yukarıdaki neden). Hiçbir şey değiştirilmedi; yeniden deneyin.'
        SERT_MOD='origin'
        (( DRY_RUN )) || sertifika_yaz "$TMP_PEM" "$TMP_KEY"
        bilgi "Sertifika: Origin CA kaydedildi -> $PEM (bitiş: $(openssl x509 -in "$TMP_PEM" -noout -enddate | cut -d= -f2))"
        san_uyari "$TMP_PEM"
        rm -f -- "$TMP_PEM" "$TMP_KEY"; trap - EXIT
    else
        SERT_MOD='oz-imzali'
        if (( DRY_RUN )); then bilgi "Sertifika: 10 yıllık öz imzalı üretilecek -> $PEM"; else oz_imzali_uret; bilgi "Sertifika: 10 yıllık öz imzalı üretildi -> $PEM (Cloudflare SSL modu: Full)"; fi
    fi
fi
if [[ "$SERT_MOD" == 'origin' ]]; then CF_SSL_MODU='Full (strict)'; else CF_SSL_MODU='Full'; fi

if nginx_http2_yonergesi_var; then HTTP2_NOT='http2 on; (nginx >= 1.25.1)'; else HTTP2_NOT='listen ... ssl http2; (nginx < 1.25.1)'; fi
bilgi "Ön kontrol tamam: nginx temiz, panel sağlıklı, DNS: $DNS_DURUM, HTTP/2: $HTTP2_NOT"
bilgi "Yazılacak: $CONF (yalnız $HOST), $IPS_CONF, $GEO_CONF; erişim: $( (( HERKESE_ACIK )) && echo 'herkese açık (--herkese-acik)' || echo 'yalnız Cloudflare uçları + bu sunucu')"
bilgi "Dokunulmayacak: Plesk vhost dosyaları, Apache, posta, güvenlik duvarı, kanit-ip-proxy (IP:18443)."
if (( DRY_RUN )); then
    bilgi 'DRY-RUN_TAMAM: Yalnız kontrol yapıldı; nginx, sertifika dosyaları ve servisler değiştirilmedi.'
    exit 0
fi

# ---------------------------------------------------------------- değişiklikler
CONF_WRITTEN=0
rollback() {
    local code="$1"
    trap - ERR INT TERM
    set +e
    echo "KURULUM_HATASI [$code] — bu betiğin yazdığı nginx dosyası geri alınıyor." >&2
    if (( CONF_WRITTEN )) && [[ -f "$CONF" ]]; then
        rm -f -- "$CONF"
        if nginx_t >/dev/null 2>&1; then "$SYSTEMCTL" reload "$NGINX_SERVICE" >/dev/null 2>&1 || true; fi
    fi
    echo "Plesk siteleri, panel verileri ve IP:18443 erişimi değiştirilmedi. Sertifika dosyaları ($CF_DIR) yeniden kullanılmak üzere bırakıldı. Hata çıktısını paylaşın." >&2
    exit "$code"
}
trap 'rollback "$?"' ERR
trap 'rollback 130' INT
trap 'rollback 143' TERM
fatal() { echo "DUR: $*" >&2; rollback 1; }

cf_dosyalarini_uret

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

conf_uret() {
    local listen_blok erisim_blok
    if nginx_http2_yonergesi_var; then
        listen_blok="    listen $IP:$HTTPS_PORT ssl;
    http2 on;"
    else
        listen_blok="    listen $IP:$HTTPS_PORT ssl http2;"
    fi
    if (( HERKESE_ACIK )); then
        erisim_blok='    # --herkese-acik: Cloudflare dışından gelen istekler de kabul edilir.'
    else
        erisim_blok='    # Cloudflare uçları (ve bu sunucunun kendisi) dışından gelen istek: Cloudflare atlanmış demektir -> 403.
    if ($kanit_cf_kaynak = 0) { return 403; }'
    fi
    local sunucu_satiri=''
    [[ "$IP" != '127.0.0.1' ]] && sunucu_satiri="    $IP 1;"
    cat <<NGINX
# Kanıt Paneli — $HOST, Cloudflare (turuncu bulut) arkasında. deploy/setup-cloudflare-https.sh yazdı; Plesk üretmez, Plesk ezmez.
# Bu dosya Plesk nginx.conf'un http{} bağlamına dahil edilir; zone ve geo tanımları burada geçerlidir.
limit_req_zone \$binary_remote_addr zone=kanit_giris:1m rate=10r/m;
# Bağlantının GERÇEK karşı ucu (real_ip öncesi) Cloudflare aralığında mı? 127.0.0.1 ve sunucunun kendisi yerel kontroller için.
geo \$realip_remote_addr \$kanit_cf_kaynak {
    default 0;
    127.0.0.1 1;
${sunucu_satiri:+$sunucu_satiri
}    include $GEO_CONF;
}
server {
    listen $IP:$HTTP_PORT;
    server_name $HOST;
    location / {
        return 301 https://\$host\$request_uri;
    }
}
server {
$listen_blok
    server_name $HOST;
    ssl_certificate $PEM;
    ssl_certificate_key $KEYF;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_ciphers $TLS_CIPHERS;
    ssl_ecdh_curve X25519:prime256v1:secp384r1;
    ssl_session_cache shared:KANIT_CF_TLS:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;
    server_tokens off;
    client_max_body_size 64m;
    client_body_timeout 60s;
    keepalive_timeout 30s;
    # Gerçek ziyaretçi IP'si: yalnız Cloudflare uçlarından gelen CF-Connecting-IP başlığına güvenilir.
    include $IPS_CONF;
    real_ip_header CF-Connecting-IP;
    real_ip_recursive on;
$erisim_blok
    # Giriş: dakikada 10 deneme, 10 ani istek toleransı; fazlası 429 (gerçek ziyaretçi IP'sine göre).
    location = /giris {
        limit_req zone=kanit_giris burst=10 nodelay;
        limit_req_status 429;
$(proxy_basliklari)
    }
    # Her istek panelin kendi giriş ve yetki kontrolünden geçer; güvenlik başlıklarını uygulama verir (çift başlık yok).
    location / {
$(proxy_basliklari)
    }
}
NGINX
}

CONF_WRITTEN=1
conf_uret > "$CONF"
chmod 644 "$CONF"
nginx_test_ve_yukle
bilgi "1/3 nginx dosyası yazıldı ve yeniden yüklendi: $CONF"

# 2/3 Origin (yerel) kontrolü: Cloudflare'ı beklemeden sunucunun kendi bloğu doğrulanır.
if (( KONTROL_ATLA )); then
    bilgi '2/3 Yerel origin kontrolü atlandı (--kontrol-atla).'
else
    DINLEYENLER="$(ss -lntH 2>/dev/null | awk '{print $4}' || true)"
    HEDEF=''
    if grep -qE "^(127\.0\.0\.1|0\.0\.0\.0|\*|\[::\]):$HTTPS_PORT$" <<<"$DINLEYENLER"; then HEDEF='127.0.0.1';
    elif grep -qE "^${IP//./\\.}:$HTTPS_PORT$" <<<"$DINLEYENLER"; then HEDEF="$IP"; fi
    if [[ -z "$HEDEF" ]]; then
        bilgi "2/3 Yerel origin kontrolü atlandı: $HTTPS_PORT portunda yerelden erişilebilir dinleyici görülmedi (ss -lnt). Cloudflare üzerinden kontrol aşağıda."
    else
        # shellcheck disable=SC2086
        SONUC="$(curl -sS --noproxy '*' -k $CURL_EXTRA --retry 10 --retry-connrefused --retry-delay 1 --connect-timeout 5 --max-time 10 \
            --resolve "$HOST:$HTTPS_PORT:$HEDEF" -o /dev/stdout -w '\n%{http_code}' "https://$HOST:$HTTPS_PORT/saglik" 2>&1 || true)"
        KOD="${SONUC##*$'\n'}"; GOVDE="${SONUC%$'\n'*}"
        if [[ "$KOD" == '200' && "$GOVDE" == 'OK' ]]; then
            bilgi "2/3 Yerel origin kontrolü: https://$HOST/saglik ($HEDEF üzerinden) -> OK"
        elif [[ "$KOD" == '403' ]]; then
            fatal "Yerel origin kontrolü 403 verdi: istek $HEDEF kaynağından geldi ama geo izin listesine düşmedi. nginx -T | grep -A4 kanit_cf_kaynak çıktısını paylaşın (geçici çözüm: --herkese-acik ya da --kontrol-atla)."
        else
            fatal "Yerel origin kontrolü beklenen OK vermedi (HTTP ${KOD:-?}; yanıt: ${GOVDE:0:120}). Plesk nginx bu alan adı için bizim bloğu seçmiyor olabilir; 'nginx -T | grep -n server_name' çıktısını paylaşın (--kontrol-atla ile geçilebilir)."
        fi
    fi
fi

# 3/3 Cloudflare üzerinden (gerçek DNS): yayılmadıysa yalnız uyarı.
CF_SONUC="$(curl -sS --noproxy '*' --connect-timeout 8 --max-time 15 "https://$HOST/saglik" 2>/dev/null || true)"
if [[ "$CF_SONUC" == 'OK' ]]; then
    bilgi "3/3 Cloudflare üzerinden kontrol: https://$HOST/saglik -> OK"
    CF_DURUM='OK'
else
    uyar "3/3 https://$HOST/saglik Cloudflare üzerinden henüz OK vermedi (yanıt: ${CF_SONUC:-yok}). DNS yayılmamış, bulut gri ya da SSL modu yanlış olabilir; aşağıdaki Cloudflare adımlarını tamamlayıp 5-10 dk sonra şunu deneyin: curl -s https://$HOST/saglik"
    CF_DURUM='BEKLIYOR'
fi

trap - ERR INT TERM
bilgi ''
bilgi "CLOUDFLARE_HTTPS_TAMAM ($CF_DURUM)"
bilgi "Tarayıcı adresi: https://$HOST  (eski görünüm kalırsa Ctrl+F5)"
bilgi "Sertifika: $SERT_MOD, bitiş $(openssl x509 -in "$PEM" -noout -enddate | cut -d= -f2) -> Cloudflare SSL/TLS modu: $CF_SSL_MODU"
bilgi ''
bilgi 'Cloudflare panelinde yapılacak 4 şey:'
bilgi "  1. DNS -> Records: A kaydı  ${HOST%%.*}  ->  $IP , Proxy status: Proxied (TURUNCU bulut)."
bilgi "  2. SSL/TLS -> Overview: şifreleme modu  $CF_SSL_MODU ."
bilgi '  3. SSL/TLS -> Edge Certificates: Always Use HTTPS = On.'
if [[ "$SERT_MOD" == 'origin' ]]; then
    bilgi '  4. SSL/TLS -> Origin Server: sertifika zaten kayıtlı (15 yıl; yenileme gerekmez).'
else
    bilgi "  4. (İsteğe bağlı, önerilir) SSL/TLS -> Origin Server -> Create Certificate (RSA 2048, 15 yıl, hostname $HOST) -> iki bloğu kaydedip:"
    bilgi "     bash deploy/setup-cloudflare-https.sh --kaldir && bash deploy/setup-cloudflare-https.sh $HOST --sertifika origin.pem --anahtar origin.key ; sonra modu Full (strict) yapın."
fi
bilgi ''
bilgi "Alan adı çalışınca IP yolu emekli edilebilir: systemctl disable --now kanit-ip-proxy  (dolmuş IP sertifikalı 18443 kapanır)."
bilgi "Kaldırmak için: bash deploy/setup-cloudflare-https.sh --kaldir ; IP listesini tazelemek için: --ip-guncelle"
