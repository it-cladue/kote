#!/usr/bin/env bash
# Kanit Merkezi - yedekten geri yukleme (root).
#   /opt/kanit/src/deploy/geri-yukle.sh <yyyy-MM-dd>            # /opt/kanit/veri/yedek/<tarih>/ icinden
#   /opt/kanit/src/deploy/geri-yukle.sh /yol/yedek/klasoru      # baska yerden (ornek: rclone ile indirilen)
#   secenekler: --sadece-db (gorsellere dokunma) | --sadece-gorseller | --evet (sorma) | --kuru
# Sira: servisleri durdur -> simdiki veri ve gorselleri kenara al (veri/yedek/geri-yukleme-oncesi-<zaman>/)
#       -> kanit.db.gz ac -> gorseller.tar.gz ac -> sahiplik -> servisleri baslat -> saglik.
# Yalnizca kayitli yedekleri yukler; .env'e dokunmaz (env.600 kopyasi yedek klasorunde durur, gerekirse elle).
set -euo pipefail

KOK=${KANIT_KOK:-/opt/kanit}          # test/deneme icin degistirilebilir
SRC=$KOK/src
VENV=$KOK/venv
VERI=${KANIT_VERI:-$KOK/veri}
ENV_DOSYA=$KOK/.env
KULLANICI=${KANIT_KULLANICI:-kanit}
YEDEK=$VERI/yedek
KURU=${KANIT_KUR_DRY:-0}
EVET=0; SADECE_DB=0; SADECE_GORSEL=0; SECIM=""
while [ $# -gt 0 ]; do
    case "$1" in
        --evet) EVET=1; shift ;;
        --sadece-db) SADECE_DB=1; shift ;;
        --sadece-gorseller) SADECE_GORSEL=1; shift ;;
        --kuru) KURU=1; shift ;;
        -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
        -*) echo "Bilinmeyen secenek: $1" >&2; exit 2 ;;
        *) SECIM=$1; shift ;;
    esac
done

bilgi() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
hata()  { printf '\033[1;31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }
calistir() { if [ "$KURU" = 1 ]; then printf '  [KURU] %s\n' "$*"; else printf '  + %s\n' "$*"; "$@"; fi; }

[ -n "$SECIM" ] || { echo "Kullanim: $0 <yyyy-MM-dd | klasor>  [--sadece-db] [--sadece-gorseller] [--evet]"; echo; echo "Eldeki yedekler:"; find "$YEDEK" -mindepth 1 -maxdepth 1 -type d -name '20*' -printf '  %f\n' 2>/dev/null | sort || true; exit 2; }
[ "$KURU" = 1 ] || [ "$(id -u)" = 0 ] || hata "root olarak calistirin"

if [ -d "$SECIM" ]; then KAYNAK=$(cd "$SECIM" && pwd); else KAYNAK=$YEDEK/$SECIM; fi
[ -d "$KAYNAK" ] || hata "yedek klasoru yok: $KAYNAK"
DB_GZ=$KAYNAK/kanit.db.gz
GORSEL_TAR=$KAYNAK/gorseller.tar.gz
[ "$SADECE_GORSEL" = 1 ] || [ -f "$DB_GZ" ] || hata "$DB_GZ yok"
[ "$SADECE_DB" = 1 ] || [ -f "$GORSEL_TAR" ] || { echo "  (gorseller.tar.gz yok; yalnizca veritabani yuklenecek)"; SADECE_DB=1; }

bilgi "Yedek dogrulaniyor: $KAYNAK"
if [ -f "$KAYNAK/SHA256SUMS" ]; then
    if [ "$KURU" = 1 ]; then echo "  [KURU] sha256sum -c SHA256SUMS"; else
        (cd "$KAYNAK" && sha256sum -c --quiet SHA256SUMS) || hata "SHA256SUMS uyusmuyor; yedek bozuk olabilir"
        echo "  = saglama tamam"
    fi
else
    echo "  (SHA256SUMS yok, saglama atlandi)"
fi
if [ "$SADECE_GORSEL" != 1 ] && [ "$KURU" != 1 ]; then
    gzip -t "$DB_GZ" || hata "kanit.db.gz acilamiyor"
fi

echo
echo "  Veritabani : $([ "$SADECE_GORSEL" = 1 ] && echo 'DOKUNULMAYACAK' || echo "$DB_GZ -> $VERI/kanit.db")"
echo "  Gorseller  : $([ "$SADECE_DB" = 1 ] && echo 'DOKUNULMAYACAK' || echo "$GORSEL_TAR -> $VERI/gorseller/")"
echo "  Simdiki veri kenara alinacak: $YEDEK/geri-yukleme-oncesi-<zaman>/"
echo "  Yedek tarihinden sonra girilen kayitlar KAYBOLUR (bot ve panel bu surede durur)."
if [ "$EVET" != 1 ] && [ "$KURU" != 1 ]; then
    read -r -p "Devam? (yazin: EVET) " c
    [ "$c" = "EVET" ] || { echo "vazgecildi"; exit 1; }
fi

ZAMAN=$(date +%Y%m%d-%H%M%S)
ONCESI=$YEDEK/geri-yukleme-oncesi-$ZAMAN
BOT_ACIKTI=0
if [ "$KURU" != 1 ] && systemctl is-active --quiet kanit-bot.service; then BOT_ACIKTI=1; fi

bilgi "1/5 Servisler durduruluyor"
calistir systemctl stop kanit-bot.service kanit-web.service

bilgi "2/5 Simdiki veri kenara aliniyor -> $ONCESI"
calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0750 "$ONCESI"
if [ "$SADECE_GORSEL" != 1 ]; then
    for f in kanit.db kanit.db-wal kanit.db-shm; do
        [ -f "$VERI/$f" ] && calistir mv -f "$VERI/$f" "$ONCESI/$f"
    done
fi
if [ "$SADECE_DB" != 1 ] && [ -d "$VERI/gorseller" ]; then
    # ayni dosya sisteminde: aninda (mv); 2 GB kopyalanmaz
    calistir mv -f "$VERI/gorseller" "$ONCESI/gorseller"
fi

bilgi "3/5 Yedek aciliyor"
if [ "$SADECE_GORSEL" != 1 ]; then
    if [ "$KURU" = 1 ]; then echo "  [KURU] gunzip -c $DB_GZ > $VERI/kanit.db"; else
        gunzip -c "$DB_GZ" > "$VERI/kanit.db"
        python3 -c "import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0]; sys.exit(0 if r=='ok' else 1)" "$VERI/kanit.db" \
            || hata "acilan veritabani bozuk; $ONCESI icindekiler geri tasinmali"
        echo "  = kanit.db geldi ($(du -h "$VERI/kanit.db" | cut -f1))"
    fi
fi
if [ "$SADECE_DB" != 1 ]; then
    calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0750 "$VERI/gorseller"
    calistir tar -C "$VERI" -xzf "$GORSEL_TAR"
fi
calistir rm -rf "$VERI/onbellek/thumbs"
calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0750 "$VERI/onbellek/thumbs"

bilgi "4/5 Sahiplik"
calistir chown -R "$KULLANICI:$KULLANICI" "$VERI"
[ "$SADECE_GORSEL" = 1 ] || calistir chmod 0640 "$VERI/kanit.db"

bilgi "5/5 Servisler ve saglik"
calistir systemctl start kanit-web.service
if [ "$BOT_ACIKTI" = 1 ] || [ "$KURU" = 1 ]; then calistir systemctl start kanit-bot.service; else echo "  = bot zaten kapaliydi, kapali kaldi"; fi
if [ "$KURU" != 1 ]; then
    sleep 3
    set +e
    (cd "$SRC/kanit" && runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" -m kanit saglik) | sed 's/^/    /'
    set -e
    printf '  kanit-web: %s   kanit-bot: %s\n' "$(systemctl is-active kanit-web)" "$(systemctl is-active kanit-bot)"
fi
echo
echo "Geri yukleme tamam. Eski veri $ONCESI altinda duruyor; her sey yolundaysa birkac gun sonra silin:"
echo "  rm -rf $ONCESI"
