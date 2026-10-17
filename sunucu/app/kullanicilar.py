"""SQL hesapları: hash'li parola, kalıcı kilit, kanonik rol ve oturum sürümü."""
import re
from datetime import datetime, timedelta
from contextlib import contextmanager
from werkzeug.security import generate_password_hash, check_password_hash
from . import db, yetki


@contextmanager
def connection(ayar):
    conn = db.baglan(ayar['DB'])
    try:
        yield conn
    finally:
        conn.close()


def yol(ayar):
    return ayar['DB']


def var_mi(ayar):
    with connection(ayar) as conn:
        return bool(conn.execute('SELECT 1 FROM panel_kullanicilari LIMIT 1').fetchone())


def bul(ayar, ad):
    with connection(ayar) as conn:
        row = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', ((ad or '').strip().lower(),)).fetchone()
        return dict(row) if row else None


def hepsi(ayar):
    with connection(ayar) as conn:
        return [dict(r) for r in conn.execute('SELECT * FROM panel_kullanicilari ORDER BY kullanici_adi')]


def _canonical(conn, role):
    codes = [r[0] for r in conn.execute('SELECT code FROM projeler')]
    return yetki.kanonikle(role, codes)


def ekle(ayar, ad, yetki_metni, sifre, gorunen_ad=None, olusturan=None):
    ad = (ad or '').strip().lower()
    if not re.fullmatch(r'[a-z0-9_.]{1,40}', ad):
        raise ValueError('Kullanıcı adı a-z, rakam, nokta/alt çizgi olmalı.')
    if len(sifre or '') < 8:
        raise ValueError('Parola en az 8 karakter olmalı.')
    hash_value = generate_password_hash(sifre)
    with connection(ayar) as conn, db.transaction(conn):
        role = _canonical(conn, yetki_metni)
        if conn.execute('SELECT 1 FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone():
            raise ValueError('Bu kullanıcı adı zaten var.')
        conn.execute('INSERT INTO panel_kullanicilari(kullanici_adi,ad,sifre_hash,yetki,olusturma,sifre_degistir) VALUES(?,?,?,?,?,1)',
                     (ad, (gorunen_ad or ad)[:120], hash_value, role, db.simdi()))
        db.denetim_yaz(conn, olusturan or 'sunucu-cli', 'kullanici_ekle', anahtar=ad,
                       yeni={'ad': gorunen_ad or ad, 'yetki': role, 'aktif': 1}, hedef_turu='hesap', hedef_id=ad)
        db.degisti(conn)


def guncelle(ayar, ad, expected_version=None, islem_yapan=None, **alanlar):
    ad = str(ad or '').strip().lower()
    password_changed = 'sifre' in alanlar
    if password_changed:
        if len(alanlar['sifre'] or '') < 8:
            raise ValueError('Parola en az 8 karakter olmalı.')
        alanlar['sifre_hash'] = generate_password_hash(alanlar.pop('sifre'))
    allowed = {'sifre_hash', 'yetki', 'aktif', 'sifre_degistir', 'ad'}
    if any(k not in allowed for k in alanlar):
        raise ValueError('Geçersiz hesap alanı.')
    with connection(ayar) as conn, db.transaction(conn):
        user = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()
        if not user:
            raise ValueError('Kullanıcı bulunamadı.')
        if expected_version is not None and str(user['session_version']) != str(expected_version):
            raise ValueError('Hesap başka bir admin tarafından değiştirildi; sayfayı yenileyin.')
        if 'yetki' in alanlar:
            alanlar['yetki'] = _canonical(conn, alanlar['yetki'])
        for flag in ('aktif', 'sifre_degistir'):
            if flag in alanlar and alanlar[flag] not in (0, 1, False, True):
                raise ValueError('Geçersiz hesap durumu.')
        was_admin = yetki.coz(user['yetki'])['admin'] and user['aktif']
        will_admin = yetki.coz(alanlar.get('yetki', user['yetki']))['admin'] and alanlar.get('aktif', user['aktif'])
        if was_admin and not will_admin:
            count = sum(yetki.coz(r['yetki'])['admin'] for r in conn.execute('SELECT yetki FROM panel_kullanicilari WHERE aktif=1'))
            if count <= 1:
                raise ValueError('Son süperadmin kapatılamaz veya yetkisi kaldırılamaz.')
        changed = {key: value for key, value in alanlar.items() if user[key] != value}
        if changed:
            sets = ','.join(key + '=?' for key in changed)
            conn.execute('UPDATE panel_kullanicilari SET ' + sets + ',session_version=session_version+1,hatali_giris=0,kilit_bitis=NULL WHERE kullanici_adi=?',
                         (*changed.values(), ad))
            public_keys = [key for key in changed if key != 'sifre_hash']
            before = {key: user[key] for key in public_keys}
            after = {key: changed[key] for key in public_keys}
            if password_changed:
                after['parola_degisti'] = True
            db.denetim_yaz(conn, islem_yapan or ad, 'kullanici_guncelle', anahtar=ad,
                           eski=before, yeni=after, hedef_turu='hesap', hedef_id=ad)
            db.degisti(conn)
    return bul(ayar, ad)


def dogrula(ayar, ad, sifre):
    ad = (ad or '').strip().lower()
    with connection(ayar) as conn, db.transaction(conn):
        user = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()
        if user and user['kilit_bitis'] and user['kilit_bitis'] > db.simdi():
            return None, 'Çok fazla hatalı deneme; 15 dakika sonra tekrar deneyin.'
        if user and user['aktif'] and check_password_hash(user['sifre_hash'], sifre or ''):
            conn.execute('UPDATE panel_kullanicilari SET hatali_giris=0,kilit_bitis=NULL,son_giris=? WHERE id=?', (db.simdi(), user['id']))
            return dict(user), None
        if user:
            attempts = user['hatali_giris'] + 1
            until = (datetime.now() + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S') if attempts >= 5 else None
            conn.execute('UPDATE panel_kullanicilari SET hatali_giris=?,kilit_bitis=? WHERE id=?', (attempts, until, user['id']))
        return None, 'Kullanıcı adı veya parola hatalı.'
