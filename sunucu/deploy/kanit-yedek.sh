#!/usr/bin/env bash
# Kanıt Paneli — günlük yedek (root; kanit-yedek.timer çalıştırır). Kurulum: bash deploy/setup-backup.sh
#
#   kanit-yedek.sh               # SQLite (backup API, kanit hesabıyla) + .env kopyası; Pazar günleri ya da ilk kez: görsel aynası
#   kanit-yedek.sh --haftalik    # görsel aynasını bugün de al
#   kanit-yedek.sh --dogrula     # son SQLite yedeğini aç, PRAGMA integrity_check + kayıt sayısı
#   kanit-yedek.sh --dry-run     # yalnız planı yaz
#   kanit-yedek.sh --geri-yukle /var/backups/kanit-paneli/gunluk/panel-YYYYMMDD.db.gz [--dry-run]
#                                # SQLite'ı yedekten geri yükle: önce yedek açılıp doğrulanır (bozuksa hiçbir şeye dokunulmaz),
#                                # servisler durur, mevcut panel.db(+-wal/-shm) /root/kanit-onceki/<zaman>/ altına kopyalanır,
#                                # -wal/-shm SİLİNİR (silinmezse eski WAL geri yüklenen dosyanın üzerine uygulanır), yeni dosya
#                                # yerine konur (kanit:kanit 600), servisler yeniden başlar. Sonda: GERI_YUKLEME_TAMAM
#
# Konumlar (root, 0700):  /var/backups/kanit-paneli/gunluk/panel-YYYYMMDD.db.gz ve env-YYYYMMDD
#                          /var/backups/kanit-paneli/haftalik/YYYY-Www/{gorseller,telegram_gorseller}/ (rsync --link-dest ile artımlı)
# Saklama: 14 günlük, 8 haftalık; apply-update yedek dizinlerinden en yeni 5 tutulur (60 günden eskiler silinir);
# panel "Yedek al" dosyalarından (data/backups) son 5 kalır. Disk yetmiyorsa görsel aynası UYARI ile atlanır.
# Ayna sırasında silinen/değişen dosya (rsync 23/24) hata değil uyarıdır; ayna yine geçerlidir.
# Dış kopya (başka sunucu/bulut) bu betiğin işi değildir; README'deki rclone/scp örneğine bakın.
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
APP="${KANIT_APP:-/opt/kanit-paneli}"
DATA="${KANIT_DATA:-$APP/data}"
PY="${KANIT_PY:-$APP/.venv/bin/python}"
KOK="${KANIT_YEDEK_KOK:-/var/backups/kanit-paneli}"
SERVIS_KULLANICI="${KANIT_USER:-kanit}"
GUNLUK_SAKLA="${KANIT_GUNLUK_SAKLA:-14}"
HAFTALIK_SAKLA="${KANIT_HAFTALIK_SAKLA:-8}"
# settings.py varsayılanları: GORSEL_KLASOR=data/gorseller, ARSIV_KLASOR=data/telegram_gorseller
GORSEL_DIZINLER="${KANIT_GORSEL_DIZINLER:-gorseller telegram_gorseller}"
IFS=' ' read -r -a GORSEL_DIZI <<<"$GORSEL_DIZINLER"
HAFTALIK_GUN="${KANIT_HAFTALIK_GUN:-7}"
SYSTEMCTL="${KANIT_SYSTEMCTL:-systemctl}"
ONCEKI_KOK="${KANIT_ONCEKI_KOK:-/root/kanit-onceki}"
if [[ -z "${KANIT_TEST:-}" ]]; then PATH=/usr/sbin:/usr/bin:/sbin:/bin; export PATH; fi
GUNLUK="$KOK/gunluk"
HAFTALIK="$KOK/haftalik"
BUGUN="$(date +%Y%m%d)"
HAFTA="$(date +%G-W%V)"

DRY_RUN=0; HAFTALIK_ZORLA=0; DOGRULA=0; GERI_YUKLE=''
while (( $# )); do
    case "$1" in
        --dry-run) DRY_RUN=1 ;;
        --haftalik) HAFTALIK_ZORLA=1 ;;
        --dogrula) DOGRULA=1 ;;
        --geri-yukle) shift; GERI_YUKLE="${1:-}"; [[ -n "$GERI_YUKLE" ]] || { echo 'HATA: --geri-yukle için yedek dosyası (panel-YYYYMMDD.db.gz) verin.' >&2; exit 2; } ;;
        -h|--help|--yardim) sed -n '2,19p' "$0"; exit 0 ;;
        *) echo "HATA: Bilinmeyen seçenek: $1 (--yardim)" >&2; exit 2 ;;
    esac
    shift
done

gunluk() { if command -v logger >/dev/null 2>&1; then logger -t kanit-yedek -- "$*" || true; fi; }
bilgi() { printf '%s\n' "$*"; gunluk "$*"; }
uyar() { printf 'UYARI: %s\n' "$*" >&2; gunluk "UYARI: $*"; }
fail() { printf 'HATA: %s\n' "$*" >&2; gunluk "HATA: $*"; exit 1; }

[[ ${EUID} -eq 0 ]] || fail 'Root gerekli (yedek dizini yalnız root okur).'
[[ -x "$PY" ]] || fail "Python bulunamadı: $PY"
[[ -d "$DATA" ]] || fail "Veri dizini yok: $DATA"
command -v gzip >/dev/null 2>&1 || fail 'gzip bulunamadı.'

# kanit hesabı varsa DB işlemleri onunla yapılır (WAL yan dosyaları root sahipli kalmasın).
kanit_olarak() {
    if getent passwd "$SERVIS_KULLANICI" >/dev/null 2>&1; then
        runuser -u "$SERVIS_KULLANICI" -- "$@"
    else
        "$@"
    fi
}

sqlite_yedek_al() {
    local kaynak="$DATA/panel.db" gecici="$DATA/.kanit-yedek-$$.db" hedef="$GUNLUK/panel-$BUGUN.db"
    [[ -f "$kaynak" ]] || fail "SQLite dosyası yok: $kaynak"
    rm -f -- "${gecici:?}"
    kanit_olarak "$PY" -I - "$kaynak" "$gecici" <<'PY'
import sqlite3, sys, os
from urllib.parse import quote
src, dst = sys.argv[1], sys.argv[2]
fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.close(fd)
s = sqlite3.connect("file:" + quote(os.path.abspath(src)) + "?mode=ro", uri=True, timeout=30)
d = sqlite3.connect(dst, timeout=30)
try:
    s.backup(d)
    d.execute("PRAGMA journal_mode=DELETE")   # yedek tek dosya olsun (-wal/-shm yok)
    ok = d.execute("PRAGMA integrity_check").fetchone()[0]
finally:
    d.close(); s.close()
if str(ok).lower() != "ok":
    os.unlink(dst); sys.exit("SQLite yedeği bütünlük denetiminden geçmedi: " + str(ok))
PY
    mv -f -- "$gecici" "$hedef"
    chown root:root "$hedef"; chmod 600 "$hedef"
    gzip -f -- "$hedef"
    bilgi "SQLite yedeği: $hedef.gz ($(du -h "$hedef.gz" | cut -f1))"
}

env_yedek_al() {
    if [[ -f "$APP/.env" ]]; then
        cp -p -- "$APP/.env" "$GUNLUK/env-$BUGUN"
        chown root:root "$GUNLUK/env-$BUGUN"; chmod 600 "$GUNLUK/env-$BUGUN"
        bilgi "Ayar kopyası: $GUNLUK/env-$BUGUN (root 600)"
    else
        uyar ".env bulunamadı ($APP/.env); ayar kopyası alınmadı."
    fi
}

son_haftalik() { find "$HAFTALIK" -mindepth 1 -maxdepth 1 -type d -name '[0-9][0-9][0-9][0-9]-W[0-9][0-9]' ! -name "$HAFTA" | sort | tail -1; }

haftalik_gerekli() {
    (( HAFTALIK_ZORLA )) && return 0
    [[ "$(date +%u)" == "$HAFTALIK_GUN" ]] && return 0
    [[ -z "$(find "$HAFTALIK" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)" ]] && return 0
    return 1
}

# Canlı panel çalışırken ayna alınır: rsync liste kurduktan sonra silinen dosya (24 'vanished') ya da aktarılamayan
# dosya (23 'partial') uyarıdır, betiği kesmez; saklama/temizlik ve YEDEK_TAMAM çalışır. Diğer kodlar ölümcül.
rsync_ayna() {
    local rc=0
    rsync "$@" || rc=$?
    case "$rc" in
        0) ;;
        23|24) uyar "rsync $rc: ayna sırasında bazı dosyalar silindi/aktarılamadı (canlı panel çalışıyor); ayna yine geçerli." ;;
        *) fail "rsync hatası (çıkış $rc); görsel aynası alınamadı." ;;
    esac
}

gorsel_ayna_al() {
    local hedef="$HAFTALIK/$HAFTA" son d boyut bos gerekli
    son="$(son_haftalik)"
    install -d -m 700 "$hedef"
    for d in "${GORSEL_DIZI[@]}"; do
        [[ -d "$DATA/$d" ]] || continue
        boyut="$(du -sb -- "$DATA/$d" | cut -f1)"
        bos="$(df --output=avail -B1 -- "$KOK" | tail -1 | tr -d ' ')"
        if command -v rsync >/dev/null 2>&1 && [[ -n "$son" && -d "$son/$d" ]]; then
            gerekli=$(( boyut / 10 + 200 * 1024 * 1024 ))   # artımlı: değişen dosyalar + pay
        else
            gerekli=$(( boyut + boyut / 20 ))
        fi
        if (( bos < gerekli )); then
            uyar "Disk yetersiz: $d için ~$(( gerekli / 1048576 )) MB gerekli, $(( bos / 1048576 )) MB boş. Görsel aynası atlandı; disk açın (df -h $KOK)."
            continue
        fi
        if command -v rsync >/dev/null 2>&1; then
            if [[ -n "$son" && -d "$son/$d" ]]; then
                # -rlptD: sahiplik kopyalanmaz (root yazar); böylece haftalar arası hardlink karşılaştırması tutar.
                rsync_ayna -rlptD --delete --link-dest="$son/$d" -- "$DATA/$d/" "$hedef/$d/"
            else
                rsync_ayna -rlptD --delete -- "$DATA/$d/" "$hedef/$d/"
            fi
            bilgi "Görsel aynası: $hedef/$d ($(du -sh -- "$hedef/$d" | cut -f1)${son:+, önceki haftaya hardlink})"
        else
            tar -C "$DATA" -czf "$hedef/$d.tar.gz" -- "$d"
            bilgi "Görsel arşivi (rsync yok): $hedef/$d.tar.gz ($(du -h -- "$hedef/$d.tar.gz" | cut -f1))"
        fi
    done
}

temizle() {
    local eski desen
    # Günlük: en yeni N kalsın (ad sırası = tarih sırası).
    for desen in 'panel-*.db.gz' 'env-*'; do
        find "$GUNLUK" -mindepth 1 -maxdepth 1 -type f -name "$desen" -printf '%f\n' | sort | head -n -"$GUNLUK_SAKLA" | while IFS= read -r eski; do
            rm -f -- "${GUNLUK:?}/${eski:?}"; bilgi "Eski günlük yedek silindi: $eski"
        done
    done
    # Haftalık: en yeni N dizin kalsın.
    find "$HAFTALIK" -mindepth 1 -maxdepth 1 -type d -name '[0-9][0-9][0-9][0-9]-W[0-9][0-9]' -printf '%f\n' | sort | head -n -"$HAFTALIK_SAKLA" | while IFS= read -r eski; do
        rm -rf -- "${HAFTALIK:?}/${eski:?}"; bilgi "Eski haftalık ayna silindi: $eski"
    done
    # apply-update yedekleri (<zaman>-<pid>): en yeni 5 kalır, kalanlardan 60 günden eskiler silinir.
    find "$KOK" -mindepth 1 -maxdepth 1 -type d -regextype posix-extended -regex '.*/[0-9]{8}T[0-9]{6}Z-[0-9]+' -printf '%f\n' | sort | head -n -5 | while IFS= read -r eski; do
        if [[ -n "$(find "$KOK/$eski" -maxdepth 0 -mtime +60)" ]]; then
            rm -rf -- "${KOK:?}/${eski:?}"; bilgi "Eski güncelleme yedeği silindi: $eski"
        fi
    done
    # Panel/Telegram "Yedek al" dosyaları (data/backups, sınırsız birikir): son 5 kalsın; dizin boşsa hata sayma.
    { ls -1t -- "$DATA"/backups/*.sqlite3 2>/dev/null || true; } | tail -n +6 | xargs -r rm -f --
}

DOGRULA_GECICI=''
dogrula() {
    local son sonuc
    son="$(find "$GUNLUK" -mindepth 1 -maxdepth 1 -type f -name 'panel-*.db.gz' -printf '%f\n' 2>/dev/null | sort | tail -1)"
    [[ -n "$son" ]] || fail "Doğrulanacak yedek yok ($GUNLUK/panel-*.db.gz)."
    DOGRULA_GECICI="$KOK/.dogrula-$$.db"
    trap '[[ -n "$DOGRULA_GECICI" ]] && rm -f -- "$DOGRULA_GECICI"' EXIT
    gunzip -c -- "$GUNLUK/$son" > "$DOGRULA_GECICI" || fail "YEDEK_BOZUK: $son açılamadı (gzip)."
    sonuc="$("$PY" -I - "$DOGRULA_GECICI" <<'PY'
import sqlite3, sys
try:
    c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro&immutable=1", uri=True)
    ic = c.execute("PRAGMA integrity_check").fetchone()[0]
    tablolar = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    kayit = c.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] if "kayitlar" in tablolar else -1
except sqlite3.Error as exc:
    print(f"sqlite hatası: {exc}"); sys.exit(1)
print(f"integrity={ic} tablo={len(tablolar)} kayit={kayit}")
if str(ic).lower() != "ok": sys.exit(1)
PY
)" || fail "YEDEK_BOZUK: $son -> ${sonuc:-açılamadı}"
    bilgi "YEDEK_DOGRULANDI: $son ($sonuc)"
}

# --geri-yukle: yedeği doğrula -> servisleri durdur -> mevcut DB'yi kenara al -> -wal/-shm sil -> yerine koy -> başlat.
GERI_GECICI=''
servis_aktif() { "$SYSTEMCTL" is-active --quiet "$1" 2>/dev/null; }
# Geri yüklemeden sonra başlatılacaklar: o an aktif olan ya da etkin (enabled) olan servisler. Çökmüş/failed ama etkin
# servis böylece geri gelir; operatörün bilinçle kapatıp devre dışı bıraktığı servis başlatılmaz.
servis_baslatilacak() { servis_aktif "$1" || "$SYSTEMCTL" is-enabled --quiet "$1" 2>/dev/null; }
geri_yukle() {
    local yedek="$1" hedef="$DATA/panel.db" onceki sonuc s aktifler=()
    [[ -f "$yedek" ]] || fail "Geri yüklenecek yedek bulunamadı: $yedek (hiçbir şeye dokunulmadı)."
    [[ "$yedek" == *.gz ]] || fail "Yedek dosyası .db.gz uzantılı olmalı: $yedek (hiçbir şeye dokunulmadı)."
    onceki="$ONCEKI_KOK/$(date +%Y%m%d-%H%M%S)-$$"
    if (( DRY_RUN )); then
        printf 'Plan: %s açılıp doğrulanacak; kanit-web/kanit-bot durdurulacak; mevcut %s (+-wal/-shm) -> %s/; -wal/-shm silinecek; yeni dosya %s olacak (%s 600); servisler başlatılacak.\n' \
            "$yedek" "$hedef" "$onceki" "$hedef" "$SERVIS_KULLANICI"
        printf 'DRY-RUN_TAMAM: hiçbir dosya yazılmadı, servislere dokunulmadı.\n'
        return 0
    fi
    # 1) Yedeği geçici dosyaya aç ve doğrula — servisler çalışıyor, hiçbir şeye dokunulmadı.
    GERI_GECICI="$DATA/.kanit-geri-yukle-$$.db"
    trap '[[ -n "$GERI_GECICI" ]] && rm -f -- "$GERI_GECICI"' EXIT
    rm -f -- "${GERI_GECICI:?}"
    gunzip -c -- "$yedek" > "$GERI_GECICI" || fail "YEDEK_BOZUK: $yedek açılamadı (gzip); hiçbir şeye dokunulmadı."
    sonuc="$("$PY" -I - "$GERI_GECICI" <<'PYKONTROL'
import sqlite3, sys
try:
    c = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro&immutable=1", uri=True)
    ic = c.execute("PRAGMA integrity_check").fetchone()[0]
    tablolar = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
except sqlite3.Error as exc:
    print(f"sqlite hatası: {exc}"); sys.exit(1)
if str(ic).lower() != "ok":
    print(f"integrity={ic}"); sys.exit(1)
if "kayitlar" not in tablolar:
    print("Kanıt Paneli veritabanı değil (kayitlar tablosu yok)"); sys.exit(1)
print(f"integrity=ok tablo={len(tablolar)}")
PYKONTROL
)" || fail "YEDEK_BOZUK: $yedek -> ${sonuc:-açılamadı}; hiçbir şeye dokunulmadı."
    bilgi "Yedek doğrulandı: $yedek ($sonuc)"
    # 2) Servisleri durdur (aktif ya da etkin olanlar sonra yeniden başlatılır).
    for s in kanit-web kanit-bot; do
        if servis_baslatilacak "$s"; then aktifler+=("$s"); fi
        "$SYSTEMCTL" stop "$s" || fail "$s durdurulamadı; veritabanına dokunulmadı. systemctl status $s"
    done
    # 3) Mevcut DB'yi (+WAL/SHM, varsa) kenara al; sonra yan dosyaları SİL (kalırsa eski WAL yeni dosyaya uygulanır).
    install -d -m 700 -o root -g root "$ONCEKI_KOK" "$onceki"
    for s in "$hedef" "$hedef-wal" "$hedef-shm"; do
        if [[ -e "$s" ]]; then cp -a -- "$s" "$onceki/"; fi
    done
    rm -f -- "$hedef-wal" "$hedef-shm"
    # 4) Yeni dosyayı yerine koy (aynı dizin: atomik rename), sahiplik/izin.
    chmod 600 -- "$GERI_GECICI"
    if getent passwd "$SERVIS_KULLANICI" >/dev/null 2>&1; then chown "$SERVIS_KULLANICI:$SERVIS_KULLANICI" -- "$GERI_GECICI"; fi
    mv -f -- "$GERI_GECICI" "$hedef"
    GERI_GECICI=''
    # 5) Önceden aktif/etkin servisleri başlat.
    for s in "${aktifler[@]}"; do
        "$SYSTEMCTL" start "$s" || uyar "$s başlatılamadı; bakın: systemctl status $s; journalctl -u $s -n 50"
    done
    (( ${#aktifler[@]} )) || uyar 'Geri yükleme öncesinde kanit-web/kanit-bot ne aktif ne etkin idi; servisler başlatılmadı (gerekirse: systemctl start kanit-web kanit-bot).'
    bilgi "GERI_YUKLEME_TAMAM: $hedef <- $yedek; önceki dosyalar: $onceki/ (artık gereksizse silin). Başlatılan: ${aktifler[*]:-yok}"
}

install -d -m 700 -o root -g root "$KOK" "$GUNLUK" "$HAFTALIK"
if [[ -n "$GERI_YUKLE" ]]; then geri_yukle "$GERI_YUKLE"; exit 0; fi
if (( DOGRULA )); then dogrula; exit 0; fi

if (( DRY_RUN )); then
    printf 'Plan: SQLite -> %s/panel-%s.db.gz; .env -> %s/env-%s; görsel aynası: %s (%s); saklama %s gün / %s hafta\n' \
        "$GUNLUK" "$BUGUN" "$GUNLUK" "$BUGUN" "$(haftalik_gerekli && echo 'bugün alınacak' || echo 'bugün alınmayacak')" "$HAFTALIK/$HAFTA" "$GUNLUK_SAKLA" "$HAFTALIK_SAKLA"
    printf 'Disk: %s\n' "$(df -h --output=avail,pcent,target -- "$KOK" | tail -1)"
    printf 'DRY-RUN_TAMAM: hiçbir dosya yazılmadı.\n'
    exit 0
fi

sqlite_yedek_al
env_yedek_al
if haftalik_gerekli; then gorsel_ayna_al; else bilgi "Görsel aynası bugün alınmadı (haftalık; son: $(son_haftalik || true))."; fi
temizle
bilgi "YEDEK_TAMAM: $(date '+%F %T'); toplam $(du -sh -- "$KOK" | cut -f1); boş alan $(df -h --output=avail -- "$KOK" | tail -1 | tr -d ' ')"
