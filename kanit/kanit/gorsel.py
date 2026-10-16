# -*- coding: utf-8 -*-
"""Gorsel deposu: VERI/gorseller/<PROJE>/<dosya>. Kayitta goreli yol tutulur (gorsel_dosya). Kucuk resimler VERI/onbellek/thumbs."""
import os, re, io, hashlib
from datetime import datetime
from urllib.parse import urlparse

GORSEL_UZANTILAR = (".jpg", ".jpeg", ".png", ".webp", ".gif")
GYAZO_ID = re.compile(r"(?:^|://|\s|[(\[<\"'])(?:[a-z0-9-]+\.)*gyazo\.com/(?:[a-z0-9_-]+/)*([0-9a-f]{32})", re.I)
_GYAZO_HOSTLAR = ("gyazo.com", "i.gyazo.com", "www.gyazo.com")
_PARCA = re.compile(r"[^0-9A-Za-zÇçĞğİıÖöŞşÜü_-]+")


def link_turu_ve_kimlik(link):
    """-> (tur, kimlik)  tur: gyazo|onedrive|dosya|metin|bos (telegrampanel/app/excel_oku.py ile ayni kurallar)"""
    s = (link or "").strip()
    if not s:
        return "bos", ""
    m = GYAZO_ID.search(s)
    if m and "teamzone" not in s.lower():
        return "gyazo", m.group(1).lower()
    low = s.lower()
    if "sharepoint.com" in low or "onedrive.aspx" in low or "1drv.ms" in low:
        from urllib.parse import parse_qs, unquote
        try:
            q = parse_qs(urlparse(s).query)
            yol = unquote(q.get("id", [""])[0])
            return "onedrive", (yol.rsplit("/", 1)[-1] or low).lower()
        except Exception:
            return "onedrive", low
    if re.match(r"^[A-Za-z]:\\", s) or s.startswith("\\\\") or s.startswith("/"):
        return "dosya", os.path.basename(s.replace("\\", "/")).lower()
    return "metin", s


def gyazo_url(link, kimlik):
    """Indirilecek adres yalnizca gyazo.com'dan: i.gyazo.com/<id>.<uz> ise o, degilse i.gyazo.com/<id>.jpg"""
    try:
        u = urlparse((link or "").strip())
        if u.scheme in ("http", "https") and (u.hostname or "").lower() == "i.gyazo.com" and re.fullmatch(r"/" + re.escape(kimlik) + r"\.(jpg|jpeg|png|gif|webp)", u.path, re.I):
            return "https://i.gyazo.com" + u.path
    except Exception:
        pass
    return f"https://i.gyazo.com/{kimlik}.jpg"


def dosya_parcasi(s, en_fazla=40):
    s = _PARCA.sub("-", str(s or "")).strip("-._")
    return s[:en_fazla]


def dosya_adi(kategori_etiket, zaman, personel="", uye="", ana="", tip="", uzanti=".jpg"):
    """Botun Get-GorselDosyaAdi kalibi: KATEGORI_yyyy-MM-dd_HH-mm-ss_personel_uye_ana_tip.jpg"""
    if isinstance(zaman, str):
        try:
            zaman = datetime.strptime(zaman[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            zaman = datetime.now()
    parcalar = [dosya_parcasi((kategori_etiket or "KAYIT").upper()) or "KAYIT", zaman.strftime("%Y-%m-%d_%H-%M-%S")]
    for alan in (personel, uye, ana, tip):
        p = dosya_parcasi(alan)
        if p:
            parcalar.append(p)
    ad = "_".join(parcalar)
    if len(ad) > 180:
        ad = ad[:180].rstrip("-._")
    return ad + uzanti


def gorsel_mi(baytlar):
    return bool(baytlar) and (baytlar[:2] == b"\xff\xd8" or baytlar[:4] == b"\x89PNG" or baytlar[:4] == b"RIFF" or baytlar[:3] == b"GIF")


def icinde_mi(yol, kok):
    try:
        k = os.path.abspath(kok)
        return os.path.commonpath([os.path.abspath(yol), k]) == k and str(yol).lower().endswith(GORSEL_UZANTILAR)
    except Exception:
        return False


def kaydet(gorseller_kok, proje, baytlar, ad):
    """Baytlari gorseller/<PROJE>/<ad> olarak yazar (ad catisirsa -2, -3 eklenir). -> goreli yol ('PP/ARK_2026-..jpg')"""
    if not gorsel_mi(baytlar):
        raise ValueError("gorsel degil")
    proje = dosya_parcasi(proje).upper() or "DIGER"
    ad = os.path.basename(ad.replace("\\", "/"))
    kok = os.path.join(gorseller_kok, proje)
    os.makedirs(kok, exist_ok=True)
    taban, uz = os.path.splitext(ad)
    hedef, i = os.path.join(kok, ad), 1
    while os.path.exists(hedef):
        i += 1
        hedef = os.path.join(kok, f"{taban}-{i}{uz}")
    tmp = hedef + ".tmp"
    with open(tmp, "wb") as f:
        f.write(baytlar)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, hedef)
    return os.path.relpath(hedef, gorseller_kok).replace("\\", "/")


def tam_yol(gorseller_kok, goreli):
    if not goreli:
        return None
    y = os.path.join(gorseller_kok, goreli.replace("\\", "/"))
    return y if icinde_mi(y, gorseller_kok) and os.path.exists(y) else None


def kucuk(onbellek, yol, boyut=400):
    """400px kucuk resim; onbellek/thumbs altinda. -> yol|None"""
    try:
        from PIL import Image
    except Exception:
        return yol
    try:
        ad = hashlib.sha1(os.path.abspath(yol).encode("utf-8")).hexdigest()[:20] + ".jpg"
        hedef = os.path.join(onbellek, "thumbs", ad)
        os.makedirs(os.path.dirname(hedef), exist_ok=True)
        if os.path.exists(hedef) and os.path.getmtime(hedef) >= os.path.getmtime(yol):
            return hedef
        with Image.open(yol) as im:
            im = im.convert("RGB")
            im.thumbnail((boyut, boyut))
            im.save(hedef, "JPEG", quality=80)
        return hedef
    except Exception:
        return None


def jpeg_yap(baytlar, en_buyuk_kenar=2400, kalite=88):
    """Telegram fotografini JPEG'e cevirir (PNG/WEBP ise), cok buyukse kucultur. Pillow yoksa oldugu gibi doner."""
    try:
        from PIL import Image
    except Exception:
        return baytlar, ".jpg" if baytlar[:2] == b"\xff\xd8" else ".png"
    try:
        with Image.open(io.BytesIO(baytlar)) as im:
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            if max(im.size) > en_buyuk_kenar:
                im.thumbnail((en_buyuk_kenar, en_buyuk_kenar))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=kalite, optimize=True)
            return out.getvalue(), ".jpg"
    except Exception:
        return baytlar, ".jpg"
