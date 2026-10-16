#!/usr/bin/env bash
# Kanit Merkezi - sunucu kurulumu (Ubuntu 24.04 + Plesk Obsidian, root ile calistirilir).
# Tekrar calistirilabilir (idempotent): var olani bozmaz, eksigi tamamlar.
#
# Kullanim:
#   bash deploy/kur.sh                         # kaynak: bu depo (deploy/../) /opt/kanit/src'ye KOPYALANIR
#   bash deploy/kur.sh --repo <git-url> [--dal <dal>]   # kaynak: git clone <url> /opt/kanit/src
#   KANIT_REPO=<git-url> bash deploy/kur.sh    # ayni sey, ortam degiskeniyle
#   KANIT_KUR_DRY=1 bash deploy/kur.sh         # KURU CALISMA: ne yapacagini yazar, hicbir sey degistirmez
#
# Secenekler / ortam degiskenleri:
#   --admin AD        ilk super admin kullanici adi (varsayilan: admin; KANIT_ADMIN)
#   --port N          web portu (.env ilk yazilirken; varsayilan 8080; KANIT_PORT)
#   --sessiz          hicbir sey sorma (TELEGRAM_TOKEN vb. .env'de yer tutucu kalir)
#   --bot-baslat      botu da hemen baslat (normalde veri aktarimi bitene kadar baslatilmaz)
#
# Yerlesim:
#   /opt/kanit/src        depo (git clone ya da kopya); uygulama /opt/kanit/src/kanit
#   /opt/kanit/venv       Python sanal ortami (python3.12 sistem yorumlayicisi)
#   /opt/kanit/veri       veritabani, gorseller, onbellek, yedek, log  (sahibi kanit, 0750)
#   /opt/kanit/gelen      Windows'tan gelen dosyalar (Excel, durum dosyalari, gorseller.zip)
#   /opt/kanit/.env       tokenlar ve ayarlar (sahibi kanit, 0600)
#   /etc/systemd/system/kanit-web.service, kanit-bot.service
#   /etc/cron.d/kanit-yedek   her gece 03:15 deploy/yedekle.sh
#   /etc/logrotate.d/kanit    veri/log/*.log haftalik dondurme
set -euo pipefail

KOK=${KANIT_KOK:-/opt/kanit}          # test/deneme icin degistirilebilir
SRC=$KOK/src
VENV=$KOK/venv
VERI=$KOK/veri
GELEN=$KOK/gelen
ENV_DOSYA=$KOK/.env
KULLANICI=${KANIT_KULLANICI:-kanit}
KURU=${KANIT_KUR_DRY:-0}
REPO=${KANIT_REPO:-}
DAL=${KANIT_DAL:-}
ADMIN_AD=${KANIT_ADMIN:-admin}
PORT=${KANIT_PORT:-8080}
SESSIZ=0
BOT_BASLAT=0
BURASI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)   # deploy/
DEPO_KOKU=$(cd "$BURASI/.." && pwd)                     # deploy/../ (kanit/ ve deploy/ burada)

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO=$2; shift 2 ;;
        --dal) DAL=$2; shift 2 ;;
        --admin) ADMIN_AD=$2; shift 2 ;;
        --port) PORT=$2; shift 2 ;;
        --sessiz) SESSIZ=1; shift ;;
        --bot-baslat) BOT_BASLAT=1; shift ;;
        --kuru) KURU=1; shift ;;
        -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
        *) echo "Bilinmeyen secenek: $1" >&2; exit 2 ;;
    esac
done

# ---------------------------------------------------------------- yardimcilar
bilgi() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
uyar()  { printf '\033[1;33m !!\033[0m %s\n' "$*" >&2; }
hata()  { printf '\033[1;31mHATA:\033[0m %s\n' "$*" >&2; exit 1; }

# calistir: normalde komutu yazar ve calistirir; kuru modda yalnizca yazar.
calistir() {
    if [ "$KURU" = 1 ]; then
        printf '  [KURU] %s\n' "$*"
    else
        printf '  + %s\n' "$*"
        "$@"
    fi
}

# kanit kullanicisi olarak calistir (HOME ayarli; nologin kabugu sorun degil)
kanit_olarak() {
    if [ "$KURU" = 1 ]; then
        printf '  [KURU] (kanit olarak) %s\n' "$*"
    else
        printf '  + (kanit olarak) %s\n' "$*"
        runuser -u "$KULLANICI" -- env HOME="$KOK" "$@"
    fi
}

# dosya_yaz HEDEF SAHIP IZIN < icerik  : icerik stdin'den gelir; kuru modda yalnizca bildirir
dosya_yaz() {
    local hedef=$1 sahip=$2 izin=$3 icerik
    icerik=$(cat)
    if [ "$KURU" = 1 ]; then
        printf '  [KURU] dosya yazilacak: %s (%s, %s, %d satir)\n' "$hedef" "$sahip" "$izin" "$(printf '%s\n' "$icerik" | wc -l)"
        return 0
    fi
    printf '  + dosya: %s\n' "$hedef"
    printf '%s\n' "$icerik" > "$hedef"
    chown "$sahip" "$hedef"
    chmod "$izin" "$hedef"
}

# kopyala_degistiyse KAYNAK HEDEF SAHIP IZIN : ayni ise dokunmaz, -> 0 degisti / 1 ayni
kopyala_degistiyse() {
    local kaynak=$1 hedef=$2 sahip=$3 izin=$4
    if [ -f "$hedef" ] && cmp -s "$kaynak" "$hedef"; then
        printf '  = ayni: %s\n' "$hedef"
        return 1
    fi
    calistir install -o "${sahip%%:*}" -g "${sahip##*:}" -m "$izin" "$kaynak" "$hedef"
    return 0
}

sor() {   # sor DEGISKEN "soru" [varsayilan] [gizli]
    local -n _hedef=$1; local soru=$2 vars=${3:-} gizli=${4:-0} cevap
    if [ "$SESSIZ" = 1 ] || [ ! -t 0 ]; then _hedef=$vars; return 0; fi
    if [ "$gizli" = 1 ]; then
        read -r -s -p "$soru${vars:+ [$vars]}: " cevap; echo
    else
        read -r -p "$soru${vars:+ [$vars]}: " cevap
    fi
    _hedef=${cevap:-$vars}
}

sunucu_ip() {
    local ip
    ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") print $(i+1); exit}') || true
    [ -n "${ip:-}" ] || ip=$(hostname -I 2>/dev/null | awk '{print $1}') || true
    echo "${ip:-SUNUCU-IP}"
}

# ---------------------------------------------------------------- on kontroller
if [ "$KURU" = 1 ]; then
    bilgi "KURU CALISMA: hicbir sey degistirilmeyecek, yalnizca yapilacaklar yazilacak."
elif [ "$(id -u)" != 0 ]; then
    hata "root olarak calistirin: sudo bash $0"
fi

if [ -z "$REPO" ] && [ ! -f "$DEPO_KOKU/kanit/requirements.txt" ]; then
    hata "Kaynak bulunamadi: ne --repo verildi ne de $DEPO_KOKU/kanit/requirements.txt var."
fi

if [ "$KURU" != 1 ] && [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
        ubuntu|debian) ;;
        *) uyar "Bu betik Ubuntu/Debian icindir (bulunan: ${ID:-?}). apt adimlari basarisiz olabilir." ;;
    esac
fi

# ---------------------------------------------------------------- 1) paketler
bilgi "1/9 Sistem paketleri"
EKSIK=()
for p in python3 python3-venv python3-pip git rsync curl unzip logrotate; do
    if ! dpkg -s "$p" >/dev/null 2>&1; then EKSIK+=("$p"); fi
done
if [ ${#EKSIK[@]} -gt 0 ]; then
    calistir env DEBIAN_FRONTEND=noninteractive apt-get update -qq
    calistir env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${EKSIK[@]}"
else
    echo "  = paketler tamam"
fi
PY=$(command -v python3.12 || command -v python3 || true)
[ -n "$PY" ] || { [ "$KURU" = 1 ] && PY=/usr/bin/python3; }
[ -n "$PY" ] || hata "python3 bulunamadi"
echo "  = python: $PY ($("$PY" --version 2>/dev/null || echo '?'))"

# ---------------------------------------------------------------- 2) kullanici + klasorler
bilgi "2/9 Kullanici '$KULLANICI' ve klasorler"
if id "$KULLANICI" >/dev/null 2>&1; then
    echo "  = kullanici var"
else
    calistir useradd --system --home-dir "$KOK" --no-create-home --shell /usr/sbin/nologin --comment "Kanit Merkezi" "$KULLANICI"
fi
calistir install -d -o root -g root -m 0755 "$KOK"
calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0750 "$VERI" "$VERI/log" "$VERI/yedek" "$VERI/gorseller" "$VERI/onbellek" "$VERI/gecici"
calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0770 "$GELEN"
# ice-aktar VERI/gelen'i de kullanabilir: tek klasor olsun
if [ ! -e "$VERI/gelen" ]; then
    calistir ln -s "$GELEN" "$VERI/gelen"
elif [ -d "$VERI/gelen" ] && [ ! -L "$VERI/gelen" ]; then
    echo "  = $VERI/gelen gercek klasor; oldugu gibi birakildi"
fi

# ---------------------------------------------------------------- 3) kaynak kod
bilgi "3/9 Kaynak kod -> $SRC"
if [ -n "$REPO" ]; then
    if [ -d "$SRC/.git" ]; then
        echo "  = git deposu var, guncelleniyor"
        kanit_olarak git -C "$SRC" fetch --quiet origin
        if [ -n "$DAL" ]; then kanit_olarak git -C "$SRC" checkout --quiet "$DAL"; fi
        kanit_olarak git -C "$SRC" pull --ff-only --quiet
    else
        [ -e "$SRC" ] && [ "$KURU" != 1 ] && hata "$SRC var ama git deposu degil; silin ya da --repo vermeden kopya modunu kullanin."
        calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0755 "$SRC"
        if [ -n "$DAL" ]; then
            kanit_olarak git clone --quiet --branch "$DAL" "$REPO" "$SRC"
        else
            kanit_olarak git clone --quiet "$REPO" "$SRC"
        fi
    fi
    dosya_yaz "$KOK/kaynak.txt" root:root 0644 <<EOF
git $REPO${DAL:+ $DAL}
EOF
else
    echo "  = kopya modu: $DEPO_KOKU -> $SRC"
    calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0755 "$SRC"
    for alt in kanit deploy; do
        [ -d "$DEPO_KOKU/$alt" ] || continue
        calistir rsync -a --delete --exclude '__pycache__' --exclude '.git' --exclude '*.pyc' \
            --chown="$KULLANICI:$KULLANICI" "$DEPO_KOKU/$alt/" "$SRC/$alt/"
    done
    [ -f "$DEPO_KOKU/README.md" ] && calistir install -o "$KULLANICI" -g "$KULLANICI" -m 0644 "$DEPO_KOKU/README.md" "$SRC/README.md"
    dosya_yaz "$KOK/kaynak.txt" root:root 0644 <<EOF
kopya $DEPO_KOKU
EOF
fi
# Betikler calistirilabilir olsun
for b in kur.sh guncelle.sh yedekle.sh geri-yukle.sh kontrol.sh; do
    [ -f "$SRC/deploy/$b" ] && calistir chmod 0755 "$SRC/deploy/$b"
done
# Kurulumdan sonra deploy betikleri hep /opt/kanit/src/deploy altindan calisir
# (birim ve ornek dosyalari oradan, yoksa bu betigin yanindan okunur)
DEPLOY=$SRC/deploy

# ---------------------------------------------------------------- 4) venv + bagimliliklar
bilgi "4/9 Sanal ortam $VENV"
if [ -x "$VENV/bin/python" ]; then
    echo "  = venv var"
else
    calistir install -d -o "$KULLANICI" -g "$KULLANICI" -m 0755 "$VENV"
    kanit_olarak "$PY" -m venv "$VENV"
fi
kanit_olarak "$VENV/bin/python" -m pip install --quiet --upgrade pip
kanit_olarak "$VENV/bin/python" -m pip install --quiet -r "$SRC/kanit/requirements.txt"

# ---------------------------------------------------------------- 5) .env
bilgi "5/9 Ayar dosyasi $ENV_DOSYA"
if [ -f "$ENV_DOSYA" ]; then
    echo "  = var, dokunulmadi (duzenlemek icin: nano $ENV_DOSYA; sonra systemctl restart kanit-web kanit-bot)"
    calistir chown "$KULLANICI:$KULLANICI" "$ENV_DOSYA"
    calistir chmod 0600 "$ENV_DOSYA"
else
    ORNEK=$DEPLOY/env.ornek
    [ -f "$ORNEK" ] || ORNEK=$BURASI/env.ornek
    [ -f "$ORNEK" ] || hata "env.ornek bulunamadi"
    TG_TOKEN=BURAYA_TELEGRAM_BOT_TOKEN; GY_TOKEN=BURAYA_GYAZO_TOKEN; BOT_SIFRE=BURAYA_UYE_SIFRESI; ADMIN_IDS=
    if [ "$SESSIZ" != 1 ] && [ -t 0 ]; then
        echo "  Tokenlar sorulacak; bos birakirsaniz yer tutucu kalir, sonra nano $ENV_DOSYA ile yazarsiniz."
        echo "  ONEMLI: Gecis bitene kadar TEST botunun token'ini verin (eski Windows botu ile ayni token iki yerde calisamaz)."
        sor TG_TOKEN  "TELEGRAM_TOKEN (test botu)" "$TG_TOKEN" 1
        sor GY_TOKEN  "GYAZO_TOKEN" "$GY_TOKEN" 1
        sor BOT_SIFRE "BOT_PASSWORD (uyelerin ortak sifresi)" "$BOT_SIFRE" 1
        sor ADMIN_IDS "ADMIN_IDS (Telegram ID'leri, virgulle)" "$ADMIN_IDS"
    fi
    ICERIK=$(sed -e "s|^TELEGRAM_TOKEN=.*|TELEGRAM_TOKEN=$TG_TOKEN|" \
                 -e "s|^GYAZO_TOKEN=.*|GYAZO_TOKEN=$GY_TOKEN|" \
                 -e "s|^BOT_PASSWORD=.*|BOT_PASSWORD=$BOT_SIFRE|" \
                 -e "s|^ADMIN_IDS=.*|ADMIN_IDS=$ADMIN_IDS|" \
                 -e "s|^PORT=.*|PORT=$PORT|" \
                 -e "s|^VERI=.*|VERI=$VERI|" "$ORNEK")
    printf '%s\n' "$ICERIK" | dosya_yaz "$ENV_DOSYA" "$KULLANICI:$KULLANICI" 0600
fi

# ---------------------------------------------------------------- 6) systemd
bilgi "6/9 systemd birimleri"
DEGISTI=0
for u in kanit-web.service kanit-bot.service; do
    kaynak=$DEPLOY/$u
    [ -f "$kaynak" ] || kaynak=$BURASI/$u
    [ -f "$kaynak" ] || hata "$u bulunamadi"
    if kopyala_degistiyse "$kaynak" "/etc/systemd/system/$u" root:root 0644; then DEGISTI=1; fi
done
if [ "$DEGISTI" = 1 ] || [ "$KURU" = 1 ]; then calistir systemctl daemon-reload; fi
calistir systemctl enable --quiet kanit-web.service
if [ "$KURU" != 1 ] && systemctl is-active --quiet kanit-web.service; then
    calistir systemctl restart kanit-web.service
else
    calistir systemctl start kanit-web.service
fi
if [ "$BOT_BASLAT" = 1 ]; then
    calistir systemctl enable --quiet --now kanit-bot.service
    BOT_DURUM="su an ACIK"
elif [ "$KURU" != 1 ] && systemctl is-enabled --quiet kanit-bot.service 2>/dev/null; then
    BOT_DURUM="daha once acilmis, oyle kaldi"           # tekrar kurulumda dokunma
else
    calistir systemctl disable --quiet kanit-bot.service 2>/dev/null || true   # ilk kurulumda bot bilerek kapali
    BOT_DURUM="su an KAPALI"
fi

# ---------------------------------------------------------------- 7) cron + logrotate
bilgi "7/9 Gece yedegi (cron 03:15) ve log dondurme"
dosya_yaz /etc/cron.d/kanit-yedek root:root 0644 <<EOF
# Kanit Merkezi: her gece 03:15 veritabani + gorsel yedegi (30 gun yerel, rclone.conf varsa uzak kopya)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 3 * * * root $DEPLOY/yedekle.sh >> $VERI/log/yedek.log 2>&1
EOF
dosya_yaz /etc/logrotate.d/kanit root:root 0644 <<EOF
$VERI/log/*.log {
    weekly
    rotate 12
    missingok
    notifempty
    compress
    delaycompress
    copytruncate
    su $KULLANICI $KULLANICI
}
EOF

# ---------------------------------------------------------------- 8) guvenlik duvari
bilgi "8/9 TCP $PORT portu"
PORT_ACIK=0
if command -v plesk >/dev/null 2>&1; then
    if plesk ext firewall --help >/dev/null 2>&1 || plesk ext firewall --list >/dev/null 2>&1; then
        if plesk ext firewall --list 2>/dev/null | grep -q "Kanit paneli"; then
            echo "  = Plesk guvenlik duvarinda 'Kanit paneli' kurali zaten var"
            PORT_ACIK=1
        else
            # Plesk Firewall uzantisi: kural ekle -> uygula -> onayla (onaylanmazsa 60 sn icinde geri alinir)
            calistir plesk ext firewall --add -name "Kanit paneli" -direction input -action allow -ports "$PORT/tcp"
            calistir plesk ext firewall --apply
            calistir plesk ext firewall --confirm
            PORT_ACIK=1
        fi
    else
        uyar "Plesk var ama Firewall uzantisi kurulu degil."
        echo "    Plesk > Uzantilar > 'Plesk Firewall' kurun, sonra:"
        echo "      plesk ext firewall --add -name 'Kanit paneli' -direction input -action allow -ports $PORT/tcp"
        echo "      plesk ext firewall --apply && plesk ext firewall --confirm"
        echo "    ya da arayuzden: Araclar ve Ayarlar > Guvenlik Duvari > Kural ekle > gelen, izin ver, TCP $PORT."
    fi
fi
if [ "$PORT_ACIK" = 0 ] && command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "^Status: active"; then
    calistir ufw allow "$PORT/tcp" comment "Kanit paneli"
    PORT_ACIK=1
fi
if [ "$PORT_ACIK" = 0 ]; then
    uyar "Port kendiliginden acilamadi. Plesk Firewall yoksa ve ufw kapaliysa port buyuk olasilikla zaten aciktir;"
    echo "    bulut saglayicinin (Hetzner/DigitalOcean/AWS) guvenlik grubunda da TCP $PORT'u acin."
    echo "    Kontrol: baska bir makineden  curl -sI http://$(sunucu_ip):$PORT/"
fi

# ---------------------------------------------------------------- 9) ilk super admin
bilgi "9/9 Ilk super admin ($ADMIN_AD) ve saglik kontrolu"
if [ "$KURU" = 1 ]; then
    printf '  [KURU] (kanit olarak) %s -m kanit kullanici-ekle %s admin\n' "$VENV/bin/python" "$ADMIN_AD"
    printf '  [KURU] (kanit olarak) %s -m kanit saglik\n' "$VENV/bin/python"
    ADMIN_CIKTI="(kuru calisma)"
else
    # bir-iki saniye: web ilk acilista semayi olusturur
    sleep 2
    set +e
    ADMIN_CIKTI=$(cd "$SRC/kanit" && runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" \
        "$VENV/bin/python" -m kanit kullanici-ekle "$ADMIN_AD" admin 2>&1)
    ADMIN_RC=$?
    set -e
    if [ $ADMIN_RC -ne 0 ]; then
        uyar "kullanici-ekle basarisiz (kullanici zaten var olabilir). Cikti:"
        printf '%s\n' "$ADMIN_CIKTI" | sed 's/^/    /'
        echo "    Sifre sifirlamak icin: cd $SRC/kanit && runuser -u kanit -- $VENV/bin/python -m kanit sifre-sifirla $ADMIN_AD"
        ADMIN_CIKTI="(kullanici zaten vardi; sifre degismedi)"
    fi
    set +e
    (cd "$SRC/kanit" && runuser -u "$KULLANICI" -- env HOME="$KOK" KANIT_ENV="$ENV_DOSYA" "$VENV/bin/python" -m kanit saglik) | sed 's/^/    /'
    set -e
fi

# ---------------------------------------------------------------- ozet
IP=$(sunucu_ip)
cat <<EOF

=====================================================================
KURULUM TAMAM
=====================================================================
Panel adresi      : http://$IP:$PORT
Ilk super admin   : $ADMIN_AD
kullanici-ekle ciktisi (gecici sifre burada; ilk giriste degistirilir):
$(printf '%s\n' "$ADMIN_CIKTI" | sed 's/^/    /')

Durum             : systemctl status kanit-web      (bot: kanit-bot, $BOT_DURUM)
Loglar            : tail -f $VERI/log/web.log  $VERI/log/bot.log
Ayarlar           : $ENV_DOSYA   (degisince: systemctl restart kanit-web kanit-bot)
Kaynak            : $(cat "$KOK/kaynak.txt" 2>/dev/null || echo "$SRC")
Hizli kontrol     : $DEPLOY/kontrol.sh

KONTROL LISTESI (sirayla):
 [ ] Tarayicidan http://$IP:$PORT acildi, '$ADMIN_AD' ile girildi, sifre degistirildi.
 [ ] Windows'tan veri yuklendi: scp ile Excel + durum dosyalari + gorseller.zip -> $GELEN
     (ayrintisi: $DEPLOY/ISLETME.md, bolum 2)
 [ ] Deneme aktarimi: cd $SRC/kanit && runuser -u kanit -- $VENV/bin/python -m kanit ice-aktar --kuru
 [ ] Gercek aktarim : ... -m kanit ice-aktar --uygula   (sonra panelde sayilari Excel ile karsilastirin)
 [ ] $ENV_DOSYA icinde TELEGRAM_TOKEN = TEST botu; sonra botu acin:
       systemctl enable --now kanit-bot && tail -f $VERI/log/bot.log
 [ ] Paralel hafta: test botuyla kayit, panelde onay; sorun yoksa gecis sirasi (ISLETME.md, bolum 3).
 [ ] Gece yedegi: /etc/cron.d/kanit-yedek (03:15). Ilk yedegi elle deneyin: $DEPLOY/yedekle.sh
 [ ] Alan adi / HTTPS isteniyorsa: $DEPLOY/nginx-plesk.md
=====================================================================
EOF
