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
# Önbellek sınırları (AYAR'da yoksa bu varsayılanlar) ve temizlik davranışı.
ONBELLEK_VARSAYILAN = {"GYAZO_ONBELLEK_MB": 2000, "GYAZO_ONBELLEK_GUN": 0, "KUCUK_ONBELLEK_MB": 300}  # GUN 0 = yaş sınırı yok
ONBELLEK_TEMIZLIK_ARALIGI_SN = 600   # gerçek tarama en fazla 10 dakikada bir (ve süreç başında bir kez)
ONBELLEK_HEDEF_ORAN = 0.9            # sınır aşılınca bu orana inilir
ONBELLEK_TAZE_SN = 60                # son 60 sn içinde yazılan ya da okunan dosya silinmez (yarış koruması)
GECICI_DOSYA_YAS_SN = 3600           # yarım kalan .part/.tmp dosyaları bir saat sonra silinir
_ONBELLEK_GORSEL_RX = re.compile(r"^[0-9a-f]{32}\.(jpg|png)$")
_ONBELLEK_YOK_RX = re.compile(r"^[0-9a-f]{32}\.yok$")
_ONBELLEK_GECICI_RX = re.compile(r"^(gyazo|thumb)-.*\.(tmp|part)$")


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


def _onbellek_siniri(ayar, anahtar, carpan):
    """AYAR'daki MB/gün değerini bayta/saniyeye çevirir; geçersizde varsayılan, 0 = sınır yok."""
    varsayilan = ONBELLEK_VARSAYILAN[anahtar]
    try:
        deger = int(float(str((ayar or {}).get(anahtar, varsayilan)).strip()))
    except (TypeError, ValueError, OverflowError):
        deger = varsayilan
    return max(0, deger) * carpan


def _dokun(yol, mtime=None):
    """Servis edilen önbellek dosyasının mtime'ını HER isabette günceller (ucuz tek utime); hata yutar.

    LRU sırası için yeter; ayrıca dosya ONBELLEK_TAZE_SN boyunca budamadan korunur, böylece yol çözümlendikten
    sonra send_file açılmadan önce temizliğin dosyayı silmesi (FileNotFoundError → 500) yarışı kapanır.
    (Eskiden saatte bir güncelleniyordu; 1-60 dk önce görüntülenmiş dosya 'en eski' aday kalabiliyordu.)
    """
    try:
        os.utime(yol, None)
    except OSError:
        pass


def _onbellek_dosyalari(dizin):
    """Dizindeki düzenli dosyalar: ``[(yol, ad, boyut, mtime)]``. Sembolik bağ ve alt dizinler atlanır."""
    sonuc = []
    try:
        with os.scandir(dizin) as it:
            for e in it:
                try:
                    if e.is_symlink() or not e.is_file(follow_symlinks=False):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                sonuc.append((e.path, e.name, st.st_size, st.st_mtime))
    except OSError:
        return []
    return sonuc


def _onbellek_dizini_guvenli(dizin, onbellek_koku, korunan_kokler):
    """Temizlenecek dizin gerçekten önbellek kökünün ALTINDA ve kullanıcı görsel köklerinin DIŞINDA mı?

    ``tmp`` kökünün kendisi başka diske sembolik bağla taşınmış olabilir (ikisi
    birlikte çözülür); ama ``tmp/gyazo`` tek başına başka yere bağlıysa ya da
    bir görsel kökü (gorseller, telegram_gorseller, ...) içine düşüyorsa temizlik yapılmaz.
    """
    try:
        gercek = os.path.realpath(dizin)
        kok = os.path.realpath(onbellek_koku)
        if gercek == kok or os.path.commonpath((gercek, kok)) != kok:
            return False
        for k in korunan_kokler or ():
            kr = os.path.realpath(k)
            if os.path.commonpath((gercek, kr)) == kr:
                return False
    except (OSError, ValueError):
        return False
    return os.path.isdir(gercek)


def _onbellek_sil(yol, boyut, rapor):
    """Tek dosyayı siler; yarışta kaybolan dosya (FileNotFoundError) ve izin hataları yutulur."""
    try:
        os.unlink(yol)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    rapor["silinen"] += 1
    rapor["silinen_bayt"] += boyut
    return True


def _onbellek_buda(dizin, sinir_bayt, yas_sn, simdi=None):
    """Tek bir önbellek dizinini budar; yalnız bu modülün ürettiği dosya adlarına dokunur.

    Sıra: bir saatten eski yarım kalan geçici dosyalar, süresi geçen ``.yok``
    işaretleri, yaş sınırını aşan görseller; sonra toplam boyut sınırı
    aşılıyorsa en eski (mtime) dosyadan başlayarak sınırın %90'ına inene kadar.
    Son 60 saniyede yazılan dosyalar ve tanınmayan adlar asla silinmez.
    """
    simdi = time.time() if simdi is None else simdi
    rapor = {"dosya": 0, "bayt": 0, "silinen": 0, "silinen_bayt": 0, "kalan_dosya": 0, "kalan_bayt": 0}
    gorseller = []
    for yol, ad, boyut, mtime in _onbellek_dosyalari(dizin):
        rapor["dosya"] += 1
        rapor["bayt"] += boyut
        yas = simdi - mtime
        if _ONBELLEK_GECICI_RX.match(ad):
            if yas > GECICI_DOSYA_YAS_SN:
                _onbellek_sil(yol, boyut, rapor)
        elif _ONBELLEK_YOK_RX.match(ad):
            if yas > GYAZO_OLUMSUZ_SN:
                _onbellek_sil(yol, boyut, rapor)
        elif _ONBELLEK_GORSEL_RX.match(ad):
            if yas_sn > 0 and yas > yas_sn:
                _onbellek_sil(yol, boyut, rapor)
            else:
                gorseller.append((mtime, boyut, yol))
    toplam = sum(g[1] for g in gorseller)
    if sinir_bayt > 0 and toplam > sinir_bayt:
        hedef = int(sinir_bayt * ONBELLEK_HEDEF_ORAN)
        for mtime, boyut, yol in sorted(gorseller):
            if toplam <= hedef or simdi - mtime < ONBELLEK_TAZE_SN:
                break
            if _onbellek_sil(yol, boyut, rapor):
                toplam -= boyut
    rapor["kalan_dosya"] = rapor["dosya"] - rapor["silinen"]
    rapor["kalan_bayt"] = rapor["bayt"] - rapor["silinen_bayt"]
    return rapor


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
        self._gyazo_son_durum = None  # son Gyazo isteğinin HTTP durumu (toplu indirme raporu için)
        self._gyazo_kilit = threading.Lock()
        self._gyazo_semafor = threading.BoundedSemaphore(4)
        # Önbellek sınırları (bayt / saniye); 0 = sınır yok. Temizlik kilidi tek iş parçacığında çalışır.
        self.gyazo_sinir_bayt = _onbellek_siniri(ayar, "GYAZO_ONBELLEK_MB", 1024 * 1024)
        self.gyazo_yas_sn = _onbellek_siniri(ayar, "GYAZO_ONBELLEK_GUN", 86400)
        self.kucuk_sinir_bayt = _onbellek_siniri(ayar, "KUCUK_ONBELLEK_MB", 1024 * 1024)
        self._temizlik_kilit = threading.Lock()
        self._temizlik_zaman = 0.0  # 0: süreç başında ilk kullanımda bir kez çalışır
        self._son_temizlik = None
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
            try:
                st = os.stat(yol)
            except OSError:
                continue
            if st.st_size > 0:
                _dokun(yol, st.st_mtime)  # LRU: okunan dosya en eski sayılmasın
                return yol
        return None

    def _gyazo_onbellek_dosyasi(self, yol):
        """Yol Gyazo önbellek klasörünün altında mı? (içerik kimliğe bağlı, değişmez)"""
        try:
            kok = os.path.realpath(self.gyazo_klasor)
            return os.path.commonpath((os.path.realpath(yol), kok)) == kok
        except (OSError, ValueError):
            return False

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
                         headers={"User-Agent": "KanitPaneli/2.3", "Accept": "image/*"})
            self._gyazo_son_durum = getattr(r, "status_code", None)
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
        self._temizlik_gerekirse()
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
            self._gyazo_son_durum = None
            try:
                veri = self._gyazo_getir(self.gyazo_kaynak.format(id=kimlik))
            except Exception:
                veri = None
                self._gyazo_son_durum = "hata"
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
            try:
                os.makedirs(self.gyazo_klasor, exist_ok=True)
                fd, gecici = tempfile.mkstemp(prefix="gyazo-", suffix=".part", dir=self.gyazo_klasor)
            except OSError:
                return None
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(veri)
                os.replace(gecici, hedef)
            except OSError:
                # Yarım kalan .part dosyası hemen; süreç çökerse periyodik temizlikle silinir.
                try:
                    os.unlink(gecici)
                except OSError:
                    pass
                return None
            try:
                os.unlink(os.path.join(self.gyazo_klasor, kimlik + ".yok"))
            except OSError:
                pass
            return hedef
        finally:
            self._gyazo_semafor.release()

    # --------------------------------------------------------------- Önbellek
    def _onbellek_dizinleri(self):
        return (("gyazo", self.gyazo_klasor, self.gyazo_sinir_bayt, self.gyazo_yas_sn),
                ("thumbs", self.thumbs, self.kucuk_sinir_bayt, 0))

    def _temizlik_gerekirse(self):
        """Ucuz denetim: gerçek tarama en fazla 10 dakikada bir (ve süreç başında bir kez)."""
        if time.time() - self._temizlik_zaman >= ONBELLEK_TEMIZLIK_ARALIGI_SN:
            self.onbellek_temizle()

    def onbellek_temizle(self, zorla=False):
        """Gyazo ve küçük resim önbelleklerini boyut/yaş sınırlarının altına çeker.

        Dönüş: ``{"gyazo": rapor, "thumbs": rapor}`` ya da ``None`` (süre dolmadı
        veya başka bir iş parçacığı temizliyor; ``zorla=True`` bekler ve çalışır).
        Hiçbir istisna dışarı sızmaz. Yalnız önbellek kökü altındaki iki klasöre,
        orada da yalnız bu modülün ürettiği adlara dokunur; sembolik bağla başka
        yere giden klasör ve kullanıcı görsel kökleri (gorseller, telegram_gorseller)
        atlanır.
        """
        if not self._temizlik_kilit.acquire(blocking=bool(zorla)):
            return None
        try:
            simdi = time.time()
            if not zorla and simdi - self._temizlik_zaman < ONBELLEK_TEMIZLIK_ARALIGI_SN:
                return None
            self._temizlik_zaman = simdi
            rapor = {}
            for ad, dizin, sinir, yas in self._onbellek_dizinleri():
                try:
                    if not _onbellek_dizini_guvenli(dizin, self.onbellek, self.kokler):
                        rapor[ad] = {"atlandi": "klasör önbellek kökü dışında ya da görsel köküyle çakışıyor"}
                        continue
                    rapor[ad] = _onbellek_buda(dizin, sinir, yas, simdi)
                except Exception as e:  # temizlik hiçbir isteği düşürmez
                    rapor[ad] = {"hata": type(e).__name__}
            self._son_temizlik = {"zaman": simdi, "rapor": rapor}
            return rapor
        finally:
            self._temizlik_kilit.release()

    def onbellek_durumu(self):
        """Önbellek klasörlerinin dosya sayısı, toplam boyutu ve sınırları (durum sayfası için)."""
        durum = {}
        toplam = 0
        for ad, dizin, sinir, yas in self._onbellek_dizinleri():
            dosyalar = _onbellek_dosyalari(dizin)
            bayt = sum(d[2] for d in dosyalar)
            toplam += bayt
            durum[ad] = {"dizin": dizin, "dosya": len(dosyalar), "bayt": bayt, "mb": round(bayt / 1048576, 2),
                         "sinir_mb": sinir // 1048576, "yas_gun": yas // 86400,
                         "doluluk_yuzde": round(100.0 * bayt / sinir, 1) if sinir else None}
        son = self._son_temizlik
        durum["toplam_bayt"] = toplam
        durum["toplam_mb"] = round(toplam / 1048576, 2)
        durum["son_temizlik"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(son["zaman"])) if son else None
        durum["son_temizlik_raporu"] = son["rapor"] if son else None
        return durum

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
        self._temizlik_gerekirse()
        try:
            eski_mtime = os.path.getmtime(hedef) if os.path.exists(hedef) else None
            # Gyazo önbelleğindeki kaynak kimliğe bağlıdır ve değişmez; mtime'ı LRU için
            # güncellendiğinden bayatlık ölçütü sayılmaz (gereksiz yeniden üretim olmaz).
            if eski_mtime is not None and (self._gyazo_onbellek_dosyasi(yol) or eski_mtime >= os.path.getmtime(yol)):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(hedef) as eski:
                        eski.verify()
                _dokun(hedef, eski_mtime)
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


def onbellek_durumu(ayar=None, onbellek=None):
    """``AYAR`` (veya verilen ayar) için önbellek özeti; panel/CLI ``gorsel.onbellek_durumu()`` diye çağırır."""
    if ayar is None:
        from .settings import AYAR as ayar
    return GorselCozucu(ayar, onbellek or ayar["ONBELLEK"]).onbellek_durumu()


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


# ------------------------------------------------------------------ Toplu Gyazo ön-indirme (CLI: gyazo-onbellekle)
_GYAZO_SEBEP = {404: "Gyazo'da görsel yok (404)", 410: "Gyazo görseli kaldırmış (410)", 403: "Gyazo erişimi reddetti (403)",
                429: "Gyazo hız sınırı (429)", "hata": "ağ hatası / zaman aşımı"}
GYAZO_TOPLU_429_BEKLEME = (30, 60, 120, 300)


def _gyazo_sebep(durum):
    if durum in _GYAZO_SEBEP:
        return _GYAZO_SEBEP[durum]
    if isinstance(durum, int):
        return f"sunucu hatası (HTTP {durum})" if durum >= 500 else ("indirilemedi (bozuk, çok büyük ya da görsel olmayan içerik)" if durum == 200 else f"HTTP {durum}")
    return "indirilemedi (izinsiz bağlantı ya da meşgul)"


def gyazo_toplu_indir(conn, cozucu, ayar=None, *, en_cok=0, bekleme_sn=0.15, uyku=None, rapor_yolu=None, ilerleme=None):
    """Kayıtlardaki tüm Gyazo bağlantılarını (ana ve ikinci görsel) sunucu önbelleğine bir kez indirir.

    Amaç: eski Excel kayıtlarının tek kopyası Gyazo'da; bağlantı ölmeden sunucuya kopyalamak ve
    açılamayanları raporlamak. Yeniden çalıştırılabilir: önbellekte olan kimlikler atlanır, her kimlik
    bu çalıştırmada bir kez daha denenir (10 dakikalık olumsuz işaret yok sayılır). Hız sınırında (429)
    30/60/120/300 s bekler; yine 429 ise durur ve sonraki çalıştırma kaldığı yerden sürer.
    Kayıt satırları hiçbir zaman değiştirilmez; yalnız önbellek dosyaları ve rapor dosyası yazılır.
    """
    if not getattr(cozucu, "gyazo_acik", False):
        raise ValueError("GYAZO_PROXY kapalı; önce .env içinde GYAZO_PROXY=1 yapın.")
    uyku = uyku or time.sleep
    t0 = time.monotonic()
    sayac = {"baglanti": 0, "kimlik": 0, "zaten_var": 0, "indirilen": 0, "acilamayan": 0, "kimliksiz": 0,
             "hiz_siniri_bekleme_sn": 0, "durduruldu": None}
    acilamayan = []
    gorulen = {}
    cur = conn.execute("SELECT id, proje, personel, link, gorsel_dosya, gorsel2, gorsel2_dosya FROM kayitlar "
                       "WHERE COALESCE(silindi,0)=0 AND (LOWER(COALESCE(link,'')) LIKE '%gyazo.com/%' "
                       "OR LOWER(COALESCE(gorsel2,'')) LIKE '%gyazo.com/%') ORDER BY id")
    sutunlar = [d[0] for d in cur.description]
    adaylar = []
    for satir in cur.fetchall():
        r = dict(zip(sutunlar, satir))
        for ikinci in (False, True):
            link = (r.get("gorsel2") if ikinci else r.get("link")) or ""
            dusuk = str(link).lower()
            if "gyazo.com/" not in dusuk or "teamzone" in dusuk:  # teamzone.gyazo.com ayrı bir hizmet, Gyazo kimliği taşımaz
                continue
            k = dict(r)
            k["_gorsel2"] = ikinci
            adaylar.append((r, link, k))
    if en_cok and en_cok > 0:
        adaylar = adaylar[:en_cok]
    sayac["baglanti"] = len(adaylar)

    def _yok_sil(kimlik):
        try:
            os.unlink(os.path.join(cozucu.gyazo_klasor, kimlik + ".yok"))
        except OSError:
            pass

    def _dene(k):
        cozucu._gyazo_son_durum = None
        yol = cozucu.gyazo_indir(k)
        return yol, cozucu._gyazo_son_durum

    toplam = len(adaylar)
    for i, (r, link, k) in enumerate(adaylar, 1):
        kimlik = cozucu.gyazo_kimlik(k)
        if not kimlik:
            sayac["kimliksiz"] += 1
            acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, "Gyazo kimliği okunamadı"))
        elif kimlik in gorulen:
            if gorulen[kimlik]:
                sayac["zaten_var"] += 1
            else:
                sayac["acilamayan"] += 1
                acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, "aynı bağlantı bu çalıştırmada açılamadı"))
        elif cozucu._gyazo_onbellek(kimlik):
            sayac["kimlik"] += 1
            gorulen[kimlik] = True
            sayac["zaten_var"] += 1
        else:
            sayac["kimlik"] += 1
            _yok_sil(kimlik)
            yol, durum = _dene(k)
            if not yol and (durum == "hata" or (isinstance(durum, int) and durum >= 500)):
                uyku(5)
                _yok_sil(kimlik)
                yol, durum = _dene(k)
            for bekle in GYAZO_TOPLU_429_BEKLEME:
                if yol or durum != 429:
                    break
                sayac["hiz_siniri_bekleme_sn"] += bekle
                uyku(bekle)
                _yok_sil(kimlik)
                yol, durum = _dene(k)
            if yol:
                gorulen[kimlik] = True
                sayac["indirilen"] += 1
            else:
                gorulen[kimlik] = False
                sayac["acilamayan"] += 1
                acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, _gyazo_sebep(durum)))
                if durum == 429:
                    sayac["durduruldu"] = ("Gyazo hız sınırı sürüyor; %d/%d bağlantı işlendi. 15 dakika sonra aynı komutu yeniden çalıştırın "
                                           "(kaldığı yerden devam eder)." % (i, toplam))
            if bekleme_sn and i < toplam and not sayac["durduruldu"]:
                uyku(bekleme_sn)
        if ilerleme and (i % 100 == 0 or i == toplam):
            ilerleme(i, toplam, dict(sayac))
        if sayac["durduruldu"]:
            break

    if rapor_yolu is None and ayar and ayar.get("DB"):
        rapor_yolu = os.path.join(os.path.dirname(os.path.abspath(str(ayar["DB"]))), "gyazo-acilamayan.csv")
    if rapor_yolu:
        import csv
        gecici = str(rapor_yolu) + ".tmp"
        with open(gecici, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["kayit_id", "proje", "personel", "link", "sebep"])
            w.writerows(acilamayan)
        os.replace(gecici, rapor_yolu)
    sonuc = dict(sayac)
    sonuc.update({"sure_sn": round(time.monotonic() - t0, 1), "rapor": rapor_yolu, "acilamayan_ornek": acilamayan[:20]})
    try:
        durum = cozucu.onbellek_durumu()
        g = durum.get("gyazo") if isinstance(durum, dict) else None
        if isinstance(g, dict):
            sonuc["onbellek_gyazo_mb"] = g.get("mb")
            sonuc["onbellek_sinir_mb"] = g.get("sinir_mb")
            if g.get("sinir_mb") and g.get("mb") and g["mb"] > 0.8 * g["sinir_mb"]:
                sonuc["uyari"] = ("Gyazo önbelleği sınırına yaklaştı (%s / %s MB); sınır dolunca en eski kopyalar silinir. "
                                  ".env içinde GYAZO_ONBELLEK_MB değerini yükseltin (örn. 5000) ve kanit-web'i yeniden başlatın." % (g["mb"], g["sinir_mb"]))
    except Exception:
        pass
    return sonuc
