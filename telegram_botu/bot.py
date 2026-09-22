# =====================================================================
# HitBet VIP Bot - Gelistirilmis Surum
# Ayrik Python uygulamasi (python-telegram-bot)
# Bolumler: Kullanici arayuzu | Foto/video kampanya | Toplu mesaj sihirbazi
#           Sikayet sistemi | Ban arayuzu | Haftalik yedek | Loglar
#           Zamanli mesaj | Sablonlar | Tekil mesaj | Buton istatistigi
# =====================================================================

import logging, asyncio, sys, os, time, sqlite3, threading, re, shutil, csv, hmac, hashlib, base64
from datetime import datetime, timedelta

# Unix tabanli sistemlerde yeni dosya ve klasorler yalnizca bot kullanicisina acilir.
try:
    os.umask(0o077)
except (AttributeError, OSError):
    pass
from functools import wraps
from collections import defaultdict
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
    ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton, BotCommandScopeDefault, BotCommandScopeChat,
    BotCommandScopeAllPrivateChats, MenuButtonWebApp, MenuButtonCommands, WebAppInfo)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler)
from telegram.constants import ParseMode

# === DIZINLER ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "images")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
COMPLAINTS_DIR = os.path.join(BASE_DIR, "complaints")
COMPLAINTS_IMG_DIR = os.path.join(COMPLAINTS_DIR, "images")
DATA_DIR = os.path.join(BASE_DIR, "data")
# Ekran goruntusu kayitlari: dosya adi = kategori + tarih + kullanicinin girdigi bilgiler.
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
for d in (IMAGES_DIR, BACKUP_DIR, COMPLAINTS_DIR, COMPLAINTS_IMG_DIR, DATA_DIR, SCREENSHOTS_DIR):
    os.makedirs(d, exist_ok=True)
for _ozel in (DATA_DIR, SCREENSHOTS_DIR):
    try:
        os.chmod(_ozel, 0o700)
    except OSError:
        pass
COMPLAINTS_LOG = os.path.join(COMPLAINTS_DIR, "sikayetler.txt")
SITE_ID_CSV = os.path.join(DATA_DIR, "site_id_kayitlari.csv")
SITE_ID_XLSX = os.path.join(DATA_DIR, "site_id_kayitlari.xlsx")
SCREENSHOTS_CSV = os.path.join(SCREENSHOTS_DIR, "ekran_goruntuleri.csv")

# === CONFIG OKU ===
config = {}
try:
    with open(os.path.join(BASE_DIR, "config.txt"), "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
except Exception as e:
    print(f"HATA: config.txt okunamadi! {e}")
    input("Enter..."); sys.exit(1)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", config.get("TOKEN", "")).strip()
ADMIN_PASSWORD_HASH = os.getenv("TELEGRAM_ADMIN_PASSWORD_HASH", config.get("PASSWORD_HASH", "")).strip()
_valid_password_hash = ADMIN_PASSWORD_HASH.startswith("pbkdf2_sha256$")
CONFIG_READY = bool(BOT_TOKEN and "BURAYA" not in BOT_TOKEN and _valid_password_hash)

BOT_NAME = config.get("BOT_NAME", "HitBet VIP Bot")
# Calisan surumu ayirt etmek icin: acilis ekraninda ve admin panelinde gorunur.
BOT_VERSION = ""  # gorunur surum kullanilmiyor (istek: bota versiyon verilmesin)

# === GUVENLIK SABITLERI ===
# Spam: kisa surede ardarda mesaj (5 mesaj / 3 saniye) -> 30dk engel
SPAM_WINDOW = 3            # saniye
SPAM_COUNT = 5            # bu kadar mesaj/pencerede spam
TEMP_BAN_MINUTES = 30     # gecici engel suresi
SAME_CMD_COUNT = 5        # ayni komut kisa surede bu kadar kez -> spam (menuye hizli basanlar banlanmasin)
SAME_CMD_WINDOW = 5       # saniye
STRIKES_FOR_PERMA = 3     # 3 kez gecici ban yiyen -> kalici ban
MAX_LOGIN_ATTEMPTS = 3
LOGIN_BLOCK_DURATION = 900
MAX_INPUT_LENGTH = 500
MAX_URL_LENGTH = 300
MAX_BROADCAST_LENGTH = 3000
MAX_CODE_LENGTH = 60
MAX_COMPLAINT_LENGTH = 1500
MIN_SITE_ID_LENGTH = 2
MAX_SITE_ID_LENGTH = 64
SITE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
# Yonetici oturumlari varsayilan 15 dakikada sona erer; config.txt ile degistirilebilir.
try:
    ADMIN_SESSION_TIMEOUT = max(60, int(config.get("ADMIN_SESSION_MINUTES", "15")) * 60)
except (TypeError, ValueError):
    ADMIN_SESSION_TIMEOUT = 900

# === VARSAYILAN LINK / BUTON / METIN ===
DEFAULT_REGISTER_LINK = config.get("REGISTER_LINK", "https://example.com/register")
DEFAULT_GIRIS_LINK    = config.get("LOGIN_LINK", "https://example.com/login")
DEFAULT_BONUS_LINK    = config.get("ACTIVATE_LINK", "https://example.com/campaign")
DEFAULT_SUPPORT_LINK  = config.get("SUPPORT_LINK", "https://t.me/example_support")
DEFAULT_PROMO_IMAGE   = config.get("CAMPAIGN_MEDIA_URL", "")

DEFAULT_REGISTER_BTN = config.get("REGISTER_BUTTON_TEXT", "\U0001f525 Hemen \u00dcye Ol")
DEFAULT_GIRIS_BTN    = config.get("LOGIN_BUTTON_TEXT", "\U0001f517 G\u00fcncel Giri\u015f")
DEFAULT_BONUS_BTN    = config.get("ACTIVATE_BUTTON_TEXT", "\U0001f381 Aktif Et")
DEFAULT_SUPPORT_BTN  = "\U0001f4ac Canl\u0131 Destek"

DEFAULT_WELCOME = config.get("WELCOME_TEXT", "Merhaba {name} \U0001f44b\n\nHo\u015fgeldin bonusunu ald\u0131n m\u0131?").replace("\\n", "\n").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
DEFAULT_CAMPAIGN_TITLE = config.get("CAMPAIGN_TITLE", "G\u00fcn\u00fcn Kampanyas\u0131")
DEFAULT_PROMO_CAP = config.get("CAMPAIGN_CAPTION", "G\u00fcn\u00fcn kampanyas\u0131n\u0131 hemen aktif et!").replace("\\n", "\n")
DEFAULT_CAPTION_LINK_TEXT = config.get("CAPTION_LINK_TEXT", "")
DEFAULT_CAPTION_LINK_URL = config.get("CAPTION_LINK_URL", "")
DEFAULT_CAMPAIGN_CODE = config.get("CAMPAIGN_CODE", "")
DEFAULT_CAMPAIGN_CODE_STYLE = config.get("CAMPAIGN_CODE_STYLE", "copy")
DEFAULT_GIRIS_TITLE = "GUNCEL GIRIS LINKI"
PLAY_MENU_TEXT = (config.get("MENU_BUTTON_TEXT", "🎮 PLAY").strip() or "🎮 PLAY")[:64]
DEFAULT_GIRIS_TEXT  = "Guncel giri\u015f adresimize a\u015fa\u011f\u0131daki butondan ula\u015fabilirsiniz \U0001f447"

# === /START KAYIT AKISI (kullanici arayuzu) ===
# 1 yapilirsa kayitsiz kullaniciya /start'ta Site ID sorulur (Luks tarzi akis).
# 0 (varsayilan) Site ID adimi PASIF: herkes karsilama + kampanya gorur,
# Site ID yalnizca /profil menusunden girilir/degistirilir.
SITE_ID_ON_START = config.get("SITE_ID_ON_START", "0").strip() == "1"
# Karsilama gorseli: bos birakilirsa aktif kampanya medyasina, o da yoksa
# images/promo.jpg dosyasina duser; hicbiri yoksa yalniz metin gonderilir.
DEFAULT_WELCOME_MEDIA_URL = config.get("WELCOME_MEDIA_URL", "").strip()
# Kanal mesaji: CHANNEL_LINK bos birakilirsa bu mesaj hic gonderilmez.
DEFAULT_CHANNEL_LINK = config.get("CHANNEL_LINK", "").strip()
DEFAULT_CHANNEL_TEXT = config.get("CHANNEL_TEXT", "\U0001f449 Kanal\u0131m\u0131za abone ol").replace("\\n", "\n")
DEFAULT_SITE_ID_PROMPT = config.get("SITE_ID_PROMPT_TEXT",
    "Yeni bonuslar almak i\u00e7in Site ID'ni gir.").replace("\\n", "\n")
DEFAULT_REGISTER_LINK_TEXT = config.get("REGISTER_LINK_TEXT", "Kay\u0131t Linki")

# Yonetici ikinci dogrulamasi: 1 yapilirsa /admin sonrasinda parola istenir.
# 0 (varsayilan) beyaz liste + dogrudan oturum acar; mevcut davranis korunur.
ADMIN_REQUIRE_PASSWORD = config.get("ADMIN_REQUIRE_PASSWORD", "0").strip() == "1"

# PLAY butonu icin ayri adres; bos birakilirsa guncel giris linki kullanilir.
DEFAULT_PLAY_LINK = config.get("PLAY_LINK", "").strip()

# === EKRAN GORUNTUSU KAYDI ===
# Kullanici bota foto (ekran goruntusu) gonderince kategori secenekleri sunulur;
# sectigi kategori, gonderdigi tarih ve girdigi bilgiler (Site ID, arkadas ID...)
# dosya ADINA yazilarak screenshots/ klasorune kaydedilir. 0 = ozellik kapali.
SCREENSHOTS_ENABLED_DEFAULT = config.get("SCREENSHOTS_ENABLED", "1").strip() != "0"
# Kategori tanimi: anahtar:Buton Yazisi:Alan1|Alan2, ... (bos birakilirsa yerlesik liste)
BUILTIN_SCREENSHOT_CATEGORIES = (
    "arkadas:\U0001f465 Arkadaşını Getir:Site ID|Arkadaş ID, "
    "yatirim:\U0001f4b0 Para Yatırma:Site ID|Tutar, "
    "cekim:\U0001f4b8 Para Çekme:Site ID|Tutar, "
    "bonus:\U0001f381 Bonus Talebi:Site ID|Bonus Adı, "
    "diger:\U0001f4c4 Diğer:Site ID|Konu")
DEFAULT_SCREENSHOT_CATEGORIES = config.get("SCREENSHOT_CATEGORIES", "").strip() or BUILTIN_SCREENSHOT_CATEGORIES
# Dosya adi sablonu. Yer tutucular: {kategori} {tarih} {saat} {alanlar} {tgid} {kullanici} {alan1} {alan2}...
DEFAULT_SCREENSHOT_NAME_FORMAT = (config.get("SCREENSHOT_NAME_FORMAT", "").strip()
                                  or "{kategori}_{tarih}_{saat}_{alanlar}_{tgid}")
try:
    SCREENSHOT_DAILY_LIMIT = max(0, int(config.get("SCREENSHOT_DAILY_LIMIT", "10")))
except (TypeError, ValueError):
    SCREENSHOT_DAILY_LIMIT = 10
DEFAULT_SCREENSHOT_PROMPT = config.get("SCREENSHOT_PROMPT_TEXT",
    "Bu ekran görüntüsü ne için? Bir seçenek seç \U0001f447").replace("\\n", "\n")
SCREENSHOT_MAX_BYTES = 20 * 1024 * 1024   # Bot API dosya indirme siniri
SCREENSHOT_MAX_FIELDS = 6

# === ANA MENU (13 buton) VE ILGILI LINKLER ===
CAMPAIGN_CATEGORIES = {
    "bonus":    "\U0001f381 Güncel Bonuslar",
    "yeni_uye": "\U0001f195 Yeni Üye Bonusları",
    "slot":     "\U0001f3b0 Slot Kampanyaları",
    "spor":     "⚽ Spor Bonusları",
    "ozel":     "⭐ Bana Özel Kampanyalar",
    "turnuva":  "\U0001f3c6 Turnuvalar",
}
# Kampanya hedefleme segmentleri: manuel VIP kademeleri + OTOMATIK sanal
# segmentler (uyelik yasi / aktiflik uzerinden kendiliginden hesaplanir).
AUTO_SEGMENTS = {
    "yeni":  "\U0001f195 Yeni Üyeler (ilk 7 gün)",
    "aktif": "\U0001f553 Aktif Kullanıcılar (son 48 saat)",
}
def CAMPAIGN_SEGMENT_LABEL(key):
    return AUTO_SEGMENTS.get(key) or SEGMENTS.get(key) or key

DEFAULT_MINIAPP_LINK  = config.get("MINIAPP_LINK", "").strip()
DEFAULT_DEPOSIT_LINK  = config.get("DEPOSIT_LINK", "").strip()
DEFAULT_WITHDRAW_LINK = config.get("WITHDRAW_LINK", "").strip()
DEFAULT_DEPOSIT_SUPPORT_LINK  = config.get("DEPOSIT_SUPPORT_LINK", "").strip()
DEFAULT_WITHDRAW_SUPPORT_LINK = config.get("WITHDRAW_SUPPORT_LINK", "").strip()
DEFAULT_BONUS_SUPPORT_LINK    = config.get("BONUS_SUPPORT_LINK", "").strip()
MAIN_MENU_TITLE = config.get("MAIN_MENU_TITLE", "\U0001f3e0 ANA MENÜ").strip().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
MAIN_MENU_TEXT  = config.get("MAIN_MENU_TEXT", "İstediğin bölüme tek dokunuşla ulaş \U0001f447").replace("\\n", "\n").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# === ALT KLAVYE MENUSU (yazi alanindaki ⌘/izgara simgesi) ===
# Luks tarzi kalici buton menusu. Simge, bot bir mesajla bu klavyeyi
# gonderdikten sonra yazi alaninin icinde belirir ve kalici kalir.
# Bicim: satirlar virgulle, ayni satirdaki butonlar | ile ayrilir.
REPLY_MENU_BUTTONS = config.get("REPLY_MENU_BUTTONS",
    "\U0001f3e0 Siteye Giriş|\U0001f4f1 Mini App,"
    "\U0001f381 Bonuslar|\U0001f195 Yeni Üye,"
    "\U0001f3b0 Slot|\u26bd Spor,"
    "\u2b50 Bana Özel|\U0001f3c6 Turnuvalar,"
    "\U0001f4b0 Para Yatır|\U0001f4b8 Para Çek,"
    "\U0001f4e2 Duyurular|\u2753 SSS,"
    "\U0001f4ac Canlı Destek|\U0001f934 Profil,"
    "\U0001f4f8 Ekran Görüntüsü|\U0001f3e0 Ana Menü")
REPLY_MENU_PROMPT = config.get("REPLY_MENU_PROMPT",
    "Alt menü her zaman hazır \U0001f447").replace("\\n", "\n")

def _build_reply_menu():
    rows = []
    for row in (REPLY_MENU_BUTTONS or "").split(","):
        btns = [KeyboardButton(b.strip()[:40]) for b in row.split("|") if b.strip()]
        if btns:
            rows.append(btns)
    if not rows:
        return None
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

# Sol alt menu butonu modu:
#   menu = komut menusu (⌘ simgesi ve komut listesi HER istemcide gorunur)
#   play = web-app PLAY butonu (guncel web Telegram ⌘ simgesini GIZLER; ikisi ayni anda olmaz)
MENU_BUTTON_MODE = config.get("MENU_BUTTON_MODE", "menu").strip().lower()
if MENU_BUTTON_MODE not in ("menu", "play"):
    MENU_BUTTON_MODE = "menu"

# Acilista buyuk ANA MENU mesaji gonderilsin mi? Varsayilan: HAYIR (menu
# zaten ikondaki alt klavyede; kullanici Ana Menü butonuyla/komutla acar).
SEND_MAIN_MENU_ON_START = config.get("SEND_MAIN_MENU_ON_START", "0").strip() == "1"

# Zamanli mesaj: gonderimden kac dakika once adminlere onizlemeli hatirlatma gitsin.
try:
    SCHED_NOTIFY_MINUTES = max(1, int(config.get("SCHED_NOTIFY_MINUTES", "5")))
except (TypeError, ValueError):
    SCHED_NOTIFY_MINUTES = 5

# === KULLANICI KATEGORILERI ===
SEGMENTS = {
    "platin": "\U0001f48e Platin",
    "altin":  "\U0001f3c5 Alt\u0131n",
    "gumus":  "\U0001f948 G\u00fcm\u00fc\u015f",
    "bronz":  "\U0001f949 Bronz",
}

DB_PATH = os.path.join(BASE_DIR, "hitbet_bot.db")
ADMINS_FILE = os.path.join(BASE_DIR, "admins.txt")
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO,
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# === ADMIN LISTESI ===
def load_admins():
    admins = []
    try:
        with open(ADMINS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        aid = int(line)
                        if aid > 0: admins.append(aid)
                    except: pass
    except: pass
    return admins

def save_admins(admin_list):
    with open(ADMINS_FILE, "w") as f:
        for a in admin_list:
            f.write(f"{a}\n")

ADMIN_IDS = load_admins()
if ADMIN_IDS:
    print(f"[OK] Adminler: {ADMIN_IDS}")
else:
    print("[GUVENLIK] admins.txt bos; bot yapilandirma tamamlanana kadar baslatilmayacak.")

# Admin oturum durumu (giris yapildi mi)
authenticated_admins = {}
login_attempts = defaultdict(int)
login_blocked = {}

def is_session_valid(uid):
    if uid not in authenticated_admins: return False
    if ADMIN_SESSION_TIMEOUT > 0 and time.time() - authenticated_admins[uid] > ADMIN_SESSION_TIMEOUT:
        del authenticated_admins[uid]; return False
    return True

def is_authenticated(uid):
    return uid in ADMIN_IDS and is_session_valid(uid)

def verify_admin_password(entered):
    """Yonetici parolasini yalnizca PBKDF2-SHA256 ozetiyle sabit zamanda dogrular."""
    value = str(entered or "")
    if not ADMIN_PASSWORD_HASH:
        return False
    try:
        scheme, iterations_text, salt_b64, digest_b64 = ADMIN_PASSWORD_HASH.split("$", 3)
        iterations = int(iterations_text)
        if scheme != "pbkdf2_sha256" or not (200_000 <= iterations <= 2_000_000):
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        expected = base64.b64decode(digest_b64.encode("ascii"), validate=True)
        actual = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, base64.binascii.Error):
        logger.error("PASSWORD_HASH bicimi gecersiz")
        return False

# === GUVENLIK / TEMIZLEME FONKSIYONLARI ===
def sanitize_input(text, max_len=MAX_INPUT_LENGTH):
    if not text: return ""
    text = str(text).strip()[:max_len]
    # Telegram HTML kipinde guvenli kalmasi icin silmek yerine kacir.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

_CTRL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

# Serbest kullanici metni icin EN SIKI temizleyici (sikayet vb.)
def harden_text(text, max_len=MAX_INPUT_LENGTH):
    if not text: return ""
    text = str(text)
    text = _CTRL_CHARS.sub('', text)
    text = text.strip()[:max_len]
    text = re.sub(r'<[^>]*>', '', text)
    danger = [
        r'javascript:', r'vbscript:', r'data:', r'file:', r'about:',
        r'on\w+\s*=', r'<\s*script', r'</\s*script',
        r'eval\s*\(', r'exec\s*\(', r'system\s*\(', r'os\.\w+',
        r'subprocess', r'import\s+os', r'__import__', r'\brm\s+-rf\b',
        r'\bcurl\b', r'\bwget\b', r'powershell', r'cmd\.exe', r'/bin/sh',
        r'\bDROP\s+TABLE\b', r'\bDELETE\s+FROM\b', r'\bINSERT\s+INTO\b',
        r'\bUPDATE\s+\w+\s+SET\b', r';--', r'\bUNION\s+SELECT\b',
    ]
    for pat in danger:
        text = re.sub(pat, '[engellendi]', text, flags=re.IGNORECASE)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()

# Dosyaya yazilacak metni notr hale getir (CSV/Excel injection korumasi dahil)
def neutralize_for_file(text):
    if not text: return ""
    text = str(text)
    text = _CTRL_CHARS.sub('', text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r'<[^>]*>', '', text)
    out = []
    for ln in text.split('\n'):
        if ln[:1] in ('=', '+', '-', '@', '\t'):
            ln = "'" + ln
        out.append(ln)
    return '\n'.join(out)

def is_valid_url(url):
    if not url or len(url) > MAX_URL_LENGTH: return False
    if not re.match(r'^https?://[^\s<>"{}|\\^`\[\]]+$', url, re.IGNORECASE): return False
    for d in ['javascript:', 'data:', 'file:', 'ftp:', 'vbscript:']:
        if d in url.lower(): return False
    return True

def is_valid_id(id_str):
    try: return 0 < int(id_str) < 10000000000
    except: return False

def is_valid_filename(name):
    if not name: return False
    if '..' in name or '/' in name or '\\' in name: return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+\.(jpg|jpeg|png|gif|webp|mp4|mov|m4v)$', name, re.IGNORECASE))

def is_safe_path(base_dir, target_path):
    try:
        base = os.path.realpath(base_dir)
        target = os.path.realpath(target_path)
        return target == base or target.startswith(base + os.sep)
    except Exception:
        return False

def box_message(title, content, emoji=""):
    header = f"{emoji} <b>{title}</b>" if emoji else f"<b>{title}</b>"
    return f"{header}\n\n{content}"

def personalize_text(template, user_name):
    """Yonetilebilir metindeki {name} alanini guvenli Telegram adi ile degistirir."""
    safe_name = sanitize_input(user_name or "Degerli Kullanici", 80)
    return str(template or "").replace("{name}", safe_name)

def _safe_setting_text(key, default="", max_len=500):
    """Veritabanindaki yonetilebilir metni Telegram HTML'i icin guvenli dondurur."""
    value = db.get_setting(key)
    return value if value else sanitize_input(default, max_len)

def build_campaign_caption():
    """Baslik, aciklama, tiklanabilir yazi ve kampanya kodunu tek aciklamada birlestirir."""
    title = _safe_setting_text("campaign_title", DEFAULT_CAMPAIGN_TITLE, 80)
    text = render_rich_tokens(_safe_setting_text("promo_caption", DEFAULT_PROMO_CAP, 700))
    parts = [f"<b>{title}</b>", text]

    # Kayitli degerler zaten kacirilmis; varsayilanlar bir kez kacirilir.
    link_text = (db.get_setting("caption_link_text") or sanitize_input(DEFAULT_CAPTION_LINK_TEXT, 80)).strip()
    link_url = (db.get_setting("caption_link_url") or DEFAULT_CAPTION_LINK_URL).strip()
    if link_text and is_valid_url(link_url):
        parts.append(f'<a href="{link_url}">{link_text}</a>')

    code = (db.get_setting("campaign_code") or sanitize_input(DEFAULT_CAMPAIGN_CODE, MAX_CODE_LENGTH)).strip()
    code_style = (db.get_setting("campaign_code_style") or DEFAULT_CAMPAIGN_CODE_STYLE or "copy").strip().lower()
    if code:
        safe_code = code
        if code_style == "spoiler":
            parts.append(f"\U0001f381 Kampanya Kodu:\n<tg-spoiler>{safe_code}</tg-spoiler>")
        else:
            parts.append(f"\U0001f381 Kampanya Kodu:\n<code>{safe_code}</code>")
    return "\n\n".join(part for part in parts if part).strip()

def build_campaign_keyboard():
    link = db.get_setting("bonus_link") or DEFAULT_BONUS_LINK
    text = _plain_label(db.get_setting("bonus_btn_text") or DEFAULT_BONUS_BTN, 40)
    # Gecersiz/bos link tum mesaji Telegram'da reddettirir; butonu birak.
    if not is_valid_url(link):
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, url=link)]])

def _media_kind(filename="", explicit=""):
    if explicit in ("photo", "video"):
        return explicit
    return "video" if str(filename).lower().endswith((".mp4", ".mov", ".m4v")) else "photo"

async def send_campaign_media(context, chat_id):
    """Aktif kampanya medyasini foto veya video olarak gonderir; hata halinde metne duser."""
    # 1024+ karakter aciklama medyayi Telegram'da reddettirir; emniyetli kisalt.
    caption = _safe_caption(build_campaign_caption())
    # Kampanya altindaki inline buton (Aktif Et)
    keyboard = build_campaign_keyboard()
    # Sabit menu (Giris & Konsol) - Telegram bir mesajda hem inline hem reply keyboard gonderemez.
    # Bu nedenle reply keyboard'u ayrica start_welcome'da gonderiyoruz.
    media_id = db.get_setting("campaign_media_id") or ""
    stored_media_file = db.get_setting("campaign_media_file") or db.get_setting("promo_image_file") or ""
    media_file = stored_media_file or "promo.jpg"
    explicit_type = db.get_setting("campaign_media_type") or ""
    local_media = os.path.join(IMAGES_DIR, media_file)
    media_url = db.get_setting("campaign_media_url") or db.get_setting("promo_image") or DEFAULT_PROMO_IMAGE

    try:
        if media_id:
            media_type = _media_kind(media_file, explicit_type)
            if media_type == "video":
                await context.bot.send_video(chat_id=chat_id, video=media_id, caption=caption,
                    parse_mode=ParseMode.HTML, reply_markup=keyboard)
            else:
                await context.bot.send_photo(chat_id=chat_id, photo=media_id, caption=caption,
                    parse_mode=ParseMode.HTML, reply_markup=keyboard)
        elif stored_media_file and os.path.exists(local_media) and is_safe_path(IMAGES_DIR, local_media):
            media_type = _media_kind(media_file, explicit_type)
            with open(local_media, "rb") as media:
                if media_type == "video":
                    await context.bot.send_video(chat_id=chat_id, video=media, caption=caption,
                        parse_mode=ParseMode.HTML, reply_markup=keyboard)
                else:
                    await context.bot.send_photo(chat_id=chat_id, photo=media, caption=caption,
                        parse_mode=ParseMode.HTML, reply_markup=keyboard)
        elif media_url:
            remote_type = _media_kind(media_url, explicit_type)
            if remote_type == "video":
                await context.bot.send_video(chat_id=chat_id, video=media_url, caption=caption,
                    parse_mode=ParseMode.HTML, reply_markup=keyboard)
            else:
                await context.bot.send_photo(chat_id=chat_id, photo=media_url, caption=caption,
                    parse_mode=ParseMode.HTML, reply_markup=keyboard)
        elif os.path.exists(local_media) and is_safe_path(IMAGES_DIR, local_media):
            fallback_type = _media_kind(media_file, explicit_type)
            with open(local_media, "rb") as media:
                if fallback_type == "video":
                    await context.bot.send_video(chat_id=chat_id, video=media, caption=caption,
                        parse_mode=ParseMode.HTML, reply_markup=keyboard)
                else:
                    await context.bot.send_photo(chat_id=chat_id, photo=media, caption=caption,
                        parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            await context.bot.send_message(chat_id=chat_id, text=caption,
                parse_mode=ParseMode.HTML, reply_markup=keyboard)
    except Exception as exc:
        logger.warning(f"Kampanya medyasi gonderilemedi: {exc}")
        await context.bot.send_message(chat_id=chat_id, text=caption,
            parse_mode=ParseMode.HTML, reply_markup=keyboard)

# === VERITABANI ===
class Database:
    def __init__(self):
        self._lock = threading.Lock()
        self._init()
    def _conn(self):
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    def _init(self):
        conn = self._conn()
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users(
                user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                last_name TEXT, is_banned INTEGER DEFAULT 0, ban_reason TEXT DEFAULT '',
                ban_at TEXT DEFAULT '', ban_by INTEGER DEFAULT 0,
                temp_ban_count INTEGER DEFAULT 0,
                joined_at TEXT, last_active TEXT, total_messages INTEGER DEFAULT 0,
                total_starts INTEGER DEFAULT 0, language_code TEXT DEFAULT '',
                segment TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, action TEXT, details TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS admin_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER, action TEXT, details TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS temp_bans(user_id INTEGER PRIMARY KEY, banned_until TEXT);
            CREATE TABLE IF NOT EXISTS security_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT, user_id INTEGER, details TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS complaints(id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER, username TEXT, first_name TEXT, message TEXT,
                image_file TEXT DEFAULT '', status TEXT DEFAULT 'yeni', created_at TEXT);
            CREATE TABLE IF NOT EXISTS templates(id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, payload TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS scheduled(id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT, target TEXT, run_at TEXT, status TEXT DEFAULT 'bekliyor',
                created_at TEXT);
            CREATE TABLE IF NOT EXISTS campaign_media_library(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_type TEXT NOT NULL,
                media_id TEXT NOT NULL,
                name TEXT DEFAULT '',
                added_by INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(media_type, media_id));
            CREATE TABLE IF NOT EXISTS site_id_records(
                telegram_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                site_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS campaigns(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT DEFAULT '',
                media_id TEXT DEFAULT '',
                media_type TEXT DEFAULT '',
                btn_text TEXT DEFAULT '',
                btn_url TEXT DEFAULT '',
                segment TEXT DEFAULT '',
                prize_pool TEXT DEFAULT '',
                conditions TEXT DEFAULT '',
                expires_at TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                notified_ending INTEGER DEFAULT 0,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS announcements(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT DEFAULT '',
                media_id TEXT DEFAULT '',
                media_type TEXT DEFAULT '',
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS broadcasts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                target TEXT DEFAULT '',
                ok INTEGER DEFAULT 0,
                fail INTEGER DEFAULT 0,
                total INTEGER DEFAULT 0,
                payload TEXT DEFAULT '',
                admin_id INTEGER DEFAULT 0,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS faqs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS screenshots(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                category TEXT NOT NULL,
                category_label TEXT DEFAULT '',
                fields TEXT DEFAULT '',
                file_name TEXT NOT NULL,
                note TEXT DEFAULT '',
                status TEXT DEFAULT 'yeni',
                created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_screenshots_user ON screenshots(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_screenshots_status ON screenshots(status);
            CREATE INDEX IF NOT EXISTS idx_campaigns_cat ON campaigns(category, active);
            CREATE INDEX IF NOT EXISTS idx_users_ban ON users(is_banned);
            CREATE INDEX IF NOT EXISTS idx_users_seg ON users(segment);
            CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);
            CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled(status);
            CREATE INDEX IF NOT EXISTS idx_campaign_media_created ON campaign_media_library(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_site_id_value ON site_id_records(site_id);
        ''')
        # Eski DB uyumu
        for col in [
            "ALTER TABLE users ADD COLUMN segment TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN ban_at TEXT DEFAULT ''",
            "ALTER TABLE users ADD COLUMN ban_by INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN temp_ban_count INTEGER DEFAULT 0",
            "ALTER TABLE scheduled ADD COLUMN notified INTEGER DEFAULT 0",
        ]:
            try: conn.execute(col)
            except: pass
        # Gonderim ortasinda kapanan botun yarim kayitlarini normalize et.
        try: conn.execute("UPDATE scheduled SET status='hata' WHERE status='gonderiliyor'")
        except: pass
        # v8.5 oncesi sihirbaz hatasindan (bos sozluk kaybi) kalan BOS kayitlari
        # temizle: bos soru "Soru #1" gorunur, bos duyuru gonderimde herkese
        # "message text is empty" hatasi verirdi.
        for temizlik in (
            "DELETE FROM faqs WHERE TRIM(question)=''",
            "DELETE FROM announcements WHERE TRIM(title)='' AND TRIM(body)='' AND TRIM(COALESCE(media_id,''))=''",
            "DELETE FROM campaigns WHERE TRIM(title)=''",
        ):
            try: conn.execute(temizlik)
            except: pass
        conn.commit(); conn.close()
    def exe(self, sql, params=()):
        with self._lock:
            conn = self._conn()
            try:
                c = conn.cursor(); c.execute(sql, params); conn.commit()
                return [dict(r) for r in c.fetchall()]
            finally: conn.close()
    def exe_id(self, sql, params=()):
        with self._lock:
            conn = self._conn()
            try:
                c = conn.cursor(); c.execute(sql, params); conn.commit()
                return c.lastrowid
            finally: conn.close()
    # --- Kullanici ---
    def add_user(self, uid, uname, fname, lname, lang=""):
        now = datetime.now().isoformat()
        self.exe("INSERT INTO users(user_id,username,first_name,last_name,language_code,joined_at,last_active,total_starts) VALUES(?,?,?,?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET username=?,first_name=?,last_name=?,language_code=?,last_active=?,total_starts=total_starts+1",
            (uid,uname,fname,lname,lang,now,now,uname,fname,lname,lang,now))
    def get_user(self, uid):
        r = self.exe("SELECT * FROM users WHERE user_id=?", (uid,)); return r[0] if r else None
    def get_all_users(self):
        return self.exe("SELECT * FROM users WHERE is_banned=0 ORDER BY last_active DESC")
    def get_users_by_segment(self, seg):
        return self.exe("SELECT * FROM users WHERE is_banned=0 AND segment=? ORDER BY last_active DESC", (seg,))
    def get_active_users(self, hours=24):
        since = (datetime.now()-timedelta(hours=hours)).isoformat()
        return self.exe("SELECT * FROM users WHERE is_banned=0 AND last_active>? ORDER BY last_active DESC", (since,))
    def set_segment(self, uid, seg):
        self.exe("UPDATE users SET segment=? WHERE user_id=?", (seg, uid))
    def is_banned(self, uid):
        r = self.exe("SELECT is_banned FROM users WHERE user_id=?", (uid,)); return bool(r and r[0]['is_banned']==1)
    def ban_user(self, uid, reason="", by_admin=0):
        # Kullanici tabloda yoksa da ban tutulsun (UPDATE 0 satir = sessiz basarisizlikti);
        # once yoksa iskelet kayit ac, sonra guncelle.
        now = datetime.now().isoformat()
        self.exe("INSERT OR IGNORE INTO users(user_id,username,first_name,last_name,language_code,joined_at,last_active,total_starts) VALUES(?,?,?,?,?,?,?,0)",
                 (uid, "", "", "", "", now, now))
        self.exe("UPDATE users SET is_banned=1,ban_reason=?,ban_at=?,ban_by=? WHERE user_id=?", (reason, now, by_admin, uid))
    def unban_user(self, uid):
        self.exe("UPDATE users SET is_banned=0,ban_reason='',ban_at='',ban_by=0 WHERE user_id=?", (uid,))
    def get_banned_users(self):
        return self.exe("SELECT * FROM users WHERE is_banned=1 ORDER BY ban_at DESC")
    def search_banned(self, query):
        q = (query or "").strip().lower()
        rows = self.get_banned_users()
        if q.isdigit():
            return [u for u in rows if q in str(u['user_id'])]
        return [u for u in rows if (u['username'] and q in u['username'].lower()) or (u['first_name'] and q in u['first_name'].lower())]
    def inc_msg(self, uid):
        self.exe("UPDATE users SET total_messages=total_messages+1,last_active=? WHERE user_id=?", (datetime.now().isoformat(),uid))
    def inc_temp_ban(self, uid):
        self.exe("UPDATE users SET temp_ban_count=temp_ban_count+1 WHERE user_id=?", (uid,))
        r = self.exe("SELECT temp_ban_count FROM users WHERE user_id=?", (uid,))
        return r[0]['temp_ban_count'] if r else 0
    # --- Site ID kayitlari ---
    def upsert_site_id(self, uid, uname, fname, lname, site_id):
        now = datetime.now().isoformat(timespec="seconds")
        self.exe(
            "INSERT INTO site_id_records(telegram_id,username,first_name,last_name,site_id,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET "
            "username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,"
            "site_id=excluded.site_id,updated_at=excluded.updated_at",
            (uid, uname or "", fname or "", lname or "", site_id, now, now))
    def get_site_id_record(self, uid):
        rows = self.exe("SELECT * FROM site_id_records WHERE telegram_id=?", (uid,))
        return rows[0] if rows else None
    def add_broadcast_log(self, kind, target, ok, fail, total, payload="", admin_id=0):
        return self.exe_id(
            "INSERT INTO broadcasts(kind,target,ok,fail,total,payload,admin_id,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (kind, str(target), ok, fail, total, payload, admin_id, datetime.now().isoformat(timespec="seconds")))
    def list_broadcast_logs(self, limit=10):
        return self.exe("SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (limit,))
    def get_broadcast_log(self, bid):
        r = self.exe("SELECT * FROM broadcasts WHERE id=?", (bid,))
        return r[0] if r else None
    ANN_EDITABLE = ("title", "body", "media_id", "media_type")
    def update_announcement_field(self, aid, field, value):
        if field not in self.ANN_EDITABLE:
            raise ValueError("duzenlenemez alan")
        self.exe(f"UPDATE announcements SET {field}=? WHERE id=?", (value, aid))
    def get_siteid_users(self):
        """Site ID baglamis (kayitli) ve banli olmayan kullanicilar."""
        return self.exe(
            "SELECT u.* FROM users u JOIN site_id_records s ON s.telegram_id=u.user_id "
            "WHERE u.is_banned=0 ORDER BY u.last_active DESC")
    def get_users_by_site_ids(self, site_ids):
        """Verilen Site ID listesine bagli kullanicilar (banlilar haric)."""
        ids = [s for s in site_ids if s]
        if not ids:
            return []
        ph = ",".join("?" for _ in ids)
        return self.exe(
            f"SELECT u.* FROM users u JOIN site_id_records s ON s.telegram_id=u.user_id "
            f"WHERE u.is_banned=0 AND s.site_id COLLATE NOCASE IN ({ph})", tuple(ids))
    def find_by_site_id(self, site_id):
        """Bir Site ID hangi Telegram kullanicisina bagli?"""
        return self.exe("SELECT * FROM site_id_records WHERE site_id=? COLLATE NOCASE", (site_id,))
    def list_site_id_records(self):
        return self.exe("SELECT * FROM site_id_records ORDER BY updated_at DESC, telegram_id ASC")
    def count_site_id_records(self):
        return self.exe("SELECT COUNT(*) AS c FROM site_id_records")[0]['c']
    # --- Kampanyalar (kategori bazli, sureli) ---
    CAMPAIGN_EDITABLE = ("title", "body", "btn_text", "btn_url", "prize_pool",
                         "conditions", "expires_at", "segment", "media_id", "media_type")
    def add_campaign(self, category, title, body="", media_id="", media_type="",
                     btn_text="", btn_url="", segment="", prize_pool="", conditions="", expires_at=""):
        return self.exe_id(
            "INSERT INTO campaigns(category,title,body,media_id,media_type,btn_text,btn_url,"
            "segment,prize_pool,conditions,expires_at,active,notified_ending,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,1,0,?)",
            (category, title, body, media_id, media_type, btn_text, btn_url,
             segment, prize_pool, conditions, expires_at, datetime.now().isoformat(timespec="seconds")))
    def update_campaign_field(self, cid, field, value):
        if field not in self.CAMPAIGN_EDITABLE:
            return False
        self.exe(f"UPDATE campaigns SET {field}=? WHERE id=?", (value, cid))
        if field == "expires_at":
            # Yeni sure verildiyse bitis bildirimleri yeniden kurulsun.
            self.exe("UPDATE campaigns SET notified_ending=0 WHERE id=?", (cid,))
        return True
    def set_campaign_active(self, cid, active):
        self.exe("UPDATE campaigns SET active=? WHERE id=?", (1 if active else 0, cid))
    def delete_campaign(self, cid):
        self.exe("DELETE FROM campaigns WHERE id=?", (cid,))
    def get_campaign(self, cid):
        r = self.exe("SELECT * FROM campaigns WHERE id=?", (cid,))
        return r[0] if r else None
    def list_campaigns(self, category=None, only_active=True, segment=None):
        """Kullaniciya gosterilecek liste: aktif ve suresi gecmemis kayitlar.
        segment verilirse o segmente ozel + herkese acik (segment='') kayitlar doner."""
        now = datetime.now().isoformat(timespec="seconds")
        sql = "SELECT * FROM campaigns WHERE 1=1"
        params = []
        if category:
            sql += " AND category=?"; params.append(category)
        if only_active:
            sql += " AND active=1 AND (expires_at='' OR expires_at>?)"; params.append(now)
        if segment is not None:
            segs = [segment] if isinstance(segment, str) else [s for s in segment if s]
            if segs:
                yer = ",".join("?" for _ in segs)
                sql += f" AND (segment='' OR segment IN ({yer}))"; params.extend(segs)
            else:
                sql += " AND segment=''"
        sql += " ORDER BY id DESC"
        return self.exe(sql, tuple(params))
    def list_campaigns_admin(self, category=None):
        sql = "SELECT * FROM campaigns"
        params = []
        if category:
            sql += " WHERE category=?"; params.append(category)
        sql += " ORDER BY id DESC"
        return self.exe(sql, tuple(params))
    def campaigns_needing_expiry_notice(self):
        """Aktif, bitis tarihi olan ve bildirimi tamamlanmamis kampanyalar."""
        now = datetime.now().isoformat(timespec="seconds")
        return self.exe(
            "SELECT * FROM campaigns WHERE active=1 AND expires_at!='' AND expires_at>? AND notified_ending<2", (now,))
    def mark_campaign_notified(self, cid, level):
        self.exe("UPDATE campaigns SET notified_ending=? WHERE id=?", (level, cid))
    def deactivate_expired_campaigns(self):
        """Suresi dolanlari otomatik yayindan kaldirir; kaldirilan id listesi doner."""
        now = datetime.now().isoformat(timespec="seconds")
        rows = self.exe("SELECT id FROM campaigns WHERE active=1 AND expires_at!='' AND expires_at<=?", (now,))
        for r in rows:
            self.exe("UPDATE campaigns SET active=0 WHERE id=?", (r["id"],))
        return [r["id"] for r in rows]
    # --- Duyurular ---
    def add_announcement(self, title, body="", media_id="", media_type=""):
        return self.exe_id(
            "INSERT INTO announcements(title,body,media_id,media_type,active,created_at) VALUES(?,?,?,?,1,?)",
            (title, body, media_id, media_type, datetime.now().isoformat(timespec="seconds")))
    def list_announcements(self, only_active=True, limit=10):
        sql = "SELECT * FROM announcements"
        if only_active:
            sql += " WHERE active=1"
        sql += " ORDER BY id DESC LIMIT ?"
        return self.exe(sql, (limit,))
    def get_announcement(self, aid):
        r = self.exe("SELECT * FROM announcements WHERE id=?", (aid,))
        return r[0] if r else None
    def delete_announcement(self, aid):
        self.exe("DELETE FROM announcements WHERE id=?", (aid,))
    # --- SSS ---
    def add_faq(self, question, answer):
        return self.exe_id("INSERT INTO faqs(question,answer,active,created_at) VALUES(?,?,1,?)",
            (question, answer, datetime.now().isoformat(timespec="seconds")))
    def list_faqs(self, only_active=True):
        sql = "SELECT * FROM faqs"
        if only_active:
            sql += " WHERE active=1"
        sql += " ORDER BY id ASC"
        return self.exe(sql)
    def get_faq(self, fid):
        r = self.exe("SELECT * FROM faqs WHERE id=?", (fid,))
        return r[0] if r else None
    def delete_faq(self, fid):
        self.exe("DELETE FROM faqs WHERE id=?", (fid,))
    # --- Ayar ---
    def get_setting(self, key):
        r = self.exe("SELECT value FROM settings WHERE key=?", (key,)); return r[0]['value'] if r else None
    def set_setting(self, key, val):
        now = datetime.now().isoformat()
        self.exe("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=?,updated_at=?", (key,val,now,val,now))
    # --- Kampanya medya kutuphanesi ---
    def add_campaign_media(self, media_type, media_id, name="", added_by=0):
        existing = self.exe(
            "SELECT id FROM campaign_media_library WHERE media_type=? AND media_id=?",
            (media_type, media_id))
        if existing:
            media_pk = existing[0]['id']
            self.exe("UPDATE campaign_media_library SET name=?,added_by=? WHERE id=?",
                (name, added_by, media_pk))
            return media_pk
        return self.exe_id(
            "INSERT INTO campaign_media_library(media_type,media_id,name,added_by,created_at) VALUES(?,?,?,?,?)",
            (media_type, media_id, name, added_by, datetime.now().isoformat()))
    def get_campaign_media(self, media_pk):
        rows = self.exe("SELECT * FROM campaign_media_library WHERE id=?", (media_pk,))
        return rows[0] if rows else None
    def list_campaign_media(self):
        return self.exe("SELECT * FROM campaign_media_library ORDER BY id DESC")
    def count_campaign_media(self):
        return self.exe("SELECT COUNT(*) AS c FROM campaign_media_library")[0]['c']
    def delete_campaign_media(self, media_pk):
        exists = self.get_campaign_media(media_pk) is not None
        if exists:
            self.exe("DELETE FROM campaign_media_library WHERE id=?", (media_pk,))
        return exists
    # --- Log ---
    def log(self, uid, action, details=""):
        self.exe("INSERT INTO logs(user_id,action,details,created_at) VALUES(?,?,?,?)", (uid,action,details,datetime.now().isoformat()))
    def admin_log(self, aid, action, details=""):
        self.exe("INSERT INTO admin_logs(admin_id,action,details,created_at) VALUES(?,?,?,?)", (aid,action,details,datetime.now().isoformat()))
    def security_event(self, etype, uid, details=""):
        self.exe("INSERT INTO security_events(event_type,user_id,details,created_at) VALUES(?,?,?,?)", (etype,uid,details,datetime.now().isoformat()))
    def get_admin_logs_for_day(self, day_str):
        return self.exe("SELECT * FROM admin_logs WHERE created_at LIKE ? ORDER BY id ASC", (f"{day_str}%",))
    def get_daily_log_summary(self, days=7):
        out = []
        for d in range(days):
            day = (datetime.now()-timedelta(days=d)).strftime("%Y-%m-%d")
            c = self.exe("SELECT COUNT(*) as c FROM admin_logs WHERE created_at LIKE ?", (f"{day}%",))[0]['c']
            out.append((day, c))
        return out
    # --- Temp ban ---
    def is_temp_banned(self, uid):
        r = self.exe("SELECT banned_until FROM temp_bans WHERE user_id=?", (uid,))
        if r:
            if datetime.now() < datetime.fromisoformat(r[0]['banned_until']): return True
            self.exe("DELETE FROM temp_bans WHERE user_id=?", (uid,))
        return False
    def temp_ban(self, uid, minutes):
        until = (datetime.now()+timedelta(minutes=minutes)).isoformat()
        self.exe("INSERT INTO temp_bans(user_id,banned_until) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET banned_until=?", (uid,until,until))
    # --- Sikayet ---
    def add_complaint(self, uid, uname, fname, message, image_file=""):
        return self.exe_id("INSERT INTO complaints(user_id,username,first_name,message,image_file,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (uid, uname or "", fname or "", message, image_file, "yeni", datetime.now().isoformat()))
    def get_complaints(self, only_new=False, limit=50):
        if only_new:
            return self.exe("SELECT * FROM complaints WHERE status='yeni' ORDER BY id DESC LIMIT ?", (limit,))
        return self.exe("SELECT * FROM complaints ORDER BY id DESC LIMIT ?", (limit,))
    def get_complaint(self, cid):
        r = self.exe("SELECT * FROM complaints WHERE id=?", (cid,)); return r[0] if r else None
    def set_complaint_status(self, cid, status):
        self.exe("UPDATE complaints SET status=? WHERE id=?", (status, cid))
    def count_new_complaints(self):
        return self.exe("SELECT COUNT(*) as c FROM complaints WHERE status='yeni'")[0]['c']
    # --- Ekran goruntusu kayitlari ---
    def add_screenshot(self, uid, uname, fname, category, category_label, fields_json, file_name, note=""):
        return self.exe_id(
            "INSERT INTO screenshots(user_id,username,first_name,category,category_label,fields,file_name,note,status,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid, uname or "", fname or "", category, category_label, fields_json, file_name, note or "",
             "yeni", datetime.now().isoformat(timespec="seconds")))
    def get_screenshot(self, sid):
        r = self.exe("SELECT * FROM screenshots WHERE id=?", (sid,)); return r[0] if r else None
    def list_screenshots(self, limit=20, only_new=False, category=None, user_id=None):
        sql, params = "SELECT * FROM screenshots WHERE 1=1", []
        if only_new:
            sql += " AND status='yeni'"
        if category:
            sql += " AND category=?"; params.append(category)
        if user_id:
            sql += " AND user_id=?"; params.append(user_id)
        sql += " ORDER BY id DESC LIMIT ?"; params.append(int(limit))
        return self.exe(sql, tuple(params))
    def count_screenshots(self, only_new=False):
        sql = "SELECT COUNT(*) AS c FROM screenshots" + (" WHERE status='yeni'" if only_new else "")
        return self.exe(sql)[0]['c']
    def count_screenshots_today(self, uid):
        day = datetime.now().strftime("%Y-%m-%d")
        return self.exe("SELECT COUNT(*) AS c FROM screenshots WHERE user_id=? AND created_at LIKE ?",
                        (uid, day + "%"))[0]['c']
    def set_screenshot_status(self, sid, status):
        self.exe("UPDATE screenshots SET status=? WHERE id=?", (status, sid))
    # --- Sablon ---
    def add_template(self, name, payload):
        return self.exe_id("INSERT INTO templates(name,payload,created_at) VALUES(?,?,?)", (name,payload,datetime.now().isoformat()))
    def get_templates(self):
        return self.exe("SELECT * FROM templates ORDER BY id DESC")
    def get_template(self, tid):
        r = self.exe("SELECT * FROM templates WHERE id=?", (tid,)); return r[0] if r else None
    def del_template(self, tid):
        self.exe("DELETE FROM templates WHERE id=?", (tid,))
    # --- Zamanli mesaj ---
    def add_scheduled(self, payload, target, run_at):
        return self.exe_id("INSERT INTO scheduled(payload,target,run_at,status,created_at) VALUES(?,?,?,?,?)",
            (payload,target,run_at,"bekliyor",datetime.now().isoformat()))
    def get_due_scheduled(self):
        now = datetime.now().isoformat()
        return self.exe("SELECT * FROM scheduled WHERE status='bekliyor' AND run_at<=?", (now,))
    def get_pending_scheduled(self):
        return self.exe("SELECT * FROM scheduled WHERE status='bekliyor' ORDER BY run_at ASC")
    def get_scheduled(self, sid):
        r = self.exe("SELECT * FROM scheduled WHERE id=?", (sid,))
        return r[0] if r else None
    def get_prenotify_scheduled(self, minutes):
        """Gonderimine <minutes> dk kalan ve henuz hatirlatilmamis kayitlar."""
        now = datetime.now().isoformat()
        soon = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        return self.exe(
            "SELECT * FROM scheduled WHERE status='bekliyor' AND COALESCE(notified,0)=0 AND run_at>? AND run_at<=?",
            (now, soon))
    def mark_scheduled_notified(self, sid):
        self.exe("UPDATE scheduled SET notified=1 WHERE id=?", (sid,))
    def update_scheduled_time(self, sid, run_at):
        """Zamani degistir; hatirlatma bayragini sifirla. Yalnizca bekleyenlerde."""
        self.exe("UPDATE scheduled SET run_at=?, notified=0 WHERE id=? AND status='bekliyor'", (run_at, sid))
    def set_scheduled_status(self, sid, status):
        self.exe("UPDATE scheduled SET status=? WHERE id=?", (status, sid))
    def claim_scheduled(self, sid):
        """Kaydi ATOMIK olarak 'gonderiliyor'a cevirir; yalnizca hala 'bekliyor'sa.

        Zamanlayici ile paneldeki "Simdi Gonder"/"Iptal Et" ayni kayda ayni anda
        dokundugunda cift gonderimi/iptal ezmeyi onler. True = gonderim bizde."""
        with self._lock:
            conn = self._conn()
            try:
                c = conn.cursor()
                c.execute("UPDATE scheduled SET status='gonderiliyor' WHERE id=? AND status='bekliyor'", (sid,))
                conn.commit()
                return c.rowcount > 0
            finally:
                conn.close()
    def del_scheduled(self, sid):
        self.exe("DELETE FROM scheduled WHERE id=?", (sid,))
    # --- Istatistik ---
    def get_stats(self):
        s = {}
        s['total'] = self.exe("SELECT COUNT(*) as c FROM users")[0]['c']
        s['active'] = self.exe("SELECT COUNT(*) as c FROM users WHERE is_banned=0")[0]['c']
        s['banned'] = self.exe("SELECT COUNT(*) as c FROM users WHERE is_banned=1")[0]['c']
        today = datetime.now().strftime("%Y-%m-%d")
        s['today'] = self.exe("SELECT COUNT(*) as c FROM users WHERE joined_at LIKE ?", (f"{today}%",))[0]['c']
        s['active24'] = self.exe("SELECT COUNT(*) as c FROM users WHERE last_active>?", ((datetime.now()-timedelta(hours=24)).isoformat(),))[0]['c']
        s['week'] = self.exe("SELECT COUNT(*) as c FROM users WHERE joined_at>?", ((datetime.now()-timedelta(days=7)).isoformat(),))[0]['c']
        s['total_msgs'] = self.exe("SELECT COALESCE(SUM(total_messages),0) as c FROM users")[0]['c']
        s['seg'] = {}
        for key in SEGMENTS:
            s['seg'][key] = self.exe("SELECT COUNT(*) as c FROM users WHERE is_banned=0 AND segment=?", (key,))[0]['c']
        try: s['giris_views'] = int(self.get_setting("giris_views") or "0")
        except: s['giris_views'] = 0
        return s

db = Database()

SITE_ID_HEADERS = [
    "Telegram ID", "Kullanici Adi", "Ad", "Soyad", "Site ID",
    "Ilk Kayit Tarihi", "Guncelleme Tarihi"
]

def validate_site_id(raw_value):
    """Site ID'yi kontrol karakterlerinden arindirir ve izinli bicimi dogrular."""
    value = _CTRL_CHARS.sub("", str(raw_value or "")).strip()
    if not (MIN_SITE_ID_LENGTH <= len(value) <= MAX_SITE_ID_LENGTH):
        return None
    if not SITE_ID_PATTERN.fullmatch(value):
        return None
    return value

def _site_id_export_rows():
    rows = []
    for record in db.list_site_id_records():
        rows.append([
            str(record["telegram_id"]),
            neutralize_for_file(record.get("username", "")),
            neutralize_for_file(record.get("first_name", "")),
            neutralize_for_file(record.get("last_name", "")),
            neutralize_for_file(record.get("site_id", "")),
            record.get("created_at", ""),
            record.get("updated_at", ""),
        ])
    return rows

def _replace_private_file(temp_path, final_path):
    os.replace(temp_path, final_path)
    try:
        os.chmod(final_path, 0o600)
    except OSError:
        pass

def export_site_id_records():
    """Veritabanindaki onayli Site ID kayitlarini CSV ve XLSX olarak atomik yeniler."""
    rows = _site_id_export_rows()
    csv_temp = SITE_ID_CSV + ".tmp"
    xlsx_temp = SITE_ID_XLSX + ".tmp"
    try:
        with open(csv_temp, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(SITE_ID_HEADERS)
            writer.writerows(rows)
        _replace_private_file(csv_temp, SITE_ID_CSV)

        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Site ID Kayitlari"
        sheet.append(SITE_ID_HEADERS)
        for row in rows:
            sheet.append(row)
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for cell in sheet[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        widths = [18, 22, 22, 22, 24, 22, 22]
        for index, width in enumerate(widths, start=1):
            sheet.column_dimensions[chr(64 + index)].width = width
        for cell in sheet["A"][1:]:
            cell.number_format = "@"
        for cell in sheet["E"][1:]:
            cell.number_format = "@"
        workbook.save(xlsx_temp)
        _replace_private_file(xlsx_temp, SITE_ID_XLSX)
    finally:
        for temp_path in (csv_temp, xlsx_temp):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
    return len(rows)

def secure_runtime_files():
    """Hassas yerel dosyalar icin sahip-okuma/yazma izinlerini uygular."""
    for path in (DB_PATH, os.path.join(BASE_DIR, "config.txt"), os.path.join(BASE_DIR, "admins.txt"), SITE_ID_CSV, SITE_ID_XLSX):
        try:
            if os.path.exists(path):
                os.chmod(path, 0o600)
        except OSError:
            pass

secure_runtime_files()

def active_campaign_media_library_id():
    try:
        return int(db.get_setting("active_campaign_media_library_id") or "0")
    except (TypeError, ValueError):
        return 0

def activate_campaign_media_record(media_row):
    """Kutuphanedeki kaydi mevcut /start medya ayarlarina uygular."""
    if not media_row:
        return False
    db.set_setting("campaign_media_id", media_row["media_id"])
    db.set_setting("campaign_media_type", media_row["media_type"])
    db.set_setting("campaign_media_file", "")
    db.set_setting("promo_image_file", "")
    db.set_setting("campaign_media_url", "")
    db.set_setting("active_campaign_media_library_id", str(media_row["id"]))
    return True

def migrate_current_campaign_media_to_library():
    """Eski surumdeki Telegram medya kimligini kutuphaneye bir kez aktarir."""
    current_id = (db.get_setting("campaign_media_id") or "").strip()
    current_type = (db.get_setting("campaign_media_type") or "photo").strip()
    if not current_id or current_type not in ("photo", "video"):
        return
    media_pk = db.add_campaign_media(current_type, current_id, "Eski aktif medya", 0)
    if not active_campaign_media_library_id():
        db.set_setting("active_campaign_media_library_id", str(media_pk))

migrate_current_campaign_media_to_library()
# =====================================================================
# SPAM & FLOOD KORUMASI
# - Kisa surede ardarda mesaj (SPAM_COUNT/SPAM_WINDOW) -> 30dk gecici ban
# - Ayni komutu SAME_CMD_COUNT kez ardarda -> spam sayilir
# - 3 kez gecici ban yiyen -> KALICI ban + tum adminlere kritik uyari
# =====================================================================
msg_times = defaultdict(list)      # genel mesaj zaman damgalari
cmd_times = defaultdict(list)      # (uid, komut) -> zamanlar
recent_contents = defaultdict(list)

# =====================================================================
# EKRAN GORUNTUSU KAYDI — yardimcilar
# Kullanici/admin bota foto gonderince kategori secenekleri sunulur; sectigi
# kategori, gonderdigi tarih ve yazdigi bilgiler (Site ID, arkadas ID, tutar...)
# DOSYA ADINA yazilarak screenshots/ klasorune kaydedilir.
# =====================================================================
SCREENSHOT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_TR_TRANSLIT = str.maketrans({
    "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
})

def _dosya_parcasi(value, limit=40, allow_dot=True):
    """Dosya adina girecek parcayi guvenli ASCII'ye indirger: Turkce harfler
    cevrilir, izinli olmayan her karakter '-' olur, bas/son ayiricilar kirpilir.
    '..' ve yol ayiricilari hicbir zaman olusmaz."""
    text = _CTRL_CHARS.sub("", str(value or "")).translate(_TR_TRANSLIT)
    pattern = r"[^A-Za-z0-9.]+" if allow_dot else r"[^A-Za-z0-9]+"
    text = re.sub(pattern, "-", text)
    text = re.sub(r"-{2,}", "-", text)
    text = re.sub(r"\.{2,}", ".", text)
    return text[:limit].strip("-.")

def parse_screenshot_categories(raw):
    """'anahtar:Buton Yazisi:Alan1|Alan2, anahtar2:...' tanimini listeye cevirir.
    Hatali/tekrarli parcalar atlanir; hic gecerli kategori yoksa bos liste doner."""
    cats, seen = [], set()
    for part in str(raw or "").split(","):
        part = _CTRL_CHARS.sub("", part).strip()
        if not part:
            continue
        pieces = part.split(":")
        if len(pieces) < 2:
            continue
        key = pieces[0].strip().lower()
        label = re.sub(r"\s+", " ", pieces[1].strip())[:40]
        fields_raw = ":".join(pieces[2:]) if len(pieces) > 2 else ""
        if not re.fullmatch(r"[a-z0-9_]{1,20}", key) or not label or key in seen:
            continue
        fields = []
        for f in fields_raw.split("|"):
            f = re.sub(r"\s+", " ", f.strip())[:30]
            if f and f not in fields:
                fields.append(f)
        seen.add(key)
        cats.append({"key": key, "label": label, "fields": fields[:SCREENSHOT_MAX_FIELDS]})
    return cats[:12]

def screenshot_categories():
    """Oncelik: panelden kaydedilen tanim > config.txt > yerlesik liste."""
    for raw in (db.get_setting("screenshot_categories"), DEFAULT_SCREENSHOT_CATEGORIES, BUILTIN_SCREENSHOT_CATEGORIES):
        cats = parse_screenshot_categories(raw)
        if cats:
            return cats
    return []

def screenshot_category(key):
    for c in screenshot_categories():
        if c["key"] == key:
            return c
    return None

def screenshots_enabled():
    val = db.get_setting("screenshots_enabled")
    if val in ("0", "1"):
        return val == "1"
    return SCREENSHOTS_ENABLED_DEFAULT

def screenshot_name_format():
    return ((db.get_setting("screenshot_name_format") or DEFAULT_SCREENSHOT_NAME_FORMAT).strip()
            or "{kategori}_{tarih}_{saat}_{alanlar}_{tgid}")

def _field_slug(label):
    return _dosya_parcasi(label, 30, allow_dot=False).lower().replace("-", "_")

def build_screenshot_filename(category, values, user_id, when=None, fmt=None, username=""):
    """Dosya adini (uzantisiz) sablondan uretir. Kullanicinin girdigi HER deger
    dosya adinda yer alir. Yer tutucular: {kategori} {kategori_kodu} {tarih}
    {saat} {alanlar} {tgid} {kullanici} {alan1} {alan2}... ve alan adi
    ({site_id}, {arkadas_id}, {tutar}...). Bilinmeyen yer tutucu bos kalir."""
    when = when or datetime.now()
    fmt = fmt or screenshot_name_format()
    if isinstance(category, dict):
        label, key, field_labels = category.get("label", ""), category.get("key", ""), category.get("fields", [])
    else:
        label, key, field_labels = str(category or ""), str(category or ""), []
    vals = [_dosya_parcasi(v) for v in (values or [])]
    vals_clean = [v for v in vals if v]
    uid = str(int(user_id or 0))
    repl = {
        "kategori": _dosya_parcasi(label, 40, allow_dot=False) or _dosya_parcasi(key, 20, allow_dot=False) or "Ekran",
        "kategori_kodu": _dosya_parcasi(key, 20, allow_dot=False) or "ekran",
        "tarih": when.strftime("%Y-%m-%d"),
        "saat": when.strftime("%H-%M-%S"),
        "alanlar": "_".join(vals_clean),
        "tgid": uid,
        "kullanici": _dosya_parcasi(username or "", 32, allow_dot=False) or uid,
    }
    for i, v in enumerate(vals, 1):
        repl[f"alan{i}"] = v
    for i, lab in enumerate(field_labels):
        slug = _field_slug(lab)
        if slug and slug not in repl:
            repl[slug] = vals[i] if i < len(vals) else ""
    name = re.sub(r"\{([^{}]+)\}", lambda m: repl.get(m.group(1).strip().lower(), ""), str(fmt))
    name = _CTRL_CHARS.sub("", name).translate(_TR_TRANSLIT)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    name = re.sub(r"_{2,}", "_", name)
    name = re.sub(r"-{2,}", "-", name)
    name = re.sub(r"\.{2,}", ".", name)
    name = name.strip("._-")[:150].rstrip("._-")
    if not name:
        name = f"Ekran_{when.strftime('%Y-%m-%d_%H-%M-%S')}_{uid}"
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = "Ekran_" + name
    return name

def _unique_screenshot_path(name, ext):
    """Ayni ad zaten varsa _2, _3... ekler. (tam_yol, dosya_adi) doner."""
    ext = ext if ext in SCREENSHOT_EXTENSIONS else ".jpg"
    for n in range(1, 1000):
        fname = f"{name}{'' if n == 1 else f'_{n}'}{ext}"
        path = os.path.join(SCREENSHOTS_DIR, fname)
        if not is_safe_path(SCREENSHOTS_DIR, path):
            break
        if not os.path.exists(path):
            return path, fname
    fname = f"{name}_{int(time.time())}{ext}"
    return os.path.join(SCREENSHOTS_DIR, fname), fname

def validate_screenshot_field(label, raw):
    """Kullanicinin yazdigi alan degerini dogrular; (deger, hata_metni) doner.
    Adinda 'ID' gecen alanlar Site ID kuraliyla (harf/rakam/./_/-) sinirlanir."""
    value = _CTRL_CHARS.sub("", str(raw or "")).strip()
    value = re.sub(r"\s+", " ", value)
    if not value:
        return "", "Boş olamaz."
    if len(value) > 60:
        return "", "En fazla 60 karakter olabilir."
    if re.search(r"\bid\b", str(label or ""), re.IGNORECASE):
        if not (MIN_SITE_ID_LENGTH <= len(value) <= MAX_SITE_ID_LENGTH) or not SITE_ID_PATTERN.match(value):
            return "", "Yalnızca harf, rakam, nokta, alt çizgi ve tire kullan (2–64 karakter)."
    if not _dosya_parcasi(value):
        return "", "Geçerli bir değer yaz (harf veya rakam içermeli)."
    return value, ""

def _record_and_check_flood(uid, content=""):
    """True donerse spam tespit edildi (gecici ban uygulanmali)."""
    now = time.time()
    msg_times[uid] = [t for t in msg_times[uid] if now - t < SPAM_WINDOW]
    msg_times[uid].append(now)
    if content:
        recent_contents[uid].append(content[:120])
        recent_contents[uid] = recent_contents[uid][-6:]
    return len(msg_times[uid]) >= SPAM_COUNT

def _check_same_command(uid, cmd):
    """Ayni komut kisa surede SAME_CMD_COUNT+ -> True (spam)."""
    now = time.time()
    key = (uid, cmd)
    cmd_times[key] = [t for t in cmd_times[key] if now - t < SAME_CMD_WINDOW]
    cmd_times[key].append(now)
    return len(cmd_times[key]) >= SAME_CMD_COUNT

async def _apply_temp_ban(context, user):
    """30dk gecici ban uygula; 3. kez ise kalici ban + admin uyarisi."""
    db.temp_ban(user.id, TEMP_BAN_MINUTES)
    strikes = db.inc_temp_ban(user.id)
    db.security_event("temp_ban", user.id, f"strike {strikes}")
    if strikes >= STRIKES_FOR_PERMA:
        # KALICI BAN
        db.ban_user(user.id, f"Tekrarlayan spam ({strikes} kez gecici ban)", by_admin=0)
        db.security_event("perma_ban", user.id, f"{strikes} strike")
        await _notify_admins_critical(context, user, strikes)
    return strikes

async def _notify_admins_critical(context, user, strikes):
    msgs = recent_contents.get(user.id, [])
    # Spam metinleri/isim HTML kipine CIG girerse uyari mesajinin kendisi cokuyordu.
    msg_list = "\n".join([f"  {i+1}. \"{sanitize_input(m, 120)}\"" for i, m in enumerate(msgs)]) or "  (yok)"
    uname = f"@{sanitize_input(user.username, 40)}" if user.username else "Yok"
    fname = sanitize_input(f"{user.first_name or ''} {user.last_name or ''}".strip() or "?", 80)
    txt = box_message("KRITIK: KALICI BAN", (
        f"\U0001f6a8 Tekrarlayan spam nedeniyle KALICI engellendi.\n\n"
        f"\u23f0 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
        f"\U0001f464 {fname} ({uname})\n"
        f"\U0001f194 <code>{user.id}</code>\n"
        f"\U0001f4ca Gecici ban sayisi: {strikes}\n\n"
        f"\U0001f4ac Son mesajlari:\n{msg_list}\n\n"
        f"<code>/unban {user.id}</code> - Kaldir"), "\u26d4")
    for aid in ADMIN_IDS:
        try: await context.bot.send_message(chat_id=aid, text=txt, parse_mode=ParseMode.HTML)
        except: pass

async def guard_flood(update, context, content="", is_command=False, cmd=""):
    """Ortak guvenlik kapisi. True donerse cagiran fonksiyon ISLEMI DURDURMALI."""
    user = update.effective_user
    if db.is_banned(user.id):
        return True
    if db.is_temp_banned(user.id):
        return True
    spam = False
    if is_command:
        # Komut spam'i: ayni komut 3+ kez ardarda
        if _check_same_command(user.id, cmd):
            spam = True
        # Komutlar ayrica genel sayaca eklenmez (istek: standart komutlar saymaz)
    else:
        spam = _record_and_check_flood(user.id, content)
    if spam:
        await _apply_temp_ban(context, user)
        try:
            await update.message.reply_text(
                box_message("ENGEL", "Cok hizli islem yapiyorsunuz. Guvenlik nedeniyle 30 dakika engellendiniz.", "\u26a0\ufe0f"),
                parse_mode=ParseMode.HTML)
        except: pass
        return True
    return False

# =====================================================================
# SOL ALT PLAY MENU BUTONU
# Oncelik: "play_link" ayari -> config PLAY_LINK -> guncel giris linki.
# =====================================================================
def _current_play_link():
    link = (db.get_setting("play_link") or DEFAULT_PLAY_LINK
            or db.get_setting("giris_link") or DEFAULT_GIRIS_LINK).strip()
    if not link.lower().startswith("https://") or not is_valid_url(link):
        raise ValueError("Play menu butonu icin gecerli bir HTTPS link gerekli.")
    return link


def _build_play_menu_button():
    menu_text = _plain_label((db.get_setting("menu_button_text") or PLAY_MENU_TEXT).strip(), 64)
    return MenuButtonWebApp(text=menu_text, web_app=WebAppInfo(url=_current_play_link()))


# ReplyKeyboard pasife alindi, Play butonu tek sabit buton olarak kalacak.


async def _apply_play_menu_buttons(bot):
    """Sol alt menu butonunu varsayilan sohbete ve admin sohbetlerine uygular.

    MENU_BUTTON_MODE=menu: komut menusu (⌘ simgesi gorunur, komutlar listelenir).
    MENU_BUTTON_MODE=play: web-app PLAY butonu. DIKKAT: guncel web Telegram,
    web-app butonu ayarli botlarda ⌘ komut simgesini gizler; ikisi birlikte olmaz.
    Play secilir ama link gecersizse yine komut menusune geri duseriz.
    """
    sonuc = True
    if MENU_BUTTON_MODE == "menu":
        button = MenuButtonCommands()
    else:
        try:
            button = _build_play_menu_button()
        except ValueError as exc:
            logger.warning(f"[PLAY MENU] {exc} Komut menusune donuldu.")
            button = MenuButtonCommands()
            sonuc = "fallback"

    try:
        await bot.set_chat_menu_button(menu_button=button)
    except Exception as exc:
        logger.warning(f"[PLAY MENU] varsayilan menu ayarlanamadi: {exc}")
        return False

    for admin_id in ADMIN_IDS:
        try:
            await bot.set_chat_menu_button(chat_id=admin_id, menu_button=button)
        except Exception as exc:
            logger.warning(f"[PLAY MENU] {admin_id}: {exc}")
    return sonuc

# =====================================================================
# GIRIS SABLONU
# _build_start_inline: /start ilk mesajinda yalnizca uyelik baglantisi
# _build_giris_only:   giris sablonunda guncel giris link butonu
# =====================================================================
def _build_start_inline():
    reg_link = db.get_setting("register_link") or DEFAULT_REGISTER_LINK
    reg_btn = _plain_label(db.get_setting("register_btn_text") or DEFAULT_REGISTER_BTN, 40)
    
    # Giris Yap butonu
    giris_link = db.get_setting("giris_link") or DEFAULT_GIRIS_LINK
    giris_btn = _plain_label(db.get_setting("giris_btn_text") or DEFAULT_GIRIS_BTN, 40)
    
    # Konsol butonu (Opsiyonel)
    console_link = db.get_setting("console_link")
    console_btn = _plain_label(db.get_setting("console_btn_text") or "💻 Konsol", 40)
    
    # Gecersiz/bos URL'li tek buton bile TUM mesaji reddettirir; yalnizca
    # gecerli linkli butonlari ekle (aksi halde /start tamamen susuyordu).
    row1 = []
    if is_valid_url(reg_link):
        row1.append(InlineKeyboardButton(reg_btn, url=reg_link))
    if is_valid_url(giris_link):
        row1.append(InlineKeyboardButton(giris_btn, url=giris_link))

    kb = [row1] if row1 else []
    if console_link and is_valid_url(console_link):
        kb.append([InlineKeyboardButton(console_btn, url=console_link)])

    return InlineKeyboardMarkup(kb) if kb else None

def _build_giris_only():
    giris_link = db.get_setting("giris_link") or DEFAULT_GIRIS_LINK
    giris_btn  = _plain_label(db.get_setting("giris_btn_text") or DEFAULT_GIRIS_BTN, 40)
    if not is_valid_url(giris_link):
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(giris_btn, url=giris_link)]])

def _count_giris_view():
    try: cur = int(db.get_setting("giris_views") or "0")
    except: cur = 0
    db.set_setting("giris_views", str(cur + 1))

# Kullaniciya: icinde Guncel Giris link butonu olan mesaj.
# Ayrica mesaj kutusunun yaninda kalici tek "Guncel Giris" butonunu da garanti eder.
async def send_giris(update, context):
    _count_giris_view()
    text = db.get_setting("giris_text") or DEFAULT_GIRIS_TEXT
    msg = box_message(DEFAULT_GIRIS_TITLE, text, "\U0001f517")
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML,
        reply_markup=_build_giris_only())

async def _send_giris_chat(context, chat_id):
    _count_giris_view()
    text = db.get_setting("giris_text") or DEFAULT_GIRIS_TEXT
    msg = box_message(DEFAULT_GIRIS_TITLE, text, "\U0001f517")
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML,
        reply_markup=_build_giris_only())

# =====================================================================
# /START - Site ID kayit kapisi ve onayli karsilama
# Kayitsiz kullanici: karsilama -> kanal linki -> Site ID istegi (kayit akisi)
# Kayitli kullanici:  karsilama + kampanya medyasi (mevcut akis)
# =====================================================================
SITE_ID_WAIT_INPUT = 200
SITE_ID_WAIT_CONFIRM = 201

async def _send_channel_message(context, chat_id):
    """Kanal linki tanimliysa tiklanabilir kanal mesajini gonderir."""
    channel_link = (db.get_setting("channel_link") or DEFAULT_CHANNEL_LINK).strip()
    channel_text = _safe_setting_text("channel_text", DEFAULT_CHANNEL_TEXT, 120)
    if is_valid_url(channel_link):
        await context.bot.send_message(chat_id=chat_id,
            text=f'<a href="{channel_link}">{channel_text}</a>',
            parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def _send_registered_start(context, user, chat_id):
    """Standart /start akisi: karsilama (+2 buton) -> kanal -> gunun kampanyasi.

    Karsilama gorseli panelden secildiyse butonlar gorselin altina eklenir;
    secilmediyse metin karsilamasi gonderilir (kampanya gorseli zaten pesinden
    geldigi icin ayni gorsel iki kez tekrarlanmaz).
    """
    user_name = user.first_name or user.username or "Degerli Uyemiz"
    welcome = personalize_text(db.get_setting("welcome_text") or DEFAULT_WELCOME, user_name)
    kb = _build_start_inline()
    try:
        if not await _send_welcome_media(context, chat_id, welcome, reply_markup=kb, allow_fallback=False):
            await context.bot.send_message(chat_id=chat_id, text=welcome, parse_mode=ParseMode.HTML,
                reply_markup=kb)
    except Exception as exc:
        logger.warning(f"[KARSILAMA] gonderilemedi: {exc}")
    try:
        await _send_channel_message(context, chat_id)
    except Exception as exc:
        logger.warning(f"[KANAL] gonderilemedi: {exc}")
    await asyncio.sleep(0.5)
    # Kampanya medyasini gonderirken sabit menuyu de ekliyoruz
    try:
        await send_campaign_media(context, chat_id)
    except Exception as exc:
        logger.warning(f"[KAMPANYA] gonderilemedi: {exc}")
    # ANA MENU mesaji istege bagli (varsayilan KAPALI: menu zaten ikonun
    # icindeki alt klavyede; kullanici Ana Menü butonuyla/komutla acar).
    if SEND_MAIN_MENU_ON_START:
        try:
            await send_main_menu(context, chat_id)
        except Exception as exc:
            logger.warning(f"[ANA MENU] gonderilemedi: {exc}")
    # Kalici alt klavye menusu: yazi alanindaki ⌘ simgesini olusturur.
    menu_kb = _build_reply_menu()
    if menu_kb:
        try:
            await context.bot.send_message(chat_id=chat_id, text=REPLY_MENU_PROMPT, reply_markup=menu_kb)
        except Exception as exc:
            logger.warning(f"[REPLY MENU] gonderilemedi: {exc}")
    logger.info(f"[START] {user.id} - {user_name}")

def _build_site_id_prompt():
    """Site ID isteme mesaji: kayit linki ve Profil menusu notu ile."""
    prompt = _safe_setting_text("site_id_prompt", DEFAULT_SITE_ID_PROMPT, 300)
    parts = [prompt]
    reg_link = (db.get_setting("register_link") or DEFAULT_REGISTER_LINK).strip()
    if is_valid_url(reg_link):
        reg_text = sanitize_input(DEFAULT_REGISTER_LINK_TEXT, 60)
        parts.append(f'Bir hesabın yoksa \U0001f449 <a href="{reg_link}">{reg_text}</a>')
    parts.append("<i>Bunu daha sonra \U0001f934 Profil menüsünden de yapabilirsin.</i>")
    return "\n\n".join(parts)

async def _send_welcome_media(context, chat_id, caption, reply_markup=None, allow_fallback=True):
    """Karsilama gorselini/videosunu aciklama (+istege bagli butonlar) ile gonderir.

    Kaynak onceligi: karsilama medyasi (kutuphaneden secilen id) -> karsilama
    medya URL'si -> (allow_fallback ise) aktif kampanya medyasi -> promo.jpg.
    allow_fallback=False, kampanya medyasi hemen ardindan gonderilecegi
    durumda ayni gorselin iki kez tekrarlanmasini onler.
    Basarirsa True; medya yoksa veya gonderim hata verirse False doner.
    """
    caption = _safe_caption(caption) if caption else caption

    async def _send(media, mtype):
        if mtype == "video":
            await context.bot.send_video(chat_id=chat_id, video=media, caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=reply_markup)
        else:
            await context.bot.send_photo(chat_id=chat_id, photo=media, caption=caption,
                parse_mode=ParseMode.HTML, reply_markup=reply_markup)

    media_id = db.get_setting("welcome_media_id") or ""
    media_type = db.get_setting("welcome_media_type") or "photo"
    media_url = (db.get_setting("welcome_media_url") or DEFAULT_WELCOME_MEDIA_URL).strip()
    try:
        if media_id:
            await _send(media_id, media_type)
            return True
        if media_url and is_valid_url(media_url):
            await _send(media_url, _media_kind(media_url))
            return True
        if allow_fallback:
            camp_id = db.get_setting("campaign_media_id") or ""
            if camp_id:
                await _send(camp_id, db.get_setting("campaign_media_type") or "photo")
                return True
            local_media = os.path.join(IMAGES_DIR, "promo.jpg")
            if os.path.exists(local_media) and is_safe_path(IMAGES_DIR, local_media):
                with open(local_media, "rb") as media:
                    await _send(media, "photo")
                return True
    except Exception as exc:
        logger.warning(f"Karsilama medyasi gonderilemedi: {exc}")
    return False

async def _send_onboarding(context, user, chat_id):
    """SITE_ID_ON_START=1 iken kayitsiz acilis: gorselli karsilama, kanal, Site ID istegi."""
    user_name = user.first_name or user.username or "Degerli Uyemiz"
    welcome = personalize_text(db.get_setting("welcome_text") or DEFAULT_WELCOME, user_name)
    if not await _send_welcome_media(context, chat_id, welcome):
        await context.bot.send_message(chat_id=chat_id, text=welcome, parse_mode=ParseMode.HTML)

    await _send_channel_message(context, chat_id)

    await context.bot.send_message(chat_id=chat_id, text=_build_site_id_prompt(),
        parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    logger.info(f"[START-KAYIT] {user.id} - Site ID istendi")

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/start"):
        return ConversationHandler.END
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    db.log(user.id, "start")
    context.user_data.pop("pending_site_id", None)
    # Yarim kalmis ekran goruntusu akisi varsa birak (akis /start'i yutmaz; Site ID
    # kaydi eskisi gibi calisir). Kalan durum, bir sonraki mesajda sessizce kapanir.
    _ss_reset(context)
    chat_id = update.effective_chat.id
    # Yarim kalmis bir onay ekrani varsa butonlarini pasiflestir.
    await _clear_confirm_buttons(context, chat_id)
    if SITE_ID_ON_START and not db.get_site_id_record(user.id):
        # Site ID akisi ACIK ve kullanici kayitsiz: kayit akisini baslat.
        await _send_onboarding(context, user, chat_id)
        return SITE_ID_WAIT_INPUT
    # Varsayilan akis: karsilama + butonlar -> kanal -> gunun kampanyasi.
    # Site ID istege bagli olarak /profil menusunden yonetilir.
    await _send_registered_start(context, user, chat_id)
    return ConversationHandler.END

async def _clear_confirm_buttons(context, chat_id):
    """Bekleyen onay ekraninin Evet/Hayir butonlarini pasiflestirir (varsa)."""
    mid = context.user_data.pop("site_confirm_mid", None)
    if mid:
        try:
            await context.bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
        except Exception:
            pass

async def site_id_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kayit akisinda /iptal: veri saklanmaz, akis kapanir."""
    context.user_data.pop("pending_site_id", None)
    await _clear_confirm_buttons(context, update.effective_chat.id)
    await update.message.reply_text("İşlem iptal edildi")
    return ConversationHandler.END

async def site_id_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending_site_id", None)
    try:
        chat = update.effective_chat
        if chat:
            await _clear_confirm_buttons(context, chat.id)
            await context.bot.send_message(chat_id=chat.id,
                text="⏳ Kayıt için süre doldu. Yeniden başlamak için /start yazabilirsin.")
    except Exception:
        pass
    return ConversationHandler.END

async def stale_button_cb(update, context):
    """Suresi dolmus sihirbaz butonlari icin son durak: spinner donmesin."""
    q = update.callback_query
    u = update.effective_user
    if u and (db.is_banned(u.id) or db.is_temp_banned(u.id)):
        try: await q.answer()
        except Exception: pass
        return
    try:
        await q.answer("Bu buton eski ya da islem suresi doldu. Ilgili menuyu yeniden acin.", show_alert=True)
    except Exception:
        pass

async def site_confirm_stale_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Akis kapandiktan sonra eski Evet/Hayir butonlari: donme animasyoni yerine bilgi ver."""
    query = update.callback_query
    try:
        await query.answer("Oturum sona erdi. /start yazın.")
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

async def site_id_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    raw_value = update.message.text or ""
    if await guard_flood(update, context, content=raw_value):
        return ConversationHandler.END
    site_id = validate_site_id(raw_value)
    if not site_id:
        await update.message.reply_text(
            box_message("GECERSIZ SITE ID", f"Site ID {MIN_SITE_ID_LENGTH}-{MAX_SITE_ID_LENGTH} karakter olmali; "
                        "yalnizca harf, rakam, nokta, alt cizgi veya tire icermelidir.\n\nTekrar girin.", "\u274c"),
            parse_mode=ParseMode.HTML)
        return SITE_ID_WAIT_INPUT

    context.user_data["pending_site_id"] = site_id
    username = f"@{user.username}" if user.username else "Yok"
    full_name = " ".join(part for part in (user.first_name, user.last_name) if part) or "Yok"
    summary = (
        f"<b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"<b>Kullanici adi:</b> {sanitize_input(username, 80)}\n"
        f"<b>Ad:</b> {sanitize_input(full_name, 120)}\n"
        f"<b>Site ID:</b> <code>{sanitize_input(site_id, MAX_SITE_ID_LENGTH)}</code>\n\n"
        "Bu bilgileri kaydetmek istediginizden emin misiniz?")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Evet, Kaydet", callback_data="site_confirm_yes")],
        [InlineKeyboardButton("Hayir, Yeniden Gir", callback_data="site_confirm_no")],
    ])
    # Eski bir onay ekrani bekliyorsa once onun butonlarini kaldir (yeni ID yazildi).
    await _clear_confirm_buttons(context, update.effective_chat.id)
    sent = await update.message.reply_text(box_message("BILGILERI DOGRULAYIN", summary, "\U0001f50d"),
        parse_mode=ParseMode.HTML, reply_markup=keyboard)
    context.user_data["site_confirm_mid"] = getattr(sent, "message_id", None)
    return SITE_ID_WAIT_CONFIRM

async def site_id_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        context.user_data.pop("pending_site_id", None)
        return ConversationHandler.END
    context.user_data.pop("site_confirm_mid", None)
    site_id = context.user_data.get("pending_site_id")
    if not site_id:
        await query.edit_message_text("Kayit oturumu sona erdi. Yeniden /start yazin.")
        return ConversationHandler.END
    if query.data == "site_confirm_no":
        context.user_data.pop("pending_site_id", None)
        await query.edit_message_text(box_message("YENIDEN GIRIN", "Dogru Site ID'yi mesaj olarak gonderin.", "\u270f\ufe0f"),
            parse_mode=ParseMode.HTML)
        return SITE_ID_WAIT_INPUT

    user = update.effective_user
    db.upsert_site_id(user.id, user.username, user.first_name, user.last_name, site_id)
    export_error = None
    try:
        await asyncio.to_thread(export_site_id_records)
        secure_runtime_files()
    except Exception as exc:
        export_error = str(exc)
        logger.exception("Site ID dosyalari guncellenemedi")
        db.security_event("site_id_export_error", user.id, export_error[:300])
    db.log(user.id, "site_id_confirmed", site_id)
    context.user_data.pop("pending_site_id", None)
    await query.edit_message_text(box_message("KAYIT TAMAMLANDI", "Bilgileriniz onaylanarak kaydedildi.", "\u2705"),
        parse_mode=ParseMode.HTML)
    if export_error:
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(admin_id, box_message("DOSYA UYARISI", "Site ID veritabanina kaydedildi ancak CSV/Excel yenilenemedi. Loglari kontrol edin.", "\u26a0\ufe0f"), parse_mode=ParseMode.HTML)
            except Exception:
                pass
    await _send_registered_start(context, user, update.effective_chat.id)
    return ConversationHandler.END

# /giris -> sadece guncel giris sablonu
async def giris_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/giris"):
        return
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, 'language_code', ''))
    db.inc_msg(user.id)
    await send_giris(update, context)

# =====================================================================
# /PROFIL - Kullanici profil menusu (Site ID goruntule/degistir)
# =====================================================================
def _build_profile_view(user):
    record = db.get_site_id_record(user.id)
    uname = f"@{user.username}" if user.username else "Yok"
    full_name = " ".join(p for p in (user.first_name, user.last_name) if p) or "Yok"
    if record:
        site_line = f"<b>Site ID:</b> <code>{sanitize_input(record['site_id'], MAX_SITE_ID_LENGTH)}</code>"
        date_line = f"<b>Son güncelleme:</b> {str(record['updated_at'])[:16].replace('T', ' ')}"
        siteid_btn = "\U0001f194 Site ID Değiştir"
    else:
        site_line = "<b>Site ID:</b> Henüz kayıtlı değil"
        date_line = "Yeni bonuslar için Site ID'ni ekleyebilirsin \U0001f447"
        siteid_btn = "\U0001f194 Site ID Gir"
    text = box_message("PROFİL", (
        f"<b>Ad:</b> {sanitize_input(full_name, 120)}\n"
        f"<b>Kullanıcı adı:</b> {sanitize_input(uname, 80)}\n"
        f"<b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"{site_line}\n{date_line}"), "\U0001f934")
    giris_link = db.get_setting("giris_link") or DEFAULT_GIRIS_LINK
    giris_btn = _plain_label(db.get_setting("giris_btn_text") or DEFAULT_GIRIS_BTN, 40)
    ikinci_satir = [InlineKeyboardButton("\U0001f381 Kampanya", callback_data="profil_kampanya")]
    # Gecersiz/bos URL tek basina TUM profili Telegram'da reddettirir.
    if is_valid_url(giris_link):
        ikinci_satir.insert(0, InlineKeyboardButton(giris_btn, url=giris_link))
    kb = [[InlineKeyboardButton(siteid_btn, callback_data="profil_siteid")],
          ikinci_satir]
    return text, InlineKeyboardMarkup(kb)

async def profil_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/profil"):
        return
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    text, kb = _build_profile_view(user)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

# Buton spam'ine karsi basit soğuma süresi (callback'ler guard_flood'dan gecmez)
_cb_last_press = {}

def _cb_throttled(uid, key, seconds):
    now = time.time()
    if now - _cb_last_press.get((uid, key), 0.0) < seconds:
        return True
    _cb_last_press[(uid, key)] = now
    return False

async def profil_siteid_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Profil menusunden Site ID girisi baslatir (kayit akisiyla ayni dogrulama)."""
    query = update.callback_query
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        await query.answer()
        return ConversationHandler.END
    if _cb_throttled(user.id, "profil_siteid", 3):
        # None: mevcut conversation durumuna dokunma, yeni akis da baslatma.
        await query.answer("Lütfen bekleyin.")
        return None
    await query.answer()
    context.user_data.pop("pending_site_id", None)
    # 48 saatten eski mesajlarda query.message erisilemez golgedir (chat_id yok);
    # effective_chat her durumda gecerlidir.
    await context.bot.send_message(chat_id=update.effective_chat.id,
        text=box_message("SİTE ID", "Yeni Site ID'ni mesaj olarak gönder.\n\nVazgeçmek için /iptal yazabilirsin.", "\U0001f194"),
        parse_mode=ParseMode.HTML)
    return SITE_ID_WAIT_INPUT

async def profil_kampanya_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        await query.answer()
        return
    # Medya gonderimi maliyetli: ayni kullanici 15 sn'de bir tetikleyebilir.
    if _cb_throttled(user.id, "profil_kampanya", 15):
        await query.answer("Lütfen birkaç saniye bekleyin.")
        return
    await query.answer()
    await send_campaign_media(context, update.effective_chat.id)

# =====================================================================
# ANA MENU (kullanici) — 13 buton, kategori listeleri, duyurular, SSS
# =====================================================================
def _menu_link(key, default):
    val = (db.get_setting(key) or default or "").strip()
    return val if is_valid_url(val) else ""

def build_main_menu():
    giris = _menu_link("giris_link", DEFAULT_GIRIS_LINK) or DEFAULT_GIRIS_LINK
    if not is_valid_url(giris):
        giris = "https://example.com/login"  # misconfig'de menu tamamen dusmesin
    miniapp = (_menu_link("miniapp_link", DEFAULT_MINIAPP_LINK)
               or _menu_link("play_link", DEFAULT_PLAY_LINK) or giris)
    deposit = _menu_link("deposit_link", DEFAULT_DEPOSIT_LINK) or giris
    withdraw = _menu_link("withdraw_link", DEFAULT_WITHDRAW_LINK) or giris
    support = _menu_link("support_link", DEFAULT_SUPPORT_LINK) or DEFAULT_SUPPORT_LINK
    if miniapp.lower().startswith("https://"):
        miniapp_btn = InlineKeyboardButton("\U0001f4f1 Mini App", web_app=WebAppInfo(url=miniapp))
    else:
        miniapp_btn = InlineKeyboardButton("\U0001f4f1 Mini App", url=miniapp or giris)
    rows = [
        [InlineKeyboardButton("\U0001f3e0 Siteye Giriş", url=giris), miniapp_btn],
        [InlineKeyboardButton(CAMPAIGN_CATEGORIES["bonus"], callback_data="um_cat_bonus"),
         InlineKeyboardButton(CAMPAIGN_CATEGORIES["yeni_uye"], callback_data="um_cat_yeni_uye")],
        [InlineKeyboardButton(CAMPAIGN_CATEGORIES["slot"], callback_data="um_cat_slot"),
         InlineKeyboardButton(CAMPAIGN_CATEGORIES["spor"], callback_data="um_cat_spor")],
        [InlineKeyboardButton(CAMPAIGN_CATEGORIES["ozel"], callback_data="um_cat_ozel"),
         InlineKeyboardButton(CAMPAIGN_CATEGORIES["turnuva"], callback_data="um_cat_turnuva")],
        [InlineKeyboardButton("\U0001f4b0 Para Yatır", url=deposit),
         InlineKeyboardButton("\U0001f4b8 Para Çek", url=withdraw)],
        [InlineKeyboardButton("\U0001f4e2 Duyurular", callback_data="um_ann"),
         InlineKeyboardButton("❓ Sık Sorulan Sorular", callback_data="um_faq")],
    ]
    # Ekran goruntusu kaydi acikken: once bilgiler, sonra foto yolu (giris yolu 2).
    if screenshots_enabled():
        rows.append([InlineKeyboardButton("\U0001f4f8 Ekran Görüntüsü Gönder", callback_data="um_ekran")])
    # Gecersiz destek linki tum menuyu Telegram'da reddettirirdi; gecerliyse
    # linkli, degilse akilli destek merkezine yonlendiren buton koy.
    if is_valid_url(support):
        rows.append([InlineKeyboardButton("\U0001f4ac Canlı Destek", url=support)])
    else:
        rows.append([InlineKeyboardButton("\U0001f4ac Canlı Destek", callback_data="um_destek")])
    return InlineKeyboardMarkup(rows)

def _main_menu_text():
    return box_message(MAIN_MENU_TITLE, MAIN_MENU_TEXT, "")

async def send_main_menu(context, chat_id):
    await context.bot.send_message(chat_id=chat_id, text=_main_menu_text(),
        parse_mode=ParseMode.HTML, reply_markup=build_main_menu())

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/menu"):
        return
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    await send_main_menu(context, update.effective_chat.id)

def _plain_label(text, limit=40):
    """Inline buton etiketi DUZ metindir; kayitta kacirilmis HTML'i geri cevir."""
    import html as _html
    return _html.unescape(str(text or ""))[:limit]

def _campaign_expiry_line(camp):
    exp = (camp.get("expires_at") or "").strip()
    if not exp:
        return ""
    try:
        dt = datetime.fromisoformat(exp)
        kalan = dt - datetime.now()
        if kalan.total_seconds() <= 0:
            return ""
        if kalan.total_seconds() < 3600:
            kalan_txt = f"{max(1, int(kalan.total_seconds() // 60))} dk"
        elif kalan.total_seconds() < 86400:
            kalan_txt = f"{int(kalan.total_seconds() // 3600)} saat"
        else:
            kalan_txt = f"{kalan.days} gün"
        return f"\n⏳ <b>Bitiş:</b> {dt.strftime('%d.%m.%Y %H:%M')} (son {kalan_txt})"
    except ValueError:
        return ""

def build_campaign_detail_text(camp):
    # Alanlar sihirbazda kayit ANINDA kacirildi; burada ikinci kez kacirmak
    # kullaniciya "&amp;amp;" gosteriyordu.
    parts = [f"<b>{camp['title']}</b>"]
    if camp.get("body"):
        parts.append(render_rich_tokens(render_clickable_tokens(camp["body"])))
    if camp.get("prize_pool"):
        parts.append(f"\U0001f3c6 <b>Ödül Havuzu:</b> {camp['prize_pool']}")
    if camp.get("conditions"):
        parts.append(f"\U0001f4cb <b>Katılım Şartları:</b>\n{camp['conditions']}")
    text = "\n\n".join(parts)
    return text + _campaign_expiry_line(camp)

def _campaign_detail_kb(camp):
    rows = []
    if camp.get("btn_text") and is_valid_url(camp.get("btn_url") or ""):
        rows.append([InlineKeyboardButton(camp["btn_text"][:40], url=camp["btn_url"])])
    rows.append([InlineKeyboardButton("◀️ Geri", callback_data=f"um_cat_{camp['category']}"),
                 InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")])
    return InlineKeyboardMarkup(rows)

def _safe_caption(text, limit=1024):
    """Medya aciklamasini Telegram sinirina EMNIYETLI kisaltir.

    Kesim HTML etiketini ortadan bolebileceginden, uzun metinlerde etiketler
    tamamen soyulup duz metin dondurulur (parse hatasi = medya kaybi olmasin)."""
    if len(text) <= limit:
        return text
    duz = re.sub(r"<[^>]+>", "", text)
    return duz[:limit - 1] + "…"

def _user_segments(user_id):
    """Kullanicinin dahil oldugu segmentler: manuel kademe + otomatik yeni/aktif."""
    segs = set()
    u = db.get_user(user_id)
    if not u:
        return segs
    if u.get("segment"):
        segs.add(u["segment"])
    try:
        joined = datetime.fromisoformat(str(u.get("joined_at") or ""))
        if (datetime.now() - joined).days < 7:
            segs.add("yeni")
    except ValueError:
        pass
    try:
        last = datetime.fromisoformat(str(u.get("last_active") or ""))
        if (datetime.now() - last).total_seconds() < 48 * 3600:
            segs.add("aktif")
    except ValueError:
        pass
    return segs

def _category_screen(user_id, key):
    """Kategori listesi ekrani: (metin, klavye). Komut ve callback ayni ekrani kullanir."""
    camps = db.list_campaigns(category=key, segment=_user_segments(user_id))
    baslik = CAMPAIGN_CATEGORIES[key]
    if not camps:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]])
        return box_message(baslik, "Şu anda bu bölümde aktif kampanya yok. Yakında burada! \U0001f440", ""), kb
    rows = [[InlineKeyboardButton(_plain_label(c["title"], 40) or f"Kampanya #{c['id']}",
                                  callback_data=f"um_camp_{c['id']}")] for c in camps[:10]]
    rows.append([InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")])
    return box_message(baslik, "Detay için bir kampanyaya dokun \U0001f447", ""), InlineKeyboardMarkup(rows)

def _ann_screen():
    anns = db.list_announcements(limit=10)
    if not anns:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]])
        return box_message("\U0001f4e2 DUYURULAR", "Henüz duyuru yok.", ""), kb
    rows = [[InlineKeyboardButton(f"{str(a['created_at'])[8:10]}.{str(a['created_at'])[5:7]} • " +
                                  (_plain_label(a["title"], 34) or f"Duyuru #{a['id']}"),
                                  callback_data=f"um_annv_{a['id']}")] for a in anns]
    rows.append([InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")])
    return box_message("\U0001f4e2 DUYURULAR", "Okumak için dokun \U0001f447", ""), InlineKeyboardMarkup(rows)

def _faq_screen():
    faqs = db.list_faqs()
    if not faqs:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]])
        return box_message("❓ SIK SORULAN SORULAR", "Henüz soru eklenmemiş.", ""), kb
    rows = [[InlineKeyboardButton(_plain_label(f["question"], 44) or f"Soru #{f['id']}",
                                  callback_data=f"um_faqv_{f['id']}")] for f in faqs[:15]]
    rows.append([InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")])
    return box_message("❓ SIK SORULAN SORULAR", "Sorunun cevabı için dokun \U0001f447", ""), InlineKeyboardMarkup(rows)

async def _um_show(query, context, text, kb):
    """Menu ekranini gosterir: metin mesajlari duzenlenir; medya mesajindan
    gelindiyse (edit imkansiz) yeni mesaj gonderilir — Geri butonu hep calisir."""
    msg = query.message
    if msg is not None and getattr(msg, "text", None):
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML,
                reply_markup=kb, disable_web_page_preview=True)
            return
        except Exception:
            pass
    # Eski (erisilemez) mesaj golgesinde chat_id yoktur ama .chat vardir.
    hedef = getattr(getattr(msg, "chat", None), "id", None)
    if hedef is None:
        return
    await context.bot.send_message(chat_id=hedef, text=text, parse_mode=ParseMode.HTML,
        reply_markup=kb, disable_web_page_preview=True)

async def user_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ana menu callback'leri: kategoriler, kampanya detayi, duyurular, SSS."""
    query = update.callback_query
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        await query.answer()
        return
    if _cb_throttled(user.id, "um", 1.2):
        await query.answer("Lütfen bekleyin.")
        return
    await query.answer()
    # Inline menuyle gezinmek de aktifliktir; "aktif" segmenti (48s) dusmesin.
    try:
        db.exe("UPDATE users SET last_active=? WHERE user_id=?", (datetime.now().isoformat(), user.id))
    except Exception:
        pass
    data = query.data
    chat_id = update.effective_chat.id

    if data == "um_main":
        try:
            await _um_show(query, context, _main_menu_text(), build_main_menu())
        except Exception:
            await send_main_menu(context, chat_id)
        return

    if data.startswith("um_cat_"):
        key = data[len("um_cat_"):]
        if key not in CAMPAIGN_CATEGORIES:
            return
        text, kb = _category_screen(user.id, key)
        await _um_show(query, context, text, kb)
        return

    if data.startswith("um_camp_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        camp = db.get_campaign(cid)
        now = datetime.now().isoformat(timespec="seconds")
        segment_dis = camp and camp.get("segment") and camp["segment"] not in _user_segments(user.id)
        if not camp or not camp["active"] or segment_dis or (camp["expires_at"] and camp["expires_at"] <= now):
            await _um_show(query, context, box_message("KAMPANYA", "Bu kampanyanın süresi doldu veya kaldırıldı.", "⌛"),
                InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]]))
            return
        text = build_campaign_detail_text(camp)
        kb = _campaign_detail_kb(camp)
        if camp.get("media_id"):
            try:
                if (camp.get("media_type") or "photo") == "video":
                    await context.bot.send_video(chat_id=chat_id, video=camp["media_id"], caption=_safe_caption(text),
                        parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await context.bot.send_photo(chat_id=chat_id, photo=camp["media_id"], caption=_safe_caption(text),
                        parse_mode=ParseMode.HTML, reply_markup=kb)
                return
            except Exception as exc:
                logger.warning(f"[MENU] kampanya medyasi gonderilemedi #{cid}: {exc}")
        await _um_show(query, context, text, kb)
        return

    if data == "um_ann":
        text, kb = _ann_screen()
        await _um_show(query, context, text, kb)
        return

    if data.startswith("um_annv_"):
        try: aid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        ann = db.get_announcement(aid)
        if not ann or not ann["active"]:
            await _um_show(query, context, box_message("DUYURU", "Bu duyuru kaldırıldı.", "⌛"),
                InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Duyurular", callback_data="um_ann"),
                                       InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]]))
            return
        text = (f"<b>{ann['title']}</b>\n\n"
                f"{render_rich_tokens(render_clickable_tokens(ann['body']))}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Duyurular", callback_data="um_ann"),
                                    InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]])
        if ann.get("media_id"):
            try:
                if (ann.get("media_type") or "photo") == "video":
                    await context.bot.send_video(chat_id=chat_id, video=ann["media_id"], caption=_safe_caption(text),
                        parse_mode=ParseMode.HTML, reply_markup=kb)
                else:
                    await context.bot.send_photo(chat_id=chat_id, photo=ann["media_id"], caption=_safe_caption(text),
                        parse_mode=ParseMode.HTML, reply_markup=kb)
                return
            except Exception as exc:
                logger.warning(f"[MENU] duyuru medyasi gonderilemedi #{aid}: {exc}")
        await _um_show(query, context, text, kb)
        return

    if data == "um_faq":
        text, kb = _faq_screen()
        await _um_show(query, context, text, kb)
        return

    if data == "um_destek":
        text, kb = _destek_screen()
        await _um_show(query, context, text, kb)
        return

    if data.startswith("um_faqv_"):
        try: fid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        faq = db.get_faq(fid)
        if not faq or not faq["active"]:
            await _um_show(query, context, box_message("SSS", "Bu soru kaldırıldı.", "⌛"),
                InlineKeyboardMarkup([[InlineKeyboardButton("◀️ SSS", callback_data="um_faq"),
                                       InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]]))
            return
        text = (f"❓ <b>{faq['question']}</b>\n\n"
                f"{render_rich_tokens(render_clickable_tokens(faq['answer']))}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("◀️ SSS", callback_data="um_faq"),
                                    InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")]])
        await _um_show(query, context, text, kb)
        return

async def _user_cmd_prelude(update, context, cmd):
    """Kullanici komutlari icin ortak kapi: flood korumasi + kayit."""
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd=cmd):
        return None
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    return user

def _make_category_cmd(key, cmd_name):
    async def _cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = await _user_cmd_prelude(update, context, cmd_name)
        if not user:
            return
        text, kb = _category_screen(user.id, key)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    return _cmd

bonuslar_cmd   = _make_category_cmd("bonus", "/bonuslar")
yeniuye_cmd    = _make_category_cmd("yeni_uye", "/yeniuye")
slot_cmd       = _make_category_cmd("slot", "/slot")
spor_cmd       = _make_category_cmd("spor", "/spor")
banaozel_cmd   = _make_category_cmd("ozel", "/banaozel")
turnuvalar_cmd = _make_category_cmd("turnuva", "/turnuvalar")

async def duyurular_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _user_cmd_prelude(update, context, "/duyurular"):
        return
    text, kb = _ann_screen()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def sss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _user_cmd_prelude(update, context, "/sss"):
        return
    text, kb = _faq_screen()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def _send_link_screen(update, title, aciklama, link, btn_label, emoji):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(btn_label, url=link)]]) if is_valid_url(link) else None
    await update.message.reply_text(box_message(title, aciklama, emoji),
        parse_mode=ParseMode.HTML, reply_markup=kb)

async def parayatir_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _user_cmd_prelude(update, context, "/parayatir"):
        return
    link = _menu_link("deposit_link", DEFAULT_DEPOSIT_LINK) or _menu_link("giris_link", DEFAULT_GIRIS_LINK)
    await _send_link_screen(update, "PARA YATIR", "Para yatırma sayfasına aşağıdaki butondan ulaşabilirsin \U0001f447",
        link, "\U0001f4b0 Para Yatır", "\U0001f4b0")

async def paracek_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _user_cmd_prelude(update, context, "/paracek"):
        return
    link = _menu_link("withdraw_link", DEFAULT_WITHDRAW_LINK) or _menu_link("giris_link", DEFAULT_GIRIS_LINK)
    await _send_link_screen(update, "PARA ÇEK", "Para çekme sayfasına aşağıdaki butondan ulaşabilirsin \U0001f447",
        link, "\U0001f4b8 Para Çek", "\U0001f4b8")

async def miniapp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _user_cmd_prelude(update, context, "/miniapp"):
        return
    miniapp = (_menu_link("miniapp_link", DEFAULT_MINIAPP_LINK)
               or _menu_link("play_link", DEFAULT_PLAY_LINK)
               or _menu_link("giris_link", DEFAULT_GIRIS_LINK))
    if miniapp.lower().startswith("https://"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f4f1 Mini App'i Aç",
            web_app=WebAppInfo(url=miniapp))]])
    elif is_valid_url(miniapp):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f4f1 Mini App'i Aç", url=miniapp)]])
    else:
        kb = None
    await update.message.reply_text(box_message("MİNİ APP", "Tek dokunuşla aç \U0001f447", "\U0001f4f1"),
        parse_mode=ParseMode.HTML, reply_markup=kb)

# Alt klavye / serbest metin -> komut eslemesi (temizlenmis TAM eslesme;
# "bonus alamadim" gibi sikayet cumleleri akilli yonlendirmeye duser)
_MENU_LABEL_ACTIONS = {
    "ana menu": "menu", "ana menü": "menu", "menu": "menu", "menü": "menu",
    "siteye giris": "giris", "siteye giriş": "giris", "guncel giris": "giris",
    "güncel giriş": "giris", "giris": "giris", "giriş": "giris",
    "mini app": "miniapp", "miniapp": "miniapp",
    "guncel bonuslar": "bonuslar", "güncel bonuslar": "bonuslar", "bonuslar": "bonuslar",
    "bonus": "bonuslar",
    "yeni uye bonuslari": "yeniuye", "yeni üye bonusları": "yeniuye",
    "yeni uye": "yeniuye", "yeni üye": "yeniuye",
    "slot kampanyalari": "slot", "slot kampanyaları": "slot", "slot": "slot",
    "spor bonuslari": "spor", "spor bonusları": "spor", "spor": "spor",
    "bana ozel kampanyalar": "banaozel", "bana özel kampanyalar": "banaozel",
    "bana ozel": "banaozel", "bana özel": "banaozel",
    "turnuvalar": "turnuvalar",
    "para yatir": "parayatir", "para yatır": "parayatir",
    "para cek": "paracek", "para çek": "paracek",
    "duyurular": "duyurular",
    "sss": "sss", "sik sorulan sorular": "sss", "sık sorulan sorular": "sss",
    "canli destek": "destek", "canlı destek": "destek", "destek": "destek",
    "profil": "profil", "kampanya": "kampanya",
    "ekran goruntusu": "ekran", "ekran görüntüsü": "ekran",
    "ekran goruntusu gonder": "ekran", "ekran görüntüsü gönder": "ekran",
    "ekran resmi": "ekran", "ekran resmi gonder": "ekran", "ekran resmi gönder": "ekran",
}
_LABEL_CLEAN = re.compile(r"[^0-9a-zçğıöşü ]+")

def _match_menu_label(low):
    clean = _LABEL_CLEAN.sub("", low).strip()
    clean = re.sub(r"\s+", " ", clean)
    hit = _MENU_LABEL_ACTIONS.get(clean)
    if hit:
        return hit
    # Ozellestirilmis buton yazilari icin: anahtar kelime metnin COGUNU
    # kapliyorsa buton sayilir ("Bonuslarim" -> bonuslar). Serbest cumleler
    # ("bonus alamadim hala") kaplamaz ve yerlesik asistana kalir.
    for key in sorted(_MENU_LABEL_ACTIONS, key=len, reverse=True):
        if key in clean and len(key) / max(1, len(clean)) >= 0.5:
            return _MENU_LABEL_ACTIONS[key]
    return None

def _destek_screen():
    """Destek merkezi ekrani: (metin, klavye). Komut ve um_destek callback'i paylasir."""
    link = (db.get_setting("support_link") or DEFAULT_SUPPORT_LINK).strip()
    btn = _plain_label(db.get_setting("support_btn_text") or DEFAULT_SUPPORT_BTN, 40)
    text = _safe_setting_text("destek_text",
        "Sana en hızlı hangi ekip yardımcı olsun? \U0001f447\n\n"
        "İstersen derdini buraya yazman da yeterli — mesajını analiz edip "
        "doğru ekibe yönlendiririm.", 400)
    rows = []
    if is_valid_url(link):
        rows.append([InlineKeyboardButton(btn, url=link)])
    cekim = (db.get_setting("withdraw_support_link") or DEFAULT_WITHDRAW_SUPPORT_LINK).strip()
    odeme = (db.get_setting("deposit_support_link") or DEFAULT_DEPOSIT_SUPPORT_LINK).strip()
    bonus = (db.get_setting("bonus_support_link") or DEFAULT_BONUS_SUPPORT_LINK).strip()
    ozel_satir = []
    if is_valid_url(cekim):
        ozel_satir.append(InlineKeyboardButton("\U0001f4b8 Çekim Destek", url=cekim))
    if is_valid_url(odeme):
        ozel_satir.append(InlineKeyboardButton("\U0001f4b3 Ödeme Destek", url=odeme))
    if ozel_satir:
        rows.append(ozel_satir)
    if is_valid_url(bonus):
        rows.append([InlineKeyboardButton("\U0001f381 Bonus Destek", url=bonus)])
    rows.append([InlineKeyboardButton("\U0001f3e0 Ana Menü", callback_data="um_main")])
    return box_message("CANLI DESTEK", text, "\U0001f4ac"), InlineKeyboardMarkup(rows)

async def destek_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Canli Destek: destek merkezi ekranini gonderir."""
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/destek"):
        return
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    text, kb = _destek_screen()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def iptal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Aktif bir akis yokken /iptal: kullaniciya kisa onay verir."""
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/iptal"):
        return
    context.user_data.pop("pending_site_id", None)
    context.user_data.pop("cmp", None)
    context.user_data.pop("ss", None)
    # Sizmis sihirbaz kilidi kalmis olabilir; /iptal her zaman temizlesin.
    context.user_data.pop("wizard_lock", None)
    await update.message.reply_text("İşlem iptal edildi")

# /whoami -> GIZLI komut (menude yok), manuel yazilinca calisir
async def whoami_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if await guard_flood(update, context, is_command=True, cmd="/whoami"):
        return
    uname = f"@{user.username}" if user.username else "Yok"
    full_name = " ".join(p for p in (user.first_name, user.last_name) if p) or "Yok"
    txt = box_message("KIMLIK BILGILERI", (
        f"\U0001f464 <b>Ad:</b> {sanitize_input(full_name, 120)}\n"
        f"\U0001f4ac <b>Username:</b> {sanitize_input(uname, 80)}\n"
        f"\U0001f194 <b>Telegram ID:</b> <code>{user.id}</code>\n"
        f"\U0001f310 <b>Dil:</b> {sanitize_input(getattr(user, 'language_code', '') or '?', 12)}"), "\U0001f464")
    await update.message.reply_text(txt, parse_mode=ParseMode.HTML)
# =====================================================================
# ADMIN DEKORATOR
# =====================================================================
def admin_only(func):
    @wraps(func)
    async def w(update, context, *args, **kwargs):
        uid = update.effective_user.id
        if not is_authenticated(uid):
            # admins.txt'de olmayan veya giris yapmayan -> sessiz/uyari
            if uid in ADMIN_IDS:
                await update.message.reply_text(box_message("ERISIM", "Once <code>/admin</code> ile giris yapin.", "\u26d4"), parse_mode=ParseMode.HTML)
            return
        if ADMIN_SESSION_TIMEOUT > 0:
            authenticated_admins[uid] = time.time()
        return await func(update, context, *args, **kwargs)
    return w

# =====================================================================
# /ADMIN - SIFRE ILE GIRIS
# =====================================================================
WAITING_PASSWORD = 1

async def admin_login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin de bir kullanicidir: users tablosunda olsun ki toplu gonderimler
    # kendisine de ulassin (gonderimi kendi gozuyle dogrulayabilsin).
    try:
        _u = update.effective_user
        db.add_user(_u.id, _u.username, _u.first_name, _u.last_name, getattr(_u, "language_code", ""))
    except Exception:
        pass
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        # Yetkisiz: TAMAMEN sessiz
        db.security_event("unauthorized_admin", uid, f"@{update.effective_user.username}")
        return ConversationHandler.END

    if ADMIN_REQUIRE_PASSWORD:
        # Ikinci dogrulama acik: parola istenir (config: ADMIN_REQUIRE_PASSWORD=1)
        now = time.time()
        if uid in login_blocked and now < login_blocked[uid]:
            kalan = int((login_blocked[uid] - now) // 60) + 1
            await update.message.reply_text(box_message("ENGELLENDI", f"Cok fazla yanlis deneme. {kalan} dk sonra tekrar deneyin.", "\u26d4"), parse_mode=ParseMode.HTML)
            return ConversationHandler.END
        await update.message.reply_text(box_message("YONETICI GIRISI", "Yonetici parolasini yazin.\n\nIptal: /iptal", "\U0001f510"), parse_mode=ParseMode.HTML)
        return WAITING_PASSWORD

    # Parola kapali (varsayilan): beyaz liste dogrulamasi ile dogrudan oturum ac
    authenticated_admins[uid] = time.time()
    db.admin_log(uid, "login_direct_success")
    # Yeni botta admin sohbeti ilk temas oncesi bilinmedigi icin acilistaki
    # kayit basarisiz olabilir; giriste admin komut menusunu tazele.
    try:
        await _apply_commands(context.bot)
    except Exception as exc:
        logger.warning(f"[CMD] giriste menu tazeleme: {exc}")
    await update.message.reply_text(box_message("GIRIS BASARILI", "\u2705 Hosgeldiniz!\n\nCikis: /logout", "\u2705"), parse_mode=ParseMode.HTML)
    await show_admin_panel(update, context)
    return ConversationHandler.END

async def admin_password_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return ConversationHandler.END
    entered = update.message.text.strip()
    try: await update.message.delete()
    except: pass
    now = time.time()
    if uid in login_blocked and now < login_blocked[uid]:
        return ConversationHandler.END
    if verify_admin_password(entered):
        authenticated_admins[uid] = time.time()
        login_attempts[uid] = 0
        db.admin_log(uid, "login_success")
        await context.bot.send_message(chat_id=uid, text=box_message("GIRIS BASARILI", "\u2705 Hosgeldiniz!\n\nCikis: /logout", "\u2705"), parse_mode=ParseMode.HTML)
        await show_admin_panel_chat(uid, context)
        return ConversationHandler.END
    login_attempts[uid] += 1
    remaining = MAX_LOGIN_ATTEMPTS - login_attempts[uid]
    db.security_event("failed_login", uid, f"deneme {login_attempts[uid]}")
    if login_attempts[uid] >= MAX_LOGIN_ATTEMPTS:
        login_blocked[uid] = now + LOGIN_BLOCK_DURATION
        login_attempts[uid] = 0
        await context.bot.send_message(chat_id=uid, text=box_message("ENGELLENDI", f"{MAX_LOGIN_ATTEMPTS} yanlis deneme!\n{LOGIN_BLOCK_DURATION//60} dk engel.", "\u26d4"), parse_mode=ParseMode.HTML)
        for aid in ADMIN_IDS:
            if aid != uid:
                try: await context.bot.send_message(chat_id=aid, text=box_message("GUVENLIK ALARMI", f"Basarisiz admin giris denemesi!\nID: <code>{uid}</code>", "\U0001f6a8"), parse_mode=ParseMode.HTML)
                except: pass
        return ConversationHandler.END
    await context.bot.send_message(chat_id=uid, text=box_message("YANLIS SIFRE", f"\u274c {remaining} hak kaldi.\nTekrar deneyin veya /iptal", "\u274c"), parse_mode=ParseMode.HTML)
    return WAITING_PASSWORD

async def admin_login_cancel(update, context):
    await update.message.reply_text(box_message("IPTAL", "Giris iptal edildi.", "\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def admin_login_timeout(update, context):
    """Parola beklerken sure dolarsa admini sessizce birakmadan bilgilendir."""
    try:
        chat = update.effective_chat
        if chat and update.effective_user and update.effective_user.id in ADMIN_IDS:
            await context.bot.send_message(chat_id=chat.id,
                text=box_message("SURE DOLDU", "Giris suresi doldu. /admin ile yeniden deneyin.", "\u23f3"),
                parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return ConversationHandler.END

# =====================================================================
# ADMIN PANEL
# =====================================================================
def _panel_keyboard():
    return [
        [InlineKeyboardButton("\U0001f4ca Istatistik", callback_data="ap_stats"),
         InlineKeyboardButton("\U0001f517 Linkler", callback_data="ap_links")],
         [InlineKeyboardButton("\U0001f3ac Banner & Medya", callback_data="ap_image"),
         InlineKeyboardButton("\u270f\ufe0f Buton & Yazi", callback_data="ap_buttons")],
        [InlineKeyboardButton("\U0001f465 Kullanicilar", callback_data="ap_users"),
         InlineKeyboardButton("\U0001f3f7 Kategoriler", callback_data="ap_segments")],
        [InlineKeyboardButton("\U0001f6ab Ban", callback_data="ap_bans"),
         InlineKeyboardButton("\U0001f4e3 Toplu Mesaj", callback_data="ap_broadcast")],
        [InlineKeyboardButton("\U0001f4c5 Zamanli Mesaj", callback_data="ap_sched"),
         InlineKeyboardButton("\U0001f4cb Sablonlar", callback_data="ap_templates")],
        [InlineKeyboardButton("\U0001f4e9 Tekil Mesaj", callback_data="ap_dm"),
         InlineKeyboardButton("\U0001f4ac Canli Destek", callback_data="ap_support")],
        [InlineKeyboardButton("\U0001f4e8 Sikayetler", callback_data="ap_complaints"),
         InlineKeyboardButton("\U0001f6e1 Guvenlik", callback_data="ap_security")],
        [InlineKeyboardButton("\U0001f3af Kampanyalar", callback_data="ap_camps"),
         InlineKeyboardButton("\U0001f4e2 Duyurular", callback_data="ap_ann")],
        [InlineKeyboardButton("\u2753 SSS Yonetimi", callback_data="ap_faq"),
         InlineKeyboardButton("\U0001f4f8 Ekran Goruntuleri", callback_data="ap_ekran")],
        [InlineKeyboardButton("\U0001f4dc Gonderim Gecmisi", callback_data="ap_history"),
         InlineKeyboardButton("\U0001f4d6 YARDIM", callback_data="ap_help")],
        [InlineKeyboardButton("\u2699\ufe0f Ayarlar", callback_data="ap_settings"),
         InlineKeyboardButton("\U0001f6aa Cikis Yap", callback_data="ap_logout")],
    ]


# =====================================================================
# PANEL ICI YARDIM — her bolum icin "bu buton ne yapar, basinca ne olur"
# =====================================================================
_YARDIM_KONULARI = [
    ("baslangic", "\U0001f680 Nereden Baslarim?"),
    ("kampanya", "\U0001f3af Kampanya / Turnuva"),
    ("duyuru", "\U0001f4e2 Duyuru"),
    ("bildirim", "\U0001f4e3 Bildirim Gonderme"),
    ("zamanli", "\U0001f4c5 Zamanli Mesaj"),
    ("banner", "\U0001f3ac Gorsel / Banner"),
    ("linkler", "\U0001f517 Linkler"),
    ("segment", "\U0001f3f7 Segment / VIP"),
    ("sss", "\u2753 SSS / Bilgi Bankasi"),
    ("asistan", "\U0001f916 Yerlesik Asistan"),
    ("rapor", "\U0001f4ca Rapor Okuma"),
    ("ekran", "\U0001f4f8 Ekran Goruntusu"),
]
_YARDIM_METINLERI = {
    "baslangic": (
        "1) <b>Linkler</b> bolumune gir, giris/kayit/destek adreslerini kaydet.\n"
        "2) Bota bir <b>foto gonder</b> — acilis gorselin hazir.\n"
        "3) <b>Kampanyalar → ➕ Yeni Kampanya</b> ile ilk kampanyani ac.\n"
        "4) <b>Duyurular → ➕ Yeni Duyuru</b> ile ilk duyurunu yayinla.\n"
        "5) Kendi hesabinla bota /start yazip kullanicinin gordugunu gor.\n\n"
        "Her ekranda ◀️ Geri vardir; yanlis bir sey silmedikce geri alinamayan islem yoktur. "
        "Sihirbazlarda her an /iptal yazarak cikabilirsin."),
    "kampanya": (
        "<b>Kampanyalar</b> butonu: kullanicinin Ana Menu'sundeki 6 kategoriyi doldurur.\n\n"
        "➕ Yeni Kampanya'ya basinca sirayla sorulur: kategori → baslik → aciklama → "
        "foto/video → buton (Yazi|https://link) → odul havuzu → sartlar → bitis tarihi. "
        "Istemedigin adimda /atla yaz.\n\n"
        "Kaydedince kullanici menusunde ANINDA gorunur; ayrica tek tikla "
        "'Yeni Kampanya Basladi' bildirimi gonderebilirsin.\n"
        "Bitis tarihi verirsen: son gun ve son 2 saat kala OTOMATIK hatirlatma gider, "
        "suresi dolunca kampanya kendiliginden yayindan kalkar.\n\n"
        "\U0001f3c6 TURNUVA = kategori olarak Turnuvalar secilen kampanyadir."),
    "duyuru": (
        "<b>Duyurular</b> iki iste birden yarar:\n"
        "1) Kalici liste: kullanici Ana Menu → 📢 Duyurular'da gecmis duyurulari okur.\n"
        "2) Anlik gonderim: kaydettikten sonra '📣 Tum Kullanicilara Gonder' ile "
        "herkese mesaj olarak da iletebilirsin.\n\n"
        "➕ Yeni Duyuru → baslik yaz → metin yaz → foto ekle (veya /atla). Bu kadar.\n"
        "Gonderim sonunda rapor gelir (✅ ulasan | ❌ ulasamayan | 👥 toplam) ve "
        "ulasamayanlarin NEDENI raporda yazar."),
    "bildirim": (
        "Bildirim gondermenin 4 yolu var:\n\n"
        "<b>A) Toplu Mesaj</b> (en esnek): /bildirim yaz veya paneldeki butona bas. "
        "Tip sec (metin / foto / kod / buton / tam paket), adimlari doldur, hedef sec "
        "(herkes, son 24s aktif veya VIP segmenti), onizlemeyi ONAYLA. "
        "Sablon olarak kaydedersen sonraki sefer tek tik.\n\n"
        "<b>B) Kampanya bildirimi:</b> kampanya olusturunca cikan tek-tik buton "
        "(FreeSpin tanimlandi duyurusu icin de bunu kullan: bonus kampanyasi ac, bildir).\n\n"
        "<b>C) Link degisti:</b> Linkler'de giris/miniapp degistirince cikan tek-tik buton.\n\n"
        "<b>D) Otomatik:</b> sureli kampanyada son gun + son 2 saat hatirlatmasi kendiliginden gider."),
    "zamanli": (
        "<b>Zamanli Mesaj:</b> mesaji simdi hazirla, ileride otomatik gonderilsin.\n\n"
        "Panel → Zamanli Mesaj → Olustur: toplu mesaj sihirbazinin aynisi, sonda "
        "tarih-saat sorar (ornek: 15.08.2026 20:30).\n\n"
        "Gonderimden 5 dk once sana onizlemeli hatirlatma gelir; altindaki butonlarla "
        "▶️ hemen gonderebilir, 🕐 saatini degistirebilir veya 🗑 iptal edebilirsin. "
        "Ayni mesajin yanlislikla iki kez gitmesi imkansizdir (kilitli)."),
    "banner": (
        "<b>Acilis gorseli degistirmenin en kolay yolu:</b> bota foto/video GONDER. "
        "Otomatik kutuphaneye eklenir ve aktif gorsel olur.\n\n"
        "Panel → Banner & Medya: kutuphanede gez (sayfada 5 kayit), istedigine dokun → "
        "aktif yap veya sil. Karsilama gorseli ile kampanya gorselini ayri da secebilirsin.\n\n"
        "NOT: Botun PROFIL fotografi Telegram kurali geregi yalnizca BotFather'dan "
        "degisir (/setuserpic)."),
    "linkler": (
        "<b>Linkler</b> botun tum yonlendirmelerinin merkezi:\n"
        "Giris, Kayit, Aktif Et, Destek, Kanal, Play, Mini App, Para Yatir, Para Cek "
        "+ 3 ozel destek kanali (Odeme/Cekim/Bonus — asistan bunlara yonlendirir).\n\n"
        "Birine dokun → yeni adresi yaz → kaydedilir ve KULLANICIDA ANINDA gecerli olur "
        "(eski mesajlardaki butonlar bile yeni adrese gider).\n"
        "Giris veya Mini App degistirdiginde tek-tik 'herkese duyur' butonu cikar."),
    "segment": (
        "<b>Segment = kullanici gruplari.</b> Kampanya ve bildirimleri gruba ozel atarsin.\n\n"
        "Manuel kademeler: 🏆 Platin, 🥇 Altin, 🥈 Gumus, 🥉 Bronz — "
        "Panel → Kategoriler'den veya /setseg ID platin ile atanir.\n"
        "Otomatik gruplar: 🆕 Yeni Uyeler (ilk 7 gun) ve 🕓 Aktif (son 48 saat) — "
        "kendiliginden hesaplanir, atama gerekmez.\n\n"
        "Kampanyada segment secersen yalnizca o grup gorur → kullanicinin "
        "'⭐ Bana Ozel Kampanyalar' bolumu boyle kisisellesir."),
    "sss": (
        "<b>SSS = ayni zamanda asistanin bilgi bankasi.</b>\n\n"
        "Ilk kurulumda 15 hazir soru-cevap yuklenir; hepsini panelden "
        "duzenleyebilir/silebilir, yenilerini ekleyebilirsin.\n"
        "Kullanici SSS menusunden okuyabilir; ayrica bota serbest soru yazdiginda "
        "asistan BURADAKI sorularla eslestirip cevabi otomatik gonderir.\n\n"
        "Yani: SSS'e ne kadar cok soru-cevap girersen, asistan o kadar cok soruyu "
        "kendi basina cevaplar."),
    "asistan": (
        "<b>Yerlesik Asistan</b> kullanicinin elle yazdigi HER mesaji analiz eder "
        "(dis yapay zeka servisi yoktur, tamamen bot icinde calisir):\n\n"
        "1) Once niyeti anlar — yazim hatasina dayaniklidir: 'param gelmedii' → "
        "Cekim Destek, 'yatiramiyorum' → Odeme Destek, 'bonus alamadim' → Bonus Destek, "
        "'giremiyorum' → guncel giris butonu, 'uye olmak istiyorum' → kayit linki...\n"
        "2) Niyet bulamazsa SSS bilgi bankasinda arar, eslesen cevabi gonderir.\n"
        "3) O da olmazsa ornek kaliplarla Destek Merkezi'ne yonlendirir.\n\n"
        "Tum yonlendirmeler /dailylog kayitlarina islenir."),
    "rapor": (
        "Her toplu gonderim sonunda rapor gelir:\n"
        "✅ = ulasan kisi | ❌ = ulasamayan | 👥 = toplam hedef\n\n"
        "❌ varsa ALTINDA nedeni yazar:\n"
        "🚫 'botu engellemis ya da hic baslatmamis' → o kisiler botu engellemis "
        "veya bota hic /start yazmamis; senlik bir durum degil, normaldir.\n"
        "⚠️ 'icerik hatasi' → mesajin kendisi Telegram'a takildi; bot.log dosyasinin "
        "son satirlari tam nedeni soyler.\n\n"
        "Istatistikler: Panel → 📊 Istatistik | Gunluk islem dokumu: /dailylog"),
    "ekran": (
        "<b>Ekran Goruntusu Kaydi:</b> kullanici (veya sen) bota bir foto gonderince bot "
        "SECENEK sunar: kategori (Arkadasini Getir, Para Yatirma, Para Cekme, Bonus, Diger...). "
        "Kategori secilince o kategori icin tanimli bilgiler sirayla sorulur (or. Site ID, "
        "Arkadas ID) ve foto <b>bu bilgilerle ADLANDIRILARAK</b> <code>screenshots/</code> "
        "klasorune kaydedilir:\n<code>Arkadasini-Getir_2026-09-22_14-30-05_ABC123_XYZ789_123456.jpg</code>\n\n"
        "Diger yol: kullanici once /ekran (veya 📸 tusu) ile kategori ve bilgileri girer, "
        "en son fotoyu gonderir; foto gelir gelmez dogrudan kaydedilir.\n\n"
        "Sen admin olarak foto gonderdiginde ek secenek cikar: 🗂 Kampanya Medyasi Yap "
        "(eski davranis, kutuphaneye ekler) ya da 📸 Ekran Goruntusu Kaydet.\n\n"
        "Kayitlari gor: /ekranlar (detay: /ekranlar ID, kapat: /ekrankapat ID); "
        "Excel dosyasi: /ekrandosya. Kategorileri, sorulan bilgileri ve dosya adi sablonunu "
        "Panel → 📸 Ekran Goruntuleri bolumunden degistirirsin; her kayitta sana bildirim gelir."),
}

def _yardim_liste_kb():
    rows, satir = [], []
    for key, ad in _YARDIM_KONULARI:
        satir.append(InlineKeyboardButton(ad, callback_data=f"aphelp_{key}"))
        if len(satir) == 2:
            rows.append(satir); satir = []
    if satir:
        rows.append(satir)
    rows.append([InlineKeyboardButton("\u25c0\ufe0f Panele Don", callback_data="ap_main")])
    return InlineKeyboardMarkup(rows)


def _camps_admin_screen():
    allc = db.list_campaigns_admin()
    counts = {}
    for c in allc:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    rows = [[InlineKeyboardButton(f"{CAMPAIGN_CATEGORIES[k]} ({counts.get(k, 0)})",
                                  callback_data=f"apc_list_{k}")] for k in CAMPAIGN_CATEGORIES]
    rows.append([InlineKeyboardButton("➕ Yeni Kampanya", callback_data="apc_new")])
    rows.append([InlineKeyboardButton("◀️ Geri", callback_data="ap_main")])
    return box_message("KAMPANYA YONETIMI",
        "Kategori secin veya yeni kampanya olusturun.\n"
        "✅ aktif | ⏸ pasif | ⌛ suresi dolmus\n"
        "Suresi dolan kampanyalar kullanicidan OTOMATIK kaldirilir;\n"
        "son gun ve son 2 saat kala hedef kitleye bildirim gider.", "\U0001f3af"), InlineKeyboardMarkup(rows)

def _ann_admin_screen():
    anns = db.list_announcements(only_active=False, limit=10)
    rows = [[InlineKeyboardButton(f"#{a['id']} {_plain_label(a['title'], 30)}",
                                  callback_data=f"apann_view_{a['id']}")] for a in anns]
    rows.append([InlineKeyboardButton("➕ Yeni Duyuru", callback_data="apann_new")])
    rows.append([InlineKeyboardButton("◀️ Geri", callback_data="ap_main")])
    return box_message("DUYURU YONETIMI",
        "Duyurular kullanicinin Ana Menu → \U0001f4e2 Duyurular bolumunde listelenir.\n"
        "Istersen olusturduktan sonra tum kullanicilara da gonderebilirsin.", "\U0001f4e2"), InlineKeyboardMarkup(rows)

def _faq_admin_screen():
    faqs = db.list_faqs(only_active=False)
    rows = [[InlineKeyboardButton(f"#{f['id']} {_plain_label(f['question'], 32)}",
                                  callback_data=f"apfaq_view_{f['id']}")] for f in faqs[:15]]
    rows.append([InlineKeyboardButton("➕ Yeni Soru", callback_data="apfaq_new")])
    rows.append([InlineKeyboardButton("◀️ Geri", callback_data="ap_main")])
    return box_message("SSS YONETIMI",
        "Sorular kullanicinin Ana Menu → ❓ SSS bolumunde gorunur.", "❓"), InlineKeyboardMarkup(rows)

def _panel_text():
    s = db.get_stats()
    return box_message("ADMIN PANELI", (
        f"\U0001f465 Toplam: {s['total']} | Aktif: {s['active']} | Banli: {s['banned']}\n"
        f"\U0001f195 Bugun: +{s['today']} | Hafta: +{s['week']}\n"
        f"\U0001f553 24s Aktif: {s['active24']} | \U0001f517 Giris gosterim: {s['giris_views']}\n\n"
        f"\U0001f447 Islem secin:"), "\U0001f6e0")


# =====================================================================
# ADMIN ALT KLAVYESI — /admin girisinde ikondaki menu admin seceneklerine
# doner; cikista/istekle kullanici menusune geri gecer.
# =====================================================================
def _build_admin_reply_menu():
    rows = [
        [KeyboardButton("\U0001f6e0 Panel"), KeyboardButton("\U0001f4ca İstatistik")],
        [KeyboardButton("\U0001f3af Kampanyalar"), KeyboardButton("\U0001f4e2 Duyurular")],
        [KeyboardButton("\U0001f4e3 Bildirim Gönder"), KeyboardButton("\U0001f4c5 Zamanlı Mesaj")],
        [KeyboardButton("\u2753 SSS Yönetimi"), KeyboardButton("\U0001f4d6 Yardım")],
        [KeyboardButton("\U0001f464 Kullanıcı Menüsü"), KeyboardButton("\U0001f6aa Çıkış")],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)

_ADMIN_MENU_LABELS = {
    "panel": "panel", "istatistik": "istatistik",
    "kampanyalar": "kampanyalar", "duyurular": "duyurular",
    "bildirim gonder": "bildirim", "bildirim gönder": "bildirim", "bildirim": "bildirim",
    "zamanli mesaj": "zamanli", "zamanlı mesaj": "zamanli", "zamanli": "zamanli",
    "sss yonetimi": "sssyonetim", "sss yönetimi": "sssyonetim",
    "yardim": "yardim", "yardım": "yardim",
    "kullanici menusu": "kullanici", "kullanıcı menüsü": "kullanici",
    "cikis": "cikis", "çıkış": "cikis",
}

def _match_admin_label(low):
    clean = _LABEL_CLEAN.sub("", low).strip()
    clean = re.sub(r"\s+", " ", clean)
    return _ADMIN_MENU_LABELS.get(clean)

async def _admin_menu_action(action, update, context):
    """Admin alt klavyesindeki butonlarin islevleri (yeni mesaj olarak)."""
    if action == "panel":
        return await show_admin_panel(update, context)
    if action == "istatistik":
        return await botstatus_cmd(update, context)
    if action == "kampanyalar":
        txt, kb = _camps_admin_screen()
        return await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    if action == "duyurular":
        txt, kb = _ann_admin_screen()
        return await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    if action == "sssyonetim":
        txt, kb = _faq_admin_screen()
        return await update.message.reply_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
    if action == "bildirim":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4e3 Toplu Mesaj Olustur", callback_data="bcgo")],
            [InlineKeyboardButton("\U0001f4cb Sablonlar", callback_data="ap_templates")]])
        return await update.message.reply_text(box_message("BILDIRIM GONDER",
            "Tip sec, adimlari doldur, hedef kitleyi sec — onizlemeden sonra gonderilir.", "\U0001f4e3"),
            parse_mode=ParseMode.HTML, reply_markup=kb)
    if action == "zamanli":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4c5 Zamanli Mesaj Olustur", callback_data="schedgo")],
            [InlineKeyboardButton("\U0001f4c5 Bekleyenler", callback_data="ap_sched")]])
        return await update.message.reply_text(box_message("ZAMANLI MESAJ",
            "Mesaji simdi hazirla; verdigin tarih-saatte otomatik gonderilir.\n"
            f"Gonderimden {SCHED_NOTIFY_MINUTES} dk once onizlemeli hatirlatma alirsin.", "\U0001f4c5"),
            parse_mode=ParseMode.HTML, reply_markup=kb)
    if action == "yardim":
        return await update.message.reply_text(box_message("YARDIM MERKEZI",
            "Konu sec 👇 Her konuda 'bu buton ne yapar, basinca ne olur' adim adim anlatilir.", "\U0001f4d6"),
            parse_mode=ParseMode.HTML, reply_markup=_yardim_liste_kb())
    if action == "kullanici":
        context.user_data["admin_kb"] = False
        return await update.message.reply_text(
            "\U0001f464 Kullanici menusune gecildi. Admin menusu icin: /admin",
            reply_markup=_build_reply_menu())
    if action == "cikis":
        uid = update.effective_user.id
        if uid in authenticated_admins:
            del authenticated_admins[uid]
        db.admin_log(uid, "logout")
        context.user_data["admin_kb"] = False
        return await update.message.reply_text(box_message("CIKIS",
            "Admin oturumu kapatildi. Giris: /admin", "\U0001f6aa"),
            parse_mode=ParseMode.HTML, reply_markup=_build_reply_menu())

async def show_admin_panel(update, context):
    # Ikondaki menu admin girisiyle ADMIN seceneklerine doner (bir kez yuklenir).
    if context is not None and not context.user_data.get("admin_kb"):
        context.user_data["admin_kb"] = True
        try:
            await update.message.reply_text("\U0001f6e0 Admin menusu klavyeye yuklendi \U0001f447",
                reply_markup=_build_admin_reply_menu())
        except Exception:
            pass
    await update.message.reply_text(_panel_text(), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(_panel_keyboard()))

async def show_admin_panel_chat(chat_id, context):
    await context.bot.send_message(chat_id=chat_id, text=_panel_text(), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(_panel_keyboard()))

# =====================================================================
# GENEL AYAR DUZENLEME SIHIRBAZI (butonla, komutlar da yedek)
# =====================================================================
SETTING_DEFS = {
    "giris_link":       ("Guncel Giris Linki", "https:// ile link", "url"),
    "giris_title":      ("Giris Basligi", "Giris mesaji basligi", "text"),
    "giris_text":       ("Giris Mesaji", "Giris aciklama metni", "text"),
    "giris_btn_text":   ("Giris Butonu Yazisi", "Buton uzerindeki yazi", "text"),
    "register_link":    ("Kayit Linki", "https:// ile link", "url"),
    "register_btn_text":("Uye Ol Butonu Yazisi", "Buton yazisi", "text"),
    "bonus_link":       ("Aktif Et Linki", "https:// ile kampanya/bonus linki", "url"),
    "bonus_btn_text":   ("Aktif Et Butonu Yazisi", "Kampanya butonu yazisi", "text"),
    "welcome_text":     ("Karsilama Mesaji", "{name}=Telegram kullanici adi", "text"),
    "campaign_title":   ("Kampanya Basligi", "Medya altindaki kalin baslik", "text"),
    "promo_caption":    ("Kampanya Aciklamasi", "Foto veya video alti yazi", "text"),
    "caption_link_text":("Tiklanabilir Yazi", "Ornek: Kampanyayi incelemek icin TIKLA", "text"),
    "caption_link_url": ("Yazi Baglantisi", "Tiklanabilir yazinin https:// adresi", "url"),
    "campaign_code":    ("Kampanya Kodu", "Bos birakmak icin /temizle kullanin", "text"),
    "campaign_code_style": ("Kod Gorunumu", "copy veya spoiler yazin", "code_style"),
    "support_link":     ("Destek Linki", "https:// veya t.me/...", "url"),
    "support_btn_text": ("Destek Butonu Yazisi", "Buton yazisi", "text"),
    "campaign_media_url": ("Kampanya Medya URL", "https:// ile foto veya video", "url"),
    "promo_image":      ("Eski Gorsel URL", "Geriye uyumluluk alani", "url"),
    "menu_button_text": ("Play Buton Yazisi", "Sol alttaki butonun adi", "text"),
    "console_link":     ("Konsol Linki", "https:// ile konsol adresi", "url"),
    "console_btn_text": ("Konsol Buton Yazisi", "Konsol butonu uzerindeki yazi", "text"),
    "channel_link":     ("Kanal Linki", "https://t.me/... acilis kanal mesaji linki", "url"),
    "channel_text":     ("Kanal Mesaji Yazisi", "Ornek: 👉 Kanalımıza abone ol", "text"),
    "site_id_prompt":   ("Site ID Istek Mesaji", "Kayitsiz kullaniciya gosterilen istek yazisi", "text"),
    "play_link":        ("Play Buton Linki", "PLAY butonunun acacagi https:// adres. Bosaltmak icin /temizle (giris linkine doner)", "url"),
    "welcome_media_url":("Karsilama Medya URL", "Acilis gorseli/videosu icin https:// adres. /temizle ile kaldirilir", "url"),
    "destek_text":      ("Destek Mesaji", "/destek komutunda gosterilen yazi", "text"),
    "miniapp_link":     ("Mini App Linki", "https:// ile Telegram Mini App adresi", "url"),
    "deposit_link":     ("Para Yatir Linki", "https:// ile para yatirma sayfasi", "url"),
    "withdraw_link":    ("Para Cek Linki", "https:// ile para cekme sayfasi", "url"),
    "deposit_support_link": ("Odeme Destek Kanali", "Yatirim sorunlari icin destek linki", "url"),
    "withdraw_support_link":("Cekim Destek Kanali", "Para cekim sorunlari icin destek linki", "url"),
    "bonus_support_link":   ("Bonus Destek Kanali", "Bonus sorunlari icin destek linki", "url"),
    "screenshot_categories": ("Ekran Goruntusu Kategorileri",
        "Bicim: anahtar:Buton Yazisi:Alan1|Alan2, anahtar2:Buton:Alan (virgulle ayrilir).\n"
        "Ornek: arkadas:👥 Arkadaşını Getir:Site ID|Arkadaş ID, bonus:🎁 Bonus:Site ID\n"
        "Varsayilana donmek icin /temizle", "sscats"),
    "screenshot_name_format": ("Ekran Goruntusu Dosya Adi Sablonu",
        "Yer tutucular: {kategori} {tarih} {saat} {alanlar} {tgid} {kullanici} {alan1} {alan2}...\n"
        "Ornek: {kategori}_{tarih}_{alanlar}   → Varsayilan icin /temizle", "ssfmt"),
    "screenshot_prompt": ("Ekran Goruntusu Secenek Mesaji", "Foto gelince kullaniciya sorulan metin", "text"),
}
ASET_WAIT = 50

async def aset_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "aset"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    key = q.data.replace("apset_", "")
    if key not in SETTING_DEFS:
        return ConversationHandler.END
    _wizard_lock(context, "aset")
    title, desc, typ = SETTING_DEFS[key]
    context.user_data["aset_key"] = key
    cur = db.get_setting(key) or "(varsayilan)"
    await q.edit_message_text(box_message(f"DEGISTIR: {title}", f"{desc}\n\n<b>Su anki:</b> <code>{cur}</code>\n\nYeni degeri yazip gonderin.\n\n<i>Iptal: /iptal</i>", "\u270f\ufe0f"), parse_mode=ParseMode.HTML)
    return ASET_WAIT

async def aset_save(update, context):
    uid = update.effective_user.id
    # Oturum sihirbaz sirasinda dolmus olabilir; suresi dolmus oturumla ayar yazma.
    if not is_authenticated(uid):
        _wizard_unlock(context)
        context.user_data.pop("aset_key", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Deger KAYDEDILMEDI. /admin ile giris yapip yeniden deneyin.", "⏳"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    key = context.user_data.get("aset_key")
    if not key or key not in SETTING_DEFS:
        _wizard_unlock(context)
        return ConversationHandler.END
    title, desc, typ = SETTING_DEFS[key]
    raw = update.message.text or ""
    if raw.strip().lower() == "/temizle" and key in ("caption_link_text", "caption_link_url", "campaign_code", "play_link", "channel_link"):
        val = ""
    elif typ == "url":
        val = raw.strip()
        if not is_valid_url(val) or (key in ("giris_link", "play_link") and not val.lower().startswith("https://")):
            await update.message.reply_text(box_message("HATA", "Gecersiz URL! https:// ile baslamali.", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
    elif typ == "code_style":
        val = raw.strip().lower()
        if val not in ("copy", "spoiler"):
            await update.message.reply_text(box_message("HATA", "Yalnizca copy veya spoiler yazin.", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
    elif typ in ("sscats", "ssfmt"):
        val = re.sub(r"\s+", " ", _CTRL_CHARS.sub("", raw)).strip()[:1500 if typ == "sscats" else 150]
        if any(ch in val for ch in "<>&"):
            await update.message.reply_text(box_message("HATA", "<, > ve &amp; karakterleri kullanilamaz.", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
        if typ == "sscats" and not parse_screenshot_categories(val):
            await update.message.reply_text(box_message("HATA",
                "Gecerli kategori bulunamadi. Bicim: <code>anahtar:Buton Yazisi:Alan1|Alan2, ...</code>", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
        if typ == "ssfmt" and ("{" not in val or not build_screenshot_filename(
                {"key": "ornek", "label": "Ornek", "fields": ["Site ID"]}, ["ABC123"], 1, datetime.now(), fmt=val)):
            await update.message.reply_text(box_message("HATA",
                "Sablonda en az bir yer tutucu olmali, or. <code>{kategori}_{tarih}_{alanlar}</code>", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
    else:
        val = sanitize_input(raw, 700)
        if not val:
            await update.message.reply_text(box_message("HATA", "Bos olamaz.", "\u274c"), parse_mode=ParseMode.HTML)
            return ASET_WAIT
    db.set_setting(key, val)
    if key in ("giris_link", "menu_button_text", "play_link"):
        await _apply_play_menu_buttons(context.bot)
    if key == "welcome_media_url":
        # URL verildiyse kutuphane secimini birak; oncelik verilen URL'de olsun.
        db.set_setting("welcome_media_id", "")
        db.set_setting("welcome_media_type", "")
    if key in ("promo_image", "campaign_media_url"):
        db.set_setting("campaign_media_id", "")
        db.set_setting("campaign_media_file", "")
        db.set_setting("promo_image_file", "")
        db.set_setting("campaign_media_type", _media_kind(val))
        db.set_setting("active_campaign_media_library_id", "")
    db.admin_log(update.effective_user.id, "set_" + key, val[:50])
    context.user_data.pop("aset_key", None)
    _wizard_unlock(context)
    rows = []
    if key == "giris_link":
        rows.append([InlineKeyboardButton("\U0001f4e3 'Giris Adresi Degisti' Bildirimi Gonder",
                                          callback_data="apnotify_giris")])
    if key == "miniapp_link":
        rows.append([InlineKeyboardButton("\U0001f4e3 'Mini App Guncellendi' Bildirimi Gonder",
                                          callback_data="apnotify_miniapp")])
    rows.append([InlineKeyboardButton("\u25c0\ufe0f Panele Don", callback_data="ap_main")])
    await update.message.reply_text(box_message("KAYDEDILDI", f"<b>{title}</b>:\n<code>{val}</code>", "\u2705"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
    return ConversationHandler.END

# /temizle bir komut oldugu icin ayri handler gerekir (TEXT & ~COMMAND filtresine takilir).
ASET_CLEARABLE = ("caption_link_text", "caption_link_url", "campaign_code", "play_link", "channel_link", "welcome_media_url",
                  "screenshot_categories", "screenshot_name_format", "screenshot_prompt")

async def aset_clear(update, context):
    key = context.user_data.get("aset_key")
    if not key or key not in SETTING_DEFS:
        _wizard_unlock(context)
        return ConversationHandler.END
    title, desc, typ = SETTING_DEFS[key]
    if key not in ASET_CLEARABLE:
        await update.message.reply_text(box_message("HATA", "Bu alan bosaltilamaz; yeni bir deger yazin veya /iptal.", "\u274c"), parse_mode=ParseMode.HTML)
        return ASET_WAIT
    db.set_setting(key, "")
    if key == "play_link":
        await _apply_play_menu_buttons(context.bot)
    if key == "welcome_media_url":
        db.set_setting("welcome_media_id", "")
        db.set_setting("welcome_media_type", "")
    db.admin_log(update.effective_user.id, "clear_" + key, "")
    context.user_data.pop("aset_key", None)
    _wizard_unlock(context)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Panele Don", callback_data="ap_main")]])
    await update.message.reply_text(box_message("TEMIZLENDI", f"<b>{title}</b> bosaltildi; varsayilan davranisa donuldu.", "\u2705"), parse_mode=ParseMode.HTML, reply_markup=kb)
    return ConversationHandler.END

async def aset_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("aset_key", None)
    await update.message.reply_text(box_message("IPTAL", "Degisiklik iptal edildi.", "\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

def _edit_btn(label, key):
    return InlineKeyboardButton(label, callback_data=f"apset_{key}")

# =====================================================================
# KAMPANYA MEDYA KUTUPHANESI
# =====================================================================
# Sayfa basina en fazla 5 kayit: liste kompakt kalir, sayfa sayisi otomatik artar.
MEDIA_LIBRARY_PAGE_SIZE = 5

def _media_library_label(row, active_id):
    mark = "✅" if row["id"] == active_id else ("🎬" if row["media_type"] == "video" else "🖼")
    name = (row["name"] or ("Video" if row["media_type"] == "video" else "Foto"))[:22]
    return f"{mark} #{row['id']} {name}"

async def render_media_library(q, page=0):
    rows = db.list_campaign_media()
    total = len(rows)
    if not rows:
        txt = box_message("MEDYA KUTUPHANESI",
            "Henuz kayitli foto veya video yok.\n\nPanelden cikip bota bir foto ya da video gonderin; medya kutuphaneye eklenip aktif edilir.", "🗂")
        kb = [[InlineKeyboardButton("📥 Nasil eklenir?", callback_data="apimg_howto")],
              [InlineKeyboardButton("◀️ Foto / Video", callback_data="ap_image")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    pages = (total + MEDIA_LIBRARY_PAGE_SIZE - 1) // MEDIA_LIBRARY_PAGE_SIZE
    page = max(0, min(page, pages - 1))
    chunk = rows[page * MEDIA_LIBRARY_PAGE_SIZE:(page + 1) * MEDIA_LIBRARY_PAGE_SIZE]
    active_id = active_campaign_media_library_id()
    kb = [[InlineKeyboardButton(_media_library_label(row, active_id), callback_data=f"apmedia_view_{row['id']}")]
          for row in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Onceki", callback_data=f"apmedia_page_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Sonraki ▶️", callback_data=f"apmedia_page_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("📥 Yeni medya ekle", callback_data="apimg_howto")])
    kb.append([InlineKeyboardButton("◀️ Foto / Video", callback_data="ap_image")])
    txt = box_message("MEDYA KUTUPHANESI",
        f"Toplam {total} kayit (Sayfa {page+1}/{pages})\n\n✅ aktif medyayi gosterir. Onizlemek veya secmek icin bir kayda dokunun.", "🗂")
    await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

def _build_media_detail(row):
    active = row["id"] == active_campaign_media_library_id()
    is_welcome = (db.get_setting("welcome_media_id") or "") == row["media_id"]
    label = "Video" if row["media_type"] == "video" else "Foto"
    durum = "✅ AKTIF" if active else "Pasif"
    if is_welcome:
        durum += " | \U0001f64b Karsilamada"
    date_text = (row["created_at"] or "")[:16].replace("T", " ")
    name = harden_text(row["name"] or f"{label} #{row['id']}", 80)
    txt = box_message("MEDYA DETAYI",
        f"<b>Kayit:</b> #{row['id']}\n<b>Ad:</b> {name}\n<b>Tur:</b> {label}\n<b>Durum:</b> {durum}\n<b>Eklenme:</b> {date_text}\n\n"
        "Onizleyebilir, kampanyada aktif edebilir veya /start acilis karsilamasinin gorseli yapabilirsiniz.", "🎞")
    kb = [[InlineKeyboardButton("👁 Onizle", callback_data=f"apmedia_preview_{row['id']}")]]
    if not active:
        kb.append([InlineKeyboardButton("✅ Aktif Et", callback_data=f"apmedia_select_{row['id']}")])
    if is_welcome:
        kb.append([InlineKeyboardButton("\U0001f6ab Karsilamadan Kaldir", callback_data=f"apmedia_unwelcome_{row['id']}")])
    else:
        kb.append([InlineKeyboardButton("\U0001f64b Karsilamada Kullan", callback_data=f"apmedia_welcome_{row['id']}")])
    if not active:
        kb.append([InlineKeyboardButton("🗑 Sil", callback_data=f"apmedia_delask_{row['id']}")])
    kb.append([InlineKeyboardButton("◀️ Kutuphane", callback_data="apmedia_page_0")])
    return txt, InlineKeyboardMarkup(kb)

async def render_media_detail(q, media_pk):
    row = db.get_campaign_media(media_pk)
    if not row:
        await render_media_library(q, 0)
        return
    txt, kb = _build_media_detail(row)
    await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def send_media_detail_chat(context, chat_id, media_pk):
    """Detay menusunu yeni mesaj olarak (sohbetin en altina) gonderir."""
    row = db.get_campaign_media(media_pk)
    if not row:
        return
    txt, kb = _build_media_detail(row)
    await context.bot.send_message(chat_id=chat_id, text=txt, parse_mode=ParseMode.HTML, reply_markup=kb)

async def send_media_library_preview(context, chat_id, row):
    caption = f"Onizleme: #{row['id']} • {'Video' if row['media_type'] == 'video' else 'Foto'}"
    if row["media_type"] == "video":
        await context.bot.send_video(chat_id=chat_id, video=row["media_id"], caption=caption)
    else:
        await context.bot.send_photo(chat_id=chat_id, photo=row["media_id"], caption=caption)
# =====================================================================
# BAN ARAYUZU (dropdown + sayfalama + detay)
# =====================================================================
BAN_PAGE_SIZE = 8

def _ban_label(u):
    name = (u['first_name'] or u['username'] or "?")[:18]
    return f"\U0001f6ab {name} ({u['user_id']})"

async def render_ban_list(q, page=0, rows=None):
    if rows is None:
        rows = db.get_banned_users()
    total = len(rows)
    if total == 0:
        kb = [[InlineKeyboardButton("\u2795 Yeni Engelle", callback_data="apban_addinfo")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(box_message("ENGELLILER", "Engellenmis kullanici yok.\n\nYeni: <code>/ban ID neden</code>", "\u2705"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    pages = (total + BAN_PAGE_SIZE - 1) // BAN_PAGE_SIZE
    page = max(0, min(page, pages-1))
    chunk = rows[page*BAN_PAGE_SIZE:(page+1)*BAN_PAGE_SIZE]
    kb = [[InlineKeyboardButton(_ban_label(u), callback_data=f"apban_view_{u['user_id']}")] for u in chunk]
    nav = []
    if page > 0: nav.append(InlineKeyboardButton("\u25c0\ufe0f Onceki", callback_data=f"apban_page_{page-1}"))
    if page < pages-1: nav.append(InlineKeyboardButton("Sonraki \u25b6\ufe0f", callback_data=f"apban_page_{page+1}"))
    if nav: kb.append(nav)
    kb.append([InlineKeyboardButton("\u2795 Yeni Engelle", callback_data="apban_addinfo"),
               InlineKeyboardButton("\U0001f50d Arama", callback_data="apban_searchinfo")])
    kb.append([InlineKeyboardButton("\u25c0\ufe0f Ana Menu", callback_data="ap_main")])
    await q.edit_message_text(box_message("ENGELLI KULLANICILAR",
        f"Toplam {total} engelli (Sayfa {page+1}/{pages})\n\nDetay icin dokunun \U0001f447", "\U0001f6ab"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

async def render_ban_detail(q, buid):
    u = db.get_user(buid)
    if not u or not u['is_banned']:
        await q.answer("Bulunamadi veya engelli degil.", show_alert=True)
        await render_ban_list(q, 0); return
    tarih = (u['ban_at'][:16].replace("T", " ") if u['ban_at'] else "Bilinmiyor")
    kim = "Sistem (oto flood)" if not u['ban_by'] else f"Admin {u['ban_by']}"
    uname = f"@{u['username']}" if u['username'] else "Yok"
    txt = box_message("ENGELLI DETAY", (
        f"\U0001f464 <b>Ad:</b> {harden_text(u['first_name'] or '',80)} {harden_text(u['last_name'] or '',80)}\n"
        f"\U0001f4ac <b>Username:</b> {uname}\n"
        f"\U0001f194 <b>ID:</b> <code>{u['user_id']}</code>\n\n"
        f"\U0001f6ab <b>Engel tarihi:</b> {tarih}\n"
        f"\U0001f4dd <b>Neden:</b> {u['ban_reason'] or '-'}\n"
        f"\U0001f451 <b>Engelleyen:</b> {kim}\n\n"
        f"\U0001f4c5 <b>Katilim:</b> {u['joined_at'][:10]}\n"
        f"\U0001f4ac <b>Mesaj:</b> {u['total_messages']}"), "\U0001f6ab")
    kb = [[InlineKeyboardButton("\u2705 Bani Kaldir", callback_data=f"apban_unban_{u['user_id']}")],
          [InlineKeyboardButton("\u25c0\ufe0f Liste", callback_data="ap_bans")],
          [InlineKeyboardButton("\U0001f3e0 Ana Menu", callback_data="ap_main")]]
    await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

# =====================================================================
# ANA PANEL CALLBACK
# =====================================================================

async def _cb_alert(q, context, text):
    """admin_cb basta genel q.answer() cagirdigi icin ikinci answer Telegram'da
    reddedilebilir; alert gosterilemezse ayni metni sohbete mesaj olarak yolla."""
    try:
        await q.answer(text, show_alert=True)
    except Exception:
        try:
            await context.bot.send_message(chat_id=q.message.chat_id, text=text)
        except Exception:
            pass

async def admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user = update.effective_user
    if not is_authenticated(user.id):
        # Beyaz listedeki ama oturumu dolmus admine neden calismadigini soyle;
        # yetkisiz kullaniciya ise hicbir sey sizdirma.
        if user.id in ADMIN_IDS:
            await q.answer("Oturum suresi doldu. /admin ile yeniden giris yapin.", show_alert=True)
        else:
            await q.answer()
        return
    # Ayni sorgu bir dala geri donerek (or. tpl_del -> ap_templates) ikinci kez
    # girebilir; ikinci answer'in reddedilmesi ekran yenilemeyi oldurmesin.
    try:
        await q.answer()
    except Exception:
        pass
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[user.id] = time.time()
    data = q.data
    back = [[InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]

    if data == "ap_logout":
        if user.id in authenticated_admins: del authenticated_admins[user.id]
        db.admin_log(user.id, "logout")
        # editMessageText yalniz inline klavye kabul eder; ReplyKeyboardRemove
        # gonderilirse Telegram TUM cikis ekranini reddediyordu.
        await q.edit_message_text(box_message("CIKIS", "Admin oturumu kapatildi.\n\nGiris: /admin", "\U0001f6aa"), parse_mode=ParseMode.HTML)
        context.user_data["admin_kb"] = False
        try:
            await context.bot.send_message(chat_id=q.message.chat_id,
                text="\U0001f464 Kullanici menusune donuldu.", reply_markup=_build_reply_menu())
        except Exception:
            pass
        await _send_giris_chat(context, q.message.chat_id)
        return

    if data == "ap_history":
        kayitlar = db.list_broadcast_logs(limit=10)
        if not kayitlar:
            await q.edit_message_text(box_message("GONDERIM GECMISI",
                "Henuz toplu gonderim yapilmadi.\nDuyuru, toplu mesaj, zamanli mesaj ve sablon gonderimleri burada listelenir.", "\U0001f4dc"),
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
            return
        rows = []
        for b in kayitlar:
            tarih = str(b["created_at"])[5:16].replace("T", " ")
            rows.append([InlineKeyboardButton(
                f"{b['kind'][:18]} → ✅{b['ok']} ❌{b['fail']} ({tarih})",
                callback_data=f"aphist_{b['id']}")])
        rows.append([InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")])
        await q.edit_message_text(box_message("GONDERIM GECMISI",
            "Son 10 gonderim. Detay ve TEKRAR GONDERME icin dokun \U0001f447", "\U0001f4dc"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("aphistsend_"):
        try: bid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        b = db.get_broadcast_log(bid)
        if not b or not b.get("payload"):
            await _cb_alert(q, context, "Bu kaydin icerigi tekrar gonderilemez.")
            return
        try:
            p = json.loads(b["payload"])
        except Exception:
            await _cb_alert(q, context, "Kayit icerigi okunamadi.")
            return
        if _cb_throttled(user.id, f"aphistsend_{bid}", 30):
            await _cb_alert(q, context, "Gonderim zaten baslatildi; lutfen bekleyin.")
            return
        await q.edit_message_text(box_message("GONDERILIYOR",
            f"Ayni icerik ayni hedefe yeniden gonderiliyor: {target_label(b['target'])}...", "⏳"),
            parse_mode=ParseMode.HTML)
        ok, fail, total, ozet = await deliver_payload(context, p, b["target"] or "all")
        _log_broadcast(f"\U0001f501 Tekrar: {b['kind'][:20]}", b["target"], ok, fail, total, p, user.id)
        db.admin_log(user.id, "broadcast_resend", f"#{bid} ok:{ok}")
        rapor = (f"Hedef: {target_label(b['target'])}\n✅ {ok} | ❌ {fail} | \U0001f465 {total}"
                 + (f"\n\n{ozet}" if ozet else ""))
        await context.bot.send_message(chat_id=q.message.chat_id,
            text=box_message("TEKRAR GONDERILDI", rapor, "\U0001f501"), parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f4dc Gecmis", callback_data="ap_history")]]))
        return

    if data.startswith("aphist_"):
        try: bid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        b = db.get_broadcast_log(bid)
        if not b:
            await _cb_alert(q, context, "Kayit bulunamadi.")
            return
        detay = (f"<b>{sanitize_input(b['kind'], 60)}</b>\n"
                 f"\U0001f3af Hedef: {target_label(b['target'])}\n"
                 f"✅ Ulasan: {b['ok']} | ❌ Ulasamayan: {b['fail']} | \U0001f465 Toplam: {b['total']}\n"
                 f"\U0001f4c5 {str(b['created_at']).replace('T', ' ')[:16]}")
        onizleme = ""
        try:
            p = json.loads(b["payload"]) if b.get("payload") else {}
            onizleme = build_payload_text(p)
        except Exception:
            p = {}
        if onizleme:
            detay += f"\n\n\U0001f4c4 <b>Icerik:</b>\n{_safe_caption(onizleme, 700)}"
        rows = []
        if b.get("payload"):
            rows.append([InlineKeyboardButton("\U0001f501 Ayni Hedefe Tekrar Gonder", callback_data=f"aphistsend_{bid}")])
        rows.append([InlineKeyboardButton("\u25c0\ufe0f Gecmis", callback_data="ap_history")])
        await q.edit_message_text(box_message("GONDERIM DETAYI", detay, "\U0001f4dc"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows),
            disable_web_page_preview=True)
        return

    if data == "ap_help":
        await q.edit_message_text(box_message("YARDIM MERKEZI",
            "Konu sec 👇 Her konuda 'bu buton ne yapar, basinca ne olur' adim adim anlatilir.\n"
            "Daha genis anlatim icin klasordeki OPERASYON_REHBERI.md dosyasina bakabilirsin.", "\U0001f4d6"),
            parse_mode=ParseMode.HTML, reply_markup=_yardim_liste_kb())
        return

    if data.startswith("aphelp_"):
        key = data[len("aphelp_"):]
        metin = _YARDIM_METINLERI.get(key)
        if not metin:
            return
        baslik = dict(_YARDIM_KONULARI).get(key, "YARDIM")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Yardim Konulari", callback_data="ap_help"),
                                    InlineKeyboardButton("\U0001f3e0 Panel", callback_data="ap_main")]])
        await q.edit_message_text(box_message(baslik, metin, "\U0001f4d6"),
            parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
        return

    if data == "ap_main":
        await q.edit_message_text(_panel_text(), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(_panel_keyboard()))
        return

    if data == "ap_stats":
        s = db.get_stats()
        seg = " | ".join([f"{SEGMENTS[k]}: {s['seg'][k]}" for k in SEGMENTS])
        txt = box_message("ISTATISTIKLER", (
            f"\U0001f465 Toplam: {s['total']}\n\u2705 Aktif: {s['active']}\n\U0001f6ab Banli: {s['banned']}\n"
            f"\U0001f195 Bugun: +{s['today']}\n\U0001f4c5 Hafta: +{s['week']}\n"
            f"\U0001f553 24s Aktif: {s['active24']}\n\U0001f4ac Toplam mesaj: {s['total_msgs']}\n"
            f"\U0001f517 Giris gosterim: {s['giris_views']}\n\n{seg}\n\n"
            f"\U0001f4c5 {datetime.now().strftime('%d.%m.%Y %H:%M')}"), "\U0001f4ca")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
        return

    if data == "ap_links":
        giris = db.get_setting("giris_link") or DEFAULT_GIRIS_LINK
        reg = db.get_setting("register_link") or DEFAULT_REGISTER_LINK
        bonus = db.get_setting("bonus_link") or DEFAULT_BONUS_LINK
        support = db.get_setting("support_link") or DEFAULT_SUPPORT_LINK
        channel = db.get_setting("channel_link") or DEFAULT_CHANNEL_LINK or "(yok)"
        play = db.get_setting("play_link") or DEFAULT_PLAY_LINK or "(giris linki kullaniliyor)"
        txt = box_message("LINK YONETIMI", (
            f"\U0001f517 <b>Giris:</b> <code>{giris}</code>\n"
            f"\U0001f525 <b>REGISTER_LINK:</b> <code>{reg}</code>\n"
            f"\U0001f381 <b>ACTIVATE_LINK:</b> <code>{bonus}</code>\n"
            f"\U0001f4ac <b>Destek:</b> <code>{support}</code>\n"
            f"\U0001f4e2 <b>Kanal:</b> <code>{channel}</code>\n"
            f"\U0001f3ae <b>Play:</b> <code>{play}</code>\n\nDegistir \U0001f447"), "\U0001f517")
        kb = [[_edit_btn("\U0001f517 Giris", "giris_link"), _edit_btn("\U0001f525 Kayit", "register_link")],
              [_edit_btn("\U0001f381 Aktif Et", "bonus_link"), _edit_btn("\U0001f4ac Destek", "support_link")],
              [_edit_btn("\U0001f4e2 Kanal", "channel_link"), _edit_btn("\U0001f3ae Play", "play_link")],
              [_edit_btn("\U0001f4f1 Mini App", "miniapp_link"), _edit_btn("\U0001f4b0 Para Yatir", "deposit_link")],
              [_edit_btn("\U0001f4b8 Para Cek", "withdraw_link")],
              [_edit_btn("\U0001f9ed Odeme Destek", "deposit_support_link"), _edit_btn("\U0001f9ed Cekim Destek", "withdraw_support_link")],
              [_edit_btn("\U0001f9ed Bonus Destek", "bonus_support_link")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("apmedia_page_"):
        try: page = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): page = 0
        await render_media_library(q, page)
        return

    if data.startswith("apmedia_view_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        await render_media_detail(q, media_pk)
        return

    if data.startswith("apmedia_preview_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        row = db.get_campaign_media(media_pk)
        if row:
            try:
                await send_media_library_preview(context, q.message.chat_id, row)
                # Menu ustte kalmasin: eski menuyu sil, yenisini onizlemenin ALTINA gonder.
                try:
                    await q.message.delete()
                except Exception:
                    pass
                await send_media_detail_chat(context, q.message.chat_id, media_pk)
            except Exception as exc:
                logger.warning(f"Medya onizlemesi gonderilemedi: {exc}")
                # Eski menu mesaji silinmis olabilir; edit yerine yeni mesaj gonder.
                await context.bot.send_message(chat_id=q.message.chat_id,
                    text=box_message("ONIZLEME HATASI", "Medya Telegram tarafindan gonderilemedi. Kaydi silip yeniden yukleyebilirsiniz.", "❌"),
                    parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Kutuphane", callback_data="apmedia_page_0")]]))
        else:
            await render_media_library(q, 0)
        return

    if data.startswith("apmedia_select_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        row = db.get_campaign_media(media_pk)
        if row and activate_campaign_media_record(row):
            db.admin_log(user.id, "select_campaign_media", str(media_pk))
            await render_media_detail(q, media_pk)
        else:
            await render_media_library(q, 0)
        return

    if data.startswith("apmedia_welcome_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        row = db.get_campaign_media(media_pk)
        if row:
            db.set_setting("welcome_media_id", row["media_id"])
            db.set_setting("welcome_media_type", row["media_type"])
            db.set_setting("welcome_media_url", "")
            db.admin_log(user.id, "set_welcome_media", str(media_pk))
            await render_media_detail(q, media_pk)
        else:
            await render_media_library(q, 0)
        return

    if data.startswith("apmedia_unwelcome_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        db.set_setting("welcome_media_id", "")
        db.set_setting("welcome_media_type", "")
        db.admin_log(user.id, "clear_welcome_media", str(media_pk))
        if db.get_campaign_media(media_pk):
            await render_media_detail(q, media_pk)
        else:
            await render_media_library(q, 0)
        return

    if data.startswith("apmedia_delask_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        row = db.get_campaign_media(media_pk)
        if not row:
            await render_media_library(q, 0); return
        if media_pk == active_campaign_media_library_id():
            await q.edit_message_text(box_message("SILINEMEZ", "Bu medya su anda aktif. Once kutuphaneden baska bir medya secin.", "⚠️"),
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Detaya Don", callback_data=f"apmedia_view_{media_pk}")]]))
            return
        kb = [[InlineKeyboardButton("🗑 Evet, Sil", callback_data=f"apmedia_delete_{media_pk}")],
              [InlineKeyboardButton("◀️ Vazgec", callback_data=f"apmedia_view_{media_pk}")]]
        await q.edit_message_text(box_message("MEDYAYI SIL", f"#{media_pk} numarali kayit kutuphaneden silinsin mi?", "⚠️"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("apmedia_delete_"):
        try: media_pk = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): media_pk = 0
        if media_pk and media_pk != active_campaign_media_library_id() and db.get_campaign_media(media_pk):
            db.delete_campaign_media(media_pk)
            db.admin_log(user.id, "delete_campaign_media", str(media_pk))
        await render_media_library(q, 0)
        return

    if data == "ap_image":
        media_file = db.get_setting("campaign_media_file") or db.get_setting("promo_image_file") or ""
        media_url = db.get_setting("campaign_media_url") or db.get_setting("promo_image") or DEFAULT_PROMO_IMAGE
        media_type = db.get_setting("campaign_media_type") or _media_kind(media_file or media_url)
        active_id = active_campaign_media_library_id()
        total = db.count_campaign_media()
        active_text = f"Kutuphane kaydi #{active_id}" if active_id else ("URL / yerel dosya" if media_url or media_file else "Yok")
        if db.get_setting("welcome_media_id"):
            welcome_media_text = "Kutuphaneden secili"
        elif (db.get_setting("welcome_media_url") or DEFAULT_WELCOME_MEDIA_URL):
            welcome_media_text = "URL"
        else:
            welcome_media_text = "Otomatik (kampanya medyasi / promo.jpg)"
        txt = box_message("BANNER & MEDYA YONETIMI", (
            f"<b>Aktif kampanya:</b> {active_text}\n<b>Tur:</b> {media_type}\n<b>Kutuphanedeki medya:</b> {total}\n"
            f"<b>Karsilama gorseli:</b> {welcome_media_text}\n\n"
            f"Kutuphaneden bir kaydi kampanyada aktif edebilir veya \U0001f64b Karsilamada Kullan ile /start acilis gorseli yapabilirsiniz."), "\U0001f5bc")
        kb = [[InlineKeyboardButton("🗂 Medya Kutuphanesi", callback_data="apmedia_page_0")],
              [InlineKeyboardButton("📥 Yeni Foto/Video Ekle", callback_data="apimg_howto")],
              [_edit_btn("\U0001f517 Medya URL ile degistir", "campaign_media_url")],
              [_edit_btn("\U0001f64b Karsilama medya URL", "welcome_media_url")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "apimg_howto":
        txt = box_message("YENI MEDYA EKLE", "1. Bu ekrandan ana sohbete donun.\n2. Bota dogrudan bir fotoğraf veya video gonderin.\n3. Her gonderi kutuphaneye ayri kayit olarak eklenir ve son eklenen medya aktif olur.\n4. Daha sonra /admin → Foto / Video → Medya Kutuphanesi yolundan istediginizi yeniden secebilirsiniz.", "📥")
        kb = [[InlineKeyboardButton("🗂 Kutuphaneyi Ac", callback_data="apmedia_page_0")],
              [InlineKeyboardButton("◀️ Foto / Video", callback_data="ap_image")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ap_buttons":
        g = lambda k, d: db.get_setting(k) or d
        txt = box_message("BUTON & YAZI", (
            f"<b>Uye Ol:</b> {g('register_btn_text',DEFAULT_REGISTER_BTN)}\n"
            f"<b>Aktif Et:</b> {g('bonus_btn_text',DEFAULT_BONUS_BTN)}\n"
            f"<b>Karsilama:</b> {g('welcome_text',DEFAULT_WELCOME)}\n"
            f"<b>Kampanya basligi:</b> {g('campaign_title',DEFAULT_CAMPAIGN_TITLE)}\n"
            f"<b>Kampanya:</b> {g('promo_caption',DEFAULT_PROMO_CAP)}\n"
            f"<b>Tiklanabilir yazi:</b> {g('caption_link_text','(yok)')}\n"
            f"<b>Kod:</b> {g('campaign_code','(yok)')} ({g('campaign_code_style','copy')})\n"
            f"<b>Giris:</b> {g('giris_btn_text',DEFAULT_GIRIS_BTN)}\n"
            f"<b>Destek:</b> {g('support_btn_text',DEFAULT_SUPPORT_BTN)}\n\nDegistir \U0001f447"), "\u270f\ufe0f")
        kb = [[_edit_btn("Uye Ol yazisi","register_btn_text"), _edit_btn("Aktif Et yazisi","bonus_btn_text")],
              [_edit_btn("Karsilama","welcome_text"), _edit_btn("Kampanya basligi","campaign_title")],
              [_edit_btn("Kampanya aciklamasi","promo_caption")],
              [_edit_btn("Tiklanabilir yazi","caption_link_text"), _edit_btn("Yazi linki","caption_link_url")],
              [_edit_btn("Kampanya kodu","campaign_code"), _edit_btn("Kod gorunumu","campaign_code_style")],
              [_edit_btn("Giris butonu","giris_btn_text"), _edit_btn("Destek butonu","support_btn_text")],
              [_edit_btn("Kanal mesaji","channel_text"), _edit_btn("Site ID mesaji","site_id_prompt")],
              [_edit_btn("Play butonu","menu_button_text"), _edit_btn("Destek mesaji","destek_text")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ap_users":
        txt = box_message("KULLANICI YONETIMI", (
            "Komutlar:\n"
            "<code>/userinfo ID</code> - Detay\n"
            "<code>/userlist</code> - Son 20\n"
            "<code>/usersearch isim</code> - Ara\n"
            "<code>/topusers</code> - En aktif 10\n"
            "<code>/export</code> - CSV indir"), "\U0001f465")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
        return

    if data == "ap_segments":
        s = db.get_stats()
        seg_lines = "\n".join([f"{SEGMENTS[k]}: {s['seg'][k]} kullanici" for k in SEGMENTS])
        txt = box_message("KATEGORILER", (
            f"{seg_lines}\n\n"
            f"<code>/setseg ID kategori</code> - ekle\n"
            f"<code>/setseg ID none</code> - cikar\n"
            f"<code>/seglist kategori</code> - uyeler\n\n"
            f"Kategoriler: {' / '.join(SEGMENTS.keys())}\n\n"
            f"<i>Toplu mesajda hedef olarak secilebilir.</i>"), "\U0001f3f7")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
        return

    if data == "ap_bans" or data.startswith("apban_page_"):
        page = 0
        if data.startswith("apban_page_"):
            try: page = int(data.replace("apban_page_", ""))
            except: page = 0
        await render_ban_list(q, page); return
    if data.startswith("apban_view_"):
        try: buid = int(data.replace("apban_view_", ""))
        except: buid = 0
        await render_ban_detail(q, buid); return
    if data.startswith("apban_unban_"):
        try: buid = int(data.replace("apban_unban_", ""))
        except: buid = 0
        db.unban_user(buid); db.admin_log(user.id, "unban", str(buid))
        await _cb_alert(q, context, "\u2705 Ban kaldirildi.")
        await render_ban_list(q, 0); return
    if data == "apban_addinfo":
        await _cb_alert(q, context, "Yeni engelleme: sohbete /ban ID neden yazin. Ornek: /ban 123 spam"); return
    if data == "apban_searchinfo":
        await _cb_alert(q, context, "Arama: sohbete /banara ID veya isim yazin."); return

    if data == "ap_broadcast":
        txt = box_message("TOPLU MESAJ", "Adim adim sihirbaz: tip \u2192 baslik \u2192 metin \u2192 (kod/foto-video/buton) \u2192 hedef \u2192 onizleme \u2192 onay.\n\nBaslat \U0001f447", "\U0001f4e3")
        kb = [[InlineKeyboardButton("\U0001f4e3 Toplu Mesaj Olustur", callback_data="bcgo")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ap_support":
        on = (db.get_setting("support_enabled") or "0") == "1"
        status = "\U0001f7e2 AKTIF" if on else "\U0001f534 PASIF"
        txt = box_message("CANLI DESTEK", (
            f"<b>Durum:</b> {status}\n"
            f"<b>Link:</b> {db.get_setting('support_link') or DEFAULT_SUPPORT_LINK}\n"
            f"<b>Buton:</b> {db.get_setting('support_btn_text') or DEFAULT_SUPPORT_BTN}\n\nYonet \U0001f447"), "\U0001f4ac")
        tg = ("\U0001f534 Pasif Yap","apsup_off") if on else ("\U0001f7e2 Aktif Et","apsup_on")
        kb = [[InlineKeyboardButton(tg[0], callback_data=tg[1])],
              [_edit_btn("\U0001f517 Link","support_link"), _edit_btn("\u270f\ufe0f Buton","support_btn_text")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    if data in ("apsup_on","apsup_off"):
        db.set_setting("support_enabled", "1" if data=="apsup_on" else "0")
        db.admin_log(user.id, "support_"+("on" if data=="apsup_on" else "off"))
        await _cb_alert(q, context, "Destek " + ("aktif." if data=="apsup_on" else "kapali."))
        q.data = "ap_support"; return await admin_cb(update, context)

    if data == "ap_complaints":
        on = (db.get_setting("complaints_enabled") or "0") == "1"
        status = "\U0001f7e2 AKTIF" if on else "\U0001f534 PASIF"
        toplam = db.exe("SELECT COUNT(*) as c FROM complaints")[0]['c']
        yeni = db.count_new_complaints()
        txt = box_message("SIKAYET YONETIMI", (
            f"<b>Durum:</b> {status}\n<b>Toplam:</b> {toplam}\n<b>Yeni:</b> {yeni}\n\nYonet \U0001f447"), "\U0001f4e8")
        tg = ("\U0001f534 Pasif Yap","apcmp_off") if on else ("\U0001f7e2 Aktif Et","apcmp_on")
        kb = [[InlineKeyboardButton(tg[0], callback_data=tg[1])],
              [InlineKeyboardButton(f"\U0001f4e8 Sikayetleri Gor ({toplam})", callback_data="apcmp_list")],
              [InlineKeyboardButton("\U0001f4e5 Dosya Indir (bilgi)", callback_data="apcmp_file")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    if data in ("apcmp_on","apcmp_off"):
        db.set_setting("complaints_enabled", "1" if data=="apcmp_on" else "0")
        db.admin_log(user.id, "complaints_"+("on" if data=="apcmp_on" else "off"))
        await _cb_alert(q, context, "Sikayet " + ("aktif." if data=="apcmp_on" else "kapali."))
        q.data = "ap_complaints"; return await admin_cb(update, context)
    if data == "apcmp_list":
        rows = db.get_complaints(limit=10)
        if not rows:
            await _cb_alert(q, context, "Sikayet yok."); return
        lines = ""
        for c in rows:
            durum = {"yeni":"\U0001f534","okundu":"\U0001f7e1","cozuldu":"\U0001f7e2"}.get(c['status'],"\u26aa")
            ozet = (c['message'][:35]+"...") if len(c['message'])>35 else c['message']
            lines += f"{durum} #{c['id']} <code>{c['user_id']}</code>: {ozet}\n"
        await q.edit_message_text(box_message("SON SIKAYETLER", f"{lines}\n<i>Detay: /sikayetler ID</i>", "\U0001f4e8"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_complaints")]]))
        return
    if data == "apcmp_file":
        await _cb_alert(q, context, "Dosya icin sohbete /sikayetdosya yazin."); return

    # --- EKRAN GORUNTUSU KAYITLARI ---
    if data == "ap_ekran":
        on = screenshots_enabled()
        status = "\U0001f7e2 AKTIF" if on else "\U0001f534 PASIF"
        toplam, yeni = db.count_screenshots(), db.count_screenshots(only_new=True)
        cats = screenshot_categories()
        cat_lines = "\n".join(
            f"• {sanitize_input(c['label'], 40)} → {', '.join(sanitize_input(f, 30) for f in c['fields']) or '(bilgi sorulmaz)'}"
            for c in cats) or "(tanimli kategori yok)"
        txt = box_message("EKRAN GORUNTUSU KAYITLARI", (
            f"<b>Durum:</b> {status}\n<b>Toplam:</b> {toplam} | <b>Yeni:</b> {yeni}\n"
            f"<b>Klasor:</b> <code>screenshots/</code>\n"
            f"<b>Dosya adi sablonu:</b> <code>{sanitize_input(screenshot_name_format(), 120)}</code>\n\n"
            f"<b>Kategoriler → sorulan bilgiler:</b>\n{cat_lines}\n\n"
            "Foto gelince bu kategoriler secenek olarak sunulur; secilen kategori, tarih ve "
            "yazilan bilgiler dosya adina yazilir."), "\U0001f4f8")
        tg = ("\U0001f534 Pasif Yap", "apekran_off") if on else ("\U0001f7e2 Aktif Et", "apekran_on")
        kb = [[InlineKeyboardButton(tg[0], callback_data=tg[1])],
              [InlineKeyboardButton(f"\U0001f4f8 Son Kayitlar ({toplam})", callback_data="apekran_list")],
              [_edit_btn("\U0001f3f7 Kategoriler", "screenshot_categories"),
               _edit_btn("\U0001f4dd Dosya Adi Sablonu", "screenshot_name_format")],
              [_edit_btn("\U0001f4ac Secenek Mesaji", "screenshot_prompt")],
              [InlineKeyboardButton("\U0001f4e5 CSV Dosyasi (bilgi)", callback_data="apekran_file")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    if data in ("apekran_on", "apekran_off"):
        db.set_setting("screenshots_enabled", "1" if data == "apekran_on" else "0")
        db.admin_log(user.id, "screenshots_" + ("on" if data == "apekran_on" else "off"))
        await _cb_alert(q, context, "Ekran goruntusu kaydi " + ("aktif." if data == "apekran_on" else "kapali."))
        q.data = "ap_ekran"; return await admin_cb(update, context)
    if data == "apekran_list":
        rows = db.list_screenshots(limit=10)
        if not rows:
            await _cb_alert(q, context, "Henuz kayit yok."); return
        await q.edit_message_text(box_message("SON EKRAN GORUNTULERI",
            f"{_ss_list_lines(rows)}\n<i>Detay ve foto: /ekranlar ID</i>", "\U0001f4f8"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_ekran")]]))
        return
    if data == "apekran_file":
        await _cb_alert(q, context, "Dosya icin sohbete /ekrandosya yazin."); return

    # --- HAZIR BILDIRIMLER: giris adresi / mini app guncellemesi ---
    if data in ("apnotify_giris", "apnotify_miniapp"):
        if _cb_throttled(user.id, "apnotify", 15):
            await _cb_alert(q, context, "Az once gonderildi; birkac saniye bekleyin."); return
        if data == "apnotify_giris":
            link = (db.get_setting("giris_link") or DEFAULT_GIRIS_LINK).strip()
            metin = box_message("\U0001f517 GUNCEL GIRIS ADRESI YENILENDI!",
                "Yeni adresimize asagidaki butondan guvenle ulasabilirsin \U0001f447", "\U0001f514")
            buton = InlineKeyboardButton(db.get_setting("giris_btn_text") or DEFAULT_GIRIS_BTN, url=link)
        else:
            link = (_menu_link("miniapp_link", DEFAULT_MINIAPP_LINK)
                    or _menu_link("giris_link", DEFAULT_GIRIS_LINK))
            metin = box_message("\U0001f4f1 MINI APP GUNCELLENDI!",
                "Yeni surumu tek dokunusla acabilirsin \U0001f447", "\U0001f514")
            if link.lower().startswith("https://"):
                buton = InlineKeyboardButton("\U0001f4f1 Mini App'i Ac", web_app=WebAppInfo(url=link))
            else:
                buton = InlineKeyboardButton("\U0001f4f1 Mini App'i Ac", url=link)
        if not is_valid_url(link):
            await _cb_alert(q, context, "Once gecerli bir link kaydedin."); return
        await q.edit_message_text(box_message("GONDERILIYOR", "Bildirim tum kullanicilara iletiliyor...", "⏳"),
            parse_mode=ParseMode.HTML)
        kb = InlineKeyboardMarkup([[buton]])
        async def _tek_bildirim(uid):
            await context.bot.send_message(chat_id=uid, text=metin,
                parse_mode=ParseMode.HTML, reply_markup=kb)
        ok, fail, ozet = await _kitle_gonder(db.get_all_users(), _tek_bildirim)
        db.admin_log(user.id, "notify_" + data.split("_")[1], f"ok:{ok}")
        rapor = f"✅ {ok} | ❌ {fail}" + (f"\n\n{ozet}" if ozet else "")
        await context.bot.send_message(chat_id=q.message.chat_id,
            text=box_message("BILDIRIM GONDERILDI", rapor, "\U0001f4e3"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Panele Don", callback_data="ap_main")]]))
        return

    # --- KAMPANYA YONETIMI ---
    if data == "ap_camps":
        txt, kb = _camps_admin_screen()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("apc_list_"):
        key = data[len("apc_list_"):]
        if key not in CAMPAIGN_CATEGORIES:
            return
        camps = db.list_campaigns_admin(category=key)
        now_iso = datetime.now().isoformat(timespec="seconds")
        rows = []
        for c in camps[:15]:
            if c["active"]:
                mark = "✅"
            elif c["expires_at"] and c["expires_at"] <= now_iso:
                mark = "⌛"
            else:
                mark = "⏸"
            rows.append([InlineKeyboardButton(f"{mark} #{c['id']} {(c['title'] or '')[:26]}",
                                              callback_data=f"apc_view_{c['id']}")])
        rows.append([InlineKeyboardButton("➕ Yeni Kampanya", callback_data="apc_new")])
        rows.append([InlineKeyboardButton("◀️ Kategoriler", callback_data="ap_camps")])
        await q.edit_message_text(box_message(CAMPAIGN_CATEGORIES[key],
            f"Toplam {len(camps)} kayit. Yonetmek icin dokunun.", "\U0001f3af"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("apc_notify_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        c = db.get_campaign(cid)
        if not c or not c["active"]:
            await _cb_alert(q, context, "Kampanya aktif degil."); return
        if _cb_throttled(user.id, "apc_notify", 10):
            await _cb_alert(q, context, "Az once gonderildi; birkac saniye bekleyin."); return
        await q.edit_message_text(box_message("GONDERILIYOR", "Yeni kampanya bildirimi hedef kitleye iletiliyor...", "⏳"),
            parse_mode=ParseMode.HTML)
        baslik_map = {"turnuva": "\U0001f3c6 TURNUVA BASLADI!"}
        bildirim_baslik = baslik_map.get(c["category"], "\U0001f389 YENI KAMPANYA BASLADI!")
        text = box_message(bildirim_baslik, build_campaign_detail_text(c), "\U0001f514")
        kb = None
        if c.get("btn_text") and is_valid_url(c.get("btn_url") or ""):
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(c["btn_text"][:40], url=c["btn_url"])]])
        async def _tek_kampanya(uid):
            if c.get("media_id") and (c.get("media_type") or "photo") == "video":
                await context.bot.send_video(chat_id=uid, video=c["media_id"],
                    caption=_safe_caption(text), parse_mode=ParseMode.HTML, reply_markup=kb)
            elif c.get("media_id"):
                await context.bot.send_photo(chat_id=uid, photo=c["media_id"],
                    caption=_safe_caption(text), parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await context.bot.send_message(chat_id=uid, text=text,
                    parse_mode=ParseMode.HTML, reply_markup=kb)
        ok, fail, ozet = await _kitle_gonder(_campaign_audience(c.get("segment") or ""), _tek_kampanya)
        db.admin_log(user.id, "campaign_notify", f"#{cid} ok:{ok}")
        rapor = f"#{cid} • ✅ {ok} | ❌ {fail}" + (f"\n\n{ozet}" if ozet else "")
        await context.bot.send_message(chat_id=q.message.chat_id,
            text=box_message("BILDIRIM GONDERILDI", rapor, "\U0001f4e3"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Kampanyalar", callback_data="ap_camps")]]))
        return

    if data.startswith("apc_view_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        c = db.get_campaign(cid)
        if not c:
            await _cb_alert(q, context, "Kayit bulunamadi."); return
        await q.edit_message_text(_camp_admin_detail_text(c), parse_mode=ParseMode.HTML,
            reply_markup=_camp_admin_detail_kb(c))
        return

    if data.startswith("apc_prev_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        c = db.get_campaign(cid)
        if not c:
            return
        text = build_campaign_detail_text(c)
        kb = _campaign_detail_kb(c)
        try:
            if c.get("media_id") and (c.get("media_type") or "photo") == "video":
                await context.bot.send_video(chat_id=q.message.chat_id, video=c["media_id"],
                    caption=_safe_caption(text), parse_mode=ParseMode.HTML, reply_markup=kb)
            elif c.get("media_id"):
                await context.bot.send_photo(chat_id=q.message.chat_id, photo=c["media_id"],
                    caption=_safe_caption(text), parse_mode=ParseMode.HTML, reply_markup=kb)
            else:
                await context.bot.send_message(chat_id=q.message.chat_id, text=text,
                    parse_mode=ParseMode.HTML, reply_markup=kb, disable_web_page_preview=True)
        except Exception as exc:
            logger.warning(f"[APC] onizleme hatasi #{cid}: {exc}")
        return

    if data.startswith("apc_toggle_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        c = db.get_campaign(cid)
        if not c:
            return
        db.set_campaign_active(cid, not c["active"])
        db.admin_log(user.id, "campaign_toggle", f"#{cid}")
        c = db.get_campaign(cid)
        await q.edit_message_text(_camp_admin_detail_text(c), parse_mode=ParseMode.HTML,
            reply_markup=_camp_admin_detail_kb(c))
        return

    if data.startswith("apc_delask_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        kb = [[InlineKeyboardButton("\U0001f5d1 Evet, Sil", callback_data=f"apc_delete_{cid}")],
              [InlineKeyboardButton("◀️ Vazgec", callback_data=f"apc_view_{cid}")]]
        await q.edit_message_text(box_message("KAMPANYAYI SIL", f"#{cid} kalici olarak silinsin mi?", "⚠️"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("apc_delete_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        c = db.get_campaign(cid)
        cat = c["category"] if c else "bonus"
        db.delete_campaign(cid)
        db.admin_log(user.id, "campaign_delete", f"#{cid}")
        await q.edit_message_text(box_message("SILINDI", f"Kampanya #{cid} silindi.", "\U0001f5d1"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Liste", callback_data=f"apc_list_{cat}")]]))
        return

    if data.startswith("apcsegset_"):
        # apcsegset_{id}_{segment|all}
        parts = data.split("_")
        try: cid = int(parts[1])
        except (TypeError, ValueError, IndexError): return
        seg = "_".join(parts[2:])
        if seg == "all":
            seg = ""
        if seg and seg not in SEGMENTS and seg not in AUTO_SEGMENTS:
            return
        db.update_campaign_field(cid, "segment", seg)
        db.admin_log(user.id, "campaign_segment", f"#{cid} {seg or 'herkes'}")
        c = db.get_campaign(cid)
        if c:
            await q.edit_message_text(_camp_admin_detail_text(c), parse_mode=ParseMode.HTML,
                reply_markup=_camp_admin_detail_kb(c))
        return

    if data.startswith("apc_seg_"):
        try: cid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        rows = [[InlineKeyboardButton("\U0001f30d Herkes", callback_data=f"apcsegset_{cid}_all")]]
        for k, label in AUTO_SEGMENTS.items():
            rows.append([InlineKeyboardButton(label, callback_data=f"apcsegset_{cid}_{k}")])
        for k, label in SEGMENTS.items():
            rows.append([InlineKeyboardButton(label, callback_data=f"apcsegset_{cid}_{k}")])
        rows.append([InlineKeyboardButton("◀️ Vazgec", callback_data=f"apc_view_{cid}")])
        await q.edit_message_text(box_message("HEDEF SEGMENT", "Bu kampanya kime ozel olsun?", "\U0001f3f7"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    # --- DUYURU YONETIMI ---
    if data == "ap_ann":
        txt, kb = _ann_admin_screen()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("apann_view_"):
        try: aid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        a = db.get_announcement(aid)
        if not a:
            return
        text = (f"<b>#{a['id']} {a['title']}</b>\n"
                f"\U0001f4c5 {str(a['created_at'])[:16].replace('T', ' ')}\n\n"
                f"{render_rich_tokens(render_clickable_tokens(a['body']))}")
        kb = [[InlineKeyboardButton("\U0001f4e3 Gonder (hedef sec)", callback_data=f"apann_send_{aid}")],
              [InlineKeyboardButton("✏️ Baslik", callback_data=f"apanne_title_{aid}"),
               InlineKeyboardButton("✏️ Metin", callback_data=f"apanne_body_{aid}"),
               InlineKeyboardButton("\U0001f5bc Medya", callback_data=f"apanne_media_{aid}")],
              [InlineKeyboardButton("\U0001f5d1 Sil", callback_data=f"apann_del_{aid}")],
              [InlineKeyboardButton("◀️ Duyurular", callback_data="ap_ann")]]
        await q.edit_message_text(text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
        return

    if data.startswith("apann_send_"):
        # Adim 1: HEDEF SECIMI (istek: duyuru belirli kisilere/gruplara atilabilsin)
        try: aid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        a = db.get_announcement(aid)
        if not a:
            await _cb_alert(q, context, "Duyuru bulunamadi (silinmis olabilir).")
            return
        s = db.get_stats()
        siteli = db.count_site_id_records()
        rows = [[InlineKeyboardButton(f"\U0001f30d Herkes ({s['active']})", callback_data=f"apannto_{aid}_all")],
                [InlineKeyboardButton(f"\U0001f194 Site ID bagli uyeler ({siteli})", callback_data=f"apannto_{aid}_siteid")]]
        for k in SEGMENTS:
            rows.append([InlineKeyboardButton(f"{SEGMENTS[k]} ({s['seg'][k]})", callback_data=f"apannto_{aid}_{k}")])
        rows.append([InlineKeyboardButton("\U0001f195 Yeni Uyeler (7g)", callback_data=f"apannto_{aid}_yeni"),
                     InlineKeyboardButton("\U0001f553 Aktif (48s)", callback_data=f"apannto_{aid}_aktif")])
        rows.append([InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data=f"apann_view_{aid}")])
        await q.edit_message_text(box_message("DUYURU HEDEFI",
            f"#{aid} duyurusu KIME gonderilsin? \U0001f447", "\U0001f3af"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return

    if data.startswith("apannto_"):
        # Adim 2: secilen hedefe gonder
        m = re.match(r"^apannto_(\d+)_([a-z0-9]+)$", data)
        if not m:
            return
        aid, hedef = int(m.group(1)), m.group(2)
        if hedef not in ("all", "siteid", "yeni", "aktif") and hedef not in SEGMENTS:
            return
        a = db.get_announcement(aid)
        if not a:
            await _cb_alert(q, context, "Duyuru bulunamadi (silinmis olabilir).")
            return
        # Cift tiklamada duyuru AYNI hedefe iki kez gitmesin (farkli hedef serbest).
        if _cb_throttled(user.id, f"apann_send_{aid}_{hedef}", 30):
            await _cb_alert(q, context, "Gonderim zaten baslatildi; lutfen bekleyin.")
            return
        await q.edit_message_text(box_message("GONDERILIYOR",
            f"Duyuru hedefe iletiliyor: {target_label(hedef)}...", "⏳"),
            parse_mode=ParseMode.HTML)
        # Once sana birebir kopya: kullanici ne goruyorsa aynen bunu gorursun.
        try:
            onizleme = {"type": "photo" if a.get("media_id") else "text", "title": a["title"],
                        "text": a["body"], "media_id": a.get("media_id") or "",
                        "media_type": a.get("media_type") or ""}
            await context.bot.send_message(chat_id=q.message.chat_id,
                text="\U0001f447 KULLANICIYA GIDEN MESAJIN BIREBIR KOPYASI \U0001f447")
            govde = build_payload_text(onizleme)
            if onizleme["media_id"]:
                await context.bot.send_photo(chat_id=q.message.chat_id, photo=onizleme["media_id"],
                    caption=_safe_caption(govde), parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_message(chat_id=q.message.chat_id, text=govde or " ",
                    parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"[DUYURU-ONIZLEME] {e}")
        payload = {"type": "photo" if a.get("media_id") else "text", "title": a["title"],
                   "text": a["body"], "media_id": a.get("media_id") or "",
                   "media_type": a.get("media_type") or ""}
        ok, fail, total, ozet = await deliver_payload(context, payload, hedef)
        db.admin_log(user.id, "announcement_send", f"#{aid} {hedef} ok:{ok}")
        _log_broadcast(f"\U0001f4e2 Duyuru #{aid}", hedef, ok, fail, total, payload, user.id)
        rapor = (f"#{aid} • Hedef: {target_label(hedef)}\n"
                 f"✅ {ok} | ❌ {fail} | \U0001f465 {total}") + (f"\n\n{ozet}" if ozet else "")
        await context.bot.send_message(chat_id=q.message.chat_id,
            text=box_message("DUYURU GONDERILDI", rapor, "\U0001f4e2"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Duyurular", callback_data="ap_ann")]]))
        return

    if data.startswith("apann_del_"):
        try: aid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        db.delete_announcement(aid)
        db.admin_log(user.id, "announcement_delete", f"#{aid}")
        await q.edit_message_text(box_message("SILINDI", f"Duyuru #{aid} silindi.", "\U0001f5d1"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Duyurular", callback_data="ap_ann")]]))
        return

    # --- SSS YONETIMI ---
    if data == "ap_faq":
        txt, kb = _faq_admin_screen()
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=kb)
        return

    if data.startswith("apfaq_view_"):
        try: fid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        f = db.get_faq(fid)
        if not f:
            return
        text = (f"❓ <b>{f['question']}</b>\n\n"
                f"{render_rich_tokens(render_clickable_tokens(f['answer']))}")
        kb = [[InlineKeyboardButton("\U0001f5d1 Sil", callback_data=f"apfaq_del_{fid}")],
              [InlineKeyboardButton("◀️ SSS", callback_data="ap_faq")]]
        await q.edit_message_text(text, parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb), disable_web_page_preview=True)
        return

    if data.startswith("apfaq_del_"):
        try: fid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): return
        db.delete_faq(fid)
        db.admin_log(user.id, "faq_delete", f"#{fid}")
        await q.edit_message_text(box_message("SILINDI", f"Soru #{fid} silindi.", "\U0001f5d1"),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ SSS", callback_data="ap_faq")]]))
        return

    if data == "ap_sched":
        pend = db.get_pending_scheduled()
        kb = []
        for sc in pend[:10]:
            label = f"\U0001f550 #{sc['id']} {str(sc['run_at'])[:16].replace('T',' ')} \u2192 {target_label(sc['target'] or 'all')[:14]}"
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"apsched_view_{sc['id']}")])
        aciklama = ("Bir kayda dokunarak onizleyebilir, zamanini degistirebilir veya iptal edebilirsiniz.\n"
                    f"Gonderimden {SCHED_NOTIFY_MINUTES} dk once onizlemeli hatirlatma alirsiniz."
                    if pend else "Bekleyen zamanli mesaj yok.")
        txt = box_message("ZAMANLI MESAJ", f"Bekleyen: {len(pend)}\n\n{aciklama}", "\U0001f4c5")
        kb.append([InlineKeyboardButton("\U0001f4c5 Yeni Zamanli Mesaj", callback_data="schedgo")])
        kb.append([InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")])
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("apsched_view_"):
        try: sid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): sid = 0
        sc = db.get_scheduled(sid)
        if not sc or sc['status'] != 'bekliyor':
            await _cb_alert(q, context, "Kayit bulunamadi veya artik beklemede degil.")
            return
        try: p = json.loads(sc['payload'])
        except Exception: p = {}
        await q.edit_message_text(box_message("ZAMANLI MESAJ DETAYI", _sched_preview_text(sc, p), "\U0001f4c5"),
            parse_mode=ParseMode.HTML, reply_markup=_sched_manage_kb(sid))
        return

    if data.startswith("apsched_now_"):
        try: sid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): sid = 0
        sc = db.get_scheduled(sid)
        # Atomik kilit: zamanlayici ya da cift tiklama ayni anda gonderemesin.
        if not sc or not db.claim_scheduled(sid):
            await _cb_alert(q, context, "Kayit zaten gonderilmis, gonderiliyor veya iptal edilmis.")
            return
        try:
            p = json.loads(sc['payload'])
            ok, fail, total, ozet = await deliver_payload(context, p, sc['target'])
            db.set_scheduled_status(sid, "gonderildi")
            db.admin_log(user.id, "schedule_send_now", f"#{sid}")
            _log_broadcast(f"\U0001f4c5 Zamanli #{sid} (elle)", sc['target'], ok, fail, total, p, user.id)
            rapor = f"#{sid} elle gonderildi.\n\u2705 {ok} | \u274c {fail} | \U0001f465 {total}" + (f"\n\n{ozet}" if ozet else "")
            await q.edit_message_text(box_message("GONDERILDI", rapor, "\U0001f4e3"),
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
        except Exception as e:
            logger.warning(f"[SCHED-NOW] {sid}: {e}")
            db.set_scheduled_status(sid, "hata")
            await q.edit_message_text(box_message("HATA", f"#{sid} gonderilemedi. Loglari kontrol edin.", "\u274c"),
                parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
        return

    if data.startswith("apsched_del_"):
        try: sid = int(data.rsplit("_", 1)[1])
        except (TypeError, ValueError): sid = 0
        sc = db.get_scheduled(sid)
        # Once atomik sahiplen (bekliyor -> gonderiliyor), sonra iptale cevir;
        # boylece gonderimi baslamis bir kaydin durumu asla ezilmez.
        if not sc or not db.claim_scheduled(sid):
            await _cb_alert(q, context, "Kayit zaten gonderilmis, gonderiliyor veya iptal edilmis.")
            return
        db.set_scheduled_status(sid, "iptal")
        db.admin_log(user.id, "schedule_cancel", f"#{sid}")
        await q.edit_message_text(box_message("IPTAL EDILDI", f"Zamanli mesaj #{sid} iptal edildi; gonderilmeyecek.", "\U0001f5d1"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
        return

    if data == "ap_templates":
        tpls = db.get_templates()
        if not tpls:
            txt = box_message("SABLONLAR", "Kayitli sablon yok.\n\nToplu mesaj sihirbazinda olusturdugun mesaji 'Sablon kaydet' ile saklayabilirsin.", "\U0001f4cb")
            await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
            return
        kb = [[InlineKeyboardButton(f"\U0001f4cb {t['name'][:25]}", callback_data=f"tpl_use_{t['id']}")] for t in tpls[:10]]
        kb.append([InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")])
        await q.edit_message_text(box_message("SABLONLAR", "Kayitli sablonlar. Birini secip gondereblirsin \U0001f447", "\U0001f4cb"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return
    if data.startswith("tpl_use_"):
        try: tid = int(data.replace("tpl_use_", ""))
        except (TypeError, ValueError): return
        await _template_preview(q, context, tid)
        return
    if data.startswith("tpl_send_"):
        try: tid = int(data.replace("tpl_send_", ""))
        except (TypeError, ValueError): return
        # Cift tiklamada ayni toplu gonderim iki kez cikmasin.
        if _cb_throttled(user.id, f"tpl_send_{tid}", 30):
            await _cb_alert(q, context, "Gonderim zaten baslatildi; lutfen bekleyin.")
            return
        await _template_send(q, context, tid)
        return
    if data.startswith("tpl_del_"):
        try: tid = int(data.replace("tpl_del_", ""))
        except (TypeError, ValueError): return
        db.del_template(tid)
        await _cb_alert(q, context, "Sablon silindi.")
        q.data = "ap_templates"; return await admin_cb(update, context)

    if data == "ap_dm":
        txt = box_message("TEKIL MESAJ", "Tek bir kullaniciya ID ile mesaj gondermek icin \U0001f447", "\U0001f4e9")
        kb = [[InlineKeyboardButton("\U0001f4e9 Tekil Mesaj Gonder", callback_data="dmgo")],
              [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_main")]]
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "ap_security":
        ev = db.exe("SELECT COUNT(*) as c FROM security_events WHERE created_at>?", ((datetime.now()-timedelta(hours=24)).isoformat(),))
        cnt = ev[0]['c'] if ev else 0
        txt = box_message("GUVENLIK", (
            f"\u2705 2 katmanli admin girisi (ID + sifre)\n"
            f"\u2705 {MAX_LOGIN_ATTEMPTS} yanlis = {LOGIN_BLOCK_DURATION//60}dk engel\n"
            f"\u2705 Spam: {SPAM_COUNT} mesaj/{SPAM_WINDOW}sn = {TEMP_BAN_MINUTES}dk\n"
            f"\u2705 Ayni komut {SAME_CMD_COUNT}x ardarda = spam\n"
            f"\u2705 {STRIKES_FOR_PERMA} gecici ban = KALICI ban + admin uyarisi\n"
            f"\u2705 HTML/script/SQL/komut temizleme\n"
            f"\u2705 CSV/Excel injection korumasi\n"
            f"\u2705 Path traversal korumasi\n\n"
            f"\U0001f6a8 Son 24s olay: {cnt}\n\n<code>/securitylog</code>"), "\U0001f6e1")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
        return

    if data == "ap_settings":
        txt = box_message("AYARLAR", (
            "<b>Admin:</b>\n<code>/addadmin ID</code>\n<code>/removeadmin ID</code>\n<code>/adminlist</code>\n\n"
            "<b>Loglar:</b>\n<code>/dailylog</code>\n<code>/logfile</code>\n<code>/securitylog</code>\n\n"
            "<b>Yedek:</b>\n<code>/backups</code>\n<code>/backupnow</code>\n\n"
            "<b>Diger:</b>\n<code>/botstatus</code>\n<code>/logout</code>"), "\u2699\ufe0f")
        await q.edit_message_text(txt, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(back))
        return
# =====================================================================
# ORTAK: payload (mesaj icerigi) olusturma ve gonderme
# payload dict: type, title, text, code, code_style, media_id, media_type, btn_text, btn_url
# =====================================================================
import json

def render_clickable_tokens(text):
    """[[Gorunen Yazi|https://adres]] bicimini guvenli Telegram HTML baglantisina cevirir."""
    pattern = re.compile(r"\[\[([^\]|]{1,80})\|(https?://[^\]\s]+)\]\]")
    def repl(match):
        label, url = match.group(1).strip(), match.group(2).strip()
        return f'<a href="{url}">{label}</a>' if is_valid_url(url) else match.group(0)
    return pattern.sub(repl, text or "")

# Vurgu isaretleri -> Telegram HTML. Metin onceden sanitize edildigi icin
# (< > & kacirilmis) yalnizca bizim urettigimiz etiketler HTML olarak kalir.
# Not: Telegram mesajlarda yazi RENGI ve PUNTO BOYUTU desteklemez.
_RICH_TOKEN_RULES = [
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"<b>\1</b>"),
    (re.compile(r"__(.+?)__", re.S), r"<i>\1</i>"),
    # ++ kurali kelimeye bitisik ++'lari (C++ gibi) vurgu saymaz.
    (re.compile(r"(?<![\w+])\+\+(?!\s)(.+?)(?<!\s)\+\+(?![\w+])", re.S), r"<u>\1</u>"),
    (re.compile(r"~~(.+?)~~", re.S), r"<s>\1</s>"),
    (re.compile(r"\|\|(.+?)\|\|", re.S), r"<tg-spoiler>\1</tg-spoiler>"),
]

_HTML_TAG_SPLIT = re.compile(r"(<[^>]*>)")

def render_rich_tokens(text):
    """**kalin**, __italik__, ++alti cizili++, ~~ustu cizili~~, ||gizli|| donusumu.

    Onceden uretilmis HTML etiketlerinin ICINE (or. <a href="...__x__...">)
    dokunmamak icin metin etiket sinirlarindan bolunur ve donusum yalnizca
    etiket disindaki parcalara uygulanir.
    """
    parts = _HTML_TAG_SPLIT.split(text or "")
    for i, part in enumerate(parts):
        if part.startswith("<"):
            continue
        for pat, rep in _RICH_TOKEN_RULES:
            part = pat.sub(rep, part)
        parts[i] = part
    return "".join(parts)

RICH_TEXT_HELP = ("Vurgu: <code>**kalin**</code> <code>__italik__</code> <code>++alti cizili++</code> "
    "<code>~~ustu cizili~~</code> <code>||gizli||</code>\n"
    "Tiklanabilir yazi: <code>[[TIKLA|https://site.com]]</code>\n"
    "<i>Not: Telegram yazi rengi ve punto boyutu desteklemez; kalin + emoji kullanin.</i>")

def _payload_codes(p):
    """Coklu kod destegi: 'codes' listesi; eski kayitlarda tekil 'code' alani."""
    codes = p.get("codes") or ([p["code"]] if p.get("code") else [])
    return [c for c in codes if c]

def build_payload_text(p):
    parts = []
    if p.get("title"): parts.append(f"<b>{p['title']}</b>")
    if p.get("text"): parts.append(render_rich_tokens(render_clickable_tokens(p["text"])))
    codes = _payload_codes(p)
    if p.get("type") in ("promocode", "full") and codes:
        header = "\U0001f381 Promosyon Kodu:" if len(codes) == 1 else "\U0001f381 Promosyon Kodlari:"
        if p.get("code_style") == "copy":
            lines = "\n".join(f"<code>{c}</code>" for c in codes)
        else:
            lines = "\n".join(f"<tg-spoiler>{c}</tg-spoiler>" for c in codes)
        parts.append(f"\n{header}\n{lines}")
    return "\n".join(parts).strip()

def build_payload_kb(p):
    row = []
    if p.get("btn_text") and p.get("btn_url"):
        row.append(InlineKeyboardButton(p["btn_text"], url=p["btn_url"]))
    if p.get("btn2_text") and p.get("btn2_url"):
        row.append(InlineKeyboardButton(p["btn2_text"], url=p["btn2_url"]))
    return InlineKeyboardMarkup([row]) if row else None

def resolve_audience(target):
    if target == "all": return db.get_all_users()
    if target == "active24": return db.get_active_users(24)
    if target == "siteid": return db.get_siteid_users()
    if target in AUTO_SEGMENTS: return _campaign_audience(target)
    if isinstance(target, str) and target.startswith("ids:"):
        return db.get_users_by_site_ids(target[4:].split(","))
    return db.get_users_by_segment(target)

def target_label(t):
    if t == "all": return "Herkes"
    if t == "active24": return "Son 24s aktif"
    if t == "siteid": return "\U0001f194 Site ID bagli uyeler"
    if t in AUTO_SEGMENTS: return AUTO_SEGMENTS[t]
    if isinstance(t, str) and t.startswith("ids:"):
        adet = len([x for x in t[4:].split(",") if x])
        return f"\U0001f194 Site ID listesi ({adet} ID)"
    return SEGMENTS.get(t, t)

async def _kitle_gonder(users, send_one):
    """Ortak toplu gonderim dongusu.

    Hatalari turune gore sayar ve loglar; flood limitinde (RetryAfter)
    bekleyip bir kez daha dener. Donus: (ok, fail, ozet_metni).
    "Forbidden" = kullanici botu engellemis YA DA bu bota hic Start basmamis
    (token degisiminden kalan eski kayitlar dahil) — bot hata degil, Telegram kurali.
    """
    from telegram.error import Forbidden, BadRequest, RetryAfter
    ok = engelli = icerik = diger = 0
    for u in users:
        uid = u["user_id"]
        try:
            try:
                await send_one(uid)
            except RetryAfter as e:
                await asyncio.sleep(min(float(getattr(e, "retry_after", 1)) + 0.5, 35))
                await send_one(uid)
            ok += 1
        except Forbidden:
            engelli += 1
            logger.info(f"[GONDERIM] {uid}: botu engellemis veya hic baslatmamis")
        except BadRequest as e:
            icerik += 1
            logger.warning(f"[GONDERIM] {uid}: icerik/istek hatasi: {e}")
        except Exception as e:
            diger += 1
            logger.warning(f"[GONDERIM] {uid}: {type(e).__name__}: {e}")
        await asyncio.sleep(0.04)
    parcalar = []
    if engelli: parcalar.append(f"\U0001f6ab {engelli} kisi botu engellemis ya da hic baslatmamis")
    if icerik:  parcalar.append(f"⚠️ {icerik} gonderimde icerik hatasi (detay: bot.log)")
    if diger:   parcalar.append(f"❗ {diger} baska hata (detay: bot.log)")
    return ok, engelli + icerik + diger, "\n".join(parcalar)

def _log_broadcast(kind, target, ok, fail, total, payload=None, admin_id=0):
    """Her toplu gonderimi gecmis tablosuna isler (panel: Gonderim Gecmisi)."""
    try:
        pj = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else (payload or "")
        db.add_broadcast_log(kind, str(target), ok, fail, total, pj[:8000], admin_id)
    except Exception as e:
        logger.warning(f"[GECMIS] kayit yazilamadi: {e}")

async def deliver_payload(context, payload, target):
    users = resolve_audience(target)
    body = build_payload_text(payload)
    kb = build_payload_kb(payload)
    media_id = payload.get("media_id") or payload.get("image_id")
    if not body.strip() and not media_id:
        # Bos icerigi Telegram her alici icin reddeder; hic denemeden bildir.
        return 0, 0, len(users), ("⚠️ Bu kaydin icerigi BOS (eski surum hatasi olabilir). "
                                  "Kaydi silip yeniden olusturun.")

    # Medya altindaki yazi (caption) Telegram'da 1024 karakterle sinirli;
    # asilirsa Telegram HER aliciyi reddeder. Emniyetli kisalt.
    caption = _safe_caption(body) if body else None

    async def _tek(uid):
        if media_id and payload.get("media_type") == "video":
            await context.bot.send_video(chat_id=uid, video=media_id,
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif media_id:
            await context.bot.send_photo(chat_id=uid, photo=media_id,
                caption=caption, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=uid, text=body or " ",
                parse_mode=ParseMode.HTML, reply_markup=kb)

    ok, fail, ozet = await _kitle_gonder(users, _tek)
    # Banli kullanicilar hedef listesine HIC girmez; admin bunu bilsin ki
    # "kullaniciya bildirim dusmedi" durumunda neden aranmasin.
    try:
        banli = db.exe("SELECT COUNT(*) c FROM users WHERE is_banned=1")[0]["c"]
        if banli:
            not_satiri = f"\U0001f6b7 {banli} banli kullanici kapsam disi (listele: /banlist, kaldir: /unban ID)"
            ozet = f"{ozet}\n{not_satiri}" if ozet else not_satiri
    except Exception:
        pass
    return ok, fail, len(users), ozet

# =====================================================================
# TOPLU MESAJ SIHIRBAZI
# =====================================================================
(BC_TYPE, BC_TITLE, BC_TEXT, BC_CODE_STYLE, BC_CODE, BC_IMAGE,
 BC_BTN_TEXT, BC_BTN_URL, BC_TARGET, BC_CONFIRM, BC_EDIT_PICK) = range(60, 71)
BC_BTN2_ASK, BC_BTN2_TEXT, BC_BTN2_URL = 71, 72, 73

def _bc_reset(context):
    # Onceki sihirbazdan kalan bayraklar yeni akisi etkilemesin.
    context.user_data.pop("bc_sched", None)
    context.user_data.pop("bc_editing", None)
    context.user_data["bc"] = {"type":None,"title":None,"text":None,"code":None,
        "codes":[], "code_style":None,"media_id":None,"media_type":None,"image_id":None,
        "btn_text":None,"btn_url":None,"btn2_text":None,"btn2_url":None,"target":None}

def _bc_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4dd Sadece Metin", callback_data="bctype_text")],
        [InlineKeyboardButton("\U0001f5bc Foto/Video + Metin", callback_data="bctype_photo")],
        [InlineKeyboardButton("\U0001f3ac Foto/Video + Metin + Buton", callback_data="bctype_photobtn")],
        [InlineKeyboardButton("\U0001f3ab Metin + Promo Kod + Buton", callback_data="bctype_promocode")],
        [InlineKeyboardButton("\U0001f9e9 Tam Paket (Medya+Kod+Buton)", callback_data="bctype_full")],
        [InlineKeyboardButton("❌ Iptal", callback_data="bc_cancel")],
    ])

async def bc_start_cmd(update, context):
    uid = update.effective_user.id
    if not is_authenticated(uid):
        return ConversationHandler.END
    if _wizard_busy(context, "bc"):
        await update.message.reply_text(box_message("MESGUL", "Once acik sihirbazi /iptal ile kapatin.", "⚠️"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    _wizard_lock(context, "bc")
    _bc_reset(context)
    await update.message.reply_text(box_message("TOPLU MESAJ", "Ne tur mesaj? \U0001f447", "\U0001f4e3"), parse_mode=ParseMode.HTML, reply_markup=_bc_type_keyboard())
    return BC_TYPE

async def bc_start_cb(update, context):
    # Panelden "bcgo" butonu ile baslatma
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "bc"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "bc")
    _bc_reset(context)
    await q.edit_message_text(box_message("TOPLU MESAJ", "Ne tur mesaj? \U0001f447", "\U0001f4e3"), parse_mode=ParseMode.HTML, reply_markup=_bc_type_keyboard())
    return BC_TYPE

async def _del_user_msg(update):
    # Admin girdi mesajini sil (temiz sohbet akisi)
    try: await update.message.delete()
    except: pass

def _editing(context):
    return context.user_data.pop("bc_editing", None)

async def bc_type_pick(update, context):
    q = update.callback_query; await q.answer()
    bc = context.user_data.get("bc")
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    bc["type"] = {"bctype_text":"text","bctype_photo":"photo","bctype_photobtn":"photobtn",
                  "bctype_promocode":"promocode","bctype_full":"full"}[q.data]
    await q.edit_message_text(box_message("ADIM: BASLIK", "Mesajin <b>basligini</b> yazin.\n\n<i>Baslik istemiyorsaniz /atla</i>\n<i>Iptal: /iptal</i>", "\U0001f516"), parse_mode=ParseMode.HTML)
    return BC_TITLE

async def bc_title_step(update, context):
    bc = context.user_data.get("bc")
    t = sanitize_input(update.message.text or "", 80)
    await _del_user_msg(update)
    if not t:
        await update.effective_chat.send_message(box_message("HATA","Bos olamaz, tekrar yazin veya /atla.","\u274c"), parse_mode=ParseMode.HTML); return BC_TITLE
    bc["title"] = t
    if _editing(context): return await _bc_reshow(update, context)
    await update.effective_chat.send_message(box_message("\u2705 Baslik kaydedildi",f"Simdi <b>mesaj metnini</b> yazin.\n\n{RICH_TEXT_HELP}\n<i>Iptal: /iptal</i>","\U0001f4dd"), parse_mode=ParseMode.HTML)
    return BC_TEXT

async def bc_title_skip(update, context):
    bc = context.user_data.get("bc"); bc["title"] = None
    await _del_user_msg(update)
    if _editing(context): return await _bc_reshow(update, context)
    await update.effective_chat.send_message(box_message("ADIM: MESAJ",f"Mesaj metnini yazin.\n\n{RICH_TEXT_HELP}\n<i>Iptal: /iptal</i>","\U0001f4dd"), parse_mode=ParseMode.HTML)
    return BC_TEXT

async def bc_text_step(update, context):
    bc = context.user_data.get("bc")
    txt = sanitize_input(update.message.text or "", MAX_BROADCAST_LENGTH)
    await _del_user_msg(update)
    if not txt:
        await update.effective_chat.send_message(box_message("HATA","Bos mesaj olmaz.","\u274c"), parse_mode=ParseMode.HTML); return BC_TEXT
    bc["text"] = txt
    if _editing(context): return await _bc_reshow(update, context)
    if bc["type"] in ("photo","photobtn","full"):
        await update.effective_chat.send_message(box_message("\u2705 Metin kaydedildi","Simdi <b>foto veya videoyu</b> gonderin.\n\n<i>Iptal: /iptal</i>","\U0001f5bc"), parse_mode=ParseMode.HTML)
        return BC_IMAGE
    if bc["type"] == "promocode":
        await update.effective_chat.send_message(box_message("\u2705 Metin kaydedildi","Promo kod nasil gorunsun?\n\n\U0001f4cb Kopyalanabilir: dokununca kopyalanir.\n\U0001f648 Gizli: ustune gelince/dokununca okunur.","\U0001f3ab"), parse_mode=ParseMode.HTML, reply_markup=_code_style_keyboard(bc))
        return BC_CODE_STYLE
    return await _bc_ask_target(update.effective_chat, context)

def _code_style_keyboard(bc):
    rows = [[InlineKeyboardButton("\U0001f4cb Kopyalanabilir kod", callback_data="bcstyle_copy")],
            [InlineKeyboardButton("\U0001f648 Gizli (ustune gelince gorunur)", callback_data="bcstyle_spoiler")]]
    if bc.get("type") == "full":
        rows.append([InlineKeyboardButton("\u23ed Kodsuz devam", callback_data="bcstyle_skip")])
    rows.append([InlineKeyboardButton("\u274c Iptal", callback_data="bc_cancel")])
    return InlineKeyboardMarkup(rows)

async def bc_code_style_pick(update, context):
    q = update.callback_query; await q.answer()
    bc = context.user_data.get("bc")
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    if q.data == "bcstyle_skip":
        # Tam pakette kod istege bagli: kod adimini atla, butona gec.
        bc["codes"] = []; bc["code"] = None
        await q.edit_message_text(box_message("ADIM: BUTON","1. butonun <b>yazisini</b> girin.\n\n<i>Buton istemiyorsaniz /atla</i>\n<i>Iptal: /iptal</i>","\U0001f518"), parse_mode=ParseMode.HTML)
        return BC_BTN_TEXT
    bc["code_style"] = "copy" if q.data == "bcstyle_copy" else "spoiler"
    await q.edit_message_text(box_message("ADIM: PROMO KOD",
        "Promo kod(lar)i yazin. Birden fazla kod icin virgul veya ayri satir kullanin (en fazla 5).\n\n"
        "<i>Ornek: HIT250</i>\n<i>Ornek: VIP100, GOLD50</i>\n<i>Iptal: /iptal</i>","\U0001f3ab"), parse_mode=ParseMode.HTML)
    return BC_CODE

async def bc_code_step(update, context):
    bc = context.user_data.get("bc")
    raw = update.message.text or ""
    await _del_user_msg(update)
    codes = []
    for part in re.split(r"[,\n]+", raw):
        c = sanitize_input(part.strip(), MAX_CODE_LENGTH)
        if c:
            codes.append(c)
    codes = codes[:5]
    if not codes:
        await update.effective_chat.send_message(box_message("HATA","Kod bos olamaz.","\u274c"), parse_mode=ParseMode.HTML); return BC_CODE
    bc["codes"] = codes
    bc["code"] = codes[0]
    if _editing(context): return await _bc_reshow(update, context)
    kod_ozet = ", ".join(codes)
    await update.effective_chat.send_message(box_message("\u2705 Kod kaydedildi",f"Kod(lar): <code>{kod_ozet}</code>\n\n1. butonun <b>yazisini</b> girin.\n\n<i>Buton istemiyorsaniz /atla</i>\n<i>Iptal: /iptal</i>","\U0001f518"), parse_mode=ParseMode.HTML)
    return BC_BTN_TEXT

async def bc_image_step(update, context):
    bc = context.user_data.get("bc")
    if update.message.video:
        bc["media_id"] = update.message.video.file_id
        bc["media_type"] = "video"
        bc["image_id"] = None
    elif update.message.photo:
        bc["media_id"] = update.message.photo[-1].file_id
        bc["media_type"] = "photo"
        bc["image_id"] = bc["media_id"]
    else:
        await update.effective_chat.send_message(box_message("HATA","Lutfen foto veya video gonderin.","\u274c"), parse_mode=ParseMode.HTML); return BC_IMAGE
    await _del_user_msg(update)
    if _editing(context): return await _bc_reshow(update, context)
    if bc["type"] == "photobtn":
        await update.effective_chat.send_message(box_message("\u2705 Medya kaydedildi","1. butonun <b>yazisini</b> girin.\n\n<i>Iptal: /iptal</i>","\U0001f518"), parse_mode=ParseMode.HTML)
        return BC_BTN_TEXT
    if bc["type"] == "full":
        await update.effective_chat.send_message(box_message("\u2705 Medya kaydedildi","Promo kod nasil gorunsun?\n\n\U0001f4cb Kopyalanabilir: dokununca kopyalanir.\n\U0001f648 Gizli: dokununca okunur.","\U0001f3ab"), parse_mode=ParseMode.HTML, reply_markup=_code_style_keyboard(bc))
        return BC_CODE_STYLE
    return await _bc_ask_target(update.effective_chat, context)

async def bc_btn_text_step(update, context):
    bc = context.user_data.get("bc")
    t = sanitize_input(update.message.text or "", 60)
    await _del_user_msg(update)
    if not t:
        await update.effective_chat.send_message(box_message("HATA","Bos olamaz.","\u274c"), parse_mode=ParseMode.HTML); return BC_BTN_TEXT
    bc["btn_text"] = t
    if _editing(context): return await _bc_reshow(update, context)
    await update.effective_chat.send_message(box_message("\u2705 Buton yazisi kaydedildi","Butonun <b>URL</b>'sini girin (https://).\n\n<i>Iptal: /iptal</i>","\U0001f517"), parse_mode=ParseMode.HTML)
    return BC_BTN_URL

async def bc_btn_skip(update, context):
    """Tam pakette buton istege bagli: /atla ile butonsuz devam edilir."""
    bc = context.user_data.get("bc")
    bc["btn_text"] = None; bc["btn_url"] = None
    bc["btn2_text"] = None; bc["btn2_url"] = None
    await _del_user_msg(update)
    if _editing(context): return await _bc_reshow(update, context)
    return await _bc_ask_target(update.effective_chat, context)

async def bc_btn_url_step(update, context):
    bc = context.user_data.get("bc")
    url = (update.message.text or "").strip()
    await _del_user_msg(update)
    if not is_valid_url(url):
        await update.effective_chat.send_message(box_message("HATA","Gecersiz URL! https:// ile baslamali.","\u274c"), parse_mode=ParseMode.HTML); return BC_BTN_URL
    bc["btn_url"] = url
    if _editing(context): return await _bc_reshow(update, context)
    # Istege bagli ikinci buton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2795 Ikinci Buton Ekle", callback_data="bcbtn2_add"),
         InlineKeyboardButton("\u23ed Devam", callback_data="bcbtn2_skip")],
        [InlineKeyboardButton("\u274c Iptal", callback_data="bc_cancel")]])
    await update.effective_chat.send_message(box_message("\u2705 1. buton kaydedildi","Ikinci bir buton eklemek ister misiniz?\n\nIki buton yan yana gorunur.","\U0001f518"), parse_mode=ParseMode.HTML, reply_markup=kb)
    return BC_BTN2_ASK

async def bc_btn2_ask_pick(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    if q.data == "bcbtn2_skip":
        bc = context.user_data.get("bc")
        bc["btn2_text"] = None; bc["btn2_url"] = None
        if context.user_data.get("bc_editing"):
            context.user_data.pop("bc_editing", None)
            return await _bc_preview(q, context)
        return await _bc_ask_target(q.message.chat, context)
    await q.edit_message_text(box_message("ADIM: 2. BUTON","Ikinci butonun <b>yazisini</b> girin.\n\n<i>Iptal: /iptal</i>","\U0001f518"), parse_mode=ParseMode.HTML)
    return BC_BTN2_TEXT

async def bc_btn2_text_step(update, context):
    bc = context.user_data.get("bc")
    t = sanitize_input(update.message.text or "", 60)
    await _del_user_msg(update)
    if not t:
        await update.effective_chat.send_message(box_message("HATA","Bos olamaz.","\u274c"), parse_mode=ParseMode.HTML); return BC_BTN2_TEXT
    bc["btn2_text"] = t
    if _editing(context): return await _bc_reshow(update, context)
    await update.effective_chat.send_message(box_message("\u2705 2. buton yazisi kaydedildi","Ikinci butonun <b>URL</b>'sini girin (https://).\n\n<i>Iptal: /iptal</i>","\U0001f517"), parse_mode=ParseMode.HTML)
    return BC_BTN2_URL

async def bc_btn2_url_step(update, context):
    bc = context.user_data.get("bc")
    url = (update.message.text or "").strip()
    await _del_user_msg(update)
    if not is_valid_url(url):
        await update.effective_chat.send_message(box_message("HATA","Gecersiz URL! https:// ile baslamali.","\u274c"), parse_mode=ParseMode.HTML); return BC_BTN2_URL
    bc["btn2_url"] = url
    if _editing(context): return await _bc_reshow(update, context)
    return await _bc_ask_target(update.effective_chat, context)

def _klavye_korumali(state):
    """Sihirbaz METIN adimi sargisi: kalici alt klavyedeki bir menu tusuna
    (admin veya kullanici) yanlislikla basildiysa metni ICERIK olarak almaz;
    uyarir ve ayni adimda bekler. Kacis her zaman /iptal."""
    def sar(fn):
        @wraps(fn)
        async def w(update, context):
            raw = (getattr(update.message, "text", "") or "").strip()
            if raw and len(raw) <= 40 and (_match_admin_label(raw.lower()) or _match_menu_label(raw.lower())):
                await update.message.reply_text(box_message("SIHIRBAZ ACIK",
                    f"'{sanitize_input(raw, 40)}' bir menu tusu; icerik olarak ALINMADI.\n"
                    "Istenen bilgiyi yazin ya da /iptal ile cikin.", "\U0001f9ed"),
                    parse_mode=ParseMode.HTML)
                return state
            return await fn(update, context)
        return w
    return sar

async def _bc_ask_target(chat, context):
    s = db.get_stats()
    siteli = db.count_site_id_records()
    rows = [[InlineKeyboardButton(f"\U0001f30d Herkes ({s['active']})", callback_data="bctarget_all")],
            [InlineKeyboardButton(f"\U0001f194 Site ID bagli uyeler ({siteli})", callback_data="bctarget_siteid")],
            [InlineKeyboardButton("\U0001f3af Belirli Site ID listesi", callback_data="bctarget_idlist")],
            [InlineKeyboardButton(f"\U0001f553 Son 24s ({s['active24']})", callback_data="bctarget_active24")]]
    for k in SEGMENTS:
        rows.append([InlineKeyboardButton(f"{SEGMENTS[k]} ({s['seg'][k]})", callback_data=f"bctarget_{k}")])
    rows.append([InlineKeyboardButton("\U0001f195 Yeni Uyeler (7g)", callback_data="bctarget_yeni"),
                 InlineKeyboardButton("\U0001f553 Aktif (48s)", callback_data="bctarget_aktif")])
    rows.append([InlineKeyboardButton("\u274c Iptal", callback_data="bc_cancel")])
    await chat.send_message(box_message("ADIM: HEDEF KITLE","Bu mesaj kime gitsin? \U0001f447","\U0001f3af"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
    return BC_TARGET

BC_IDLIST = 74

async def bc_target_pick(update, context):
    q = update.callback_query; await q.answer()
    bc = context.user_data.get("bc")
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    if q.data == "bctarget_idlist":
        await q.edit_message_text(box_message("ADIM: SITE ID LISTESI",
            "Hedef uyelerin <b>Site ID</b>'lerini yazin (bosluk veya virgulle ayirin).\n"
            "Ornek: <code>12345 67890 24680</code>\n\n<i>Iptal: /iptal</i>", "\U0001f194"),
            parse_mode=ParseMode.HTML)
        return BC_IDLIST
    bc["target"] = q.data.replace("bctarget_","")
    # Zamanli mesaj modundaysak preview yerine zaman sor
    if context.user_data.get("bc_sched"):
        return await sched_after_target(update, context)
    return await _bc_preview(q, context)

async def bc_idlist_step(update, context):
    """Site ID listesi girisi: dogrula, esles, hedefi kur."""
    bc = context.user_data.get("bc")
    if bc is None:
        return ConversationHandler.END
    ham = re.split(r"[\s,;]+", (update.message.text or "").strip())
    site_ids, gecersiz = [], []
    for parca in ham:
        if not parca:
            continue
        v = validate_site_id(parca)
        (site_ids if v else gecersiz).append(v or parca[:20])
    site_ids = list(dict.fromkeys(site_ids))[:500]
    if not site_ids:
        await update.message.reply_text(box_message("HATA",
            "Gecerli Site ID bulunamadi. Ornek: <code>12345 67890</code>", "\u274c"),
            parse_mode=ParseMode.HTML)
        return BC_IDLIST
    eslesen = db.get_users_by_site_ids(site_ids)
    bulunan_idler = set()
    for u in eslesen:
        r = db.get_site_id_record(u["user_id"])
        if r:
            bulunan_idler.add(r["site_id"].lower())
    eksik, banli = [], []
    for s_id in site_ids:
        if s_id.lower() in bulunan_idler:
            continue
        (banli if db.find_by_site_id(s_id) else eksik).append(s_id)
    if not eslesen:
        await update.message.reply_text(box_message("ESLESME YOK",
            "Bu Site ID'lerle bota bagli uye bulunamadi.\n"
            "Uyeler once /profil uzerinden Site ID'lerini baglamis olmali.\n\n"
            "Yeniden deneyin veya /iptal yazin.", "\u26a0\ufe0f"), parse_mode=ParseMode.HTML)
        return BC_IDLIST
    bc["target"] = "ids:" + ",".join(sorted(bulunan_idler))
    ozet = f"\u2705 {len(eslesen)} uye eslesti."
    if eksik:
        ozet += f"\n\u26a0\ufe0f Bota bagli olmayan {len(eksik)} ID atlandi: {', '.join(eksik[:10])}"
    if banli:
        ozet += f"\n\U0001f6b7 Banli oldugu icin atlanan {len(banli)} ID: {', '.join(banli[:10])} (/unban ile acilir)"
    await update.message.reply_text(box_message("HEDEF KURULDU", ozet, "\U0001f194"), parse_mode=ParseMode.HTML)
    if context.user_data.get("bc_sched"):
        await update.message.reply_text(box_message("ADIM: ZAMAN",
            "Gonderim zamanini girin.\n\nBicim: <code>GG.AA.YYYY SS:DD</code>\nOrnek: <code>15.06.2026 20:30</code>\n\n<i>Iptal: /iptal</i>", "\U0001f550"),
            parse_mode=ParseMode.HTML)
        return SCHED_WAIT_WHEN
    class Shim:
        def __init__(self, m): self.message = m
    return await _bc_preview(Shim(update.message), context)

async def _bc_preview(q, context):
    bc = context.user_data.get("bc")
    body = build_payload_text(bc)
    media_id = bc.get("media_id") or bc.get("image_id")
    btn_info = bc.get('btn_text') or 'Yok'
    if bc.get('btn2_text'):
        btn_info += f" + {bc['btn2_text']}"
    kodlar = ", ".join(_payload_codes(bc)) or "Yok"
    info = (f"<b>Tip:</b> {bc['type']} | <b>Hedef:</b> {target_label(bc['target'])}\n"
            f"<b>Medya:</b> {bc.get('media_type') if media_id else 'Yok'} | "
            f"<b>Buton:</b> {btn_info} | <b>Kod:</b> {kodlar}")
    if media_id and body and len(body) > 1024:
        info += "\n\n⚠️ Medyali mesajlarda aciklama en fazla 1024 karakter olabilir; metni kisaltin yoksa gonderim basarisiz olur."
    chat_id = q.message.chat_id
    await context.bot.send_message(chat_id=chat_id, text=box_message("ONIZLEME","Asagidaki gibi gidecek \U0001f447\n\n"+info,"\U0001f441"), parse_mode=ParseMode.HTML)
    kb = build_payload_kb(bc)
    try:
        media_id = bc.get("media_id") or bc.get("image_id")
        if media_id and bc.get("media_type") == "video":
            await context.bot.send_video(chat_id=chat_id, video=media_id, caption=body or None, parse_mode=ParseMode.HTML, reply_markup=kb)
        elif media_id:
            await context.bot.send_photo(chat_id=chat_id, photo=media_id, caption=body or None, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            await context.bot.send_message(chat_id=chat_id, text=body or "(bos)", parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Onizleme hatasi: {e}")
    confirm = InlineKeyboardMarkup([
        [InlineKeyboardButton("\u2705 Onayla ve Gonder", callback_data="bc_confirm")],
        [InlineKeyboardButton("\U0001f4cb Sablon Olarak Kaydet", callback_data="bc_savetpl")],
        [InlineKeyboardButton("\u270f\ufe0f Duzenle", callback_data="bc_edit")],
        [InlineKeyboardButton("\u274c Iptal", callback_data="bc_cancel")]])
    await context.bot.send_message(chat_id=chat_id, text="\U0001f446 Onayliyor musunuz?", reply_markup=confirm)
    return BC_CONFIRM

async def _bc_reshow(update, context):
    class Shim:
        def __init__(self, m): self.message = m
    return await _bc_preview(Shim(update.message), context)

async def bc_confirm_pick(update, context):
    q = update.callback_query; await q.answer()
    uid = update.effective_user.id
    # Oturum sihirbaz icinde dolmus/kapatilmis olabilir; yetkisiz gonderime izin verme.
    if not is_authenticated(uid):
        try: await q.edit_message_text(box_message("OTURUM DOLDU", "Gonderim YAPILMADI. /admin ile giris yapip yeniden deneyin.", "\u23f3"), parse_mode=ParseMode.HTML)
        except Exception: pass
        _wizard_unlock(context)
        context.user_data.pop("bc", None)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    bc = context.user_data.get("bc")
    if not bc:
        try: await q.edit_message_text(box_message("SURESI GECTI", "Bu onay ekrani eski. /bildirim ile yeniden baslayin.", "\u26a0\ufe0f"), parse_mode=ParseMode.HTML)
        except Exception: pass
        _wizard_unlock(context)
        return ConversationHandler.END
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    if q.data == "bc_savetpl":
        # Sablon olarak kaydet
        name = (bc.get("title") or bc.get("text") or "Sablon")[:30]
        db.add_template(name, json.dumps(bc))
        await _cb_alert(q, context, "\U0001f4cb Sablon kaydedildi.")
        return BC_CONFIRM
    if q.data == "bc_confirm":
        if _cb_throttled(uid, "bc_confirm", 30):
            await _cb_alert(q, context, "Gonderim zaten baslatildi; lutfen bekleyin.")
            return BC_CONFIRM
        await q.edit_message_text(box_message("GONDERILIYOR","Lutfen bekleyin...","\u23f3"), parse_mode=ParseMode.HTML)
        ok, fail, total, ozet = await deliver_payload(context, bc, bc["target"])
        rapor = f"Hedef: {target_label(bc['target'])}\n\u2705 Basarili: {ok}\n\u274c Basarisiz: {fail}" + (f"\n\n{ozet}" if ozet else "")
        await context.bot.send_message(chat_id=q.message.chat_id, text=box_message("TAMAMLANDI",
            rapor, "\U0001f389"), parse_mode=ParseMode.HTML)
        db.admin_log(update.effective_user.id, "broadcast", f"{bc['type']} {bc['target']} ok:{ok}")
        _log_broadcast("\U0001f4e3 Toplu mesaj", bc.get("target") or "all", ok, fail, total,
                       {k: v for k, v in bc.items() if k != "image_id"}, update.effective_user.id)
        _wizard_unlock(context)
        context.user_data.pop("bc", None)
        context.user_data.pop("bc_editing", None)
        context.user_data.pop("bc_sched", None)
        return ConversationHandler.END
    if q.data == "bc_edit":
        bc = context.user_data.get("bc")
        rows = [[InlineKeyboardButton("\U0001f516 Baslik", callback_data="bcedit_title")],
                [InlineKeyboardButton("\U0001f4dd Metin", callback_data="bcedit_text")]]
        if bc["type"] in ("promocode","full"):
            rows += [[InlineKeyboardButton("\U0001f3ab Kod(lar)", callback_data="bcedit_code")]]
        if bc["type"] in ("photo","photobtn","full"):
            rows += [[InlineKeyboardButton("\U0001f3ac Foto / Video", callback_data="bcedit_image")]]
        if bc["type"] in ("photobtn","promocode","full"):
            rows += [[InlineKeyboardButton("\U0001f518 Buton yazisi", callback_data="bcedit_btntext"),
                      InlineKeyboardButton("\U0001f517 Buton linki", callback_data="bcedit_btnurl")]]
        if bc.get("btn2_text"):
            rows += [[InlineKeyboardButton("\U0001f518 2. buton yazisi", callback_data="bcedit_btn2text"),
                      InlineKeyboardButton("\U0001f517 2. buton linki", callback_data="bcedit_btn2url")]]
        rows.append([InlineKeyboardButton("\U0001f3af Hedef", callback_data="bcedit_target")])
        rows.append([InlineKeyboardButton("\u274c Iptal", callback_data="bc_cancel")])
        await q.edit_message_text(box_message("DUZENLE","Hangi kismi degistireceksiniz?","\u270f\ufe0f"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return BC_EDIT_PICK

async def bc_edit_pick(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "bc_cancel": return await bc_cancel_cb(update, context)
    field = q.data.replace("bcedit_","")
    if field == "target":
        # Hedef secimi kendi callback akisiyla ilerler; bc_editing bayragi
        # birakilirsa bir SONRAKI sihirbazi yarim onizlemeye atlatir.
        return await _bc_ask_target(q.message.chat, context)
    context.user_data["bc_editing"] = field
    prompts = {
        "title":("ADIM: BASLIK","Yeni basligi yazin (veya /atla).","\U0001f516",BC_TITLE),
        "text":("ADIM: METIN",f"Yeni metni yazin.\n\n{RICH_TEXT_HELP}","\U0001f4dd",BC_TEXT),
        "code":("ADIM: KOD","Yeni promo kod(lar)i yazin (virgul ile coklu).","\U0001f3ab",BC_CODE),
        "btntext":("ADIM: BUTON YAZISI","Yeni buton yazisini girin.","\U0001f518",BC_BTN_TEXT),
        "btnurl":("ADIM: BUTON LINKI","Yeni URL girin (https://).","\U0001f517",BC_BTN_URL),
        "btn2text":("ADIM: 2. BUTON YAZISI","Ikinci butonun yeni yazisini girin.","\U0001f518",BC_BTN2_TEXT),
        "btn2url":("ADIM: 2. BUTON LINKI","Ikinci buton icin yeni URL girin (https://).","\U0001f517",BC_BTN2_URL),
        "image":("ADIM: MEDYA","Yeni foto veya video gonderin.","\U0001f5bc",BC_IMAGE)}
    if field not in prompts:
        return BC_EDIT_PICK
    title, body, emoji, state = prompts[field]
    await q.edit_message_text(box_message(title, f"{body}\n\n<i>Iptal: /iptal</i>", emoji), parse_mode=ParseMode.HTML)
    return state

async def bc_cancel_cmd(update, context):
    _wizard_unlock(context)
    context.user_data.pop("bc", None); context.user_data.pop("bc_editing", None)
    context.user_data.pop("bc_sched", None)
    await update.message.reply_text(box_message("IPTAL","Toplu mesaj iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def bc_cancel_cb(update, context):
    q = update.callback_query
    _wizard_unlock(context)
    context.user_data.pop("bc", None); context.user_data.pop("bc_editing", None)
    context.user_data.pop("bc_sched", None)
    try: await q.edit_message_text(box_message("IPTAL","Toplu mesaj iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    except: await context.bot.send_message(chat_id=q.message.chat_id, text=box_message("IPTAL","Iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# =====================================================================
# SABLON kullan / gonder
# =====================================================================
async def _template_preview(q, context, tid):
    t = db.get_template(tid)
    if not t:
        await q.answer("Sablon yok.", show_alert=True); return
    try: p = json.loads(t['payload'])
    except: p = {}
    body = build_payload_text(p)
    await q.edit_message_text(box_message(f"SABLON: {t['name']}", body or "(bos)", "\U0001f4cb"), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("\U0001f4e3 Herkese Gonder", callback_data=f"tpl_send_{tid}")],
            [InlineKeyboardButton("\U0001f5d1 Sil", callback_data=f"tpl_del_{tid}")],
            [InlineKeyboardButton("\u25c0\ufe0f Geri", callback_data="ap_templates")]]))

async def _template_send(q, context, tid):
    t = db.get_template(tid)
    if not t:
        await q.answer("Sablon yok.", show_alert=True); return
    try: p = json.loads(t['payload'])
    except: p = {}
    await q.edit_message_text(box_message("GONDERILIYOR","Lutfen bekleyin...","\u23f3"), parse_mode=ParseMode.HTML)
    ok, fail, total, ozet = await deliver_payload(context, p, p.get("target") or "all")
    rapor = f"\u2705 {ok} | \u274c {fail}" + (f"\n\n{ozet}" if ozet else "")
    await context.bot.send_message(chat_id=q.message.chat_id, text=box_message("TAMAMLANDI", rapor, "\U0001f389"), parse_mode=ParseMode.HTML)
    db.admin_log(q.from_user.id, "template_send", t['name'])
    _log_broadcast(f"\U0001f4cb Sablon: {t['name'][:24]}", p.get("target") or "all", ok, fail, total, p, q.from_user.id)

# =====================================================================
# KAMPANYA / DUYURU / SSS YONETIM SIHIRBAZLARI
# =====================================================================
# Ayni anda iki admin sihirbazi acilirsa metinler yanlis sihirbaza gider;
# tek seferde tek sihirbaza izin veren hafif kilit.
def _wizard_busy(context, name):
    info = context.user_data.get("wizard_lock")
    if not info:
        return False
    n, ts = info
    return n != name and (time.time() - ts) < 610

def _wizard_lock(context, name):
    context.user_data["wizard_lock"] = (name, time.time())

def _wizard_unlock(context):
    context.user_data.pop("wizard_lock", None)

def _camp_admin_detail_text(c):
    seg = CAMPAIGN_SEGMENT_LABEL(c["segment"]) if c["segment"] else "\U0001f30d Herkes"
    exp = c["expires_at"].replace("T", " ")[:16] if c["expires_at"] else "Suresiz"
    now_iso = datetime.now().isoformat(timespec="seconds")
    if c["active"]:
        durum = "✅ Aktif"
    elif c["expires_at"] and c["expires_at"] <= now_iso:
        durum = "⌛ Suresi doldu (otomatik kaldirildi)"
    else:
        durum = "⏸ Pasif"
    lines = [f"<b>#{c['id']} {sanitize_input(c['title'], 120)}</b>",
             f"\U0001f3f7 Kategori: {CAMPAIGN_CATEGORIES.get(c['category'], c['category'])}",
             f"\U0001f4ca Durum: {durum}",
             f"\U0001f3af Hedef: {seg}",
             f"\U0001f550 Bitis: {exp}"]
    if c.get("prize_pool"):
        lines.append(f"\U0001f3c6 Odul: {sanitize_input(c['prize_pool'], 100)}")
    if c.get("btn_text"):
        lines.append(f"\U0001f518 Buton: {sanitize_input(c['btn_text'], 40)}")
    if c.get("media_id"):
        lines.append(f"\U0001f5bc Medya: {c.get('media_type') or 'photo'}")
    if c.get("body"):
        ozet = sanitize_input(c["body"], 200)
        lines.append(f"\n{ozet}{'…' if len(c['body']) > 200 else ''}")
    return box_message("KAMPANYA DETAYI", "\n".join(lines), "\U0001f3af")

def _camp_admin_detail_kb(c):
    rows = [[InlineKeyboardButton("👁 Onizle", callback_data=f"apc_prev_{c['id']}")],
            [InlineKeyboardButton("✏️ Baslik", callback_data=f"apce_title_{c['id']}"),
             InlineKeyboardButton("✏️ Metin", callback_data=f"apce_body_{c['id']}")],
            [InlineKeyboardButton("\U0001f550 Bitis", callback_data=f"apce_expires_{c['id']}"),
             InlineKeyboardButton("\U0001f518 Buton", callback_data=f"apce_btn_{c['id']}")]]
    if c["category"] == "turnuva":
        rows.append([InlineKeyboardButton("\U0001f3c6 Odul", callback_data=f"apce_prize_{c['id']}"),
                     InlineKeyboardButton("\U0001f4cb Sartlar", callback_data=f"apce_cond_{c['id']}")])
    rows.append([InlineKeyboardButton("\U0001f3f7 Segment", callback_data=f"apc_seg_{c['id']}")])
    rows.append([InlineKeyboardButton("⏸ Pasife Al" if c["active"] else "▶️ Aktif Et",
                                      callback_data=f"apc_toggle_{c['id']}"),
                 InlineKeyboardButton("\U0001f5d1 Sil", callback_data=f"apc_delask_{c['id']}")])
    rows.append([InlineKeyboardButton("◀️ Liste", callback_data=f"apc_list_{c['category']}")])
    return InlineKeyboardMarkup(rows)

(CAMP_CAT, CAMP_TITLE, CAMP_BODY, CAMP_MEDIA, CAMP_BTN,
 CAMP_PRIZE, CAMP_COND, CAMP_EXPIRES) = range(330, 338)
CAMP_EDIT_WAIT = 345
ANN_TITLE, ANN_BODY, ANN_MEDIA = 350, 351, 352
FAQ_Q, FAQ_A = 360, 361

async def camp_new_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "camp_new"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "camp_new")
    context.user_data["camp"] = {}
    rows = [[InlineKeyboardButton(label, callback_data=f"campcat_{k}")]
            for k, label in CAMPAIGN_CATEGORIES.items()]
    rows.append([InlineKeyboardButton("❌ Iptal", callback_data="camp_cancel")])
    await q.edit_message_text(box_message("YENI KAMPANYA", "Kategori secin \U0001f447", "➕"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
    return CAMP_CAT

async def camp_new_start_cmd(update, context):
    """/kampanyaekle: kampanya sihirbazini komutla baslatir."""
    if not is_authenticated(update.effective_user.id):
        return ConversationHandler.END
    if _wizard_busy(context, "camp_new"):
        await update.message.reply_text(box_message("MESGUL", "Once acik sihirbazi /iptal ile kapatin.", "⚠️"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    _wizard_lock(context, "camp_new")
    context.user_data["camp"] = {}
    rows = [[InlineKeyboardButton(label, callback_data=f"campcat_{k}")]
            for k, label in CAMPAIGN_CATEGORIES.items()]
    rows.append([InlineKeyboardButton("❌ Iptal", callback_data="camp_cancel")])
    await update.message.reply_text(box_message("YENI KAMPANYA", "Kategori secin \U0001f447", "➕"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
    return CAMP_CAT

async def camp_cat_pick(update, context):
    q = update.callback_query; await q.answer()
    if q.data == "camp_cancel":
        _wizard_unlock(context)
        context.user_data.pop("camp", None)
        await q.edit_message_text(box_message("IPTAL", "Kampanya olusturma iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    key = q.data.replace("campcat_", "")
    if key not in CAMPAIGN_CATEGORIES:
        return CAMP_CAT
    context.user_data["camp"] = {"category": key}
    await q.edit_message_text(box_message("ADIM: BASLIK",
        f"{CAMPAIGN_CATEGORIES[key]} icin kampanya <b>basligini</b> yazin.\n\n<i>Iptal: /iptal</i>", "\U0001f516"),
        parse_mode=ParseMode.HTML)
    return CAMP_TITLE

async def camp_title_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    t = sanitize_input(update.message.text or "", 120)
    if not t:
        await update.message.reply_text(box_message("HATA", "Baslik bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_TITLE
    camp["title"] = t
    await update.message.reply_text(box_message("✅ Baslik kaydedildi",
        f"Kampanya <b>aciklamasini</b> yazin.\n\n{RICH_TEXT_HELP}\n<i>Aciklamasiz: /atla | Iptal: /iptal</i>", "\U0001f4dd"),
        parse_mode=ParseMode.HTML)
    return CAMP_BODY

async def camp_body_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    camp["body"] = sanitize_input(update.message.text or "", 900)
    return await _camp_ask_media(update, context)

async def camp_body_skip(update, context):
    camp = context.user_data.setdefault("camp", {})
    camp["body"] = ""
    return await _camp_ask_media(update, context)

async def _camp_ask_media(update, context):
    await update.message.reply_text(box_message("ADIM: MEDYA",
        "Kampanya <b>foto/videosunu</b> gonderin.\n\n<i>Medyasiz: /atla | Iptal: /iptal</i>", "\U0001f5bc"),
        parse_mode=ParseMode.HTML)
    return CAMP_MEDIA

async def camp_media_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    if update.message.video:
        camp["media_id"], camp["media_type"] = update.message.video.file_id, "video"
    elif update.message.photo:
        camp["media_id"], camp["media_type"] = update.message.photo[-1].file_id, "photo"
    else:
        await update.message.reply_text(box_message("HATA", "Foto/video gonderin veya /atla.", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_MEDIA
    return await _camp_ask_btn(update, context)

async def camp_media_skip(update, context):
    return await _camp_ask_btn(update, context)

async def _camp_ask_btn(update, context):
    await update.message.reply_text(box_message("ADIM: BUTON",
        "Buton icin <code>yazi | https://link</code> bicimini kullanin.\n"
        "<i>Ornek:</i> <code>Hemen Katil | https://site.com/kampanya</code>\n\n"
        "<i>Butonsuz: /atla | Iptal: /iptal</i>", "\U0001f518"), parse_mode=ParseMode.HTML)
    return CAMP_BTN

def _parse_btn_pair(raw):
    if "|" not in raw:
        return None
    text, url = raw.split("|", 1)
    text, url = sanitize_input(text.strip(), 40), url.strip()
    if not text or not is_valid_url(url):
        return None
    return text, url

async def camp_btn_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    pair = _parse_btn_pair(update.message.text or "")
    if not pair:
        await update.message.reply_text(box_message("HATA",
            "Bicim: <code>yazi | https://link</code> (veya /atla)", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_BTN
    camp["btn_text"], camp["btn_url"] = pair
    return await _camp_after_btn(update, context)

async def camp_btn_skip(update, context):
    return await _camp_after_btn(update, context)

async def _camp_after_btn(update, context):
    camp = context.user_data.setdefault("camp", {})
    if camp.get("category") == "turnuva":
        await update.message.reply_text(box_message("ADIM: ODUL HAVUZU",
            "Turnuva <b>odul havuzunu</b> yazin (or. 500.000 TL).\n\n<i>Atla: /atla | Iptal: /iptal</i>", "\U0001f3c6"),
            parse_mode=ParseMode.HTML)
        return CAMP_PRIZE
    return await _camp_ask_expires(update, context)

async def camp_prize_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    camp["prize_pool"] = sanitize_input(update.message.text or "", 120)
    await update.message.reply_text(box_message("ADIM: KATILIM SARTLARI",
        "Turnuvanin <b>katilim sartlarini</b> yazin.\n\n<i>Atla: /atla | Iptal: /iptal</i>", "\U0001f4cb"),
        parse_mode=ParseMode.HTML)
    return CAMP_COND

async def camp_prize_skip(update, context):
    await update.message.reply_text(box_message("ADIM: KATILIM SARTLARI",
        "Turnuvanin <b>katilim sartlarini</b> yazin.\n\n<i>Atla: /atla | Iptal: /iptal</i>", "\U0001f4cb"),
        parse_mode=ParseMode.HTML)
    return CAMP_COND

async def camp_cond_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    camp["conditions"] = sanitize_input(update.message.text or "", 500)
    return await _camp_ask_expires(update, context)

async def camp_cond_skip(update, context):
    return await _camp_ask_expires(update, context)

async def _camp_ask_expires(update, context):
    await update.message.reply_text(box_message("ADIM: BITIS ZAMANI",
        "Kampanya ne zaman bitsin?\n\nBicim: <code>GG.AA.YYYY SS:DD</code>\n"
        "Ornek: <code>20.08.2026 23:59</code>\n\n"
        "Suresi dolunca OTOMATIK yayindan kalkar; son gun ve son 2 saat kala kullanicilara bildirim gider.\n\n"
        "<i>Suresiz: /atla | Iptal: /iptal</i>", "\U0001f550"), parse_mode=ParseMode.HTML)
    return CAMP_EXPIRES

async def camp_expires_step(update, context):
    camp = context.user_data.setdefault("camp", {})
    raw = (update.message.text or "").strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except ValueError:
        await update.message.reply_text(box_message("HATA", "Bicim: 20.08.2026 23:59 (veya /atla)", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_EXPIRES
    if dt <= datetime.now():
        await update.message.reply_text(box_message("HATA", "Gecmis bir zaman olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_EXPIRES
    camp["expires_at"] = dt.isoformat(timespec="seconds")
    return await _camp_save(update, context)

async def camp_expires_skip(update, context):
    return await _camp_save(update, context)

async def _camp_save(update, context):
    _wizard_unlock(context)
    camp = context.user_data.pop("camp", None) or {}
    if not is_authenticated(update.effective_user.id):
        await update.message.reply_text(box_message("OTURUM DOLDU", "Kampanya KAYDEDILMEDI. /admin ile giris yapin.", "\u23f3"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if not camp.get("title") or not camp.get("category"):
        await update.message.reply_text(box_message("HATA", "Eksik bilgi; /iptal ile cikip yeniden deneyin.", "❌"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    cid = db.add_campaign(camp["category"], camp["title"], camp.get("body", ""),
        camp.get("media_id", ""), camp.get("media_type", ""), camp.get("btn_text", ""),
        camp.get("btn_url", ""), camp.get("segment", ""), camp.get("prize_pool", ""),
        camp.get("conditions", ""), camp.get("expires_at", ""))
    db.admin_log(update.effective_user.id, "campaign_add", f"#{cid} {camp['category']}")
    c = db.get_campaign(cid)
    notify_kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        "\U0001f4e3 'Yeni Kampanya Basladi' Bildirimi Gonder", callback_data=f"apc_notify_{cid}")]])
    await update.message.reply_text(box_message("KAMPANYA OLUSTURULDU",
        f"✅ #{cid} yayinda! Kullanicilar Ana Menu → {CAMPAIGN_CATEGORIES[camp['category']]} altinda gorecek.\n\n"
        f"Hedef kitleye simdi haber vermek istersen \U0001f447", "\U0001f389"),
        parse_mode=ParseMode.HTML, reply_markup=notify_kb)
    await update.message.reply_text(_camp_admin_detail_text(c), parse_mode=ParseMode.HTML,
        reply_markup=_camp_admin_detail_kb(c))
    return ConversationHandler.END

async def camp_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("camp", None)
    await update.message.reply_text(box_message("IPTAL", "Kampanya olusturma iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- Kampanya alan duzenleme (tek adimlik) ---
CAMP_EDIT_FIELDS = {
    "title":   ("Baslik", "Yeni basligi yazin.", "title"),
    "body":    ("Metin", "Yeni aciklamayi yazin.", "body"),
    "expires": ("Bitis", "Yeni bitis: <code>GG.AA.YYYY SS:DD</code>\nSuresiz yapmak icin /temizle", "expires_at"),
    "btn":     ("Buton", "Yeni buton: <code>yazi | https://link</code>\nButonu kaldirmak icin /temizle", "btn_text"),
    "prize":   ("Odul Havuzu", "Yeni odul havuzunu yazin.", "prize_pool"),
    "cond":    ("Katilim Sartlari", "Yeni sartlari yazin.", "conditions"),
}

async def camp_edit_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "camp_edit"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    m = re.match(r"^apce_([a-z]+)_(\d+)$", q.data or "")
    if not m or m.group(1) not in CAMP_EDIT_FIELDS:
        return ConversationHandler.END
    field, cid = m.group(1), int(m.group(2))
    if not db.get_campaign(cid):
        await _cb_alert(q, context, "Kampanya bulunamadi (silinmis olabilir).")
        return ConversationHandler.END
    _wizard_lock(context, "camp_edit")
    context.user_data["camp_edit"] = (field, cid)
    title, desc, _col = CAMP_EDIT_FIELDS[field]
    await q.edit_message_text(box_message(f"DEGISTIR: {title}", f"{desc}\n\n<i>Iptal: /iptal</i>", "✏️"),
        parse_mode=ParseMode.HTML)
    return CAMP_EDIT_WAIT

async def _camp_edit_finish(update, context, cid):
    _wizard_unlock(context)
    c = db.get_campaign(cid)
    if c:
        await update.message.reply_text(_camp_admin_detail_text(c), parse_mode=ParseMode.HTML,
            reply_markup=_camp_admin_detail_kb(c))
    return ConversationHandler.END

async def camp_edit_save(update, context):
    uid = update.effective_user.id
    if not is_authenticated(uid):
        _wizard_unlock(context)
        context.user_data.pop("camp_edit", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Degisiklik KAYDEDILMEDI. /admin ile giris yapin.", "⏳"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    info = context.user_data.get("camp_edit")
    if not info:
        _wizard_unlock(context)
        return ConversationHandler.END
    field, cid = info
    raw = (update.message.text or "").strip()
    if field == "expires":
        try:
            dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
        except ValueError:
            await update.message.reply_text(box_message("HATA", "Bicim: 20.08.2026 23:59 (veya /temizle)", "❌"), parse_mode=ParseMode.HTML)
            return CAMP_EDIT_WAIT
        if dt <= datetime.now():
            await update.message.reply_text(box_message("HATA", "Gecmis bir zaman olamaz.", "❌"), parse_mode=ParseMode.HTML)
            return CAMP_EDIT_WAIT
        db.update_campaign_field(cid, "expires_at", dt.isoformat(timespec="seconds"))
        db.set_campaign_active(cid, True)
    elif field == "btn":
        pair = _parse_btn_pair(raw)
        if not pair:
            await update.message.reply_text(box_message("HATA", "Bicim: <code>yazi | https://link</code> (veya /temizle)", "❌"), parse_mode=ParseMode.HTML)
            return CAMP_EDIT_WAIT
        db.update_campaign_field(cid, "btn_text", pair[0])
        db.update_campaign_field(cid, "btn_url", pair[1])
    else:
        limits = {"title": 120, "body": 900, "prize": 120, "cond": 500}
        val = sanitize_input(raw, limits.get(field, 300))
        if not val:
            await update.message.reply_text(box_message("HATA", "Bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
            return CAMP_EDIT_WAIT
        db.update_campaign_field(cid, CAMP_EDIT_FIELDS[field][2], val)
    db.admin_log(update.effective_user.id, "campaign_edit", f"#{cid} {field}")
    context.user_data.pop("camp_edit", None)
    return await _camp_edit_finish(update, context, cid)

async def camp_edit_clear(update, context):
    info = context.user_data.get("camp_edit")
    if not info:
        return ConversationHandler.END
    field, cid = info
    if field == "expires":
        db.update_campaign_field(cid, "expires_at", "")
    elif field == "btn":
        db.update_campaign_field(cid, "btn_text", "")
        db.update_campaign_field(cid, "btn_url", "")
    else:
        await update.message.reply_text(box_message("HATA", "Bu alan /temizle ile bosaltilamaz.", "❌"), parse_mode=ParseMode.HTML)
        return CAMP_EDIT_WAIT
    db.admin_log(update.effective_user.id, "campaign_clear", f"#{cid} {field}")
    context.user_data.pop("camp_edit", None)
    return await _camp_edit_finish(update, context, cid)

async def camp_edit_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("camp_edit", None)
    await update.message.reply_text(box_message("IPTAL", "Degisiklik iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- Duyuru olusturma ---
async def ann_new_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "ann_new"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "ann_new")
    context.user_data["ann"] = {}
    await q.edit_message_text(box_message("YENI DUYURU", "Duyuru <b>basligini</b> yazin.\n\n<i>Iptal: /iptal</i>", "\U0001f4e2"),
        parse_mode=ParseMode.HTML)
    return ANN_TITLE

async def ann_new_start_cmd(update, context):
    """/duyuruekle: duyuru sihirbazini komutla baslatir."""
    if not is_authenticated(update.effective_user.id):
        return ConversationHandler.END
    if _wizard_busy(context, "ann_new"):
        await update.message.reply_text(box_message("MESGUL", "Once acik sihirbazi /iptal ile kapatin.", "⚠️"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    _wizard_lock(context, "ann_new")
    context.user_data["ann"] = {}
    await update.message.reply_text(box_message("YENI DUYURU", "Duyuru <b>basligini</b> yazin.\n\n<i>Iptal: /iptal</i>", "\U0001f4e2"),
        parse_mode=ParseMode.HTML)
    return ANN_TITLE

async def ann_title_step(update, context):
    ann = context.user_data.setdefault("ann", {})
    t = sanitize_input(update.message.text or "", 120)
    if not t:
        await update.message.reply_text(box_message("HATA", "Baslik bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return ANN_TITLE
    ann["title"] = t
    await update.message.reply_text(box_message("✅ Baslik kaydedildi",
        f"Duyuru <b>metnini</b> yazin.\n\n{RICH_TEXT_HELP}\n<i>Iptal: /iptal</i>", "\U0001f4dd"), parse_mode=ParseMode.HTML)
    return ANN_BODY

async def ann_body_step(update, context):
    ann = context.user_data.setdefault("ann", {})
    body = sanitize_input(update.message.text or "", 1500)
    if not body:
        await update.message.reply_text(box_message("HATA", "Metin bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return ANN_BODY
    ann["body"] = body
    await update.message.reply_text(box_message("ADIM: MEDYA",
        "Duyuruya <b>foto/video</b> ekleyebilirsiniz.\n\n<i>Medyasiz: /atla | Iptal: /iptal</i>", "\U0001f5bc"),
        parse_mode=ParseMode.HTML)
    return ANN_MEDIA

async def _ann_save(update, context):
    _wizard_unlock(context)
    ann = context.user_data.pop("ann", None) or {}
    if not is_authenticated(update.effective_user.id):
        await update.message.reply_text(box_message("OTURUM DOLDU", "Duyuru KAYDEDILMEDI. /admin ile giris yapin.", "\u23f3"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if not (ann.get("title") or "").strip() or not (ann.get("body") or "").strip():
        await update.message.reply_text(box_message("HATA",
            "Baslik/metin kaybolmus; duyuru KAYDEDILMEDI. /duyuruekle ile yeniden deneyin.", "❌"),
            parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    aid = db.add_announcement(ann.get("title", ""), ann.get("body", ""),
        ann.get("media_id", ""), ann.get("media_type", ""))
    db.admin_log(update.effective_user.id, "announcement_add", f"#{aid}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4e3 Gonder (hedef sec)", callback_data=f"apann_send_{aid}")],
        [InlineKeyboardButton("◀️ Duyurular", callback_data="ap_ann")]])
    await update.message.reply_text(box_message("DUYURU KAYDEDILDI",
        f"✅ #{aid} kullanicilarin Duyurular bolumune eklendi.\n\nIstersen simdi herkese de gonderebilirsin \U0001f447", "\U0001f4e2"),
        parse_mode=ParseMode.HTML, reply_markup=kb)
    return ConversationHandler.END

async def ann_media_step(update, context):
    ann = context.user_data.setdefault("ann", {})
    if update.message.video:
        ann["media_id"], ann["media_type"] = update.message.video.file_id, "video"
    elif update.message.photo:
        ann["media_id"], ann["media_type"] = update.message.photo[-1].file_id, "photo"
    else:
        await update.message.reply_text(box_message("HATA", "Foto/video gonderin veya /atla.", "❌"), parse_mode=ParseMode.HTML)
        return ANN_MEDIA
    return await _ann_save(update, context)

async def ann_media_skip(update, context):
    return await _ann_save(update, context)

async def ann_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("ann", None)
    await update.message.reply_text(box_message("IPTAL", "Duyuru iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END


# --- Duyuru alan duzenleme (tek adimlik) ---
ANN_EDIT_WAIT = 353

async def ann_edit_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "ann_edit"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    m = re.match(r"^apanne_(title|body|media)_(\d+)$", q.data or "")
    if not m:
        return ConversationHandler.END
    field, aid = m.group(1), int(m.group(2))
    if not db.get_announcement(aid):
        await _cb_alert(q, context, "Duyuru bulunamadi (silinmis olabilir).")
        return ConversationHandler.END
    _wizard_lock(context, "ann_edit")
    context.user_data["ann_edit"] = (field, aid)
    if field == "media":
        istem = "Yeni <b>foto/video</b> gonderin.\n\n<i>Medyayi kaldirmak icin /temizle | Iptal: /iptal</i>"
    elif field == "title":
        istem = f"Yeni <b>basligi</b> yazin.\n\n<i>Iptal: /iptal</i>"
    else:
        istem = f"Yeni <b>metni</b> yazin.\n\n{RICH_TEXT_HELP}\n<i>Iptal: /iptal</i>"
    await q.edit_message_text(box_message("DUYURU DUZENLE", istem, "✏️"), parse_mode=ParseMode.HTML)
    return ANN_EDIT_WAIT

async def _ann_edit_finish(update, context, aid):
    _wizard_unlock(context)
    context.user_data.pop("ann_edit", None)
    a = db.get_announcement(aid)
    baslik = _plain_label((a or {}).get("title") or "?", 40)
    await update.message.reply_text(box_message("GUNCELLENDI",
        f"✅ Duyuru #{aid} guncellendi: <b>{sanitize_input(baslik, 60)}</b>\n"
        f"Kullanici listesinde ANINDA yeni haliyle gorunur.", "✏️"),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\U0001f441 Duyuruyu Gor", callback_data=f"apann_view_{aid}"),
                                            InlineKeyboardButton("◀️ Duyurular", callback_data="ap_ann")]]))
    return ConversationHandler.END

async def ann_edit_save(update, context):
    uid = update.effective_user.id
    if not is_authenticated(uid):
        _wizard_unlock(context)
        context.user_data.pop("ann_edit", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Degisiklik KAYDEDILMEDI. /admin ile giris yapin.", "⏳"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    info = context.user_data.get("ann_edit")
    if not info:
        _wizard_unlock(context)
        return ConversationHandler.END
    field, aid = info
    if field == "media":
        if update.message.video:
            db.update_announcement_field(aid, "media_id", update.message.video.file_id)
            db.update_announcement_field(aid, "media_type", "video")
        elif update.message.photo:
            db.update_announcement_field(aid, "media_id", update.message.photo[-1].file_id)
            db.update_announcement_field(aid, "media_type", "photo")
        else:
            await update.message.reply_text(box_message("HATA", "Foto/video gonderin, /temizle veya /iptal.", "❌"), parse_mode=ParseMode.HTML)
            return ANN_EDIT_WAIT
    else:
        deger = sanitize_input(update.message.text or "", 120 if field == "title" else 1500)
        if not deger:
            await update.message.reply_text(box_message("HATA", "Bos olamaz; tekrar yazin veya /iptal.", "❌"), parse_mode=ParseMode.HTML)
            return ANN_EDIT_WAIT
        db.update_announcement_field(aid, field, deger)
    db.admin_log(uid, "announcement_edit", f"#{aid} {field}")
    return await _ann_edit_finish(update, context, aid)

async def ann_edit_clear(update, context):
    """/temizle: yalnizca medya alaninda gecerli — duyuruyu metin-only yapar."""
    info = context.user_data.get("ann_edit")
    if not info:
        _wizard_unlock(context)
        return ConversationHandler.END
    field, aid = info
    if field != "media":
        await update.message.reply_text(box_message("HATA", "Bu alan bosaltilamaz; yeni deger yazin veya /iptal.", "❌"), parse_mode=ParseMode.HTML)
        return ANN_EDIT_WAIT
    db.update_announcement_field(aid, "media_id", "")
    db.update_announcement_field(aid, "media_type", "")
    db.admin_log(update.effective_user.id, "announcement_edit", f"#{aid} media temizlendi")
    return await _ann_edit_finish(update, context, aid)

async def ann_edit_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("ann_edit", None)
    await update.message.reply_text(box_message("IPTAL", "Duzenleme iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- SSS olusturma ---
async def faq_new_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "faq_new"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "faq_new")
    context.user_data["faq"] = {}
    await q.edit_message_text(box_message("YENI SORU", "<b>Soruyu</b> yazin.\n\n<i>Iptal: /iptal</i>", "❓"),
        parse_mode=ParseMode.HTML)
    return FAQ_Q

async def faq_q_step(update, context):
    faq = context.user_data.setdefault("faq", {})
    qtext = sanitize_input(update.message.text or "", 200)
    if not qtext:
        await update.message.reply_text(box_message("HATA", "Soru bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return FAQ_Q
    faq["q"] = qtext
    await update.message.reply_text(box_message("✅ Soru kaydedildi",
        f"Simdi <b>cevabini</b> yazin.\n\n{RICH_TEXT_HELP}\n<i>Iptal: /iptal</i>", "\U0001f4dd"), parse_mode=ParseMode.HTML)
    return FAQ_A

async def faq_a_step(update, context):
    faq = context.user_data.pop("faq", None) or {}
    ans = sanitize_input(update.message.text or "", 1500)
    if not ans:
        context.user_data["faq"] = faq
        await update.message.reply_text(box_message("HATA", "Cevap bos olamaz.", "❌"), parse_mode=ParseMode.HTML)
        return FAQ_A
    if not is_authenticated(update.effective_user.id):
        _wizard_unlock(context)
        context.user_data.pop("faq", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Soru KAYDEDILMEDI. /admin ile giris yapin.", "\u23f3"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if not (faq.get("q") or "").strip():
        context.user_data["faq"] = faq
        await update.message.reply_text(box_message("HATA",
            "Soru metni kaybolmus; once <b>soruyu</b> yazin.", "❌"), parse_mode=ParseMode.HTML)
        return FAQ_Q
    _wizard_unlock(context)
    fid = db.add_faq(faq.get("q", ""), ans)
    db.admin_log(update.effective_user.id, "faq_add", f"#{fid}")
    await update.message.reply_text(box_message("SSS EKLENDI",
        f"✅ #{fid} kullanicilarin SSS bolumune eklendi.", "❓"), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ SSS Yonetimi", callback_data="ap_faq")]]))
    return ConversationHandler.END

async def faq_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("faq", None)
    await update.message.reply_text(box_message("IPTAL", "Soru ekleme iptal edildi.", "❌"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# =====================================================================
# ZAMANLI MESAJ SIHIRBAZI (mevcut toplu mesaj payload'i + zaman)
# =====================================================================
SCHED_WAIT_WHEN = 80

async def sched_start_cb(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "bc"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "bc")
    await q.edit_message_text(box_message("ZAMANLI MESAJ","Once mesaji hazirlayalim. Tip secin \U0001f447","\U0001f4c5"), parse_mode=ParseMode.HTML)
    _bc_reset(context)
    context.user_data["bc_sched"] = True
    await context.bot.send_message(chat_id=q.message.chat_id, text=box_message("TIP SEC","Ne tur mesaj? \U0001f447","\U0001f4e3"), parse_mode=ParseMode.HTML, reply_markup=_bc_type_keyboard())
    return BC_TYPE

# Zamanli modda hedef secilince zaman sorulur (preview yerine)
async def sched_after_target(update, context):
    # bc_target_pick icinde sched bayragi varsa buraya yonlenir
    q = update.callback_query
    await q.edit_message_text(box_message("ADIM: ZAMAN","Gonderim zamanini girin.\n\nBicim: <code>GG.AA.YYYY SS:DD</code>\nOrnek: <code>15.06.2026 20:30</code>\n\n<i>Iptal: /iptal</i>","\U0001f550"), parse_mode=ParseMode.HTML)
    return SCHED_WAIT_WHEN

async def sched_when_step(update, context):
    uid = update.effective_user.id
    if not is_authenticated(uid):
        _wizard_unlock(context)
        context.user_data.pop("bc", None); context.user_data.pop("bc_sched", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Zamanli mesaj KURULMADI. /admin ile giris yapin.", "⏳"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    bc = context.user_data.get("bc")
    if not bc:
        _wizard_unlock(context)
        await update.message.reply_text(box_message("SURESI GECTI", "Sihirbaz durumu bulunamadi. /zamanla ile yeniden baslayin.", "⚠️"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    raw = (update.message.text or "").strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except:
        await update.message.reply_text(box_message("HATA","Hatali bicim. Ornek: 15.06.2026 20:30","\u274c"), parse_mode=ParseMode.HTML)
        return SCHED_WAIT_WHEN
    if dt <= datetime.now():
        await update.message.reply_text(box_message("HATA","Gecmis bir zaman olamaz.","\u274c"), parse_mode=ParseMode.HTML)
        return SCHED_WAIT_WHEN
    body = build_payload_text(bc)
    if (bc.get("media_id") or bc.get("image_id")) and body and len(body) > 1024:
        await update.message.reply_text(box_message("HATA",
            "Medyali mesajlarda aciklama en fazla 1024 karakter olabilir; bu haliyle gonderim tum alicilarda basarisiz olur.\n\n/iptal yazip metni kisaltarak yeniden kurun.","\u26a0\ufe0f"), parse_mode=ParseMode.HTML)
        return SCHED_WAIT_WHEN
    sid = db.add_scheduled(json.dumps(bc), bc.get("target") or "all", dt.isoformat())
    db.admin_log(update.effective_user.id, "schedule_add", f"#{sid} {raw}")
    _wizard_unlock(context)
    context.user_data.pop("bc", None); context.user_data.pop("bc_sched", None)
    await update.message.reply_text(box_message("KURULDU",
        f"\u2705 Zamanli mesaj #{sid} kuruldu.\n\U0001f550 {raw}\n\U0001f3af {target_label(bc.get('target') or 'all')}\n\n"
        f"\U0001f514 Gonderimden {SCHED_NOTIFY_MINUTES} dk once onizlemeli hatirlatma alacaksiniz.\n"
        f"Yonetim: /admin \u2192 Zamanli Mesaj", "\U0001f4c5"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# --- Zamanli mesajin saatini degistirme (panel: \ud83d\udd50 Zaman\u0131 De\u011fi\u015ftir) ---
SCHED_TIME_WAIT = 85

async def sched_time_start(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        if update.effective_user.id in ADMIN_IDS:
            await q.answer("Oturum suresi doldu. /admin ile yeniden giris yapin.", show_alert=True)
        else:
            await q.answer()
        return ConversationHandler.END
    await q.answer()
    try: sid = int(q.data.rsplit("_", 1)[1])
    except (TypeError, ValueError): return ConversationHandler.END
    sc = db.get_scheduled(sid)
    if not sc or sc['status'] != 'bekliyor':
        await q.edit_message_text(box_message("BULUNAMADI", "Kayit beklemede degil.", "\u274c"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
        return ConversationHandler.END
    if _wizard_busy(context, "sched_time"):
        await _cb_alert(q, context, "Once acik sihirbazi /iptal ile kapatin.")
        return ConversationHandler.END
    _wizard_lock(context, "sched_time")
    context.user_data["sched_time_sid"] = sid
    await q.edit_message_text(box_message("YENI ZAMAN",
        f"#{sid} icin yeni gonderim zamanini girin.\n\nBicim: <code>GG.AA.YYYY SS:DD</code>\nOrnek: <code>15.08.2026 20:30</code>\n\n<i>Iptal: /iptal</i>", "\U0001f550"),
        parse_mode=ParseMode.HTML)
    return SCHED_TIME_WAIT

async def sched_time_save(update, context):
    sid = context.user_data.get("sched_time_sid")
    if not sid:
        return ConversationHandler.END
    raw = (update.message.text or "").strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except ValueError:
        await update.message.reply_text(box_message("HATA", "Hatali bicim. Ornek: 15.08.2026 20:30", "\u274c"), parse_mode=ParseMode.HTML)
        return SCHED_TIME_WAIT
    if dt <= datetime.now():
        await update.message.reply_text(box_message("HATA", "Gecmis bir zaman olamaz.", "\u274c"), parse_mode=ParseMode.HTML)
        return SCHED_TIME_WAIT
    sc = db.get_scheduled(sid)
    if not sc or sc['status'] != 'bekliyor':
        _wizard_unlock(context)
        context.user_data.pop("sched_time_sid", None)
        await update.message.reply_text(box_message("GUNCELLENEMEDI", f"#{sid} bu arada gonderilmis veya iptal edilmis.", "\u274c"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
        return ConversationHandler.END
    db.update_scheduled_time(sid, dt.isoformat())
    db.admin_log(update.effective_user.id, "schedule_retime", f"#{sid} {raw}")
    _wizard_unlock(context)
    context.user_data.pop("sched_time_sid", None)
    await update.message.reply_text(box_message("GUNCELLENDI", f"\u2705 #{sid} yeni zamani: {raw}\nHatirlatma yeniden kurulacak.", "\U0001f550"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")]]))
    return ConversationHandler.END

async def sched_time_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("sched_time_sid", None)
    await update.message.reply_text(box_message("IPTAL", "Zaman degisikligi iptal edildi.", "\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

# =====================================================================
# TEKIL MESAJ SIHIRBAZI (ID ile tek kullaniciya)
# =====================================================================
DM_WAIT_ID, DM_WAIT_TEXT = 90, 91

async def dm_start_cb(update, context):
    q = update.callback_query
    if not is_authenticated(update.effective_user.id):
        await q.answer()
        return ConversationHandler.END
    if _wizard_busy(context, "dm"):
        await q.answer("Once acik sihirbazi /iptal ile kapatin.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    _wizard_lock(context, "dm")
    await q.edit_message_text(box_message("TEKIL MESAJ","Hedef kullanicinin <b>ID</b>'sini girin.\n\n<i>Iptal: /iptal</i>","\U0001f4e9"), parse_mode=ParseMode.HTML)
    return DM_WAIT_ID

async def dm_id_step(update, context):
    raw = (update.message.text or "").strip()
    if not is_valid_id(raw):
        await update.message.reply_text(box_message("HATA","Gecersiz ID. Tekrar girin.","\u274c"), parse_mode=ParseMode.HTML)
        return DM_WAIT_ID
    context.user_data["dm_target"] = int(raw)
    await update.message.reply_text(box_message("ADIM: MESAJ","Gonderilecek <b>mesaji</b> yazin.\n\n<i>Iptal: /iptal</i>","\U0001f4dd"), parse_mode=ParseMode.HTML)
    return DM_WAIT_TEXT

async def dm_text_step(update, context):
    uid = update.effective_user.id
    if not is_authenticated(uid):
        _wizard_unlock(context)
        context.user_data.pop("dm_target", None)
        await update.message.reply_text(box_message("OTURUM DOLDU", "Mesaj GONDERILMEDI. /admin ile giris yapin.", "⏳"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if ADMIN_SESSION_TIMEOUT > 0:
        authenticated_admins[uid] = time.time()
    target = context.user_data.get("dm_target")
    text = sanitize_input(update.message.text or "", MAX_BROADCAST_LENGTH)
    if not text:
        await update.message.reply_text(box_message("HATA","Bos olamaz.","\u274c"), parse_mode=ParseMode.HTML); return DM_WAIT_TEXT
    try:
        await context.bot.send_message(chat_id=target, text=text, parse_mode=ParseMode.HTML)
        await update.message.reply_text(box_message("GONDERILDI", f"\u2705 <code>{target}</code> kullanicisina iletildi.","\U0001f4e9"), parse_mode=ParseMode.HTML)
        db.admin_log(update.effective_user.id, "dm", str(target))
    except Exception as e:
        # Ham hata metni <>& icerebilir; HTML'i bozup kilidi sizdirmasin.
        try:
            await update.message.reply_text(box_message("HATA", f"Gonderilemedi: {sanitize_input(str(e), 200)}\n(Kullanici botu engellemis olabilir.)","\u274c"), parse_mode=ParseMode.HTML)
        except Exception:
            pass
    finally:
        context.user_data.pop("dm_target", None)
        _wizard_unlock(context)
    return ConversationHandler.END

async def dm_cancel(update, context):
    _wizard_unlock(context)
    context.user_data.pop("dm_target", None)
    await update.message.reply_text(box_message("IPTAL","Iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END
# =====================================================================
# SIKAYET SISTEMI (kullanici tarafi - sihirbaz)
# =====================================================================
CMP_KIND, CMP_TEXT, CMP_IMAGE = 110, 111, 112

def _complaints_enabled():
    return (db.get_setting("complaints_enabled") or "0") == "1"

async def sikayet_start(update, context):
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        return ConversationHandler.END
    if not _complaints_enabled():
        await update.message.reply_text(box_message("SIKAYET","Sikayet sistemi su an kapali.","\u2139\ufe0f"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if await guard_flood(update, context, is_command=True, cmd="/sikayet"):
        return ConversationHandler.END
    _ss_reset(context)  # yarim kalmis ekran goruntusu akisi sikayet metnini yutmasin
    context.user_data["cmp"] = {"kind":None,"text":None,"image_id":None}
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001f4dd Sadece Metin", callback_data="cmpkind_text")],
        [InlineKeyboardButton("\U0001f5bc Gorsel + Metin", callback_data="cmpkind_photo")],
        [InlineKeyboardButton("\u274c Vazgec", callback_data="cmp_cancel")]])
    await update.message.reply_text(box_message("SIKAYET / DESTEK","Sorununuzu nasil iletmek istersiniz? \U0001f447","\U0001f4e8"), parse_mode=ParseMode.HTML, reply_markup=kb)
    return CMP_KIND

async def sikayet_kind(update, context):
    q = update.callback_query; await q.answer()
    cmp = context.user_data.setdefault("cmp", {"kind": None, "text": None, "image_id": None})
    if q.data == "cmp_cancel": return await sikayet_cancel_cb(update, context)
    cmp["kind"] = "photo" if q.data == "cmpkind_photo" else "text"
    await q.edit_message_text(box_message("SIKAYET - MESAJ","Sorununuzu / sikayetinizi yazin.\n\n<i>Vazgec: /iptal</i>","\U0001f4dd"), parse_mode=ParseMode.HTML)
    return CMP_TEXT

async def sikayet_text(update, context):
    cmp = context.user_data.setdefault("cmp", {"kind": None, "text": None, "image_id": None})
    text = harden_text(update.message.text or "", MAX_COMPLAINT_LENGTH)
    if not text or len(text.strip()) < 3:
        await update.message.reply_text(box_message("HATA","Lutfen daha aciklayici yazin.","\u274c"), parse_mode=ParseMode.HTML)
        return CMP_TEXT
    cmp["text"] = text
    if cmp["kind"] == "photo":
        await update.message.reply_text(box_message("SIKAYET - GORSEL","Konuyla ilgili foto gonderin.\n\n<i>Gorsel istemiyorsaniz /atla</i>\n<i>Vazgec: /iptal</i>","\U0001f5bc"), parse_mode=ParseMode.HTML)
        return CMP_IMAGE
    return await _finalize_complaint(update, context)

async def sikayet_image(update, context):
    cmp = context.user_data.setdefault("cmp", {"kind": None, "text": None, "image_id": None})
    if not update.message.photo:
        await update.message.reply_text(box_message("HATA","Foto gonderin veya /atla.","\u274c"), parse_mode=ParseMode.HTML)
        return CMP_IMAGE
    cmp["image_id"] = update.message.photo[-1].file_id
    return await _finalize_complaint(update, context)

async def sikayet_skip(update, context):
    return await _finalize_complaint(update, context)

def append_complaint_file(cid, uid, uname, fname, message, image_file=""):
    block = (f"\n{'='*55}\nSIKAYET #{cid}\n"
             f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
             f"Kullanici: {neutralize_for_file(fname)} (@{neutralize_for_file(uname or 'yok')}) ID:{uid}\n"
             f"Gorsel: {image_file or 'yok'}\n{'-'*55}\n{neutralize_for_file(message)}\n")
    try:
        with open(COMPLAINTS_LOG, "a", encoding="utf-8") as f: f.write(block)
    except Exception as e:
        logger.warning(f"[COMPLAINT] dosya: {e}")

async def _finalize_complaint(update, context):
    cmp = context.user_data.get("cmp", {})
    user = update.effective_user
    image_filename = ""
    # Gunluk kota: ayni kullanici gunde en fazla 3 sikayet acabilsin
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        sayi = db.exe("SELECT COUNT(*) c FROM complaints WHERE user_id=? AND created_at LIKE ?",
                      (user.id, bugun + "%"))[0]["c"]
    except Exception:
        sayi = 0
    if sayi >= 3:
        context.user_data.pop("cmp", None)
        await update.message.reply_text(box_message("LIMIT",
            "Bugun icin sikayet hakkiniz doldu (3/3). Yarin tekrar deneyebilirsiniz.", "\u26a0\ufe0f"),
            parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if cmp.get("image_id"):
        try:
            file = await context.bot.get_file(cmp["image_id"])
            if getattr(file, "file_size", 0) and file.file_size > 10 * 1024 * 1024:
                raise ValueError("gorsel 10MB sinirini asiyor")
            image_filename = f"complaint_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{user.id}.jpg"
            target = os.path.join(COMPLAINTS_IMG_DIR, image_filename)
            if is_safe_path(COMPLAINTS_IMG_DIR, target):
                await file.download_to_drive(target)
            else:
                image_filename = ""
        except Exception as e:
            logger.warning(f"[COMPLAINT] gorsel: {e}"); image_filename = ""
    cid = db.add_complaint(user.id, user.username, user.first_name, cmp.get("text",""), image_filename)
    append_complaint_file(cid, user.id, user.username, user.first_name, cmp.get("text",""), image_filename)
    db.log(user.id, "complaint", str(cid))
    await update.message.reply_text(box_message("ALINDI", f"\u2705 Sikayetiniz #{cid} kaydedildi. En kisa surede ilgilenecegiz.","\U0001f64f"), parse_mode=ParseMode.HTML)
    notify = box_message("YENI SIKAYET", (
        f"\U0001f4e8 #{cid}\n\U0001f464 {harden_text(user.first_name or '',80)} (@{user.username or 'yok'})\n"
        f"\U0001f194 <code>{user.id}</code>\n\U0001f4ac {cmp.get('text','')}\n\n<i>/sikayetler</i>"), "\U0001f6a8")
    for aid in ADMIN_IDS:
        try:
            if cmp.get("image_id"):
                # Uzun sikayet + baslik 1024 caption sinirini asarsa admin
                # HIC haber alamiyordu; emniyetli kisalt.
                await context.bot.send_photo(chat_id=aid, photo=cmp["image_id"], caption=_safe_caption(notify), parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_message(chat_id=aid, text=notify, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"[COMPLAINT] admin bildirimi ({aid}): {e}")
    context.user_data.pop("cmp", None)
    return ConversationHandler.END

async def sikayet_cancel_cmd(update, context):
    context.user_data.pop("cmp", None)
    await update.message.reply_text(box_message("VAZGECILDI","Sikayet iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def sikayet_timeout(update, context):
    """10 dk islemsizlik: cmp kalintisi temizlenir (ekran goruntusu akisini kilitlemesin)."""
    context.user_data.pop("cmp", None)
    return ConversationHandler.END

async def sikayet_cancel_cb(update, context):
    q = update.callback_query
    context.user_data.pop("cmp", None)
    try: await q.edit_message_text(box_message("VAZGECILDI","Iptal edildi.","\u274c"), parse_mode=ParseMode.HTML)
    except: pass
    return ConversationHandler.END

# =====================================================================
# EKRAN GORUNTUSU KAYDI (kullanici + admin) — iki giris yolu:
#   1) Once FOTO gelir  -> secenekler (kategori; adminde ek olarak "kutuphane")
#      -> alanlar sirayla sorulur -> dosya girilen bilgilerle ADLANDIRILIP kaydedilir.
#   2) Once /ekran (ana menu / alt klavye tusu) -> kategori -> alanlar ->
#      "simdi fotoyu gonder" -> foto gelince DOGRUDAN kaydedilir.
# Dosya adi: sablon (varsayilan {kategori}_{tarih}_{saat}_{alanlar}_{tgid}).
# =====================================================================
SS_ACTION, SS_CAT, SS_FIELD, SS_PHOTO = 400, 401, 402, 403
SCREENSHOT_CSV_HEADERS = ["Kayit No", "Tarih", "Telegram ID", "Kullanici Adi", "Ad",
                          "Kategori", "Girilen Bilgiler", "Dosya Adi"]

class _EkranEtiketFiltresi(filters.MessageFilter):
    """Alt klavyedeki '📸 Ekran Görüntüsü' tusunu (kisa etiket) yakalar."""
    def filter(self, message):
        raw = (getattr(message, "text", "") or "").strip()
        return bool(raw) and len(raw) <= 40 and _match_menu_label(raw.lower()) == "ekran"

_EKRAN_ETIKET_FILTRESI = _EkranEtiketFiltresi(name="ekran_etiketi")

def _ss_media_from_message(msg):
    """Mesajdaki foto ya da resim dosyasini (file_id, uzanti, tur) olarak dondurur."""
    photo = getattr(msg, "photo", None)
    if photo:
        return photo[-1].file_id, ".jpg", "photo"
    doc = getattr(msg, "document", None)
    if doc is not None and getattr(doc, "file_id", None):
        mime = (getattr(doc, "mime_type", "") or "").lower()
        fname = (getattr(doc, "file_name", "") or "").lower()
        ext = os.path.splitext(fname)[1]
        if ext not in SCREENSHOT_EXTENSIONS:
            ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".jpg")
        if mime.startswith("image/") or os.path.splitext(fname)[1] in SCREENSHOT_EXTENSIONS:
            return doc.file_id, ext, "document"
    return None, "", ""

def _ss_msg_time(msg):
    """Fotonun GONDERILDIGI an (yerel saat, ISO). Dosya adindaki tarih budur."""
    d = getattr(msg, "date", None)
    try:
        if d is not None:
            return d.astimezone().replace(tzinfo=None).isoformat(timespec="seconds")
    except Exception:
        pass
    return datetime.now().isoformat(timespec="seconds")

def _ss_reset(context):
    context.user_data.pop("ss", None)
    info = context.user_data.get("wizard_lock")
    if info and info[0] == "ss":
        _wizard_unlock(context)

def _ss_new_state(mode, msg=None):
    file_id, ext, kind = _ss_media_from_message(msg) if msg is not None else (None, "", "")
    caption = getattr(msg, "caption", "") if msg is not None else ""
    return {"mode": mode, "file_id": file_id, "ext": ext, "kind": kind,
            "note": harden_text(caption or "", 200),
            "caption_raw": _CTRL_CHARS.sub("", caption or "").strip()[:60],
            "sent_at": _ss_msg_time(msg) if msg is not None else "",
            "cat": None, "cat_label": "", "fields": [], "values": [], "idx": 0}

def _ss_prompt_text():
    return _safe_setting_text("screenshot_prompt", DEFAULT_SCREENSHOT_PROMPT, 300)

def _ss_category_kb():
    rows = [[InlineKeyboardButton(_plain_label(c["label"], 40), callback_data=f"sscat_{c['key']}")]
            for c in screenshot_categories()]
    rows.append([InlineKeyboardButton("❌ Vazgeç", callback_data="ss_cancel")])
    return InlineKeyboardMarkup(rows)

def _ss_done_lines(ss):
    return "\n".join(f"✅ {sanitize_input(l, 30)}: <code>{sanitize_input(v, 60)}</code>"
                     for l, v in zip(ss.get("fields", []), ss.get("values", [])))

def _ss_field_prompt(ss):
    idx, total = ss["idx"], len(ss["fields"])
    label = ss["fields"][idx]
    done = _ss_done_lines(ss)
    body = (f"{done}\n\n" if done else "")
    body += (f"<b>{sanitize_input(label, 30)}</b> bilgisini yaz ({idx + 1}/{total}).\n"
             "Yazdığın her bilgi dosya adına eklenir.\n\n<i>Vazgeç: /iptal</i>")
    return box_message(f"📸 {sanitize_input(ss.get('cat_label') or '', 40)}", body, "")

def _ss_field_kb(user, ss):
    rows = []
    try:
        label = ss["fields"][ss["idx"]].lower()
    except (IndexError, KeyError):
        label = ""
    if "site" in label:
        rec = db.get_site_id_record(user.id)
        if rec and rec.get("site_id"):
            rows.append([InlineKeyboardButton(
                f"✅ Kayıtlı Site ID'mi kullan ({_plain_label(rec['site_id'], 24)})", callback_data="ss_usesite")])
    rows.append([InlineKeyboardButton("❌ Vazgeç", callback_data="ss_cancel")])
    return InlineKeyboardMarkup(rows)

def _ss_photo_prompt(ss):
    done = _ss_done_lines(ss)
    body = (f"{done}\n\n" if done else "")
    body += ("Şimdi <b>ekran görüntüsünü</b> gönder. Fotoğraf geldiği anda bu bilgilerle "
             "adlandırılıp kaydedilecek 📁\n\n<i>Vazgeç: /iptal</i>")
    return box_message("📸 EKRAN GÖRÜNTÜSÜNÜ GÖNDER", body, "")

async def _ss_limit_reached(context, chat_id):
    await context.bot.send_message(chat_id=chat_id, text=box_message("LİMİT",
        f"Bugün için ekran görüntüsü hakkın doldu ({SCREENSHOT_DAILY_LIMIT}/{SCREENSHOT_DAILY_LIMIT}). "
        "Yarın tekrar deneyebilirsin.", "⚠️"), parse_mode=ParseMode.HTML)

def _ss_limit_hit(user):
    return (user.id not in ADMIN_IDS and SCREENSHOT_DAILY_LIMIT
            and db.count_screenshots_today(user.id) >= SCREENSHOT_DAILY_LIMIT)

_SS_ACIK_ISLEM_METNI = box_message("AÇIK İŞLEM VAR",
    "Şu an açık bir işlemin var (şikayet ya da başka bir akış). Önce onu tamamla ya da /iptal yaz; "
    "sonra ekran görüntüsünü tekrar gönder.", "⚠️")

def _ss_other_flow_open(context):
    """Sikayet sihirbazi (cmp) veya baska bir admin sihirbazi (wizard_lock) acik mi?
    Bu akislar ONCE kayitli oldugu icin yazilan bilgiler onlara duser; o yuzden
    ekran goruntusu akisi baslatilmaz."""
    return bool(context.user_data.get("cmp")) or _wizard_busy(context, "ss")

async def _ss_expired(q, context):
    _ss_reset(context)
    try:
        await q.edit_message_text(box_message("SÜRE DOLDU",
            "Baştan başla: fotoğrafı tekrar gönder veya /ekran yaz.", "⌛"), parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return ConversationHandler.END

# --- Giris yolu 1: once FOTO ---
async def ss_photo_entry(update, context):
    """Sihirbaz disinda gelen foto: secenek sun. Admin oturumunda 'kutuphane'
    secenegi de eklenir; ozellik kapaliysa admin fotosu eskisi gibi kutuphaneye gider,
    kullanici fotosu sessizce yok sayilir."""
    user = update.effective_user
    msg = update.message
    file_id, ext, kind = _ss_media_from_message(msg)
    if not file_id:
        return ConversationHandler.END
    chat_id = update.effective_chat.id
    # allow_reentry=True oldugu icin PTB, akis ACIKKEN gelen fotoyu da (durum
    # handler'larindan ONCE) bu giris noktasina yollar. Kategori secilmisse yeni
    # akis baslatma: bilgi adimindaysa fotoyu al ve devam et, "simdi fotoyu
    # gonder" adimindaysa dogrudan kaydet (giris yolu 2'nin son adimi).
    ss = context.user_data.get("ss")
    if ss and ss.get("cat") is not None:
        if ss.get("idx", 0) >= len(ss.get("fields") or []):
            return await ss_photo_step(update, context)
        return await ss_photo_midway_field(update, context)
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        return ConversationHandler.END
    admin = is_authenticated(user.id)
    if _ss_other_flow_open(context):
        # Acik sikayet akisi / admin sihirbazi varken foto YENI akis baslatmaz;
        # yoksa yazilan bilgiler once kayitli olan sihirbaza duser.
        if admin:
            await msg.reply_text(box_message("SIHIRBAZ ACIK",
                "Foto ISLENMEDI: su an acik bir sihirbaz var. Once onu bitirin ya da /iptal yazin.", "⚠️"),
                parse_mode=ParseMode.HTML)
        elif screenshots_enabled():
            await msg.reply_text(_SS_ACIK_ISLEM_METNI, parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if admin:
        if not screenshots_enabled():
            if kind == "photo":
                await _kutuphaneye_ekle(context, chat_id, user, "photo", file_id, msg.caption)
            return ConversationHandler.END
    else:
        if not screenshots_enabled():
            return ConversationHandler.END
        # Album (tek seferde secilen birden fazla foto) ayri mesajlar olarak gelir.
        # Ilkini al, 2 sn icinde gelenleri sessizce yok say; genel flood sayacina
        # SOKMA (5 fotoluk album 30 dk engel yemesin).
        if _cb_throttled(user.id, "ss_photo", 2):
            return ConversationHandler.END
        if _ss_limit_hit(user):
            await _ss_limit_reached(context, chat_id)
            return ConversationHandler.END
        db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
        db.inc_msg(user.id)
    _wizard_lock(context, "ss")
    context.user_data["ss"] = _ss_new_state("photo_first", msg)
    if admin and kind == "photo":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗂 Kampanya Medyasi Yap (kutuphane)", callback_data="ssact_library")],
            [InlineKeyboardButton("📸 Ekran Goruntusu Olarak Kaydet", callback_data="ssact_screenshot")],
            [InlineKeyboardButton("❌ Vazgec", callback_data="ss_cancel")]])
        await msg.reply_text(box_message("FOTO ALINDI — NE YAPALIM?",
            "🗂 <b>Kampanya Medyasi</b>: kutuphaneye eklenir ve aktif acilis gorseli olur.\n"
            "📸 <b>Ekran Goruntusu</b>: kategori secip bilgileri yazarsin; dosya o bilgilerle "
            "adlandirilip <code>screenshots/</code> klasorune kaydedilir.", "🖼"),
            parse_mode=ParseMode.HTML, reply_markup=kb)
        return SS_ACTION
    await msg.reply_text(box_message("EKRAN GÖRÜNTÜSÜ", _ss_prompt_text(), "📸"),
        parse_mode=ParseMode.HTML, reply_markup=_ss_category_kb())
    return SS_CAT

async def ss_action_pick(update, context):
    """Admin secimi: kutuphaneye ekle (eski davranis) ya da ekran goruntusu kaydi."""
    q = update.callback_query
    if q.data == "ss_cancel":
        return await ss_cancel_cb(update, context)
    ss = context.user_data.get("ss") or {}
    if not ss.get("file_id"):
        await q.answer()
        return await _ss_expired(q, context)
    user = update.effective_user
    chat_id = update.effective_chat.id
    if q.data == "ssact_library":
        await q.answer()
        if not is_authenticated(user.id):
            _ss_reset(context)
            await q.edit_message_text(box_message("OTURUM DOLDU",
                "Kutuphaneye EKLENMEDI. /admin ile giris yapip fotoyu yeniden gonderin.", "⏳"), parse_mode=ParseMode.HTML)
            return ConversationHandler.END
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _kutuphaneye_ekle(context, chat_id, user, "photo", ss["file_id"], ss.get("caption_raw", ""))
        _ss_reset(context)
        return ConversationHandler.END
    await q.answer()
    await q.edit_message_text(box_message("EKRAN GÖRÜNTÜSÜ", _ss_prompt_text(), "📸"),
        parse_mode=ParseMode.HTML, reply_markup=_ss_category_kb())
    return SS_CAT

# --- Giris yolu 2: once BILGILER (komut / ana menu / alt klavye) ---
async def ss_start_cmd(update, context):
    """/ekran ya da alt klavyedeki 📸 tusu: kategori → bilgiler → foto."""
    user = update.effective_user
    msg = update.message
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        return ConversationHandler.END
    if not screenshots_enabled():
        await msg.reply_text(box_message("EKRAN GÖRÜNTÜSÜ", "Bu özellik şu an kapalı.", "ℹ️"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if await guard_flood(update, context, is_command=True, cmd="/ekran"):
        return ConversationHandler.END
    if _ss_other_flow_open(context):
        await msg.reply_text(box_message("MESGUL", "Once acik sihirbazi /iptal ile kapatin.", "⚠️") if is_authenticated(user.id)
                             else _SS_ACIK_ISLEM_METNI, parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if _ss_limit_hit(user):
        await _ss_limit_reached(context, update.effective_chat.id)
        return ConversationHandler.END
    db.add_user(user.id, user.username, user.first_name, user.last_name, getattr(user, "language_code", ""))
    db.inc_msg(user.id)
    _wizard_lock(context, "ss")
    context.user_data["ss"] = _ss_new_state("data_first")
    await msg.reply_text(box_message("EKRAN GÖRÜNTÜSÜ GÖNDER",
        "Önce ne için gönderdiğini seç, ardından istenen bilgileri yaz; en son ekran görüntüsünü gönder 👇\n\n"
        "<i>Fotoğrafı önce göndermen de yeterli: seçenekler otomatik çıkar.</i>", "📸"),
        parse_mode=ParseMode.HTML, reply_markup=_ss_category_kb())
    return SS_CAT

async def ss_start_cb(update, context):
    """Ana menudeki 📸 Ekran Görüntüsü Gönder butonu."""
    q = update.callback_query
    user = update.effective_user
    if db.is_banned(user.id) or db.is_temp_banned(user.id):
        await q.answer()
        return ConversationHandler.END
    if not screenshots_enabled():
        await q.answer("Bu özellik şu an kapalı.", show_alert=True)
        return ConversationHandler.END
    if _ss_other_flow_open(context):
        await q.answer("Önce açık işlemi tamamla ya da /iptal yaz.", show_alert=True)
        return ConversationHandler.END
    await q.answer()
    if _ss_limit_hit(user):
        await _ss_limit_reached(context, update.effective_chat.id)
        return ConversationHandler.END
    try:
        db.exe("UPDATE users SET last_active=? WHERE user_id=?", (datetime.now().isoformat(), user.id))
    except Exception:
        pass
    _wizard_lock(context, "ss")
    context.user_data["ss"] = _ss_new_state("data_first")
    await _um_show(q, context, box_message("EKRAN GÖRÜNTÜSÜ GÖNDER",
        "Önce ne için gönderdiğini seç, ardından istenen bilgileri yaz; en son ekran görüntüsünü gönder 👇", "📸"),
        _ss_category_kb())
    return SS_CAT

async def ss_cat_pick(update, context):
    q = update.callback_query
    if q.data == "ss_cancel":
        return await ss_cancel_cb(update, context)
    ss = context.user_data.get("ss")
    if not ss:
        await q.answer()
        return await _ss_expired(q, context)
    cat = screenshot_category(q.data[len("sscat_"):])
    if not cat:
        await q.answer("Bu seçenek artık yok; yeniden seç.", show_alert=True)
        try:
            await q.edit_message_reply_markup(reply_markup=_ss_category_kb())
        except Exception:
            pass
        return SS_CAT
    await q.answer()
    ss.update({"cat": cat["key"], "cat_label": cat["label"], "fields": list(cat["fields"]), "values": [], "idx": 0})
    user, chat_id = update.effective_user, update.effective_chat.id
    if not ss["fields"]:
        if ss.get("file_id"):
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return await _ss_save(context, user, chat_id)
        await q.edit_message_text(_ss_photo_prompt(ss), parse_mode=ParseMode.HTML)
        return SS_PHOTO
    await q.edit_message_text(_ss_field_prompt(ss), parse_mode=ParseMode.HTML, reply_markup=_ss_field_kb(user, ss))
    return SS_FIELD

async def _ss_take_value(context, user, chat_id, raw):
    ss = context.user_data["ss"]
    label = ss["fields"][ss["idx"]]
    value, err = validate_screenshot_field(label, raw)
    if err:
        await context.bot.send_message(chat_id=chat_id, text=box_message("HATA",
            f"{err}\n\n<b>{sanitize_input(label, 30)}</b> bilgisini yeniden yaz.", "❌"),
            parse_mode=ParseMode.HTML, reply_markup=_ss_field_kb(user, ss))
        return SS_FIELD
    ss["values"].append(value)
    ss["idx"] += 1
    if ss["idx"] < len(ss["fields"]):
        await context.bot.send_message(chat_id=chat_id, text=_ss_field_prompt(ss),
            parse_mode=ParseMode.HTML, reply_markup=_ss_field_kb(user, ss))
        return SS_FIELD
    if ss.get("file_id"):
        return await _ss_save(context, user, chat_id)
    await context.bot.send_message(chat_id=chat_id, text=_ss_photo_prompt(ss), parse_mode=ParseMode.HTML)
    return SS_PHOTO

def _ss_menu_tusu(update):
    """Kalici alt klavyedeki bir menu tusuna basildi mi? (icerik sayilmaz)"""
    raw = (getattr(update.message, "text", "") or "").strip()
    return bool(raw) and len(raw) <= 40 and bool(_match_admin_label(raw.lower()) or _match_menu_label(raw.lower()))

async def ss_field_step(update, context):
    ss = context.user_data.get("ss")
    if not ss or ss.get("cat") is None or ss["idx"] >= len(ss["fields"]):
        # Akis /start vb. ile birakilmis, PTB durumu kalmis: metni normal yola ver
        # (menu tusu, asistan...) ve kalan durumu sessizce kapat.
        _ss_reset(context)
        await handle_text(update, context)
        return ConversationHandler.END
    if _ss_menu_tusu(update):
        raw = (update.message.text or "").strip()
        await update.message.reply_text(box_message("EKRAN GÖRÜNTÜSÜ",
            f"'{sanitize_input(raw, 40)}' bir menü tuşu; bilgi olarak ALINMADI.\n"
            "İstenen bilgiyi yaz ya da /iptal ile çık.", "🧭"), parse_mode=ParseMode.HTML)
        return SS_FIELD
    return await _ss_take_value(context, update.effective_user, update.effective_chat.id, update.message.text or "")

async def ss_usesite_cb(update, context):
    """'Kayıtlı Site ID'mi kullan' butonu: profildeki Site ID alana yazilir."""
    q = update.callback_query
    ss = context.user_data.get("ss")
    if not ss or ss.get("cat") is None or ss["idx"] >= len(ss["fields"]):
        await q.answer()
        return await _ss_expired(q, context)
    rec = db.get_site_id_record(update.effective_user.id)
    if not rec or not rec.get("site_id"):
        await q.answer("Kayıtlı Site ID bulunamadı; elle yaz.", show_alert=True)
        return SS_FIELD
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return await _ss_take_value(context, update.effective_user, update.effective_chat.id, rec["site_id"])

async def ss_photo_midway_field(update, context):
    """Bilgi adimindayken foto gelirse (ss_photo_entry buraya yonlendirir):
    fotoyu al, girilen bilgileri koru, ayni adimda kal."""
    ss = context.user_data.get("ss")
    file_id, ext, kind = _ss_media_from_message(update.message)
    if not ss or not file_id:
        return SS_FIELD
    ss.update({"file_id": file_id, "ext": ext, "kind": kind, "sent_at": _ss_msg_time(update.message)})
    if not ss.get("note"):
        ss["note"] = harden_text(update.message.caption or "", 200)
    await update.message.reply_text(box_message("FOTO ALINDI ✅",
        "Bilgileri girmeye devam et 👇", "📸"), parse_mode=ParseMode.HTML)
    await update.message.reply_text(_ss_field_prompt(ss), parse_mode=ParseMode.HTML,
        reply_markup=_ss_field_kb(update.effective_user, ss))
    return SS_FIELD

async def ss_photo_step(update, context):
    """Bilgiler girildi, foto bekleniyor: foto gelince dogrudan kaydet."""
    ss = context.user_data.get("ss")
    msg = update.message
    file_id, ext, kind = _ss_media_from_message(msg)
    if not ss or ss.get("cat") is None:
        # Akis birakilmis (or. /start), PTB durumu kalmis: foto ise yeni akis baslat,
        # metin ise normal yola ver; kalan durumu kapat.
        _ss_reset(context)
        if file_id:
            return await ss_photo_entry(update, context)
        if getattr(msg, "text", None):
            await handle_text(update, context)
        return ConversationHandler.END
    if not file_id:
        if _ss_menu_tusu(update):
            await msg.reply_text(box_message("EKRAN GÖRÜNTÜSÜ",
                "Bu bir menü tuşu. Şimdi ekran görüntüsünü gönder ya da /iptal ile çık.", "🧭"), parse_mode=ParseMode.HTML)
            return SS_PHOTO
        await msg.reply_text(box_message("HATA",
            "Lütfen bir fotoğraf (ekran görüntüsü) gönder veya /iptal yaz.", "❌"), parse_mode=ParseMode.HTML)
        return SS_PHOTO
    ss.update({"file_id": file_id, "ext": ext, "kind": kind, "sent_at": _ss_msg_time(msg)})
    if not ss.get("note"):
        ss["note"] = harden_text(msg.caption or "", 200)
    return await _ss_save(context, update.effective_user, update.effective_chat.id)

def _ss_append_csv(sid, user, cat, values, fname, when):
    """Excel'de acilabilen kayit dosyasi: screenshots/ekran_goruntuleri.csv"""
    try:
        yeni = not os.path.exists(SCREENSHOTS_CSV)
        with open(SCREENSHOTS_CSV, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if yeni:
                w.writerow(SCREENSHOT_CSV_HEADERS)
            bilgiler = " | ".join(f"{l}={v}" for l, v in zip(cat["fields"], values))
            w.writerow([sid, when.strftime("%d.%m.%Y %H:%M:%S"), user.id,
                        neutralize_for_file(user.username or ""), neutralize_for_file(user.first_name or ""),
                        neutralize_for_file(cat["label"]), neutralize_for_file(bilgiler), fname])
        try:
            os.chmod(SCREENSHOTS_CSV, 0o600)
        except OSError:
            pass
    except Exception as e:
        logger.warning(f"[EKRAN] csv yazilamadi: {e}")

async def _ss_notify_admins(context, user, sid, cat, values, fname, file_id, kind):
    bilgiler = "\n".join(f"• {sanitize_input(l, 30)}: <code>{sanitize_input(v, 60)}</code>"
                         for l, v in zip(cat["fields"], values)) or "• (bilgi girilmedi)"
    text = box_message("YENI EKRAN GORUNTUSU", (
        f"📸 #{sid} • {sanitize_input(cat['label'], 40)}\n"
        f"👤 {harden_text(user.first_name or '', 80)} (@{user.username or 'yok'})\n"
        f"🆔 <code>{user.id}</code>\n{bilgiler}\n📁 <code>{sanitize_input(fname, 160)}</code>\n\n"
        f"<i>/ekranlar {sid}</i>"), "🔔")
    for aid in ADMIN_IDS:
        if aid == user.id:
            continue
        try:
            if kind == "document":
                await context.bot.send_document(chat_id=aid, document=file_id, caption=_safe_caption(text), parse_mode=ParseMode.HTML)
            else:
                await context.bot.send_photo(chat_id=aid, photo=file_id, caption=_safe_caption(text), parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.warning(f"[EKRAN] admin bildirimi ({aid}): {e}")

async def _ss_save(context, user, chat_id):
    """Fotoyu indir, girilen bilgilerle adlandir, diske + veritabanina + CSV'ye yaz."""
    ss = context.user_data.get("ss") or {}
    _ss_reset(context)
    cat = {"key": ss.get("cat") or "ekran", "label": ss.get("cat_label") or "Ekran",
           "fields": list(ss.get("fields") or [])}
    values = list(ss.get("values") or [])
    file_id = ss.get("file_id")
    if not file_id:
        await context.bot.send_message(chat_id=chat_id, text=box_message("HATA",
            "Fotoğraf bulunamadı; /ekran ile yeniden başla.", "❌"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    if _ss_limit_hit(user):
        await _ss_limit_reached(context, chat_id)
        return ConversationHandler.END
    try:
        when = datetime.fromisoformat(ss.get("sent_at") or "")
    except (TypeError, ValueError):
        when = datetime.now()
    base = build_screenshot_filename(cat, values, user.id, when, username=user.username or "")
    path, fname = _unique_screenshot_path(base, ss.get("ext") or ".jpg")
    try:
        tg_file = await context.bot.get_file(file_id)
        size = getattr(tg_file, "file_size", 0) or 0
        if size > SCREENSHOT_MAX_BYTES:
            raise ValueError("dosya 20MB sinirini asiyor")
        if not is_safe_path(SCREENSHOTS_DIR, path):
            raise ValueError("gecersiz dosya yolu")
        await tg_file.download_to_drive(path)
    except Exception as e:
        logger.warning(f"[EKRAN] indirme basarisiz ({user.id}): {e}")
        await context.bot.send_message(chat_id=chat_id, text=box_message("KAYDEDİLEMEDİ",
            "Görsel indirilemedi. Lütfen fotoğrafı tekrar gönder.", "❌"), parse_mode=ParseMode.HTML)
        return ConversationHandler.END
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    fields_json = json.dumps([{"alan": l, "deger": v} for l, v in zip(cat["fields"], values)], ensure_ascii=False)
    sid = db.add_screenshot(user.id, user.username, user.first_name, cat["key"], cat["label"],
                            fields_json, fname, ss.get("note", ""))
    _ss_append_csv(sid, user, cat, values, fname, when)
    db.log(user.id, "screenshot", f"#{sid} {fname}")
    logger.info(f"[EKRAN] {user.id} -> #{sid} {fname}")
    bilgiler = "\n".join(f"• {sanitize_input(l, 30)}: <code>{sanitize_input(v, 60)}</code>"
                         for l, v in zip(cat["fields"], values)) or "• (bilgi istenmedi)"
    await context.bot.send_message(chat_id=chat_id, text=box_message("KAYDEDİLDİ ✅", (
        f"🏷 <b>{sanitize_input(cat['label'], 40)}</b>\n{bilgiler}\n\n"
        f"📁 Dosya adı:\n<code>{sanitize_input(fname, 160)}</code>\n\nKayıt no: #{sid}"), "📸"),
        parse_mode=ParseMode.HTML)
    await _ss_notify_admins(context, user, sid, cat, values, fname, file_id, ss.get("kind"))
    return ConversationHandler.END

async def ss_cancel_cmd(update, context):
    _ss_reset(context)
    await update.message.reply_text(box_message("VAZGEÇİLDİ", "Ekran görüntüsü kaydı iptal edildi.", "❌"),
        parse_mode=ParseMode.HTML)
    return ConversationHandler.END

async def ss_cancel_cb(update, context):
    q = update.callback_query
    _ss_reset(context)
    try:
        await q.answer()
    except Exception:
        pass
    try:
        await q.edit_message_text(box_message("VAZGEÇİLDİ", "Ekran görüntüsü kaydı iptal edildi.", "❌"),
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return ConversationHandler.END

async def ss_timeout(update, context):
    _ss_reset(context)
    try:
        chat = update.effective_chat
        if chat is not None:
            await context.bot.send_message(chat_id=chat.id, text=box_message("SÜRE DOLDU",
                "Ekran görüntüsü kaydı zaman aşımına uğradı. Yeniden başlamak için fotoğrafı tekrar gönder "
                "veya /ekran yaz.", "⌛"), parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return ConversationHandler.END

# --- Admin tarafi: kayitlari gorme ---
def _ss_fields_list(r):
    try:
        data = json.loads(r.get("fields") or "[]")
        return [(str(d.get("alan", "")), str(d.get("deger", ""))) for d in data if isinstance(d, dict)]
    except Exception:
        return []

def _ss_admin_detail_text(r):
    bilgiler = "\n".join(f"• {sanitize_input(a, 30)}: <code>{sanitize_input(d, 60)}</code>"
                         for a, d in _ss_fields_list(r)) or "• (bilgi girilmedi)"
    note = f"\n📝 {r['note']}" if r.get("note") else ""
    return box_message(f"EKRAN GORUNTUSU #{r['id']}", (
        f"🏷 {sanitize_input(r.get('category_label') or r.get('category') or '', 40)}\n"
        f"👤 {harden_text(r.get('first_name') or '', 80)} (@{r.get('username') or 'yok'})\n"
        f"🆔 <code>{r['user_id']}</code>\n⏰ {str(r.get('created_at') or '')[:16].replace('T', ' ')}\n"
        f"📌 {r.get('status') or ''}\n{bilgiler}\n📁 <code>{sanitize_input(r.get('file_name') or '', 160)}</code>"
        f"{note}\n\n<code>/ekrankapat {r['id']}</code>"), "📸")

def _ss_list_lines(rows, max_chars=3300):
    """Liste satirlari; Telegram 4096 sinirina takilmamak icin satir ozeti ve toplam uzunluk kirpilir."""
    lines = ""
    for r in rows:
        durum = {"yeni": "🔴", "okundu": "🟡", "cozuldu": "🟢"}.get(r.get("status"), "⚪")
        ozet = ", ".join(d for _a, d in _ss_fields_list(r))
        ozet = sanitize_input(ozet[:40] + ("…" if len(ozet) > 40 else ""), 60) or "-"
        satir = (f"{durum} #{r['id']} <code>{r['user_id']}</code> "
                 f"{sanitize_input(_plain_label(r.get('category_label') or r.get('category') or '', 24), 40)}: {ozet}\n")
        if len(lines) + len(satir) > max_chars:
            lines += "… <i>(liste kisaltildi; kategori ya da 'yeni' filtresi kullanin)</i>\n"
            break
        lines += satir
    return lines

@admin_only
async def ekranlar_cmd(update, context):
    """/ekranlar [ID | yeni | kategori] — ekran goruntusu kayitlari."""
    if context.args and context.args[0].isdigit():
        r = db.get_screenshot(int(context.args[0]))
        if not r:
            await update.message.reply_text(box_message("HATA", "Bulunamadi.", "❌"), parse_mode=ParseMode.HTML); return
        txt = _ss_admin_detail_text(r)
        path = os.path.join(SCREENSHOTS_DIR, r.get("file_name") or "")
        gonderildi = False
        if r.get("file_name") and is_safe_path(SCREENSHOTS_DIR, path) and os.path.isfile(path):
            try:
                with open(path, "rb") as fh:
                    if path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                        await update.message.reply_photo(photo=fh, caption=_safe_caption(txt), parse_mode=ParseMode.HTML)
                    else:
                        await update.message.reply_document(document=fh, caption=_safe_caption(txt), parse_mode=ParseMode.HTML)
                gonderildi = True
            except Exception as e:
                logger.warning(f"[EKRAN] dosya gonderilemedi #{r['id']}: {e}")
        if not gonderildi:
            await update.message.reply_text(txt + "\n\n⚠️ Dosya diskte bulunamadi.", parse_mode=ParseMode.HTML)
        if r.get("status") == "yeni":
            db.set_screenshot_status(r["id"], "okundu")
        return
    arg = (context.args[0].lower() if context.args else "")
    only_new = arg in ("yeni", "new")
    cat = arg if (arg and not only_new and screenshot_category(arg)) else None
    rows = db.list_screenshots(limit=20, only_new=only_new, category=cat)
    if not rows:
        await update.message.reply_text(box_message("EKRAN GORUNTULERI", "Kayit yok.", "ℹ️"), parse_mode=ParseMode.HTML); return
    await update.message.reply_text(box_message("EKRAN GORUNTULERI",
        f"{_ss_list_lines(rows)}\n<i>Detay ve foto: /ekranlar ID | Yalniz yeniler: /ekranlar yeni | Kategori: /ekranlar anahtar</i>\n"
        f"Dosyalar: <code>screenshots/</code>", "📸"), parse_mode=ParseMode.HTML)

@admin_only
async def ekrankapat_cmd(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(box_message("KULLANIM", "<code>/ekrankapat ID</code>", "ℹ️"), parse_mode=ParseMode.HTML); return
    sid = int(context.args[0])
    if not db.get_screenshot(sid):
        await update.message.reply_text(box_message("HATA", "Bulunamadi.", "❌"), parse_mode=ParseMode.HTML); return
    db.set_screenshot_status(sid, "cozuldu")
    db.admin_log(update.effective_user.id, "screenshot_resolved", str(sid))
    await update.message.reply_text(box_message("BASARILI", f"#{sid} kapatildi.", "✅"), parse_mode=ParseMode.HTML)

@admin_only
async def ekrandosya_cmd(update, context):
    """screenshots/ekran_goruntuleri.csv dosyasini gonderir."""
    if not os.path.isfile(SCREENSHOTS_CSV):
        await update.message.reply_text(box_message("BILGI", "Henuz kayit dosyasi yok.", "ℹ️"), parse_mode=ParseMode.HTML); return
    with open(SCREENSHOTS_CSV, "rb") as fh:
        await update.message.reply_document(document=fh, filename=os.path.basename(SCREENSHOTS_CSV),
            caption=f"{db.count_screenshots()} ekran goruntusu kaydi")

# =====================================================================
# ADMIN KOMUTLARI - ayar (yedek komut yolu), ban, kullanici, sikayet, log
# =====================================================================
@admin_only
async def setval_generic(update, context, key):
    if not context.args:
        await update.message.reply_text(box_message("KULLANIM", f"Deger girin.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    title, desc, typ = SETTING_DEFS[key]
    val = " ".join(context.args)
    if typ == "url":
        val = val.strip()
        if not is_valid_url(val) or (key == "giris_link" and not val.lower().startswith("https://")):
            await update.message.reply_text(box_message("HATA","Gecersiz URL! https:// ile baslamali.","\u274c"), parse_mode=ParseMode.HTML); return
    else:
        val = sanitize_input(val, 300)
    db.set_setting(key, val)
    if key in ("giris_link", "menu_button_text", "play_link"):
        await _apply_play_menu_buttons(context.bot)
    if key in ("promo_image", "campaign_media_url"):
        db.set_setting("campaign_media_id", "")
        db.set_setting("campaign_media_file", "")
        db.set_setting("promo_image_file", "")
        db.set_setting("campaign_media_type", _media_kind(val))
        db.set_setting("active_campaign_media_library_id", "")
    db.admin_log(update.effective_user.id, "set_"+key, val[:50])
    await update.message.reply_text(box_message("KAYDEDILDI", f"<b>{title}</b>:\n<code>{val}</code>","\u2705"), parse_mode=ParseMode.HTML)

# Yedek komutlar (butonlu sihirbaz ana yol; bunlar da calisir)
async def setgirislink_cmd(update, context):  await setval_generic(update, context, "giris_link")
async def setgiristitle_cmd(update, context): await setval_generic(update, context, "giris_title")
async def setgiristext_cmd(update, context):  await setval_generic(update, context, "giris_text")
async def setgirisbtn_cmd(update, context):   await setval_generic(update, context, "giris_btn_text")
async def setreglink_cmd(update, context):    await setval_generic(update, context, "register_link")
async def setregbtn_cmd(update, context):     await setval_generic(update, context, "register_btn_text")
async def setbonuslink_cmd(update, context):  await setval_generic(update, context, "bonus_link")
async def setbonusbtn_cmd(update, context):   await setval_generic(update, context, "bonus_btn_text")
async def setsupport_cmd(update, context):    await setval_generic(update, context, "support_link")
async def setsupportbtn_cmd(update, context): await setval_generic(update, context, "support_btn_text")
async def setwelcome_cmd(update, context):    await setval_generic(update, context, "welcome_text")
async def setcaption_cmd(update, context):    await setval_generic(update, context, "promo_caption")
async def setimageurl_cmd(update, context):   await setval_generic(update, context, "campaign_media_url")

@admin_only
async def setimage_cmd(update, context):
    if not context.args:
        files = [f for f in os.listdir(IMAGES_DIR) if f.lower().endswith(('.jpg','.jpeg','.png','.gif','.webp','.mp4','.mov','.m4v'))]
        await update.message.reply_text(box_message("KAMPANYA MEDYASI","<code>/setimage dosya.jpg</code> veya <code>/setimage video.mp4</code>\n\n"+("\n".join(files) or "(bos)"),"\U0001f5bc"), parse_mode=ParseMode.HTML); return
    fn = context.args[0]
    if not is_valid_filename(fn):
        await update.message.reply_text(box_message("HATA","Gecersiz dosya adi!","\u274c"), parse_mode=ParseMode.HTML); return
    path = os.path.join(IMAGES_DIR, fn)
    if not (is_safe_path(IMAGES_DIR, path) and os.path.exists(path)):
        await update.message.reply_text(box_message("HATA","Dosya bulunamadi.","\u274c"), parse_mode=ParseMode.HTML); return
    db.set_setting("campaign_media_file", fn)
    db.set_setting("campaign_media_id", "")
    db.set_setting("campaign_media_type", _media_kind(fn))
    db.set_setting("promo_image_file", fn)
    db.set_setting("active_campaign_media_library_id", "")
    db.admin_log(update.effective_user.id, "set_campaign_media_file", fn)
    await update.message.reply_text(box_message("BASARILI", f"Kampanya medyasi: {fn}","\u2705"), parse_mode=ParseMode.HTML)

@admin_only
async def supporton_cmd(update, context):
    db.set_setting("support_enabled","1"); await _apply_commands(context.bot)
    await update.message.reply_text(box_message("BASARILI","\U0001f7e2 Canli destek aktif.","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def supportoff_cmd(update, context):
    db.set_setting("support_enabled","0"); await _apply_commands(context.bot)
    await update.message.reply_text(box_message("BASARILI","\U0001f534 Canli destek kapali.","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def sikayetac_cmd(update, context):
    db.set_setting("complaints_enabled","1"); await _apply_commands(context.bot)
    await update.message.reply_text(box_message("BASARILI","\U0001f7e2 Sikayet sistemi aktif.","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def sikayetkapat_cmd(update, context):
    db.set_setting("complaints_enabled","0"); await _apply_commands(context.bot)
    await update.message.reply_text(box_message("BASARILI","\U0001f534 Sikayet sistemi kapali.","\u2705"), parse_mode=ParseMode.HTML)

@admin_only
async def ban_cmd(update, context):
    if not context.args or not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("KULLANIM","<code>/ban ID neden</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    uid = int(context.args[0]); reason = sanitize_input(" ".join(context.args[1:]),200)
    if uid in ADMIN_IDS:
        await update.message.reply_text(box_message("HATA","Admin banlanamaz!","\u274c"), parse_mode=ParseMode.HTML); return
    db.ban_user(uid, reason, by_admin=update.effective_user.id)
    db.admin_log(update.effective_user.id, "ban", f"{uid} {reason}")
    await update.message.reply_text(box_message("BANLANDI", f"ID: <code>{uid}</code>\nNeden: {reason or '-'}\nTarih: {datetime.now().strftime('%d.%m.%Y %H:%M')}","\U0001f6ab"), parse_mode=ParseMode.HTML)
@admin_only
async def unban_cmd(update, context):
    if not context.args or not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("KULLANIM","<code>/unban ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    uid = int(context.args[0]); db.unban_user(uid); db.admin_log(update.effective_user.id,"unban",str(uid))
    await update.message.reply_text(box_message("BASARILI", f"Ban kaldirildi: <code>{uid}</code>","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def banlist_cmd(update, context):
    rows = db.get_banned_users()
    if not rows:
        await update.message.reply_text(box_message("BILGI","Banli yok.","\u2705"), parse_mode=ParseMode.HTML); return
    lines = ""
    for u in rows[:30]:
        kim = "Sistem" if not u['ban_by'] else str(u['ban_by'])
        lines += f"\u2022 <code>{u['user_id']}</code> {sanitize_input(u['first_name'] or '', 40)} - {sanitize_input(u['ban_reason'] or '?', 60)} ({u['ban_at'][:10]}, {kim})\n"
    await update.message.reply_text(box_message("BANLI KULLANICILAR", f"{lines}\nToplam: {len(rows)}","\U0001f6ab"), parse_mode=ParseMode.HTML)
@admin_only
async def banara_cmd(update, context):
    if not context.args:
        await update.message.reply_text(box_message("KULLANIM","<code>/banara ID veya isim</code>","\U0001f50d"), parse_mode=ParseMode.HTML); return
    res = db.search_banned(sanitize_input(" ".join(context.args),50))
    if not res:
        await update.message.reply_text(box_message("SONUC","Eslesen engelli yok.","\U0001f50d"), parse_mode=ParseMode.HTML); return
    kb = [[InlineKeyboardButton(_ban_label(u), callback_data=f"apban_view_{u['user_id']}")] for u in res[:BAN_PAGE_SIZE]]
    kb.append([InlineKeyboardButton("\U0001f3e0 Ana Menu", callback_data="ap_main")])
    await update.message.reply_text(box_message("ARAMA SONUCU", f"{len(res)} engelli bulundu \U0001f447","\U0001f50d"), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))

@admin_only
async def userinfo_cmd(update, context):
    if not context.args or not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("KULLANIM","<code>/userinfo ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    u = db.get_user(int(context.args[0]))
    if not u:
        await update.message.reply_text(box_message("HATA","Bulunamadi.","\u274c"), parse_mode=ParseMode.HTML); return
    st = "\U0001f6ab Banli" if u['is_banned'] else "\u2705 Aktif"
    seg = SEGMENTS.get(u['segment'] or "", "Kategorisiz")
    ban_d = ""
    if u['is_banned']:
        kim = "Sistem" if not u['ban_by'] else f"Admin {u['ban_by']}"
        ban_d = f"\n<b>Engel:</b> {u['ban_at'][:16].replace('T',' ')} | {u['ban_reason'] or '-'} | {kim}"
    await update.message.reply_text(box_message("KULLANICI DETAY", (
        f"<b>ID:</b> <code>{u['user_id']}</code>\n<b>Ad:</b> {sanitize_input(u['first_name'] or '', 60)} {sanitize_input(u['last_name'] or '', 60)}\n"
        f"<b>Username:</b> @{sanitize_input(u['username'] or 'Yok', 40)}\n<b>Durum:</b> {st}{ban_d}\n"
        f"<b>Kategori:</b> {seg}\n<b>Katilim:</b> {u['joined_at'][:10]}\n<b>Mesaj:</b> {u['total_messages']}"),"\U0001f464"), parse_mode=ParseMode.HTML)
@admin_only
async def userlist_cmd(update, context):
    rows = db.get_all_users()
    lines = "".join([f"\u2022 <code>{u['user_id']}</code> {sanitize_input(u['first_name'] or '', 40)} (@{sanitize_input(u['username'] or 'N/A', 40)})\n" for u in rows[:20]])
    await update.message.reply_text(box_message("SON KULLANICILAR", f"{lines}\nToplam: {len(rows)}","\U0001f465"), parse_mode=ParseMode.HTML)
@admin_only
async def usersearch_cmd(update, context):
    if not context.args:
        await update.message.reply_text(box_message("KULLANIM","<code>/usersearch isim</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    qx = sanitize_input(" ".join(context.args)).lower()
    rows = db.exe("SELECT * FROM users ORDER BY last_active DESC")
    res = [u for u in rows if (u['username'] and qx in u['username'].lower()) or (u['first_name'] and qx in u['first_name'].lower())]
    if not res:
        await update.message.reply_text(box_message("SONUC","Bulunamadi.","\U0001f50d"), parse_mode=ParseMode.HTML); return
    _ban_mark, _ok_mark = "\U0001f6ab", "\u2705"
    lines = "".join([f"{_ban_mark if u['is_banned'] else _ok_mark} <code>{u['user_id']}</code> {sanitize_input(u['first_name'] or '', 40)}\n" for u in res[:15]])
    await update.message.reply_text(box_message("ARAMA", lines, "\U0001f50d"), parse_mode=ParseMode.HTML)
@admin_only
async def topusers_cmd(update, context):
    rows = db.exe("SELECT * FROM users ORDER BY total_messages DESC LIMIT 10")
    medals = ["\U0001f947","\U0001f948","\U0001f949"]
    lines = "".join([f"{medals[i] if i<3 else str(i+1)+'.'} {sanitize_input(u['first_name'] or '', 40)} - {u['total_messages']}\n" for i,u in enumerate(rows)])
    await update.message.reply_text(box_message("EN AKTIF", lines or "Yok","\U0001f3c6"), parse_mode=ParseMode.HTML)
@admin_only
async def export_cmd(update, context):
    rows = db.exe("SELECT * FROM users ORDER BY last_active DESC")
    csv = "ID,Username,Ad,Durum,Kategori,Katilim,Mesaj\n"
    for u in rows:
        csv += f"{u['user_id']},{neutralize_for_file(u['username'] or '')},{neutralize_for_file(u['first_name'])},{'Banli' if u['is_banned'] else 'Aktif'},{neutralize_for_file(u['segment'] or '')},{u['joined_at'][:10]},{u['total_messages']}\n"
    fn = os.path.join(BASE_DIR, f"export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
    with open(fn,'w',encoding='utf-8-sig') as f: f.write(csv)
    with open(fn, 'rb') as fh:
        await update.message.reply_document(document=fh, filename=os.path.basename(fn), caption=f"{len(rows)} kullanici")
@admin_only
async def setseg_cmd(update, context):
    if len(context.args) < 2:
        await update.message.reply_text(box_message("KULLANIM", f"<code>/setseg ID kategori</code>\n{' / '.join(SEGMENTS.keys())} / none","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    if not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("HATA","Gecersiz ID.","\u274c"), parse_mode=ParseMode.HTML); return
    uid = int(context.args[0]); seg = context.args[1].lower()
    if seg in ("none","yok","-"): seg = ""
    elif seg not in SEGMENTS:
        await update.message.reply_text(box_message("HATA","Gecersiz kategori.","\u274c"), parse_mode=ParseMode.HTML); return
    if not db.get_user(uid):
        await update.message.reply_text(box_message("HATA","Kullanici yok.","\u274c"), parse_mode=ParseMode.HTML); return
    db.set_segment(uid, seg); db.admin_log(update.effective_user.id,"setseg",f"{uid} {seg}")
    await update.message.reply_text(box_message("BASARILI", f"<code>{uid}</code>: {SEGMENTS.get(seg,'Kategorisiz')}","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def seglist_cmd(update, context):
    if not context.args or context.args[0].lower() not in SEGMENTS:
        await update.message.reply_text(box_message("KULLANIM", f"<code>/seglist kategori</code>\n{' / '.join(SEGMENTS.keys())}","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    seg = context.args[0].lower(); rows = db.get_users_by_segment(seg)
    if not rows:
        await update.message.reply_text(box_message(SEGMENTS[seg],"Bos.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    lines = "".join([f"\u2022 <code>{u['user_id']}</code> {sanitize_input(u['first_name'] or '', 40)}\n" for u in rows[:30]])
    await update.message.reply_text(box_message(f"{SEGMENTS[seg]} ({len(rows)})", lines, "\U0001f3f7"), parse_mode=ParseMode.HTML)

@admin_only
async def sikayetler_cmd(update, context):
    if context.args and context.args[0].isdigit():
        c = db.get_complaint(int(context.args[0]))
        if not c:
            await update.message.reply_text(box_message("HATA","Bulunamadi.","\u274c"), parse_mode=ParseMode.HTML); return
        txt = box_message(f"SIKAYET #{c['id']}", (
            f"\U0001f464 {harden_text(c['first_name'] or '',80)} (@{c['username'] or 'yok'})\n"
            f"\U0001f194 <code>{c['user_id']}</code>\n\u23f0 {c['created_at'][:16]}\n"
            f"\U0001f4cc {c['status']}\n\n\U0001f4ac {c['message']}\n\n<code>/sikayetkapatildi {c['id']}</code>"),"\U0001f4e8")
        img = c['image_file']
        if img:
            path = os.path.join(COMPLAINTS_IMG_DIR, img)
            if is_safe_path(COMPLAINTS_IMG_DIR, path) and os.path.exists(path):
                with open(path, 'rb') as fh:
                    await update.message.reply_photo(photo=fh, caption=_safe_caption(txt), parse_mode=ParseMode.HTML)
                db.set_complaint_status(c['id'],"okundu"); return
        await update.message.reply_text(txt, parse_mode=ParseMode.HTML); db.set_complaint_status(c['id'],"okundu"); return
    only_new = bool(context.args) and context.args[0].lower() in ("yeni","new")
    rows = db.get_complaints(only_new=only_new, limit=30)
    if not rows:
        await update.message.reply_text(box_message("SIKAYETLER","Yok.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    lines = ""
    for c in rows:
        durum = {"yeni":"\U0001f534","okundu":"\U0001f7e1","cozuldu":"\U0001f7e2"}.get(c['status'],"\u26aa")
        img = " \U0001f5bc" if c['image_file'] else ""
        ozet = (c['message'][:40]+"...") if len(c['message'])>40 else c['message']
        lines += f"{durum} #{c['id']} <code>{c['user_id']}</code>{img}: {ozet}\n"
    await update.message.reply_text(box_message("SIKAYETLER", f"{lines}\n<i>Detay: /sikayetler ID</i>","\U0001f4e8"), parse_mode=ParseMode.HTML)
@admin_only
async def sikayetkapatildi_cmd(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(box_message("KULLANIM","<code>/sikayetkapatildi ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    cid = int(context.args[0])
    if not db.get_complaint(cid):
        await update.message.reply_text(box_message("HATA","Bulunamadi.","\u274c"), parse_mode=ParseMode.HTML); return
    db.set_complaint_status(cid,"cozuldu"); db.admin_log(update.effective_user.id,"complaint_resolved",str(cid))
    await update.message.reply_text(box_message("BASARILI", f"#{cid} cozuldu.","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def sikayetdosya_cmd(update, context):
    rows = db.exe("SELECT * FROM complaints ORDER BY id ASC")
    if not rows:
        await update.message.reply_text(box_message("BILGI","Yok.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    fn = os.path.join(BASE_DIR, f"sikayetler_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
    with open(fn,"w",encoding="utf-8") as f:
        f.write(f"Sikayet Kayitlari - {datetime.now().strftime('%d.%m.%Y %H:%M')}\nToplam: {len(rows)}\n"+"="*50+"\n")
        for r in rows:
            f.write(f"\n#{r['id']} [{r['created_at'][:19]}] {r['status']}\nID:{r['user_id']} {neutralize_for_file(r['first_name'])}\nGorsel:{r['image_file'] or 'yok'}\nMesaj: {neutralize_for_file(r['message'])}\n")
    with open(fn, 'rb') as fh:
        await update.message.reply_document(document=fh, filename=os.path.basename(fn), caption=f"{len(rows)} sikayet")

# --- Zamanli mesaj iptal ---
@admin_only
async def zamanliiptal_cmd(update, context):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(box_message("KULLANIM","<code>/zamanliiptal ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    sid = int(context.args[0])
    # Yalnizca hala BEKLEYEN kayit iptal edilebilir; gonderilmis/iptal kaydin
    # durumunu ezmek gecmisi bozar ve admini yaniltirdi.
    if not db.claim_scheduled(sid):
        sc = db.get_scheduled(sid)
        durum = sc["status"] if sc else "kayit yok"
        await update.message.reply_text(box_message("IPTAL EDILEMEDI",
            f"#{sid} beklemede degil (durum: {durum}).", "\u274c"), parse_mode=ParseMode.HTML)
        return
    db.set_scheduled_status(sid, "iptal")
    db.admin_log(update.effective_user.id, "schedule_cancel", f"#{sid}")
    await update.message.reply_text(box_message("IPTAL", f"Zamanli mesaj #{sid} iptal edildi.","\u2705"), parse_mode=ParseMode.HTML)

# --- Admin yonetimi ---
@admin_only
async def addadmin_cmd(update, context):
    if not context.args or not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("KULLANIM","<code>/addadmin ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    nid = int(context.args[0])
    if nid in ADMIN_IDS:
        await update.message.reply_text(box_message("BILGI","Zaten admin.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    ADMIN_IDS.append(nid); save_admins(ADMIN_IDS); await _apply_commands(context.bot)
    db.admin_log(update.effective_user.id,"add_admin",str(nid))
    await update.message.reply_text(box_message("BASARILI", f"Admin eklendi: <code>{nid}</code>","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def removeadmin_cmd(update, context):
    if not context.args or not is_valid_id(context.args[0]):
        await update.message.reply_text(box_message("KULLANIM","<code>/removeadmin ID</code>","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    rid = int(context.args[0])
    if rid not in ADMIN_IDS:
        await update.message.reply_text(box_message("HATA","Admin degil.","\u274c"), parse_mode=ParseMode.HTML); return
    if len(ADMIN_IDS) <= 1:
        await update.message.reply_text(box_message("HATA","Son admin kaldirilamaz!","\u274c"), parse_mode=ParseMode.HTML); return
    ADMIN_IDS.remove(rid); save_admins(ADMIN_IDS)
    if rid in authenticated_admins: del authenticated_admins[rid]
    # Eski adminin sohbetindeki ADMIN komut listesini Telegram'dan kaldir;
    # yoksa /bildirim, /export gibi komutlar menusunde sonsuza dek gorunur.
    try:
        await context.bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=rid))
    except Exception as exc:
        logger.warning(f"[ADMIN] {rid} komut menusu silinemedi: {exc}")
    db.admin_log(update.effective_user.id, "remove_admin", str(rid))
    await update.message.reply_text(box_message("BASARILI", f"Kaldirildi: <code>{rid}</code>","\u2705"), parse_mode=ParseMode.HTML)
@admin_only
async def adminlist_cmd(update, context):
    _on_mark, _off_mark = " \U0001f7e2", " \u26aa"
    lines = "".join([f"\u2022 <code>{a}</code>{_on_mark if is_session_valid(a) else _off_mark}\n" for a in ADMIN_IDS])
    await update.message.reply_text(box_message("ADMINLER", lines,"\U0001f451"), parse_mode=ParseMode.HTML)
@admin_only
async def botstatus_cmd(update, context):
    s = db.get_stats()
    sup = "\U0001f7e2" if (db.get_setting("support_enabled") or "0")=="1" else "\U0001f534"
    cmp = "\U0001f7e2" if _complaints_enabled() else "\U0001f534"
    await update.message.reply_text(box_message("BOT DURUMU", f"\u2705 Aktif\n\U0001f465 {s['total']} kullanici\n\U0001f451 {len(ADMIN_IDS)} admin\n\U0001f4ac Destek: {sup} | Sikayet: {cmp}","\U0001f916"), parse_mode=ParseMode.HTML)
@admin_only
async def logout_cmd(update, context):
    uid = update.effective_user.id
    if uid in authenticated_admins: del authenticated_admins[uid]
    db.admin_log(uid,"logout")
    context.user_data["admin_kb"] = False
    await update.message.reply_text(box_message("CIKIS","Admin oturumu kapatildi.","\U0001f6aa"),
        parse_mode=ParseMode.HTML, reply_markup=_build_reply_menu())
    await send_giris(update, context)

# --- Loglar ---
_ACTION_TR = {"login_success":"Giris yapti","logout":"Cikis","broadcast":"Toplu mesaj","ban":"Ban","unban":"Ban kaldirdi",
    "setseg":"Kategori atadi","add_admin":"Admin ekledi","remove_admin":"Admin cikardi","schedule_add":"Zamanli mesaj kurdu",
    "dm":"Tekil mesaj","template_send":"Sablon gonderdi","complaint_resolved":"Sikayet cozdu",
    "screenshots_on":"Ekran kaydini acti","screenshots_off":"Ekran kaydini kapatti",
    "screenshot_resolved":"Ekran kaydini kapatti"}
def _atr(a): return _ACTION_TR.get(a, a)

@admin_only
async def dailylog_cmd(update, context):
    if context.args:
        day = context.args[0].strip()
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', day):
            await update.message.reply_text(box_message("HATA","Bicim: /dailylog YYYY-AA-GG","\u274c"), parse_mode=ParseMode.HTML); return
        rows = db.get_admin_logs_for_day(day)
        if not rows:
            await update.message.reply_text(box_message(f"LOG {day}","Kayit yok.","\U0001f4c5"), parse_mode=ParseMode.HTML); return
        lines = "".join([f"\u2022 [{r['created_at'][11:16]}] <code>{r['admin_id']}</code>: {_atr(r['action'])} {r['details'] or ''}\n" for r in rows])
        await update.message.reply_text(box_message(f"LOG {day} ({len(rows)})", lines[:3500],"\U0001f4c5"), parse_mode=ParseMode.HTML); return
    summ = db.get_daily_log_summary(7)
    sl = "".join([f"\u2022 {d}: {c} islem\n" for d,c in summ])
    today = datetime.now().strftime("%Y-%m-%d")
    todays = db.get_admin_logs_for_day(today)
    det = "".join([f"\u2022 [{r['created_at'][11:16]}] {_atr(r['action'])}\n" for r in todays[-15:]]) or "Bugun islem yok."
    await update.message.reply_text(box_message("GUNLUK LOG", f"<b>Son 7 gun:</b>\n{sl}\n<b>Bugun:</b>\n{det}\n<i>/dailylog YYYY-AA-GG, /logfile</i>","\U0001f4c5"), parse_mode=ParseMode.HTML)
@admin_only
async def logfile_cmd(update, context):
    rows = db.exe("SELECT * FROM admin_logs ORDER BY id ASC")
    if not rows:
        await update.message.reply_text(box_message("BILGI","Yok.","\u2139\ufe0f"), parse_mode=ParseMode.HTML); return
    fn = os.path.join(BASE_DIR, f"admin_log_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
    with open(fn,"w",encoding="utf-8") as f:
        f.write(f"Admin Loglari - {datetime.now().strftime('%d.%m.%Y %H:%M')}\nToplam: {len(rows)}\n"+"="*50+"\n")
        for r in rows:
            f.write(f"[{r['created_at'][:19]}] {r['admin_id']}: {_atr(r['action'])} {neutralize_for_file(r['details'] or '')}\n")
    with open(fn, 'rb') as fh:
        await update.message.reply_document(document=fh, filename=os.path.basename(fn), caption=f"{len(rows)} islem")
@admin_only
async def securitylog_cmd(update, context):
    rows = db.exe("SELECT * FROM security_events ORDER BY id DESC LIMIT 20")
    lines = "".join([f"\u2022 [{r['created_at'][11:16]}] {r['event_type']} - {r['user_id']}\n" for r in rows]) or "Yok."
    await update.message.reply_text(box_message("GUVENLIK LOG", lines,"\U0001f6e1"), parse_mode=ParseMode.HTML)

# =====================================================================
# YEDEKLEME (haftalik, ISO hafta)
# =====================================================================
def _week_tag():
    iso = datetime.now().isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"

def weekly_backup_if_needed():
    tag = _week_tag(); folder = os.path.join(BACKUP_DIR, tag)
    if os.path.exists(folder):
        return False, tag
    os.makedirs(folder, exist_ok=True)
    # WAL modundaki canli DB'yi dosya kopyalamak yirtik/acilamaz yedek uretebilir;
    # SQLite'in kendi backup API'si tutarli anlik goruntu alir.
    try:
        with db._lock:
            kaynak = sqlite3.connect(DB_PATH, timeout=10)
            hedef = sqlite3.connect(os.path.join(folder, "hitbet_bot.db"))
            try:
                kaynak.backup(hedef)
            finally:
                hedef.close(); kaynak.close()
    except Exception as e:
        logger.warning(f"[BACKUP] sqlite backup API hatasi ({e}); dosya kopyasina dusuluyor")
        for fn in os.listdir(BASE_DIR):
            if fn.startswith("hitbet_bot.db"):
                try: shutil.copy2(os.path.join(BASE_DIR,fn), os.path.join(folder,fn))
                except: pass
    try:
        rows = db.exe("SELECT * FROM admin_logs ORDER BY id ASC")
        with open(os.path.join(folder,"admin_log.txt"),"w",encoding="utf-8") as f:
            for r in rows: f.write(f"[{r['created_at'][:19]}] {r['admin_id']}: {r['action']} {neutralize_for_file(r['details'] or '')}\n")
    except: pass
    try:
        crows = db.exe("SELECT * FROM complaints ORDER BY id ASC")
        with open(os.path.join(folder,"sikayetler.txt"),"w",encoding="utf-8") as f:
            for r in crows: f.write(f"#{r['id']} [{r['created_at'][:19]}] {r['status']} ID:{r['user_id']}\n{neutralize_for_file(r['message'])}\n\n")
    except: pass
    try:
        if os.path.isdir(COMPLAINTS_IMG_DIR):
            imgs = [x for x in os.listdir(COMPLAINTS_IMG_DIR) if not x.startswith('.')]
            if imgs:
                dest = os.path.join(folder,"complaint_images"); os.makedirs(dest, exist_ok=True)
                for im in imgs:
                    try: shutil.copy2(os.path.join(COMPLAINTS_IMG_DIR,im), os.path.join(dest,im))
                    except: pass
    except: pass
    logger.info(f"[BACKUP] {tag} alindi")
    return True, tag

@admin_only
async def backups_cmd(update, context):
    folders = sorted([d for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR,d))], reverse=True)
    if not folders:
        await update.message.reply_text(box_message("YEDEKLER","Yok.","\U0001f4be"), parse_mode=ParseMode.HTML); return
    lines = "".join([f"\u2022 {f} ({len(os.listdir(os.path.join(BACKUP_DIR,f)))} dosya)\n" for f in folders[:15]])
    await update.message.reply_text(box_message("YEDEKLER", f"{lines}\nBu hafta: {_week_tag()}\n<i>/backupnow</i>","\U0001f4be"), parse_mode=ParseMode.HTML)


@admin_only
async def siteseg_cmd(update, context):
    """Site ID listesine toplu segment atar: /siteseg platin 12345 67890"""
    args = context.args or []
    if len(args) < 2 or args[0].lower() not in SEGMENTS:
        kademeler = ", ".join(SEGMENTS)
        await update.message.reply_text(box_message("KULLANIM",
            f"<code>/siteseg KADEME ID1 ID2 ...</code>\nKademeler: {kademeler}\n"
            f"Ornek: <code>/siteseg platin 12345 67890</code>", "\u2139\ufe0f"), parse_mode=ParseMode.HTML)
        return
    kademe = args[0].lower()
    site_ids, gecersiz = [], []
    for parca in args[1:]:
        v = validate_site_id(parca)
        (site_ids if v else gecersiz).append(v or parca[:20])
    site_ids = list(dict.fromkeys(site_ids))[:500]
    eslesen = db.get_users_by_site_ids(site_ids)
    atanan_idler = set()
    for u in eslesen:
        db.set_segment(u["user_id"], kademe)
        r = db.get_site_id_record(u["user_id"])
        if r:
            atanan_idler.add(r["site_id"].lower())
    eksik, banli = [], []
    for s_id in site_ids:
        if s_id.lower() in atanan_idler:
            continue
        (banli if db.find_by_site_id(s_id) else eksik).append(s_id)
    db.admin_log(update.effective_user.id, "siteseg", f"{kademe} ok:{len(eslesen)}")
    rapor = f"\u2705 {len(eslesen)} uye {SEGMENTS[kademe]} yapildi."
    if eksik:
        rapor += f"\n\u26a0\ufe0f Bota bagli olmayan {len(eksik)} ID atlandi: {', '.join(eksik[:10])}"
    if banli:
        rapor += f"\n\U0001f6b7 Banli oldugu icin atlanan {len(banli)} ID: {', '.join(banli[:10])} (/unban ile acilir)"
    if gecersiz:
        rapor += f"\n\u274c Gecersiz bicim: {', '.join(sanitize_input(g, 20) for g in gecersiz[:5])}"
    rapor += "\n\nBu gruba gonderim: /bildirim -> hedefte kademeyi sec."
    await update.message.reply_text(box_message("SITE ID SEGMENT", rapor, "\U0001f3f7"), parse_mode=ParseMode.HTML)

@admin_only
async def kim_cmd(update, context):
    """Site ID kime bagli? /kim 12345"""
    args = context.args or []
    v = validate_site_id(args[0]) if args else None
    if not v:
        await update.message.reply_text(box_message("KULLANIM", "<code>/kim SITEID</code>", "\u2139\ufe0f"), parse_mode=ParseMode.HTML)
        return
    kayitlar = db.find_by_site_id(v)
    if not kayitlar:
        await update.message.reply_text(box_message("BULUNAMADI",
            f"<code>{v}</code> Site ID'si hicbir Telegram hesabina bagli degil.", "\U0001f50e"), parse_mode=ParseMode.HTML)
        return
    satirlar = []
    for r in kayitlar:
        u = db.get_user(r["telegram_id"])
        seg = SEGMENTS.get((u or {}).get("segment") or "", "-")
        durum = "\U0001f6ab BANLI" if (u and u.get("is_banned")) else "\u2705 aktif"
        satirlar.append(f"\U0001f464 {sanitize_input(r['first_name'] or '?', 40)} "
                        f"(@{sanitize_input(r['username'] or 'yok', 32)})\n"
                        f"\U0001f194 Telegram: <code>{r['telegram_id']}</code> | {durum} | {seg}\n"
                        f"\U0001f4c5 Baglama: {str(r['updated_at'])[:16].replace('T', ' ')}")
    await update.message.reply_text(box_message(f"SITE ID: {v}", "\n\n".join(satirlar), "\U0001f50e"),
        parse_mode=ParseMode.HTML)


@admin_only
async def dmid_cmd(update, context):
    """Site ID'ye tekil mesaj: /dmid 12345 Merhaba, bonusun tanimlandi!"""
    args = context.args or []
    v = validate_site_id(args[0]) if args else None
    metin = sanitize_input(" ".join(args[1:]), MAX_BROADCAST_LENGTH) if len(args) > 1 else ""
    if not v or not metin:
        await update.message.reply_text(box_message("KULLANIM",
            "<code>/dmid SITEID mesaj</code>\nOrnek: <code>/dmid 12345 Bonusun tanimlandi! \U0001f381</code>", "\u2139\ufe0f"),
            parse_mode=ParseMode.HTML)
        return
    kayitlar = db.find_by_site_id(v)
    if not kayitlar:
        await update.message.reply_text(box_message("BULUNAMADI",
            f"<code>{v}</code> Site ID'si hicbir Telegram hesabina bagli degil. Kontrol: /kim {v}", "\U0001f50e"),
            parse_mode=ParseMode.HTML)
        return
    ok, hata = 0, ""
    for r in kayitlar:
        if db.is_banned(r["telegram_id"]):
            hata = "kullanici BANLI (/unban " + str(r["telegram_id"]) + " ile acilir)"
            continue
        try:
            await context.bot.send_message(chat_id=r["telegram_id"], text=metin, parse_mode=ParseMode.HTML)
            ok += 1
        except Exception as e:
            hata = sanitize_input(str(e), 150)
    db.admin_log(update.effective_user.id, "dmid", f"{v} ok:{ok}")
    if ok:
        await update.message.reply_text(box_message("GONDERILDI",
            f"✅ Site ID <code>{v}</code> uyesine iletildi.", "\U0001f4e9"), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(box_message("GONDERILEMEDI",
            f"❌ Iletilemedi: {hata or 'kullanici botu engellemis olabilir'}", "\u26a0\ufe0f"), parse_mode=ParseMode.HTML)

@admin_only
async def menukur_cmd(update, context):
    """Komut menusunu (⌘) Telegram'a yeniden kurar ve canli sonucu gosterir."""
    await update.message.reply_text(box_message("MENU KURULUYOR", "Komut menusu Telegram'a yeniden kaydediliyor...", "⏳"), parse_mode=ParseMode.HTML)
    sonuclar = await _apply_commands(context.bot)
    rapor = "\n".join(sanitize_input(s, 200) for s in sonuclar[:12])
    await update.message.reply_text(box_message("MENU KURULDU",
        f"{rapor}\n\n\u26a0\ufe0f Telegram menuyu ONBELLEGE alir: sohbeti kapat-ac; "
        f"webde Ctrl+F5; telefonda uygulamayi tamamen kapatip ac. "
        f"Mesaj kutusuna / yazinca liste geliyorsa kayit tamamdir.", "\u2705"), parse_mode=ParseMode.HTML)

@admin_only
async def backupnow_cmd(update, context):
    done, tag = await asyncio.to_thread(weekly_backup_if_needed); db.admin_log(update.effective_user.id,"manual_backup",tag)
    msg = f"\u2705 {tag} yedeklendi." if done else f"\u2139\ufe0f {tag} zaten yedekli."
    await update.message.reply_text(box_message("YEDEK", msg,"\U0001f4be"), parse_mode=ParseMode.HTML)

# =====================================================================
# KULLANICI SERBEST MESAJ + FOTO
# =====================================================================
# Akilli destek yonlendirme: kullanicinin serbest mesaji analiz edilir,
# uygun destek kanalinin linki onerilir. (anahtar kelimeler, ayar_linki, etiket)
# =====================================================================
# YERLESIK ASISTAN — dis yapay zeka servisi OLMADAN niyet analizi.
# Kullanicinin elle yazdigi her mesaj: normalize edilir (Turkce karakter +
# kucuk harf), kelimelere bolunur, yazim hatasi toleransiyla (difflib)
# niyet tablosuna puanlanir; niyet yoksa SSS sorularinda en iyi eslesme
# aranir; o da yoksa destek merkezi onerilir. Tamamen cevrimdisi calisir.
# =====================================================================
import difflib as _difflib

_TR_ASCII = str.maketrans("çğıöşüâîûÇĞİÖŞÜ", "cgiosuaiuCGIOSU")

def _normalize_tr(text):
    """kucult + Turkce karakterleri sadelestir + kelimelere ayir."""
    duz = (text or "").translate(_TR_ASCII).lower()
    return re.findall(r"[a-z0-9]+", duz)

def _fuzzy_token(token, kelime):
    """Tek kelime eslesmesi: tam, govde icermesi veya %84+ benzerlik."""
    if token == kelime:
        return True
    if len(kelime) >= 3 and (kelime in token or token in kelime):
        return True
    if len(kelime) >= 4 and abs(len(token) - len(kelime)) <= 2:
        return _difflib.SequenceMatcher(None, token, kelime).ratio() >= 0.84
    return False

# Niyet tablosu: kelime -> agirlik. Toplam puan ESIK'i (3) gecen en yuksek
# niyet kazanir. Coklu-kelime obekleri metnin tamaminda aranir (agirlik 3).
_INTENTS = [
    {"key": "cekim", "esik": 3,
     "kelimeler": {"cekim": 3, "cekemiyorum": 3, "cekemedim": 3, "cekilmiyor": 3,
                   "yatmadi": 2, "gelmedi": 2, "param": 1, "havale": 2, "iban": 2,
                   "odenmedi": 2, "bekliyor": 1, "onaylanmadi": 2},
     "obekler": ("param gelmedi", "para gelmedi", "para cek", "cekim talebi"),
     "baslik": "PARA ÇEKİM",
     "cevap": "Para çekimiyle ilgili sana en hızlı <b>Çekim Destek</b> ekibi yardımcı olur 👇",
     "link_ayar": "withdraw_support_link", "link_yazi": "💸 Çekim Destek"},
    {"key": "yatirim", "esik": 3,
     "kelimeler": {"yatiramiyorum": 3, "yatiramadim": 3, "yatirim": 2, "yatirma": 2,
                   "odeme": 2, "kart": 1, "kredi": 1, "papara": 2, "payfix": 2,
                   "kabul": 1, "gecmiyor": 2},
     "obekler": ("para yatir", "yatirim yap", "odeme yap"),
     "baslik": "PARA YATIRMA",
     "cevap": "Yatırım sorununda sana en hızlı <b>Ödeme Destek</b> ekibi yardımcı olur 👇",
     "link_ayar": "deposit_support_link", "link_yazi": "💳 Ödeme Destek",
     "ek_buton": ("deposit_link", "💰 Para Yatır Sayfası")},
    {"key": "bonus", "esik": 3,
     "kelimeler": {"bonus": 3, "bonusum": 3, "freespin": 3, "cevrim": 2,
                   "tanimlanmadi": 2, "alamadim": 2, "gelmedi": 1, "deneme": 1,
                   "kayip": 1, "promosyon": 2},
     "obekler": ("bonus alamadim", "bonus gelmedi", "free spin", "deneme bonusu", "kayip bonusu"),
     "baslik": "BONUS",
     "cevap": "Bonus konusunda sana en hızlı <b>Bonus Destek</b> ekibi yardımcı olur.\nGüncel bonusları da menüden görebilirsin 👇",
     "link_ayar": "bonus_support_link", "link_yazi": "🎁 Bonus Destek",
     "cb_buton": ("um_cat_bonus", "🎁 Güncel Bonuslar")},
    {"key": "giris", "esik": 3,
     "kelimeler": {"giremiyorum": 3, "acilmiyor": 3, "giris": 2, "adres": 2,
                   "link": 1, "engel": 2, "erisim": 2, "dns": 2, "site": 1,
                   "guncel": 1, "acilmadi": 3},
     "obekler": ("siteye giremiyorum", "site acilmiyor", "guncel giris", "giris adresi"),
     "baslik": "SİTEYE GİRİŞ",
     "cevap": "Site adresi zaman zaman güncellenir; <b>güncel giriş</b> her zaman aşağıdaki butondadır 👇",
     "link_ayar": "giris_link", "link_yazi": "🔗 Güncel Giriş"},
    {"key": "kayit", "esik": 3,
     "kelimeler": {"kayit": 3, "uyelik": 3, "uye": 2, "hesap": 2, "acmak": 1,
                   "olusturmak": 1, "kaydol": 3},
     "obekler": ("uye ol", "hesap ac", "kayit ol", "nasil uye"),
     "baslik": "ÜYELİK",
     "cevap": "Hemen üye olmak için aşağıdaki butonu kullanabilirsin 👇",
     "link_ayar": "register_link", "link_yazi": "🔥 Hemen Üye Ol"},
    {"key": "turnuva", "esik": 3,
     "kelimeler": {"turnuva": 3, "turnuvalar": 3, "odul": 1, "havuz": 1,
                   "siralama": 2, "katilim": 1, "yaris": 2},
     "obekler": ("odul havuzu", "nasil katilirim"),
     "baslik": "TURNUVALAR",
     "cevap": "Aktif turnuvaları, ödül havuzlarını ve katılım şartlarını menüden görebilirsin 👇",
     "cb_buton": ("um_cat_turnuva", "🏆 Turnuvalar")},
    {"key": "kampanya", "esik": 3,
     "kelimeler": {"kampanya": 3, "kampanyalar": 3, "etkinlik": 2, "cekilis": 2,
                   "firsat": 2, "guncel": 1},
     "obekler": ("hangi kampanyalar", "kampanya var"),
     "baslik": "KAMPANYALAR",
     "cevap": "Tüm güncel kampanyalar ana menüde kategorilere ayrılmış hâlde 👇",
     "cb_buton": ("um_main", "🏠 Ana Menü")},
    {"key": "siteid", "esik": 3,
     "kelimeler": {"id": 2, "kimlik": 2},
     "obekler": ("site id", "id gir", "id nasil", "uyelik id", "id degistir"),
     "baslik": "SİTE ID",
     "cevap": "Site ID'ni <b>🤴 Profil</b> menüsünden girebilir veya değiştirebilirsin: /profil yaz ya da alttaki menüden Profil'e dokun.",
     "cb_buton": ("um_main", "🏠 Ana Menü")},
    {"key": "miniapp", "esik": 3,
     "kelimeler": {"miniapp": 3, "uygulama": 2, "app": 2},
     "obekler": ("mini app", "mini uygulama"),
     "baslik": "MİNİ APP",
     "cevap": "Mini App'e ana menüdeki 📱 butonundan tek dokunuşla ulaşabilirsin 👇",
     "cb_buton": ("um_main", "🏠 Ana Menü")},
    {"key": "selam", "esik": 3,
     "kelimeler": {"merhaba": 3, "selam": 3, "gunaydin": 3, "iyi": 1,
                   "aksamlar": 2, "naber": 3, "nasilsin": 3, "tesekkur": 3,
                   "tesekkurler": 3, "sagol": 3, "eyvallah": 3},
     "obekler": (),
     "baslik": "MERHABA 👋",
     "cevap": "Hoş geldin! Sana nasıl yardımcı olabilirim?\n\nDerdini yazman yeterli: örn. <i>\"param gelmedi\"</i>, <i>\"bonus alamadım\"</i>, <i>\"siteye giremiyorum\"</i>...",
     "cb_buton": ("um_main", "🏠 Ana Menü")},
    {"key": "sikayet", "esik": 3,
     "kelimeler": {"sikayet": 3, "sikayetim": 3, "magdur": 2, "dolandirildim": 3},
     "obekler": ("sikayet etmek",),
     "baslik": "ŞİKAYET",
     "cevap": "Şikayetini kayda almak için /sikayet yazabilirsin; foto da ekleyebilirsin. Ekibimiz en kısa sürede döner.",
     "cb_buton": ("um_destek", "💬 Canlı Destek")},
]

_SMART_LINK_DEFAULTS = {
    "withdraw_support_link": lambda: DEFAULT_WITHDRAW_SUPPORT_LINK,
    "deposit_support_link": lambda: DEFAULT_DEPOSIT_SUPPORT_LINK,
    "bonus_support_link": lambda: DEFAULT_BONUS_SUPPORT_LINK,
    "giris_link": lambda: DEFAULT_GIRIS_LINK,
    "register_link": lambda: DEFAULT_REGISTER_LINK,
    "deposit_link": lambda: DEFAULT_DEPOSIT_LINK,
}

def _intent_link(ayar):
    try:
        link = (db.get_setting(ayar) or "").strip()
    except Exception:
        link = ""
    if not link and ayar in _SMART_LINK_DEFAULTS:
        link = (_SMART_LINK_DEFAULTS[ayar]() or "").strip()
    if not link:
        try:
            link = (db.get_setting("support_link") or DEFAULT_SUPPORT_LINK or "").strip()
        except Exception:
            link = ""
    return link if is_valid_url(link) else ""

def _analyze_intent(raw):
    """(niyet, puan) dondurur; esigi gecen en yuksek puanli niyet, yoksa None."""
    tokens = _normalize_tr(raw)
    if not tokens:
        return None, 0
    metin = " ".join(tokens)
    en_iyi, en_puan = None, 0
    for niyet in _INTENTS:
        puan = 0
        for kelime, agirlik in niyet["kelimeler"].items():
            if any(_fuzzy_token(t, kelime) for t in tokens):
                puan += agirlik
        for obek in niyet["obekler"]:
            if obek in metin:
                puan += 3
        if puan >= niyet["esik"] and puan > en_puan:
            en_iyi, en_puan = niyet, puan
    return en_iyi, en_puan

def _faq_best_match(raw):
    """SSS sorularinda en iyi eslesme: (faq, skor). Skor<esik ise (None, 0)."""
    try:
        faqs = db.list_faqs()
    except Exception:
        return None, 0.0
    tokens = _normalize_tr(raw)
    if not tokens or not faqs:
        return None, 0.0
    metin = " ".join(tokens)
    en_iyi, en_skor = None, 0.0
    for f in faqs:
        soru_tokens = _normalize_tr(f.get("question") or "")
        if not soru_tokens:
            continue
        ortak = sum(1 for t in set(tokens) if any(_fuzzy_token(t, s) for s in soru_tokens))
        kapsama = ortak / max(1, len(set(soru_tokens)))
        benzerlik = _difflib.SequenceMatcher(None, metin, " ".join(soru_tokens)).ratio()
        skor = max(kapsama, benzerlik)
        if skor > en_skor:
            en_iyi, en_skor = f, skor
    return (en_iyi, en_skor) if en_skor >= 0.55 else (None, 0.0)

async def _assistant_reply(update, context, raw):
    """Serbest metni analiz et ve yonlendir. True = cevap verildi."""
    user = update.effective_user
    niyet, puan = _analyze_intent(raw)
    if niyet:
        rows = []
        if niyet.get("link_ayar"):
            link = _intent_link(niyet["link_ayar"])
            if link:
                rows.append([InlineKeyboardButton(niyet.get("link_yazi", "🔗 Bağlantı"), url=link)])
        ek = niyet.get("ek_buton")
        if ek:
            ek_link = _intent_link(ek[0])
            if ek_link:
                rows.append([InlineKeyboardButton(ek[1], url=ek_link)])
        cb = niyet.get("cb_buton")
        if cb:
            rows.append([InlineKeyboardButton(cb[1], callback_data=cb[0])])
        if not any(b.callback_data == "um_destek" for r in rows for b in r if b.callback_data):
            rows.append([InlineKeyboardButton("💬 Canlı Destek", callback_data="um_destek")])
        try:
            db.log(user.id, "smart_route", f"{niyet['key']}:{puan}")
        except Exception:
            pass
        await update.message.reply_text(box_message(niyet["baslik"], niyet["cevap"], "🤖"),
            parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))
        return True
    faq, skor = _faq_best_match(raw)
    if faq:
        text = (f"🤖 Sorunla eşleşen cevabı buldum:\n\n❓ <b>{faq['question']}</b>\n\n"
                f"{render_rich_tokens(render_clickable_tokens(faq['answer']))}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❓ Tüm Sorular", callback_data="um_faq"),
                                    InlineKeyboardButton("💬 Canlı Destek", callback_data="um_destek")]])
        try:
            db.log(user.id, "smart_route", f"faq:{faq['id']}")
        except Exception:
            pass
        await update.message.reply_text(text, parse_mode=ParseMode.HTML,
            reply_markup=kb, disable_web_page_preview=True)
        return True
    # Hicbir sey eslesmedi: kibar yonlendirme (destek merkezi)
    metin, kb = _destek_screen()
    await update.message.reply_text(
        box_message("SENİ TAM ANLAYAMADIM 🤖",
            "Birkaç kelimeyle derdini yazarsan doğru yere yönlendiririm:\n"
            "<i>\"param gelmedi\"</i>, <i>\"yatıramıyorum\"</i>, <i>\"bonus alamadım\"</i>, "
            "<i>\"siteye giremiyorum\"</i>...\n\nya da doğrudan ekiplerimize ulaş 👇", "🧭"),
        parse_mode=ParseMode.HTML, reply_markup=kb)
    return True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alt klavye menusu butonlarini ve akilli destek yonlendirmesini isler;
    diger metinler yalnizca oturumu acik yoneticiler icin panel acar,
    kalanlar sessizce yok sayilir."""
    user = update.effective_user
    raw = (getattr(update.message, "text", "") or "").strip()
    low = raw.lower()
    chat = update.effective_chat
    is_private = getattr(chat, "type", "") == "private"
    # ADMIN alt klavyesi: beyaz listedeki adminde admin etiketleri ONCE calisir
    # (Duyurular/Kampanyalar gibi cakisan adlar admin ekranina gider).
    # Oturum dolmus olsa bile tuslar asistana/kullanici ekranina DUSMEZ:
    # Cikis tusu klavyeyi toplar, digerleri /admin hatirlatmasi yapar.
    if is_private and raw and len(raw) <= 40 and user.id in ADMIN_IDS \
            and not context.user_data.get("wizard_lock"):
        admin_aksiyon = _match_admin_label(low)
        if admin_aksiyon:
            if is_authenticated(user.id):
                return await _admin_menu_action(admin_aksiyon, update, context)
            if admin_aksiyon == "cikis":
                context.user_data["admin_kb"] = False
                await update.message.reply_text(box_message("CIKIS",
                    "Oturum zaten kapali; kullanici menusune donuldu.", "\U0001f6aa"),
                    parse_mode=ParseMode.HTML, reply_markup=_build_reply_menu())
                return
            await update.message.reply_text(box_message("OTURUM DOLDU",
                "Admin oturumun sona ermis. /admin yazip yeniden giris yap;\n"
                "kullanici menusune donmek icin \U0001f6aa Çıkış tusuna bas.", "⏳"),
                parse_mode=ParseMode.HTML)
            return
    # Alt menu butonlari: temizlenmis TAM eslesme (serbest cumleler tetiklemez)
    if is_private and raw and len(raw) <= 40:
        action = _match_menu_label(low)
        if action == "kampanya":
            if await guard_flood(update, context, content=raw):
                return
            if _cb_throttled(user.id, "menu_kampanya", 10):
                return
            return await send_campaign_media(context, chat.id)
        _ACTION_CMDS = {"menu": menu_cmd, "profil": profil_cmd, "destek": destek_cmd,
            "giris": giris_cmd, "miniapp": miniapp_cmd, "bonuslar": bonuslar_cmd,
            "yeniuye": yeniuye_cmd, "slot": slot_cmd, "spor": spor_cmd,
            "banaozel": banaozel_cmd, "turnuvalar": turnuvalar_cmd,
            "parayatir": parayatir_cmd, "paracek": paracek_cmd,
            "duyurular": duyurular_cmd, "sss": sss_cmd}
        if action in _ACTION_CMDS:
            return await _ACTION_CMDS[action](update, context)
    # YERLESIK ASISTAN: yonetici olmayan kullanicinin elle yazdigi HER mesaj
    # analiz edilir (niyet -> SSS -> destek merkezi). Dis servis kullanilmaz.
    if is_private and raw and 2 <= len(raw) <= 300 and not is_authenticated(user.id):
        if await guard_flood(update, context, content=raw):
            return
        if _cb_throttled(user.id, "smart_support", 6):
            return
        return await _assistant_reply(update, context, raw)
    if not is_authenticated(user.id):
        return
    # Acik sihirbaz varken (or. medya bekleyen adimda yazi yazildi) panel dokmek
    # yerine yol goster; sihirbaz beklemede kalmaya devam eder.
    if context.user_data.get("wizard_lock"):
        await update.message.reply_text(box_message("SIHIRBAZ ACIK",
            "Su an acik bir sihirbaz var. Istenen icerigi gonderin ya da /iptal yazin.", "🧭"),
            parse_mode=ParseMode.HTML)
        return
    await show_admin_panel(update, context)

async def _kutuphaneye_ekle(context, chat_id, user, media_type, media_id, raw_caption=""):
    """Admin medyasini kutuphaneye ekler ve aktif kampanya medyasi yapar (eski davranis).
    Hem serbest video gonderiminden hem de foto secenek menusunden cagrilir."""
    raw_name = _CTRL_CHARS.sub("", raw_caption or "").strip()[:60]
    label = "Video" if media_type == "video" else "Foto"
    name = raw_name or f"{label} {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    media_pk = db.add_campaign_media(media_type, media_id, name, user.id)
    row = db.get_campaign_media(media_pk)
    activate_campaign_media_record(row)
    db.admin_log(user.id, "upload_campaign_media", f"{media_type} #{media_pk}")
    kb = [[InlineKeyboardButton("👁 Kaydi Gor", callback_data=f"apmedia_view_{media_pk}"),
           InlineKeyboardButton("🗂 Kutuphane", callback_data="apmedia_page_0")]]
    await context.bot.send_message(chat_id=chat_id, text=box_message("KUTUPHANEYE EKLENDI",
        f"{label} <b>#{media_pk}</b> olarak kaydedildi ve aktif kampanya medyasi yapildi.\n\nYeni foto/video gondererek baska kayitlar ekleyebilir; sonra kutuphaneden istediginizi secebilirsiniz.","\u2705"),
        parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb))
    return media_pk

async def handle_campaign_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin serbest medya: video dogrudan kutuphaneye gider. Fotolar ekran goruntusu
    sihirbazinin giris noktasinda secenek menusuyle karsilanir (ss_photo_entry);
    burasi yalnizca oraya dusmeyen durumlar icin yedek yoldur."""
    user = update.effective_user
    if not is_authenticated(user.id):
        return
    if context.user_data.get("wizard_lock"):
        await update.message.reply_text(box_message("SIHIRBAZ ACIK",
            "Medya kutuphaneye EKLENMEDI: su an acik bir sihirbaz var. Once onu bitirin ya da /iptal yazin.", "⚠️"),
            parse_mode=ParseMode.HTML)
        return

    if update.message.video:
        media_id = update.message.video.file_id
        media_type = "video"
    elif update.message.photo:
        media_id = update.message.photo[-1].file_id
        media_type = "photo"
    else:
        return
    await _kutuphaneye_ekle(context, update.effective_chat.id, user, media_type, media_id, update.message.caption)

_conflict_notified = {"done": False}

async def error_handler(update, context):
    from telegram.error import Conflict
    if isinstance(context.error, Conflict):
        # Ayni token ile ikinci bir bot sureci calisiyor demektir.
        logger.error("[CAKISMA] Ayni token ile BIRDEN FAZLA bot calisiyor! Diger kopyayi kapatin.")
        print("🚨 CAKISMA: Bu token ile ayni anda baska bir bot daha calisiyor! Eski pencereyi/sunucuyu kapatin.")
        if not _conflict_notified["done"]:
            _conflict_notified["done"] = True
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=aid, text=box_message("UYARI: CIFT BOT CALISIYOR",
                        "Bu token ile ayni anda birden fazla bot calisiyor! Mesajlar iki kopya arasinda rastgele bolusulur.\n\nEski calisan kopyayi (diger pencere/sunucu) kapatin.", "🚨"),
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
        return
    logger.error(f"Hata: {context.error}")

# =====================================================================
# KOMUTLAR VE SOL ALT PLAY MENU BUTONU
# =====================================================================
def _parse_user_commands():
    """config USER_COMMANDS'tan kullanici menusunu okur (komut:aciklama, virgulle).

    Ornek: USER_COMMANDS=start:🚀 Başla, profil:🤴 Profil, destek:💬 Canlı Destek
    Bos veya hatali ise yerlesik varsayilan liste kullanilir.
    """
    cmds = []
    raw = config.get("USER_COMMANDS", "").strip()
    if raw:
        for part in raw.split(","):
            if ":" not in part:
                continue
            name, desc = part.split(":", 1)
            name = name.strip().lstrip("/").lower()
            desc = desc.strip()[:256]
            if re.fullmatch(r"[a-z0-9_]{1,32}", name) and desc:
                cmds.append(BotCommand(name, desc))
    if not cmds:
        cmds = [
            BotCommand("start", "\U0001f680 Başla"),
            BotCommand("menu", "\U0001f3e0 Ana Menü"),
            BotCommand("giris", "\U0001f3e0 Siteye Giriş"),
            BotCommand("miniapp", "\U0001f4f1 Mini App"),
            BotCommand("bonuslar", "\U0001f381 Güncel Bonuslar"),
            BotCommand("yeniuye", "\U0001f195 Yeni Üye Bonusları"),
            BotCommand("slot", "\U0001f3b0 Slot Kampanyaları"),
            BotCommand("spor", "⚽ Spor Bonusları"),
            BotCommand("banaozel", "⭐ Bana Özel Kampanyalar"),
            BotCommand("turnuvalar", "\U0001f3c6 Turnuvalar"),
            BotCommand("parayatir", "\U0001f4b0 Para Yatır"),
            BotCommand("paracek", "\U0001f4b8 Para Çek"),
            BotCommand("duyurular", "\U0001f4e2 Duyurular"),
            BotCommand("sss", "❓ Sık Sorulan Sorular"),
            BotCommand("destek", "\U0001f4ac Canlı Destek"),
            BotCommand("profil", "\U0001f934 Profil"),
            BotCommand("ekran", "\U0001f4f8 Ekran Görüntüsü Gönder"),
            BotCommand("iptal", "❌ İşlemi iptal et"),
        ]
    return cmds[:25]

async def _apply_commands(bot):
    """Komut menusunu Telegram'a kaydeder; her adimin sonucunu rapor listesi olarak dondurur."""
    results = []
    # Kullanici komut menusu: "/" yazinca, saginda cikan ⌘ simgesinde ve bot profilinde gorunur.
    # Sol altta ayrica Play web-app butonu bulunur.
    user_cmds = _parse_user_commands()
    # Bazi istemciler Default yerine AllPrivateChats kapsamini okur;
    # menu simgesinin HER istemcide gorunmesi icin ikisine birden kaydet.
    for scope_name, scope in (("Default", BotCommandScopeDefault()),
                              ("Ozel sohbetler", BotCommandScopeAllPrivateChats())):
        try:
            await bot.set_my_commands(user_cmds, scope=scope)
            results.append(f"✅ Kullanici komut menusu ({scope_name}): {len(user_cmds)} komut kaydedildi")
            logger.info(f"[CMD] kullanici menusu ayarlandi ({scope_name})")
        except Exception as e:
            results.append(f"❌ Kullanici komut menusu ({scope_name}): {e}")
            logger.warning(f"[CMD] kullanici menusu ({scope_name}): {e}")

    # Admin komutlari yalnizca beyaz listedeki sohbetlere ozel kalir.
    # "/" menusunde panel disinda en sik kullanilan yonetim komutlari da listelenir.
    admin_cmds = [
        BotCommand("admin", "\U0001f6e0 Yönetici paneli"),
        BotCommand("kampanyaekle", "➕ Kampanya / turnuva ekle"),
        BotCommand("duyuruekle", "\U0001f4e2 Duyuru paylaş"),
        BotCommand("bildirim", "\U0001f4e3 Bildirim gönder (toplu mesaj)"),
        BotCommand("botstatus", "\U0001f4c8 Bot durumu"),
        BotCommand("userlist", "\U0001f465 Son kullanıcılar"),
        BotCommand("banlist", "\U0001f6ab Engelli listesi"),
        BotCommand("export", "\U0001f4e4 Kullanıcı dışa aktar"),
        BotCommand("backupnow", "\U0001f4be Hemen yedek al"),
        BotCommand("menukur", "\U0001f4cb Komut menusunu yeniden kur"),
        BotCommand("siteseg", "\U0001f3f7 Site ID listesine segment ata"),
        BotCommand("kim", "\U0001f50e Site ID kime bagli?"),
        BotCommand("dmid", "\U0001f4e9 Site ID uyesine tekil mesaj"),
        BotCommand("zamanliiptal", "\U0001f4c5 Zamanlı mesaj iptali"),
        BotCommand("ekranlar", "\U0001f4f8 Ekran görüntüsü kayıtları"),
        BotCommand("logout", "\U0001f6aa Yönetici çıkışı"),
    ] + user_cmds
    for aid in ADMIN_IDS:
        try:
            await bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=aid))
            results.append(f"✅ Admin komut menusu ({aid}): {len(admin_cmds)} komut")
        except Exception as e:
            # Admin bota hic /start yazmadiysa Telegram bu sohbeti taniyamaz.
            results.append(f"❌ Admin menusu ({aid}): {e} — once bota /start yazin")
            logger.warning(f"[CMD] {aid}: {e}")

    # GERI OKUMA DOGRULAMASI: Telegram'in gercekte ne kaydettigini goster.
    try:
        check = await bot.get_my_commands(scope=BotCommandScopeAllPrivateChats())
        if not check:
            check = await bot.get_my_commands(scope=BotCommandScopeDefault())
        listed = ", ".join("/" + c.command for c in check) or "(bos!)"
        results.append(f"\U0001f50e Telegram dogrulamasi — kullanici menusu: {listed}")
    except Exception as e:
        results.append(f"\U0001f50e Dogrulama okunamadi: {e}")

    play_ok = await _apply_play_menu_buttons(bot)
    if MENU_BUTTON_MODE == "menu":
        results.append("✅ Sol alt buton: KOMUT MENUSU (⌘ simgesi gorunur)" if play_ok
                       else "⚠️ Menu butonu ayarlanamadi (bot.log: [PLAY MENU])")
    elif play_ok == "fallback":
        results.append("⚠️ Play linki gecersiz (https zorunlu) — KOMUT MENUSUNE donuldu")
    else:
        results.append("✅ Sol alt buton: PLAY (web Telegram'da ⌘ simgesini gizler!)" if play_ok
                       else "⚠️ Play butonu ayarlanamadi (bot.log: [PLAY MENU])")

    # Bot profilindeki "What can this bot do?" tanitim alanlari
    desc = config.get("BOT_DESCRIPTION", "").replace("\\n", "\n").strip()
    short = config.get("BOT_SHORT_DESCRIPTION", "").strip()
    try:
        if desc:
            try:
                await bot.set_my_description(description=desc[:512])
            except Exception as exc:
                logger.warning(f"[TANITIM] description: {exc}")
        if short:
            await bot.set_my_short_description(short_description=short[:120])
        if desc or short:
            results.append("✅ Bot tanitim yazisi guncellendi")
    except Exception as e:
        results.append(f"⚠️ Tanitim yazisi ayarlanamadi: {e}")
    return results

# =====================================================================
# ZAMANLI MESAJ + YEDEK JOB
# =====================================================================
def _sched_preview_text(sc, payload):
    """Zamanli mesajin admin onizleme metni: hedef, zaman ve icerik ozeti.

    Ozet etiketsiz uretilir: 500 karakterde kesmek acik HTML etiketi
    birakip Telegram parse hatasina yol acmasin.
    """
    body = re.sub(r"<[^>]+>", "", build_payload_text(payload)) or "(bos metin)"
    if len(body) > 500:
        body = body[:500] + "\u2026"
    media_note = ""
    if payload.get("media_id") or payload.get("image_id"):
        media_note = "\n\U0001f5bc Medya iceriyor (foto/video)."
    btn_note = ""
    if payload.get("btn_text") and payload.get("btn_url"):
        btn_note = f"\n\U0001f518 Buton: {sanitize_input(payload['btn_text'], 40)}"
    return (f"<b>Kayit:</b> #{sc['id']}\n"
            f"\U0001f550 <b>Zaman:</b> {str(sc['run_at'])[:16].replace('T', ' ')}\n"
            f"\U0001f3af <b>Hedef:</b> {target_label(sc['target'] or 'all')}{media_note}{btn_note}\n\n"
            f"\u2014 Bu \u015fekilde payla\u015f\u0131lacak \u2014\n\n{body}")

def _sched_manage_kb(sid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u25b6\ufe0f \u015eimdi G\u00f6nder", callback_data=f"apsched_now_{sid}"),
         InlineKeyboardButton("\ud83d\udd50 Zaman\u0131 De\u011fi\u015ftir", callback_data=f"apschedtime_{sid}")],
        [InlineKeyboardButton("\ud83d\uddd1 \u0130ptal Et", callback_data=f"apsched_del_{sid}"),
         InlineKeyboardButton("\u25c0\ufe0f Zamanl\u0131 Mesajlar", callback_data="ap_sched")],
    ])

def _campaign_audience(segment):
    """Kampanya hedef kitlesi: '' = herkes, oto segment = hesaplanan liste."""
    if not segment:
        return db.get_all_users()
    if segment == "aktif":
        return db.get_active_users(48)
    if segment == "yeni":
        hafta = (datetime.now() - timedelta(days=7)).isoformat()
        return db.exe("SELECT * FROM users WHERE is_banned=0 AND joined_at>? ORDER BY last_active DESC", (hafta,))
    return db.get_users_by_segment(segment)

def _evict_stale_memory():
    """Aylarca calisan botta bir daha donmeyen kullanicilarin izleme kayitlarini
    bosalt (sinirsiz buyume = yavas bellek sizintisi)."""
    now = time.time()
    for d, pencere in ((msg_times, SPAM_WINDOW * 4), (cmd_times, SAME_CMD_WINDOW * 4)):
        for k in [k for k, v in list(d.items()) if not v or now - v[-1] > pencere]:
            d.pop(k, None)
    for k in [k for k, t in list(_cb_last_press.items()) if now - t > 3600]:
        _cb_last_press.pop(k, None)
    for uid in [u for u in list(recent_contents) if u not in msg_times]:
        recent_contents.pop(uid, None)

async def _scheduler_job(context):
    try:
        _evict_stale_memory()
    except Exception:
        pass
    due = db.get_due_scheduled()
    for sc in due:
        try:
            # Liste alindiktan sonra admin "Simdi Gonder"/"Iptal Et" yapmis
            # olabilir; kaydi ATOMIK sahiplenemezsek dokunmadan gec.
            if not db.claim_scheduled(sc['id']):
                continue
            p = json.loads(sc['payload'])
            ok, fail, total, ozet = await deliver_payload(context, p, sc['target'])
            db.set_scheduled_status(sc['id'], "gonderildi")
            _log_broadcast(f"\U0001f4c5 Zamanli #{sc['id']}", sc['target'], ok, fail, total, p, 0)
            rapor = f"#{sc['id']} \u2705 {ok} | \u274c {fail}" + (f"\n\n{ozet}" if ozet else "")
            for aid in ADMIN_IDS:
                try: await context.bot.send_message(chat_id=aid, text=box_message("ZAMANLI MESAJ GONDERILDI", rapor, "\U0001f4c5"), parse_mode=ParseMode.HTML)
                except: pass
        except Exception as e:
            logger.warning(f"[SCHED] {sc['id']}: {e}")
            db.set_scheduled_status(sc['id'], "hata")

    # Suresi dolan kampanyalari otomatik yayindan kaldir
    try:
        dropped = db.deactivate_expired_campaigns()
        if dropped:
            logger.info(f"[KAMPANYA] Suresi dolup kaldirilanlar: {dropped}")
    except Exception as e:
        logger.warning(f"[KAMPANYA-EXPIRE] {e}")

    # Kampanya bitis bildirimleri: son GUN (24s) ve son 2 SAAT kala hedef kitleye push
    try:
        now = datetime.now()
        for camp in db.campaigns_needing_expiry_notice():
            try:
                exp = datetime.fromisoformat(camp["expires_at"])
            except ValueError:
                continue
            kalan = (exp - now).total_seconds()
            level = None
            if kalan <= 2 * 3600 and camp["notified_ending"] < 2:
                level, baslik = 2, "⏳ SON 2 SAAT!"
            elif kalan <= 24 * 3600 and camp["notified_ending"] < 1:
                level, baslik = 1, "\U0001f4c5 SON GÜN!"
            if not level:
                continue
            # Cokme durumunda ayni kitleye ikinci kez gitmesin diye ONCE isaretle.
            db.mark_campaign_notified(camp["id"], level)
            text = box_message(baslik,
                f"<b>{sanitize_input(camp['title'], 120)}</b> bitmek üzere — kaçırma!\n"
                f"⏰ Bitiş: {exp.strftime('%d.%m.%Y %H:%M')}", "\U0001f514")
            kb = None
            if camp.get("btn_text") and is_valid_url(camp.get("btn_url") or ""):
                kb = InlineKeyboardMarkup([[InlineKeyboardButton(camp["btn_text"][:40], url=camp["btn_url"])]])
            ok = fail = 0
            for u in _campaign_audience(camp.get("segment") or ""):
                try:
                    await context.bot.send_message(chat_id=u["user_id"], text=text,
                        parse_mode=ParseMode.HTML, reply_markup=kb)
                    ok += 1
                except Exception:
                    fail += 1
                await asyncio.sleep(0.04)
            logger.info(f"[KAMPANYA-BILDIRIM] #{camp['id']} seviye {level}: ✅{ok} ❌{fail}")
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=aid, text=box_message("KAMPANYA BILDIRIMI GONDERILDI",
                        f"#{camp['id']} {sanitize_input(camp['title'], 60)}\n{baslik} • ✅ {ok} | ❌ {fail}", "\U0001f514"),
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
    except Exception as e:
        logger.warning(f"[KAMPANYA-BILDIRIM] {e}")

    # Gonderime az kalanlar: adminlere onizlemeli hatirlatma (duzenle/iptal sansi)
    for sc in db.get_prenotify_scheduled(SCHED_NOTIFY_MINUTES):
        try:
            p = json.loads(sc['payload'])
            try:
                kalan = max(1, int((datetime.fromisoformat(sc['run_at']) - datetime.now()).total_seconds() // 60))
            except Exception:
                kalan = SCHED_NOTIFY_MINUTES
            txt = box_message("ZAMANLI MESAJ HATIRLATMASI",
                f"\u23f3 <b>{kalan} dk sonra</b> g\u00f6nderilecek.\n\n" + _sched_preview_text(sc, p), "\U0001f514")
            # Once isaretle: gonderim ortasinda cokup yeniden baslarsak ayni
            # hatirlatma her dakika tekrar gitmesin (kampanya bildirimiyle ayni ilke).
            db.mark_scheduled_notified(sc['id'])
            for aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=aid, text=txt,
                        parse_mode=ParseMode.HTML, reply_markup=_sched_manage_kb(sc['id']))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[SCHED-NOTIFY] {sc['id']}: {e}")

async def _backup_job(context):
    try:
        done, tag = await asyncio.to_thread(weekly_backup_if_needed)
        if done: logger.info(f"[BACKUP JOB] {tag}")
    except Exception as e:
        logger.warning(f"[BACKUP JOB] {e}")


# =====================================================================
# HAZIR BILGI BANKASI — ilk calistirmada SSS bos ise otomatik yuklenir.
# Panelden serbestce duzenlenebilir/silinebilir; bir kez yuklenir,
# admin sildiklerini geri getirmez (faq_seeded bayragi).
# =====================================================================
_VARSAYILAN_SSS = [
    ("Guncel giris adresine nasil ulasirim?",
     "Ana menudeki **Siteye Giris** butonu her zaman guncel adrese goturur. Adres degistiginde buton otomatik guncellenir ve ayrica bildirim gonderilir."),
    ("Para yatirma yontemleri nelerdir?",
     "Havale/EFT, Papara, kripto ve kartla yatirim desteklenir. Ana menuden **Para Yatir** butonuna dokunarak tum yontemleri ve limitleri gorebilirsin."),
    ("Para cekimim ne zaman hesabima gecer?",
     "Cekim talepleri kontrol sonrasi odenir; yontemine gore suresi degisir. Talebinin uzerinden uzun sure gectiyse **Cekim Destek** ekibine yazman yeterli — bota \"param gelmedi\" yazarsan seni dogrudan yonlendiririm."),
    ("Yatirim yaptim ama bakiyeme gecmedi, ne yapmaliyim?",
     "Dekont/islem goruntusuyle birlikte **Odeme Destek** ekibine ulas; bota \"yatirim yaptim gecmedi\" yazarsan dogru kanala yonlendiririm. Cogu gecikme birkac dakika icinde cozulur."),
    ("Deneme bonusu nasil alinir?",
     "Aktif deneme bonuslari **Yeni Uye Bonuslari** bolumunde yayinlanir. Kosullar kampanya detayinda yazar; uygunsan Bonus Destek ekibi tanimlar."),
    ("Bonusum neden tanimlanmadi?",
     "Bonuslarin kendine ozel kurallari vardir (minimum yatirim, zaman siniri, tek kullanim gibi). Detay icin **Bonus Destek** ekibine yaz; bota \"bonus alamadim\" yazarsan seni dogrudan yonlendiririm."),
    ("Cevrim sarti nedir?",
     "Cevrim sarti, bonusla kazanilan tutari cekebilmek icin yapman gereken toplam oyun miktaridir. Her kampanyanin cevrim kati kendi detayinda yazar."),
    ("FreeSpin nedir, nasil kullanilir?",
     "FreeSpin, belirli slot oyunlarinda gecerli bedava donusdur. Tanimlaninca bildirim alirsin; ilgili oyunu actiginda otomatik kullanilir."),
    ("Kayip bonusu nedir?",
     "Belirli donemdeki net kaybinin bir yuzdesinin iade edildigi bonustur. Oranlar ve kosullar **Guncel Bonuslar** bolumundeki kampanya detayinda yazar."),
    ("Turnuvalara nasil katilirim?",
     "Ana menuden **Turnuvalar** bolumune gir; odul havuzu ve katilim sartlari her turnuvanin detayinda yazar. Cogu turnuvaya katilim otomatiktir."),
    ("Site ID nedir, nereden bulurum?",
     "Site ID, sitedeki uyelik numarandir; site profil sayfanda yazar. Bota tanitmak icin **Profil** menusunden Site ID gir — sana ozel kampanyalar boylece eslesir."),
    ("Sifremi unuttum, ne yapmaliyim?",
     "Giris sayfasindaki \"Sifremi Unuttum\" adimini kullan. Sorun yasarsan **Canli Destek** ekibi kimlik dogrulamasi sonrasi sifirlama yapar."),
    ("Hesap dogrulama (belge) neden istenir?",
     "Guvenlik ve yasal yukumlulukler geregi odeme oncesi kimlik dogrulamasi istenebilir. Belgelerin yalnizca dogrulama icin kullanilir."),
    ("Mini App nedir?",
     "Telegram'dan cikmadan siteyi kullanmani saglayan uygulamadir. Ana menudeki **Mini App** butonuyla tek dokunusta acilir."),
    ("Canli destege nasil ulasirim?",
     "Ana menuden **Canli Destek** butonuna dokun ya da derdini buraya yaz — mesajini analiz edip dogru ekibe (cekim/odeme/bonus) yonlendiririm."),
]

def seed_bilgi_bankasi():
    """SSS bosken hazir soru-cevap setini yukler (yalnizca ilk kurulumda)."""
    try:
        if db.get_setting("faq_seeded") == "1":
            return 0
        if db.list_faqs(only_active=False):
            db.set_setting("faq_seeded", "1")
            return 0
        for soru, cevap in _VARSAYILAN_SSS:
            db.add_faq(sanitize_input(soru, 200), sanitize_input(cevap, 1500))
        db.set_setting("faq_seeded", "1")
        return len(_VARSAYILAN_SSS)
    except Exception as e:
        logger.warning(f"[SSS-SEED] {e}")
        return 0

async def post_init(app):
    yuklenen = seed_bilgi_bankasi()
    if yuklenen:
        print(f"\U0001f4da Hazir bilgi bankasi yuklendi: {yuklenen} soru-cevap (panelden duzenlenebilir)")
    cmd_results = await _apply_commands(app.bot)
    for line in cmd_results:
        print(f"  {line}")
    try:
        count = export_site_id_records()
        secure_runtime_files()
        print(f"Site ID kayit dosyalari guncel: {count} kayit")
    except Exception as e:
        logger.exception("Baslangicta Site ID dosyalari yenilenemedi")
        print(f"Site ID dosya uyarisi: {e}")
    try:
        done, tag = weekly_backup_if_needed()
        print(f"\U0001f4be Yedek ({tag}): {'alindi' if done else 'mevcut'}")
    except Exception as e:
        print(f"Yedek uyarisi: {e}")
    try:
        if app.job_queue:
            app.job_queue.run_repeating(_backup_job, interval=86400, first=86400)
            app.job_queue.run_repeating(_scheduler_job, interval=60, first=30)
            print("\U0001f552 Zamanli gorevler planlandi.")
    except Exception as e:
        print(f"Job uyarisi: {e}")
    print(f"\u2705 {BOT_NAME} aktif! Adminler: {ADMIN_IDS}")

# =====================================================================
# MAIN
# =====================================================================

# Sihirbaz metin adimlarina klavye korumasi (menu tusu icerik sanilmasin).
bc_title_step   = _klavye_korumali(BC_TITLE)(bc_title_step)
bc_text_step    = _klavye_korumali(BC_TEXT)(bc_text_step)
bc_code_step    = _klavye_korumali(BC_CODE)(bc_code_step)
bc_btn_text_step  = _klavye_korumali(BC_BTN_TEXT)(bc_btn_text_step)
bc_btn_url_step   = _klavye_korumali(BC_BTN_URL)(bc_btn_url_step)
bc_btn2_text_step = _klavye_korumali(BC_BTN2_TEXT)(bc_btn2_text_step)
bc_btn2_url_step  = _klavye_korumali(BC_BTN2_URL)(bc_btn2_url_step)
bc_idlist_step  = _klavye_korumali(BC_IDLIST)(bc_idlist_step)
sched_when_step = _klavye_korumali(SCHED_WAIT_WHEN)(sched_when_step)
sched_time_save = _klavye_korumali(SCHED_TIME_WAIT)(sched_time_save)
dm_id_step      = _klavye_korumali(DM_WAIT_ID)(dm_id_step)
dm_text_step    = _klavye_korumali(DM_WAIT_TEXT)(dm_text_step)
aset_save       = _klavye_korumali(ASET_WAIT)(aset_save)
camp_title_step   = _klavye_korumali(CAMP_TITLE)(camp_title_step)
camp_body_step    = _klavye_korumali(CAMP_BODY)(camp_body_step)
camp_btn_step     = _klavye_korumali(CAMP_BTN)(camp_btn_step)
camp_prize_step   = _klavye_korumali(CAMP_PRIZE)(camp_prize_step)
camp_cond_step    = _klavye_korumali(CAMP_COND)(camp_cond_step)
camp_expires_step = _klavye_korumali(CAMP_EXPIRES)(camp_expires_step)
camp_edit_save  = _klavye_korumali(CAMP_EDIT_WAIT)(camp_edit_save)
ann_title_step  = _klavye_korumali(ANN_TITLE)(ann_title_step)
ann_body_step   = _klavye_korumali(ANN_BODY)(ann_body_step)
ann_edit_save   = _klavye_korumali(ANN_EDIT_WAIT)(ann_edit_save)
faq_q_step      = _klavye_korumali(FAQ_Q)(faq_q_step)
faq_a_step      = _klavye_korumali(FAQ_A)(faq_a_step)
sikayet_text    = _klavye_korumali(CMP_TEXT)(sikayet_text)
site_id_receive = _klavye_korumali(SITE_ID_WAIT_INPUT)(site_id_receive)

def main():
    print(f"\n{'='*40}\n  {BOT_NAME}\n{'='*40}\n")
    if not CONFIG_READY or not ADMIN_IDS:
        print("HATA: TELEGRAM_BOT_TOKEN ve TELEGRAM_ADMIN_PASSWORD_HASH ayarlarini yapin.")
        print("Ayrica admins.txt dosyasina kendi Telegram sayisal ID'nizi yazin.")
        print("GUVENLIK: Bu uc kosul birlikte saglanmadan bot baslatilmaz.")
        return
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # SIRALAMA ONEMLI: ayni grupta ilk eslesen handler update'i alir.
    # Admin conversation'lari Site ID conversation'indan ONCE kayit edilir;
    # boylece adminin parola/ayar/toplu-mesaj metinleri Site ID akisina dusmez.

    # Admin giris: ADMIN_REQUIRE_PASSWORD=1 ise parola sorulur, degilse dogrudan acilir.
    # Panel yalnizca ozel sohbette acilir; grupta /admin sessiz kalir.
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("admin", admin_login_cmd, filters.ChatType.PRIVATE)],
        states={
            WAITING_PASSWORD:[MessageHandler(filters.TEXT & ~filters.COMMAND, admin_password_check)],
            ConversationHandler.TIMEOUT:[MessageHandler(filters.ALL, admin_login_timeout),
                                         CallbackQueryHandler(admin_login_timeout)],
        },
        fallbacks=[CommandHandler("iptal", admin_login_cancel)],
        conversation_timeout=120, per_message=False))

    # Toplu mesaj + zamanli mesaj (ayni wizard, sched bayragi ile)
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(bc_start_cb, pattern="^bcgo$"),
                      CallbackQueryHandler(sched_start_cb, pattern="^schedgo$"),
                      CommandHandler("bildirim", bc_start_cmd)],
        states={
            BC_TYPE:[CallbackQueryHandler(bc_type_pick, pattern="^(bctype_|bc_cancel)")],
            BC_TITLE:[CommandHandler("atla", bc_title_skip), MessageHandler(filters.TEXT & ~filters.COMMAND, bc_title_step)],
            BC_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_text_step)],
            BC_CODE_STYLE:[CallbackQueryHandler(bc_code_style_pick, pattern="^(bcstyle_|bc_cancel)")],
            BC_CODE:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_code_step)],
            BC_IMAGE:[MessageHandler(filters.PHOTO | filters.VIDEO, bc_image_step)],
            BC_BTN_TEXT:[CommandHandler("atla", bc_btn_skip), MessageHandler(filters.TEXT & ~filters.COMMAND, bc_btn_text_step)],
            BC_BTN_URL:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_btn_url_step)],
            BC_BTN2_ASK:[CallbackQueryHandler(bc_btn2_ask_pick, pattern="^(bcbtn2_|bc_cancel)")],
            BC_BTN2_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_btn2_text_step)],
            BC_BTN2_URL:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_btn2_url_step)],
            BC_TARGET:[CallbackQueryHandler(bc_target_pick, pattern="^(bctarget_|bc_cancel)")],
            BC_IDLIST:[MessageHandler(filters.TEXT & ~filters.COMMAND, bc_idlist_step)],
            BC_CONFIRM:[CallbackQueryHandler(bc_confirm_pick, pattern="^(bc_confirm|bc_savetpl|bc_edit|bc_cancel)")],
            BC_EDIT_PICK:[CallbackQueryHandler(bc_edit_pick, pattern="^(bcedit_|bc_cancel)")],
            SCHED_WAIT_WHEN:[MessageHandler(filters.TEXT & ~filters.COMMAND, sched_when_step)],
        },
        fallbacks=[CommandHandler("iptal", bc_cancel_cmd)], conversation_timeout=900, per_message=False, allow_reentry=True))

    # Tekil mesaj
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(dm_start_cb, pattern="^dmgo$")],
        states={DM_WAIT_ID:[MessageHandler(filters.TEXT & ~filters.COMMAND, dm_id_step)],
                DM_WAIT_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, dm_text_step)]},
        fallbacks=[CommandHandler("iptal", dm_cancel)], conversation_timeout=300, per_message=False, allow_reentry=True))

    # Genel ayar duzenleme
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(aset_start, pattern="^apset_")],
        states={ASET_WAIT:[CommandHandler("temizle", aset_clear),
                           MessageHandler(filters.TEXT & ~filters.COMMAND, aset_save)]},
        fallbacks=[CommandHandler("iptal", aset_cancel)], conversation_timeout=300, per_message=False, allow_reentry=True))

    # Zamanli mesajin saatini degistirme
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(sched_time_start, pattern="^apschedtime_")],
        states={SCHED_TIME_WAIT:[MessageHandler(filters.TEXT & ~filters.COMMAND, sched_time_save)]},
        fallbacks=[CommandHandler("iptal", sched_time_cancel)], conversation_timeout=300, per_message=False, allow_reentry=True))

    # Yeni kampanya olusturma sihirbazi
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(camp_new_start, pattern="^apc_new$"),
                      CommandHandler("kampanyaekle", camp_new_start_cmd)],
        states={
            CAMP_CAT:[CallbackQueryHandler(camp_cat_pick, pattern="^(campcat_|camp_cancel)")],
            CAMP_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND, camp_title_step)],
            CAMP_BODY:[CommandHandler("atla", camp_body_skip),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, camp_body_step)],
            CAMP_MEDIA:[CommandHandler("atla", camp_media_skip),
                        MessageHandler(filters.PHOTO | filters.VIDEO, camp_media_step)],
            CAMP_BTN:[CommandHandler("atla", camp_btn_skip),
                      MessageHandler(filters.TEXT & ~filters.COMMAND, camp_btn_step)],
            CAMP_PRIZE:[CommandHandler("atla", camp_prize_skip),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, camp_prize_step)],
            CAMP_COND:[CommandHandler("atla", camp_cond_skip),
                       MessageHandler(filters.TEXT & ~filters.COMMAND, camp_cond_step)],
            CAMP_EXPIRES:[CommandHandler("atla", camp_expires_skip),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, camp_expires_step)],
        },
        fallbacks=[CommandHandler("iptal", camp_cancel)], conversation_timeout=600, per_message=False, allow_reentry=True))

    # Kampanya alan duzenleme
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(camp_edit_start, pattern="^apce_(title|body|expires|btn|prize|cond)_\\d+$")],
        states={CAMP_EDIT_WAIT:[CommandHandler("temizle", camp_edit_clear),
                                MessageHandler(filters.TEXT & ~filters.COMMAND, camp_edit_save)]},
        fallbacks=[CommandHandler("iptal", camp_edit_cancel)], conversation_timeout=300, per_message=False, allow_reentry=True))

    # Duyuru olusturma
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(ann_new_start, pattern="^apann_new$"),
                      CommandHandler("duyuruekle", ann_new_start_cmd)],
        states={
            ANN_TITLE:[MessageHandler(filters.TEXT & ~filters.COMMAND, ann_title_step)],
            ANN_BODY:[MessageHandler(filters.TEXT & ~filters.COMMAND, ann_body_step)],
            ANN_MEDIA:[CommandHandler("atla", ann_media_skip),
                       MessageHandler(filters.PHOTO | filters.VIDEO, ann_media_step)],
        },
        fallbacks=[CommandHandler("iptal", ann_cancel)], conversation_timeout=600, per_message=False, allow_reentry=True))

    # Duyuru alan duzenleme
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(ann_edit_start, pattern="^apanne_(title|body|media)_\\d+$")],
        states={ANN_EDIT_WAIT:[CommandHandler("temizle", ann_edit_clear),
                               MessageHandler(filters.TEXT & ~filters.COMMAND, ann_edit_save),
                               MessageHandler(filters.PHOTO | filters.VIDEO, ann_edit_save)]},
        fallbacks=[CommandHandler("iptal", ann_edit_cancel)],
        conversation_timeout=300, per_message=False, allow_reentry=True))

    # SSS olusturma
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(faq_new_start, pattern="^apfaq_new$")],
        states={FAQ_Q:[MessageHandler(filters.TEXT & ~filters.COMMAND, faq_q_step)],
                FAQ_A:[MessageHandler(filters.TEXT & ~filters.COMMAND, faq_a_step)]},
        fallbacks=[CommandHandler("iptal", faq_cancel)], conversation_timeout=600, per_message=False, allow_reentry=True))

    # Sikayet sihirbazi (kullanici tarafi) — panel Sikayetler bolumunun kullanici girisi
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("sikayet", sikayet_start, filters.ChatType.PRIVATE)],
        states={
            CMP_KIND:[CallbackQueryHandler(sikayet_kind, pattern="^(cmpkind_|cmp_cancel)")],
            CMP_TEXT:[MessageHandler(filters.TEXT & ~filters.COMMAND, sikayet_text)],
            CMP_IMAGE:[CommandHandler("atla", sikayet_skip),
                       MessageHandler(filters.PHOTO, sikayet_image)],
            ConversationHandler.TIMEOUT:[MessageHandler(filters.ALL, sikayet_timeout),
                                         CallbackQueryHandler(sikayet_timeout)],
        },
        fallbacks=[CommandHandler("iptal", sikayet_cancel_cmd)],
        conversation_timeout=600, per_message=False, allow_reentry=True))

    # /start + Site ID kayit akisi ve Profil menusunden Site ID degistirme.
    # Kayitli kullanicida akis aninda biter (karsilama + kampanya gosterilir).
    # allow_reentry: akis acikken Profil'deki "Site ID" butonu tekrar basilabilsin.
    # Yalnizca ozel sohbette calisir; grupta /start sessiz kalir.
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start_cmd, filters.ChatType.PRIVATE),
                      CallbackQueryHandler(profil_siteid_cb, pattern="^profil_siteid$")],
        states={
            SITE_ID_WAIT_INPUT:[MessageHandler(filters.TEXT & ~filters.COMMAND, site_id_receive)],
            SITE_ID_WAIT_CONFIRM:[CallbackQueryHandler(site_id_confirm, pattern="^site_confirm_"),
                                  MessageHandler(filters.TEXT & ~filters.COMMAND, site_id_receive)],
            ConversationHandler.TIMEOUT:[MessageHandler(filters.ALL, site_id_timeout),
                                         CallbackQueryHandler(site_id_timeout)],
        },
        fallbacks=[CommandHandler("iptal", site_id_cancel),
                   CommandHandler("start", start_cmd, filters.ChatType.PRIVATE)],
        conversation_timeout=600, per_message=False, allow_reentry=True))

    # Ekran goruntusu kaydi: foto gelince secenek sunar (admin: kutuphane / ekran goruntusu;
    # kullanici: kategori) ya da /ekran, ana menu ve alt klavye tusuyla once bilgiler sonra foto.
    # SIRA: /start + Site ID akisindan SONRA (Site ID girisi ve /start her zaman o akista kalir),
    # serbest foto handler'indan ve um_ callback'inden ONCE.
    app.add_handler(ConversationHandler(
        entry_points=[
            MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE), ss_photo_entry),
            CommandHandler("ekran", ss_start_cmd, filters.ChatType.PRIVATE),
            CallbackQueryHandler(ss_start_cb, pattern="^um_ekran$"),
            MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND & _EKRAN_ETIKET_FILTRESI, ss_start_cmd),
        ],
        states={
            SS_ACTION:[CallbackQueryHandler(ss_action_pick, pattern="^(ssact_|ss_cancel$)")],
            # NOT: akis acikken gelen fotolar allow_reentry nedeniyle giris noktasina
            # (ss_photo_entry) duser; o da kaldigi adima gore ss_photo_midway_field /
            # ss_photo_step'e yonlendirir. Bu yuzden durumlara ayri foto handler'i konmaz.
            SS_CAT:[CallbackQueryHandler(ss_cat_pick, pattern="^(sscat_|ss_cancel$)")],
            SS_FIELD:[CallbackQueryHandler(ss_usesite_cb, pattern="^ss_usesite$"),
                      CallbackQueryHandler(ss_cancel_cb, pattern="^ss_cancel$"),
                      MessageHandler(filters.TEXT & ~filters.COMMAND, ss_field_step)],
            SS_PHOTO:[CallbackQueryHandler(ss_cancel_cb, pattern="^ss_cancel$"),
                      MessageHandler(filters.ALL & ~filters.COMMAND, ss_photo_step)],
            ConversationHandler.TIMEOUT:[MessageHandler(filters.ALL, ss_timeout),
                                         CallbackQueryHandler(ss_timeout)],
        },
        fallbacks=[CommandHandler("iptal", ss_cancel_cmd)],
        conversation_timeout=600, per_message=False, allow_reentry=True))

    # Admin komutlari (butonlu sihirbaz ana yol; bunlar yedek)
    for cmd, fn in [
        ("setgirislink",setgirislink_cmd),("setgiristitle",setgiristitle_cmd),("setgiristext",setgiristext_cmd),
        ("setgirisbtn",setgirisbtn_cmd),("setreglink",setreglink_cmd),("setregbtn",setregbtn_cmd),
        ("setbonuslink",setbonuslink_cmd),("setbonusbtn",setbonusbtn_cmd),("setsupport",setsupport_cmd),
        ("setsupportbtn",setsupportbtn_cmd),("setwelcome",setwelcome_cmd),("setcaption",setcaption_cmd),
        ("setimage",setimage_cmd),("setimageurl",setimageurl_cmd),
        ("supporton",supporton_cmd),("supportoff",supportoff_cmd),
        ("sikayetac",sikayetac_cmd),("sikayetkapat",sikayetkapat_cmd),
        ("ban",ban_cmd),("unban",unban_cmd),("banlist",banlist_cmd),("banara",banara_cmd),
        ("userinfo",userinfo_cmd),("userlist",userlist_cmd),("usersearch",usersearch_cmd),
        ("topusers",topusers_cmd),("export",export_cmd),("setseg",setseg_cmd),("seglist",seglist_cmd),
        ("sikayetler",sikayetler_cmd),("sikayetkapatildi",sikayetkapatildi_cmd),("sikayetdosya",sikayetdosya_cmd),
        ("zamanliiptal",zamanliiptal_cmd),
        ("ekranlar",ekranlar_cmd),("ekrankapat",ekrankapat_cmd),("ekrandosya",ekrandosya_cmd),
        ("addadmin",addadmin_cmd),("removeadmin",removeadmin_cmd),("adminlist",adminlist_cmd),
        ("botstatus",botstatus_cmd),("logout",logout_cmd),
        ("dailylog",dailylog_cmd),("logfile",logfile_cmd),("securitylog",securitylog_cmd),
        ("backups",backups_cmd),("backupnow",backupnow_cmd),("menukur",menukur_cmd),("siteseg",siteseg_cmd),("kim",kim_cmd),("dmid",dmid_cmd),
    ]:
        app.add_handler(CommandHandler(cmd, fn))

    # Kullanici komutlari (yalnizca ozel sohbet): ana menu, profil, giris, destek, iptal, kimlik
    for _cmd, _fn in [("menu", menu_cmd), ("profil", profil_cmd), ("giris", giris_cmd),
                      ("destek", destek_cmd), ("iptal", iptal_cmd), ("whoami", whoami_cmd),
                      ("miniapp", miniapp_cmd), ("bonuslar", bonuslar_cmd), ("yeniuye", yeniuye_cmd),
                      ("slot", slot_cmd), ("spor", spor_cmd), ("banaozel", banaozel_cmd),
                      ("turnuvalar", turnuvalar_cmd), ("parayatir", parayatir_cmd),
                      ("paracek", paracek_cmd), ("duyurular", duyurular_cmd), ("sss", sss_cmd)]:
        app.add_handler(CommandHandler(_cmd, _fn, filters.ChatType.PRIVATE))
    app.add_handler(CallbackQueryHandler(user_menu_cb, pattern="^um_"))
    app.add_handler(CallbackQueryHandler(profil_kampanya_cb, pattern="^profil_kampanya$"))
    # Akis kapandiktan sonra kalan eski Evet/Hayir butonlari icin son durak
    app.add_handler(CallbackQueryHandler(site_confirm_stale_cb, pattern="^site_confirm_"))
    # Panel callback
    app.add_handler(CallbackQueryHandler(admin_cb, pattern="^(ap_|aphelp_|aphist_|aphistsend_|apban_|apsup_|apcmp_|apimg_|apmedia_|apsched_|apc_|apcsegset_|apann_|apannto_|apfaq_|apnotify_|apekran_|tpl_)"))

    # SON DURAK: suresi dolmus sihirbaz butonlari (bctype_, campcat_, cmpkind_...)
    # hicbir handler'a dusmezse spinner donup kalmasin.
    # DIKKAT: desensiz oldugu icin TUM callback'leri yakalar — kesinlikle
    # admin_cb dahil butun CallbackQueryHandler'lardan SONRA kayitli kalmali.
    app.add_handler(CallbackQueryHandler(stale_button_cb))

    # Yalnizca oturumu acik yoneticiler icin serbest foto/video ve metin.
    # Yetkisiz kullanici girdileri bu son katmanda cevap uretilmeden yok sayilir.
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO), handle_campaign_media))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text))

    app.add_error_handler(error_handler)
    print("\U0001f7e2 Bot calisiyor... Ctrl+C ile durdurun.\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()

