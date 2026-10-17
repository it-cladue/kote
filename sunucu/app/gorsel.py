# -*- coding: utf-8 -*-
"""Yerel, erişim denetimli görsel çözümleme.

Bu modül Gyazo'ya istek yapmaz ve indirme yapmaz. Bağlantı yalnızca güvenli
yerel indeks/isim eşlemesi için kimlik kaynağıdır.
"""
import csv
import hashlib
import os
import re
import tempfile
import threading
import time
import unicodedata
import warnings
from pathlib import Path
from urllib.parse import urlparse

from .excel_oku import link_turu_ve_kimlik

GORSEL_UZANTILARI = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
KIMLIK_RX = re.compile(r"[0-9a-f]{32}", re.I)
MAX_IMAGE_PIXELS = 25_000_000
# Gyazo vekili: yalnız bu hostlar, yalnız 32 hex kimlik, sınırlı boyut/süre.
GYAZO_HOSTLAR = ("gyazo.com", "i.gyazo.com")
GYAZO_KAYNAK = "https://i.gyazo.com/{id}.jpg"
GYAZO_MAX_BYTES = 20 * 1024 * 1024
GYAZO_ZAMAN_ASIMI = 15
GYAZO_OLUMSUZ_SN = 600
GYAZO_BICIMLER = {"JPEG": ".jpg", "PNG": ".png"}


def _baslik(adi):
    """CSV başlıklarını GyazoId/Dosya Yolu gibi zararsız farklılıklara dayanıklı yapar."""
    s = unicodedata.normalize("NFKD", str(adi or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _guvenli_altinda(yol, kokler):
    """Var olan bir yolu çözer; symlink ile izinli kök dışına çıkışı reddeder."""
    if not yol:
        return None
    try:
        p = Path(yol).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not p.is_file():
        return None
    for kok in kokler:
        try:
            r = Path(kok).expanduser().resolve(strict=False)
            if os.path.commonpath((str(p), str(r))) == str(r):
                return str(p)
        except (OSError, ValueError, RuntimeError):
            continue
    return None


def _isim_yolu(s):
    """Windows mutlak yollarında da yalnızca son bileşeni alır."""
    return os.path.basename(str(s or "").replace("\\", "/"))


def _csv_satirlari(yol):
    try:
        with open(yol, "r", encoding="utf-8-sig", newline="") as f:
            ornek = f.read(4096)
            f.seek(0)
            try:
                lehce = csv.Sniffer().sniff(ornek, delimiters=";,\t,")
            except csv.Error:
                lehce = csv.excel
                lehce.delimiter = ";"
            yield from csv.DictReader(f, dialect=lehce)
    except (OSError, csv.Error, UnicodeError):
        return


def _satir_degeri(satir, *adlar):
    normal = {_baslik(k): v for k, v in satir.items() if k is not None}
    for ad in adlar:
        v = normal.get(ad)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _indeks_oku(yol, kokler, dosya_haritasi):
    """``indeks.csv`` içinden sadece izinli dosyalara işaret eden kimlikleri döndürür.

    Dönüş değeri ``{gyazo_id: {çözülmüş_yol, ...}}`` biçimindedir; birden çok
    aday asla ilk rastlanana indirgenmez.
    """
    sonuc = {}
    indeks_koku = os.path.dirname(os.path.abspath(yol))
    for r in _csv_satirlari(yol) or ():
        gid = _satir_degeri(r, "gyazoid", "gyazo", "gyazokimlik").lower()
        if not KIMLIK_RX.fullmatch(gid):
            continue
        ham_yol = _satir_degeri(r, "dosyayolu", "dosyapath", "path", "yol")
        ad = _satir_degeri(r, "dosyaadi", "filename", "dosya", "ad") or _isim_yolu(ham_yol)
        proje = _satir_degeri(r, "proje", "project")
        adaylar = set()
        # CSV'de mevcut yerel/mutlak yol varsa önce o kabul edilir; yalnızca izinli
        # kökün altında ve çözümlenen hedefi de oradaysa.
        if ham_yol:
            p = ham_yol.replace("\\", os.sep)
            if not re.match(r"^[a-zA-Z]:[\\/]", ham_yol) and not ham_yol.startswith("\\\\"):
                p = p if os.path.isabs(p) else os.path.join(indeks_koku, p)
            guvenli = _guvenli_altinda(p, kokler)
            if guvenli:
                adaylar.add(guvenli)
        # Başka bilgisayardaki Windows mutlak yolu taşındıysa, yalnızca indeksin
        # yerel kök/proje/dosya düzeninde ya da benzersiz basename olarak bul.
        if ad:
            for kok in kokler:
                for p in (
                    os.path.join(kok, proje, ad) if proje else "",
                    os.path.join(kok, ad),
                    os.path.join(indeks_koku, proje, ad) if proje else "",
                    os.path.join(indeks_koku, ad),
                ):
                    guvenli = _guvenli_altinda(p, kokler)
                    if guvenli:
                        adaylar.add(guvenli)
            adaylar.update(dosya_haritasi.get(ad.lower(), set()))
        if adaylar:
            sonuc.setdefault(gid, set()).update(adaylar)
    return sonuc


class GorselCozucu:
    def __init__(self, ayar, onbellek):
        self.ayar = ayar
        self.gorsel_klasor = ayar.get("GORSEL_KLASOR") or os.path.join(ayar["BOT_KLASOR"], "gorseller")
        self.arsiv_klasor = ayar.get("ARSIV_KLASOR") or os.path.join(ayar.get("BOT_KLASOR", ""), "telegram_gorseller")
        self.ek_klasorler = list(ayar.get("EK_GORSEL_KLASORLERI") or [])
        # Önceki kurulumlarda bu iki kök ayarlarda açıkça yazılmamış olabilir.
        bot = ayar.get("BOT_KLASOR", "")
        self.ek_klasorler += [os.path.join(bot, "ekran_goruntuleri"), self.arsiv_klasor]
        self.kokler = self._tekil_kokler([self.gorsel_klasor] + self.ek_klasorler)
        self.onbellek = os.path.abspath(onbellek)
        self.thumbs = os.path.join(self.onbellek, "thumbs")
        self.gyazo_klasor = os.path.join(self.onbellek, "gyazo")
        os.makedirs(self.thumbs, exist_ok=True)
        os.makedirs(self.gyazo_klasor, exist_ok=True)
        self.gyazo_acik = str(ayar.get("GYAZO_PROXY", "1")).strip().lower() in ("1", "true", "evet")
        self.gyazo_hostlar = tuple(GYAZO_HOSTLAR)
        self.gyazo_kaynak = GYAZO_KAYNAK
        self._http = None
        self._gyazo_kilit = threading.Lock()
        self._gyazo_semafor = threading.BoundedSemaphore(4)
        self._indeks = {}
        self._dosya_haritasi = {}
        self._yol_kimlik = {}
        self._indeks_zaman = 0
        self._dosya_zaman = 0

    @staticmethod
    def _tekil_kokler(kokler):
        sonuc = []
        for k in kokler:
            if not k:
                continue
            try:
                k = str(Path(k).expanduser().resolve(strict=False))
            except (OSError, RuntimeError, ValueError):
                continue
            if k not in sonuc:
                sonuc.append(k)
        return sonuc

    def _guvenli(self, yol):
        return _guvenli_altinda(yol, self.kokler)

    def _goreli_dosya(self, deger):
        """DB'deki relative media yolunu yalnızca güncel media köküne bağlar."""
        if not deger:
            return None
        deger = str(deger)
        if os.path.isabs(deger) or re.match(r"^[a-zA-Z]:[\\/]", deger) or deger.startswith("\\\\"):
            return self._guvenli(deger)
        # ``..`` dahil olsa bile resolve+whitelist kesin olarak reddeder.
        return self._guvenli(os.path.join(self.gorsel_klasor, deger))

    def _yenile(self):
        """İzinli kökleri tarar; symlink dışına çıkmaz ve belirsiz adları saklar."""
        simdi = time.time()
        if simdi - self._dosya_zaman > 300:
            dosyalar = {}
            for kok in self.kokler:
                if not os.path.isdir(kok):
                    continue
                for dp, dirs, fns in os.walk(kok, followlinks=False):
                    # Klasör symlink'lerini os.walk takip etmez; yine de taramayı azalt.
                    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dp, d))]
                    for fn in fns:
                        if Path(fn).suffix.lower() not in GORSEL_UZANTILARI:
                            continue
                        yol = self._guvenli(os.path.join(dp, fn))
                        if yol:
                            dosyalar.setdefault(fn.lower(), set()).add(yol)
            self._dosya_haritasi = dosyalar
            self._dosya_zaman = simdi
            self._indeks_zaman = 0
        if simdi - self._indeks_zaman > 300:
            indeks = {}
            for kok in self.kokler:
                if not os.path.isdir(kok):
                    continue
                for dp, dirs, fns in os.walk(kok, followlinks=False):
                    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dp, d))]
                    for fn in fns:
                        if fn.lower() != "indeks.csv":
                            continue
                        p = self._guvenli(os.path.join(dp, fn))
                        if p:
                            for gid, yollar in _indeks_oku(p, self.kokler, self._dosya_haritasi).items():
                                indeks.setdefault(gid, set()).update(yollar)
            self._indeks = indeks
            ters = {}
            for gid, yollar in indeks.items():
                for yol in yollar:
                    ters.setdefault(yol, set()).add(gid)
            self._yol_kimlik = ters
            self._indeks_zaman = simdi

    @staticmethod
    def _tek(adaylar):
        adaylar = set(adaylar or ())
        return next(iter(adaylar)) if len(adaylar) == 1 else None

    def _dosya_alani(self, kayit, ikinci=False):
        if ikinci:
            return kayit.get("gorsel2_dosya"), kayit.get("gorsel2") or ""
        return kayit.get("gorsel_dosya"), kayit.get("link") or ""

    def _yerel_dosya(self, kayit, ikinci=False):
        self._yenile()
        dosya, link = self._dosya_alani(kayit, ikinci)
        # DB'de yazılı yol, ancak izinli kök altında çözümlenebiliyorsa geçerlidir.
        yol = self._goreli_dosya(dosya)
        if yol:
            return yol, "yerel"
        tur, kimlik = link_turu_ve_kimlik(link)
        proje = str(kayit.get("proje") or "").strip().upper()
        if tur == "onedrive" and kimlik:
            dogrudan = self._guvenli(os.path.join(self.gorsel_klasor, proje, kimlik))
            if dogrudan:
                return dogrudan, "yerel"
            yol = self._tek(self._dosya_haritasi.get(kimlik.lower()))
            if yol:
                return yol, "yerel"
        if tur == "dosya":
            # Excel'deki mutlak yol, ancak whitelist içindeyse; taşınmış Windows
            # yolunda yalnızca benzersiz basename eşleşmesi kabul edilir.
            yol = self._guvenli(link)
            if yol:
                return yol, "yerel"
            yol = self._tek(self._dosya_haritasi.get(_isim_yolu(link).lower()))
            if yol:
                return yol, "yerel"
        if tur == "gyazo" and kimlik:
            yol = self._tek(self._indeks.get(kimlik))
            if yol:
                return yol, "yerel"
            # Kimlik dosya adının tamamıysa doğruluk kesindir; zamanı/kullanıcıyı
            # andıran başka dosya adları asla tahmin edilmez.
            adaylar = self._dosya_haritasi.get((kimlik + ".jpg").lower(), set())
            adaylar = set(adaylar) | set(self._dosya_haritasi.get((kimlik + ".jpeg").lower(), set()))
            adaylar |= set(self._dosya_haritasi.get((kimlik + ".png").lower(), set()))
            adaylar |= set(self._dosya_haritasi.get((kimlik + ".webp").lower(), set()))
            adaylar |= set(self._dosya_haritasi.get((kimlik + ".gif").lower(), set()))
            yol = self._tek(adaylar)
            if yol:
                return yol, "yerel"
        return None, "yok"

    def yerel_dosya(self, kayit):
        """Ana görseli çözer: ``(yol|None, 'yerel'|'yok')``."""
        return self._yerel_dosya(kayit, ikinci=bool(kayit.get("_gorsel2")))

    def ikinci_dosya(self, kayit):
        """İkinci görsel (``gorsel2[_dosya]``) için aynı güvenli çözümleyici."""
        return self._yerel_dosya(kayit, ikinci=True)

    # ------------------------------------------------------------------ Gyazo
    def gyazo_kimlik(self, kayit):
        """Kayıttaki (ana veya ikinci) bağlantıdan 32 hex Gyazo kimliğini verir."""
        _, link = self._dosya_alani(kayit, bool(kayit.get("_gorsel2")))
        if not isinstance(link, str):
            return None
        tur, kimlik = link_turu_ve_kimlik(link)
        if tur != "gyazo" or not KIMLIK_RX.fullmatch(kimlik or ""):
            return None
        return kimlik.lower()

    def gyazo_mumkun(self, kayit):
        """Vekil açıksa, kayıtta geçerli Gyazo kimliği varsa ve kimlik olumsuz önbellekte değilse True."""
        kimlik = self.gyazo_kimlik(kayit) if self.gyazo_acik else None
        if not kimlik:
            return False
        return bool(self._gyazo_onbellek(kimlik)) or not self._gyazo_olumsuz(kimlik)

    def _gyazo_host_izinli(self, url):
        try:
            parts = urlparse(url)
        except ValueError:
            return False
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        host = parts.hostname.lower()
        return any(host == h or host.endswith("." + h) for h in self.gyazo_hostlar)

    def _gyazo_onbellek(self, kimlik):
        for uz in (".jpg", ".png"):
            yol = os.path.join(self.gyazo_klasor, kimlik + uz)
            if os.path.isfile(yol) and os.path.getsize(yol) > 0:
                return yol
        return None

    def _gyazo_olumsuz(self, kimlik):
        isaret = os.path.join(self.gyazo_klasor, kimlik + ".yok")
        try:
            return time.time() - os.path.getmtime(isaret) < GYAZO_OLUMSUZ_SN
        except OSError:
            return False

    def _gyazo_olumsuz_yaz(self, kimlik):
        try:
            with open(os.path.join(self.gyazo_klasor, kimlik + ".yok"), "w") as f:
                f.write(str(int(time.time())))
        except OSError:
            pass

    def _gyazo_http(self):
        if self._http is None:
            import requests
            self._http = requests.Session()
        return self._http

    def _gyazo_getir(self, url):
        """Yalnız izinli hostlar arasında yönlendirmeyi izler; gövdeyi sınırla okur."""
        http = self._gyazo_http()
        for _ in range(5):
            if not self._gyazo_host_izinli(url):
                return None
            r = http.get(url, stream=True, timeout=(5, GYAZO_ZAMAN_ASIMI), allow_redirects=False,
                         headers={"User-Agent": "KanitPaneli/2.2", "Accept": "image/*"})
            try:
                if r.status_code in (301, 302, 303, 307, 308):
                    hedef = r.headers.get("Location", "")
                    if not hedef:
                        return None
                    url = hedef if "://" in hedef else urlparse(url)._replace(path=hedef, query="").geturl()
                    continue
                if r.status_code != 200:
                    return None
                uzunluk = r.headers.get("Content-Length")
                if uzunluk and uzunluk.isdigit() and int(uzunluk) > GYAZO_MAX_BYTES:
                    return None
                parcalar = []
                toplam = 0
                for parca in r.iter_content(65536):
                    toplam += len(parca)
                    if toplam > GYAZO_MAX_BYTES:
                        return None
                    parcalar.append(parca)
                return b"".join(parcalar)
            finally:
                r.close()
        return None

    def gyazo_indir(self, kayit):
        """Gyazo bağlantısını sunucu tarafında indirir, doğrular ve önbellekler.

        Dönüş: yerel önbellek yolu ya da None. Başarısız kimlikler 10 dakika
        boyunca yeniden denenmez (olumsuz önbellek). Asla kayıt satırını değiştirmez.
        """
        if not self.gyazo_acik:
            return None
        kimlik = self.gyazo_kimlik(kayit)
        if not kimlik:
            return None
        yol = self._gyazo_onbellek(kimlik)
        if yol:
            return yol
        if self._gyazo_olumsuz(kimlik):
            return None
        if not self._gyazo_semafor.acquire(timeout=20):
            return None
        try:
            yol = self._gyazo_onbellek(kimlik)
            if yol:
                return yol
            try:
                veri = self._gyazo_getir(self.gyazo_kaynak.format(id=kimlik))
            except Exception:
                veri = None
            if not veri:
                self._gyazo_olumsuz_yaz(kimlik)
                return None
            try:
                from PIL import Image
                import io
                Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(veri)) as im:
                        bicim = str(im.format or "").upper()
                        im.verify()
                uz = GYAZO_BICIMLER.get(bicim)
                if not uz:
                    # Gyazo WEBP/GIF gibi biçimleri JPEG'e çevirerek sakla.
                    with Image.open(io.BytesIO(veri)) as im:
                        im.load()
                        cikti = io.BytesIO()
                        im.convert("RGB").save(cikti, format="JPEG", quality=90)
                        veri = cikti.getvalue()
                        uz = ".jpg"
            except Exception:
                self._gyazo_olumsuz_yaz(kimlik)
                return None
            hedef = os.path.join(self.gyazo_klasor, kimlik + uz)
            fd, gecici = tempfile.mkstemp(prefix="gyazo-", suffix=".tmp", dir=self.gyazo_klasor)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(veri)
                os.replace(gecici, hedef)
            except OSError:
                if os.path.exists(gecici):
                    os.unlink(gecici)
                return None
            try:
                os.unlink(os.path.join(self.gyazo_klasor, kimlik + ".yok"))
            except OSError:
                pass
            return hedef
        finally:
            self._gyazo_semafor.release()

    def gorsel_yolu(self, kayit):
        """Ana (veya ``_gorsel2``) görselin yolu ve kaynağı: yerel, gyazo veya yok."""
        yol, kaynak = self.yerel_dosya(kayit)
        if yol:
            return yol, kaynak
        yol = self.gyazo_indir(kayit)
        if yol:
            return yol, "gyazo"
        return None, "yok"

    def gecerli(self, yol):
        """Dosya gerçekten açılabilir bir görsel mi? (bozuk/kesik/aşırı büyük → False)

        Yalnız başlık ve yapı doğrulanır; piksel verisi yüklenmez, bu yüzden
        liste yüklemelerinde her çağrı ucuzdur.
        """
        if not yol or not os.path.isfile(yol):
            return False
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(yol) as im:
                    im.verify()
            return True
        except Exception:
            return False

    def kucuk(self, kayit, yol):
        """Doğrulanmış kaynaktan atomik 400px JPEG küçük resim üretir.

        Bozuk, decompression-bomb veya izinli kök dışındaki dosyada ``None``
        döner; asla rastgele/orijinal dosya yolunu geri vermez. Önbellek
        klasörü çalışma anında silinmişse her üretimde yeniden oluşturulur.
        """
        if not _guvenli_altinda(yol, list(self.kokler) + [self.gyazo_klasor]):
            return None
        try:
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        except Exception:
            return None
        ad = hashlib.sha256((str(kayit.get("anahtar") or "") + "\0" + str(yol)).encode("utf-8")).hexdigest()[:32] + ".jpg"
        hedef = os.path.join(self.thumbs, ad)
        try:
            os.makedirs(self.thumbs, exist_ok=True)
        except OSError:
            return None
        try:
            if os.path.exists(hedef) and os.path.getmtime(hedef) >= os.path.getmtime(yol):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(hedef) as eski:
                        eski.verify()
                return hedef
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(yol) as kontrol:
                    kontrol.verify()
                with Image.open(yol) as im:
                    im.load()
                    im = im.convert("RGB")
                    im.thumbnail((400, 400))
                    os.makedirs(self.thumbs, exist_ok=True)
                    fd, gecici = tempfile.mkstemp(prefix="thumb-", suffix=".tmp", dir=self.thumbs)
                    os.close(fd)
                    try:
                        im.save(gecici, format="JPEG", quality=80, optimize=True)
                        with Image.open(gecici) as dogrula:
                            dogrula.verify()
                        os.replace(gecici, hedef)
                    finally:
                        if os.path.exists(gecici):
                            os.unlink(gecici)
            return hedef
        except Exception:
            return None


def yer_tutucu_svg(baslik="Görsel açılamadı", aciklama="", genislik=400, yukseklik=300):
    """Bozuk/okunamayan görsel yerine gösterilecek sade SVG (bayt olarak).

    Metinler XML için kaçışlanır; dış kaynak içermez, bu yüzden nosniff ile
    güvenle ``image/svg+xml`` olarak sunulabilir.
    """
    from xml.sax.saxutils import escape
    w, h = int(genislik), int(yukseklik)
    boy = max(14, min(26, w // 16))
    kucuk = max(11, boy - 5)
    satirlar = [escape(str(baslik or ""))]
    if aciklama:
        satirlar.append(escape(str(aciklama)))
    y0 = h // 2 - (len(satirlar) - 1) * (kucuk + 6) // 2
    metin = "".join(
        '<text x="%d" y="%d" fill="%s" font-size="%d" font-weight="%s" text-anchor="middle" font-family="system-ui,Segoe UI,Arial,sans-serif">%s</text>'
        % (w // 2, y0 + i * (kucuk + 10), "#e2e8f0" if i == 0 else "#94a3b8", boy if i == 0 else kucuk, "700" if i == 0 else "400", t)
        for i, t in enumerate(satirlar)
    )
    cizgi = '<path d="M%d %dl%d %dM%d %dl%d -%d" stroke="#64748b" stroke-width="3" stroke-linecap="round"/>' % (
        w // 2 - 14, y0 - boy - 28, 28, 28, w // 2 - 14, y0 - boy, 28, 28)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-label="%s">'
           '<rect width="100%%" height="100%%" fill="#1f2937"/>%s%s</svg>') % (w, h, w, h, escape(str(baslik or "")), cizgi, metin)
    return svg.encode("utf-8")


def arsiv_tara(ayar, conn, cozucu):
    """İzinli arşivi kataloglar ve sadece kesin Gyazo kimliğiyle tek kayda bağlar.

    Aynı kimliği taşıyan birden fazla kayıt ya da birden çok aday dosya varsa
    ``kayit_id`` boş bırakılır; web katmanı bunu manuel eşleme kuyruğu olarak
    sunabilir.
    """
    # Kullanıcının açık tarama isteği beş dakikalık önbelleği beklemez.
    cozucu._dosya_zaman = 0
    cozucu._indeks_zaman = 0
    cozucu._yenile()
    arsiv = ayar.get("ARSIV_KLASOR") or getattr(cozucu, "arsiv_klasor", "")
    try:
        arsiv = str(Path(arsiv).expanduser().resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return {"tarandi": 0, "indekslendi": 0, "eslesti": 0, "eslesmeyen": 0, "belirsiz": 0, "hata": "geçersiz arşiv kökü"}
    if arsiv not in cozucu.kokler or not os.path.isdir(arsiv):
        return {"tarandi": 0, "indekslendi": 0, "eslesti": 0, "eslesmeyen": 0, "belirsiz": 0, "hata": "arşiv kökü izinli/değil veya yok"}

    kayit_kimlikleri = {}
    for r in conn.execute("SELECT id, link FROM kayitlar WHERE link IS NOT NULL AND link<>''"):
        tur, kimlik = link_turu_ve_kimlik(r["link"])
        if tur == "gyazo" and kimlik:
            kayit_kimlikleri.setdefault(kimlik, set()).add(r["id"])

    rapor = {"tarandi": 0, "indekslendi": 0, "eslesti": 0, "eslesmeyen": 0, "belirsiz": 0, "hata": None}
    zaman = time.strftime("%Y-%m-%d %H:%M:%S")
    for dp, dirs, fns in os.walk(arsiv, followlinks=False):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dp, d))]
        for fn in fns:
            if Path(fn).suffix.lower() not in GORSEL_UZANTILARI:
                continue
            yol = _guvenli_altinda(os.path.join(dp, fn), [arsiv])
            if not yol:
                continue
            rapor["tarandi"] += 1
            kimlikler = set(cozucu._yol_kimlik.get(yol, set()))
            stem = Path(fn).stem.lower()
            if KIMLIK_RX.fullmatch(stem):
                kimlikler.add(stem)
            kimlik = next(iter(kimlikler)) if len(kimlikler) == 1 else None
            adaylar = kayit_kimlikleri.get(kimlik, set()) if kimlik else set()
            # Tek kayıt yetmez: aynı kimliğe birden çok dosya bağlıysa belirsizdir.
            dosya_adaylari = set(cozucu._indeks.get(kimlik, set())) if kimlik else set()
            if kimlik:
                for uz in GORSEL_UZANTILARI:
                    dosya_adaylari.update(cozucu._dosya_haritasi.get(kimlik + uz, set()))
            tek_dosya = len(dosya_adaylari) == 1 and yol in dosya_adaylari
            otomatik = next(iter(adaylar)) if len(adaylar) == 1 and tek_dosya else None
            eski = conn.execute("SELECT kayit_id FROM arsiv_dosyalar WHERE yol=?", (yol,)).fetchone()
            # Belirsiz/yok otomatik eşlemede eski elle atanmış sahip korunur.
            kayit_id = eski["kayit_id"] if eski and eski["kayit_id"] else otomatik
            try:
                goreli = os.path.relpath(yol, arsiv)
                proje = goreli.split(os.sep, 1)[0].upper() if os.sep in goreli else ""
                conn.execute(
                    """INSERT INTO arsiv_dosyalar(yol,ad,proje,kimlik,kayit_id,guncelleme)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(yol) DO UPDATE SET ad=excluded.ad,proje=excluded.proje,
                       kimlik=excluded.kimlik,kayit_id=excluded.kayit_id,guncelleme=excluded.guncelleme""",
                    (yol, fn, proje, kimlik, kayit_id, zaman),
                )
                rapor["indekslendi"] += 1
            except Exception as e:
                rapor["hata"] = f"{type(e).__name__}: {e}"
                continue
            if otomatik is not None:
                rapor["eslesti"] += 1
            elif len(kimlikler) > 1 or len(adaylar) > 1 or len(dosya_adaylari) > 1:
                rapor["belirsiz"] += 1
            else:
                rapor["eslesmeyen"] += 1
    return rapor
