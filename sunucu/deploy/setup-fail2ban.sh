#!/usr/bin/env bash
# Kanıt Paneli — mevcut fail2ban'a (Plesk'in kurduğu) kanit-web jail'ini ekler. sshd/Plesk jail'lerine dokunmaz.
#
#   bash deploy/setup-fail2ban.sh [--dry-run]    # filter.d/kanit-web.conf + jail.d/kanit-web.local, sonra fail2ban-client reload
#   bash deploy/setup-fail2ban.sh --kur          # fail2ban kurulu değilse apt-get ile kurar (python3-systemd dahil)
#
# Önkoşul: uygulama güncellemesi (apply-update.sh) ve sertleştirilmiş kanit-web.service (SyslogIdentifier=kanit-web).
# NOT: Cloudflare (turuncu bulut) arkasında bu jail etkisizdir; yalnız IP yolu (18443) açıkken anlamlıdır. Ayrıntı: jail dosyası.
set -Eeuo pipefail
IFS=$'\n\t'
F2B_DIR="${KANIT_F2B_DIR:-/etc/fail2ban}"
F2B_CLIENT="${KANIT_F2B_CLIENT:-fail2ban-client}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
SRC_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)/fail2ban"
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi

DRY_RUN=0; KUR=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --kur) KUR=1 ;;
        -h|--help|--yardim) sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $arg (--yardim)" >&2; exit 2 ;;
    esac
done
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }
[[ ${EUID} -eq 0 ]] || fail 'Root oturumu gerekli.'
[[ -r "$SRC_DIR/kanit-web.conf" && -r "$SRC_DIR/jail-kanit.conf" ]] || fail "Kaynak dosyalar yok: $SRC_DIR/{kanit-web.conf,jail-kanit.conf}"

if ! command -v "$F2B_CLIENT" >/dev/null 2>&1; then
    if (( KUR )) && (( ! DRY_RUN )); then
        bilgi 'fail2ban kurulu değil; apt-get ile kuruluyor (python3-systemd ile).'
        DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban python3-systemd
    else
        fail 'fail2ban-client bulunamadı. Kurmak için: bash deploy/setup-fail2ban.sh --kur  (ya da apt-get install -y fail2ban python3-systemd)'
    fi
fi
if ! python3 -c 'import systemd.journal' >/dev/null 2>&1; then
    if (( KUR )) && (( ! DRY_RUN )); then
        DEBIAN_FRONTEND=noninteractive apt-get install -y python3-systemd
    else
        bilgi 'UYARI: python3-systemd eksik görünüyor; backend=systemd jail başlamaz. Kurmak için: apt-get install -y python3-systemd (ya da --kur).'
    fi
fi

FILTER="$F2B_DIR/filter.d/kanit-web.conf"
JAIL="$F2B_DIR/jail.d/kanit-web.local"
install -d -m 755 "$F2B_DIR/filter.d" "$F2B_DIR/jail.d"
DEGISTI=0
for pair in "$SRC_DIR/kanit-web.conf:$FILTER" "$SRC_DIR/jail-kanit.conf:$JAIL"; do
    src="${pair%%:*}"; dst="${pair#*:}"
    if [[ -f "$dst" ]] && cmp -s "$src" "$dst"; then
        bilgi "Güncel: $dst"
        continue
    fi
    DEGISTI=1
    if (( DRY_RUN )); then
        bilgi "Yazılacak: $dst"
        [[ -f "$dst" ]] && { diff -u "$dst" "$src" | sed 's/^/   /' || true; }
    else
        [[ -f "$dst" ]] && cp -p -- "$dst" "$dst.before-$(date +%Y%m%d-%H%M%S)"
        install -m 644 -o root -g root "$src" "$dst"
        bilgi "Yazıldı: $dst"
    fi
done

# Filtre kendini doğrular (fail2ban-regex varsa).
if command -v fail2ban-regex >/dev/null 2>&1; then
    ORNEK='Nov 23 19:00:00 sunucu kanit-web[1234]: kanit-web GIRIS_HATA ip=203.0.113.5 kullanici=admin'
    KAYNAK="$SRC_DIR/kanit-web.conf"
    if fail2ban-regex "$ORNEK" "$KAYNAK" 2>/dev/null | grep -qE '^Lines: 1 lines, 0 ignored, 1 matched'; then
        bilgi 'Filtre denemesi: örnek satır eşleşti.'
    else
        fail 'Filtre denemesi başarısız: örnek satır eşleşmedi; dosya değiştirilmiş olabilir.'
    fi
fi

if (( DRY_RUN )); then
    bilgi 'DRY-RUN_TAMAM: fail2ban dosyaları ve servisi değiştirilmedi.'
    exit 0
fi

if "$SYSTEMCTL" is-active --quiet fail2ban 2>/dev/null; then
    if (( DEGISTI )); then
        "$F2B_CLIENT" reload >/dev/null || fail 'fail2ban-client reload başarısız; "fail2ban-client -d" ve journalctl -u fail2ban çıktısını paylaşın.'
        bilgi 'fail2ban yeniden yüklendi.'
    fi
else
    if (( KUR )); then
        "$SYSTEMCTL" enable --now fail2ban
    else
        fail 'fail2ban servisi çalışmıyor; dosyalar yazıldı ama jail etkin değil. Başlatmak için: systemctl enable --now fail2ban (ya da --kur).'
    fi
fi
sleep 1
if "$F2B_CLIENT" status kanit-web >/dev/null 2>&1; then
    "$F2B_CLIENT" status kanit-web | sed 's/^/   /'
    bilgi 'FAIL2BAN_TAMAM: kanit-web jail etkin (10 hata / 10 dk -> 1 saat; portlar 18443,443).'
else
    fail 'kanit-web jail durumu alınamadı. journalctl -u fail2ban -n 30 çıktısını paylaşın (python3-systemd eksikliği en sık sebeptir).'
fi
bilgi 'Not: Cloudflare arkasında bu engel etkisizdir; asıl koruma uygulama kilidi + nginx limit_req katmanıdır (README).'
