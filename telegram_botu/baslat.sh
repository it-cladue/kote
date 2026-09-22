#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if grep -q "BURAYA_BOT_TOKEN\|BURAYA_GUCLU_ADMIN_SIFRESI" config.txt; then
  echo "HATA: Once config.txt icindeki TOKEN ve PASSWORD alanlarini doldurun."
  exit 1
fi

mkdir -p images backups complaints/images screenshots
python3 -m pip install -q -r requirements.txt
exec python3 bot.py
