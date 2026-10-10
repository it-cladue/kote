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
    ids = set(d.keys()) | set(onay.keys()) | set(engel.keys())
    out = []
    for i in sorted(ids, key=lambda x: (x not in onay, x)):
        u = d.get(i, {}) if isinstance(d.get(i), dict) else {}
        out.append({"id": i, "username": u.get("username", "") or onay.get(i, {}).get("ad", ""), "first_name": u.get("first_name", ""),
                    "last_seen": u.get("last_seen", ""), "kayit_sayisi": u.get("kayit_sayisi", 0) or 0,
                    "onayli": i in onay, "onay_tarihi": onay.get(i, {}).get("tarih", ""),
                    "engelli": i in engel, "engel_sebep": engel.get(i, {}).get("sebep", "")})
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
    """config.json'un GIZLI OLMAYAN alanlari (token/sifre asla okunmaz)"""
    yol = _yol(ayar, "config.json")
    try:
        with open(yol, encoding="utf-8-sig") as f:
            d = json.load(f)
    except Exception:
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


def bot_calisiyor_mu(ayar):
    """heartbeat.txt (bot yamasi) varsa yasi; yoksa Windows'ta telebot.ps1 sureci var mi"""
    hb = _yol(ayar, "heartbeat.txt")
    if os.path.exists(hb):
        yas = (datetime.now().timestamp() - os.path.getmtime(hb))
        return {"kaynak": "heartbeat", "yas_sn": int(yas), "canli": yas < 180}
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


