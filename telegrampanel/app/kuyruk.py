# -*- coding: utf-8 -*-
"""Panel -> bot is kuyrugu. Panel Excel'e ASLA dogrudan yazmaz; islemi kuyruga ekler,
bot kendi Excel baglantisiyla uygular ve sonucu panel_kuyruk_sonuc.jsonl'a yazar."""
import os, re, json, uuid, socket, getpass, threading
from datetime import datetime

_kilit = threading.Lock()


def istemci_adi(ayar):
    """Her bilgisayar kendi kuyruk dosyasina yazar (OneDrive'da ayni dosyaya iki kisi yazmasin):
    panel_kuyruk\<bilgisayar>_<windows kullanicisi>.jsonl"""
    if ayar.get("ISTEMCI"):
        return str(ayar["ISTEMCI"])
    try:
        ham = f"{socket.gethostname()}_{getpass.getuser()}"
    except Exception:
        ham = "panel"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", ham).strip("_")[:60] or "panel"


def kuyruk_yolu(ayar):
    return os.path.join(ayar["BOT_KLASOR"], "panel_kuyruk", istemci_adi(ayar) + ".jsonl")


def sonuc_yolu(ayar):
    return os.path.join(ayar["BOT_KLASOR"], "panel_kuyruk_sonuc.jsonl")


def ekle(ayar, op, sayfa, link, parmak, deger=None, kullanici=None, anahtar=None):
    kayit = {"id": uuid.uuid4().hex, "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "op": op, "sayfa": sayfa,
             "link": link or "", "parmak": parmak or {}, "deger": deger or {}, "kullanici": kullanici or "", "anahtar": anahtar or ""}
    with _kilit:
        y = kuyruk_yolu(ayar)
        os.makedirs(os.path.dirname(y), exist_ok=True)
        son = None
        for deneme in range(5):
            try:
                with open(y, "a", encoding="utf-8") as f:
                    f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                return kayit["id"]
            except (PermissionError, OSError) as e:
                son = e
                import time
                time.sleep(0.3)
        raise IOError(f"kuyruk dosyasina yazilamadi ({y}): {son}")


def sonuclari_oku(ayar, offset):
    """offset'ten itibaren yeni sonuc satirlari -> (liste, yeni_offset)"""
    yol = sonuc_yolu(ayar)
    if not os.path.exists(yol):
        return [], offset
    sonuclar = []
    with open(yol, "rb") as f:
        f.seek(0, 2)
        n = f.tell()
        if offset > n:
            offset = 0
        f.seek(offset)
        veri = f.read()
    # satir sonunda kesilmis olabilir: son tam satira kadar al
    son_nl = veri.rfind(b"\n")
    if son_nl < 0:
        return [], offset
    yeni_offset = offset + son_nl + 1
    for ln in veri[:son_nl].decode("utf-8", errors="replace").splitlines():
        ln = ln.strip().lstrip("\ufeff")
        if not ln:
            continue
        try:
            sonuclar.append(json.loads(ln))
        except Exception:
            pass
    return sonuclar, yeni_offset


def bekleyen_sayisi(conn):
    """Bu bilgisayardan gonderilip botun henuz cevaplamadigi islem sayisi (kayit + bot islemleri)."""
    try:
        a = conn.execute("SELECT COUNT(*) FROM kayitlar WHERE bekleyen_islem IS NOT NULL").fetchone()[0]
        b = conn.execute("SELECT COUNT(*) FROM islem_sonuclari WHERE durum='bekliyor'").fetchone()[0]
        return a + b
    except Exception:
        return 0


def bot_islemi(ayar, conn, op, deger, kullanici, ozet):
    """Super adminin bot komutlari da kuyruktan gider; sonucu islem_sonuclari tablosunda izlenir."""
    qid = ekle(ayar, op, "", "", {}, deger, kullanici, "")
    conn.execute("INSERT OR REPLACE INTO islem_sonuclari(id,zaman,op,ozet,kullanici,durum) VALUES(?,?,?,?,?,'bekliyor')",
                 (qid, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), op, ozet, kullanici))
    return qid
