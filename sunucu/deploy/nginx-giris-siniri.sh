#!/usr/bin/env bash
# Kanıt Paneli — mevcut IP proxy nginx.conf'una (/opt/kanit-ssl/nginx.conf) giriş sınırı ve TLS satırlarını ekler.
#
#   bash deploy/nginx-giris-siniri.sh [--dry-run]
#
# Yaptığı (hepsi idempotent; zaten varsa dokunmaz):
#   - http{} içine: limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m; limit_req_status 429;
#   - server{} içine: location = /giris { limit_req zone=kanit_giris burst=10 nodelay; ...mevcut proxy satırları... }
#   - TLS: ssl_prefer_server_ciphers off; ssl_ciphers (Mozilla intermediate, yalnız ECDHE); ssl_ecdh_curve;
#     ssl_session_timeout 1d; HTTP/2 (nginx sürümüne göre "http2 on;" ya da "listen ... ssl http2;")
#   - client_max_body_size 12m -> 64m (uygulama sınırıyla uyumlu)
# Önce yeni dosya geçici konumda "nginx -t" ile denenir; eski dosya yedeklenir; sonra kanit-ip-proxy yeniden yüklenir.
# Yeniden yükleme başarısızsa eski dosya geri konur. Plesk'in nginx'ine dokunmaz.
set -Eeuo pipefail
IFS=$'\n\t'
BASE="${KANIT_SSL_BASE:-/opt/kanit-ssl}"
CONF="${KANIT_CONF:-$BASE/nginx.conf}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
SERVICE='kanit-ip-proxy.service'
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help|--yardim) sed -n '2,14p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $arg (--yardim)" >&2; exit 2 ;;
    esac
done
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID} -eq 0 ]] || fail 'Root oturumu gerekli.'
NGINX="$(command -v nginx)" || fail 'nginx bulunamadı.'
command -v python3 >/dev/null 2>&1 || fail 'python3 bulunamadı.'
[[ -f "$CONF" ]] || fail "$CONF yok; IP proxy kurulumu bulunamadı (deploy/setup-ip-https.sh)."

HTTP2_MOD='listen'
if "$NGINX" -v 2>&1 | sed -nE 's#.*nginx/([0-9]+\.[0-9]+\.[0-9]+).*#\1#p' | {
    IFS=. read -r maj min pat || true
    [[ -n "${maj:-}" ]] && (( maj > 1 || (maj == 1 && (min > 25 || (min == 25 && pat >= 1))) ))
}; then HTTP2_MOD='directive'; fi

YENI="$(mktemp "$BASE/.nginx.conf.yeni.XXXXXX")"
trap 'rm -f -- "$YENI"' EXIT
chmod 600 "$YENI"
python3 - "$CONF" "$YENI" "$HTTP2_MOD" <<'PY'
import re
import sys

src, dst, http2_mod = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(src, encoding="utf-8").read()
orig = text
CIPHERS = ("ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:"
           "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305")
notes = []

def insert_after(pattern, addition, label):
    global text
    m = re.search(pattern, text, re.M)
    if not m:
        sys.exit(f"HATA: beklenen satır bulunamadı ({label}); dosya bu betiğin tanıdığı biçimde değil.")
    end = text.index("\n", m.end()) + 1
    text = text[:end] + addition + text[end:]

# 1) http{} içinde zone tanımı (server_tokens off; satırından sonra)
if "limit_req_zone" not in text:
    insert_after(r"^\s*server_tokens off;\s*$",
                 "    # Giriş denemeleri için istemci IP'si başına kenar sınırı (uygulamanın kendi kilidine ek).\n"
                 "    limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m;\n"
                 "    limit_req_status 429;\n", "server_tokens off")
    notes.append("limit_req_zone eklendi")

# 2) location = /giris bloğu: mevcut location / içindeki proxy satırları kopyalanır
if "location = /giris" not in text:
    m = re.search(r"^(\s*)location / \{\n(.*?)^\1\}\n", text, re.M | re.S)
    if not m:
        sys.exit("HATA: 'location / {' bloğu bulunamadı; dosya bu betiğin tanıdığı biçimde değil.")
    indent, body = m.group(1), m.group(2)
    block = (f"{indent}# Giriş: dakikada 10 deneme, 10 ani istek toleransı; fazlası 429.\n"
             f"{indent}location = /giris {{\n{indent}    limit_req zone=kanit_giris burst=10 nodelay;\n{body}{indent}}}\n")
    start = m.start()
    # "location /" üstündeki açıklama satırı ona ait kalsın; yeni blok açıklamanın üstüne girer.
    prev_start = text.rfind("\n", 0, start - 1) + 1
    if text[prev_start:start].strip().startswith("#"):
        start = prev_start
    text = text[:start] + block + text[start:]
    notes.append("location = /giris eklendi")

# 3) TLS satırları
if "ssl_ciphers" not in text:
    insert_after(r"^\s*ssl_protocols .*;$",
                 f"        ssl_prefer_server_ciphers off;\n        ssl_ciphers {CIPHERS};\n"
                 "        ssl_ecdh_curve X25519:prime256v1:secp384r1;\n", "ssl_protocols")
    notes.append("ssl_ciphers/ssl_prefer_server_ciphers/ssl_ecdh_curve eklendi")
if re.search(r"^\s*ssl_session_timeout 1h;", text, re.M):
    text = re.sub(r"^(\s*)ssl_session_timeout 1h;", r"\1ssl_session_timeout 1d;", text, flags=re.M)
    notes.append("ssl_session_timeout 1d")
if re.search(r"^\s*client_max_body_size 12m;", text, re.M):
    text = re.sub(r"^(\s*)client_max_body_size 12m;", r"\1client_max_body_size 64m;", text, flags=re.M)
    notes.append("client_max_body_size 64m")

# 4) HTTP/2
if "http2" not in text:
    m = re.search(r"^(\s*)listen ([^;]*\bssl)\s*;\s*$", text, re.M)
    if not m:
        sys.exit("HATA: 'listen ... ssl;' satırı bulunamadı; dosya bu betiğin tanıdığı biçimde değil.")
    if http2_mod == "directive":
        text = text[:m.end()] + f"\n{m.group(1)}http2 on;" + text[m.end():]
    else:
        text = text[:m.start()] + f"{m.group(1)}listen {m.group(2)} http2;" + text[m.end():]
    notes.append("HTTP/2 açıldı")

open(dst, "w", encoding="utf-8").write(text)
if text == orig:
    print("DEGISIKLIK_YOK")
else:
    print("DEGISIKLIKLER: " + "; ".join(notes))
PY

if cmp -s "$CONF" "$YENI"; then
    printf 'NGINX_CONF_GUNCEL: %s zaten giriş sınırı ve TLS satırlarını içeriyor.\n' "$CONF"
    exit 0
fi
printf 'Fark (%s):\n' "$CONF"
diff -u "$CONF" "$YENI" | sed 's/^/   /' || true
# Yeni dosya önce geçici adıyla denenir (mutlak yollar kullanıldığı için -p ile aynı sonucu verir).
if ! "$NGINX" -t -p "$BASE/" -c "$YENI" >/dev/null 2>&1; then
    "$NGINX" -t -p "$BASE/" -c "$YENI" 2>&1 | sed 's/^/   /' >&2 || true
    fail 'Yeni nginx.conf denetimden geçmedi; mevcut dosya değiştirilmedi.'
fi
if (( DRY_RUN )); then
    printf 'DRY-RUN_TAMAM: nginx -t geçti; dosya ve servis değiştirilmedi.\n'
    exit 0
fi
YEDEK="$CONF.before-$(date +%Y%m%d-%H%M%S)"
cp -p -- "$CONF" "$YEDEK"
chmod 600 "$YENI"
mv -f -- "$YENI" "$CONF"
trap - EXIT
if "$SYSTEMCTL" is-active --quiet "$SERVICE" 2>/dev/null; then
    if ! "$SYSTEMCTL" reload "$SERVICE"; then
        printf 'Yeniden yükleme başarısız; eski dosya geri konuyor.\n' >&2
        cp -p -- "$YEDEK" "$CONF"
        "$SYSTEMCTL" reload "$SERVICE" || true
        fail "kanit-ip-proxy yeni yapılandırmayı yüklemedi. Yedek: $YEDEK"
    fi
    printf 'NGINX_CONF_GUNCELLENDI: %s yazıldı ve %s yeniden yüklendi. Eski dosya: %s\n' "$CONF" "$SERVICE" "$YEDEK"
else
    printf 'NGINX_CONF_GUNCELLENDI: %s yazıldı; %s çalışmıyor, yeniden yükleme yapılmadı. Eski dosya: %s\n' "$CONF" "$SERVICE" "$YEDEK"
fi
