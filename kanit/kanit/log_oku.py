# -*- coding: utf-8 -*-
"""bot_log.txt'den kaydi ekleyen Telegram kullanicisini cikarir (telegrampanel/app/log_oku.py'nin kopyasi).

Excel satirinda ekleyen yok. Bot her kayitta loga 'Kaydedildi -> [PROJE] [KAT] <link>' yazar;
ondan once ayni kisiden gelen 'Mesaj geldi: <ad> (ID: <id>)' satirlari vardir.
  - kullanicilar.json (+ backups/*/kullanicilar.json) son_kayit_tarihi/son_kayit_proje noktalari KESIN
  - digerleri tuketim modeliyle TAHMINI (en son mesaj yazan, >=3 mesaji olan aday)
  - kayitlar.jsonl (bot yamasi) varsa %100 kesin ve oncelikli
"""
import re, os, json, glob
from datetime import datetime, timedelta

RX_SATIR = re.compile(r"^\ufeff?\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*?)\s*$")
RX_MESAJ = re.compile(r"^Mesaj geldi: (.+) \(ID: (\d+)\)$")
RX_KAYIT = re.compile(r"^Kaydedildi (?:->|\u2192) \[([^\]]+)\] \[([^\]]+)\] (\S+)$")


def _oku_satirlar(yol):
    with open(yol, "r", encoding="utf-8-sig", errors="replace") as f:
        for ln in f:
            yield ln.rstrip("\r\n").lstrip("\ufeff")


def kesin_noktalar(kullanici_json, yedek_klasor):
    kesin = {}
    dosyalar = []
    if kullanici_json and os.path.exists(kullanici_json):
        dosyalar.append(kullanici_json)
    if yedek_klasor and os.path.isdir(yedek_klasor):
        dosyalar += glob.glob(os.path.join(yedek_klasor, "*", "kullanicilar.json"))
    adlar = {}
    for p in dosyalar:
        try:
            with open(p, encoding="utf-8-sig") as f:
                d = json.load(f)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for uid, u in d.items():
            if not isinstance(u, dict):
                continue
            ad = u.get("username") or u.get("first_name") or ""
            if ad:
                adlar[str(uid)] = ad
            t, pr = u.get("son_kayit_tarihi"), u.get("son_kayit_proje")
            if t and pr:
                kesin[f"{t}|{str(pr).upper()}"] = str(uid)
    return kesin, adlar


def kayitlar_jsonl(yol):
    """Bot yamasinin yazdigi kesin kayitlar: link -> {zaman, proje, kategori, kat_kodu, personel, uyeid, anaid, tip, link, dosya, tg_id, tg_ad, giris}"""
    sonuc = {}
    if not yol or not os.path.exists(yol):
        return sonuc
    for ln in _oku_satirlar(yol):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        link = str(d.get("link") or "")
        if link:
            sonuc[link] = d
        elif d.get("dosya"):
            sonuc[str(d["dosya"])] = d
    return sonuc


def eslestir(log_yol, kullanici_json=None, yedek_klasor=None):
    """-> list of {zaman, proje, kategori, link, ekleyen_id, ekleyen_ad, guven}"""
    if not log_yol or not os.path.exists(log_yol):
        return []
    kesin, adlar = kesin_noktalar(kullanici_json, yedek_klasor)
    tuketilmemis = {}   # uid -> [sira,...]
    kayitlar = []
    sira = 0
    for satir in _oku_satirlar(log_yol):
        m = RX_SATIR.match(satir)
        if not m:
            continue
        sira += 1
        govde = m.group(2)
        mm = RX_MESAJ.match(govde)
        if mm:
            uid = mm.group(2)
            tuketilmemis.setdefault(uid, []).append(sira)
            adlar[uid] = mm.group(1)
            continue
        mk = RX_KAYIT.match(govde)
        if not mk:
            continue
        zaman = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        proje, kat, link = mk.group(1).upper(), mk.group(2).upper(), mk.group(3)
        secilen, guven = None, "yok"
        for d in range(0, 6):
            k = (zaman - timedelta(seconds=d)).strftime("%Y-%m-%d %H:%M:%S") + "|" + proje
            if k in kesin:
                secilen, guven = kesin.pop(k), "kesin"
                break
        if not secilen:
            adaylar = [(uid, l[-1]) for uid, l in tuketilmemis.items() if len(l) >= 3]
            if not adaylar:
                adaylar = [(uid, l[-1]) for uid, l in tuketilmemis.items() if l]
            if adaylar:
                adaylar.sort(key=lambda x: x[1], reverse=True)
                secilen, guven = adaylar[0][0], "tahmini"
        if secilen and secilen in tuketilmemis:
            tuketilmemis[secilen] = []
        kayitlar.append({"zaman": zaman.strftime("%Y-%m-%d %H:%M:%S"), "proje": proje, "kategori": kat, "link": link,
                         "ekleyen_id": secilen, "ekleyen_ad": adlar.get(secilen, "") if secilen else "", "guven": guven})
    return kayitlar


def link_haritasi(kayitlar, jsonl_kayitlar=None):
    """link kimligi ('tur:kimlik') -> ekleyen bilgisi (jsonl kesin olanlar oncelikli). Bot 'dosya' kayitlari icin
    jsonl'daki dosya adi da 'dosya:<ad>' anahtariyla eklenir (Excel'e Windows yolu yazilmis kayitlar boyle eslesir)."""
    from .excel_oku import link_turu_ve_kimlik
    harita = {}
    for k in kayitlar:
        tur, kimlik = link_turu_ve_kimlik(k["link"])
        if kimlik:
            harita.setdefault(f"{tur}:{kimlik}", k)
    for link, d in (jsonl_kayitlar or {}).items():
        bilgi = {"zaman": d.get("zaman"), "proje": str(d.get("proje", "")).upper(), "kategori": str(d.get("kategori", "")).upper(),
                 "link": link, "ekleyen_id": str(d.get("tg_id") or d.get("ekleyen_id") or ""),
                 "ekleyen_ad": d.get("tg_ad") or d.get("ekleyen_ad") or "", "guven": "kesin"}
        if not bilgi["ekleyen_id"]:
            continue
        tur, kimlik = link_turu_ve_kimlik(link)
        if kimlik:
            harita[f"{tur}:{kimlik}"] = bilgi
        dosya = str(d.get("dosya") or "")
        if dosya:
            harita.setdefault("dosya:" + os.path.basename(dosya.replace("\\", "/")).lower(), bilgi)
    return harita


def son_satir_zamani(log_yol):
    """Logdaki son zaman damgasi (bot canli mi gostergesi icin)"""
    try:
        with open(log_yol, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 65536))
            kuyruk = f.read().decode("utf-8", errors="replace")
        son = None
        for ln in kuyruk.splitlines():
            m = RX_SATIR.match(ln)
            if m:
                son = m.group(1)
        return son
    except Exception:
        return None
