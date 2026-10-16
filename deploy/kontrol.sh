#!/usr/bin/env bash
# Kanit Merkezi - hizli saglik kontrolu (root ya da kanit). Hicbir seyi degistirmez.
#   /opt/kanit/src/deploy/kontrol.sh          # ozet
#   /opt/kanit/src/deploy/kontrol.sh --hata 50  # loglardan son 50 hata satiri (varsayilan 15)
set -uo pipefail

KOK=${KANIT_KOK:-/opt/kanit}          # test/deneme icin degistirilebilir
SRC=$KOK/src
VENV=$KOK/venv
VERI=${KANIT_VERI:-$KOK/veri}
ENV_DOSYA=$KOK/.env
KULLANICI=${KANIT_KULLANICI:-kanit}
HATA_N=15
while [ $# -gt 0 ]; do
    case "$1" in
        --hata) HATA_N=$2; shift 2 ;;
        -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
        *) echo "Bilinmeyen secenek: $1" >&2; exit 2 ;;
    esac
done

baslik() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()     { printf '  \033[1;32mOK \033[0m %s\n' "$*"; }
kotu()   { printf '  \033[1;31mSORUN\033[0m %s\n' "$*"; SORUN=$((SORUN+1)); }
SORUN=0

PORT=$(grep -E '^PORT=' "$ENV_DOSYA" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]"'"'"); PORT=${PORT:-8080}
DINLE=$(grep -E '^DINLE=' "$ENV_DOSYA" 2>/dev/null | tail -1 | cut -d= -f2 | tr -d '[:space:]"'"'"); DINLE=${DINLE:-0.0.0.0}

baslik "KANIT MERKEZI KONTROL  $(date '+%Y-%m-%d %H:%M:%S')  ($(hostname))"
echo "  kaynak : $(cat "$KOK/kaynak.txt" 2>/dev/null || echo '?')"
[ -d "$SRC/.git" ] && echo "  surum  : $(git -C "$SRC" log -1 --format='%h %ci' 2>/dev/null || echo '?')"
echo "  python : $("$VENV/bin/python" --version 2>&1 || echo 'venv yok')"

baslik "Servisler"
for u in kanit-web kanit-bot; do
    durum=$(systemctl is-active "$u" 2>/dev/null || echo bilinmiyor)
    etkin=$(systemctl is-enabled "$u" 2>/dev/null || echo -)
    beri=$(systemctl show "$u" -p ActiveEnterTimestamp --value 2>/dev/null || true)
    yeniden=$(systemctl show "$u" -p NRestarts --value 2>/dev/null || echo 0)
    satir="$u: $durum (acilista: $etkin, baslangic: ${beri:-?}, yeniden baslatma: ${yeniden:-0})"
    if [ "$durum" = active ]; then ok "$satir"
    elif [ "$u" = kanit-bot ] && [ "$etkin" = disabled ]; then echo "  -   $satir  [veri aktarimi bitince: systemctl enable --now kanit-bot]"
    else kotu "$satir"; fi
    [ "${yeniden:-0}" -gt 5 ] 2>/dev/null && kotu "$u cok sik yeniden basliyor ($yeniden); journalctl -u $u -n 50"
done

baslik "Web ($DINLE:$PORT)"
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$PORT "; then ok "port $PORT dinleniyor"; else kotu "port $PORT dinlenmiyor"; fi
KOD=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || echo 000)
case "$KOD" in
    200|302|303) ok "http://127.0.0.1:$PORT/ -> $KOD" ;;
    *) kotu "http://127.0.0.1:$PORT/ -> $KOD (servis acik mi? tail $VERI/log/web.log)" ;;
esac

baslik "Uygulama sagligi (python -m kanit saglik)"
if [ -x "$VENV/bin/python" ]; then
    if [ "$(id -u)" = 0 ]; then
        (cd "$SRC/kanit" && runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" -m kanit saglik 2>&1) | sed 's/^/  /'
    else
        (cd "$SRC/kanit" && env KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" -m kanit saglik 2>&1) | sed 's/^/  /'
    fi
    RC=${PIPESTATUS[0]}
    if [ "$RC" = 0 ]; then ok "saglik komutu 0 ile cikti"; else kotu "saglik komutu $RC ile cikti"; fi
else
    kotu "venv yok: $VENV"
fi

baslik "Disk"
df -h --output=target,size,used,avail,pcent "$VERI" 2>/dev/null | sed 's/^/  /'
DOLU=$(df --output=pcent "$VERI" 2>/dev/null | tail -1 | tr -dc '0-9'); DOLU=${DOLU:-0}
if [ "$DOLU" -ge 90 ]; then kotu "disk %$DOLU dolu (eski yedekleri silin: ls $VERI/yedek)"; elif [ "$DOLU" -ge 80 ]; then echo "  !   disk %$DOLU dolu, yakinda yer acin"; else ok "disk %$DOLU dolu"; fi
for alt in kanit.db gorseller onbellek yedek log; do
    [ -e "$VERI/$alt" ] && printf '  %-10s %s\n' "$alt" "$(du -sh "$VERI/$alt" 2>/dev/null | cut -f1)"
done

baslik "Yedek"
SON=$(cat "$VERI/yedek/SON" 2>/dev/null || true)
if [ -n "$SON" ] && [ -d "$VERI/yedek/$SON" ]; then
    YAS=$(( ( $(date +%s) - $(date -d "$SON" +%s 2>/dev/null || echo 0) ) / 86400 ))
    if [ "$YAS" -le 1 ]; then ok "son yedek $SON ($(du -sh "$VERI/yedek/$SON" 2>/dev/null | cut -f1))"; else kotu "son yedek $SON, $YAS gun once (cron: /etc/cron.d/kanit-yedek, log: $VERI/log/yedek.log)"; fi
    echo "  yedek sayisi: $(find "$VERI/yedek" -mindepth 1 -maxdepth 1 -type d -name '20*' 2>/dev/null | wc -l)"
else
    kotu "hic yedek yok (elle: $SRC/deploy/yedekle.sh)"
fi
if [ -f /etc/cron.d/kanit-yedek ]; then ok "cron satiri var"; else kotu "/etc/cron.d/kanit-yedek yok"; fi
[ -f "$KOK/rclone.conf" ] && echo "  uzak kopya: rclone.conf var" || echo "  uzak kopya: yok (istege bagli, bkz. yedekle.sh)"

baslik "Ayar dosyasi"
if [ -f "$ENV_DOSYA" ]; then
    IZIN=$(stat -c '%a %U' "$ENV_DOSYA" 2>/dev/null)
    if [ "$IZIN" = "600 $KULLANICI" ]; then ok ".env izni $IZIN"; else kotu ".env izni '$IZIN' (olmasi gereken: 600 $KULLANICI)"; fi
    if grep -qE '^TELEGRAM_TOKEN=BURAYA|^TELEGRAM_TOKEN=$' "$ENV_DOSYA"; then kotu "TELEGRAM_TOKEN yazilmamis"; else ok "TELEGRAM_TOKEN yazili"; fi
    if grep -qE '^BOT_PASSWORD=BURAYA|^BOT_PASSWORD=$' "$ENV_DOSYA"; then kotu "BOT_PASSWORD yazilmamis"; else ok "BOT_PASSWORD yazili"; fi
else
    kotu "$ENV_DOSYA yok"
fi

baslik "Son hatalar (loglar, son $HATA_N satir)"
for l in web bot yedek; do
    d=$VERI/log/$l.log
    [ -f "$d" ] || continue
    n=$(grep -ciE 'error|hata|traceback|exception|critical' "$d" 2>/dev/null || echo 0)
    echo "  -- $l.log ($(du -h "$d" | cut -f1), son degisme: $(date -r "$d" '+%Y-%m-%d %H:%M'), toplam hata satiri: $n)"
    grep -iE 'error|hata|traceback|exception|critical' "$d" 2>/dev/null | tail -n "$HATA_N" | sed 's/^/     /'
done
echo "  -- journal (son 5):"
journalctl -u kanit-web -u kanit-bot -n 5 --no-pager -o short 2>/dev/null | sed 's/^/     /' || true

baslik "Sonuc"
if [ "$SORUN" = 0 ]; then ok "sorun yok"; else printf '  \033[1;31m%d sorun\033[0m - yukaridaki SORUN satirlarina bakin (ISLETME.md, bolum 4)\n' "$SORUN"; fi
exit $(( SORUN > 0 ? 1 : 0 ))
