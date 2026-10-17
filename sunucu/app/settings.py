"""Sunucu ayarları; gerçek sırlar yalnızca ortam veya .env üzerinden alınır."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.getenv('PANEL_VERI', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)

def settings():
    media = Path(os.getenv('GORSEL_KLASOR', str(DATA / 'gorseller'))).resolve()
    archive = Path(os.getenv('ARSIV_KLASOR', str(DATA / 'telegram_gorseller'))).resolve()
    media.mkdir(parents=True, exist_ok=True)
    return {
        'BOT_KLASOR': str(DATA), 'DB': str(DATA / 'panel.db'),
        'GORSEL_KLASOR': str(media), 'ARSIV_KLASOR': str(archive),
        'EK_GORSEL_KLASORLERI': [str(archive)], 'ONBELLEK': str(DATA / 'tmp'),
        'LOG_DOSYA': str(DATA / 'bot_log.txt'), 'HTTPS': os.getenv('HTTPS', '0'),
        'PORT': int(os.getenv('PORT', '8080')), 'DINLE': os.getenv('DINLE', '127.0.0.1'),
        'TRUST_PROXY': os.getenv('TRUST_PROXY', '0'),
        'PROJELER': ['PP', 'PA', 'OF', 'HI', 'VI', 'GA', 'BETA'], 'SAYFA_BOYU': 48,
        'PROJE_RENK': {'PP': '#A6A6A6', 'PA': '#4472C4', 'OF': '#FFFF00', 'HI': '#FF0000', 'VI': '#7030A0', 'GA': '#00B050', 'BETA': '#FFA500'},
        'GYAZO_PROXY': '0', 'MAX_GORSEL_BYTES': 10 * 1024 * 1024,
    }

AYAR = settings()
