# -*- coding: utf-8 -*-
"""Yerel, erişim denetimli görsel çözümleme.

Yerel dosyalar izinli kökler altında çözülür. Gyazo (2.3.0) ve 2.3.2'den
itibaren Snappark/Teamzone bağlantıları yalnız izinli hostlardan, boyut ve
PIL doğrulamasıyla sunucu önbelleğine indirilir; kayıt satırı asla değişmez.
"""
import csv
import hashlib
import ipaddress
import logging
import os
import socket
from datetime import datetime, timedelta
import re
import tempfile
import threading
import time
import unicodedata
import warnings
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit

from .excel_oku import link_turu_ve_kimlik

GORSEL_UZANTILARI = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
KIMLIK_RX = re.compile(r"[0-9a-f]{32}", re.I)
MAX_IMAGE_PIXELS = 25_000_000
# Gyazo vekili: yalnız bu hostlar, yalnız 32 hex kimlik, sınırlı boyut/süre.
GYAZO_HOSTLAR = ("gyazo.com", "i.gyazo.com", "t.gyazo.com")  # t.gyazo.com: Gyazo Teams görsel yönlendirme hedefi
GYAZO_KAYNAK = "https://i.gyazo.com/{id}.jpg"
GYAZO_MAX_BYTES = 20 * 1024 * 1024
GYAZO_ZAMAN_ASIMI = 15              # okuma zaman aşımı (sn); bağlantı zaman aşımı BAGLANTI_ZAMAN_ASIMI
BAGLANTI_ZAMAN_ASIMI = 5
DIS_TOPLAM_SURE_SN = 30             # 2.3.2-inc: tek indirmenin (yönlendirmeler + gövde) toplam süre üst sınırı
GORSEL_ISTEK_BEKLEME_SN = 10        # /gorsel isteği indirme yuvası için en çok bu kadar bekler
TOPLU_BEKLEME_SN = 20               # toplu/gece kopyalamada yuva beklemesi
ARKA_PLAN_ESZAMANLI = 2             # /kucuk isteklerinin arka planda başlattığı en çok eşzamanlı dış indirme
YONLENDIRME_SINIRI = 5
ERISIM_ATLAMA_ESIGI = 3             # bir dış servis art arda bu kadar FARKLI bağlantıda bağlantı kuramazsa çalıştırmada atlanır
GYAZO_OLUMSUZ_SN = 600
GYAZO_BICIMLER = {"JPEG": ".jpg", "PNG": ".png"}
# Önbellek sınırları (AYAR'da yoksa bu varsayılanlar) ve temizlik davranışı.
ONBELLEK_VARSAYILAN = {"GYAZO_ONBELLEK_MB": 2000, "GYAZO_ONBELLEK_GUN": 0, "KUCUK_ONBELLEK_MB": 300}  # GUN 0 = yaş sınırı yok
ONBELLEK_TEMIZLIK_ARALIGI_SN = 600   # gerçek tarama en fazla 10 dakikada bir (ve süreç başında bir kez)
ONBELLEK_HEDEF_ORAN = 0.9            # sınır aşılınca bu orana inilir
ONBELLEK_TAZE_SN = 60                # son 60 sn içinde yazılan ya da okunan dosya silinmez (yarış koruması)
GECICI_DOSYA_YAS_SN = 3600           # yarım kalan .part/.tmp dosyaları bir saat sonra silinir
# 32 hex: Gyazo kimliği / küçük resim; 40 hex: dış görsel (sha1(normalize URL), 2.3.2).
_ONBELLEK_GORSEL_RX = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40})\.(jpg|png)$")
_ONBELLEK_YOK_RX = re.compile(r"^(?:[0-9a-f]{32}|[0-9a-f]{40})\.yok$")
_ONBELLEK_GECICI_RX = re.compile(r"^(gyazo|thumb|dis)-.*\.(tmp|part)$")
# 2.3.2 — Dış görsel servisleri: yalnız bu hostlar (alt alan adları dahil), yönlendirme de yalnız bunlara.
DIS_GORSEL_HOSTLAR = {
    "snappark": ("img.snappark.net", "snappark.net"),
    "teamzone": ("teamzone.gyazo.com", "i.gyazo.com", "t.gyazo.com"),  # i./t.gyazo.com: Gyazo Teams görselinin dosya ve yönlendirme hedefleri
}
DIS_GORSEL_ADLARI = {"gyazo": "Gyazo", "snappark": "Snappark", "teamzone": "Teamzone"}
DIS_MAX_BYTES = GYAZO_MAX_BYTES
_SNAPPARK_YOL_RX = re.compile(r"^/s/([A-Za-z0-9_-]{3,64})(?:/raw)?/?$")
_TEST_HOST_RX = re.compile(r"^(127\.0\.0\.1|localhost):(\d{2,5})$")


_GUVENSIZ_URL_KARAKTER = re.compile(r"[^\x21-\x7e]|[\\@]")  # boşluk, kontrol, ASCII dışı, ters bölü, '@' (userinfo)
_logger = logging.getLogger(__name__)


def _guvenli_url(url, izinli_hostlar, test_host=None):
    """2.3.2-inc: ortak URL/yönlendirme denetimi (SSRF). True yalnız şu durumda:

    * metin, en çok 2048 karakter; boşluk, kontrol karakteri, ASCII dışı karakter, ters bölü ya da '@' YOK
      (``http://İÇ-IP\\@img.snappark.net/`` gibi ayrıştırıcı farkı yükleri baştan reddedilir);
    * şema https; host ``urlsplit`` ile okunur ve izinli listedeki bir hostla TAM eşleşir (sonek/alt alan adı değil);
      port yok ya da 443; IPv6/IP değişmezi izinli listede olmadığı için reddedilir;
    * ``urllib3.util.parse_url`` aynı hostu okumalıdır (iki ayrıştırıcı aynı sonucu vermezse ret);
    * istisna: ``test_host`` ("127.0.0.1:PORT", yalnız DIS_GORSEL_TEST_HOST) ile netloc birebir aynıysa http/https kabul.
    """
    if not isinstance(url, str) or not url or len(url) > 2048 or _GUVENSIZ_URL_KARAKTER.search(url):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if not host or parts.username is not None or parts.password is not None:
        return False
    try:
        from urllib3.util import parse_url
        u3 = parse_url(url)
        if (u3.host or "").lower().strip("[]") != host or u3.auth:
            return False
    except Exception:
        return False
    if test_host and parts.scheme in ("http", "https") and parts.netloc.lower() == str(test_host).lower():
        return True
    if parts.scheme != "https" or port not in (None, 443):
        return False
    return host in {str(h).lower() for h in izinli_hostlar}


def _host_izinli(url, hostlar):
    """Geriye uyum adı: ``_guvenli_url`` (test hostu yok)."""
    return _guvenli_url(url, hostlar)


class IcAdresHatasi(Exception):
    """Hostun çözüldüğü adres özel/loopback/link-local vb. (SSRF koruması): bağlantı kurulmadı."""


def _ic_adres_mi(ip_metni):
    try:
        ip = ipaddress.ip_address(str(ip_metni).split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (not ip.is_global) or ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved \
        or ip.is_unspecified


def _adres_denetle(host, port, test_host=None):
    """Bağlanmadan önce hostun çözüldüğü TÜM adresleri denetler. Test hostu (yalnız DIS_GORSEL_TEST_HOST) birebir eşleşirse muaf."""
    import requests
    if test_host and ("%s:%s" % (host, port)).lower() == str(test_host).lower():
        return
    try:
        adresler = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as e:
        hata = requests.exceptions.ConnectionError("DNS çözümlenemedi: %s (%s)" % (host, type(e).__name__))
        hata.kanit_erisim = True
        raise hata
    if not adresler:
        hata = requests.exceptions.ConnectionError("DNS çözümlenemedi: %s" % host)
        hata.kanit_erisim = True
        raise hata
    for adres in adresler:
        if _ic_adres_mi(adres[4][0]):
            raise IcAdresHatasi("%s iç ağ adresine çözülüyor; bağlanılmadı" % host)


def _guvenli_adaptor(test_host_al):
    """requests HTTPAdapter: her istekten önce hedef hostun çözüldüğü IP'leri denetler (vekil kullanılıyorsa vekil denetler)."""
    from requests.adapters import HTTPAdapter
    from requests.utils import select_proxy

    class GuvenliAdaptor(HTTPAdapter):
        def send(self, request, **kw):
            parts = urlsplit(request.url)
            proxy = select_proxy(request.url, kw.get("proxies") or {})
            if not proxy:
                _adres_denetle(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80), test_host_al())
            return super().send(request, **kw)
    return GuvenliAdaptor(max_retries=0)


def _hata_turu(e):
    """İndirme istisnasını sınıflar: 'ic_adres' | 'erisim' (DNS, bağlantı reddi, bağlantı zaman aşımı) | 'hata' (bağlantıya özgü)."""
    if isinstance(e, IcAdresHatasi):
        return "ic_adres"
    try:
        import requests
        from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, NewConnectionError
    except Exception:  # pragma: no cover
        return "hata"
    if getattr(e, "kanit_erisim", False) or isinstance(e, requests.exceptions.ConnectTimeout):
        return "erisim"
    if isinstance(e, requests.exceptions.ConnectionError):
        ic = e.args[0] if e.args else None
        if isinstance(ic, MaxRetryError):
            ic = ic.reason
        if isinstance(ic, (NewConnectionError, ConnectTimeoutError)):
            return "erisim"
        return "hata"
    if isinstance(e, requests.exceptions.RequestException):
        return "hata"
    if isinstance(e, (socket.gaierror, ConnectionRefusedError)) or (isinstance(e, OSError) and type(e) is OSError):
        return "erisim"
    return "hata"


def dis_gorsel_cozumle(link):
    """Snappark/Teamzone bağlantısını normalize eder; ağ isteği yapmaz.

    Dönüş: ``{"tur", "url" (normalize), "anahtar" (sha1 hex), "adaylar" [denenecek URL'ler]}`` ya da None.
    Snappark: ``*.snappark.net/s/<id>`` ve ``/s/<id>/raw/`` → ``https://img.snappark.net/s/<id>/raw/`` (kimlik büyük/küçük harf duyarlı).
    Teamzone: ``teamzone.gyazo.com/<32hex>`` → önce ``i.gyazo.com/<id>.png``, sonra ``.jpg``, sonra Teamzone adresinin kendisi.
    """
    s = str(link or "").strip()
    if not s or len(s) > 2048:
        return None
    try:
        parts = urlparse(s)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if host == "snappark.net" or host.endswith(".snappark.net"):
        m = _SNAPPARK_YOL_RX.match(parts.path or "")
        if not m:
            return None
        url = "https://img.snappark.net/s/%s/raw/" % m.group(1)
        return {"tur": "snappark", "url": url, "anahtar": hashlib.sha1(url.encode("utf-8")).hexdigest(), "adaylar": [url]}
    if host == "teamzone.gyazo.com":
        son = (parts.path or "").rstrip("/").rsplit("/", 1)[-1]
        kimlik = son.split(".", 1)[0].lower()
        if not KIMLIK_RX.fullmatch(kimlik):
            return None
        url = "https://teamzone.gyazo.com/" + kimlik
        adaylar = ["https://i.gyazo.com/%s.png" % kimlik, "https://i.gyazo.com/%s.jpg" % kimlik, url]
        return {"tur": "teamzone", "url": url, "anahtar": hashlib.sha1(url.encode("utf-8")).hexdigest(), "adaylar": adaylar}
    return None


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
        self.dis_klasor = os.path.join(self.onbellek, "dis")
        os.makedirs(self.thumbs, exist_ok=True)
        os.makedirs(self.gyazo_klasor, exist_ok=True)
        os.makedirs(self.dis_klasor, exist_ok=True)
        self.gyazo_acik = str(ayar.get("GYAZO_PROXY", "1")).strip().lower() in ("1", "true", "evet")
        self.gyazo_hostlar = tuple(GYAZO_HOSTLAR)
        self.gyazo_kaynak = GYAZO_KAYNAK
        self._http = None
        self._gyazo_son_durum = None  # son Gyazo isteğinin HTTP durumu (toplu indirme raporu için)
        self._gyazo_kilit = threading.Lock()
        self._gyazo_semafor = threading.BoundedSemaphore(4)
        # 2.3.2 — Snappark/Teamzone: ayrı anahtar (varsayılan GYAZO_PROXY ile aynı), ayrı semafor, aynı güvenlik sınırları.
        self.dis_acik = str(ayar.get("DIS_GORSEL_PROXY", ayar.get("GYAZO_PROXY", "1"))).strip().lower() in ("1", "true", "evet")
        self.dis_hostlar = {k: tuple(v) for k, v in DIS_GORSEL_HOSTLAR.items()}
        self._dis_son_durum = None
        self._dis_semafor = threading.BoundedSemaphore(4)
        # 2.3.2-inc: /kucuk isteği dış indirmeyi beklemez; arka planda en çok ARKA_PLAN_ESZAMANLI indirme başlatır.
        self._arka_semafor = threading.BoundedSemaphore(ARKA_PLAN_ESZAMANLI)
        self._arka_kilit = threading.Lock()
        self._arka_aktif = set()
        # Yalnız yerel uçtan uca test: dış adayların hepsi bu loopback sunucuya yönlendirilir (127.0.0.1/localhost dışı yok sayılır).
        m = _TEST_HOST_RX.match(str(ayar.get("DIS_GORSEL_TEST_HOST") or "").strip())
        self.dis_test_host = m.group(0) if m else None
        if self.dis_test_host:
            _logger.warning("DIS_GORSEL_TEST_HOST etkin (%s): dış görseller bu yerel test sunucusundan alınır. "
                            "Canlı sunucuda .env'den bu satırı silin.", self.dis_test_host)
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
        return _guvenli_url(url, self.gyazo_hostlar, self.dis_test_host)

    def _gyazo_onbellek(self, kimlik):
        return self._onbellekte(self.gyazo_klasor, kimlik)

    @staticmethod
    def _onbellekte(klasor, ad):
        for uz in (".jpg", ".png"):
            yol = os.path.join(klasor, ad + uz)
            try:
                st = os.stat(yol)
            except OSError:
                continue
            if st.st_size > 0:
                _dokun(yol, st.st_mtime)  # LRU: okunan dosya en eski sayılmasın
                return yol
        return None

    def _gyazo_onbellek_dosyasi(self, yol):
        """Yol Gyazo ya da dış görsel önbelleğinin altında mı? (içerik kimliğe/URL'ye bağlı, değişmez)"""
        for klasor in (self.gyazo_klasor, self.dis_klasor):
            try:
                kok = os.path.realpath(klasor)
                if os.path.commonpath((os.path.realpath(yol), kok)) == kok:
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _gyazo_olumsuz(self, kimlik):
        return self._olumsuz_mu(self.gyazo_klasor, kimlik)

    def _gyazo_olumsuz_yaz(self, kimlik):
        self._olumsuz_yaz(self.gyazo_klasor, kimlik)

    @staticmethod
    def _olumsuz_mu(klasor, ad):
        try:
            return time.time() - os.path.getmtime(os.path.join(klasor, ad + ".yok")) < GYAZO_OLUMSUZ_SN
        except OSError:
            return False

    @staticmethod
    def _olumsuz_yaz(klasor, ad):
        try:
            with open(os.path.join(klasor, ad + ".yok"), "w") as f:
                f.write(str(int(time.time())))
        except OSError:
            pass

    def _gyazo_http(self):
        if self._http is None:
            import requests
            oturum = requests.Session()
            adaptor = _guvenli_adaptor(lambda: self.dis_test_host)
            oturum.mount("https://", adaptor)
            oturum.mount("http://", adaptor)
            self._http = oturum
        return self._http

    def _gyazo_getir(self, url):
        """Yalnız izinli hostlar arasında yönlendirmeyi izler; gövdeyi sınırla okur."""
        def durum(kod):
            self._gyazo_son_durum = kod
        return self._sinirli_getir(url, self._gyazo_host_izinli, GYAZO_MAX_BYTES, durum)

    def _sinirli_getir(self, url, izinli, en_cok_bayt, durum_yaz, sadece_gorsel=False):
        """Ortak indirici: en çok 5 yönlendirme, her adımda ``_guvenli_url`` denetimi, Content-Length ve akış boyut sınırı,
        bağlantı 5 sn / okuma 15 sn / toplam DIS_TOPLAM_SURE_SN zaman sınırı.

        ``sadece_gorsel``: 200 yanıtı ``Content-Type: image/*`` değilse reddedilir (giriş sayfası / HTML).
        Durumlar: HTTP kodu ya da 'izinsiz' (izin verilmeyen adres/yönlendirme), 'zaman_asimi', 'gorsel_degil', 'buyuk', 'yonlendirme'.
        """
        http = self._gyazo_http()
        bitis = time.monotonic() + DIS_TOPLAM_SURE_SN
        for _ in range(YONLENDIRME_SINIRI + 1):
            if not izinli(url):
                durum_yaz("izinsiz")
                return None
            kalan = bitis - time.monotonic()
            if kalan <= 0:
                durum_yaz("zaman_asimi")
                return None
            r = http.get(url, stream=True, timeout=(min(BAGLANTI_ZAMAN_ASIMI, kalan), min(GYAZO_ZAMAN_ASIMI, kalan)), allow_redirects=False,
                         headers={"User-Agent": "KanitPaneli/2.3", "Accept": "image/*"})
            durum_yaz(getattr(r, "status_code", None))
            try:
                if r.status_code in (301, 302, 303, 307, 308):
                    hedef = r.headers.get("Location", "")
                    if not hedef or not isinstance(hedef, str) or _GUVENSIZ_URL_KARAKTER.search(hedef):
                        _logger.warning("Dış görsel yönlendirmesi reddedildi (geçersiz Location).")
                        durum_yaz("izinsiz")
                        return None
                    url = urljoin(url, hedef)  # göreli Location güvenle birleştirilir; sonuç döngü başında yeniden denetlenir
                    if not izinli(url):
                        try:
                            host = urlsplit(url).hostname
                        except ValueError:
                            host = None
                        _logger.warning("Dış görsel yönlendirmesi izinli olmayan adrese reddedildi: %s", str(host or "?")[:100])
                        durum_yaz("izinsiz")
                        return None
                    continue
                if r.status_code != 200:
                    return None
                if sadece_gorsel:
                    tur = str((r.headers or {}).get("Content-Type", "") or "").split(";", 1)[0].strip().lower()
                    if not tur.startswith("image/"):
                        durum_yaz("gorsel_degil")
                        return None
                uzunluk = r.headers.get("Content-Length")
                if uzunluk and uzunluk.isdigit() and int(uzunluk) > en_cok_bayt:
                    if sadece_gorsel:
                        durum_yaz("buyuk")
                    return None
                parcalar = []
                toplam = 0
                for parca in self._parcalar(r):
                    if time.monotonic() > bitis:
                        durum_yaz("zaman_asimi")
                        return None
                    toplam += len(parca)
                    if toplam > en_cok_bayt:
                        if sadece_gorsel:
                            durum_yaz("buyuk")
                        return None
                    parcalar.append(parca)
                return b"".join(parcalar)
            finally:
                r.close()
        if sadece_gorsel:
            durum_yaz("yonlendirme")
        return None

    @staticmethod
    def _parcalar(r, boyut=65536):
        """Gövde parçaları. Gerçek urllib3 yanıtında ``read1`` (gelen kadarını hemen verir): damlatan sunucuda bile toplam süre
        denetimi her parçada çalışır. Sahte/eski yanıtlarda ``iter_content``."""
        ham = getattr(r, "raw", None)
        oku = getattr(ham, "read1", None)
        if callable(oku) and hasattr(ham, "_fp"):
            while True:
                parca = oku(boyut, decode_content=True)
                if not parca:
                    return
                yield parca
        else:
            yield from r.iter_content(boyut)

    @staticmethod
    def _gorsel_dogrula(veri):
        """PIL ile doğrular (decompression bomb dahil); JPEG/PNG dışını JPEG'e çevirir. -> (bayt, uzanti) ya da None."""
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
                # WEBP/GIF gibi biçimler JPEG'e çevrilerek saklanır.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(veri)) as im:
                        im.load()
                        cikti = io.BytesIO()
                        im.convert("RGB").save(cikti, format="JPEG", quality=90)
                        veri = cikti.getvalue()
                        uz = ".jpg"
            return veri, uz
        except Exception:
            return None

    @staticmethod
    def _atomik_yaz(klasor, ad, veri, onek):
        """Geçici dosya + os.replace; hata olursa None (yarım .part temizlenir)."""
        hedef = os.path.join(klasor, ad)
        try:
            os.makedirs(klasor, exist_ok=True)
            fd, gecici = tempfile.mkstemp(prefix=onek, suffix=".part", dir=klasor)
        except OSError:
            return None
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(veri)
            os.replace(gecici, hedef)
        except OSError:
            try:
                os.unlink(gecici)
            except OSError:
                pass
            return None
        return hedef

    def gyazo_indir(self, kayit, bekle=TOPLU_BEKLEME_SN):
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
        if not self._gyazo_semafor.acquire(timeout=max(0, bekle)):
            return None
        try:
            yol = self._gyazo_onbellek(kimlik)
            if yol:
                return yol
            self._gyazo_son_durum = None
            try:
                veri = self._gyazo_getir(self.gyazo_kaynak.format(id=kimlik))
            except Exception as e:
                veri = None
                self._gyazo_son_durum = "hata" if _hata_turu(e) != "ic_adres" else "ic_adres"
            if not veri:
                self._gyazo_olumsuz_yaz(kimlik)
                return None
            dogru = self._gorsel_dogrula(veri)
            if not dogru:
                self._gyazo_olumsuz_yaz(kimlik)
                return None
            veri, uz = dogru
            # Yarım kalan .part dosyası hemen; süreç çökerse periyodik temizlikle silinir.
            hedef = self._atomik_yaz(self.gyazo_klasor, kimlik + uz, veri, "gyazo-")
            if not hedef:
                return None
            try:
                os.unlink(os.path.join(self.gyazo_klasor, kimlik + ".yok"))
            except OSError:
                pass
            return hedef
        finally:
            self._gyazo_semafor.release()

    # ------------------------------------------------- Dış görsel (Snappark / Teamzone), 2.3.2
    def dis_cozum(self, kayit):
        """Kayıttaki (ana veya ``_gorsel2``) bağlantı Snappark/Teamzone ise normalize çözüm; değilse None."""
        _, link = self._dosya_alani(kayit, bool(kayit.get("_gorsel2")))
        if not isinstance(link, str) or not link.strip():
            return None
        tur, _ = link_turu_ve_kimlik(link)
        if tur not in ("snappark", "teamzone"):
            return None
        return dis_gorsel_cozumle(link)

    def dis_onbellek(self, kayit_ya_da_cozum):
        coz = kayit_ya_da_cozum if "anahtar" in kayit_ya_da_cozum and "adaylar" in kayit_ya_da_cozum else self.dis_cozum(kayit_ya_da_cozum)
        return self._onbellekte(self.dis_klasor, coz["anahtar"]) if coz else None

    def dis_mumkun(self, kayit):
        """Dış görsel gösterilebilir mi? Dönüş: 'snappark' | 'teamzone' | None (kapalı, tanınmayan ya da 10 dk olumsuz işaretli)."""
        if not self.dis_acik:
            return None
        coz = self.dis_cozum(kayit)
        if not coz:
            return None
        if self._onbellekte(self.dis_klasor, coz["anahtar"]) or not self._olumsuz_mu(self.dis_klasor, coz["anahtar"]):
            return coz["tur"]
        return None

    def _dis_test_url(self, url):
        """DIS_GORSEL_TEST_HOST (yalnız loopback) verilmişse adayı ``http://<test>/<host><yol>`` adresine çevirir."""
        if not self.dis_test_host:
            return url
        parts = urlparse(url)
        return "http://%s/%s%s" % (self.dis_test_host, parts.hostname or "", parts.path or "/")

    def _dis_izinli(self, tur):
        hostlar = tuple(self.dis_hostlar.get(tur, ()))
        test_host = self.dis_test_host  # 2.3.2-inc: yalnız tam host:port (önceden portsuz 127.0.0.1 / localhost'un her portu)
        return lambda url: _guvenli_url(url, hostlar, test_host)

    def dis_indir(self, kayit, bekle=TOPLU_BEKLEME_SN):
        """Snappark/Teamzone görselini Gyazo ile aynı sınırlarla indirir ve ``tmp/dis/<sha1>.(jpg|png)`` olarak saklar.

        Teamzone için adaylar sırayla denenir (i.gyazo.com .png → .jpg → Teamzone adresi); yalnız image/* yanıt kabul edilir.
        Başarısızlık 10 dk olumsuz işaretlenir. ``_dis_son_durum``: son HTTP durumu ya da 'hata'/'gorsel_degil'/'bozuk'/...
        """
        if not self.dis_acik:
            return None
        coz = self.dis_cozum(kayit)
        if not coz:
            return None
        self._temizlik_gerekirse()
        anahtar = coz["anahtar"]
        yol = self._onbellekte(self.dis_klasor, anahtar)
        if yol:
            return yol
        if self._olumsuz_mu(self.dis_klasor, anahtar):
            return None
        if not self._dis_semafor.acquire(timeout=max(0, bekle)):
            return None
        try:
            yol = self._onbellekte(self.dis_klasor, anahtar)
            if yol:
                return yol
            izinli = self._dis_izinli(coz["tur"])
            veri = None
            durumlar = []
            for aday in coz["adaylar"]:
                son = {"d": None}

                def yaz(kod, son=son):
                    son["d"] = kod
                try:
                    veri = self._sinirli_getir(self._dis_test_url(aday), izinli, DIS_MAX_BYTES, yaz, sadece_gorsel=True)
                except Exception as e:
                    # 2.3.2-inc: bağlantı düzeyi ('erisim': DNS/ret/bağlantı zaman aşımı) ile bağlantıya özgü hata ('hata') ayrılır.
                    veri = None
                    son["d"] = _hata_turu(e)
                if veri:
                    dogru = self._gorsel_dogrula(veri)
                    if dogru:
                        veri = dogru
                        break
                    veri = None
                    son["d"] = "bozuk"
                durumlar.append(son["d"])
                if son["d"] in (429, "erisim"):
                    break  # hız sınırı / servise bağlanılamıyor: diğer adaylarla sunucuyu yüklemeyiz
            if not veri:
                # Raporlanacak durum: 429 > bağlantı kurulamadı > iç adres > (yalnız TÜM adaylar hata verdiyse) 'hata' >
                # ilk anlamlı HTTP durumu (ör. .png 404 iken son aday 'gorsel_degil').
                self._dis_son_durum = next((d for d in durumlar if d == 429), None) or next((d for d in durumlar if d == "erisim"), None) \
                    or next((d for d in durumlar if d == "ic_adres"), None) \
                    or ("hata" if durumlar and all(d == "hata" for d in durumlar) else None) \
                    or next((d for d in durumlar if d not in (None, 404, "hata")), None) or (durumlar[0] if durumlar else None)
                self._olumsuz_yaz(self.dis_klasor, anahtar)
                return None
            self._dis_son_durum = 200
            veri, uz = veri
            hedef = self._atomik_yaz(self.dis_klasor, anahtar + uz, veri, "dis-")
            if not hedef:
                return None
            try:
                os.unlink(os.path.join(self.dis_klasor, anahtar + ".yok"))
            except OSError:
                pass
            return hedef
        finally:
            self._dis_semafor.release()

    # --------------------------------------------------------------- Önbellek
    def _onbellek_dizinleri(self):
        # "dis": Snappark/Teamzone kopyaları; Gyazo kopyalarıyla aynı MB/gün sınırları (ayrı bütçe).
        return (("gyazo", self.gyazo_klasor, self.gyazo_sinir_bayt, self.gyazo_yas_sn),
                ("dis", self.dis_klasor, self.gyazo_sinir_bayt, self.gyazo_yas_sn),
                ("thumbs", self.thumbs, self.kucuk_sinir_bayt, 0))

    def _temizlik_gerekirse(self):
        """Ucuz denetim: gerçek tarama en fazla 10 dakikada bir (ve süreç başında bir kez)."""
        if time.time() - self._temizlik_zaman >= ONBELLEK_TEMIZLIK_ARALIGI_SN:
            self.onbellek_temizle()

    def onbellek_temizle(self, zorla=False):
        """Gyazo ve küçük resim önbelleklerini boyut/yaş sınırlarının altına çeker.

        Dönüş: ``{"gyazo": rapor, "dis": rapor, "thumbs": rapor}`` ya da ``None`` (süre dolmadı
        veya başka bir iş parçacığı temizliyor; ``zorla=True`` bekler ve çalışır).
        Hiçbir istisna dışarı sızmaz. Yalnız önbellek kökü altındaki üç klasöre (gyazo, dis, thumbs),
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

    def gorsel_yolu(self, kayit, bekle=TOPLU_BEKLEME_SN, arka_plan=False):
        """Ana (veya ``_gorsel2``) görselin yolu ve kaynağı: yerel, gyazo, snappark, teamzone, hazirlaniyor veya yok.

        ``bekle``: indirme yuvası için en çok bekleme (sn). ``arka_plan=True`` (liste/galeri küçük resmi): önbellekte yoksa
        istek BEKLEMEZ; indirme arka planda başlatılır (yuva doluysa başlatılmaz) ve ``(None, "hazirlaniyor")`` döner.
        """
        yol, kaynak = self.yerel_dosya(kayit)
        if yol:
            return yol, kaynak
        if arka_plan:
            kimlik = self.gyazo_kimlik(kayit) if self.gyazo_acik else None
            yol = self._gyazo_onbellek(kimlik) if kimlik else None
            if yol:
                return yol, "gyazo"
            coz = self.dis_cozum(kayit) if self.dis_acik else None
            yol = self._onbellekte(self.dis_klasor, coz["anahtar"]) if coz else None
            if yol:
                return yol, coz["tur"]
            if self.gyazo_mumkun(kayit) or self.dis_mumkun(kayit):
                self.arka_planda_indir(kayit)
                return None, "hazirlaniyor"
            return None, "yok"
        yol = self.gyazo_indir(kayit, bekle=bekle)
        if yol:
            return yol, "gyazo"
        coz = self.dis_cozum(kayit)
        if coz:
            yol = self.dis_indir(kayit, bekle=bekle)
            if yol:
                return yol, coz["tur"]
        return None, "yok"

    def arka_planda_indir(self, kayit):
        """Dış/Gyazo görselini arka plan iş parçacığında indirir (en çok ARKA_PLAN_ESZAMANLI). Başlatıldıysa ya da zaten
        sürüyorsa True; yuva doluysa False (istek yine hemen yer tutucu alır, sonraki açılışta yeniden denenir)."""
        kimlik = self.gyazo_kimlik(kayit) if self.gyazo_acik else None
        coz = None if kimlik else self.dis_cozum(kayit)
        anahtar = ("g:" + kimlik) if kimlik else (("d:" + coz["anahtar"]) if coz else None)
        if not anahtar:
            return False
        with self._arka_kilit:
            if anahtar in self._arka_aktif:
                return True
            if not self._arka_semafor.acquire(blocking=False):
                return False
            self._arka_aktif.add(anahtar)
        kopya = dict(kayit)

        def is_():
            try:
                self.gorsel_yolu(kopya, bekle=GORSEL_ISTEK_BEKLEME_SN)
            except Exception:  # arka plan işi hiçbir isteği düşürmez
                pass
            finally:
                with self._arka_kilit:
                    self._arka_aktif.discard(anahtar)
                self._arka_semafor.release()
        try:
            threading.Thread(target=is_, name="kanit-gorsel-arka", daemon=True).start()
        except Exception:
            with self._arka_kilit:
                self._arka_aktif.discard(anahtar)
            self._arka_semafor.release()
            return False
        return True

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
        if not _guvenli_altinda(yol, list(self.kokler) + [self.gyazo_klasor, self.dis_klasor]):
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
                503: "Gyazo yanıt vermiyor (HTTP 503: Gyazo arızası ya da silinmiş görsel; sonraki çalıştırmada yeniden denenir)",
                429: "Gyazo hız sınırı (429)", "hata": "ağ hatası / zaman aşımı",
                "erisim": "bağlantı kurulamadı (DNS / bağlantı reddi / zaman aşımı)", "ic_adres": "iç ağ adresine çözülüyor (güvenlik nedeniyle indirilmedi)",
                "izinsiz": "izin verilmeyen adrese yönlendirme (güvenlik nedeniyle izlenmedi)", "zaman_asimi": "indirme 30 sn'de bitmedi"}
GYAZO_TOPLU_429_BEKLEME = (30, 60, 120, 300)
GYAZO_ARIZA_ESIGI = 10  # art arda bu kadar 5xx: servis arızalı sayılır, kalan bağlantılar yeniden denenmeden/beklenmeden geçilir


_SERVIS_EKI = {"Gyazo": "'da", "Snappark": "'ta", "Teamzone": "'da"}
_DIS_SEBEP = {"gorsel_degil": "görsel değil (giriş sayfası ya da oturum gerekiyor olabilir)",
              "bozuk": "indirilen dosya bozuk ya da görsel değil", "buyuk": "görsel çok büyük (20 MB sınırı)",
              "yonlendirme": "çok fazla yönlendirme", "erisim": "bağlantı kurulamadı (DNS / bağlantı reddi / zaman aşımı)",
              "ic_adres": "iç ağ adresine çözülüyor (güvenlik nedeniyle indirilmedi)",
              "izinsiz": "izin verilmeyen adrese yönlendirme (güvenlik nedeniyle izlenmedi)", "zaman_asimi": "indirme 30 sn'de bitmedi"}


def _gyazo_sebep(durum, servis="Gyazo"):
    if servis == "Gyazo" and durum in _GYAZO_SEBEP:
        return _GYAZO_SEBEP[durum]
    if servis != "Gyazo":
        ek = _SERVIS_EKI.get(servis, "'da")
        sablon = {404: f"{servis}{ek} görsel yok (404)", 410: f"{servis} görseli kaldırmış (410)", 403: f"{servis} erişimi reddetti (403)",
                  401: f"{servis} oturum istiyor (401)", 429: f"{servis} hız sınırı (429)", "hata": "ağ hatası / zaman aşımı"}
        if durum in sablon:
            return sablon[durum]
        if durum in _DIS_SEBEP:
            return _DIS_SEBEP[durum]
    if isinstance(durum, int):
        return f"sunucu hatası (HTTP {durum})" if durum >= 500 else ("indirilemedi (bozuk, çok büyük ya da görsel olmayan içerik)" if durum == 200 else f"HTTP {durum}")
    return "indirilemedi (izinsiz bağlantı ya da meşgul)"


def gyazo_toplu_indir(conn, cozucu, ayar=None, *, en_cok=0, yeni_en_cok=0, bitis=None, bekleme_sn=0.15, uyku=None,
                      rapor_yolu=None, ilerleme=None, log=None, on_kontrol=False, simdi=None):
    """Kayıtlardaki tüm Gyazo, Snappark ve Teamzone bağlantılarını (ana ve ikinci görsel) sunucu önbelleğine bir kez indirir.

    2.3.2: raporda ``turler`` = {gyazo|snappark|teamzone: {baglanti, indirilen, zaten_var, acilamayan, taninmayan}}.
    Ön kontrol (on_kontrol) yalnız Gyazo içindir; bir dış servisin ilk denemesi ağ hatasıyla (iki kez) biterse
    o servisin kalan bağlantıları bu çalıştırmada istek atılmadan "ulaşılamıyor" diye raporlanır.

    yeni_en_cok: bu çalıştırmada en çok bu kadar YENİ indirme denenir (gece planı; kalanı sonraki çalıştırmaya).
    bitis: bu zamana (datetime) gelince durur. log(metin): isteğe bağlı ayrıntılı satır çıktısı.
    on_kontrol: başta Gyazo'ya tek bir deneme isteği atar; ulaşılamıyorsa hiçbir bağlantı denenmeden döner.
    Dönüşteki bitis_nedeni: tamam | sinir | sure | hiz_siniri | erisim.

    Amaç: eski Excel kayıtlarının tek kopyası Gyazo'da; bağlantı ölmeden sunucuya kopyalamak ve
    açılamayanları raporlamak. Yeniden çalıştırılabilir: önbellekte olan kimlikler atlanır, her kimlik
    bu çalıştırmada bir kez daha denenir (10 dakikalık olumsuz işaret yok sayılır). Hız sınırında (429)
    30/60/120/300 s bekler; yine 429 ise durur ve sonraki çalıştırma kaldığı yerden sürer.
    Kayıt satırları hiçbir zaman değiştirilmez; yalnız önbellek dosyaları ve rapor dosyası yazılır.
    """
    gyazo_acik = bool(getattr(cozucu, "gyazo_acik", False))
    if not gyazo_acik and not getattr(cozucu, "dis_acik", False):
        raise ValueError("GYAZO_PROXY ve DIS_GORSEL_PROXY kapalı; önce .env içinde GYAZO_PROXY=1 (ya da DIS_GORSEL_PROXY=1) yapın.")
    uyku = uyku or time.sleep
    log = log or (lambda metin: None)
    simdi = simdi or (lambda: datetime.now(getattr(bitis, "tzinfo", None)))
    t0 = time.monotonic()
    sayac = {"baglanti": 0, "kimlik": 0, "zaten_var": 0, "indirilen": 0, "acilamayan": 0, "kimliksiz": 0,
             "hiz_siniri_bekleme_sn": 0, "durduruldu": None, "bitis_nedeni": "tamam", "denenen": 0, "kalan": 0}
    turler = {t: {"baglanti": 0, "indirilen": 0, "zaten_var": 0, "acilamayan": 0, "taninmayan": 0} for t in ("gyazo", "snappark", "teamzone")}
    acilamayan = []
    gorulen = {}
    if on_kontrol and gyazo_acik:
        try:
            r = cozucu._gyazo_http().get(cozucu.gyazo_kaynak.format(id="0" * 32), stream=True, timeout=(5, 10), allow_redirects=False,
                                         headers={"User-Agent": "KanitPaneli/2.3", "Accept": "image/*"})
            try:
                durum_kodu = getattr(r, "status_code", None)
            finally:
                try:
                    r.close()
                except Exception:
                    pass
            log("Gyazo erişimi: ulaşıldı (deneme isteği HTTP %s; var olmayan kimlik için 503/404 normaldir)" % durum_kodu)
        except Exception as hata:
            sayac["bitis_nedeni"] = "erisim"
            sayac["durduruldu"] = ("Gyazo'ya ulaşılamıyor (%s: %s). Sunucunun dış HTTPS erişimini kontrol edin: "
                                   "curl -sS -o /dev/null -w '%%{http_code}\\n' --max-time 20 https://i.gyazo.com/" % (type(hata).__name__, str(hata)[:160]))
            log(sayac["durduruldu"])
            sonuc = dict(sayac)
            sonuc.update({"sure_sn": round(time.monotonic() - t0, 1), "rapor": None, "acilamayan_ornek": [], "turler": turler})
            return sonuc
    cur = conn.execute("SELECT id, proje, personel, link, gorsel_dosya, gorsel2, gorsel2_dosya FROM kayitlar "
                       "WHERE COALESCE(silindi,0)=0 AND (LOWER(COALESCE(link,'')) LIKE '%gyazo.com/%' "
                       "OR LOWER(COALESCE(gorsel2,'')) LIKE '%gyazo.com/%' OR LOWER(COALESCE(link,'')) LIKE '%snappark%' "
                       "OR LOWER(COALESCE(gorsel2,'')) LIKE '%snappark%') ORDER BY id")
    sutunlar = [d[0] for d in cur.description]
    dis_acik = bool(getattr(cozucu, "dis_acik", False))
    adaylar = []
    for satir in cur.fetchall():
        r = dict(zip(sutunlar, satir))
        for ikinci in (False, True):
            link = (r.get("gorsel2") if ikinci else r.get("link")) or ""
            dusuk = str(link).lower()
            k = dict(r)
            k["_gorsel2"] = ikinci
            if "gyazo.com/" in dusuk and "teamzone" not in dusuk:  # teamzone.gyazo.com ayrı bir hizmet, Gyazo kimliği taşımaz
                if not gyazo_acik:  # GYAZO_PROXY=0: Gyazo bağlantıları bu çalıştırmada denenmez, dış servisler yine kopyalanır
                    turler["gyazo"]["taninmayan"] += 1
                    continue
                adaylar.append((r, link, k, "gyazo", None))
                continue
            if "snappark" not in dusuk and "teamzone.gyazo" not in dusuk:
                continue
            tur = link_turu_ve_kimlik(link)[0]
            if tur not in ("snappark", "teamzone"):
                continue
            coz = dis_gorsel_cozumle(link)
            if not coz or not dis_acik:  # tanınmayan biçim (ör. /s/<id> yok) ya da DIS_GORSEL_PROXY=0: hiç denenmez
                turler[tur]["taninmayan"] += 1
                continue
            adaylar.append((r, link, k, coz["tur"], coz))
    if en_cok and en_cok > 0:
        adaylar = adaylar[:en_cok]
    sayac["baglanti"] = len(adaylar)
    for a in adaylar:
        turler[a[3]]["baglanti"] += 1

    def _yok_sil(kimlik, tur="gyazo"):
        klasor, ad = (cozucu.gyazo_klasor, kimlik) if tur == "gyazo" else (cozucu.dis_klasor, kimlik.split(":", 1)[-1])
        try:
            os.unlink(os.path.join(klasor, ad + ".yok"))
        except OSError:
            pass

    def _dene(k, tur="gyazo"):
        if tur == "gyazo":
            cozucu._gyazo_son_durum = None
            yol = cozucu.gyazo_indir(k)
            return yol, cozucu._gyazo_son_durum
        cozucu._dis_son_durum = None
        yol = cozucu.dis_indir(k)
        return yol, cozucu._dis_son_durum

    toplam = len(adaylar)
    ariza_sayac = {}  # servis -> art arda 5xx sayısı; GYAZO_ARIZA_ESIGI aşılınca o servis için hızlı geçiş (yeniden deneme/bekleme yok)
    log("%d bağlantı taranıyor (Gyazo %d, Snappark %d, Teamzone %d)%s" % (
        toplam, turler["gyazo"]["baglanti"], turler["snappark"]["baglanti"], turler["teamzone"]["baglanti"],
        "; bu çalıştırmada en çok %d yeni indirme" % yeni_en_cok if yeni_en_cok else ""))
    islenen = 0
    erisim_yok = set()   # art arda ERISIM_ATLAMA_ESIGI farklı bağlantıda bağlantı kuramayan dış servisler (bu çalıştırmada atlanır)
    hiz_siniri = set()   # 429'u sürdüğü için bu çalıştırmada durdurulan dış servisler (Gyazo ve diğer servisler sürer)
    ardisik = {}         # tür -> art arda 'erisim' veren farklı bağlantı sayısı (başka her sonuçta sıfırlanır)
    basarili = set()     # bu çalıştırmada en az bir indirmesi başarılı olan servisler
    for i, (r, link, k, tur, coz) in enumerate(adaylar, 1):
        servis = DIS_GORSEL_ADLARI[tur]
        t = turler[tur]
        if tur == "gyazo":
            kimlik = cozucu.gyazo_kimlik(k)
            onbellekte = bool(kimlik) and kimlik not in gorulen and bool(cozucu._gyazo_onbellek(kimlik))
        else:
            kimlik = tur + ":" + coz["anahtar"]
            onbellekte = kimlik not in gorulen and bool(cozucu.dis_onbellek(coz))
            if not onbellekte and kimlik not in gorulen and (tur in erisim_yok or tur in hiz_siniri):
                islenen = i
                gorulen[kimlik] = False
                sayac["kimlik"] += 1
                sayac["acilamayan"] += 1
                t["acilamayan"] += 1
                sebep = ("%s'a ulaşılamıyor (art arda %d bağlantı kurulamadı; bu çalıştırmada denenmedi)" % (servis, ERISIM_ATLAMA_ESIGI)
                         if tur in erisim_yok else "%s hız sınırı sürüyor (bu çalıştırmada denenmedi)" % servis)
                acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, sebep))
                if ilerleme and (i % 100 == 0 or i == toplam):
                    ilerleme(i, toplam, dict(sayac))
                continue
        yeni_gerek = bool(kimlik) and kimlik not in gorulen and not onbellekte
        if yeni_gerek and yeni_en_cok and sayac["denenen"] >= yeni_en_cok:
            sayac["bitis_nedeni"] = "sinir"
            log("Bu çalıştırmanın yeni indirme sınırı (%d) doldu; kalan bağlantılar sonraki çalıştırmada." % yeni_en_cok)
            break
        if yeni_gerek and bitis is not None and simdi() >= bitis:
            sayac["bitis_nedeni"] = "sure"
            log("Bitiş saatine gelindi (%s); kalan bağlantılar sonraki çalıştırmada." % bitis.strftime("%H:%M"))
            break
        islenen = i
        if not kimlik:
            sayac["kimliksiz"] += 1
            acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, "Gyazo kimliği okunamadı"))
        elif kimlik in gorulen:
            if gorulen[kimlik]:
                sayac["zaten_var"] += 1
                t["zaten_var"] += 1
            else:
                sayac["acilamayan"] += 1
                t["acilamayan"] += 1
                acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, "aynı bağlantı bu çalıştırmada açılamadı"))
        elif onbellekte:
            sayac["kimlik"] += 1
            gorulen[kimlik] = True
            sayac["zaten_var"] += 1
            t["zaten_var"] += 1
        else:
            etiket = kimlik[:8] if tur == "gyazo" else "%s %s" % (servis, coz["anahtar"][:8])
            sayac["kimlik"] += 1
            sayac["denenen"] += 1
            _yok_sil(kimlik, tur)
            yol, durum = _dene(k, tur)
            ariza_modu = ariza_sayac.get(servis, 0) >= GYAZO_ARIZA_ESIGI
            if not yol and not ariza_modu and (durum in ("hata", "erisim") or (isinstance(durum, int) and durum >= 500)):
                log("%d/%d %s… geçici hata (%s); 1 sn sonra bir kez daha" % (i, toplam, etiket, _gyazo_sebep(durum, servis)))
                uyku(1)
                _yok_sil(kimlik, tur)
                yol, durum = _dene(k, tur)
            if yol:
                ariza_sayac[servis] = 0
            elif isinstance(durum, int) and durum >= 500:
                ariza_sayac[servis] = ariza_sayac.get(servis, 0) + 1
                if ariza_sayac[servis] == GYAZO_ARIZA_ESIGI:
                    log("%s art arda %d bağlantıda sunucu hatası (HTTP %s) verdi; muhtemelen %s arızası. Kalan bağlantılar beklemeden geçilir, sonraki çalıştırmada yeniden denenir."
                        % (servis, GYAZO_ARIZA_ESIGI, durum, servis))
                    sayac.setdefault("ariza", []).append(servis)
            for bekle in GYAZO_TOPLU_429_BEKLEME:
                if yol or durum != 429:
                    break
                if bitis is not None and simdi() + timedelta(seconds=bekle) >= bitis:
                    break  # bekleme gece penceresini aşardı: aşağıda 429 olarak raporlanır
                sayac["hiz_siniri_bekleme_sn"] += bekle
                log("%d/%d %s hız sınırı (429); %d sn bekleniyor…" % (i, toplam, servis, bekle))
                uyku(bekle)
                _yok_sil(kimlik, tur)
                yol, durum = _dene(k, tur)
            if tur != "gyazo":
                ardisik[tur] = ardisik.get(tur, 0) + 1 if (not yol and durum == "erisim") else 0
            if yol:
                gorulen[kimlik] = True
                basarili.add(tur)
                sayac["indirilen"] += 1
                t["indirilen"] += 1
                try:
                    boyut_kb = os.path.getsize(yol) // 1024
                except OSError:
                    boyut_kb = 0
                log("%d/%d %s… indirildi (%d KB)" % (i, toplam, etiket, boyut_kb))
            else:
                gorulen[kimlik] = False
                sayac["acilamayan"] += 1
                t["acilamayan"] += 1
                acilamayan.append((r["id"], r["proje"], r.get("personel") or "", link, _gyazo_sebep(durum, servis)))
                log("%d/%d %s… açılamadı: %s" % (i, toplam, etiket, _gyazo_sebep(durum, servis)))
                if tur != "gyazo" and ardisik.get(tur, 0) >= ERISIM_ATLAMA_ESIGI:
                    # 2.3.2-inc: yalnız bağlantı düzeyi hatalar (DNS, bağlantı reddi/zaman aşımı) art arda 3 farklı bağlantıda
                    # görülünce servis atlanır; HTTP 4xx/5xx, yönlendirme ve gövde hataları yalnız o bağlantıyı açılamayan sayar.
                    erisim_yok.add(tur)
                    log("%s'a art arda %d bağlantıda ulaşılamadı; kalan %s bağlantıları bu çalıştırmada denenmeyecek. "
                        "Sunucunun dış HTTPS erişimini kontrol edin: curl -sS -o /dev/null -w '%%{http_code}\\n' --max-time 20 %s"
                        % (servis, ERISIM_ATLAMA_ESIGI, servis, coz["adaylar"][0]))
                if durum == 429 and tur != "gyazo":
                    hiz_siniri.add(tur)
                    log("%s hız sınırı (429) sürüyor; kalan %s bağlantıları bu çalıştırmada denenmeyecek, diğer servisler sürüyor."
                        % (servis, servis))
                elif durum == 429:
                    sayac["bitis_nedeni"] = "hiz_siniri"
                    sayac["durduruldu"] = ("%s hız sınırı sürüyor; %d/%d bağlantı işlendi. 15 dakika sonra aynı komutu yeniden çalıştırın "
                                           "(kaldığı yerden devam eder)." % (servis, i, toplam))
            if bekleme_sn and i < toplam and not sayac["durduruldu"] and ariza_sayac.get(servis, 0) < GYAZO_ARIZA_ESIGI:
                uyku(bekleme_sn)
        if ilerleme and (i % 100 == 0 or i == toplam):
            ilerleme(i, toplam, dict(sayac))
        if sayac["durduruldu"]:
            break
    sayac["kalan"] = max(0, toplam - islenen)

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
    sonuc.update({"sure_sn": round(time.monotonic() - t0, 1), "rapor": rapor_yolu, "acilamayan_ornek": acilamayan[:20], "turler": turler})
    if erisim_yok:
        sonuc["dis_erisim_yok"] = sorted(DIS_GORSEL_ADLARI[t] for t in erisim_yok)
    if hiz_siniri:
        sonuc["dis_hiz_siniri"] = sorted(DIS_GORSEL_ADLARI[t] for t in hiz_siniri)
    try:
        durum = cozucu.onbellek_durumu()
        for ad, etiket in (("gyazo", "Gyazo"), ("dis", "Dış görsel (Snappark/Teamzone)")):
            g = durum.get(ad) if isinstance(durum, dict) else None
            if not isinstance(g, dict):
                continue
            sonuc["onbellek_%s_mb" % ad] = g.get("mb")
            if ad == "gyazo":
                sonuc["onbellek_sinir_mb"] = g.get("sinir_mb")
            if g.get("sinir_mb") and g.get("mb") and g["mb"] > 0.8 * g["sinir_mb"] and "uyari" not in sonuc:
                sonuc["uyari"] = ("%s önbelleği sınırına yaklaştı (%s / %s MB); sınır dolunca en eski kopyalar silinir. "
                                  ".env içinde GYAZO_ONBELLEK_MB değerini yükseltin (örn. 5000; Gyazo ve dış görsel kopyalarına ayrı ayrı "
                                  "uygulanır) ve kanit-web'i yeniden başlatın." % (etiket, g["mb"], g["sinir_mb"]))
    except Exception:
        pass
    return sonuc


def gyazo_pencere(pencere, dilim="Europe/Istanbul", simdi=None):
    """'22:30-07:30' biçimindeki saat penceresini çözer.

    Dönüş: (icinde, bitis, aciklama). Gece yarısını aşan pencere desteklenir. Saat dilimi bulunamazsa
    sunucunun yerel saati kullanılır (aciklama bunu söyler). Geçersiz biçimde ValueError.
    """
    import re as _re
    m = _re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", str(pencere or ""))
    if not m:
        raise ValueError("Pencere biçimi SS:DD-SS:DD olmalı, örn. 22:30-07:30")
    bs, bd, es, ed = (int(x) for x in m.groups())
    if not (0 <= bs < 24 and 0 <= bd < 60 and 0 <= es < 24 and 0 <= ed < 60):
        raise ValueError("Pencere saatleri 00:00-23:59 arasında olmalı")
    tz = None
    not_ = ""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(dilim)
    except Exception:
        not_ = " (saat dilimi bulunamadı, sunucu yerel saati kullanıldı)"
    now = simdi() if simdi else datetime.now(tz)
    if tz is not None and now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    bugun_bas = now.replace(hour=bs, minute=bd, second=0, microsecond=0)
    bugun_bit = now.replace(hour=es, minute=ed, second=0, microsecond=0)
    if bugun_bit <= bugun_bas:  # gece yarısını aşan pencere
        if now >= bugun_bas:
            return True, bugun_bit + timedelta(days=1), "pencere %s-%s içinde%s" % (m.group(1).zfill(2) + ":" + m.group(2), m.group(3).zfill(2) + ":" + m.group(4), not_)
        if now < bugun_bit:
            return True, bugun_bit, "pencere içinde (gece yarısından sonra)%s" % not_
        return False, bugun_bas, "pencere dışı; sonraki başlangıç %s%s" % (bugun_bas.strftime("%H:%M"), not_)
    if bugun_bas <= now < bugun_bit:
        return True, bugun_bit, "pencere içinde%s" % not_
    sonraki = bugun_bas if now < bugun_bas else bugun_bas + timedelta(days=1)
    return False, sonraki, "pencere dışı; sonraki başlangıç %s%s" % (sonraki.strftime("%d.%m %H:%M"), not_)
