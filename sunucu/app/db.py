"""İki süreç/çok oturum: WAL, kısa transaction, idempotent additive geçiş."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime

SEMA = '''
CREATE TABLE IF NOT EXISTS kayitlar (
 id INTEGER PRIMARY KEY, anahtar TEXT UNIQUE NOT NULL, proje TEXT NOT NULL,
 kategori TEXT, personel TEXT, uye_id TEXT, ana_uye_id TEXT, tip TEXT,
 link TEXT, link_turu TEXT, gorsel_dosya TEXT, tarih TEXT, tarih_ham TEXT,
 excel_satir INTEGER, excel_durum TEXT DEFAULT 'var', kt INTEGER DEFAULT 0,
 kt_kaynak TEXT DEFAULT 'panel', kt_kim TEXT, kt_zaman TEXT, aciklama TEXT,
 gorsel2 TEXT, gorsel2_dosya TEXT, ek_not TEXT, ekleyen_id TEXT, ekleyen_ad TEXT,
 ekleyen_guven TEXT, silindi INTEGER DEFAULT 0, silen TEXT, silme_zamani TEXT,
 bekleyen_islem TEXT, bekleyen_id TEXT, bekleyen_hata TEXT, panel_uygulama TEXT,
 ilk_gorulme TEXT, son_gorulme TEXT, guncelleme TEXT, kaynak TEXT DEFAULT 'telegram',
 giris_tipi TEXT, lead_id TEXT, telegram_bot_id TEXT, file_id TEXT,
 file_unique_id TEXT, message_id INTEGER, chat_id TEXT, kategori_code TEXT,
 kategori_mode TEXT, surum INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS panel_kullanicilari (
 id INTEGER PRIMARY KEY, kullanici_adi TEXT UNIQUE NOT NULL, ad TEXT,
 sifre_hash TEXT NOT NULL, yetki TEXT NOT NULL DEFAULT '', aktif INTEGER DEFAULT 1,
 hatali_giris INTEGER DEFAULT 0, kilit_bitis TEXT, sifre_degistir INTEGER DEFAULT 0,
 olusturma TEXT, son_giris TEXT, session_version INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS denetim (
 id INTEGER PRIMARY KEY,zaman TEXT,kullanici TEXT,islem TEXT,proje TEXT,
 anahtar TEXT,eski TEXT,yeni TEXT,ip TEXT
);
CREATE TABLE IF NOT EXISTS ice_aktarim (
 id INTEGER PRIMARY KEY,zaman TEXT,sure_ms INTEGER,sayfalar TEXT,
 yeni INTEGER,degisen INTEGER,silinen INTEGER,hata TEXT
);
CREATE TABLE IF NOT EXISTS ayarlar (anahtar TEXT PRIMARY KEY,deger TEXT);
CREATE TABLE IF NOT EXISTS islem_sonuclari (
 id TEXT PRIMARY KEY,zaman TEXT,op TEXT,ozet TEXT,kullanici TEXT,
 durum TEXT DEFAULT 'ok',mesaj TEXT,sonuc_zaman TEXT
);
CREATE TABLE IF NOT EXISTS tg_kullanicilar (
 id TEXT PRIMARY KEY,username TEXT DEFAULT '',first_name TEXT DEFAULT '',
 onayli INTEGER DEFAULT 0,engelli INTEGER DEFAULT 0,engel_sebep TEXT,
 onay_tarihi TEXT,last_seen TEXT,deneme INTEGER DEFAULT 0,kayit_sayisi INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS kategoriler (
 code TEXT PRIMARY KEY,label TEXT NOT NULL,mode TEXT NOT NULL,aktif INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tg_oturumlar (
 bot_id TEXT NOT NULL,user_id TEXT NOT NULL,veri TEXT NOT NULL,guncelleme TEXT,
 PRIMARY KEY(bot_id,user_id)
);
CREATE TABLE IF NOT EXISTS tg_gelen (
 bot_id TEXT NOT NULL,update_id INTEGER NOT NULL,veri TEXT NOT NULL,
 durum TEXT DEFAULT 'bekliyor',deneme INTEGER DEFAULT 0,hata TEXT,
 olusturma TEXT,guncelleme TEXT,PRIMARY KEY(bot_id,update_id)
);
CREATE TABLE IF NOT EXISTS tg_durum (
 bot_id TEXT PRIMARY KEY,offset INTEGER DEFAULT 0,heartbeat TEXT,username TEXT,hata TEXT
);
CREATE TABLE IF NOT EXISTS arsiv_dosyalar (
 id INTEGER PRIMARY KEY,yol TEXT UNIQUE NOT NULL,ad TEXT,proje TEXT,
 kimlik TEXT,kayit_id INTEGER,guncelleme TEXT
);
CREATE TABLE IF NOT EXISTS bildirimler (
 id INTEGER PRIMARY KEY,kullanici_adi TEXT NOT NULL,kayit_id INTEGER NOT NULL,
 proje TEXT NOT NULL,zaman TEXT NOT NULL,okundu INTEGER DEFAULT 0,
 UNIQUE(kullanici_adi,kayit_id),FOREIGN KEY(kayit_id) REFERENCES kayitlar(id)
);
CREATE TABLE IF NOT EXISTS yorumlar (
 id INTEGER PRIMARY KEY,kayit_id INTEGER NOT NULL,kullanici TEXT NOT NULL,
 metin TEXT NOT NULL,zaman TEXT NOT NULL,yanit_id INTEGER,alici TEXT,tur TEXT DEFAULT 'yorum',
 FOREIGN KEY(kayit_id) REFERENCES kayitlar(id)
);
CREATE TABLE IF NOT EXISTS tg_girisler (
 bot_id TEXT NOT NULL,user_id TEXT NOT NULL,zaman TEXT,PRIMARY KEY(bot_id,user_id)
);
CREATE TABLE IF NOT EXISTS tg_tema (user_id TEXT PRIMARY KEY,renkli INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS mesaj_bildirimleri (
 id INTEGER PRIMARY KEY,kullanici_adi TEXT NOT NULL,kayit_id INTEGER NOT NULL,
 proje TEXT NOT NULL,olay TEXT NOT NULL,tur TEXT NOT NULL,kim TEXT NOT NULL,
 metin TEXT,zaman TEXT NOT NULL,okundu INTEGER DEFAULT 0,
 UNIQUE(kullanici_adi,olay),FOREIGN KEY(kayit_id) REFERENCES kayitlar(id)
);
CREATE INDEX IF NOT EXISTS ix_kayit_proje ON kayitlar(proje,silindi,kt);
CREATE INDEX IF NOT EXISTS ix_kayit_tarih ON kayitlar(tarih);
CREATE INDEX IF NOT EXISTS ix_kayit_personel ON kayitlar(personel);
CREATE INDEX IF NOT EXISTS ix_kayit_ekleyen ON kayitlar(ekleyen_id,proje,id);
CREATE INDEX IF NOT EXISTS ix_kayit_uye ON kayitlar(proje,uye_id,silindi);
CREATE INDEX IF NOT EXISTS ix_kayit_ana_uye ON kayitlar(proje,ana_uye_id,silindi);
CREATE INDEX IF NOT EXISTS ix_kayit_lead ON kayitlar(proje,lead_id,silindi);
CREATE INDEX IF NOT EXISTS ix_denetim_zaman ON denetim(zaman);
CREATE INDEX IF NOT EXISTS ix_denetim_proje ON denetim(proje,id);
CREATE INDEX IF NOT EXISTS ix_denetim_anahtar ON denetim(anahtar,id);
CREATE INDEX IF NOT EXISTS ix_bildirim_kullanici ON bildirimler(kullanici_adi,okundu,id);
CREATE INDEX IF NOT EXISTS ix_mesaj_alici ON mesaj_bildirimleri(kullanici_adi,okundu,id);
'''
DEFAULT_CATEGORIES = [
 ('ark','ARK','ark_ana'),('dds','DDS','sessiz_tip'),('ddt','DDT','sessiz_tip'),
 ('hgst','HGST','tek_uye'),('prcst','PRCST','tek_uye'),('lpst','LPST','ana_only'),
 ('cvpsz','CVPS','tek_uye'),('btagsz','btagsz','tek_uye'),('30gn','30gün','tek_uye'),
 ('sark','S.ARK','ark_ana'),
]
_MIGRATION_LOCK = threading.RLock()


def simdi():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


@contextmanager
def transaction(conn):
    if conn.in_transaction:
        yield conn
        return
    conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def ayar_al(conn, anahtar, varsayilan=None):
    row = conn.execute('SELECT deger FROM ayarlar WHERE anahtar=?', (anahtar,)).fetchone()
    return row['deger'] if row else varsayilan


def ayar_yaz(conn, anahtar, deger):
    conn.execute('INSERT INTO ayarlar(anahtar,deger) VALUES(?,?) ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger',
                 (anahtar, str(deger)))


def _ready(conn):
    try:
        return ayar_al(conn, 'core_schema_21') == '1'
    except sqlite3.OperationalError:
        return False


def _add_columns(conn, table, definitions):
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(' + table + ')')}
    for name, kind in definitions:
        if name not in columns:
            conn.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + name + ' ' + kind)


def baglan(yol):
    path = os.path.abspath(yol)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.create_collation('UNICODE_NOCASE', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=FULL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    if _ready(conn):
        return conn
    try:
        with _MIGRATION_LOCK, transaction(conn):
            if _ready(conn):
                return conn
            existing = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='kategoriler'").fetchone()
            for statement in SEMA.split(';'):
                if statement.strip():
                    conn.execute(statement)
            if not existing:
                conn.executemany('INSERT OR IGNORE INTO kategoriler(code,label,mode) VALUES(?,?,?)', DEFAULT_CATEGORIES)
            _add_columns(conn, 'yorumlar', [('yanit_id','INTEGER'),('alici','TEXT'),('tur',"TEXT DEFAULT 'yorum'")])
            _add_columns(conn, 'tg_kullanicilar', [('ana_proje','TEXT')])
            _add_columns(conn, 'denetim', [('sonuc',"TEXT DEFAULT 'ok'"),('hedef_turu','TEXT'),('hedef_id','TEXT'),('aciklama','TEXT')])
            from . import katalog, donusum_isleri, yetki
            katalog.ensure_schema(conn)
            donusum_isleri.ensure_schema(conn)
            yetki.eski_wildcardlari_sabitle(conn, [p['code'] for p in katalog.list_projects(conn)])
            ayar_yaz(conn, 'core_schema_21', '1')
        return conn
    except BaseException:
        conn.close()
        raise


def denetim_yaz(conn, kullanici, islem, proje=None, anahtar=None, eski=None, yeni=None, ip=None,
                *, sonuc=None, hedef_turu=None, hedef_id=None, aciklama=None):
    from .guvenli_log import serialize, text
    action = text(islem)[:80]
    if sonuc is None:
        sonuc = 'hata' if 'hata' in action or 'basarisiz' in action else ('uyari' if 'yerel_korundu' in action else 'ok')
    if hedef_turu is None:
        hedef_turu = 'kayit' if proje and anahtar else ('kategori' if 'kategori' in action else 'hesap' if 'kullanici' in action or 'yetki' in action else 'sistem')
    conn.execute('INSERT INTO denetim(zaman,kullanici,islem,proje,anahtar,eski,yeni,ip,sonuc,hedef_turu,hedef_id,aciklama) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                 (simdi(), text(kullanici)[:120], action, proje, anahtar, serialize(eski), serialize(yeni), ip,
                  sonuc, hedef_turu, str(hedef_id) if hedef_id is not None else anahtar, text(aciklama)[:1000] if aciklama else None))


def degisti(conn):
    ayar_yaz(conn, 'son_degisiklik', datetime.now().isoformat(timespec='microseconds'))


def bildirim_uret(conn, kayit_id):
    from . import yetki
    row = conn.execute('SELECT proje FROM kayitlar WHERE id=?', (kayit_id,)).fetchone()
    if not row:
        return
    for user in conn.execute('SELECT kullanici_adi,yetki FROM panel_kullanicilari WHERE aktif=1').fetchall():
        if yetki.izin(yetki.coz(user['yetki']), row['proje'], 'kt'):
            conn.execute('INSERT OR IGNORE INTO bildirimler(kullanici_adi,kayit_id,proje,zaman) VALUES(?,?,?,?)',
                         (user['kullanici_adi'], kayit_id, row['proje'], simdi()))


def mesaj_bildir(conn, kayit_id, alici, tur, kim, metin, olay):
    from . import yetki
    if not alici or alici == kim:
        return
    record = conn.execute('SELECT proje FROM kayitlar WHERE id=?', (kayit_id,)).fetchone()
    user = conn.execute('SELECT yetki FROM panel_kullanicilari WHERE kullanici_adi=? AND aktif=1', (alici,)).fetchone()
    if not record or not user or not yetki.izin(yetki.coz(user['yetki']), record['proje'], 'oku'):
        return
    conn.execute('INSERT OR IGNORE INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                 (alici, kayit_id, record['proje'], olay, tur, kim, str(metin)[:300], simdi()))
