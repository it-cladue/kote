# -*- coding: utf-8 -*-
import sqlite3, os, threading

SEMA = """
CREATE TABLE IF NOT EXISTS kayitlar (
  id INTEGER PRIMARY KEY,
  anahtar TEXT UNIQUE NOT NULL,
  proje TEXT NOT NULL,
  kategori TEXT, personel TEXT, uye_id TEXT, ana_uye_id TEXT, tip TEXT,
  link TEXT, link_turu TEXT, gorsel_dosya TEXT,
  tarih TEXT, tarih_ham TEXT, excel_satir INTEGER,
  excel_durum TEXT DEFAULT 'var',
  kt INTEGER DEFAULT 0, kt_kaynak TEXT DEFAULT 'excel', kt_kim TEXT, kt_zaman TEXT,
  aciklama TEXT, gorsel2 TEXT, ek_not TEXT,
  ekleyen_id TEXT, ekleyen_ad TEXT, ekleyen_guven TEXT,
  silindi INTEGER DEFAULT 0, silen TEXT, silme_zamani TEXT,
  bekleyen_islem TEXT, bekleyen_id TEXT, bekleyen_hata TEXT,
  ilk_gorulme TEXT, son_gorulme TEXT, guncelleme TEXT
);
CREATE INDEX IF NOT EXISTS ix_kayit_proje ON kayitlar(proje, silindi, kt);
CREATE INDEX IF NOT EXISTS ix_kayit_personel ON kayitlar(personel);
CREATE INDEX IF NOT EXISTS ix_kayit_uye ON kayitlar(uye_id);
CREATE INDEX IF NOT EXISTS ix_kayit_tarih ON kayitlar(tarih);

CREATE TABLE IF NOT EXISTS panel_kullanicilari (
  id INTEGER PRIMARY KEY,
  kullanici_adi TEXT UNIQUE NOT NULL,
  ad TEXT, sifre_hash TEXT NOT NULL, yetki TEXT NOT NULL DEFAULT '',
  aktif INTEGER DEFAULT 1, hatali_giris INTEGER DEFAULT 0, kilit_bitis TEXT,
  sifre_degistir INTEGER DEFAULT 0, olusturma TEXT, son_giris TEXT
);
CREATE TABLE IF NOT EXISTS denetim (
  id INTEGER PRIMARY KEY, zaman TEXT, kullanici TEXT, islem TEXT,
  proje TEXT, anahtar TEXT, eski TEXT, yeni TEXT, ip TEXT
);
CREATE INDEX IF NOT EXISTS ix_denetim_zaman ON denetim(zaman);
CREATE TABLE IF NOT EXISTS ice_aktarim (
  id INTEGER PRIMARY KEY, zaman TEXT, sure_ms INTEGER, sayfalar TEXT,
  yeni INTEGER, degisen INTEGER, silinen INTEGER, hata TEXT
);
CREATE TABLE IF NOT EXISTS ayarlar (anahtar TEXT PRIMARY KEY, deger TEXT);
CREATE TABLE IF NOT EXISTS islem_sonuclari (
  id TEXT PRIMARY KEY, zaman TEXT, op TEXT, ozet TEXT, kullanici TEXT,
  durum TEXT DEFAULT 'bekliyor', mesaj TEXT, sonuc_zaman TEXT
);
"""

_kilit = threading.RLock()


def baglan(yol):
    os.makedirs(os.path.dirname(os.path.abspath(yol)), exist_ok=True)
    conn = sqlite3.connect(yol, check_same_thread=False, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SEMA)
    return conn


def ayar_al(conn, anahtar, varsayilan=None):
    r = conn.execute("SELECT deger FROM ayarlar WHERE anahtar=?", (anahtar,)).fetchone()
    return r["deger"] if r else varsayilan


def ayar_yaz(conn, anahtar, deger):
    with _kilit:
        conn.execute("INSERT INTO ayarlar(anahtar,deger) VALUES(?,?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger", (anahtar, str(deger)))


def denetim_yaz(conn, kullanici, islem, proje=None, anahtar=None, eski=None, yeni=None, ip=None):
    from datetime import datetime
    with _kilit:
        conn.execute("INSERT INTO denetim(zaman,kullanici,islem,proje,anahtar,eski,yeni,ip) VALUES(?,?,?,?,?,?,?,?)",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kullanici, islem, proje, anahtar,
                      None if eski is None else str(eski)[:2000], None if yeni is None else str(yeni)[:2000], ip))
