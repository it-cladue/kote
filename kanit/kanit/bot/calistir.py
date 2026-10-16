# -*- coding: utf-8 -*-
"""Botun dongusu: tek is parcacikli long polling (getUpdates timeout 25 sn), offset ayarlar tablosunda,
nabiz (bot_nabiz) her turda, hatalar son_hata'ya, log VERI/log/bot.log (donen, 5 x 5 MB).

calistir(ayar=None, bir_tur=False): bir_tur=True tek getUpdates turu isler ve Bot nesnesini dondurur (testler icin).
Ayar anahtarlari: TELEGRAM_TOKEN, TELEGRAM_API (taban adres), GYAZO_TOKEN, GYAZO_API, BOT_PASSWORD, ADMIN_IDS, MAX_DENEME,
MAX_GORSEL_MB, HATA_BEKLEME_SN (varsayilan 5), CAKISMA_BEKLEME_SN (409 sonrasi; varsayilan 30), LOG_EKRAN (0: stdout'a yazma).
"""
import logging
import os
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from .. import db, gorsel
from . import akis
from .telegram_api import TelegramAPI, CakismaHatasi

POLL_ZAMAN_ASIMI = 25
NORMAL_UYKU = 0.2
TEMIZLIK_ARALIGI_SN = 3600


def log_kur(ayar):
    """'[yyyy-MM-dd HH:mm:ss] mesaj' bicimi; VERI/log/bot.log donen dosya + (istege bagli) ekran."""
    lg = logging.getLogger("kanit.bot")
    lg.setLevel(logging.DEBUG if str(ayar.get("LOG_SEVIYE", "INFO")).upper() == "DEBUG" else logging.INFO)
    lg.propagate = False
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass
    bicim = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    klasor = ayar.get("LOG") or os.path.join(ayar.get("VERI", "."), "log")
    os.makedirs(klasor, exist_ok=True)
    fh = RotatingFileHandler(os.path.join(klasor, "bot.log"), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(bicim)
    lg.addHandler(fh)
    if str(ayar.get("LOG_EKRAN", "1")) != "0":
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(bicim)
        lg.addHandler(sh)
    return lg


class Bot:
    def __init__(self, ayar, conn=None):
        self.ayar = ayar
        self.conn = conn or db.baglan(ayar["DB"])
        self.log = log_kur(ayar)
        self.uyku = time.sleep
        self.api = TelegramAPI(ayar.get("TELEGRAM_TOKEN") or "", ayar.get("TELEGRAM_API"), uyku=lambda s: self.uyku(s))
        self.admin_ids = {str(x).strip() for x in (ayar.get("ADMIN_IDS") or []) if str(x).strip()}
        self.baslangic = db.simdi()
        self.son_temizlik = time.time()
        self.son_gorseller = {}   # tg_id -> (sha256, zaman)  5 dk kopya korumasi
        self.bekleyen_onay = {}   # admin tg_id -> {tur, id, sebep}
        self.son_hata = ""
        self.durdur = False
        self.gecici = os.path.join(ayar["VERI"], "gecici")
        os.makedirs(self.gecici, exist_ok=True)

    # ---- yardimcilar ----
    def admin_mi(self, uid):
        return str(uid) in self.admin_ids

    def hata(self, metin):
        self.son_hata = f"{db.simdi()} {metin}"
        self.log.error("! %s", metin)
        try:
            db.ayar_yaz(self.conn, "son_hata", self.son_hata[:500])
        except Exception:
            pass

    def nabiz(self):
        db.ayar_yaz(self.conn, "bot_nabiz", db.simdi())

    def gecici_yol(self, uid):
        return os.path.join(self.gecici, "tg_" + "".join(c for c in str(uid) if c.isalnum()) + ".img")

    def gecici_yaz(self, uid, baytlar):
        try:
            yol = self.gecici_yol(uid)
            with open(yol + ".tmp", "wb") as f:
                f.write(baytlar)
            os.replace(yol + ".tmp", yol)
        except OSError as e:
            self.log.warning("! Gecici gorsel yazilamadi: %s", e)

    def gecici_sil(self, uid):
        try:
            os.remove(self.gecici_yol(uid))
        except OSError:
            pass

    def oturum_kaldir(self, uid):
        db.oturum_sil(self.conn, uid)
        self.gecici_sil(uid)

    def gorsel_baytlari(self, uid, ot):
        """Onayla'da gorsel: gecici dosya (sha uyusuyorsa) yoksa Telegram'dan yeniden indirilir."""
        import hashlib
        yol = self.gecici_yol(uid)
        if ot.get("fotoSha") and os.path.exists(yol):
            with open(yol, "rb") as f:
                b = f.read()
            if hashlib.sha256(b).hexdigest() == ot["fotoSha"]:
                return b
        sinir = int(self.ayar.get("MAX_GORSEL_MB") or 8) * 1024 * 1024
        return self.api.gorsel_indir(ot.get("fileId"), sinir)

    def bakim_isleri(self, zorla=False):
        """Saatte bir: 24 saatten eski oturumlar + sahipsiz gecici gorseller silinir."""
        if not zorla and time.time() - self.son_temizlik < TEMIZLIK_ARALIGI_SN:
            return 0
        self.son_temizlik = time.time()
        n = db.oturum_temizle_eski(self.conn, 24)
        if n:
            self.log.info("  %s eski oturum temizlendi", n)
        try:
            esik = time.time() - 24 * 3600
            for ad in os.listdir(self.gecici):
                yol = os.path.join(self.gecici, ad)
                if ad.startswith("tg_") and os.path.isfile(yol) and os.path.getmtime(yol) < esik:
                    os.remove(yol)
        except OSError:
            pass
        return n

    def patlama_korumasi(self, guncellemeler):
        """Baslangic patlamasi: ayni uyeden bir pakette birden fazla fotograf -> yalniz sonuncusu islenir, uye bir kez uyarilir.
        -> atlanacak update_id kumesi"""
        fotolar = {}
        for g in guncellemeler:
            m = g.get("message") or {}
            if (m.get("chat") or {}).get("type", "private") == "private" and akis.foto_kimligi(m):
                uid = str((m.get("from") or {}).get("id") or "")
                fotolar.setdefault(uid, []).append((g["update_id"], m["chat"]["id"]))
        atla = set()
        for uid, liste in fotolar.items():
            if len(liste) < 2:
                continue
            tg = db.tg_al(self.conn, uid) or {}
            if not tg.get("onayli") or tg.get("engelli"):
                continue
            atla.update(i for i, _ in liste[:-1])
            self.log.info("  Patlama korumasi: %s uyesinden %s fotograf, yalniz sonuncusu islenecek", uid, len(liste))
            self.api.mesaj_gonder(liste[-1][1], akis.M_PATLAMA)
        return atla

    # ---- dongu ----
    def tur(self):
        """Bir getUpdates turu. -> islenen guncelleme sayisi (hata/409'da 0)."""
        self.nabiz()
        self.bakim_isleri()
        try:
            offset = int(db.ayar_al(self.conn, "telegram_offset", "0") or 0)
        except ValueError:
            offset = 0
        try:
            sonuc = self.api.guncellemeler(offset, POLL_ZAMAN_ASIMI)
        except CakismaHatasi as e:
            self.hata(f"409 CONFLICT: ayni token ile baska bir bot sureci calisiyor! ({e}) "
                      f"{self.ayar.get('CAKISMA_BEKLEME_SN', 30)} sn bekleniyor")
            self.uyku(float(self.ayar.get("CAKISMA_BEKLEME_SN", 30)))
            return 0
        if sonuc is None:
            self.hata(f"getUpdates basarisiz: {self.api.son_hata}")
            self.uyku(float(self.ayar.get("HATA_BEKLEME_SN", 5)))
            return 0
        if not sonuc:
            return 0
        self.log.info("  %s guncelleme bulundu.", len(sonuc))
        atla = self.patlama_korumasi(sonuc)
        for g in sonuc:
            gid = g.get("update_id", offset)
            try:
                if gid in atla:
                    pass
                elif g.get("callback_query"):
                    akis.geri_arama_isle(self, g)
                elif g.get("message"):
                    akis.mesaj_isle(self, g)
            except CakismaHatasi as e:
                self.hata(f"409 CONFLICT: {e}")
            except Exception as e:
                self.hata(f"Hata (update {gid}): {e!r}")
                self.log.debug("ayrinti", exc_info=True)
            offset = max(offset, int(gid) + 1)
            db.ayar_yaz(self.conn, "telegram_offset", offset)
        self.nabiz()
        return len(sonuc)

    def dongu(self):
        self.log.info("========================================")
        self.log.info("  Bot baslatiliyor... DB: %s", self.ayar.get("DB"))
        self.log.info("  Gorsel klasoru: %s | Gyazo: %s | Bakim: %s", self.ayar.get("GORSELLER"),
                      "BAKIMDA" if db.gyazo_bakim(self.conn) else "ACIK", "ACIK" if db.bakim_modu(self.conn) else "KAPALI")
        self.log.info("  Hazir! Long polling aktif (timeout %s sn).", POLL_ZAMAN_ASIMI)
        self.log.info("========================================")
        while not self.durdur:
            try:
                n = self.tur()
            except Exception as e:
                self.hata(f"Dongu hatasi: {e!r} - {self.ayar.get('HATA_BEKLEME_SN', 5)} sn sonra tekrar")
                self.log.debug("ayrinti", exc_info=True)
                self.uyku(float(self.ayar.get("HATA_BEKLEME_SN", 5)))
                continue
            if n:
                self.uyku(NORMAL_UYKU)
        self.log.info("Bot guvenli sekilde durduruldu.")


def calistir(ayar=None, bir_tur=False):
    """Botu calistirir. ayar None ise kanit.ayar.yukle(). bir_tur=True: tek tur isler, Bot nesnesini dondurur."""
    if ayar is None:
        from .. import ayar as A
        ayar = A.yukle()
    b = Bot(ayar)
    if not ayar.get("TELEGRAM_TOKEN"):
        b.hata("TELEGRAM_TOKEN bos; .env dosyasini doldurun.")
        return b
    if bir_tur:
        b.tur()
        return b

    def _dur(sig, frm):
        b.log.info("  Durdurma sinyali alindi (%s).", sig)
        b.durdur = True
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _dur)
        except (ValueError, OSError):
            pass
    try:
        b.dongu()
    except KeyboardInterrupt:
        b.log.info("Bot durduruluyor (CTRL+C).")
    return b
