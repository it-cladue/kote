"""Sunucu ayarları; gerçek sırlar yalnızca ortam veya .env üzerinden alınır."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.getenv('PANEL_VERI', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)

def _tam_sayi(ad, varsayilan, en_az=0):
    """Ortamdan tam sayı okur; boş ya da geçersiz değerde varsayılanı kullanır (sunucu çökmez)."""
    ham = str(os.getenv(ad, '') or '').strip()
    if not ham:
        return varsayilan
    try:
        deger = int(float(ham))
    except (TypeError, ValueError, OverflowError):
        return varsayilan
    return max(en_az, deger)

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
        'GYAZO_PROXY': os.getenv('GYAZO_PROXY', '1'), 'MAX_GORSEL_BYTES': 10 * 1024 * 1024,
        # Görsel önbelleği sınırları: tmp/gyazo için MB ve gün, tmp/thumbs için MB. 0 = sınır yok.
        # Gyazo kopyaları tek kaynağı Gyazo olan kayıtların sunucudaki tek kopyasıdır: varsayılan yaş sınırı yok (0), boyut 2000 MB;
        # boyut dolunca yine en eski (en uzun süre görüntülenmeyen) silinir.
        'GYAZO_ONBELLEK_MB': _tam_sayi('GYAZO_ONBELLEK_MB', 2000),
        'GYAZO_ONBELLEK_GUN': _tam_sayi('GYAZO_ONBELLEK_GUN', 0),
        'KUCUK_ONBELLEK_MB': _tam_sayi('KUCUK_ONBELLEK_MB', 300),
        # 2.3.1 — Onaysız kayıt görünürlüğü (kt yetkisi olmayan kullanıcı için): 'uyar' (varsayılan; kırmızı rozet ve şerit)
        # ya da 'gizle' (onaysız kayıtlar liste/arama/ayrıntı/çıktıda hiç görünmez). Başka değer 'uyar' sayılır.
        'ONAYSIZ_GORUNUM': 'gizle' if str(os.getenv('ONAYSIZ_GORUNUM', '') or '').strip().lower() == 'gizle' else 'uyar',
        # 2.3.1 — Hatırlatma bildirimleri: yaş eşiği (gün), tekrar aralığı (gün), arka plan kontrol sıklığı (dk; 0 = kapalı),
        # bir çalıştırmada kullanıcı başına en çok kayıt hatırlatması (aşan kısım proje özetine katlanır).
        'HATIRLATMA_GUN': _tam_sayi('HATIRLATMA_GUN', 3, en_az=1),
        'HATIRLATMA_TEKRAR_GUN': _tam_sayi('HATIRLATMA_TEKRAR_GUN', 3, en_az=1),
        'HATIRLATMA_KONTROL_DK': _tam_sayi('HATIRLATMA_KONTROL_DK', 30),
        'HATIRLATMA_GUNLUK_SINIR': _tam_sayi('HATIRLATMA_GUNLUK_SINIR', 50, en_az=1),
    }

AYAR = settings()
