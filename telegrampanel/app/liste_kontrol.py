# -*- coding: utf-8 -*-
"""Liste kontrolu: yuklenen dosyadaki (xlsx / csv / txt ya da yapistirilan liste) degerler panel kayitlarinda var mi?

Adimlar arasinda dosyanin cozulmus satirlari ONBELLEK\\liste_<token>.json icinde tutulur (sahibi kullanici adi;
24 saatten eski dosyalar her kullanimda silinir). Excel'e ve bot klasorune hicbir sey yazilmaz.
"""
import os, io, re, csv, json, time, secrets
from . import excel_oku

ALANLAR = [("personel", "Personel kodu"), ("uye_id", "Uye ID"), ("ana_uye_id", "Ana uye ID"), ("link", "Link"),
           ("kategori", "Kategori"), ("ekleyen_ad", "Ekleyen"), ("aciklama", "Aciklama")]
ALAN_ADLARI = dict(ALANLAR)
MAKS_SATIR, MAKS_SUTUN, ONIZLEME = 20000, 50, 5
AYIRICILAR = [",", ";", "\t", "|"]
_BOSLUK = re.compile(r"\s+")
_URL = re.compile(r"^(?:https?://)?(?:www\.)?", re.I)
# baslik adi -> panel alani tahmini (sira onemli: "ana uye id" once ana_uye_id'ye gider)
_TAHMIN = [("ana_uye_id", ("ana",)), ("personel", ("personel", "kod", "staff")), ("uye_id", ("uye", "\u00fcye", "id", "member")),
           ("link", ("link", "url", "gyazo", "kanit", "kan\u0131t")), ("kategori", ("kategori", "kat")), ("ekleyen_ad", ("ekleyen",)),
           ("aciklama", ("aciklama", "a\u00e7\u0131klama", "not"))]


# ==================== normallestirme ====================
def normalle(v):
    """Karsilastirma anahtari: metin, kirp, kucuk harf, ic bosluklar tek bosluk; yalniz rakamsa bastaki sifirlar atilir;
    link ise http(s)://, www., sondaki / ve sorgu kismi atilir."""
    s = _BOSLUK.sub(" ", excel_oku._metin(v)).strip().casefold()
    if not s:
        return ""
    if s.isdigit():
        return s.lstrip("0") or "0"
    if s.startswith(("http://", "https://", "www.")):
        s = _URL.sub("", s).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return s


# ==================== dosya cozme ====================
def _metin_satirlari(metin):
    """csv/txt/yapistirilan metin -> satir listesi. Ayirici , ; sekme | arasindan tahmin edilir; bulunamazsa tek sutun."""
    satirlar_ham = [s for s in metin.splitlines() if s.strip()][:40]
    ayirici = None
    en_iyi = (0, 0)
    for a in AYIRICILAR:
        sayilar = [s.count(a) for s in satirlar_ham]
        if sayilar and min(sayilar) > 0:
            puan = (len(set(sayilar)) == 1, sum(sayilar))
            if puan > en_iyi:
                en_iyi, ayirici = puan, a
    if ayirici is None:
        return [[s.strip()] for s in metin.splitlines()]
    return [[h.strip() for h in r] for r in csv.reader(io.StringIO(metin), delimiter=ayirici)]


def _kirp(satirlar):
    """Sondaki bos sutun/satirlari at, sinirlari denetle, her satiri ayni genislige getir."""
    genislik = 0
    for r in satirlar:
        dolu = [i for i, h in enumerate(r) if h != ""]
        if dolu:
            genislik = max(genislik, dolu[-1] + 1)
    while satirlar and all(h == "" for h in satirlar[-1]):
        satirlar.pop()
    if len(satirlar) > MAKS_SATIR:
        raise ValueError(f"Dosya cok buyuk: en fazla {MAKS_SATIR} satir olabilir ({len(satirlar)} satir var).")
    if genislik > MAKS_SUTUN:
        raise ValueError(f"Dosyada cok fazla sutun var: en fazla {MAKS_SUTUN} ({genislik} sutun var).")
    return [(r + [""] * genislik)[:genislik] for r in satirlar]


def coz(dosya_adi, veri):
    """Yuklenen dosya (bytes) -> {"tablolar": {sayfa: satirlar}, "sayfalar": [sayfa adlari]}"""
    uz = os.path.splitext(dosya_adi or "")[1].lower()
    if uz == ".xlsx" or veri[:2] == b"PK":
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(veri), read_only=True, data_only=True)
        except Exception as e:
            raise ValueError(f"Excel dosyasi okunamadi: {e}")
        tablolar = {}
        try:
            for ws in wb.worksheets:
                satirlar = []
                for r in ws.iter_rows(values_only=True):
                    if len(satirlar) >= MAKS_SATIR:
                        raise ValueError(f"Dosya cok buyuk: en fazla {MAKS_SATIR} satir olabilir ('{ws.title}' sayfasi daha uzun).")
                    satirlar.append([excel_oku._metin(h) for h in r[:MAKS_SUTUN + 1]])
                tablolar[ws.title] = _kirp(satirlar)
        finally:
            wb.close()
    elif uz in (".csv", ".txt", ""):
        try:
            metin = veri.decode("utf-8-sig")
        except UnicodeDecodeError:
            metin = veri.decode("cp1254", errors="replace")
        tablolar = {"": _kirp(_metin_satirlari(metin))}
    else:
        raise ValueError("Yalnizca .xlsx, .csv ve .txt dosyalari yuklenebilir.")
    tablolar = {ad: t for ad, t in tablolar.items() if t} or {"": []}
    if not any(tablolar.values()):
        raise ValueError("Dosyada veri bulunamadi.")
    return {"tablolar": tablolar, "sayfalar": list(tablolar)}


def metin_coz(metin):
    """Yapistirilan liste -> coz() ile ayni yapi."""
    return coz("liste.txt", metin.encode("utf-8"))


# ==================== baslik ve eslesme tahmini ====================
def _tur(h):
    s = (h or "").strip().casefold()
    return "b" if not s else "s" if s.isdigit() else "u" if s.startswith(("http://", "https://", "www.")) else "m"


def baslik_mi(satirlar):
    """Ilk satir baslik mi? Icinde rakam olmayan metin var ve deseni (metin/sayi/link) altindaki satirlardan farkli."""
    if len(satirlar) < 2:
        return False
    ilk = [_tur(h) for h in satirlar[0]]
    if "m" not in ilk:
        return False
    for r in satirlar[1:21]:
        if [_tur(h) for h in r] != ilk and any(h for h in r):
            return True
    return False


def tahmin(basliklar):
    """Baslik adlarindan panel alani tahmini: [[alan, ...], ...] (sutun basina)."""
    sonuc = []
    for b in basliklar:
        s = (b or "").strip().casefold()
        alanlar = []
        for alan, anahtarlar in _TAHMIN:
            if s and any(a in s for a in anahtarlar):
                alanlar = [alan]
                break
        sonuc.append(alanlar)
    if basliklar and not any(sonuc):   # basliksiz / tek sutunlu liste: ilk sutun, uye ID ya da personel kodu
        sonuc[0] = ["uye_id", "personel"]
    return sonuc


def sutunlar(satirlar, baslik):
    """Esleme tablosu icin sutun bilgisi: ad, ornek deger, tahmin edilen alanlar, ontanimli isaret."""
    genislik = len(satirlar[0]) if satirlar else 0
    basliklar = [str(h) for h in satirlar[0]] if (baslik and satirlar) else [""] * genislik
    veri = satirlar[1:] if baslik else satirlar
    tahminler = tahmin(basliklar)
    s = []
    for i in range(genislik):
        ornek = next((r[i] for r in veri[:50] if r[i]), "")
        # kimlik sutunlari (personel / uye / ana uye / link) ontanimli isaretli; kategori, ekleyen, aciklama yalnizca onerilir
        secili = bool(tahminler[i]) and tahminler[i][0] in ("personel", "uye_id", "ana_uye_id", "link")
        s.append({"no": i, "ad": basliklar[i] or f"Sutun {i + 1}", "ornek": ornek, "alanlar": tahminler[i], "secili": secili})
    return s


# ==================== eslestirme ====================
def eslestir(satirlar, baslik, esleme, kayitlar):
    """satirlar: dosya satirlari; esleme: [{"sutun": i, "alanlar": [...]}]; kayitlar: sozluk listesi.
    Bir sutundaki alanlar VEYA ile (deger herhangi birinde), isaretli sutunlar VE ile birlesir; bos hucre atlanir.
    -> {"satirlar": [{"no", "degerler", "eslesen": [kayit indeksleri]}], "bulunan", "yok", "coklu", "bos"}"""
    indeks = {}
    for alan in {a for e in esleme for a in e["alanlar"]}:
        d = indeks[alan] = {}
        for i, k in enumerate(kayitlar):
            n = normalle(k.get(alan))
            if n:
                d.setdefault(n, []).append(i)
    sonuc = {"satirlar": [], "bulunan": 0, "yok": 0, "coklu": 0, "bos": 0}
    for no, r in enumerate(satirlar, 1):
        if baslik and no == 1:
            continue
        degerler = [r[e["sutun"]] if e["sutun"] < len(r) else "" for e in esleme]
        adaylar = None
        for e, v in zip(esleme, degerler):
            n = normalle(v)
            if not n:
                continue
            bulunan = set()
            for alan in e["alanlar"]:
                bulunan.update(indeks[alan].get(n, ()))
            adaylar = bulunan if adaylar is None else adaylar & bulunan
            if not adaylar:
                break
        if adaylar is None:
            sonuc["bos"] += 1
            continue
        eslesen = sorted(adaylar)
        sonuc["satirlar"].append({"no": no, "degerler": degerler, "eslesen": eslesen})
        if eslesen:
            sonuc["bulunan"] += 1
            if len(eslesen) > 1:
                sonuc["coklu"] += 1
        else:
            sonuc["yok"] += 1
    return sonuc


# ==================== adimlar arasi saklama ====================
def _yol(onbellek, token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,48}", token or ""):
        return None
    return os.path.join(onbellek, f"liste_{token}.json")


def temizle(onbellek, yas_sn=24 * 3600):
    try:
        for ad in os.listdir(onbellek):
            y = os.path.join(onbellek, ad)
            if ad.startswith("liste_") and ad.endswith(".json") and time.time() - os.path.getmtime(y) > yas_sn:
                os.remove(y)
    except OSError:
        pass


def kaydet(onbellek, veri, token=None):
    """-> token. veri icinde 'sahip' (kullanici adi) bulunmali."""
    os.makedirs(onbellek, exist_ok=True)
    temizle(onbellek)
    token = token or secrets.token_urlsafe(16)
    veri["zaman"] = time.time()
    with open(_yol(onbellek, token), "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False)
    return token


def yukle(onbellek, token, kullanici):
    """Token dosyasini oku; yoksa ya da baska kullanicininsa None."""
    temizle(onbellek)
    y = _yol(onbellek, token)
    if not y or not os.path.isfile(y):
        return None
    try:
        with open(y, encoding="utf-8") as f:
            veri = json.load(f)
    except (OSError, ValueError):
        return None
    return veri if veri.get("sahip") == kullanici else None
