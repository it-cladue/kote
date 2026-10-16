# -*- coding: utf-8 -*-
"""Ayarlar: /opt/kanit/.env (ya da KANIT_ENV ile verilen dosya) + ortam degiskenleri.

Dosya bicimi: her satir ANAHTAR=DEGER, # ile yorum. Token'lar YALNIZCA bu dosyada durur (0600), depoya girmez.
Calisma zamaninda degisen seyler (bakim modu, gyazo bakim, telegram offset, bot nabzi) ayarlar TABLOSUNDA tutulur (db.ayar_al).
"""
import os, secrets

VARSAYILAN = {
    "VERI": "/opt/kanit/veri",          # veritabani, gorseller, onbellek, yedek, log
    "PORT": "8080",
    "DINLE": "0.0.0.0",                 # alan adi gelince Plesk/nginx arkasinda 127.0.0.1 yapilir
    "SITE_URL": "",                     # ornek: https://kanit.sirket.com (disa aktarma linkleri icin; bos ise istekten alinir)
    "TELEGRAM_TOKEN": "",
    "GYAZO_TOKEN": "",
    "BOT_PASSWORD": "",                 # Telegram uyelerinin bir kez yazdigi ortak sifre (bugunku bot gibi)
    "ADMIN_IDS": "",                    # virgulle ayrilmis Telegram ID'leri (botun /durum, /bakim_* komutlari icin)
    "MAX_DENEME": "3",                  # yanlis sifre denemesi; asilinca engel
    "MAX_GORSEL_MB": "8",
    "TZ": "Europe/Istanbul",
    "GUVENILIR_PROXY": "0",             # 1: X-Forwarded-For / CF-Connecting-IP basligina guven (nginx/Cloudflare arkasinda)
    "HTTPS": "0",                       # 1: oturum cerezi yalnizca https
    "SECRET_KEY": "",                   # bos ise VERI/gizli_anahtar.txt uretilir
    "LOG_SEVIYE": "INFO",
}


def _env_dosyasi():
    for aday in (os.environ.get("KANIT_ENV"), "/opt/kanit/.env", os.path.join(os.getcwd(), ".env")):
        if aday and os.path.isfile(aday):
            return aday
    return None


def _dosya_oku(yol):
    d = {}
    with open(yol, encoding="utf-8-sig") as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, v = ln.split("=", 1)
            d[k.strip().upper()] = v.strip().strip('"').strip("'")
    return d


def yukle():
    """-> dict. Oncelik: ortam degiskeni (KANIT_ ile baslayan ya da ciplak ad) > .env dosyasi > varsayilan."""
    a = dict(VARSAYILAN)
    yol = _env_dosyasi()
    if yol:
        a.update({k: v for k, v in _dosya_oku(yol).items() if k in VARSAYILAN or k.startswith("KANIT_")})
    for k in list(VARSAYILAN):
        v = os.environ.get("KANIT_" + k) or os.environ.get(k) if k not in ("PORT", "TZ", "HTTPS") else os.environ.get("KANIT_" + k)
        if v:
            a[k] = v
    a["VERI"] = os.path.abspath(os.path.expanduser(a["VERI"]))
    a["ENV_DOSYA"] = yol
    a["ADMIN_IDS"] = [x.strip() for x in str(a["ADMIN_IDS"]).replace(";", ",").split(",") if x.strip()]
    for k in ("PORT", "MAX_DENEME", "MAX_GORSEL_MB"):
        try:
            a[k] = int(a[k])
        except (TypeError, ValueError):
            a[k] = int(VARSAYILAN[k])
    # klasorler
    for alt in ("", "gorseller", "onbellek", "onbellek/thumbs", "yedek", "log", "gelen", "gecici"):
        os.makedirs(os.path.join(a["VERI"], alt), exist_ok=True)
    a["DB"] = os.path.join(a["VERI"], "kanit.db")
    a["GORSELLER"] = os.path.join(a["VERI"], "gorseller")
    a["ONBELLEK"] = os.path.join(a["VERI"], "onbellek")
    a["YEDEK"] = os.path.join(a["VERI"], "yedek")
    a["LOG"] = os.path.join(a["VERI"], "log")
    if not a["SECRET_KEY"]:
        gy = os.path.join(a["VERI"], "gizli_anahtar.txt")
        if not os.path.exists(gy):
            with open(gy, "w", encoding="utf-8") as f:
                f.write(secrets.token_hex(32))
            try:
                os.chmod(gy, 0o600)
            except OSError:
                pass
        with open(gy, encoding="utf-8") as f:
            a["SECRET_KEY"] = f.read().strip()
    return a


def ornek_env():
    return "\n".join([
        "# Kanit Merkezi ayarlari - bu dosya /opt/kanit/.env olarak durur, izni 600, depoya girmez",
        "VERI=/opt/kanit/veri",
        "PORT=8080",
        "DINLE=0.0.0.0",
        "SITE_URL=",
        "TELEGRAM_TOKEN=BURAYA_TELEGRAM_BOT_TOKEN",
        "GYAZO_TOKEN=BURAYA_GYAZO_TOKEN",
        "BOT_PASSWORD=BURAYA_UYE_SIFRESI",
        "ADMIN_IDS=",
        "MAX_DENEME=3",
        "TZ=Europe/Istanbul",
        "GUVENILIR_PROXY=0",
        "HTTPS=0",
        "",
    ])
