#!/usr/bin/env bash
# Kullanıcının kendi Ubuntu/Debian sunucusunda çalıştıracağı isteğe bağlı kurulum.
set -Eeuo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/opt/kanit-paneli
if [[ $EUID -ne 0 ]]; then echo 'Bu betiği sudo bash deploy/setup-linux.sh ile çalıştırın.' >&2; exit 1; fi
if [[ ! -f "$BASE/.env" ]]; then echo '.env.example dosyasını .env olarak kopyalayıp token ve parolaları önce doldurun.' >&2; exit 1; fi
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip
id kanit >/dev/null 2>&1 || useradd --system --home-dir "$DEST" --shell /usr/sbin/nologin kanit
install -d -m 755 "$DEST"
if [[ "$BASE" != "$DEST" ]]; then
  # Çalışma verileri ve mevcut .env asla ezilmez.
  tar -C "$BASE" --exclude='./data' --exclude='./.env' --exclude='./.venv' --exclude='./.git' --exclude='./.pytest_cache' --exclude='__pycache__' -cf - . | tar -C "$DEST" -xf -
  if [[ ! -f "$DEST/.env" ]]; then install -m 640 -o root -g kanit "$BASE/.env" "$DEST/.env"; fi
fi
chown root:kanit "$DEST/.env"; chmod 640 "$DEST/.env"
install -d -m 700 -o kanit -g kanit "$DEST/data" "$DEST/data/gorseller" "$DEST/data/telegram_gorseller"
python3 -m venv "$DEST/.venv"
"$DEST/.venv/bin/python" -m pip install -r "$DEST/requirements.txt"
install -m 644 "$DEST/deploy/kanit-web.service" /etc/systemd/system/kanit-web.service
install -m 644 "$DEST/deploy/kanit-bot.service" /etc/systemd/system/kanit-bot.service
systemctl daemon-reload
cat <<'END'
Kurulum hazır; servisler henüz başlatılmadı.
1) cd /opt/kanit-paneli
2) sudo -u kanit .venv/bin/python -m app.cli admin-ekle admin
3) Eski veriyi ice-aktar /ESKI_KLASOR, arşivi arsiv-tara ile taşı.
4) sudo systemctl enable --now kanit-web kanit-bot
5) journalctl -u kanit-bot -n 80 --no-pager
Alan adı/HTTPS için README ve Nginx örneğini uygula. Aynı tokenı eski botta açık bırakma.
END
