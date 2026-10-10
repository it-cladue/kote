# -*- coding: utf-8 -*-
"""Panel kullanicilari: bot klasorundeki panel_kullanicilar.json (OneDrive ile tum bilgisayarlara dagilir).

Her bilgisayarda calisan panel ayni dosyayi okur; boylece bir kez acilan kullanici her yerde gecerlidir.
Yazma: tmp dosyaya yaz + yerine koy (OneDrive kisa sureli kilitlerse birkac kez dener).
Kilitleme sayaclari (5 hatali giris) yalnizca bu islemde (bellekte) tutulur.
"""
import os, json, time, threading
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

DOSYA_ADI = "panel_kullanicilar.json"
_kilit = threading.RLock()
_hatali = {}   # kullanici_adi -> [sayi, kilit_bitis(datetime|None)]


def yol(ayar):
    return os.path.join(ayar["BOT_KLASOR"], DOSYA_ADI)


def var_mi(ayar):
    return os.path.exists(yol(ayar))


_onbellek = {"imza": None, "veri": None}


def yukle(ayar):
    import copy
    y = yol(ayar)
    if not os.path.exists(y):
        return {"surum": 1, "kullanicilar": []}
    try:
        st = os.stat(y)
        imza = (y, st.st_mtime_ns, st.st_size)
    except OSError:
        imza = None
    if imza and _onbellek["imza"] == imza and _onbellek["veri"] is not None:
        return copy.deepcopy(_onbellek["veri"])
    for deneme in range(5):
        try:
            with open(y, encoding="utf-8-sig") as f:
                d = json.load(f)
            if not (isinstance(d, dict) and isinstance(d.get("kullanicilar"), list)):
                d = {"surum": 1, "kullanicilar": []}
            d = _catisma_kopyalarini_birlestir(ayar, d)
            _onbellek["imza"], _onbellek["veri"] = imza, copy.deepcopy(d)
            return d
        except (PermissionError, OSError, json.JSONDecodeError):
            time.sleep(0.3)
    return {"surum": 1, "kullanicilar": []}


def _catisma_kopyalarini_birlestir(ayar, d):
    """OneDrive iki bilgisayardan ayni anda yazilinca 'panel_kullanicilar-<PC>.json' kopyasi birakir.
    Kopyalardaki kullanicilar kaybolmasin: kullanici adina gore birlestir, her kullanicinin en yeni 'guncelleme'si kazanir."""
    import glob
    kok = ayar["BOT_KLASOR"]
    kopyalar = [k for k in glob.glob(os.path.join(kok, "panel_kullanicilar*.json")) if os.path.basename(k).lower() != DOSYA_ADI and not k.endswith(".tmp")]
    if not kopyalar:
        return d
    mevcut = {(u.get("kullanici_adi") or "").lower(): u for u in d["kullanicilar"]}
    degisti = False
    for k in kopyalar:
        try:
            with open(k, encoding="utf-8-sig") as f:
                dk = json.load(f)
            for u in dk.get("kullanicilar", []):
                ad = (u.get("kullanici_adi") or "").lower()
                if not ad:
                    continue
                if ad not in mevcut or (u.get("guncelleme") or "") > (mevcut[ad].get("guncelleme") or ""):
                    mevcut[ad] = u
                    degisti = True
        except Exception:
            continue
    if degisti:
        d["kullanicilar"] = list(mevcut.values())
    return d


def once_kullanilmis(ayar):
    """Bu bot klasorunde panel daha once kurulmus mu (kullanici dosyasi OneDrive'dan henuz gelmemis olabilir)?"""
    kok = ayar["BOT_KLASOR"]
    for ad in ("panel_kuyruk", "panel_kuyruk_sonuc.jsonl", "panel_kuyruk_islenen.txt", "panel_kuyruk_offset.json", "heartbeat.txt", "kayitlar.jsonl"):
        if os.path.exists(os.path.join(kok, ad)):
            return True
    return False


def kaydet(ayar, veri):
    y = yol(ayar)
    tmp = y + ".tmp"
    veri["surum"] = 1
    veri["guncelleme"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    son = None
    with _kilit:
        for deneme in range(5):
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(veri, f, ensure_ascii=False, indent=2)
                os.replace(tmp, y)
                return True
            except (PermissionError, OSError) as e:
                son = e
                time.sleep(0.4)
    raise IOError(f"panel_kullanicilar.json yazilamadi: {son}")


def _bul(veri, ad):
    ad = (ad or "").strip().lower()
    for u in veri["kullanicilar"]:
        if (u.get("kullanici_adi") or "").lower() == ad:
            return u
    return None


def bul(ayar, ad):
    return _bul(yukle(ayar), ad)


def hepsi(ayar):
    return sorted(yukle(ayar)["kullanicilar"], key=lambda u: (u.get("kullanici_adi") or "").lower())


def ekle(ayar, ad, yetki, sifre, gorunen_ad=None, olusturan=None):
    ad = (ad or "").strip().lower()
    if not ad or not yetki:
        raise ValueError("Kullanici adi ve yetki gerekli.")
    with _kilit:
        veri = yukle(ayar)
        if _bul(veri, ad):
            raise ValueError("Bu kullanici adi zaten var.")
        simdi = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        veri["kullanicilar"].append({"kullanici_adi": ad, "ad": gorunen_ad or ad, "sifre_hash": generate_password_hash(sifre), "yetki": yetki,
                                     "aktif": True, "sifre_degistir": True, "olusturma": simdi, "guncelleme": simdi, "olusturan": olusturan or ""})
        kaydet(ayar, veri)


def guncelle(ayar, ad, **alanlar):
    """alanlar: yetki, aktif, sifre (duz metin -> hash), sifre_degistir, ad"""
    with _kilit:
        veri = yukle(ayar)
        u = _bul(veri, ad)
        if not u:
            raise ValueError("Kullanici bulunamadi.")
        if "sifre" in alanlar:
            u["sifre_hash"] = generate_password_hash(alanlar.pop("sifre"))
        u.update(alanlar)
        u["guncelleme"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kaydet(ayar, veri)
        return u


def dogrula(ayar, ad, sifre):
    """-> (kullanici|None, hata_mesaji|None)"""
    ad = (ad or "").strip().lower()
    h = _hatali.get(ad)
    if h and h[1] and h[1] > datetime.now():
        return None, "Cok fazla hatali deneme; 15 dakika sonra tekrar deneyin."
    u = bul(ayar, ad)
    if u and u.get("aktif", True) and check_password_hash(u.get("sifre_hash", ""), sifre or ""):
        _hatali.pop(ad, None)
        return u, None
    n = (h[0] if h else 0) + 1
    _hatali[ad] = [0 if n >= 5 else n, datetime.now() + timedelta(minutes=15) if n >= 5 else None]
    return None, "Kullanici adi veya sifre hatali."


def sqlite_tasi(ayar, conn):
    """Eski surum (panel.db icindeki panel_kullanicilari) -> ortak dosya. Dosya varsa ya da klasorde panel
    daha once kullanilmissa (dosya OneDrive'dan henuz gelmemis olabilir) dokunmaz."""
    if var_mi(ayar) or once_kullanilmis(ayar):
        return 0
    try:
        rows = conn.execute("SELECT * FROM panel_kullanicilari").fetchall()
    except Exception:
        return 0
    if not rows:
        return 0
    veri = {"surum": 1, "kullanicilar": []}
    for r in rows:
        veri["kullanicilar"].append({"kullanici_adi": r["kullanici_adi"], "ad": r["ad"] or r["kullanici_adi"], "sifre_hash": r["sifre_hash"], "yetki": r["yetki"],
                                     "aktif": bool(r["aktif"]), "sifre_degistir": bool(r["sifre_degistir"]), "olusturma": r["olusturma"] or "", "olusturan": "sqlite"})
    kaydet(ayar, veri)
    return len(veri["kullanicilar"])
