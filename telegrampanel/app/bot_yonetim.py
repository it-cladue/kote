# -*- coding: utf-8 -*-
"""Botun admin komutlarinin dosya karsiliklari. Bot bu dosyalari her mesajda yeniden okudugu icin
yeniden baslatma gerekmez. Yazim botun Set-TextFileAtomic kalibiyla: .tmp yaz + yerine koy, satir sonu ile."""
import os, re, json, shutil, subprocess, platform
from datetime import datetime

_ID_BOL = re.compile(r"(?=(?<![0-9])[0-9]{8,12}\|)")


def _yol(ayar, ad):
    return os.path.join(ayar["BOT_KLASOR"], ad)


def _oku_satirlar(yol):
    if not os.path.exists(yol):
        return []
    with open(yol, encoding="utf-8-sig", errors="replace") as f:
        ham = f.read()
    sonuc = []
    for ln in ham.splitlines():
        if not ln.strip():
            continue
        for p in _ID_BOL.split(ln):   # yapisik kayitlari ID basindan bol
            if p.strip():
                sonuc.append(p.strip())
    return sonuc


def _yaz_satirlar(yol, satirlar):
    tmp = yol + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(satirlar) + ("\r\n" if satirlar else ""))
    os.replace(tmp, yol)


# ---- onayli / engelli kullanicilar ----
def onaylilar(ayar):
    out = []
    for ln in _oku_satirlar(_yol(ayar, "onaylilar.txt")):
        p = [x.strip() for x in ln.split("|")]
        if len(p) >= 1:
            out.append({"id": p[0], "ad": p[1] if len(p) > 1 else "", "tarih": p[2] if len(p) > 2 else ""})
    return out


def engellenenler(ayar):
    out = []
    for ln in _oku_satirlar(_yol(ayar, "engellenenler.txt")):
        p = [x.strip() for x in ln.split("|")]
        out.append({"id": p[0], "kim": p[1] if len(p) > 1 else "", "tarih": p[2] if len(p) > 2 else "", "sebep": p[3] if len(p) > 3 else ""})
    return out


def _op(ayar, conn, op, deger, kim, ozet):
    from . import kuyruk
    return kuyruk.bot_islemi(ayar, conn, op, deger, kim, ozet)


# ---- yazma islemleri: dogrudan dosyaya DEGIL, bot kuyruguna (bot uygular; OneDrive ile baska PC'den de calisir) ----
def onayla(ayar, conn, tg_id, ad, kim="panel"):
    tg_id = str(tg_id).strip()
    return _op(ayar, conn, "bot_onayla", {"tg_id": tg_id, "ad": ad or tg_id}, kim, f"Onayla {tg_id} {ad or ''}".strip())


def onay_kaldir(ayar, conn, tg_id, kim="panel"):
    tg_id = str(tg_id).strip()
    return _op(ayar, conn, "bot_onay_kaldir", {"tg_id": tg_id}, kim, f"Onayi kaldir {tg_id}")


def engelle(ayar, conn, tg_id, ad, sebep, kim="panel"):
    tg_id = str(tg_id).strip()
    return _op(ayar, conn, "bot_engelle", {"tg_id": tg_id, "ad": ad or "", "sebep": sebep or "panel"}, kim, f"Engelle {tg_id} ({sebep or 'panel'})")


def engel_kaldir(ayar, conn, tg_id, kim="panel"):
    tg_id = str(tg_id).strip()
    return _op(ayar, conn, "bot_engel_kaldir", {"tg_id": tg_id}, kim, f"Engeli kaldir {tg_id}")


def bakim_modu_ayarla(ayar, conn, acik, kim="panel"):
    return _op(ayar, conn, "bot_bakim", {"acik": bool(acik)}, kim, "Bakim modu " + ("AC" if acik else "KAPAT"))


def gyazo_bakim_ayarla(ayar, conn, acik, kim="panel"):
    return _op(ayar, conn, "bot_gyazo_bakim", {"acik": bool(acik)}, kim, "Gyazo bakim " + ("AC" if acik else "KAPAT"))


def oturum_temizle(ayar, conn, tg_id=None, kim="panel"):
    return _op(ayar, conn, "bot_oturum_temizle", {"tg_id": str(tg_id or "")}, kim, f"Oturum temizle {tg_id or '(hepsi)'}")


def kategori_kaydet(ayar, conn, code, label, mode, kim="panel"):
    return _op(ayar, conn, "bot_kategori_ekle", {"code": code, "label": label, "mode": mode}, kim, f"Kategori ekle/guncelle {code}")


def kategori_sil(ayar, conn, code, kim="panel"):
    return _op(ayar, conn, "bot_kategori_sil", {"code": code}, kim, f"Kategori sil {code}")


def yedek_al(ayar, conn, kim="panel"):
    return _op(ayar, conn, "bot_yedek", {}, kim, "Yedek al")


def tam_sifirla(ayar, conn, tg_id, kim="panel"):
    """Botun /engel_kaldir_sifirla komutu: engel + onay + deneme + oturum birlikte temizlenir, kullanici yeniden sifreye duser."""
    tg_id = str(tg_id).strip()
    return _op(ayar, conn, "bot_tam_sifirla", {"tg_id": tg_id}, kim, f"Tam sifirla {tg_id}")


EXCEL_MODLARI = ("son_dolunun_altina", "ilk_bos_satir")


def excel_mod_ayarla(ayar, conn, mod, kim="panel"):
    """Botun /excel_mod komutu."""
    mod = (mod or "").strip()
    if mod not in EXCEL_MODLARI:
        raise ValueError("Gecersiz Excel yazma modu")
    return _op(ayar, conn, "bot_excel_mod", {"mod": mod}, kim, f"Excel yazma modu: {mod}")


def excel_son_satir_sor(ayar, conn, sayfa, kim="panel"):
    """Botun /excel_son_satir SAYFA komutu: bot kendi Excel baglantisindan son dolu / ilk bos / yazilacak satiri bildirir."""
    sayfa = (sayfa or "").strip().upper()
    if not sayfa or len(sayfa) > 31:
        raise ValueError("Sayfa adi bos")
    return _op(ayar, conn, "bot_excel_son_satir", {"sayfa": sayfa}, kim, f"Excel son satir sor: {sayfa}")


def bot_kapat(ayar, conn, kim="panel"):
    """Botun /kapat komutu: bot dongusu guvenli sekilde biter (yeniden baslatma bot bilgisayarindan yapilir)."""
    return _op(ayar, conn, "bot_kapat", {}, kim, "BOTU DURDUR")


# ---- salt okunur: botun /durum, /istatistik, /kullanici_durum, /kayit_raporu, /excel_mod karsiliklari ----
def denemeler(ayar):
    """denemeler.txt -> {tg_id: hatali sifre denemesi}"""
    out = {}
    for ln in _oku_satirlar(_yol(ayar, "denemeler.txt")):
        p = [x.strip() for x in ln.split("|")]
        if len(p) >= 2 and p[0]:
            try:
                out[p[0]] = int(p[1])
            except ValueError:
                pass
    return out


def excel_yazma_modu(ayar):
    try:
        with open(_yol(ayar, "excel_yazma_modu.txt"), encoding="utf-8-sig") as f:
            m = f.read().strip()
        return m if m in EXCEL_MODLARI else EXCEL_MODLARI[0]
    except Exception:
        return EXCEL_MODLARI[0]


def kullanici_defteri(ayar):
    yol = _yol(ayar, "kullanicilar.json")
    try:
        with open(yol, encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _sozluk(v):
    return {str(k): v[k] for k in v} if isinstance(v, dict) else {}


def son_hata(ayar):
    """Botun $global:LastErrorText karsiligi: logdaki son '!' satiri."""
    for s in reversed(son_log(ayar, 400)):
        if "] !" in s:
            return s
    return ""


def istatistik(ayar, conn):
    """Botun /istatistik + /kayit_raporu + /durum ozetleri (dosyalardan ve panel veritabanindan)."""
    defter = kullanici_defteri(ayar)
    ots = oturumlar(ayar)
    sayacli = [u for u in defter.values() if isinstance(u, dict) and u.get("kayit_sayisi")]
    rapor = sorted(sayacli, key=lambda u: -int(u.get("kayit_sayisi") or 0))[:15]
    kayit_raporu = [{"id": str(u.get("id") or ""), "ad": " / ".join(x for x in (u.get("username"), u.get("first_name")) if x),
                     "kayit": int(u.get("kayit_sayisi") or 0), "son": u.get("son_kayit_tarihi") or "",
                     "proje": u.get("son_kayit_proje") or "", "kategori": u.get("son_kayit_kategori") or ""} for u in rapor]
    db_proje = {r[0]: r[1] for r in conn.execute("SELECT proje, COUNT(*) FROM kayitlar WHERE silindi=0 GROUP BY proje").fetchall()}
    db_kt = conn.execute("SELECT SUM(kt=1), SUM(kt=0) FROM kayitlar WHERE silindi=0").fetchone()
    excel_satir = {r[0]: r[1] for r in conn.execute("SELECT proje, MAX(excel_satir) FROM kayitlar WHERE excel_durum<>'silinmis' GROUP BY proje").fetchall()}
    return {"defter": len(defter), "onayli": len(onaylilar(ayar)), "engelli": len(engellenenler(ayar)), "oturum": len(ots),
            "sayacli": len(sayacli), "bakim": bakim_modu(ayar), "gyazo_bakim": gyazo_bakim(ayar), "excel_mod": excel_yazma_modu(ayar),
            "kayit_raporu": kayit_raporu, "db_proje": db_proje, "db_toplam": sum(db_proje.values()),
            "db_onayli": int(db_kt[0] or 0), "db_bekleyen": int(db_kt[1] or 0), "excel_satir": excel_satir, "son_hata": son_hata(ayar)}


def kullanici_detay(ayar, conn, tg_id):
    """Botun /kullanici_durum ID komutunun genisi: kimlik, onay/engel/deneme, CANLI oturum (hangi adimda kaldi),
    panel veritabanindan proje/kategori dagilimi ve son kayitlar."""
    tg_id = str(tg_id).strip()
    u = kullanici_defteri(ayar).get(tg_id)
    u = u if isinstance(u, dict) else {}
    onay = {o["id"]: o for o in onaylilar(ayar)}.get(tg_id)
    engel = {e["id"]: e for e in engellenenler(ayar)}.get(tg_id)
    ot = None
    try:
        with open(_yol(ayar, "oturumlar.json"), encoding="utf-8-sig") as f:
            d = json.load(f)
        v = d.get(tg_id) if isinstance(d, dict) else None
        if isinstance(v, dict):
            ot = {k: vv for k, vv in v.items() if k != "fileId"}
            ot["gorsel_var"] = bool(v.get("fileId"))
    except Exception:
        ot = None
    rows = conn.execute("SELECT id, proje, kategori, personel, uye_id, ana_uye_id, tarih, kt, silindi, excel_durum, bekleyen_islem FROM kayitlar WHERE ekleyen_id=? ORDER BY COALESCE(tarih,'0000') DESC, id DESC", (tg_id,)).fetchall()
    proje, kategori, capraz = {}, {}, {}
    onayli = bekleyen = silinen = 0
    for r in rows:
        if r["silindi"] or r["excel_durum"] == "silinmis":
            silinen += 1
            continue
        proje[r["proje"]] = proje.get(r["proje"], 0) + 1
        k = (r["kategori"] or "").upper() or "-"
        kategori[k] = kategori.get(k, 0) + 1
        capraz.setdefault(r["proje"], {})[k] = capraz.get(r["proje"], {}).get(k, 0) + 1
        if r["kt"]:
            onayli += 1
        else:
            bekleyen += 1
    son = [{"id": r["id"], "proje": r["proje"], "kategori": r["kategori"] or "", "personel": r["personel"] or "", "uye_id": r["uye_id"] or "",
            "ana_uye_id": r["ana_uye_id"] or "", "tarih": r["tarih"] or "", "kt": bool(r["kt"]),
            "silindi": bool(r["silindi"] or r["excel_durum"] == "silinmis"), "bekleyen": r["bekleyen_islem"] or ""} for r in rows[:25]]
    return {"id": tg_id, "username": u.get("username") or (onay or {}).get("ad") or "", "first_name": u.get("first_name") or "",
            "last_seen": u.get("last_seen") or "", "status": u.get("status") or "",
            "onayli": bool(onay), "onay_tarihi": (onay or {}).get("tarih", ""),
            "engelli": bool(engel), "engel_sebep": (engel or {}).get("sebep", ""), "engel_tarihi": (engel or {}).get("tarih", ""),
            "deneme": denemeler(ayar).get(tg_id, 0), "oturum": ot,
            "bot_sayac": {"kayit": int(u.get("kayit_sayisi") or 0), "son_tarih": u.get("son_kayit_tarihi") or "", "son_proje": u.get("son_kayit_proje") or "",
                          "son_kategori": u.get("son_kayit_kategori") or "", "proje": _sozluk(u.get("proje_sayilari")), "kategori": _sozluk(u.get("kategori_sayilari"))},
            "panel": {"toplam": onayli + bekleyen, "onayli": onayli, "bekleyen": bekleyen, "silinen": silinen, "proje": proje, "kategori": kategori, "capraz": capraz, "son": son},
            "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def son_islemler(conn, n=30):
    return [dict(r) for r in conn.execute("SELECT * FROM islem_sonuclari ORDER BY zaman DESC, rowid DESC LIMIT ?", (n,)).fetchall()]


def telegram_kullanicilari(ayar):
    """kullanicilar.json + onaylilar + engellenenler birlesik gorunum"""
    yol = _yol(ayar, "kullanicilar.json")
    d = {}
    if os.path.exists(yol):
        try:
            with open(yol, encoding="utf-8-sig") as f:
                d = json.load(f)
        except Exception:
            d = {}
    onay = {o["id"]: o for o in onaylilar(ayar)}
    engel = {e["id"]: e for e in engellenenler(ayar)}
    den = denemeler(ayar)
    ots = {o["id"]: o for o in oturumlar(ayar)}
    ids = set(d.keys()) | set(onay.keys()) | set(engel.keys()) | set(ots.keys())
    out = []
    for i in sorted(ids, key=lambda x: (x not in onay, x)):
        u = d.get(i, {}) if isinstance(d.get(i), dict) else {}
        ot = ots.get(i)
        out.append({"id": i, "username": u.get("username", "") or onay.get(i, {}).get("ad", ""), "first_name": u.get("first_name", ""),
                    "last_seen": u.get("last_seen", ""), "kayit_sayisi": u.get("kayit_sayisi", 0) or 0, "status": u.get("status", ""),
                    "son_kayit": u.get("son_kayit_tarihi", ""), "son_proje": u.get("son_kayit_proje", ""), "son_kategori": u.get("son_kayit_kategori", ""),
                    "onayli": i in onay, "onay_tarihi": onay.get(i, {}).get("tarih", ""),
                    "engelli": i in engel, "engel_sebep": engel.get(i, {}).get("sebep", ""),
                    "deneme": den.get(i, 0), "oturum": ({"adim": ot.get("adim") or ot.get("step") or "", "proje": ot.get("proje") or "", "kategori": ot.get("kategori") or ""} if ot else None)})
    return out


def kullanici_filtrele(liste, q="", sure_saat=0, durum="", adet=0):
    """Botun /son_kullanicilar [adet] [sure] ve /kullanici_ara kelime komutlari: arama, sure, durum ve adet suzgeci."""
    q = (q or "").strip().lower()
    out = []
    esik = None
    if sure_saat and int(sure_saat) > 0:
        from datetime import timedelta
        esik = (datetime.now() - timedelta(hours=int(sure_saat))).strftime("%Y-%m-%d %H:%M:%S")
    for u in liste:
        if q and q not in f"{u['id']} {u['username']} {u['first_name']}".lower():
            continue
        if esik and (u.get("last_seen") or "") < esik:
            continue
        if durum == "onayli" and not (u["onayli"] and not u["engelli"]):
            continue
        if durum == "engelli" and not u["engelli"]:
            continue
        if durum == "onaysiz" and (u["onayli"] or u["engelli"]):
            continue
        if durum == "oturum" and not u.get("oturum"):
            continue
        out.append(u)
    if esik or q or durum:
        out.sort(key=lambda u: u.get("last_seen") or "", reverse=True)
    if adet and int(adet) > 0:
        out = out[:int(adet)]
    return out


# ---- kategoriler ----
def kategoriler(ayar):
    yol = _yol(ayar, "kategoriler.json")
    try:
        with open(yol, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return []


# ---- bakim anahtarlari ----
def bakim_modu(ayar):
    return os.path.exists(_yol(ayar, "bakim_modu.txt"))


def gyazo_bakim(ayar):
    yol = _yol(ayar, "gyazo_bakim.txt")
    if os.path.exists(yol):
        with open(yol, encoding="utf-8-sig") as f:
            return f.read().strip() != "0"
    cfg = config(ayar)
    return str(cfg.get("GYAZO_BAKIM", "0")).strip().lower() not in ("0", "false", "kapali")


def config(ayar):
    """config.json'un GIZLI OLMAYAN alanlari (token/sifre asla okunmaz). Paylasim klasoru modunda bot bunlari
    panel_bot_ayarlari.json olarak koyar (gizli alanlar ayiklanmis)."""
    d = None
    for ad in ("config.json", "panel_bot_ayarlari.json"):
        try:
            with open(_yol(ayar, ad), encoding="utf-8-sig") as f:
                d = json.load(f)
            break
        except Exception:
            continue
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if not any(s in k.upper() for s in ("TOKEN", "PASSWORD", "SIFRE", "SECRET"))}


# ---- oturumlar ----
def oturumlar(ayar):
    yol = _yol(ayar, "oturumlar.json")
    try:
        with open(yol, encoding="utf-8-sig") as f:
            d = json.load(f)
        return [{"id": k, **{kk: vv for kk, vv in v.items() if kk != "fileId"}} for k, v in d.items() if isinstance(v, dict)]
    except Exception:
        return []


# ---- log / durum / yedek ----
def son_log(ayar, n=200, sadece_hata=False):
    yol = ayar.get("LOG_DOSYA") or _yol(ayar, "bot_log.txt")
    if not os.path.exists(yol):
        return []
    with open(yol, "rb") as f:
        f.seek(0, 2)
        boy = f.tell()
        f.seek(max(0, boy - 400000))
        satirlar = f.read().decode("utf-8", errors="replace").splitlines()
    if sadece_hata:
        satirlar = [s for s in satirlar if "] !" in s or "] ! " in s or "Hata" in s or "hatasi" in s]
    return satirlar[-n:]


def yerel_bot_sureci():
    """Bu bilgisayarda telebot.ps1 calisiyor mu? (Windows: Win32_Process). Bot bilgisayarini tanimak icin."""
    if platform.system() != "Windows":
        return False
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -like '*telebot.ps1*' } | Measure-Object | Select-Object -ExpandProperty Count"],
                             capture_output=True, text=True, timeout=15)
        return int((out.stdout or "0").strip() or 0) > 0
    except Exception:
        return False


def admin_sifresi_dogru(ayar, sifre):
    """Botun ADMIN_PASSWORD'u (config.json ya da TELEBOT_ADMIN_PASSWORD) ile eslesiyor mu? Ilk-admin yeniden olusturma kapisi."""
    if not sifre:
        return False
    beklenen = os.environ.get("TELEBOT_ADMIN_PASSWORD")
    if not beklenen:
        try:
            with open(_yol(ayar, "config.json"), encoding="utf-8-sig") as f:
                beklenen = (json.load(f) or {}).get("ADMIN_PASSWORD")
        except Exception:
            beklenen = None
    return bool(beklenen) and str(beklenen) == str(sifre)


def bot_calisiyor_mu(ayar):
    """heartbeat.txt (bot yamasi) varsa yasi; yoksa Windows'ta telebot.ps1 sureci var mi"""
    hb = _yol(ayar, "heartbeat.txt")
    if os.path.exists(hb):
        yas = (datetime.now().timestamp() - os.path.getmtime(hb))
        # bot 60 sn'de bir yazar; OneDrive esitlemesi 1-2 dk gecikebilir -> 5 dk esigi
        return {"kaynak": "heartbeat", "yas_sn": int(yas), "canli": yas < 300}
    if platform.system() == "Windows":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -like '*telebot.ps1*' } | Measure-Object | Select-Object -ExpandProperty Count"],
                                 capture_output=True, text=True, timeout=15)
            n = int((out.stdout or "0").strip() or 0)
            return {"kaynak": "surec", "yas_sn": None, "canli": n > 0}
        except Exception:
            pass
    return {"kaynak": "bilinmiyor", "yas_sn": None, "canli": None}


