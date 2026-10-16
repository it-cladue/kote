# -*- coding: utf-8 -*-
"""Windows surumunden tek seferlik gecis: Excel kitabi + bot durum dosyalari + eski panel.db + gorsel klasorleri -> veritabani.

Kullanim (komut satiri: python -m kanit ice-aktar ...):
    rapor = calistir(conn, ayar, excel=..., bot_klasor=..., panel_db=[...], gorseller=[...], kuru=True)   # deneme: hicbir sey yazmaz
    rapor = calistir(conn, ayar, ..., kuru=False)                                                          # uygula
    rapor = excel_ekle(conn, ayar, excel=...)                                                              # sonradan toplu duzeltme kitabi
    print(rapor_metni(rapor))

Kurallar:
  - kayitlar tablosuna yalnizca db.kayit_ekle / kt_ayarla / kayit_sil ile yazilir (kim='aktarim', kaynak='excel').
  - Ikinci calisma guvenlidir: eski_anahtar (Excel sayfa + link kimligi, excel_oku.anahtar_uret) ile eslesen satirlar atlanir.
  - Birebir tekrarlar (ayni proje+personel+uye+ana+link, tarih farki <= 2 dk) yalnizca RAPORLANIR; hicbir sey kendiliginden silinmez.
  - Onay bilgisi: Excel H sutunu; eski panel.db'de ayni anahtar icin panelden onay (kt_kaynak='panel', kt_kim) varsa o kim yazilir.
  - Ekleyen: kayitlar.jsonl (kesin) > bot_log.txt + kullanicilar.json eslestirmesi (kesin/tahmini) > yok.
  - Gorseller: gyazo id (indeks.csv) ya da dosya adi (Excel'e yazilmis Windows yolu / OneDrive dosya adi) ile eslesir;
    VERI/gorseller/<PROJE>/ altina KOPYALANIR (ustune yazilmaz, gorsel oldugu dogrulanir), kayda gorsel_dosya yazilir.
Hiz: openpyxl read_only ile 6 MB kitap birkac saniyede okunur; satir basina db.kayit_ekle (kendi islemi) ~0.3-0.5 ms (WAL, synchronous=NORMAL).
"""
import os, re, csv, json, time, sqlite3
from datetime import datetime, timedelta
from . import db, excel_oku, log_oku, gorsel
from . import normalle as N

KIM = "aktarim"
MUKERRER_DK = 2
LISTE_SINIRI = 300          # raporda tutulan ornek satir sayisi (dosya raporunda tamami yazilir)
RX_DOSYA_TARIH = re.compile(r"(\d{4})-(\d{2})-(\d{2})[_ T-](\d{2})-(\d{2})-(\d{2})")
_ID_BOL = re.compile(r"(?=(?<![0-9])[0-9]{8,12}\|)")   # yapisik onaylilar/engellenenler satirlarini ID basindan boler
AKISLAR = ("tek_uye", "ark_ana", "ana_only", "sessiz_tip")


def _simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def foto_tarihi(dosya_adi):
    """Botun dosya adi kalibi KATEGORI_yyyy-MM-dd_HH-mm-ss_... -> 'yyyy-MM-dd HH:mm:ss' | None"""
    m = RX_DOSYA_TARIH.search(os.path.basename(str(dosya_adi or "")))
    if not m:
        return None
    try:
        return datetime(*[int(x) for x in m.groups()]).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


# ==================== bot klasoru (durum dosyalari) ====================
def _satirlar(yol):
    """id|... satirlari; satir sonu olmadan yapismis kayitlar ID basindan bolunur (bot_yonetim._ID_BOL)."""
    if not yol or not os.path.exists(yol):
        return []
    with open(yol, encoding="utf-8-sig", errors="replace") as f:
        ham = f.read()
    out = []
    for ln in ham.splitlines():
        if not ln.strip():
            continue
        for p in _ID_BOL.split(ln):
            if p.strip():
                out.append(p.strip())
    return out


def _json_oku(yol, varsayilan):
    if not yol or not os.path.exists(yol):
        return varsayilan
    try:
        with open(yol, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return varsayilan


def bot_klasoru_oku(klasor):
    """-> {kullanicilar, onaylilar, engellenenler, denemeler, kategoriler, panel_kullanicilar, jsonl, log, dosyalar}"""
    k = {"kullanicilar": {}, "onaylilar": [], "engellenenler": [], "denemeler": {}, "kategoriler": [], "panel_kullanicilar": [],
         "jsonl": {}, "log": [], "dosyalar": {}}
    if not klasor or not os.path.isdir(klasor):
        return k
    y = lambda ad: os.path.join(klasor, ad)
    for ad in ("kullanicilar.json", "onaylilar.txt", "engellenenler.txt", "denemeler.txt", "kategoriler.json", "kayitlar.jsonl", "bot_log.txt", "panel_kullanicilar.json"):
        k["dosyalar"][ad] = os.path.exists(y(ad))
    d = _json_oku(y("kullanicilar.json"), {})
    if isinstance(d, dict):
        for uid, u in d.items():
            if isinstance(u, dict) and str(uid).strip():
                k["kullanicilar"][str(uid).strip()] = u
    for ln in _satirlar(y("onaylilar.txt")):
        p = [x.strip() for x in ln.split("|")]
        if p[0]:
            k["onaylilar"].append({"id": p[0], "ad": p[1] if len(p) > 1 else "", "tarih": p[2] if len(p) > 2 else ""})
    for ln in _satirlar(y("engellenenler.txt")):
        p = [x.strip() for x in ln.split("|")]
        if p[0]:
            k["engellenenler"].append({"id": p[0], "kim": p[1] if len(p) > 1 else "", "tarih": p[2] if len(p) > 2 else "", "sebep": p[3] if len(p) > 3 else ""})
    for ln in _satirlar(y("denemeler.txt")):
        p = [x.strip() for x in ln.split("|")]
        if len(p) >= 2 and p[0]:
            try:
                k["denemeler"][p[0]] = int(p[1])
            except ValueError:
                pass
    kat = _json_oku(y("kategoriler.json"), [])
    if isinstance(kat, list):
        for it in kat:
            if not isinstance(it, dict):
                continue
            code = N.kucuk(str(it.get("code") or "")).strip()
            mode = str(it.get("mode") or "tek_uye")
            if code and mode in AKISLAR:
                k["kategoriler"].append({"code": code, "label": str(it.get("label") or code.upper()).strip(), "mode": mode})
    pk = _json_oku(y("panel_kullanicilar.json"), {})
    if isinstance(pk, dict) and isinstance(pk.get("kullanicilar"), list):
        k["panel_kullanicilar"] = [u for u in pk["kullanicilar"] if isinstance(u, dict) and u.get("kullanici_adi")]
    k["jsonl"] = log_oku.kayitlar_jsonl(y("kayitlar.jsonl"))
    k["log"] = log_oku.eslestir(y("bot_log.txt"), y("kullanicilar.json"), y("backups"))
    return k


# ==================== eski panel.db ====================
def panel_db_oku(yollar):
    """Eski Windows paneli (telegrampanel) panel.db dosyalari -> ({anahtar: {kt, kt_kim, kt_zaman, kt_kaynak, silindi, silen, silme_zamani, silme_nedeni}}, [kullanici])
    Birden fazla dosyada ayni anahtar: panelden onay/silme bilgisi tasiyan kazanir."""
    bilgi, kullanicilar, gorulen_k = {}, [], set()
    for yol in yollar or []:
        if not yol or not os.path.exists(yol):
            continue
        try:
            c = sqlite3.connect(f"file:{os.path.abspath(yol)}?mode=ro", uri=True)
            c.row_factory = sqlite3.Row
        except sqlite3.Error:
            continue
        try:
            tablolar = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if "kayitlar" in tablolar:
                kol = {r[1] for r in c.execute("PRAGMA table_info(kayitlar)").fetchall()}
                nedenler = {}
                if "denetim" in tablolar:
                    dk = {r[1] for r in c.execute("PRAGMA table_info(denetim)").fetchall()}
                    if {"anahtar", "islem", "yeni"} <= dk:
                        for r in c.execute("SELECT anahtar, yeni FROM denetim WHERE islem='sil' ORDER BY id").fetchall():
                            if r["anahtar"] and r["yeni"]:
                                nedenler[r["anahtar"]] = str(r["yeni"])[:200]
                for r in c.execute("SELECT * FROM kayitlar").fetchall():
                    a = r["anahtar"]
                    if not a:
                        continue
                    g = lambda k, v=None: (r[k] if k in kol else v)
                    yeni = {"kt": int(g("kt", 0) or 0), "kt_kim": str(g("kt_kim") or ""), "kt_zaman": g("kt_zaman"), "kt_kaynak": str(g("kt_kaynak") or ""),
                            "silindi": int(g("silindi", 0) or 0), "silen": str(g("silen") or ""), "silme_zamani": g("silme_zamani"),
                            "silme_nedeni": nedenler.get(a, ""), "dosya": os.path.basename(yol)}
                    eski = bilgi.get(a)
                    if eski is None or _panel_agirlik(yeni) >= _panel_agirlik(eski):
                        bilgi[a] = yeni
            if "panel_kullanicilari" in tablolar:
                for r in c.execute("SELECT * FROM panel_kullanicilari").fetchall():
                    d = dict(r)
                    ad = N.kucuk(str(d.get("kullanici_adi") or "")).strip()
                    if ad and ad not in gorulen_k and d.get("sifre_hash"):
                        gorulen_k.add(ad)
                        kullanicilar.append({"kullanici_adi": ad, "ad": d.get("ad") or ad, "sifre_hash": d["sifre_hash"], "yetki": d.get("yetki") or "",
                                             "aktif": d.get("aktif", 1), "sifre_degistir": d.get("sifre_degistir", 0), "olusturma": d.get("olusturma"), "olusturan": "panel.db"})
        finally:
            c.close()
    return bilgi, kullanicilar


def _panel_agirlik(b):
    return (1 if b["silindi"] else 0) + (2 if (b["kt"] and b["kt_kaynak"] == "panel" and b["kt_kim"]) else 0)


# ==================== gorsel klasorleri ====================
class GorselKaynagi:
    """Eski gorsel klasorleri (gorseller/<PROJE>/*.jpg, ekran_goruntuleri/, telegram_gorseller/; her birinde indeks.csv olabilir).
    gyazo: gyazo id -> dosya yolu; adlar: dosya adi (kucuk) -> dosya yolu; tum: butun gorsel dosyalari."""

    def __init__(self):
        self.gyazo, self.adlar, self.tum, self.kullanilan, self.klasorler = {}, {}, set(), set(), []
        self._gecerli = {}

    def gecerli_mi(self, yol):
        """Dosya gercekten gorsel mi (ilk baytlar)? Sonuc onbellege alinir."""
        if yol not in self._gecerli:
            try:
                with open(yol, "rb") as f:
                    self._gecerli[yol] = gorsel.gorsel_mi(f.read(12))
            except OSError:
                self._gecerli[yol] = False
        return self._gecerli[yol]

    def tara(self, klasor):
        if not klasor or not os.path.isdir(klasor):
            return
        kok = os.path.abspath(klasor)
        self.klasorler.append(kok)
        for dizin, _altlar, dosyalar in os.walk(kok):
            for ad in dosyalar:
                if ad.lower().endswith(gorsel.GORSEL_UZANTILAR):
                    yol = os.path.join(dizin, ad)
                    self.tum.add(yol)
                    self.adlar.setdefault(ad.lower(), yol)
        indeks = os.path.join(kok, "indeks.csv")
        if os.path.exists(indeks):
            self._indeks_oku(indeks, kok)

    def _indeks_oku(self, yol, kok):
        try:
            with open(yol, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    gid = (r.get("GyazoId") or "").strip().lower()
                    ad = os.path.basename(((r.get("DosyaAdi") or "") or (r.get("DosyaYolu") or "")).replace("\\", "/")).strip()
                    proje = (r.get("Proje") or "").strip()
                    hedef = None
                    for aday in (os.path.join(kok, proje.upper(), ad), os.path.join(kok, proje, ad), os.path.join(kok, ad), self.adlar.get(ad.lower())):
                        if ad and aday and os.path.isfile(aday) and gorsel.icinde_mi(aday, kok):
                            hedef = aday
                            break
                    if not hedef:
                        continue
                    if gid and re.fullmatch(r"[0-9a-f]{32}", gid):
                        self.gyazo.setdefault(gid, hedef)
                    self.adlar.setdefault(ad.lower(), hedef)
        except Exception:
            pass

    def bul(self, tur, kimlik):
        """Excel satirinin linkine gore kaynak dosya -> yol | None"""
        if not kimlik:
            return None
        yol = None
        if tur == "gyazo":
            yol = self.gyazo.get(kimlik)
        elif tur in ("dosya", "onedrive"):
            yol = self.adlar.get(os.path.basename(kimlik.replace("\\", "/")).lower())
        return yol if yol and self.gecerli_mi(yol) else None


def gorsel_klasorlerini_tara(klasorler):
    g = GorselKaynagi()
    for k in klasorler or []:
        g.tara(k)
    return g


def _gorsel_kopyala(gorseller_kok, proje, kaynak_yol, onbellek):
    """Kaynak dosyayi VERI/gorseller/<PROJE>/<ad> olarak kopyalar (ustune yazmaz; ayni boyutta varsa yeniden kullanir). -> goreli yol | None"""
    anahtar = (proje, kaynak_yol)
    if anahtar in onbellek:
        return onbellek[anahtar]
    sonuc = None
    try:
        with open(kaynak_yol, "rb") as f:
            baytlar = f.read()
        if gorsel.gorsel_mi(baytlar):
            ad = os.path.basename(kaynak_yol)
            pk = gorsel.dosya_parcasi(proje).upper() or "DIGER"
            hedef = os.path.join(gorseller_kok, pk, ad)
            if os.path.exists(hedef) and os.path.getsize(hedef) == len(baytlar):
                sonuc = f"{pk}/{ad}"
            else:
                sonuc = gorsel.kaydet(gorseller_kok, pk, baytlar, ad)
    except (OSError, ValueError):
        sonuc = None
    onbellek[anahtar] = sonuc
    return sonuc


# ==================== kaynaklari hazirla ====================
def hazirla(excel=None, bot_klasor=None, panel_db=(), gorseller=()):
    """Tum kaynaklari bellege okur (yazmaz). -> kaynak dict"""
    k = {"sayfalar": {}, "excel": excel or "", "bot": bot_klasoru_oku(bot_klasor), "panel": {}, "panel_kullanicilar": [], "gorsel": gorsel_klasorlerini_tara(gorseller)}
    if excel:
        k["sayfalar"] = excel_oku.oku(excel)
    k["harita"] = log_oku.link_haritasi(k["bot"]["log"], k["bot"]["jsonl"])
    k["panel"], k["panel_kullanicilar"] = panel_db_oku(panel_db)
    return k


def _mukerrerler(satirlar):
    """[(sayfa, satir dict)] -> ayni proje+personel+uye+ana+link ve tarih farki <= MUKERRER_DK dk olan ciftler."""
    gruplar = {}
    for sayfa, s in satirlar:
        if not s["tarih"]:
            continue
        g = (excel_oku.sayfa_projesi(sayfa), N.normalle(s["personel"]), N.normalle(s["uye"]), N.normalle(s["ana"]), N.normalle(s["link"]))
        gruplar.setdefault(g, []).append((sayfa, s))
    out = []
    for g, liste in gruplar.items():
        if len(liste) < 2:
            continue
        liste.sort(key=lambda x: x[1]["tarih"])
        for i in range(len(liste) - 1):
            a, b = liste[i], liste[i + 1]
            ta, tb = datetime.strptime(a[1]["tarih"], "%Y-%m-%d %H:%M:%S"), datetime.strptime(b[1]["tarih"], "%Y-%m-%d %H:%M:%S")
            if tb - ta <= timedelta(minutes=MUKERRER_DK):
                out.append({"proje": g[0], "sayfa1": a[0], "satir1": a[1]["satir"], "sayfa2": b[0], "satir2": b[1]["satir"],
                            "personel": a[1]["personel"], "uye": a[1]["uye"], "ana": a[1]["ana"], "link": a[1]["link"], "tarih1": a[1]["tarih"], "tarih2": b[1]["tarih"]})
    return out


# ==================== cekirdek ====================
def calistir(conn, ayar, excel=None, bot_klasor=None, panel_db=(), gorseller=(), kuru=True, kim=KIM, tur=None, kaynak=None):
    """Tam aktarim. kuru=True: hicbir sey yazilmaz, yalnizca rapor. -> rapor dict (rapor_metni ile okunur hale gelir)."""
    t0 = time.time()
    tur = tur or ("kuru" if kuru else "uygula")
    k = kaynak or hazirla(excel, bot_klasor, panel_db, gorseller)
    gorseller_kok = ayar["GORSELLER"]
    r = {"tur": tur, "kuru": bool(kuru), "zaman": _simdi(), "excel": k["excel"], "bot_klasor": bot_klasor or "", "panel_db": [p for p in (panel_db or []) if p],
         "gorsel_klasorleri": list(k["gorsel"].klasorler), "bot_dosyalari": k["bot"]["dosyalar"],
         "sayfalar": {}, "toplam_satir": 0, "yeni": 0, "atlandi": 0, "kt_guncellenen": 0, "silinen": 0, "hata": [],
         "tarih_hatali": [], "tarihsiz": 0, "mukerrer": [], "gorselsiz": 0, "gorselli": 0, "gorsel_kopyalanan": 0, "gorsel_satirsiz": [], "gorsel_satirsiz_sayi": 0,
         "ekleyen": {"kesin": 0, "tahmini": 0, "yok": 0}, "kt": {"excel": 0, "panel": 0, "toplam": 0}, "panel_eslesen": 0,
         "yeni_projeler": [], "cennet_kt": any(excel_oku.sayfa_projesi(s) == "CENNET" for s in k["sayfalar"]),
         "kategoriler": {"yeni": [], "guncellenen": []}, "kullanicilar": {"yeni": [], "mevcut": [], "hatali": []},
         "tg": {"defter": len(k["bot"]["kullanicilar"]), "onayli": len(k["bot"]["onaylilar"]), "engelli": len(k["bot"]["engellenenler"]), "deneme": len(k["bot"]["denemeler"]), "yazilan": 0},
         "log_kayitlari": len(k["bot"]["log"]), "jsonl_kayitlari": len(k["bot"]["jsonl"]), "panel_db_kayitlari": len(k["panel"])}
    mevcut = db.eski_anahtarlar(conn)
    mevcut_projeler = set(db.proje_kodlari(conn, aktif=False))
    gk = k["gorsel"]
    kopya_onbellek = {}
    tum_satirlar = []

    for sayfa, satirlar in k["sayfalar"].items():
        proje = excel_oku.sayfa_projesi(sayfa)
        sr = {"proje": proje, "satir": len(satirlar), "yeni": 0, "atlandi": 0, "kt_guncellenen": 0, "tarih_hatali": 0, "gorselsiz": 0, "gorselli": 0, "silinen": 0}
        r["sayfalar"][sayfa] = sr
        r["toplam_satir"] += len(satirlar)
        if proje not in mevcut_projeler:
            if proje not in r["yeni_projeler"]:
                r["yeni_projeler"].append(proje)
            if not kuru:
                db.proje_ekle_yoksa(conn, proje, kim=kim)
            mevcut_projeler.add(proje)
        for s in satirlar:
            tum_satirlar.append((sayfa, s))
            tur_l, kimlik = excel_oku.link_turu_ve_kimlik(s["link"])
            ek = k["harita"].get(f"{tur_l}:{kimlik}") if kimlik else None
            pb = k["panel"].get(s["anahtar"])
            if pb:
                r["panel_eslesen"] += 1
            kaynak_gorsel = gk.bul(tur_l, kimlik)
            if kaynak_gorsel:
                gk.kullanilan.add(kaynak_gorsel)
                sr["gorselli"] += 1
            else:
                sr["gorselsiz"] += 1
            if s["tarih_ham"] and not s["tarih"]:
                sr["tarih_hatali"] += 1
                if len(r["tarih_hatali"]) < LISTE_SINIRI:
                    r["tarih_hatali"].append({"sayfa": sayfa, "satir": s["satir"], "ham": s["tarih_ham"]})
            foto = foto_tarihi(kaynak_gorsel) if kaynak_gorsel else None
            tarih = s["tarih"] or (ek["zaman"] if ek and ek.get("zaman") else None) or foto
            if not tarih:
                r["tarihsiz"] += 1
            guven = ek["guven"] if ek and ek.get("ekleyen_id") else "yok"
            r["ekleyen"][guven if guven in r["ekleyen"] else "yok"] += 1
            kt = 1 if s["kt"] else 0
            kt_kim, kt_kaynak, kt_zaman = "", "excel" if kt else "", None
            if pb and pb["kt"] and pb["kt_kaynak"] == "panel" and pb["kt_kim"]:
                kt, kt_kim, kt_kaynak, kt_zaman = 1, pb["kt_kim"], "panel", pb["kt_zaman"]
            if kt:
                r["kt"]["toplam"] += 1
                r["kt"][kt_kaynak] += 1
            var = mevcut.get(s["anahtar"])
            if var:
                sr["atlandi"] += 1
                r["atlandi"] += 1
                # excel_ekle: sonradan gelen kitapta onay isaretlenmisse uygula
                if tur == "excel_ekle" and kt and not var["kt"] and not var["silindi"]:
                    sr["kt_guncellenen"] += 1
                    r["kt_guncellenen"] += 1
                    if not kuru:
                        db.kt_ayarla(conn, var["id"], 1, kt_kim or kim, kaynak=kt_kaynak or "excel")
                continue
            sr["yeni"] += 1
            r["yeni"] += 1
            if pb and pb["silindi"]:
                sr["silinen"] += 1
                r["silinen"] += 1
            if kuru:
                continue
            gorsel_dosya = _gorsel_kopyala(gorseller_kok, proje, kaynak_gorsel, kopya_onbellek) if kaynak_gorsel else None
            if gorsel_dosya and (proje, kaynak_gorsel) not in r.setdefault("_kopyalanan", set()):
                r["_kopyalanan"].add((proje, kaynak_gorsel))
            alanlar = {"proje": proje, "kategori": s["kategori"], "personel": s["personel"], "uye_id": s["uye"], "ana_uye_id": s["ana"], "tip": s["tip"],
                       "link": s["link"], "gorsel2": s["gorsel2"], "aciklama": s["aciklama"], "ek_not": s["ek_not"],
                       "giris_tipi": "yazili" if (tur_l == "metin" and s["link"] and not kaynak_gorsel) else "resim",
                       "lead_id": s["link"][:50] if tur_l == "metin" else "",
                       "tarih": tarih, "tarih_ham": s["tarih_ham"], "foto_tarih": foto,
                       "kt": kt, "kt_kim": kt_kim, "kt_zaman": kt_zaman, "kt_kaynak": kt_kaynak,
                       "ekleyen_tg_id": (ek.get("ekleyen_id") or "") if ek else "", "ekleyen_ad": (ek.get("ekleyen_ad") or "") if ek else "", "ekleyen_guven": guven,
                       "gorsel_dosya": gorsel_dosya or "", "eski_sayfa": sayfa, "eski_satir": s["satir"], "eski_anahtar": s["anahtar"]}
            try:
                kayit = db.kayit_ekle(conn, alanlar, kim=kim, kaynak="excel", bildir=False)
                mevcut[s["anahtar"]] = {"id": kayit["id"], "kt": kayit["kt"], "silindi": 0}
                if pb and pb["silindi"]:
                    db.kayit_sil(conn, kayit["id"], pb["silen"] or kim, neden=pb["silme_nedeni"] or "eski panelde silinmis (aktarim)")
                    mevcut[s["anahtar"]]["silindi"] = 1
            except Exception as e:
                r["hata"].append(f"{sayfa}!{s['satir']}: {type(e).__name__}: {e}")
    r["gorsel_kopyalanan"] = len(r.pop("_kopyalanan", set()))
    r["gorselli"] = sum(x["gorselli"] for x in r["sayfalar"].values())
    r["gorselsiz"] = sum(x["gorselsiz"] for x in r["sayfalar"].values())
    r["mukerrer"] = _mukerrerler(tum_satirlar)
    satirsiz = sorted(gk.tum - gk.kullanilan)
    r["gorsel_satirsiz_sayi"] = len(satirsiz)
    r["gorsel_satirsiz"] = [_goreli(p, gk.klasorler) for p in satirsiz[:LISTE_SINIRI]]

    # ---- bot defteri, kategoriler, panel kullanicilari (excel_ekle modunda dokunulmaz) ----
    if tur != "excel_ekle":
        _tg_aktar(conn, k["bot"], r, kuru)
        _kategori_aktar(conn, k["bot"]["kategoriler"], r, kuru, kim)
        _kullanici_aktar(conn, k["bot"]["panel_kullanicilar"] + k["panel_kullanicilar"], r, kuru, kim)
    r["sure_sn"] = round(time.time() - t0, 2)
    r["satir_sn"] = round(r["yeni"] / r["sure_sn"]) if r["sure_sn"] > 0 and not kuru else None
    try:
        kayit_r = {kk: v for kk, v in r.items() if kk not in ("tarih_hatali", "mukerrer", "gorsel_satirsiz")}
        kayit_r.update({"tarih_hatali_sayi": len(r["tarih_hatali"]), "mukerrer_sayi": len(r["mukerrer"])})
        db.ice_aktarim_yaz(conn, tur, kayit_r, kim)
        if not kuru and (r["yeni"] or r["kt_guncellenen"]):
            db.ayar_yaz(conn, "son_degisiklik", _simdi())
    except Exception as e:
        r["hata"].append(f"rapor yazilamadi: {e}")
    return r


def _goreli(yol, klasorler):
    for k in klasorler:
        try:
            if os.path.commonpath([yol, k]) == k:
                return os.path.join(os.path.basename(k), os.path.relpath(yol, k)).replace("\\", "/")
        except ValueError:
            pass
    return os.path.basename(yol)


def _tg_aktar(conn, bot, r, kuru):
    idler = set(bot["kullanicilar"]) | {o["id"] for o in bot["onaylilar"]} | {e["id"] for e in bot["engellenenler"]} | set(bot["denemeler"])
    idler = {i for i in idler if i and i.isdigit()}
    r["tg"]["yazilan"] = len(idler)
    if kuru or not idler:
        return
    onay = {o["id"]: o for o in bot["onaylilar"]}
    engel = {e["id"]: e for e in bot["engellenenler"]}
    with db.islem(conn):
        for tid in sorted(idler):
            alan = {}
            u = bot["kullanicilar"].get(tid)
            if u:
                for kk, hedef in (("username", "username"), ("first_name", "first_name"), ("last_seen", "last_seen"), ("status", "status"),
                                  ("son_kayit_tarihi", "son_kayit_tarihi"), ("son_kayit_proje", "son_kayit_proje"), ("son_kayit_kategori", "son_kayit_kategori")):
                    if u.get(kk) not in (None, ""):
                        alan[hedef] = str(u[kk])
                try:
                    alan["kayit_sayisi"] = int(u.get("kayit_sayisi") or 0)
                except (TypeError, ValueError):
                    pass
                for kk in ("proje_sayilari", "kategori_sayilari"):
                    if isinstance(u.get(kk), dict):
                        alan[kk] = {str(a): int(b) for a, b in u[kk].items() if str(b).lstrip("-").isdigit()}
            if tid in onay:
                alan.update({"onayli": 1, "onay_tarihi": onay[tid]["tarih"] or None, "onay_adi": onay[tid]["ad"]})
            if tid in engel:
                alan.update({"engelli": 1, "engel_tarihi": engel[tid]["tarih"] or None, "engel_sebep": engel[tid]["sebep"], "engelleyen": engel[tid]["kim"]})
            if tid in bot["denemeler"]:
                alan["deneme"] = bot["denemeler"][tid]
            db.tg_guncelle(conn, tid, **alan)
        db.denetim_yaz(conn, KIM, "ice_aktar_tg", yeni=f"{len(idler)} telegram kullanicisi")


def _kategori_aktar(conn, kategoriler, r, kuru, kim):
    mevcut = {kk["kod"]: kk for kk in db.kategoriler(conn, aktif=False)}
    for it in kategoriler:
        m = mevcut.get(it["code"])
        if m and m["etiket"] == it["label"] and m["akis"] == it["mode"] and m["aktif"]:
            continue
        (r["kategoriler"]["guncellenen"] if m else r["kategoriler"]["yeni"]).append(it["code"])
        if not kuru:
            h = db.kategori_kaydet(conn, it["code"], it["label"], it["mode"], kim=kim)
            if h:
                r["hata"].append(f"kategori {it['code']}: {h}")


def _kullanici_aktar(conn, kullanicilar, r, kuru, kim):
    gorulen = set()
    for u in kullanicilar:
        ad = N.kucuk(str(u.get("kullanici_adi") or "")).strip()
        if not ad or ad in gorulen:
            continue
        gorulen.add(ad)
        if db.kullanici_bul(conn, ad):
            r["kullanicilar"]["mevcut"].append(ad)
            continue
        h = u.get("sifre_hash") or ""
        if not db.kullanici_adi_gecerli(ad) or not h or ":" not in h:
            r["kullanicilar"]["hatali"].append(ad)
            continue
        r["kullanicilar"]["yeni"].append(ad)
        if kuru:
            continue
        try:
            db.kullanici_ekle(conn, ad, str(u.get("yetki") or ""), None, gorunen_ad=str(u.get("ad") or ad), olusturan=str(u.get("olusturan") or kim),
                              sifre_degistir=bool(u.get("sifre_degistir")), sifre_hash=h)
            if not u.get("aktif", 1):
                db.kullanici_guncelle(conn, ad, kim=kim, aktif=0)
        except Exception as e:
            r["hata"].append(f"kullanici {ad}: {e}")


def excel_ekle(conn, ayar, excel, kuru=False, kim=KIM, gorseller=()):
    """Sonradan gelen (duzeltilmis) kitap: ayni eslestirme; yalnizca YENI satirlar eklenir ve Excel'de onaylanmis olup
    veritabaninda onaysiz olanlar KT yapilir. Silme / alan degisikligi uygulanmaz. -> rapor"""
    return calistir(conn, ayar, excel=excel, gorseller=gorseller, kuru=kuru, kim=kim, tur="excel_ekle")


# ==================== okunur rapor ====================
def rapor_metni(r, tam=False):
    """Turkce (ASCII) ozet. tam=True: listelerin tamami (dosyaya yazmak icin)."""
    L = []
    bas = {"kuru": "DENEME (kuru) - hicbir sey yazilmadi", "uygula": "UYGULAMA", "excel_ekle": "EK KITAP (excel-ekle)"}.get(r["tur"], r["tur"])
    L.append(f"=== Ice aktarim raporu: {bas} === {r['zaman']}  sure {r.get('sure_sn', 0)} sn" + (f"  (~{r['satir_sn']} satir/sn)" if r.get("satir_sn") else ""))
    L.append(f"Excel: {r['excel'] or '-'}   bot klasoru: {r['bot_klasor'] or '-'}   eski panel.db: {', '.join(r['panel_db']) or '-'}")
    L.append(f"Gorsel klasorleri: {', '.join(r['gorsel_klasorleri']) or '-'}")
    if r["bot_klasor"]:
        L.append("Bot dosyalari: " + ", ".join(f"{a}={'var' if v else 'YOK'}" for a, v in r["bot_dosyalari"].items()))
    L.append("")
    L.append("Sayfalar (satir / yeni / atlanan / tarih hatasi / gorselli / gorselsiz / eski panelde silinmis):")
    for sayfa, s in r["sayfalar"].items():
        L.append(f"  {sayfa:<12} -> {s['proje']:<7} {s['satir']:>6} / {s['yeni']:>6} / {s['atlandi']:>6} / {s['tarih_hatali']:>5} / {s['gorselli']:>6} / {s['gorselsiz']:>6} / {s['silinen']:>4}"
                 + (f"   KT guncellenen: {s['kt_guncellenen']}" if s.get("kt_guncellenen") else ""))
    L.append(f"Toplam satir {r['toplam_satir']}: yeni {r['yeni']}, atlanan (zaten var) {r['atlandi']}, KT guncellenen {r['kt_guncellenen']}, silinmis olarak isaretlenecek {r['silinen']}")
    L.append(f"'cennet kt' sayfasi: {'VAR (CENNET projesi olarak aktarilir)' if r['cennet_kt'] else 'yok'}" + (f"   yeni proje(ler): {', '.join(r['yeni_projeler'])}" if r["yeni_projeler"] else ""))
    L.append("")
    L.append(f"Tarih: cozulemeyen {len(r['tarih_hatali'])} (asagida), tarihsiz (log/gorselden de bulunamadi, aktarim zamani yazilir) {r['tarihsiz']}")
    for t in (r["tarih_hatali"] if tam else r["tarih_hatali"][:20]):
        L.append(f"  {t['sayfa']}!{t['satir']}: '{t['ham']}'")
    if not tam and len(r["tarih_hatali"]) > 20:
        L.append(f"  ... {len(r['tarih_hatali']) - 20} satir daha (--rapor dosyasinda tamami)")
    L.append("")
    L.append(f"Birebir tekrar (ayni proje+personel+uye+ana+link, tarih farki <= {MUKERRER_DK} dk) - ELLE kontrol icin, silinmez: {len(r['mukerrer'])}")
    for m in (r["mukerrer"] if tam else r["mukerrer"][:20]):
        L.append(f"  {m['proje']}: {m['sayfa1']}!{m['satir1']} ({m['tarih1']}) ~ {m['sayfa2']}!{m['satir2']} ({m['tarih2']})  personel={m['personel']} uye={m['uye']} ana={m['ana']} link={m['link'][:60]}")
    if not tam and len(r["mukerrer"]) > 20:
        L.append(f"  ... {len(r['mukerrer']) - 20} cift daha")
    L.append("")
    L.append(f"Gorsel: eslesen satir {r['gorselli']}, gorselsiz satir {r['gorselsiz']}, kopyalanan dosya {r['gorsel_kopyalanan']}, satiri olmayan gorsel {r['gorsel_satirsiz_sayi']}")
    for g in (r["gorsel_satirsiz"] if tam else r["gorsel_satirsiz"][:10]):
        L.append(f"  satirsiz: {g}")
    L.append(f"Ekleyen: kesin {r['ekleyen']['kesin']}, tahmini {r['ekleyen']['tahmini']}, yok {r['ekleyen']['yok']}   (bot_log {r['log_kayitlari']} kayit, kayitlar.jsonl {r['jsonl_kayitlari']} satir)")
    L.append(f"KT: toplam {r['kt']['toplam']} (Excel {r['kt']['excel']}, eski panelden kim bilgisiyle {r['kt']['panel']});  eski panel.db ile eslesen satir {r['panel_eslesen']} / {r['panel_db_kayitlari']}")
    L.append("")
    if r["tur"] != "excel_ekle":
        L.append(f"Telegram defteri: {r['tg']['defter']} kullanici, {r['tg']['onayli']} onayli, {r['tg']['engelli']} engelli, {r['tg']['deneme']} deneme sayaci -> {r['tg']['yazilan']} satir yazilir")
        L.append(f"Kategoriler: yeni {', '.join(r['kategoriler']['yeni']) or '-'}; guncellenen {', '.join(r['kategoriler']['guncellenen']) or '-'}")
        L.append(f"Panel kullanicilari: yeni {', '.join(r['kullanicilar']['yeni']) or '-'}; zaten var {', '.join(r['kullanicilar']['mevcut']) or '-'}; hatali (sifre ozeti yok) {', '.join(r['kullanicilar']['hatali']) or '-'}")
    if r["hata"]:
        L.append("")
        L.append(f"HATALAR ({len(r['hata'])}):")
        L.extend("  " + h for h in (r["hata"] if tam else r["hata"][:30]))
    return "\n".join(L)
