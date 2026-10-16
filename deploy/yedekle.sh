#!/usr/bin/env bash
# Kanit Merkezi - gece yedegi (root ya da kanit; cron: /etc/cron.d/kanit-yedek, 03:15).
#   /opt/kanit/src/deploy/yedekle.sh            # bugunun yedegi: /opt/kanit/veri/yedek/<yyyy-MM-dd>/
#   /opt/kanit/src/deploy/yedekle.sh --gun 60   # yerel saklama suresi (varsayilan 30 gun)
#   /opt/kanit/src/deploy/yedekle.sh --sadece-db  # gorselleri paketleme (hizli, elle alinan ara yedek)
#
# Yedek klasoru icerigi:
#   kanit.db.gz        SQLite online yedek (tutarli kopya; python -m kanit yedekle), gzip
#   gorseller.tar.gz   VERI/gorseller tam paketi (2 GB icin dakikalar surer; gece 03:15 sorun degil)
#   env.600            /opt/kanit/.env kopyasi (TOKENLAR ICERIR, izni 600)
#   SHA256SUMS         dogrulama:  cd <klasor> && sha256sum -c SHA256SUMS
# Ayni gun ikinci kez calisirsa ustune yazar. 30 gunden eski klasorler silinir.
#
# Uzak kopya (istege bagli): /opt/kanit/rclone.conf varsa yedek klasoru rclone ile uzak hedefe esitlenir.
#   Hedef adi: KANIT_RCLONE_HEDEF (varsayilan "kanit-yedek:kanit"). Kurulum: apt install rclone;
#   rclone --config /opt/kanit/rclone.conf config   -> ad: kanit-yedek, tur: Google Drive / S3 / Backblaze / SFTP ...
#   env.600 tokenlari tasir: uzak tarafta "crypt" uzak hedef kullanin ya da KANIT_YEDEK_ENV=0 ile env kopyasini kapatin.
set -euo pipefail

KOK=${KANIT_KOK:-/opt/kanit}          # test/deneme icin degistirilebilir
SRC=$KOK/src
VENV=$KOK/venv
VERI=${KANIT_VERI:-$KOK/veri}
ENV_DOSYA=$KOK/.env
KULLANICI=${KANIT_KULLANICI:-kanit}
YEDEK=$VERI/yedek
GUN=${KANIT_YEDEK_GUN:-30}
SADECE_DB=0
ENV_KOPYA=${KANIT_YEDEK_ENV:-1}
RCLONE_CONF=$KOK/rclone.conf
RCLONE_HEDEF=${KANIT_RCLONE_HEDEF:-kanit-yedek:kanit}
KURU=${KANIT_KUR_DRY:-0}
while [ $# -gt 0 ]; do
    case "$1" in
        --gun) GUN=$2; shift 2 ;;
        --sadece-db) SADECE_DB=1; shift ;;
        --kuru) KURU=1; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) echo "Bilinmeyen secenek: $1" >&2; exit 2 ;;
    esac
done

zaman() { date '+%Y-%m-%d %H:%M:%S'; }
bilgi() { printf '%s  %s\n' "$(zaman)" "$*"; }
hata()  { printf '%s  HATA: %s\n' "$(zaman)" "$*" >&2; exit 1; }
calistir() { if [ "$KURU" = 1 ]; then printf '  [KURU] %s\n' "$*"; else "$@"; fi; }

# Ayni anda iki yedek calismasin
KILIT=$VERI/gecici/yedek.kilit
if [ "$KURU" != 1 ]; then
    mkdir -p "$VERI/gecici"
    exec 9>"$KILIT"
    flock -n 9 || hata "baska bir yedekleme suruyor ($KILIT)"
fi

TARIH=$(date +%Y-%m-%d)
HEDEF=$YEDEK/$TARIH
bilgi "yedek basliyor -> $HEDEF"
calistir mkdir -p "$HEDEF"

# Komutlari kanit kullanicisi olarak calistir (root isek); kanit isek dogrudan
py_kanit() {
    if [ "$(id -u)" = 0 ]; then
        runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" "$@"
    else
        env KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" "$@"
    fi
}

# 1) veritabani: once CLI (python -m kanit yedekle HEDEF), olmazsa dogrudan db.yedekle
if [ "$KURU" = 1 ]; then
    printf '  [KURU] (kanit olarak) cd %s/kanit && python -m kanit yedekle %s/kanit.db ; gzip\n' "$SRC" "$HEDEF"
else
    rm -f "$HEDEF/kanit.db" "$HEDEF/kanit.db.gz"
    if ! (cd "$SRC/kanit" && py_kanit -m kanit yedekle "$HEDEF/kanit.db") >/dev/null 2>&1 || [ ! -s "$HEDEF/kanit.db" ]; then
        bilgi "CLI yedekle calismadi, db.yedekle ile deneniyor"
        (cd "$SRC/kanit" && py_kanit -c "import sys; from kanit import ayar, db; a=ayar.yukle(); c=db.baglan(a['DB']); db.yedekle(c, sys.argv[1]); c.close()" "$HEDEF/kanit.db")
    fi
    [ -s "$HEDEF/kanit.db" ] || hata "veritabani yedegi olusmadi"
    # butunluk
    if ! python3 -c "import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0]; sys.exit(0 if r=='ok' else 1)" "$HEDEF/kanit.db"; then
        hata "yedek veritabani butunluk kontrolunden gecmedi"
    fi
    gzip -f "$HEDEF/kanit.db"
    bilgi "kanit.db.gz hazir ($(du -h "$HEDEF/kanit.db.gz" | cut -f1))"
fi

# 2) gorseller (tam paket; gorsel adlari ASCII, relatif yol)
if [ "$SADECE_DB" = 1 ]; then
    bilgi "gorseller atlandi (--sadece-db)"
elif [ "$KURU" = 1 ]; then
    printf '  [KURU] tar -C %s -czf %s/gorseller.tar.gz gorseller\n' "$VERI" "$HEDEF"
else
    if [ -d "$VERI/gorseller" ]; then
        # tar 1 = "dosya okunurken degisti" (bot o anda gorsel yaziyorsa); hata sayma
        set +e
        nice -n 10 ionice -c 3 tar -C "$VERI" --warning=no-file-changed -czf "$HEDEF/gorseller.tar.gz.part" gorseller
        RC=$?
        set -e
        [ $RC -le 1 ] || hata "gorsel paketi basarisiz (tar $RC)"
        mv -f "$HEDEF/gorseller.tar.gz.part" "$HEDEF/gorseller.tar.gz"
        bilgi "gorseller.tar.gz hazir ($(du -h "$HEDEF/gorseller.tar.gz" | cut -f1))"
    else
        bilgi "gorsel klasoru yok, atlandi"
    fi
fi

# 3) .env kopyasi
if [ "$ENV_KOPYA" = 1 ] && [ -f "$ENV_DOSYA" ]; then
    calistir install -m 0600 "$ENV_DOSYA" "$HEDEF/env.600"
fi

# 4) saglama + sahiplik
if [ "$KURU" != 1 ]; then
    # SHA256SUMS kendisi listeye girmesin (ayni gun ikinci calismada dosya zaten var)
    (cd "$HEDEF" && find . -maxdepth 1 -type f ! -name 'SHA256SUMS*' -printf '%f\n' | sort | xargs -r sha256sum -- > SHA256SUMS.tmp && mv -f SHA256SUMS.tmp SHA256SUMS)
    if [ "$(id -u)" = 0 ]; then chown -R "$KULLANICI:$KULLANICI" "$HEDEF"; fi
    chmod 0750 "$HEDEF"
    printf '%s\n' "$TARIH" > "$YEDEK/SON"
fi

# 5) eski yedekleri sil
bilgi "$GUN gunden eski yedekler siliniyor"
if [ "$KURU" = 1 ]; then
    find "$YEDEK" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' -mtime +"$GUN" -print 2>/dev/null | sed 's/^/  [KURU] silinecek: /' || true
else
    find "$YEDEK" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' -mtime +"$GUN" -print -exec rm -rf {} + | sed 's/^/  silindi: /' || true
fi

# 6) uzak kopya
if [ -f "$RCLONE_CONF" ]; then
    if command -v rclone >/dev/null 2>&1; then
        bilgi "uzak kopya: rclone sync -> $RCLONE_HEDEF"
        calistir rclone --config "$RCLONE_CONF" sync "$YEDEK" "$RCLONE_HEDEF" --transfers 2 --checkers 4 --stats-one-line --stats 1m -v
    else
        bilgi "UYARI: $RCLONE_CONF var ama rclone kurulu degil (apt install rclone)"
    fi
fi

bilgi "disk: $(df -h --output=avail,pcent "$VERI" | tail -1 | xargs)  kullanilabilir/dolu"
bilgi "yedek tamam: $HEDEF"
