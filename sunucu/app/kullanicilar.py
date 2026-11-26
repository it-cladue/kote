"""SQL hesapları: hash'li parola, kalıcı kilit, kanonik rol ve oturum sürümü."""
import re
import secrets
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


def ekle(ayar, ad, yetki_metni, sifre, gorunen_ad=None, olusturan=None, ip=None):
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
        db.denetim_yaz(conn, olusturan or 'sunucu-cli', 'kullanici_ekle', anahtar=ad, ip=ip,
                       yeni={'ad': gorunen_ad or ad, 'yetki': role, 'aktif': 1}, hedef_turu='hesap', hedef_id=ad)
        db.degisti(conn)


def guncelle(ayar, ad, expected_version=None, islem_yapan=None, ip=None, **alanlar):
    ad = str(ad or '').strip().lower()
    if 'gorunen_ad' in alanlar:
        # 'ad' konumsal parametre kullanıcı adıdır; görünen ad alanı 'gorunen_ad' anahtarıyla gelir.
        alanlar['ad'] = str(alanlar.pop('gorunen_ad') or ad)[:120]
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
        # İyimser kilit ayrı sayaçta (hesap_surumu): yalnız bu fonksiyon artırır; kullanıcının çıkışı (session_version+1) admin formunu düşürmez.
        if expected_version is not None and str(user['hesap_surumu']) != str(expected_version):
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
        # 2.4.0: son etkin sahip de kapatılamaz/düşürülemez (sahip hiç yoksa kural uygulanmaz; ilk atama ayrı adımdır).
        was_sahip = yetki.coz(user['yetki'])['sahip'] and user['aktif']
        will_sahip = yetki.coz(alanlar.get('yetki', user['yetki']))['sahip'] and alanlar.get('aktif', user['aktif'])
        if was_sahip and not will_sahip and aktif_sahip_sayisi(conn) <= 1:
            raise ValueError('Son sahip hesabı kapatılamaz veya rolü düşürülemez. Önce başka bir hesabı sahip yapın.')
        changed = {key: value for key, value in alanlar.items() if user[key] != value}
        # "Kaydet" kilidi de açar: hiçbir alan değişmese bile kilitli ya da hatalı giriş sayacı dolu hesap sıfırlanır (Kullanıcılar sayfası etiketi bunu söyler).
        kilit_acilir = bool(user['kilit_bitis']) or (user['hatali_giris'] or 0) > 0
        if changed:
            sets = ','.join(key + '=?' for key in changed)
            conn.execute('UPDATE panel_kullanicilari SET ' + sets + ',session_version=session_version+1,hesap_surumu=hesap_surumu+1,hatali_giris=0,kilit_bitis=NULL WHERE kullanici_adi=?',
                         (*changed.values(), ad))
            public_keys = [key for key in changed if key != 'sifre_hash']
            before = {key: user[key] for key in public_keys}
            after = {key: changed[key] for key in public_keys}
            if password_changed:
                after['parola_degisti'] = True
            db.denetim_yaz(conn, islem_yapan or ad, 'kullanici_guncelle', anahtar=ad, ip=ip,
                           eski=before, yeni=after, hedef_turu='hesap', hedef_id=ad)
            db.degisti(conn)
        elif kilit_acilir:
            conn.execute('UPDATE panel_kullanicilari SET hatali_giris=0,kilit_bitis=NULL WHERE kullanici_adi=?', (ad,))
        if kilit_acilir:
            aciklama = ('%d hatalı deneme sayacı sıfırlandı' % (user['hatali_giris'] or 0)) + ('; kilit %s kadar sürecekti' % user['kilit_bitis'][11:16] if kilitli_mi(user) else '')
            db.denetim_yaz(conn, islem_yapan or ad, 'kilit_ac', anahtar=ad, ip=ip, eski={'hatali_giris': user['hatali_giris'], 'kilit_bitis': user['kilit_bitis']},
                           yeni={'hatali_giris': 0, 'kilit_bitis': None}, hedef_turu='hesap', hedef_id=ad, aciklama=aciklama)
            db.degisti(conn)
    return bul(ayar, ad)


# Var olmayan/pasif/kilitli kullanıcı için de aynı hash maliyeti ödenir; yanıt süresi ve mesaj kullanıcı adının varlığını
# ya da kilidi açık etmez (kilit yalnız İşlem Geçmişi'nde ve Kullanıcılar sayfasında görünür).
_SAHTE_HASH = generate_password_hash(secrets.token_hex(16))
GENEL_HATA = 'Kullanıcı adı veya parola hatalı.'
KILIT_DAKIKA = 15
KILIT_DENEME = 5

# Yeni parola belirlenirken reddedilen çok yaygın parolalar (küçük harfle karşılaştırılır). Mevcut girişleri etkilemez.
YAYGIN_PAROLALAR = frozenset("""
123456 1234567 12345678 123456789 1234567890 12345 123123 123321 111111 000000 654321 987654321 password password1 password123
passw0rd parola parola1 parola123 sifre sifre123 sifre1234 qwerty qwerty123 qwertyuiop asdfgh asdf1234 zxcvbnm abc123 abcd1234
admin admin1 admin123 admin1234 administrator root toor letmein welcome welcome1 iloveyou monkey dragon football baseball master
sunshine princess superman trustno1 telecc telecc1 telecc123 telecc1234 kanit kanit123 kanit1234 panel123 panel1234 deneme123 test123
test1234 1q2w3e4r 1qaz2wsx 123qwe 159753 112233 a123456 qwe123 pass123 pass1234 passwort changeme default guest12345
""".split())


def parola_politikasi(ad, yeni, eski=None):
    """Yeni parola kuralları; hata metni ya da None. Yalnız parola BELİRLENİRKEN uygulanır, giriş akışını etkilemez."""
    yeni = yeni or ''
    ad = (ad or '').strip().lower()
    if len(yeni) < 8:
        return 'Parola en az 8 karakter olmalı.'
    if len(yeni) > 200:
        return 'Parola en çok 200 karakter olabilir.'
    if eski is not None and yeni == eski:
        return 'Yeni parola eskisiyle aynı olamaz.'
    if len(ad) >= 3 and ad in yeni.lower():
        return 'Parola kullanıcı adını içeremez.'
    duz = yeni.lower().strip()
    if duz in YAYGIN_PAROLALAR or duz.rstrip('!.?*') in YAYGIN_PAROLALAR:
        return 'Bu parola çok yaygın; tahmin edilmesi kolay. Harf, rakam ve işaret karışımı daha uzun bir parola seçin.'
    return None


def parola_dogru(ayar, ad, sifre):
    """Oturumu açık kullanıcının mevcut parolasını doğrular; kilit sayacına DOKUNMAZ (/sifre sayfası için).
    Olmayan/pasif hesapta da hash maliyeti ödenir."""
    user = bul(ayar, ad)
    if not user or not user['aktif']:
        check_password_hash(_SAHTE_HASH, sifre or '')
        return False
    return check_password_hash(user['sifre_hash'], sifre or '')


def kilitli_mi(user):
    return bool(user and user['kilit_bitis'] and user['kilit_bitis'] > db.simdi())


def dogrula(ayar, ad, sifre, ip=None):
    """(kullanıcı, hata) döndürür. Kilitli, pasif veya olmayan hesapta da aynı genel mesaj ve aynı hash maliyeti.
    Kilit: 5 hatalı deneme → 15 dakika; süresi dolan kilidin sayacı sıfırdan başlar (süresiz kilit DoS'u yok)."""
    ad = (ad or '').strip().lower()
    with connection(ayar) as conn, db.transaction(conn):
        user = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()
        if not user:
            check_password_hash(_SAHTE_HASH, sifre or '')
            return None, GENEL_HATA
        if kilitli_mi(user):
            # Kilitliyken doğru parola da kabul edilmez; sayaç ve kilit süresi değişmez (kilit kendiliğinden biter).
            check_password_hash(_SAHTE_HASH, sifre or '')
            return None, GENEL_HATA
        if user['aktif'] and check_password_hash(user['sifre_hash'], sifre or ''):
            conn.execute('UPDATE panel_kullanicilari SET hatali_giris=0,kilit_bitis=NULL,son_giris=? WHERE id=?', (db.simdi(), user['id']))
            return dict(user), None
        if not user['aktif']:
            check_password_hash(_SAHTE_HASH, sifre or '')
        # Süresi dolmuş kilidin (kilit_bitis dolu ama geçmişte) sayacı sıfırlanır; aksi hâlde tek hatalı deneme kilidi süresiz uzatır.
        attempts = (0 if user['kilit_bitis'] else user['hatali_giris']) + 1
        until = (datetime.now() + timedelta(minutes=KILIT_DAKIKA)).strftime('%Y-%m-%d %H:%M:%S') if attempts >= KILIT_DENEME else None
        conn.execute('UPDATE panel_kullanicilari SET hatali_giris=?,kilit_bitis=? WHERE id=?', (attempts, until, user['id']))
        if until:
            db.denetim_yaz(conn, ad, 'giris_kilit', ip=ip, sonuc='uyari', hedef_turu='hesap', hedef_id=ad,
                           aciklama='%d hatalı deneme; %d dakika kilit' % (KILIT_DENEME, KILIT_DAKIKA))
        return None, GENEL_HATA


# ------------------------------------------------------------------ 2.4.0: sahip rolü, yönetim izinleri ve yazılı onaylar

class Yasak(PermissionError):
    """İşlemi yapanın rolü bu işleme yetmiyor (panel 403 döner)."""


SAHIP_GEREKLI_MESAJ = ('Bu işlemi yalnız sahip yapabilir: süperadmin/sahip hesaplarını ekleme, düzenleme, pasife alma, '
                       'şifre sıfırlama ve bu rollere yükseltme ya da bu rollerden düşürme.')


def _yonetici_rolu(metin):
    return yetki.rol_kodu(metin) in ('sahip', 'superadmin')


def yonetim_denetimi(islem_yapan_yk, hedef=None, yeni_yetki=None):
    """Süperadmin/sahip hesaplarına ve bu rollere geçişe dokunan her işlem yalnız sahibe açıktır (aksi hâlde Yasak).
    hedef: mevcut hesap satırı (ekleme için None); yeni_yetki: kanonik yeni yetki metni (yetki değişmiyorsa None)."""
    if yetki.sahip_mi(islem_yapan_yk):
        return
    if hedef is not None and _yonetici_rolu(hedef.get('yetki')):
        raise Yasak(SAHIP_GEREKLI_MESAJ)
    if yeni_yetki is not None and _yonetici_rolu(yeni_yetki):
        raise Yasak(SAHIP_GEREKLI_MESAJ)


def onay_gerekli(hedef, yeni_yetki=None, yeni_aktif=None):
    """Yazılı onay (hedef kullanıcı adını yazma) isteyen tehlikeli değişiklik mi? Açıklama metni ya da None.
    Kurallar: rol sınıfı değişikliği (proje kullanıcısı ↔ süperadmin ↔ sahip) ve süperadmin/sahip hesabını pasife alma."""
    eski_rol = yetki.rol_kodu(hedef.get('yetki'))
    if yeni_yetki is not None:
        yeni_rol = yetki.rol_kodu(yeni_yetki)
        if yeni_rol != eski_rol:
            return 'Rol değişikliği: %s → %s' % (yetki.ROL_ADLARI[eski_rol], yetki.ROL_ADLARI[yeni_rol])
    if yeni_aktif is not None and not yeni_aktif and hedef.get('aktif') and eski_rol != 'proje':
        return '%s hesabını pasife alma' % yetki.ROL_ADLARI[eski_rol]
    return None


def onay_dogru(beklenen, yazilan):
    """Yazılı onay: baş/son boşluk ve büyük-küçük harf önemsiz, aksi hâlde birebir aynı olmalı."""
    return bool(str(beklenen or '').strip()) and str(yazilan or '').strip().casefold() == str(beklenen).strip().casefold()


def aktif_sahip_sayisi(conn):
    return sum(1 for r in conn.execute('SELECT yetki FROM panel_kullanicilari WHERE aktif=1') if yetki.coz(r['yetki'])['sahip'])


def aktif_sahip_var(ayar):
    with connection(ayar) as conn:
        return aktif_sahip_sayisi(conn) > 0


def sahip_ata(ayar, ad, islem_yapan, ip=None):
    """İlk sahip ataması (kurulum adımı): etkin sahip yokken bir süperadmin TEK bir hesabı (kendisi dahil) sahip yapar.
    Etkin sahip varsa ValueError. İşlem İşlem Geçmişi'ne 'sahip_atama' olarak yazılır; hedef hesabın oturumu düşer."""
    ad = str(ad or '').strip().lower()
    with connection(ayar) as conn, db.transaction(conn):
        if aktif_sahip_sayisi(conn):
            raise ValueError('Zaten etkin bir sahip hesabı var; yeni sahip atamasını yalnız sahip, Kullanıcılar listesinden yapar.')
        user = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()
        if not user or not user['aktif']:
            raise ValueError('Sahip yapılacak hesap bulunamadı ya da pasif.')
        conn.execute("UPDATE panel_kullanicilari SET yetki='sahip',session_version=session_version+1,hesap_surumu=hesap_surumu+1 "
                     "WHERE kullanici_adi=?", (ad,))
        db.denetim_yaz(conn, islem_yapan or 'sunucu-cli', 'sahip_atama', anahtar=ad, ip=ip, eski={'yetki': user['yetki']},
                       yeni={'yetki': 'sahip'}, hedef_turu='hesap', hedef_id=ad, aciklama='İlk sahip ataması (etkin sahip yokken)')
        db.degisti(conn)
    return bul(ayar, ad)
