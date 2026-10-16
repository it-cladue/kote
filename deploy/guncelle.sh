#!/usr/bin/env bash
# Kanit Merkezi - guncelleme (root): kaynagi yeniler, bagimliliklari kurar, iki servisi yeniden baslatir,
# saglik kontrolu yapar, son log satirlarini gosterir.
#   /opt/kanit/src/deploy/guncelle.sh            # kaynak /opt/kanit/kaynak.txt'den (git ya da kopya)
#   /opt/kanit/src/deploy/guncelle.sh --dal DAL  # git modunda baska dala gec
#   KANIT_KUR_DRY=1 ... guncelle.sh              # kuru calisma
set -euo pipefail

KOK=${KANIT_KOK:-/opt/kanit}          # test/deneme icin degistirilebilir
SRC=$KOK/src
VENV=$KOK/venv
VERI=$KOK/veri
ENV_DOSYA=$KOK/.env
KULLANICI=${KANIT_KULLANICI:-kanit}
KURU=${KANIT_KUR_DRY:-0}
DAL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --dal) DAL=$2; shift 2 ;;
        --kuru) KURU=1; shift ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "Bilinmeyen secenek: $1" >&2; exit 2 ;;
    esac
done

bilgi() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
uyar()  { printf '\033[1;33m !!\033[0m %s\n' "$*" >&2; }
hata()  { printf '\033[1;31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }
calistir() { if [ "$KURU" = 1 ]; then printf '  [KURU] %s\n' "$*"; else printf '  + %s\n' "$*"; "$@"; fi; }
kanit_olarak() {
    if [ "$KURU" = 1 ]; then printf '  [KURU] (kanit olarak) %s\n' "$*"; else
        printf '  + (kanit olarak) %s\n' "$*"; runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$@"; fi
}

[ "$KURU" = 1 ] || [ "$(id -u)" = 0 ] || hata "root olarak calistirin"
[ -f "$KOK/kaynak.txt" ] || hata "$KOK/kaynak.txt yok; once deploy/kur.sh calistirin"
read -r MOD KAYNAK EKDAL < "$KOK/kaynak.txt"
[ -n "$DAL" ] || DAL=${EKDAL:-}

bilgi "1/5 Kaynak ($MOD: $KAYNAK)"
case "$MOD" in
    git)
        kanit_olarak git -C "$SRC" fetch --quiet origin
        if [ -n "$DAL" ]; then kanit_olarak git -C "$SRC" checkout --quiet "$DAL"; fi
        kanit_olarak git -C "$SRC" pull --ff-only --quiet
        echo "  = surum: $(git -C "$SRC" log -1 --format='%h %ci %s' 2>/dev/null || echo '?')"
        ;;
    kopya)
        [ -d "$KAYNAK/kanit" ] || hata "Kopya kaynagi yok: $KAYNAK/kanit (yeni surumu once oraya koyun)"
        for alt in kanit deploy; do
            [ -d "$KAYNAK/$alt" ] || continue
            calistir rsync -a --delete --exclude '__pycache__' --exclude '.git' --exclude '*.pyc' \
                --chown="$KULLANICI:$KULLANICI" "$KAYNAK/$alt/" "$SRC/$alt/"
        done
        ;;
    *) hata "kaynak.txt anlasilamadi: $MOD" ;;
esac
for b in kur.sh guncelle.sh yedekle.sh geri-yukle.sh kontrol.sh; do
    [ -f "$SRC/deploy/$b" ] && calistir chmod 0755 "$SRC/deploy/$b"
done

bilgi "2/5 Bagimliliklar"
kanit_olarak "$VENV/bin/python" -m pip install --quiet -r "$SRC/kanit/requirements.txt"

bilgi "3/5 systemd birimleri (degistiyse)"
DEGISTI=0
for u in kanit-web.service kanit-bot.service; do
    if ! cmp -s "$SRC/deploy/$u" "/etc/systemd/system/$u"; then
        calistir install -o root -g root -m 0644 "$SRC/deploy/$u" "/etc/systemd/system/$u"; DEGISTI=1
    fi
done
[ "$DEGISTI" = 1 ] && calistir systemctl daemon-reload

bilgi "4/5 Servisler yeniden baslatiliyor"
calistir systemctl restart kanit-web.service
if systemctl is-enabled --quiet kanit-bot.service 2>/dev/null; then
    calistir systemctl restart kanit-bot.service
else
    echo "  = kanit-bot etkin degil (veri aktarimi bitince: systemctl enable --now kanit-bot)"
fi
[ "$KURU" = 1 ] || sleep 3

bilgi "5/5 Saglik"
if [ "$KURU" != 1 ]; then
    for u in kanit-web kanit-bot; do
        printf '  %-10s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || true)"
    done
    set +e
    (cd "$SRC/kanit" && runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" -m kanit saglik) | sed 's/^/    /'
    RC=${PIPESTATUS[0]}
    set -e
    [ "$RC" = 0 ] || uyar "saglik komutu $RC ile cikti; loglara bakin"
    for l in web bot; do
        echo "---- $VERI/log/$l.log (son 20 satir) ----"
        tail -n 20 "$VERI/log/$l.log" 2>/dev/null || echo "(yok)"
    done
else
    printf '  [KURU] (kanit olarak) %s -m kanit saglik; tail -n 20 %s/log/{web,bot}.log\n' "$VENV/bin/python" "$VERI"
fi
echo "Guncelleme tamam."
