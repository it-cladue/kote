# -*- coding: utf-8 -*-
"""Eski Excel çalışma kitabını salt-okunur ve tek seferlik aktarım için okur.

Çalışma kitabı XML'i satır satır taranır. Bu özellikle OF sayfasında yalnızca H
sütununda bir milyon ``FALSE`` hücresi bulunduğunda openpyxl'in tüm dikdörtgeni
oluşturmasını önler. A..G'de veri olmayan satırlar kayıt değildir; aradaki boş
satırlar hiçbir zaman taramayı durdurmaz.
"""
import hashlib
import os
import posixpath
import re
import shutil
import time
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET

import openpyxl

VARSAYILAN_HARITA = {
    "personel": "A", "uye": "B", "ana": "C", "tip": "D", "link": "E",
    "kategori": "F", "tarih": "G", "kt": "H", "gorsel2": "I", "aciklama": "J",
}
# Elle açılmış eski sayfa: A üye ID, B onay kutusu, C bağlantı.
SAYFA_HARITALARI = {
    "cennet kt": {
        "personel": None, "uye": "A", "ana": None, "tip": None, "link": "C",
        "kategori": None, "tarih": None, "kt": "B", "gorsel2": None, "aciklama": "D",
    }
}
HARIC_SAYFALAR = {"HATALI", "ONAYLILAR"}
DESTEKLENEN_PROJELER = {"PP", "PA", "OF", "HI", "VI", "GA"}
BOT_KOPYA_ADI = "panel_excel_kopya.xlsx"

_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DATE_NUMFMTS = set(range(14, 23)) | {45, 46, 47}


def proje_normalize(ad):
    """Bilinen proje sayfa adlarını büyük harfe çevir; bilinmeyen eski adları koru."""
    temiz = str(ad or "").strip()
    buyuk = temiz.upper()
    return buyuk if buyuk in DESTEKLENEN_PROJELER else temiz


def _kol(harf):
    if harf in (None, "", "-"):
        return None
    return openpyxl.utils.column_index_from_string(str(harf).strip()) - 1


def _win_kopyala(kaynak, hedef):
    """Windows'ta Excel'in açık dosyasını CopyFileW ile kopyalamayı dener."""
    if os.name != "nt":
        raise OSError("sadece Windows")
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CopyFileW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL)
    k32.CopyFileW.restype = wintypes.BOOL
    if not k32.CopyFileW(kaynak, hedef, False):
        raise OSError(ctypes.get_last_error(), "CopyFileW basarisiz")


def _kaynak_kopyala(kaynak, gecici):
    try:
        shutil.copyfile(kaynak, gecici)
    except PermissionError:
        _win_kopyala(kaynak, gecici)


def kopyala(kaynak, hedef_klasor, deneme=2):
    """Çalışma kitabını yerel önbelleğe atomik kopyalar; eski panel uyumluluğu."""
    os.makedirs(hedef_klasor, exist_ok=True)
    hedef = os.path.join(hedef_klasor, "excel_kopya.xlsx")
    gecici = hedef + ".tmp"
    bot_kopya = os.path.join(os.path.dirname(kaynak), BOT_KOPYA_ADI)
    adaylar = [(kaynak, None)]
    if os.path.exists(bot_kopya) and os.path.abspath(bot_kopya) != os.path.abspath(kaynak):
        try:
            fark = os.path.getmtime(kaynak) - os.path.getmtime(bot_kopya)
        except OSError:
            fark = 0
        uyari = None if fark < 180 else f"botun panel kopyasi ana dosyadan {int(fark // 60)} dk eski"
        adaylar.append((bot_kopya, uyari))
    son_hata = None
    for yol, uyari in adaylar:
        for _ in range(deneme):
            try:
                _kaynak_kopyala(yol, gecici)
                with zipfile.ZipFile(gecici) as z:
                    if z.testzip() is not None:
                        raise IOError("zip bozuk")
                os.replace(gecici, hedef)
                return hedef, uyari
            except Exception as e:
                son_hata = e
                time.sleep(1)
    if os.path.exists(hedef):
        return hedef, f"kopyalanamadi ({son_hata}); onceki kopya kullaniliyor"
    raise IOError(f"Excel kopyalanamadi: {son_hata}")


def _metin(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v).strip()


def _tarih(v):
    """Excel G hücresi -> (ISO tarih|None, ham değer). Ham değer her zaman saklanır."""
    if v is None or v == "":
        return None, ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S"), v.strftime("%Y-%m-%d %H:%M:%S")
    s = str(v).strip()
    for f in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(s, f).strftime("%Y-%m-%d %H:%M:%S"), s
        except ValueError:
            pass
    return None, s


def _kt(v):
    if isinstance(v, bool):
        return 1 if v else 0
    return 1 if _metin(v).lower() in ("true", "1", "x", "evet", "ok", "kt", "✓") else 0


GYAZO_ID = re.compile(r"gyazo\.com/(?:[a-z0-9_-]+/)*([0-9a-f]{32})", re.I)


def link_turu_ve_kimlik(link):
    """-> (tur, kimlik); ağ isteği yapmaz."""
    s = (link or "").strip()
    if not s:
        return "bos", ""
    m = GYAZO_ID.search(s)
    if m and "teamzone" not in s.lower():
        return "gyazo", m.group(1).lower()
    low = s.lower()
    if "sharepoint.com" in low or "onedrive.aspx" in low or "1drv.ms" in low:
        from urllib.parse import parse_qs, unquote, urlparse
        try:
            q = parse_qs(urlparse(s).query)
            yol = unquote(q.get("id", [""])[0])
            ad = yol.rsplit("/", 1)[-1]
            return "onedrive", ad.lower() or low
        except Exception:
            return "onedrive", low
    if "snappark" in low:
        return "snappark", low.rstrip("/").rsplit("/", 1)[-1]
    if "teamzone.gyazo" in low:
        return "teamzone", low.rstrip("/").rsplit("/", 1)[-1]
    if re.match(r"^[a-z]:\\", low) or low.startswith("\\\\"):
        return "dosya", os.path.basename(s.replace("\\", "/")).lower()
    if low.startswith("http"):
        return "diger", low
    return "metin", ""


PARMAK_ALANLARI = ("personel", "uye", "ana", "tip", "kategori", "tarih_ham", "link")


def parmak_ozeti(satir_degerleri, uzunluk=16):
    parmak = "|".join(str(satir_degerleri.get(k, "") or "") for k in PARMAK_ALANLARI)
    return hashlib.sha1(parmak.encode("utf-8")).hexdigest()[:uzunluk]


def anahtar_uret(sayfa, satir_degerleri, link, sayac, link_sayisi=None):
    """Eski panel uyumluluğu için içerik/link temelli anahtar üretir.

    Tek-seferlik aktarım kendi, satır-kararlı ``legacy:...`` anahtarını kullanır.
    """
    tur, kimlik = link_turu_ve_kimlik(link)
    if tur in ("gyazo", "onedrive", "snappark", "teamzone", "dosya", "diger") and kimlik:
        temel = f"{sayfa}|{tur}:{kimlik}"
        if link_sayisi and link_sayisi.get(f"{tur}:{kimlik}", 0) > 1:
            temel += "|h:" + parmak_ozeti(satir_degerleri, 8)
    else:
        temel = f"{sayfa}|h:" + parmak_ozeti(satir_degerleri)
    n = sayac.get(temel, 0) + 1
    sayac[temel] = n
    return (temel if n == 1 else f"{temel}#{n}"), tur


def _yerel_ad(tag):
    return tag.rsplit("}", 1)[-1]


def _xlsx_sayfalari(z):
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError as e:
        raise ValueError("Geçerli bir .xlsx çalışma kitabı değil") from e
    hedefler = {r.attrib.get("Id"): r.attrib.get("Target", "") for r in rels}
    sonuc = []
    for e in wb.iter():
        if _yerel_ad(e.tag) != "sheet":
            continue
        rid = e.attrib.get(_NS_REL + "id")
        hedef = hedefler.get(rid)
        if not hedef:
            continue
        if hedef.startswith("/"):
            xml_yol = hedef.lstrip("/")
        else:
            xml_yol = posixpath.normpath(posixpath.join("xl", hedef))
        sonuc.append((e.attrib.get("name", ""), xml_yol))
    return sonuc, wb


def _paylasilan_metinler(z):
    try:
        with z.open("xl/sharedStrings.xml") as f:
            agac = ET.parse(f)
    except KeyError:
        return []
    sonuc = []
    for si in agac.getroot():
        if _yerel_ad(si.tag) != "si":
            continue
        sonuc.append("".join(t.text or "" for t in si.iter() if _yerel_ad(t.tag) == "t"))
    return sonuc


def _tarih_stilleri(z):
    """Stil numarası -> Excel sayısının tarih olduğu bilgisi."""
    try:
        agac = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return set()
    ozel = {}
    for e in agac.iter():
        if _yerel_ad(e.tag) == "numFmt":
            try:
                ozel[int(e.attrib.get("numFmtId", "-1"))] = e.attrib.get("formatCode", "")
            except ValueError:
                continue
    xfs = next((e for e in agac.iter() if _yerel_ad(e.tag) == "cellXfs"), None)
    if xfs is None:
        return set()
    tarih = set()
    for i, xf in enumerate(xfs):
        if _yerel_ad(xf.tag) != "xf":
            continue
        try:
            fmt = int(xf.attrib.get("numFmtId", "0"))
        except ValueError:
            continue
        kod = re.sub(r'"[^"]*"|\\.', "", ozel.get(fmt, "")).lower()
        if fmt in _DATE_NUMFMTS or (kod and re.search(r"[ymdhss]", kod)):
            tarih.add(i)
    return tarih


def _hucre_degeri(c, paylasilan, tarih_stilleri, date1904):
    tur = c.attrib.get("t")
    stil = c.attrib.get("s")
    v = None
    for x in c:
        ad = _yerel_ad(x.tag)
        if ad == "v":
            v = x.text
            break
        if ad == "is":
            return "".join(t.text or "" for t in x.iter() if _yerel_ad(t.tag) == "t")
    if v is None:
        return None
    if tur == "s":
        try:
            return paylasilan[int(v)]
        except (ValueError, IndexError):
            return ""
    if tur == "b":
        return v in ("1", "true", "TRUE")
    if tur in ("str", "inlineStr", "e"):
        return v
    try:
        sayi = float(v)
    except ValueError:
        return v
    try:
        stil_no = int(stil) if stil is not None else -1
    except ValueError:
        stil_no = -1
    if stil_no in tarih_stilleri:
        # Excel'in 1900 artık-yıl hatası için 1899-12-30 başlangıcı kullanılır.
        baslangic = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
        return baslangic + timedelta(days=sayi)
    return int(sayi) if sayi.is_integer() else sayi


def _sutun_indeksi(ref):
    m = re.match(r"([A-Za-z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1).upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def _satir_hucreleri(z, xml_yol, paylasilan, tarih_stilleri, date1904):
    """XML'i seyrek satırlar halinde verir; milyonluk boş aralığı genişletmez."""
    try:
        kaynak = z.open(xml_yol)
    except KeyError as e:
        raise ValueError(f"Çalışma sayfası XML'i eksik: {xml_yol}") from e
    with kaynak:
        for _, e in ET.iterparse(kaynak, events=("end",)):
            if _yerel_ad(e.tag) != "row":
                continue
            try:
                satir_no = int(e.attrib.get("r", "0"))
            except ValueError:
                satir_no = 0
            hucreler = {}
            for c in e:
                if _yerel_ad(c.tag) != "c":
                    continue
                col = _sutun_indeksi(c.attrib.get("r"))
                if col is not None:
                    hucreler[col] = _hucre_degeri(c, paylasilan, tarih_stilleri, date1904)
            if satir_no:
                yield satir_no, hucreler
            e.clear()


def oku(xlsx_yol, sutun_haritasi=None, haric=HARIC_SAYFALAR):
    """Çalışma kitabını okur.

    Dönüş: ``{proje: [satir sözlüğü]}``. HATALI ve ONAYLILAR sayfaları kayıt
    değildir. Bilinen küçük harfli proje adları PP/PA/OF/HI/VI/GA'ya normalize
    edilir; başka eski sayfalar görünür kalır.
    """
    sutun_haritasi = sutun_haritasi or {}
    haric_buyuk = {str(h).strip().upper() for h in haric}
    sonuc = {}
    with zipfile.ZipFile(xlsx_yol) as z:
        sayfalar, wb = _xlsx_sayfalari(z)
        paylasilan = _paylasilan_metinler(z)
        tarih_stilleri = _tarih_stilleri(z)
        date1904 = any(
            _yerel_ad(e.tag) == "workbookPr" and e.attrib.get("date1904", "").lower() in ("1", "true")
            for e in wb.iter()
        )
        for ham_ad, xml_yol in sayfalar:
            if str(ham_ad).strip().upper() in haric_buyuk:
                continue
            ad = proje_normalize(ham_ad)
            harita = dict(VARSAYILAN_HARITA)
            harita.update(SAYFA_HARITALARI.get(str(ham_ad).strip().lower(), {}))
            harita.update(sutun_haritasi.get(ham_ad, sutun_haritasi.get(ad, {})))
            idx = {k: _kol(v) for k, v in harita.items()}
            ana_kolonlar = [idx[k] for k in ("personel", "uye", "ana", "tip", "link", "kategori", "tarih") if idx.get(k) is not None]
            satirlar, sayac, link_sayisi = [], {}, {}
            kullanilan = {v for v in idx.values() if v is not None}
            for satir_no, hucreler in _satir_hucreleri(z, xml_yol, paylasilan, tarih_stilleri, date1904):
                if satir_no == 1:
                    continue
                # KT/H tek başına FALSE olsa bile bu bir kayıt değildir. Ancak 30 boş satır
                # gibi bir erken çıkış da yoktur: alttaki gerçek veriler korunur.
                if not any(hucreler.get(j) not in (None, "") for j in ana_kolonlar):
                    continue
                def hucre(k):
                    j = idx.get(k)
                    return hucreler.get(j) if j is not None else None
                tarih, tarih_ham = _tarih(hucre("tarih"))
                d = {
                    "satir": satir_no,
                    "personel": _metin(hucre("personel")), "uye": _metin(hucre("uye")),
                    "ana": _metin(hucre("ana")), "tip": _metin(hucre("tip")),
                    "link": _metin(hucre("link")), "kategori": _metin(hucre("kategori")),
                    "tarih": tarih, "tarih_ham": tarih_ham, "kt": _kt(hucre("kt")),
                    "gorsel2": _metin(hucre("gorsel2")), "aciklama": _metin(hucre("aciklama")),
                }
                ek = {
                    openpyxl.utils.get_column_letter(j + 1): _metin(v)
                    for j, v in hucreler.items() if j not in kullanilan and v not in (None, "")
                }
                d["ek_not"] = "; ".join(f"{k}={v}" for k, v in sorted(ek.items())) if ek else ""
                tur, kimlik = link_turu_ve_kimlik(d["link"])
                if kimlik:
                    link_sayisi[f"{tur}:{kimlik}"] = link_sayisi.get(f"{tur}:{kimlik}", 0) + 1
                satirlar.append(d)
            for d in satirlar:
                d["anahtar"], d["link_turu"] = anahtar_uret(ad, d, d["link"], sayac, link_sayisi)
            # Yinelenen normalleşmiş sayfalar teorik olarak olabilir; görünür veriyi kaybetme.
            sonuc.setdefault(ad, []).extend(satirlar)
    return sonuc
