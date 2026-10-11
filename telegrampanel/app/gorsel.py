# -*- coding: utf-8 -*-
"""Kaydin gorselini yerel diskten bulur, kucuk resim uretir, gerekirse Gyazo'dan onbellege alir."""
import os, re, csv, time, hashlib, urllib.request, urllib.error
from .excel_oku import link_turu_ve_kimlik

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"


GORSEL_UZANTILAR = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")


def gorsel_icinde_mi(yol, kokler):
    """Yol, izin verilen gorsel klasorlerinden birinin ICINDE ve bir gorsel dosyasi mi? (indeks.csv / Excel'e yazilmis
    bir yol config.json ya da telebot.ps1 gibi baska bir dosyayi gosteremesin)"""
    try:
        if not yol or not str(yol).lower().endswith(GORSEL_UZANTILAR):
            return False
        mutlak = os.path.abspath(yol)
        for kok in kokler:
            if not kok:
                continue
            k = os.path.abspath(kok)
            if os.path.commonpath([mutlak, k]) == k:
                return True
    except Exception:
        pass
    return False


def _indeks_oku(yol, kokler=None):
    """ekran_goruntuleri\\indeks.csv / telegram_gorseller\\indeks.csv -> gyazo id -> dosya yolu
    (yalnizca izinli gorsel klasorlerinin icindeki gorsel dosyalari)"""
    h = {}
    if not yol or not os.path.exists(yol):
        return h
    try:
        with open(yol, encoding="utf-8-sig", newline="") as f:
            kok = os.path.dirname(yol)
            izinli = list(kokler or []) + [kok]
            for r in csv.DictReader(f, delimiter=";"):
                gid = (r.get("GyazoId") or "").lower()
                yol_d = r.get("DosyaYolu") or ""
                if not gid or not re.fullmatch(r"[0-9a-f]{32}", gid):
                    continue
                if yol_d and os.path.exists(yol_d) and gorsel_icinde_mi(yol_d, izinli):
                    h[gid] = yol_d
                    continue
                # Baska bilgisayarda (OneDrive ile gelen kopya): mutlak yol tutmaz; klasor + proje + dosya adi ile bul
                ad = os.path.basename((r.get("DosyaAdi") or os.path.basename(yol_d.replace("\\", "/"))).replace("\\", "/"))
                for aday in (os.path.join(kok, (r.get("Proje") or "").upper(), ad), os.path.join(kok, r.get("Proje") or "", ad), os.path.join(kok, ad)):
                    if ad and os.path.exists(aday) and gorsel_icinde_mi(aday, [kok]):
                        h[gid] = aday
                        break
    except Exception:
        pass
    return h


_GYAZO_HOSTLAR = ("gyazo.com", "i.gyazo.com", "www.gyazo.com")


def gyazo_url(link, kimlik):
    """Indirilecek adres: yalnizca gyazo.com. Linkin kendisi i.gyazo.com'daki bir gorsel dosyasiysa o, degilse
    kimlikten uretilen https://i.gyazo.com/<id>.jpg (Telegram'dan gelen link baska bir sunucuya yonlendiremez)."""
    from urllib.parse import urlparse
    try:
        u = urlparse((link or "").strip())
        if u.scheme in ("http", "https") and (u.hostname or "").lower() == "i.gyazo.com" and re.fullmatch(r"/" + re.escape(kimlik) + r"\.(jpg|jpeg|png|gif|webp)", u.path, re.I):
            return "https://i.gyazo.com" + u.path
    except Exception:
        pass
    return f"https://i.gyazo.com/{kimlik}.jpg"


class _GyazoYonlendirme(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        if (urlparse(newurl).hostname or "").lower() not in _GYAZO_HOSTLAR:
            raise urllib.error.HTTPError(newurl, code, "gyazo disina yonlendirme", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GorselCozucu:
    def __init__(self, ayar, onbellek_klasor):
        self.ayar = ayar
        self.gorsel_klasor = ayar.get("GORSEL_KLASOR") or os.path.join(ayar["BOT_KLASOR"], "gorseller")
        self.ek_klasorler = [os.path.join(ayar["BOT_KLASOR"], "ekran_goruntuleri"), os.path.join(ayar["BOT_KLASOR"], "telegram_gorseller")] + list(ayar.get("EK_GORSEL_KLASORLERI", []))
        self.onbellek = onbellek_klasor
        self.thumbs = os.path.join(onbellek_klasor, "thumbs")
        self.gyazo_cache = os.path.join(onbellek_klasor, "gyazo")
        os.makedirs(self.thumbs, exist_ok=True)
        os.makedirs(self.gyazo_cache, exist_ok=True)
        self._indeks = {}
        self._indeks_zaman = 0
        self._dosya_haritasi = {}
        self._dosya_zaman = 0
        self.gyazo_proxy = str(ayar.get("GYAZO_PROXY", "1")).lower() not in ("0", "false", "hayir")

    def _yenile(self):
        if time.time() - self._indeks_zaman > 300:
            h = {}
            for k in self.ek_klasorler:
                h.update(_indeks_oku(os.path.join(k, "indeks.csv"), [self.gorsel_klasor] + self.ek_klasorler))
            self._indeks = h
            self._indeks_zaman = time.time()
        if time.time() - self._dosya_zaman > 300:
            m = {}
            for kok in [self.gorsel_klasor] + self.ek_klasorler:
                if not os.path.isdir(kok):
                    continue
                for dp, _, fns in os.walk(kok):
                    for fn in fns:
                        if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                            m.setdefault(fn.lower(), os.path.join(dp, fn))
            self._dosya_haritasi = m
            self._dosya_zaman = time.time()

    def kokler(self):
        return [self.gorsel_klasor] + self.ek_klasorler

    def yerel_dosya(self, kayit):
        """-> (yol|None, kaynak)  kaynak: yerel|gyazo_onbellek|yok. Donen yol her zaman gorsel klasorlerinin icindedir."""
        yol, kaynak = self._yerel_dosya(kayit)
        if yol and not gorsel_icinde_mi(yol, self.kokler() + [self.gyazo_cache]):
            return None, "yok"
        return yol, kaynak

    def _yerel_dosya(self, kayit):
        self._yenile()
        if kayit.get("gorsel_dosya") and os.path.exists(kayit["gorsel_dosya"]):
            return kayit["gorsel_dosya"], "yerel"
        tur, kimlik = link_turu_ve_kimlik(kayit.get("link") or "")
        if tur == "onedrive" and kimlik:
            for kok in [self.gorsel_klasor]:
                aday = os.path.join(kok, (kayit.get("proje") or "").upper(), kimlik)
                if os.path.exists(aday):
                    return aday, "yerel"
            if kimlik in self._dosya_haritasi:
                return self._dosya_haritasi[kimlik], "yerel"
        if tur == "dosya":
            # Excel'e tam yol yazilmis; sadece gorsel klasoru altindaysa kabul
            yol = kayit.get("link")
            try:
                if os.path.exists(yol) and os.path.commonpath([os.path.abspath(yol), os.path.abspath(self.gorsel_klasor)]) == os.path.abspath(self.gorsel_klasor):
                    return yol, "yerel"
            except Exception:
                pass
        if tur == "gyazo" and kimlik:
            if kimlik in self._indeks:
                return self._indeks[kimlik], "yerel"
            for uz in (".png", ".jpg"):
                c = os.path.join(self.gyazo_cache, kimlik + uz)
                if os.path.exists(c):
                    return c, "gyazo_onbellek"
        return None, "yok"

    def gyazo_indir(self, kayit):
        """Gyazo'dan bir kez indirip onbellege koy. Basarisizsa 1 saat tekrar denemez."""
        if not self.gyazo_proxy:
            return None
        tur, kimlik = link_turu_ve_kimlik(kayit.get("link") or "")
        if tur != "gyazo" or not kimlik:
            return None
        hata_dosyasi = os.path.join(self.gyazo_cache, kimlik + ".hata")
        if os.path.exists(hata_dosyasi) and time.time() - os.path.getmtime(hata_dosyasi) < 3600:
            return None
        url = gyazo_url(kayit.get("link"), kimlik)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "image/*,*/*;q=0.8", "Referer": "https://gyazo.com/"})
            with urllib.request.build_opener(_GyazoYonlendirme()).open(req, timeout=15) as r:
                veri = r.read(20 * 1024 * 1024 + 1)
            if len(veri) > 20 * 1024 * 1024:
                raise IOError("cok buyuk")
            if len(veri) < 100 or not (veri[:2] == b"\xff\xd8" or veri[:4] == b"\x89PNG"):
                raise IOError("gorsel degil")
            uz = ".png" if veri[:4] == b"\x89PNG" else ".jpg"
            hedef = os.path.join(self.gyazo_cache, kimlik + uz)
            with open(hedef, "wb") as f:
                f.write(veri)
            return hedef
        except Exception:
            with open(hata_dosyasi, "w") as f:
                f.write(str(time.time()))
            return None

    def kucuk(self, kayit, yol):
        """400px kucuk resim; onbellekte tutulur. -> yol|None"""
        try:
            from PIL import Image
        except Exception:
            return yol
        ad = hashlib.sha1((kayit.get("anahtar") or yol).encode("utf-8")).hexdigest()[:20] + ".jpg"
        hedef = os.path.join(self.thumbs, ad)
        try:
            if os.path.exists(hedef) and os.path.getmtime(hedef) >= os.path.getmtime(yol):
                return hedef
            with Image.open(yol) as im:
                im = im.convert("RGB")
                im.thumbnail((400, 400))
                im.save(hedef, "JPEG", quality=80)
            return hedef
        except Exception:
            return yol
