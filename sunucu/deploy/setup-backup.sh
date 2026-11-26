#!/usr/bin/env bash
# Kanıt Paneli — günlük yedek zamanlayıcısını kurar (root).
#
#   bash deploy/setup-backup.sh [--dry-run]
#
# Yaptığı: deploy/kanit-yedek.sh -> /usr/local/sbin/kanit-yedek.sh (root 700); kanit-yedek.service + kanit-yedek.timer
# -> /etc/systemd/system; daemon-reload; timer etkin (her gün 03:17 + rastgele 15 dk; kaçırılan çalışma açılışta telafi);
# ilk yedek hemen alınır ve --dogrula ile denetlenir. Mevcut dosyalar aynıysa dokunulmaz.
# 2.4.0: birim --zamanlayici ile çalışır (gece dosyası panel-YYYYMMDD.db.gz); elle çalıştırma saatli ad alır ve gece dosyasını
# ezmez. Güncellemeden sonra bu betiği bir kez yeniden çalıştırın (yeni betik + birim kurulur). Liste: kanit-yedek.sh --liste
set -Eeuo pipefail
IFS=$'\n\t'
SBIN_DIR="${KANIT_SBIN_DIR:-/usr/local/sbin}"
UNIT_DIR="${KANIT_UNIT_DIR:-/etc/systemd/system}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
SRC_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        -h|--help|--yardim) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $arg (--yardim)" >&2; exit 2 ;;
    esac
done
fail() { printf 'DUR: %s\n' "$*" >&2; exit 1; }
bilgi() { printf '%s\n' "$*"; }
[[ ${EUID} -eq 0 ]] || fail 'Root oturumu gerekli.'
for f in kanit-yedek.sh kanit-yedek.service kanit-yedek.timer; do [[ -r "$SRC_DIR/$f" ]] || fail "Kaynak dosya yok: $SRC_DIR/$f"; done
bash -n "$SRC_DIR/kanit-yedek.sh" || fail 'kanit-yedek.sh sözdizimi hatalı.'
command -v rsync >/dev/null 2>&1 || bilgi 'UYARI: rsync yok; görsel aynası tar.gz olarak alınır (artımlı değil). Önerilen: apt-get install -y rsync'

HEDEF_SH="$SBIN_DIR/kanit-yedek.sh"
yaz() { # kaynak hedef mod
    if [[ -f "$2" ]] && cmp -s "$1" "$2"; then bilgi "Güncel: $2"; return 0; fi
    if (( DRY_RUN )); then bilgi "Yazılacak: $2"; return 0; fi
    install -d -m 755 "$(dirname -- "$2")"
    install -m "$3" -o root -g root "$1" "$2"
    bilgi "Yazıldı: $2"
}
yaz "$SRC_DIR/kanit-yedek.sh" "$HEDEF_SH" 700
yaz "$SRC_DIR/kanit-yedek.service" "$UNIT_DIR/kanit-yedek.service" 644
yaz "$SRC_DIR/kanit-yedek.timer" "$UNIT_DIR/kanit-yedek.timer" 644
if (( DRY_RUN )); then
    bash "$SRC_DIR/kanit-yedek.sh" --dry-run
    bilgi 'DRY-RUN_TAMAM: dosya, servis ve zamanlayıcı değiştirilmedi.'
    exit 0
fi
if command -v systemd-analyze >/dev/null 2>&1 && ! systemd-analyze verify "$UNIT_DIR/kanit-yedek.service" "$UNIT_DIR/kanit-yedek.timer"; then
    bilgi 'UYARI: systemd-analyze verify uyarı verdi (yukarıda); birimler yine de kuruluyor.'
fi
"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable --now kanit-yedek.timer
bilgi 'İlk yedek alınıyor...'
"$HEDEF_SH" --zamanlayici   # ilk yedek gece biçiminde (panel-YYYYMMDD.db.gz); o geceki çalışma aynı dosyayı yeniler
"$HEDEF_SH" --dogrula
"$SYSTEMCTL" list-timers kanit-yedek.timer --no-pager 2>/dev/null | sed 's/^/   /' || true
bilgi 'YEDEK_ZAMANLAYICI_TAMAM: kanit-yedek.timer etkin. Dış kopya için README "Yedek" bölümündeki rclone/scp örneğini ayrıca kurun.'
