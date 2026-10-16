# -*- coding: utf-8 -*-
"""Tek veritabani (SQLite, WAL) ve ORTAK YAZMA ISLEMLERI.

Kural: kayitlar tablosuna bot da, web de, aktarici da YALNIZCA bu modulun fonksiyonlariyla yazar
(kayit_ekle, kayit_guncelle, kt_ayarla, kayit_sil, kayit_geri_al). Boylece her degisiklik:
  1) arsiv tablosuna (dokunulmaz, yalniz ekleme; UPDATE/DELETE tetikleyiciyle yasak) kaydin o anki tam kopyasini yazar,
  2) denetim tablosuna kim/ne zaman/ne satirini yazar,
  3) gerekli bildirimleri uretir.
Satir kimligi kayitlar.id'dir; Excel satir numarasi (eski_sayfa/eski_satir) yalnizca tasinan kayitlarda bilgi olarak durur.
"""
import os, json, sqlite3, threading
from datetime import datetime, timedelta
from . import normalle as N
from . import yetki as Y

SEMA_SURUMU = 1
_kilit = threading.RLock()

SEMA = """
CREATE TABLE IF NOT EXISTS ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT);

CREATE TABLE IF NOT EXISTS projeler (
  kod TEXT PRIMARY KEY, ad TEXT, renk TEXT NOT NULL DEFAULT '#999999', emoji TEXT DEFAULT '',
  sira INTEGER NOT NULL DEFAULT 0, aktif INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kategoriler (
  kod TEXT PRIMARY KEY, etiket TEXT NOT NULL,
  akis TEXT NOT NULL CHECK (akis IN ('tek_uye','ark_ana','ana_only','sessiz_tip')),
  sira INTEGER NOT NULL DEFAULT 0, aktif INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS kayitlar (
  id INTEGER PRIMARY KEY,
  proje TEXT NOT NULL,
  kategori TEXT NOT NULL DEFAULT '',          -- Excel F: etiket (BUYUK)
  kategori_kod TEXT NOT NULL DEFAULT '',
  personel TEXT NOT NULL DEFAULT '',          -- A
  uye_id TEXT NOT NULL DEFAULT '',            -- B
  ana_uye_id TEXT NOT NULL DEFAULT '',        -- C
  tip TEXT NOT NULL DEFAULT '',               -- D  Sessiz / Telesekreter
  link TEXT NOT NULL DEFAULT '',              -- E  gyazo linki, eski onedrive linki, lead id metni...
  link_turu TEXT NOT NULL DEFAULT 'bos',      -- gyazo|dosya|metin|onedrive|bos
  gorsel_dosya TEXT NOT NULL DEFAULT '',      -- gorseller/ altinda goreli yol (sunucuda saklanan gorsel)
  gorsel2 TEXT NOT NULL DEFAULT '',           -- I
  aciklama TEXT NOT NULL DEFAULT '',          -- J
  ek_not TEXT NOT NULL DEFAULT '',            -- Excel'de A..J disinda kalanlar
  giris_tipi TEXT NOT NULL DEFAULT 'resim',   -- resim|yazili
  lead_id TEXT NOT NULL DEFAULT '',
  tarih TEXT,                                 -- G  'yyyy-MM-dd HH:mm:ss' (yerel)
  tarih_ham TEXT NOT NULL DEFAULT '',
  foto_tarih TEXT,
  kt INTEGER NOT NULL DEFAULT 0,              -- H
  kt_kim TEXT NOT NULL DEFAULT '', kt_zaman TEXT, kt_kaynak TEXT NOT NULL DEFAULT '',
  ekleyen_tg_id TEXT NOT NULL DEFAULT '', ekleyen_ad TEXT NOT NULL DEFAULT '',
  ekleyen_guven TEXT NOT NULL DEFAULT 'yok',  -- kesin|tahmini|yok
  kaynak TEXT NOT NULL DEFAULT 'bot',         -- bot|excel|panel
  eski_sayfa TEXT NOT NULL DEFAULT '', eski_satir INTEGER, eski_anahtar TEXT NOT NULL DEFAULT '',
  silindi INTEGER NOT NULL DEFAULT 0, silen TEXT NOT NULL DEFAULT '', silme_zamani TEXT, silme_nedeni TEXT NOT NULL DEFAULT '',
  surum INTEGER NOT NULL DEFAULT 1,
  yorum_sayisi INTEGER NOT NULL DEFAULT 0, son_yorum_zamani TEXT,
  personel_norm TEXT NOT NULL DEFAULT '', uye_norm TEXT NOT NULL DEFAULT '', ana_norm TEXT NOT NULL DEFAULT '', link_norm TEXT NOT NULL DEFAULT '',
  olusturma TEXT NOT NULL, guncelleme TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kayit_proje ON kayitlar(proje, silindi, kt);
CREATE INDEX IF NOT EXISTS ix_kayit_tarih ON kayitlar(tarih);
CREATE INDEX IF NOT EXISTS ix_kayit_personel ON kayitlar(personel_norm);
CREATE INDEX IF NOT EXISTS ix_kayit_uye ON kayitlar(uye_norm);
CREATE INDEX IF NOT EXISTS ix_kayit_ana ON kayitlar(ana_norm);
CREATE INDEX IF NOT EXISTS ix_kayit_link ON kayitlar(link_norm);
CREATE INDEX IF NOT EXISTS ix_kayit_ekleyen ON kayitlar(ekleyen_tg_id);
CREATE INDEX IF NOT EXISTS ix_kayit_eski ON kayitlar(eski_anahtar);

-- ARSIV: eklenen her kaydin her hali. Yalniz ekleme; degistirme ve silme tetikleyiciyle yasak.
CREATE TABLE IF NOT EXISTS arsiv (
  id INTEGER PRIMARY KEY, kayit_id INTEGER NOT NULL, zaman TEXT NOT NULL,
  olay TEXT NOT NULL,                         -- olustur|degistir|kt|sil|geri_al|ice_aktar
  kim TEXT NOT NULL DEFAULT '', veri TEXT NOT NULL  -- kaydin o anki tam kopyasi (JSON)
);
CREATE INDEX IF NOT EXISTS ix_arsiv_kayit ON arsiv(kayit_id);
CREATE TRIGGER IF NOT EXISTS arsiv_guncellenemez BEFORE UPDATE ON arsiv BEGIN SELECT RAISE(ABORT, 'arsiv degistirilemez'); END;
CREATE TRIGGER IF NOT EXISTS arsiv_silinemez BEFORE DELETE ON arsiv BEGIN SELECT RAISE(ABORT, 'arsiv silinemez'); END;

CREATE TABLE IF NOT EXISTS yorumlar (
  id INTEGER PRIMARY KEY, kayit_id INTEGER NOT NULL, kullanici TEXT NOT NULL, metin TEXT NOT NULL,
  zaman TEXT NOT NULL, duzenleme_zamani TEXT,
  silindi INTEGER NOT NULL DEFAULT 0, silen TEXT NOT NULL DEFAULT '', silme_zamani TEXT
);
CREATE INDEX IF NOT EXISTS ix_yorum_kayit ON yorumlar(kayit_id, id);

CREATE TABLE IF NOT EXISTS yorum_okuma (
  kullanici TEXT NOT NULL, kayit_id INTEGER NOT NULL, son_okunan_yorum_id INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (kullanici, kayit_id)
);

CREATE TABLE IF NOT EXISTS bildirimler (
  id INTEGER PRIMARY KEY, kullanici TEXT NOT NULL, zaman TEXT NOT NULL, tur TEXT NOT NULL,
  kayit_id INTEGER, proje TEXT NOT NULL DEFAULT '', metin TEXT NOT NULL DEFAULT '',
  okundu INTEGER NOT NULL DEFAULT 0, okuma_zamani TEXT
);
CREATE INDEX IF NOT EXISTS ix_bildirim_kullanici ON bildirimler(kullanici, okundu, id);

CREATE TABLE IF NOT EXISTS panel_kullanicilari (
  kullanici_adi TEXT PRIMARY KEY, ad TEXT NOT NULL DEFAULT '', sifre_hash TEXT NOT NULL, yetki TEXT NOT NULL DEFAULT '',
  aktif INTEGER NOT NULL DEFAULT 1, sifre_degistir INTEGER NOT NULL DEFAULT 0,
  olusturma TEXT NOT NULL, olusturan TEXT NOT NULL DEFAULT '', son_giris TEXT, guncelleme TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS denetim (
  id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, kullanici TEXT NOT NULL DEFAULT '', islem TEXT NOT NULL,
  proje TEXT NOT NULL DEFAULT '', kayit_id INTEGER, eski TEXT, yeni TEXT, ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_denetim_zaman ON denetim(zaman);
CREATE INDEX IF NOT EXISTS ix_denetim_kayit ON denetim(kayit_id);

CREATE TABLE IF NOT EXISTS tg_kullanicilari (
  tg_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '',
  last_seen TEXT, status TEXT NOT NULL DEFAULT '',
  kayit_sayisi INTEGER NOT NULL DEFAULT 0, son_kayit_tarihi TEXT, son_kayit_proje TEXT NOT NULL DEFAULT '', son_kayit_kategori TEXT NOT NULL DEFAULT '',
  proje_sayilari TEXT NOT NULL DEFAULT '{}', kategori_sayilari TEXT NOT NULL DEFAULT '{}',
  onayli INTEGER NOT NULL DEFAULT 0, onay_tarihi TEXT, onay_adi TEXT NOT NULL DEFAULT '',
  engelli INTEGER NOT NULL DEFAULT 0, engel_tarihi TEXT, engel_sebep TEXT NOT NULL DEFAULT '', engelleyen TEXT NOT NULL DEFAULT '',
  deneme INTEGER NOT NULL DEFAULT 0, guncelleme TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_oturumlari (
  tg_id TEXT PRIMARY KEY, veri TEXT NOT NULL DEFAULT '{}', guncelleme TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ice_aktarimlar (
  id INTEGER PRIMARY KEY, zaman TEXT NOT NULL, tur TEXT NOT NULL, kullanici TEXT NOT NULL DEFAULT '', rapor TEXT NOT NULL DEFAULT '{}'
);
"""

PROJE_VARSAYILAN = [("PP", "PP", "#A6A6A6", "⚫"), ("PA", "PA", "#4472C4", "\U0001f535"), ("OF", "OF", "#FFFF00", "\U0001f7e1"),
                    ("HI", "HI", "#FF0000", "\U0001f534"), ("VI", "VI", "#7030A0", "\U0001f7e3"), ("GA", "GA", "#00B050", "\U0001f7e2"),
                    ("BETA", "BETA", "#FFA500", "\U0001f7e0")]
KATEGORI_VARSAYILAN = [("ark", "ARK", "ark_ana"), ("dds", "DDS", "sessiz_tip"), ("ddt", "DDT", "sessiz_tip"),
                       ("hgst", "HGST", "tek_uye"), ("prcst", "PRCST", "tek_uye"), ("lpst", "LPST", "ana_only")]
AKIS_ALANLARI = {"tek_uye": "Personel kodu + Uye ID", "ark_ana": "Personel kodu + Arkadas uye ID + Ana uye ID",
                 "ana_only": "Personel kodu + Ana uye ID", "sessiz_tip": "Personel kodu + Uye ID + Sessiz/Telesekreter"}
# kayit_guncelle ile degistirilebilen alanlar
DUZENLENEBILIR = ("personel", "uye_id", "ana_uye_id", "tip", "kategori", "kategori_kod", "link", "link_turu", "gorsel2", "aciklama",
                  "ek_not", "tarih", "tarih_ham", "lead_id", "giris_tipi", "ekleyen_tg_id", "ekleyen_ad", "ekleyen_guven", "gorsel_dosya", "foto_tarih")
ALAN_SINIR = {"personel": 50, "uye_id": 50, "ana_uye_id": 50, "tip": 30, "kategori": 50, "link": 500, "gorsel2": 500, "aciklama": 500, "ek_not": 500, "lead_id": 50}


def simdi():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def baglan(yol):
    os.makedirs(os.path.dirname(os.path.abspath(yol)), exist_ok=True)
    conn = sqlite3.connect(yol, check_same_thread=False, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SEMA)
    _goc(conn)
    _tohum(conn)
    return conn


def _goc(conn):
    """Sema surumu (PRAGMA user_version). Yeni surumde buraya 'ALTER TABLE' adimlari eklenir."""
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    if v < 1:
        conn.execute(f"PRAGMA user_version={SEMA_SURUMU}")


def _tohum(conn):
    if conn.execute("SELECT COUNT(*) FROM projeler").fetchone()[0] == 0:
        for i, (kod, ad, renk, emoji) in enumerate(PROJE_VARSAYILAN):
            conn.execute("INSERT INTO projeler(kod, ad, renk, emoji, sira) VALUES(?,?,?,?,?)", (kod, ad, renk, emoji, i))
    if conn.execute("SELECT COUNT(*) FROM kategoriler").fetchone()[0] == 0:
        for i, (kod, etiket, akis) in enumerate(KATEGORI_VARSAYILAN):
            conn.execute("INSERT INTO kategoriler(kod, etiket, akis, sira) VALUES(?,?,?,?)", (kod, etiket, akis, i))


def islem(conn):
    """with islem(conn): ... -> BEGIN IMMEDIATE / COMMIT (hata -> ROLLBACK). Ic ice kullanilmaz."""
    return _Islem(conn)


class _Islem:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        _kilit.acquire()
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, t, v, tb):
        try:
            if t is None:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute("ROLLBACK")
        finally:
            _kilit.release()
        return False


# ==================== ayarlar ====================
def ayar_al(conn, anahtar, varsayilan=None):
    r = conn.execute("SELECT deger FROM ayarlar WHERE anahtar=?", (anahtar,)).fetchone()
    return r["deger"] if r else varsayilan


def ayar_yaz(conn, anahtar, deger):
    conn.execute("INSERT INTO ayarlar(anahtar, deger) VALUES(?,?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger", (anahtar, "" if deger is None else str(deger)))


def bakim_modu(conn):
    return ayar_al(conn, "bakim_modu", "0") == "1"


def gyazo_bakim(conn):
    return ayar_al(conn, "gyazo_bakim", "0") == "1"


# ==================== projeler / kategoriler ====================
def projeler(conn, aktif=True):
    q = "SELECT * FROM projeler" + (" WHERE aktif=1" if aktif else "") + " ORDER BY sira, kod"
    return [dict(r) for r in conn.execute(q).fetchall()]


def proje_kodlari(conn, aktif=True):
    return [p["kod"] for p in projeler(conn, aktif)]


def proje_renk(conn):
    return {p["kod"]: p["renk"] for p in projeler(conn, False)}


def kategoriler(conn, aktif=True):
    q = "SELECT * FROM kategoriler" + (" WHERE aktif=1" if aktif else "") + " ORDER BY sira, kod"
    return [dict(r) for r in conn.execute(q).fetchall()]


def kategori_bul(conn, kod_veya_etiket):
    s = N.kucuk(kod_veya_etiket).strip()
    if not s:
        return None
    r = conn.execute("SELECT * FROM kategoriler WHERE kod=? OR lower(etiket)=?", (s, s)).fetchone()
    return dict(r) if r else None


def kategori_kaydet(conn, kod, etiket, akis, kim=""):
    """Botun Add-OrUpdate-Kategori'si: kod kucuk harf [a-z0-9_], akis dort tipten biri. -> hata metni | None"""
    kod = N.kucuk(kod).strip()
    if not kod or not all(c.isalnum() or c == "_" for c in kod):
        return "Kategori kodu bos veya gecersiz."
    if akis not in AKIS_ALANLARI:
        return "Akis tipi gecersiz. Gecerli: tek_uye, ark_ana, ana_only, sessiz_tip"
    etiket = N.metin(etiket) or kod.upper()
    with islem(conn):
        sira = conn.execute("SELECT COALESCE(MAX(sira),0)+1 FROM kategoriler").fetchone()[0]
        conn.execute("""INSERT INTO kategoriler(kod, etiket, akis, sira, aktif) VALUES(?,?,?,?,1)
                        ON CONFLICT(kod) DO UPDATE SET etiket=excluded.etiket, akis=excluded.akis, aktif=1""", (kod, etiket, akis, sira))
        denetim_yaz(conn, kim, "kategori_kaydet", yeni=f"{kod}|{etiket}|{akis}")
    return None


def kategori_sil(conn, kod, kim=""):
    kod = N.kucuk(kod).strip()
    with islem(conn):
        n = conn.execute("UPDATE kategoriler SET aktif=0 WHERE kod=?", (kod,)).rowcount
        if n:
            denetim_yaz(conn, kim, "kategori_sil", yeni=kod)
    return n > 0


# ==================== kayitlar ====================
KAYIT_ALANLARI = None  # ilk cagrida doldurulur


def kayit_sozluk(r):
    return dict(r) if r is not None else None


def kayit_al(conn, kid):
    return kayit_sozluk(conn.execute("SELECT * FROM kayitlar WHERE id=?", (kid,)).fetchone())


def _norm_alanlari(d):
    return {"personel_norm": N.normalle(d.get("personel")), "uye_norm": N.normalle(d.get("uye_id")),
            "ana_norm": N.normalle(d.get("ana_uye_id")), "link_norm": N.normalle(d.get("link"))}


def _kirp(alanlar):
    out = {}
    for k, v in alanlar.items():
        if v is None:
            v = ""
        if isinstance(v, str):
            v = N.metin(v) if k not in ("aciklama", "ek_not") else v.strip()
            lim = ALAN_SINIR.get(k)
            if lim:
                v = v[:lim]
        out[k] = v
    return out


def arsiv_yaz(conn, kayit_id, olay, kim, veri):
    conn.execute("INSERT INTO arsiv(kayit_id, zaman, olay, kim, veri) VALUES(?,?,?,?,?)",
                 (kayit_id, simdi(), olay, kim or "", json.dumps(veri, ensure_ascii=False, default=str)))


def denetim_yaz(conn, kullanici, islem_adi, proje="", kayit_id=None, eski=None, yeni=None, ip=""):
    conn.execute("INSERT INTO denetim(zaman, kullanici, islem, proje, kayit_id, eski, yeni, ip) VALUES(?,?,?,?,?,?,?,?)",
                 (simdi(), kullanici or "", islem_adi, proje or "", kayit_id,
                  None if eski is None else (eski if isinstance(eski, str) else json.dumps(eski, ensure_ascii=False, default=str))[:4000],
                  None if yeni is None else (yeni if isinstance(yeni, str) else json.dumps(yeni, ensure_ascii=False, default=str))[:4000], ip or ""))


def kayit_ekle(conn, alanlar, kim="bot", kaynak="bot", ip="", bildir=True):
    """Yeni kayit. alanlar: proje (zorunlu) + DUZENLENEBILIR alanlar + kt/kt_kim/kt_zaman/kt_kaynak + eski_* + foto_tarih.
    -> kayit (dict). Arsiv 'olustur', denetim 'ekle', projeyi okuyabilen panel kullanicilarina 'yeni_kayit' bildirimi."""
    a = _kirp(dict(alanlar))
    proje = (a.get("proje") or "").upper()
    if not proje:
        raise ValueError("proje bos")
    kat = a.get("kategori") or ""
    kat_kod = a.get("kategori_kod") or ""
    if kat and not kat_kod:
        k = kategori_bul(conn, kat)
        kat_kod = k["kod"] if k else N.kucuk(kat)
    if kat_kod and not kat:
        k = kategori_bul(conn, kat_kod)
        kat = k["etiket"] if k else kat_kod.upper()
    if a.get("link") and not a.get("link_turu"):
        from .gorsel import link_turu_ve_kimlik
        a["link_turu"] = link_turu_ve_kimlik(a["link"])[0]
    z = simdi()
    satir = {k: a.get(k, "") for k in DUZENLENEBILIR}
    satir.update({"proje": proje, "kategori": N.buyuk(kat) if kat else "", "kategori_kod": kat_kod,
                  "kt": 1 if a.get("kt") else 0, "kt_kim": a.get("kt_kim") or "", "kt_zaman": a.get("kt_zaman") or (z if a.get("kt") else None),
                  "kt_kaynak": a.get("kt_kaynak") or ("bot" if a.get("kt") else ""),
                  "kaynak": kaynak, "eski_sayfa": a.get("eski_sayfa") or "", "eski_satir": a.get("eski_satir"), "eski_anahtar": a.get("eski_anahtar") or "",
                  "tarih": a.get("tarih") or z, "tarih_ham": a.get("tarih_ham") or "", "foto_tarih": a.get("foto_tarih"),
                  "link_turu": a.get("link_turu") or "bos", "olusturma": z, "guncelleme": z})
    satir.update(_norm_alanlari(satir))
    kolonlar = ", ".join(satir.keys())
    with islem(conn):
        cur = conn.execute(f"INSERT INTO kayitlar({kolonlar}) VALUES({', '.join('?' * len(satir))})", tuple(satir.values()))
        kid = cur.lastrowid
        kayit = kayit_al(conn, kid)
        arsiv_yaz(conn, kid, "ice_aktar" if kaynak == "excel" else "olustur", kim, kayit)
        denetim_yaz(conn, kim, "ekle", proje, kid, yeni={"personel": kayit["personel"], "uye_id": kayit["uye_id"], "kategori": kayit["kategori"]}, ip=ip)
        if bildir and kaynak != "excel":
            _bildirim_dagit(conn, "yeni_kayit", kayit, f"{proje}: yeni kanit {kayit['personel']} {kayit['kategori']}".strip(), haric=kim)
    return kayit


def kayit_guncelle(conn, kid, degisiklik, kim, surum=None, ip="", neden=""):
    """Alan degisikligi (yalniz DUZENLENEBILIR). surum verilirse iyimser kilit: uyusmazsa (False, guncel_kayit, 'catisma').
    -> (True, kayit, None) | (False, kayit|None, hata)"""
    d = _kirp({k: v for k, v in degisiklik.items() if k in DUZENLENEBILIR})
    if not d:
        return False, kayit_al(conn, kid), "degisiklik yok"
    with islem(conn):
        eski = kayit_al(conn, kid)
        if not eski:
            return False, None, "kayit yok"
        if surum is not None and int(surum) != eski["surum"]:
            return False, eski, "catisma"
        if "kategori" in d:
            k = kategori_bul(conn, d["kategori"])
            d["kategori"] = N.buyuk(k["etiket"] if k else d["kategori"])
            d["kategori_kod"] = k["kod"] if k else N.kucuk(d["kategori"])
        if "link" in d and "link_turu" not in d:
            from .gorsel import link_turu_ve_kimlik
            d["link_turu"] = link_turu_ve_kimlik(d["link"])[0]
        gercek = {k: v for k, v in d.items() if eski.get(k) != v}
        if not gercek:
            return True, eski, None
        yeni = dict(eski)
        yeni.update(gercek)
        gercek.update(_norm_alanlari(yeni))
        gercek["surum"] = eski["surum"] + 1
        gercek["guncelleme"] = simdi()
        sets = ", ".join(f"{k}=?" for k in gercek)
        conn.execute(f"UPDATE kayitlar SET {sets} WHERE id=?", (*gercek.values(), kid))
        kayit = kayit_al(conn, kid)
        arsiv_yaz(conn, kid, "degistir", kim, kayit)
        fark = {k: [eski.get(k), kayit.get(k)] for k in d if eski.get(k) != kayit.get(k)}
        denetim_yaz(conn, kim, "duzenle", kayit["proje"], kid, eski={k: v[0] for k, v in fark.items()}, yeni={k: v[1] for k, v in fark.items()}, ip=ip)
        _bildirim_dagit(conn, "degisti", kayit, f"{kayit['proje']}: {kayit['personel']} kaydi {kim} tarafindan duzenlendi", haric=kim, sadece_ilgililer=True)
    return True, kayit, None


def kt_ayarla(conn, kid, deger, kim, kaynak="panel", ip=""):
    """Onay (KT). Hedef deger zaten buysa dokunmaz (idempotent). -> kayit|None"""
    deger = 1 if deger else 0
    with islem(conn):
        eski = kayit_al(conn, kid)
        if not eski:
            return None
        if eski["kt"] == deger:
            return eski
        z = simdi()
        conn.execute("UPDATE kayitlar SET kt=?, kt_kim=?, kt_zaman=?, kt_kaynak=?, surum=surum+1, guncelleme=? WHERE id=?",
                     (deger, kim if deger else "", z if deger else None, kaynak if deger else "", z, kid))
        kayit = kayit_al(conn, kid)
        arsiv_yaz(conn, kid, "kt", kim, kayit)
        denetim_yaz(conn, kim, "kt" if deger else "kt_kaldir", kayit["proje"], kid, eski=str(eski["kt"]), yeni=str(deger), ip=ip)
        _bildirim_dagit(conn, "kt", kayit, f"{kayit['proje']}: {kayit['personel']} kaydi {'onaylandi' if deger else 'onayi kaldirildi'} ({kim})", haric=kim, sadece_ilgililer=True)
    return kayit


def kayit_sil(conn, kid, kim, neden="", ip=""):
    """Yumusak silme: listelerde gorunmez, arsivde ve gecmiste kalir, geri alinabilir. -> kayit|None"""
    with islem(conn):
        eski = kayit_al(conn, kid)
        if not eski or eski["silindi"]:
            return eski
        z = simdi()
        conn.execute("UPDATE kayitlar SET silindi=1, silen=?, silme_zamani=?, silme_nedeni=?, surum=surum+1, guncelleme=? WHERE id=?", (kim, z, (neden or "")[:200], z, kid))
        kayit = kayit_al(conn, kid)
        arsiv_yaz(conn, kid, "sil", kim, kayit)
        denetim_yaz(conn, kim, "sil", kayit["proje"], kid, eski={"personel": eski["personel"], "uye_id": eski["uye_id"], "kategori": eski["kategori"]}, yeni=neden or None, ip=ip)
        _bildirim_dagit(conn, "silindi", kayit, f"{kayit['proje']}: {kayit['personel']} kaydi {kim} tarafindan silindi", haric=kim, sadece_ilgililer=True)
    return kayit


def kayit_geri_al(conn, kid, kim, ip=""):
    with islem(conn):
        eski = kayit_al(conn, kid)
        if not eski or not eski["silindi"]:
            return eski
        z = simdi()
        conn.execute("UPDATE kayitlar SET silindi=0, silen='', silme_zamani=NULL, silme_nedeni='', surum=surum+1, guncelleme=? WHERE id=?", (z, kid))
        kayit = kayit_al(conn, kid)
        arsiv_yaz(conn, kid, "geri_al", kim, kayit)
        denetim_yaz(conn, kim, "geri_al", kayit["proje"], kid, ip=ip)
    return kayit


def kayit_gecmisi(conn, kid):
    """Gecmis sekmesi: denetim satirlari (yeniden eskiye) + arsiv kopyalari sayisi."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM denetim WHERE kayit_id=? ORDER BY id DESC", (kid,)).fetchall()]
    for r in rows:
        for k in ("eski", "yeni"):
            try:
                r[k] = json.loads(r[k]) if r[k] and r[k][:1] in "{[" else r[k]
            except Exception:
                pass
    return rows


def arsiv_kayitlari(conn, kid):
    out = []
    for r in conn.execute("SELECT * FROM arsiv WHERE kayit_id=? ORDER BY id", (kid,)).fetchall():
        d = dict(r)
        try:
            d["veri"] = json.loads(d["veri"])
        except Exception:
            pass
        out.append(d)
    return out


# ==================== yorumlar ====================
YORUM_SINIR = 2000
YORUM_DUZENLEME_DK = 15


def yorumlar(conn, kid):
    return [dict(r) for r in conn.execute("SELECT * FROM yorumlar WHERE kayit_id=? ORDER BY id", (kid,)).fetchall()]


def yorum_ekle(conn, kid, kim, metin, ip=""):
    metin = (metin or "").strip()
    if not metin:
        raise ValueError("yorum bos")
    metin = metin[:YORUM_SINIR]
    with islem(conn):
        kayit = kayit_al(conn, kid)
        if not kayit:
            raise ValueError("kayit yok")
        z = simdi()
        cur = conn.execute("INSERT INTO yorumlar(kayit_id, kullanici, metin, zaman) VALUES(?,?,?,?)", (kid, kim, metin, z))
        yid = cur.lastrowid
        conn.execute("UPDATE kayitlar SET yorum_sayisi=(SELECT COUNT(*) FROM yorumlar WHERE kayit_id=? AND silindi=0), son_yorum_zamani=? WHERE id=?", (kid, z, kid))
        conn.execute("INSERT INTO yorum_okuma(kullanici, kayit_id, son_okunan_yorum_id) VALUES(?,?,?) ON CONFLICT(kullanici, kayit_id) DO UPDATE SET son_okunan_yorum_id=excluded.son_okunan_yorum_id", (kim, kid, yid))
        denetim_yaz(conn, kim, "yorum", kayit["proje"], kid, yeni=metin[:300], ip=ip)
        _bildirim_dagit(conn, "yorum", kayit, f"{kayit['proje']}: {kayit['personel']} kaydina {kim} yorum yazdi: {metin[:80]}", haric=kim, sadece_ilgililer=True)
    return dict(conn.execute("SELECT * FROM yorumlar WHERE id=?", (yid,)).fetchone())


def yorum_duzenle(conn, yid, kim, metin, admin=False, ip=""):
    """Yazar YORUM_DUZENLEME_DK icinde duzeltebilir. -> (ok, hata)"""
    metin = (metin or "").strip()[:YORUM_SINIR]
    with islem(conn):
        y = conn.execute("SELECT * FROM yorumlar WHERE id=?", (yid,)).fetchone()
        if not y or y["silindi"]:
            return False, "yorum yok"
        if y["kullanici"] != kim and not admin:
            return False, "yalniz yazar duzeltebilir"
        if not admin and datetime.strptime(y["zaman"], "%Y-%m-%d %H:%M:%S") + timedelta(minutes=YORUM_DUZENLEME_DK) < datetime.now():
            return False, f"{YORUM_DUZENLEME_DK} dakika gecti"
        if not metin:
            return False, "yorum bos"
        conn.execute("UPDATE yorumlar SET metin=?, duzenleme_zamani=? WHERE id=?", (metin, simdi(), yid))
        denetim_yaz(conn, kim, "yorum_duzenle", kayit_id=y["kayit_id"], eski=y["metin"][:300], yeni=metin[:300], ip=ip)
    return True, None


def yorum_sil(conn, yid, kim, admin=False, ip=""):
    with islem(conn):
        y = conn.execute("SELECT * FROM yorumlar WHERE id=?", (yid,)).fetchone()
        if not y or y["silindi"]:
            return False, "yorum yok"
        if y["kullanici"] != kim and not admin:
            return False, "yalniz yazar ya da admin silebilir"
        conn.execute("UPDATE yorumlar SET silindi=1, silen=?, silme_zamani=? WHERE id=?", (kim, simdi(), yid))
        conn.execute("UPDATE kayitlar SET yorum_sayisi=(SELECT COUNT(*) FROM yorumlar WHERE kayit_id=? AND silindi=0) WHERE id=?", (y["kayit_id"], y["kayit_id"]))
        denetim_yaz(conn, kim, "yorum_sil", kayit_id=y["kayit_id"], eski=y["metin"][:300], ip=ip)
    return True, None


def yorum_okundu(conn, kullanici, kid):
    son = conn.execute("SELECT COALESCE(MAX(id),0) FROM yorumlar WHERE kayit_id=?", (kid,)).fetchone()[0]
    conn.execute("INSERT INTO yorum_okuma(kullanici, kayit_id, son_okunan_yorum_id) VALUES(?,?,?) ON CONFLICT(kullanici, kayit_id) DO UPDATE SET son_okunan_yorum_id=excluded.son_okunan_yorum_id", (kullanici, kid, son))


def okunmamis_yorumlar(conn, kullanici, kids):
    """-> {kayit_id: okunmamis yorum sayisi} (yalniz >0 olanlar)"""
    if not kids:
        return {}
    out = {}
    for i in range(0, len(kids), 500):
        parca = list(kids[i:i + 500])
        q = f"""SELECT y.kayit_id, COUNT(*) n FROM yorumlar y LEFT JOIN yorum_okuma o ON o.kayit_id=y.kayit_id AND o.kullanici=?
                WHERE y.kayit_id IN ({','.join('?' * len(parca))}) AND y.silindi=0 AND y.kullanici<>? AND y.id > COALESCE(o.son_okunan_yorum_id, 0)
                GROUP BY y.kayit_id"""
        for r in conn.execute(q, (kullanici, *parca, kullanici)).fetchall():
            out[r["kayit_id"]] = r["n"]
    return out


# ==================== bildirimler ====================
def _ilgililer(conn, kayit):
    """Kaydi onaylayan, duzenleyen, silen ya da yorum yazan panel kullanicilari."""
    k = set()
    for r in conn.execute("SELECT DISTINCT kullanici FROM yorumlar WHERE kayit_id=? AND silindi=0", (kayit["id"],)).fetchall():
        k.add(r["kullanici"])
    for r in conn.execute("SELECT DISTINCT kullanici FROM denetim WHERE kayit_id=? AND islem IN ('kt','kt_kaldir','duzenle','sil','geri_al','ekle')", (kayit["id"],)).fetchall():
        k.add(r["kullanici"])
    return {x for x in k if x and x != "bot"}


def _bildirim_dagit(conn, tur, kayit, metin, haric=None, sadece_ilgililer=False):
    hedef = _ilgililer(conn, kayit) if sadece_ilgililer else set()
    if not sadece_ilgililer:
        for u in conn.execute("SELECT kullanici_adi, yetki FROM panel_kullanicilari WHERE aktif=1").fetchall():
            if Y.izin(Y.coz(u["yetki"]), kayit["proje"], "oku"):
                hedef.add(u["kullanici_adi"])
    else:
        hedef = {u for u in hedef if _okuyabilir(conn, u, kayit["proje"])}
    hedef.discard(haric)
    z = simdi()
    for u in sorted(hedef):
        conn.execute("INSERT INTO bildirimler(kullanici, zaman, tur, kayit_id, proje, metin) VALUES(?,?,?,?,?,?)", (u, z, tur, kayit["id"], kayit["proje"], metin[:300]))


def _okuyabilir(conn, kullanici, proje):
    r = conn.execute("SELECT yetki, aktif FROM panel_kullanicilari WHERE kullanici_adi=?", (kullanici,)).fetchone()
    return bool(r and r["aktif"] and Y.izin(Y.coz(r["yetki"]), proje, "oku"))


def bildirimler(conn, kullanici, n=50, sadece_okunmamis=False):
    q = "SELECT * FROM bildirimler WHERE kullanici=?" + (" AND okundu=0" if sadece_okunmamis else "") + " ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in conn.execute(q, (kullanici, n)).fetchall()]


def okunmamis_bildirim_sayisi(conn, kullanici):
    return conn.execute("SELECT COUNT(*) FROM bildirimler WHERE kullanici=? AND okundu=0", (kullanici,)).fetchone()[0]


def bildirim_okundu(conn, kullanici, ids=None, okundu=True):
    z = simdi() if okundu else None
    if ids is None:
        conn.execute("UPDATE bildirimler SET okundu=?, okuma_zamani=? WHERE kullanici=?", (1 if okundu else 0, z, kullanici))
    else:
        for i in ids:
            conn.execute("UPDATE bildirimler SET okundu=?, okuma_zamani=? WHERE kullanici=? AND id=?", (1 if okundu else 0, z, kullanici, int(i)))


def bildirim_temizle(conn, gun=90):
    esik = (datetime.now() - timedelta(days=gun)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM bildirimler WHERE zaman < ?", (esik,))


# ==================== panel kullanicilari ====================
_hatali = {}
_hatali_ip = {}
KILIT_DK = 15


def kullanici_bul(conn, ad):
    r = conn.execute("SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?", (N.kucuk(ad).strip(),)).fetchone()
    return dict(r) if r else None


def kullanicilar(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM panel_kullanicilari ORDER BY kullanici_adi").fetchall()]


def kullanici_adi_gecerli(ad):
    return bool(ad) and len(ad) <= 40 and ad.replace("_", "").replace(".", "").isalnum()


def kullanici_ekle(conn, ad, yetki, sifre, gorunen_ad="", olusturan="", sifre_degistir=True, sifre_hash=None):
    from werkzeug.security import generate_password_hash
    ad = N.kucuk(ad).strip()
    if not kullanici_adi_gecerli(ad):
        raise ValueError("Kullanici adi harf/rakam olmali")
    z = simdi()
    with islem(conn):
        conn.execute("""INSERT INTO panel_kullanicilari(kullanici_adi, ad, sifre_hash, yetki, aktif, sifre_degistir, olusturma, olusturan, guncelleme)
                        VALUES(?,?,?,?,1,?,?,?,?)""", (ad, gorunen_ad or ad, sifre_hash or generate_password_hash(sifre), yetki or "", 1 if sifre_degistir else 0, z, olusturan, z))
        denetim_yaz(conn, olusturan, "kullanici_ekle", yeni=f"{ad} [{yetki}]")
    return kullanici_bul(conn, ad)


def kullanici_guncelle(conn, ad, kim="", **alan):
    """alan: ad, yetki, aktif, sifre (duz metin -> hash), sifre_degistir"""
    from werkzeug.security import generate_password_hash
    ad = N.kucuk(ad).strip()
    sets, vals = [], []
    for k, v in alan.items():
        if k == "sifre":
            sets.append("sifre_hash=?"); vals.append(generate_password_hash(v))
        elif k in ("ad", "yetki"):
            sets.append(f"{k}=?"); vals.append(v or "")
        elif k in ("aktif", "sifre_degistir"):
            sets.append(f"{k}=?"); vals.append(1 if v else 0)
        elif k == "son_giris":
            sets.append("son_giris=?"); vals.append(v)
    if not sets:
        return
    sets.append("guncelleme=?"); vals.append(simdi())
    with islem(conn):
        conn.execute(f"UPDATE panel_kullanicilari SET {', '.join(sets)} WHERE kullanici_adi=?", (*vals, ad))
        denetim_yaz(conn, kim, "kullanici_guncelle", yeni=f"{ad}: " + ", ".join(k for k in alan if k != "sifre") + (" sifre" if "sifre" in alan else ""))


def _kilitli(d, k):
    h = d.get(k)
    return bool(h and h[1] and h[1] > datetime.now())


def _hata_say(d, k, esik):
    h = d.get(k)
    n = (h[0] if h and not (h[1] and h[1] <= datetime.now()) else 0) + 1
    d[k] = [0 if n >= esik else n, datetime.now() + timedelta(minutes=KILIT_DK) if n >= esik else None]
    if len(d) > 5000:
        for kk in [kk for kk, v in d.items() if not v[1] or v[1] <= datetime.now()][:2500]:
            d.pop(kk, None)


def kullanici_dogrula(conn, ad, sifre, kaynak=""):
    """-> (kullanici|None, hata|None). Kilit deneyen adrese baglidir (5/15 dk ad+adres, 20/15 dk adres)."""
    from werkzeug.security import check_password_hash
    ad = N.kucuk(ad).strip()
    kaynak = str(kaynak or "")
    if _kilitli(_hatali_ip, kaynak) or _kilitli(_hatali, (kaynak, ad)):
        return None, "Cok fazla hatali deneme; 15 dakika sonra tekrar deneyin."
    u = kullanici_bul(conn, ad)
    if u and u["aktif"] and check_password_hash(u["sifre_hash"], sifre or ""):
        _hatali.pop((kaynak, ad), None)
        _hatali_ip.pop(kaynak, None)
        conn.execute("UPDATE panel_kullanicilari SET son_giris=? WHERE kullanici_adi=?", (simdi(), ad))
        return u, None
    _hata_say(_hatali, (kaynak, ad), 5)
    _hata_say(_hatali_ip, kaynak, 20)
    return None, "Kullanici adi veya sifre hatali."


# ==================== telegram kullanicilari (bot defteri + onay/engel/deneme) ====================
def tg_al(conn, tg_id):
    r = conn.execute("SELECT * FROM tg_kullanicilari WHERE tg_id=?", (str(tg_id),)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("proje_sayilari", "kategori_sayilari"):
        try:
            d[k] = json.loads(d[k] or "{}")
        except Exception:
            d[k] = {}
    return d


def tg_listesi(conn):
    return [tg_al(conn, r["tg_id"]) for r in conn.execute("SELECT tg_id FROM tg_kullanicilari ORDER BY onayli DESC, last_seen DESC").fetchall()]


def tg_guncelle(conn, tg_id, **alan):
    """Satir yoksa olusturur. alan: username, first_name, last_seen, status, onayli, onay_tarihi, onay_adi, engelli, engel_tarihi,
    engel_sebep, engelleyen, deneme, kayit_sayisi, son_kayit_*, proje_sayilari(dict), kategori_sayilari(dict)"""
    tg_id = str(tg_id)
    z = simdi()
    for k in ("proje_sayilari", "kategori_sayilari"):
        if k in alan and not isinstance(alan[k], str):
            alan[k] = json.dumps(alan[k], ensure_ascii=False)
    conn.execute("INSERT OR IGNORE INTO tg_kullanicilari(tg_id, guncelleme) VALUES(?,?)", (tg_id, z))
    if alan:
        sets = ", ".join(f"{k}=?" for k in alan)
        conn.execute(f"UPDATE tg_kullanicilari SET {sets}, guncelleme=? WHERE tg_id=?", (*alan.values(), z, tg_id))


def tg_onayla(conn, tg_id, ad="", kim="panel", ip=""):
    with islem(conn):
        tg_guncelle(conn, tg_id, onayli=1, onay_tarihi=simdi(), onay_adi=ad or "", engelli=0, engel_sebep="", deneme=0)
        oturum_sil(conn, tg_id)
        denetim_yaz(conn, kim, "bot_onayla", yeni=f"{tg_id} {ad}".strip(), ip=ip)


def tg_onay_kaldir(conn, tg_id, kim="panel", ip=""):
    """Botun /onayli_sil'i: onay + oturum + deneme temizlenir, kullanici yeniden sifreye duser."""
    with islem(conn):
        tg_guncelle(conn, tg_id, onayli=0, onay_tarihi=None, deneme=0)
        oturum_sil(conn, tg_id)
        denetim_yaz(conn, kim, "bot_onay_kaldir", yeni=str(tg_id), ip=ip)


def tg_engelle(conn, tg_id, sebep="", kim="panel", ip=""):
    with islem(conn):
        tg_guncelle(conn, tg_id, engelli=1, engel_tarihi=simdi(), engel_sebep=sebep or "", engelleyen=kim)
        oturum_sil(conn, tg_id)
        denetim_yaz(conn, kim, "bot_engelle", yeni=f"{tg_id} ({sebep})", ip=ip)


def tg_engel_kaldir(conn, tg_id, kim="panel", ip=""):
    """Botun /engel_kaldir'i: engel + deneme + oturum temizlenir (onay durur). -> engel kaydi var miydi"""
    with islem(conn):
        u = tg_al(conn, tg_id)
        vardi = bool(u and u["engelli"])
        tg_guncelle(conn, tg_id, engelli=0, engel_sebep="", engel_tarihi=None, deneme=0)
        oturum_sil(conn, tg_id)
        denetim_yaz(conn, kim, "bot_engel_kaldir", yeni=str(tg_id), ip=ip)
    return vardi


def tg_tam_sifirla(conn, tg_id, kim="panel", ip=""):
    """Botun /engel_kaldir_sifirla'si: engel + onay + deneme + oturum birlikte."""
    with islem(conn):
        u = tg_al(conn, tg_id)
        sonuc = {"engel_silindi": bool(u and u["engelli"]), "onay_silindi": bool(u and u["onayli"])}
        tg_guncelle(conn, tg_id, engelli=0, engel_sebep="", engel_tarihi=None, onayli=0, onay_tarihi=None, deneme=0)
        oturum_sil(conn, tg_id)
        denetim_yaz(conn, kim, "bot_tam_sifirla", yeni=str(tg_id), ip=ip)
    return sonuc


def tg_deneme(conn, tg_id, arttir=True):
    """Yanlis sifre sayaci. -> yeni deger"""
    u = tg_al(conn, tg_id) or {"deneme": 0}
    n = (u.get("deneme") or 0) + 1 if arttir else 0
    tg_guncelle(conn, tg_id, deneme=n)
    return n


def tg_kayit_sayaci(conn, tg_id, username, first_name, proje, kategori_kod, kategori_etiket):
    """Botun Register-KullaniciKayit'i."""
    u = tg_al(conn, tg_id) or {"kayit_sayisi": 0, "proje_sayilari": {}, "kategori_sayilari": {}}
    p = dict(u.get("proje_sayilari") or {}); p[proje.upper()] = p.get(proje.upper(), 0) + 1
    k = dict(u.get("kategori_sayilari") or {}); kk = (kategori_kod or "").upper(); k[kk] = k.get(kk, 0) + 1
    z = simdi()
    tg_guncelle(conn, tg_id, username=username or "", first_name=first_name or "", last_seen=z, status="kayit_eklendi",
                kayit_sayisi=(u.get("kayit_sayisi") or 0) + 1, son_kayit_tarihi=z, son_kayit_proje=proje.upper(), son_kayit_kategori=kategori_etiket or "",
                proje_sayilari=p, kategori_sayilari=k)


# ==================== bot oturumlari ====================
def oturum_al(conn, tg_id):
    r = conn.execute("SELECT veri FROM bot_oturumlari WHERE tg_id=?", (str(tg_id),)).fetchone()
    if not r:
        return None
    try:
        return json.loads(r["veri"])
    except Exception:
        return None


def oturum_yaz(conn, tg_id, veri):
    conn.execute("INSERT INTO bot_oturumlari(tg_id, veri, guncelleme) VALUES(?,?,?) ON CONFLICT(tg_id) DO UPDATE SET veri=excluded.veri, guncelleme=excluded.guncelleme",
                 (str(tg_id), json.dumps(veri or {}, ensure_ascii=False), simdi()))


def oturum_sil(conn, tg_id=None):
    if tg_id is None:
        conn.execute("DELETE FROM bot_oturumlari")
    else:
        conn.execute("DELETE FROM bot_oturumlari WHERE tg_id=?", (str(tg_id),))


def oturumlar(conn):
    out = []
    for r in conn.execute("SELECT * FROM bot_oturumlari ORDER BY guncelleme DESC").fetchall():
        try:
            v = json.loads(r["veri"])
        except Exception:
            v = {}
        v = dict(v); v["id"] = r["tg_id"]; v["guncelleme"] = r["guncelleme"]
        out.append(v)
    return out


def oturum_temizle_eski(conn, saat=24):
    esik = (datetime.now() - timedelta(hours=saat)).strftime("%Y-%m-%d %H:%M:%S")
    return conn.execute("DELETE FROM bot_oturumlari WHERE guncelleme < ?", (esik,)).rowcount


# ==================== sayaclar / ozet ====================
def proje_sayaclari(conn, izinli=None):
    """-> {proje: {bekleyen, onayli, silinen, toplam}}"""
    out = {}
    for r in conn.execute("""SELECT proje, SUM(CASE WHEN kt=0 AND silindi=0 THEN 1 ELSE 0 END) bekleyen,
                                    SUM(CASE WHEN kt=1 AND silindi=0 THEN 1 ELSE 0 END) onayli,
                                    SUM(CASE WHEN silindi=1 THEN 1 ELSE 0 END) silinen, COUNT(*) toplam
                             FROM kayitlar GROUP BY proje""").fetchall():
        if izinli is None or r["proje"] in izinli:
            out[r["proje"]] = {"bekleyen": r["bekleyen"] or 0, "onayli": r["onayli"] or 0, "silinen": r["silinen"] or 0, "toplam": r["toplam"]}
    return out


def yedekle(conn, hedef_yol):
    """SQLite online yedek (tutarli kopya). -> hedef_yol"""
    os.makedirs(os.path.dirname(os.path.abspath(hedef_yol)), exist_ok=True)
    hedef = sqlite3.connect(hedef_yol)
    try:
        with _kilit:
            conn.backup(hedef)
    finally:
        hedef.close()
    return hedef_yol
