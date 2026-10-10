# -*- coding: utf-8 -*-
"""Panel -> bot is kuyrugu. Panel Excel'e ASLA dogrudan yazmaz; islemi kuyruga ekler,
bot kendi Excel baglantisiyla uygular ve sonucu panel_kuyruk_sonuc.jsonl'a yazar."""
import os, json, uuid, threading
from datetime import datetime

_kilit = threading.Lock()


def kuyruk_yolu(ayar):
    return os.path.join(ayar["BOT_KLASOR"], "panel_kuyruk.jsonl")


def sonuc_yolu(ayar):
    return os.path.join(ayar["BOT_KLASOR"], "panel_kuyruk_sonuc.jsonl")


def ekle(ayar, op, sayfa, link, parmak, deger=None, kullanici=None, anahtar=None):
    kayit = {"id": uuid.uuid4().hex, "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "op": op, "sayfa": sayfa,
             "link": link or "", "parmak": parmak or {}, "deger": deger or {}, "kullanici": kullanici or "", "anahtar": anahtar or ""}
    with _kilit:
        with open(kuyruk_yolu(ayar), "a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    return kayit["id"]


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


def bekleyen_sayisi(ayar):
    try:
        k = sum(1 for _ in open(kuyruk_yolu(ayar), encoding="utf-8")) if os.path.exists(kuyruk_yolu(ayar)) else 0
        s = sum(1 for _ in open(sonuc_yolu(ayar), encoding="utf-8")) if os.path.exists(sonuc_yolu(ayar)) else 0
        return max(0, k - s)
    except Exception:
        return 0
