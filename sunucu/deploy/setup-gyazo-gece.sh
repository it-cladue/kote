#!/usr/bin/env bash
# Kanıt Paneli — eski kayıtların Gyazo görsellerini geceleri sunucuya kopyalayan zamanlayıcıyı kurar (root).
#
#   bash deploy/setup-gyazo-gece.sh [--saat 22:30] [--bitis 07:30] [--gecelik 900] [--dilim Europe/Istanbul] [--dry-run] [--kaldir]
#
# Yaptığı: kanit-gyazo.service + kanit-gyazo.timer -> /etc/systemd/system; her gece --saat'te (+5 dk rastgele) başlar,
# gecede en çok --gecelik yeni indirme yapar, --bitis saatinde durur (mesai öncesi); kaldığı yerden devam eder.
# Gün içinde başlatılsa bile pencere dışında olduğunu görüp hiçbir şey yapmadan çıkar. Günlük: journalctl -u kanit-gyazo.
set -Eeuo pipefail
IFS=$'\n\t'
UNIT_DIR="${KANIT_UNIT_DIR:-/etc/systemd/system}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
KANIT_DIR="${KANIT_DIR:-/opt/kanit-paneli}"
SRC_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi
DRY_RUN=0; KALDIR=0; BASLANGIC='22:30'; BITIS='07:30'; GECELIK=900; DILIM='Europe/Istanbul'
while (( $# )); do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --kaldir) KALDIR=1 ;;
        --saat) shift; BASLANGIC="${1:-}" ;;
        --bitis) shift; BITIS="${1:-}" ;;
        --gecelik) shift; GECELIK="${1:-}" ;;
        --dilim) shift; DILIM="${1:-}" ;;
        -h|--help|--yardim) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $1 (--yardim)" >&2; exit 2 ;;
    esac
    shift
done
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }
[[ ${EUID} -eq 0 ]] || fail 'Root oturumu gerekli.'
[[ "$BASLANGIC" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || fail "--saat SS:DD biçiminde olmalı (örn. 22:30): $BASLANGIC"
[[ "$BITIS" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] || fail "--bitis SS:DD biçiminde olmalı (örn. 07:30): $BITIS"
[[ "$GECELIK" =~ ^[1-9][0-9]{0,4}$ ]] || fail "--gecelik 1-99999 arası tam sayı olmalı: $GECELIK"
[[ "$DILIM" =~ ^[A-Za-z_]+(/[A-Za-z_+-]+)*$ ]] || fail "--dilim geçersiz: $DILIM"
[[ -f "/usr/share/zoneinfo/$DILIM" ]] || bilgi "UYARI: /usr/share/zoneinfo/$DILIM yok; komut sunucu yerel saatini kullanır."

if (( KALDIR )); then
    if (( DRY_RUN )); then bilgi "Kaldırılacak: kanit-gyazo.timer, $UNIT_DIR/kanit-gyazo.{service,timer}"; bilgi 'DRY-RUN_TAMAM'; exit 0; fi
    "$SYSTEMCTL" disable --now kanit-gyazo.timer 2>/dev/null || true
    rm -f -- "$UNIT_DIR/kanit-gyazo.service" "$UNIT_DIR/kanit-gyazo.timer"
    "$SYSTEMCTL" daemon-reload
    bilgi 'GYAZO_GECE_KALDIRILDI: zamanlayıcı ve birimler silindi; indirilmiş kopyalar yerinde.'
    exit 0
fi
for f in kanit-gyazo.service kanit-gyazo.timer; do [[ -r "$SRC_DIR/$f" ]] || fail "Kaynak dosya yok: $SRC_DIR/$f"; done
[[ -x "$KANIT_DIR/.venv/bin/python" ]] || fail "Panel kurulumu bulunamadı: $KANIT_DIR/.venv/bin/python"
[[ -f "$KANIT_DIR/.env" ]] || fail "$KANIT_DIR/.env yok."
( cd "$KANIT_DIR" && "$KANIT_DIR/.venv/bin/python" -m app.cli gyazo-onbellekle --help ) >/dev/null 2>&1 || fail 'Kurulu panelde gyazo-onbellekle komutu yok; önce 2.3.1 güncellemesini uygulayın.'

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
uret() { sed -e "s#@KANIT_DIR@#$KANIT_DIR#g" -e "s#@BASLANGIC@#$BASLANGIC#g" -e "s#@BITIS@#$BITIS#g" -e "s#@GECELIK@#$GECELIK#g" -e "s#@DILIM@#$DILIM#g" "$1" > "$2"; }
uret "$SRC_DIR/kanit-gyazo.service" "$TMP/kanit-gyazo.service"
uret "$SRC_DIR/kanit-gyazo.timer" "$TMP/kanit-gyazo.timer"
grep -q '@' "$TMP/kanit-gyazo.service" && fail 'Birim şablonunda yer tutucu kaldı.'
yaz() { # kaynak hedef
    if [[ -f "$2" ]] && cmp -s "$1" "$2"; then bilgi "Güncel: $2"; return 0; fi
    if (( DRY_RUN )); then bilgi "Yazılacak: $2"; sed 's/^/   /' "$1"; return 0; fi
    install -d -m 755 "$(dirname -- "$2")"
    install -m 644 -o root -g root "$1" "$2"
    bilgi "Yazıldı: $2"
}
bilgi "Plan: her gece $BASLANGIC ($DILIM) başlar, gecede en çok $GECELIK yeni indirme, en geç $BITIS durur; günlük journalctl -u kanit-gyazo."
yaz "$TMP/kanit-gyazo.service" "$UNIT_DIR/kanit-gyazo.service"
yaz "$TMP/kanit-gyazo.timer" "$UNIT_DIR/kanit-gyazo.timer"
if (( DRY_RUN )); then bilgi 'DRY-RUN_TAMAM: birim ve zamanlayıcı değiştirilmedi.'; exit 0; fi
if command -v systemd-analyze >/dev/null 2>&1 && ! systemd-analyze verify "$UNIT_DIR/kanit-gyazo.service" "$UNIT_DIR/kanit-gyazo.timer"; then
    bilgi 'UYARI: systemd-analyze verify uyarı verdi (yukarıda); birimler yine de kuruluyor.'
fi
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable --now kanit-gyazo.timer
"$SYSTEMCTL" list-timers kanit-gyazo.timer --no-pager 2>/dev/null | sed 's/^/   /' || true
bilgi "GYAZO_GECE_TAMAM: kanit-gyazo.timer etkin (her gece $BASLANGIC, bitiş $BITIS, gecede $GECELIK). Hemen denemek: systemctl start kanit-gyazo.service; izlemek: journalctl -u kanit-gyazo -f"
