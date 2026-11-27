"""2.4.1 — İki adımlı doğrulama (TOTP; Google Authenticator / Microsoft Authenticator / Authy uyumlu).

Algoritma: RFC 4226 (HOTP) + RFC 6238 (TOTP), HMAC-SHA1, 6 hane, 30 saniye. Yalnız standart kütüphane (hmac, hashlib,
base64, struct, time). Doğrulama ±1 adım (±30 sn saat kayması) kabul eder, aynı kodun (aynı sayaç ya da daha eskisi) ikinci
kez kullanılmasını son kullanılan sayacı saklayarak reddeder ve karşılaştırmayı sabit zamanlı yapar (hmac.compare_digest).

Saklama (dürüst not): TOTP anahtarı veritabanında DÜZ METİN (base32) tutulur; panel_kullanicilari.iki_adim_sir. Güven sınırı
veritabanı dosyasıdır: dosya yalnız 'kanit' hesabınca okunur (kurulumdaki izinler) ve yedekler aynı özenle saklanmalıdır.
Kurtarma kodları parola karması (werkzeug generate_password_hash) ile, güvenilen cihaz belirteçleri SHA-256 özetiyle saklanır;
düz hâlleri yalnız bir kez ekranda / çerezde bulunur.

Tablolar (db.py şeması, core_schema_241_iki_adim):
  panel_kullanicilari: iki_adim_acik, iki_adim_sir, iki_adim_son_sayac, iki_adim_tarih
  iki_adim_kurtarma:   kullanici_adi, kod_hash, olusturma, kullanildi
  iki_adim_cihazlar:   kullanici_adi, ozet (SHA-256), olusturma, bitis, son_kullanim, son_ip, tarayici
Giriş öncesi işaret (parola doğru, kod bekleniyor) tam oturum DEĞİLDİR: oturumda yalnız rastgele bir numara, sunucuda
ayarlar tablosunda 'iki_adim_on:<numara>' satırı (5 dakika, tek kullanım) bulunur.
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from werkzeug.security import check_password_hash, generate_password_hash

from . import db, yetki

YAYINCI = 'Kanıt Paneli'
ADIM_SN = 30
HANE = 6
KAYMA_ADIM = 1                # ±1 adım = ±30 saniye
KURTARMA_ADET = 8
KURTARMA_UZUNLUK = 10
KURTARMA_UYARI_ESIGI = 2      # bu kadar ya da daha az kod kalınca uyarı
ON_GIRIS_SN = 5 * 60          # parola sonrası kod adımının ömrü
BEKLEYEN_SN = 15 * 60         # kurulumda üretilen (henüz doğrulanmamış) anahtarın ömrü
KOD_DENEME = 5                # hesap başına ...
KOD_PENCERE_DK = 5            # ... bu kadar dakikada en çok hatalı kod; aşılınca hesap parola kilidiyle aynı süre kilitlenir
VARSAYILAN_GUVEN_GUN = 30
POLITIKALAR = ('kapali', 'yonetici', 'hepsi')
_KURTARMA_HARFLERI = 'abcdefghjkmnpqrstuvwxyz23456789'  # karışan 0/o, 1/l/i yok
ON_ONEK = 'iki_adim_on:'
BEKLEYEN_ONEK = 'iki_adim_bekleyen:'


# ---------------------------------------------------------------- TOTP / HOTP

def sir_uret():
    """160 bit rastgele anahtar, base32 (32 karakter, dolgu yok)."""
    return base64.b32encode(secrets.token_bytes(20)).decode('ascii').rstrip('=')


def sir_coz(sir):
    """Base32 anahtarı baytlara çevirir: boşluk/tire ve küçük harf hoş görülür, dolgu kendiliğinden eklenir."""
    temiz = re.sub(r'[\s-]', '', str(sir or '')).upper().rstrip('=')
    if not temiz or not re.fullmatch(r'[A-Z2-7]+', temiz):
        raise ValueError('Geçersiz anahtar (base32 bekleniyor).')
    return base64.b32decode(temiz + '=' * (-len(temiz) % 8))


def sir_grupla(sir):
    """Elle giriş için 4'lü gruplar: 'ABCD EFGH …'."""
    return ' '.join(sir[i:i + 4] for i in range(0, len(sir), 4))


def hotp(anahtar, sayac, hane=HANE, algoritma=hashlib.sha1):
    """RFC 4226: HMAC(anahtar, 8 baytlık sayaç) → dinamik kesme → hane basamak."""
    if isinstance(anahtar, str):
        anahtar = sir_coz(anahtar)
    ozet = hmac.new(anahtar, struct.pack('>Q', int(sayac)), algoritma).digest()
    kayma = ozet[-1] & 0x0F
    sayi = struct.unpack('>I', ozet[kayma:kayma + 4])[0] & 0x7FFFFFFF
    return str(sayi % (10 ** hane)).zfill(hane)


def _saat():
    """TOTP zaman kaynağı: sunucu saati (testler bu işlevi değiştirerek zamanı ilerletir)."""
    return time.time()


def sayac(zaman=None):
    return int((_saat() if zaman is None else zaman) // ADIM_SN)


def totp(anahtar, zaman=None, hane=HANE, algoritma=hashlib.sha1):
    """RFC 6238: T = floor(zaman / 30)."""
    return hotp(anahtar, sayac(zaman), hane, algoritma)


def kod_temizle(girdi):
    return re.sub(r'[\s-]', '', str(girdi or ''))


def kod_dogrula(sir, girdi, son_sayac=0, zaman=None):
    """Geçerli kodun sayacı ya da None. ±KAYMA_ADIM pencere; son_sayac ve öncesi (kullanılmış kod) reddedilir.
    Penceredeki her aday karşılaştırılır (erken çıkış yok); karşılaştırma sabit zamanlıdır."""
    kod = kod_temizle(girdi)
    if not re.fullmatch(r'\d{%d}' % HANE, kod):
        return None
    try:
        anahtar = sir_coz(sir)
    except ValueError:
        return None
    simdiki = sayac(zaman)
    bulunan = None
    for s in range(simdiki - KAYMA_ADIM, simdiki + KAYMA_ADIM + 1):
        if hmac.compare_digest(hotp(anahtar, s), kod) and s > int(son_sayac or 0) and bulunan is None:
            bulunan = s
    return bulunan


def otpauth_uri(kullanici_adi, sir, yayinci=YAYINCI):
    """otpauth://totp/Kan%C4%B1t%20Paneli:<kullanıcı>?secret=…&issuer=…&digits=6&period=30&algorithm=SHA1"""
    etiket = quote(yayinci, safe='') + ':' + quote(str(kullanici_adi), safe='')
    return ('otpauth://totp/%s?secret=%s&issuer=%s&digits=%d&period=%d&algorithm=SHA1'
            % (etiket, sir, quote(yayinci, safe=''), HANE, ADIM_SN))


# ---------------------------------------------------------------- kurtarma kodları

def kurtarma_kodlari_uret(adet=KURTARMA_ADET):
    return [''.join(secrets.choice(_KURTARMA_HARFLERI) for _ in range(KURTARMA_UZUNLUK)) for _ in range(adet)]


def kurtarma_goster(kod):
    return kod[:5] + '-' + kod[5:]


def kurtarma_temizle(girdi):
    return kod_temizle(girdi).lower()


def kurtarma_bicimi_mi(girdi):
    return bool(re.fullmatch('[a-z0-9]{%d}' % KURTARMA_UZUNLUK, kurtarma_temizle(girdi)))


# ---------------------------------------------------------------- ayarlar (Çalışma ayarları)

def politika(conn=None):
    from . import ayarlar
    deger = str(ayarlar.deger('IKI_ADIM_ZORUNLU', conn=conn) or 'kapali').strip().lower()
    return deger if deger in POLITIKALAR else 'kapali'


def guven_gun(conn=None):
    from . import ayarlar
    try:
        gun = int(str(ayarlar.deger('IKI_ADIM_GUVEN_GUN', conn=conn)).strip())
    except (TypeError, ValueError):
        return VARSAYILAN_GUVEN_GUN
    return max(0, min(gun, 365))


def yonetici_mi(kullanici):
    """'yonetici' politikasının kapsamı: sahip, süperadmin ve herhangi bir projede onay (kt) yetkisi olan hesap."""
    yk = yetki.coz((kullanici or {}).get('yetki', ''))
    return bool(yk['admin'] or any('kt' in eylemler for eylemler in yk['projeler'].values()))


HESAP_AYARLARI = ('politika', 'zorunlu', 'degil')
HESAP_AYAR_ADLARI = {'politika': 'politikaya göre', 'zorunlu': 'zorunlu', 'degil': 'zorunlu değil'}
POLITIKA_ADLARI = {'kapali': 'isteğe bağlı', 'yonetici': 'yöneticilere zorunlu', 'hepsi': 'herkese zorunlu'}


def hesap_ayari(kullanici):
    """2.4.2: hesabın kendi zorunluluk ayarı: 'zorunlu' (1) | 'degil' (0) | 'politika' (NULL / sütun yok)."""
    deger = (kullanici or {}).get('iki_adim_zorunlu')
    if deger is None or deger == '':
        return 'politika'
    try:
        return 'zorunlu' if int(deger) else 'degil'
    except (TypeError, ValueError):
        return 'politika'


def hesap_ayari_degeri(metin):
    """Form / CLI girdisini sütun değerine çevirir: 'zorunlu'/'evet'/'1' → 1, 'degil'/'hayir'/'0' → 0,
    'politika'/'' → None. Tanınmayan girdi ValueError."""
    m = str('' if metin is None else metin).strip().lower()
    if m in ('', 'politika', 'null', 'none'):
        return None
    if m in ('1', 'zorunlu', 'evet', 'on', 'true'):
        return 1
    if m in ('0', 'degil', 'değil', 'hayir', 'hayır', 'off', 'false'):
        return 0
    raise ValueError('İki adımlı doğrulama zorunluluğu için geçersiz değer: zorunlu, zorunlu değil ya da politikaya göre seçin.')


def zorunlu_mu(kullanici, pol=None, conn=None):
    """Etkin zorunluluk: önce hesabın kendi ayarı (2.4.2), o 'politikaya göre' ise genel politika."""
    ayar = hesap_ayari(kullanici)
    if ayar == 'zorunlu':
        return True
    if ayar == 'degil':
        return False
    pol = pol or politika(conn)
    if pol == 'hepsi':
        return True
    if pol == 'yonetici':
        return yonetici_mi(kullanici)
    return False


def acik_mi(kullanici):
    return bool(kullanici and kullanici.get('iki_adim_acik') and kullanici.get('iki_adim_sir'))


def durum_etiketi(kullanici, pol=None, conn=None):
    """Kullanıcılar sayfası sütunu: 'acik' | 'zorunlu_bekliyor' | 'yok'."""
    if acik_mi(kullanici):
        return 'acik'
    return 'zorunlu_bekliyor' if zorunlu_mu(kullanici, pol, conn) else 'yok'


# ---------------------------------------------------------------- kurulum / kapatma / sıfırlama

def _kullanici(conn, ad):
    row = conn.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()
    return dict(row) if row else None


def bekleyen_al(conn, ad, olustur=False):
    """Kurulum sırasında gösterilen, henüz hesaba yazılmamış anahtar (15 dk). olustur=True ise yoksa yenisi üretilir."""
    anahtar = BEKLEYEN_ONEK + ad
    ham = db.ayar_al(conn, anahtar)
    veri = None
    if ham:
        try:
            veri = json.loads(ham)
        except ValueError:
            veri = None
    if veri and time.time() - float(veri.get('zaman', 0)) <= BEKLEYEN_SN and veri.get('sir'):
        return veri['sir']
    if not olustur:
        if ham:
            with db.transaction(conn):
                conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (anahtar,))
        return None
    sir = sir_uret()
    with db.transaction(conn):
        db.ayar_yaz(conn, anahtar, json.dumps({'sir': sir, 'zaman': time.time()}))
    return sir


def bekleyen_sil(conn, ad):
    with db.transaction(conn):
        conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (BEKLEYEN_ONEK + ad,))


def _kurtarma_yaz(conn, ad):
    kodlar = kurtarma_kodlari_uret()
    conn.execute('DELETE FROM iki_adim_kurtarma WHERE kullanici_adi=?', (ad,))
    zaman = db.simdi()
    conn.executemany('INSERT INTO iki_adim_kurtarma(kullanici_adi,kod_hash,olusturma) VALUES(?,?,?)',
                     [(ad, generate_password_hash(k), zaman) for k in kodlar])
    return kodlar


def etkinlestir(conn, ad, sir, kod, kim=None, ip=None):
    """Bekleyen anahtarı geçerli bir kodla hesaba yazar. Dönüş: düz kurtarma kodları (yalnız bir kez gösterilir).
    Geçersiz kodda ValueError. Yeniden kurulumda eski anahtar ve kurtarma kodları değişir."""
    s = kod_dogrula(sir, kod, 0)
    if s is None:
        raise ValueError('Kod doğrulanamadı. Uygulamadaki güncel 6 haneli kodu girin; telefonun saati otomatik olmalı.')
    with db.transaction(conn):
        u = _kullanici(conn, ad)
        if not u:
            raise ValueError('Hesap bulunamadı.')
        yeniden = acik_mi(u)
        conn.execute('UPDATE panel_kullanicilari SET iki_adim_acik=1,iki_adim_sir=?,iki_adim_son_sayac=?,iki_adim_tarih=? WHERE kullanici_adi=?',
                     (sir, s, db.simdi(), ad))
        kodlar = _kurtarma_yaz(conn, ad)
        conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (BEKLEYEN_ONEK + ad,))
        db.denetim_yaz(conn, kim or ad, '2fa_ac', ip=ip, hedef_turu='hesap', hedef_id=ad,
                       aciklama='İki adımlı doğrulama yeniden kuruldu (yeni anahtar)' if yeniden else 'İki adımlı doğrulama açıldı')
    return kodlar


def _temizle(conn, ad):
    conn.execute('UPDATE panel_kullanicilari SET iki_adim_acik=0,iki_adim_sir=NULL,iki_adim_son_sayac=0,iki_adim_tarih=NULL WHERE kullanici_adi=?', (ad,))
    conn.execute('DELETE FROM iki_adim_kurtarma WHERE kullanici_adi=?', (ad,))
    sayi = conn.execute('DELETE FROM iki_adim_cihazlar WHERE kullanici_adi=?', (ad,)).rowcount
    conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (BEKLEYEN_ONEK + ad,))
    return sayi


def kapat(conn, ad, kim=None, ip=None):
    """Kullanıcının kendi isteğiyle kapatma (parola + kod denetimi çağıranda). Anahtar, kurtarma kodları, güvenilen cihazlar silinir."""
    with db.transaction(conn):
        cihaz = _temizle(conn, ad)
        db.denetim_yaz(conn, kim or ad, '2fa_kapat', ip=ip, hedef_turu='hesap', hedef_id=ad,
                       aciklama='İki adımlı doğrulama kapatıldı; %d güvenilen cihaz kaldırıldı' % cihaz)


def sifirla(conn, ad, kim, ip=None):
    """Sahip ya da sunucu (CLI) sıfırlaması: anahtar, kurtarma kodları ve güvenilen cihazlar silinir, açık oturumlar kapanır.
    Kullanıcı bir sonraki girişte (hesap ayarı ya da politika zorunlu kılıyorsa) yeniden kurar. Dönüş: (önceden açık mıydı, silinen cihaz)."""
    with db.transaction(conn):
        u = _kullanici(conn, ad)
        if not u:
            raise ValueError('Hesap bulunamadı.')
        onceki = acik_mi(u)
        cihaz = _temizle(conn, ad)
        conn.execute('UPDATE panel_kullanicilari SET session_version=session_version+1,hesap_surumu=hesap_surumu+1 WHERE kullanici_adi=?', (ad,))
        db.denetim_yaz(conn, kim, '2fa_sifirla', anahtar=ad, ip=ip, eski={'iki_adim': 'açık' if onceki else 'kapalı'},
                       yeni={'iki_adim': 'kapalı'}, hedef_turu='hesap', hedef_id=ad,
                       aciklama='İki adımlı doğrulama sıfırlandı; %d güvenilen cihaz kaldırıldı, açık oturumlar kapandı' % cihaz)
    return onceki, cihaz


def kurtarma_yenile(conn, ad, kim=None, ip=None):
    with db.transaction(conn):
        u = _kullanici(conn, ad)
        if not acik_mi(u):
            raise ValueError('İki adımlı doğrulama açık değil.')
        kodlar = _kurtarma_yaz(conn, ad)
        db.denetim_yaz(conn, kim or ad, '2fa_kurtarma_yenile', ip=ip, hedef_turu='hesap', hedef_id=ad,
                       aciklama='Yeni %d kurtarma kodu üretildi; eskiler geçersiz' % len(kodlar))
    return kodlar


def kalan_kurtarma(conn, ad):
    return conn.execute('SELECT COUNT(*) FROM iki_adim_kurtarma WHERE kullanici_adi=? AND kullanildi IS NULL', (ad,)).fetchone()[0]


def kod_kontrol(conn, ad, girdi, ip=None, kurtarma_kabul=True, kim=None):
    """Hesabın anahtarıyla 6 haneli kodu ya da kurtarma kodunu doğrular ve TÜKETİR (tek işlem içinde).
    Dönüş: 'totp' | 'kurtarma' | None. TOTP'de son sayaç güncellenir (aynı kod yeniden kullanılamaz);
    kurtarma kodu kullanıldı olarak işaretlenir ve '2fa_kurtarma_kullanildi' yazılır."""
    with db.transaction(conn):
        u = _kullanici(conn, ad)
        if not acik_mi(u):
            return None
        temiz = kod_temizle(girdi)
        if re.fullmatch(r'\d{%d}' % HANE, temiz):
            s = kod_dogrula(u['iki_adim_sir'], temiz, u['iki_adim_son_sayac'] or 0)
            if s is None:
                return None
            conn.execute('UPDATE panel_kullanicilari SET iki_adim_son_sayac=? WHERE kullanici_adi=? AND COALESCE(iki_adim_son_sayac,0)<?',
                         (s, ad, s))
            return 'totp'
        if kurtarma_kabul and kurtarma_bicimi_mi(temiz):
            kod = kurtarma_temizle(temiz)
            eslesen = None
            for r in conn.execute('SELECT id,kod_hash FROM iki_adim_kurtarma WHERE kullanici_adi=? AND kullanildi IS NULL', (ad,)).fetchall():
                if check_password_hash(r['kod_hash'], kod) and eslesen is None:
                    eslesen = r['id']
            if eslesen is None:
                return None
            conn.execute('UPDATE iki_adim_kurtarma SET kullanildi=? WHERE id=?', (db.simdi(), eslesen))
            kalan = conn.execute('SELECT COUNT(*) FROM iki_adim_kurtarma WHERE kullanici_adi=? AND kullanildi IS NULL', (ad,)).fetchone()[0]
            db.denetim_yaz(conn, kim or ad, '2fa_kurtarma_kullanildi', ip=ip, sonuc='uyari', hedef_turu='hesap', hedef_id=ad,
                           aciklama='Kurtarma kodu kullanıldı; %d kod kaldı' % kalan)
            return 'kurtarma'
        return None


def son_hatalar(conn, ad):
    esik = (datetime.now() - timedelta(minutes=KOD_PENCERE_DK)).strftime('%Y-%m-%d %H:%M:%S')
    return conn.execute("SELECT COUNT(*) FROM denetim WHERE islem='2fa_hata' AND kullanici=? AND zaman>?", (ad, esik)).fetchone()[0]


def hata_kaydet(conn, ad, ip=None, kilit_dk=15):
    """Hatalı kod: '2fa_hata' satırı ve hesabın hatalı deneme sayacı. Pencerede KOD_DENEME'ye ulaşılırsa parola akışındaki gibi
    kilit (kilit_bitis) ve 'giris_kilit' satırı. Dönüş: kilitlendi mi."""
    with db.transaction(conn):
        db.denetim_yaz(conn, ad, '2fa_hata', ip=ip, hedef_turu='hesap', hedef_id=ad)
        conn.execute('UPDATE panel_kullanicilari SET hatali_giris=COALESCE(hatali_giris,0)+1 WHERE kullanici_adi=?', (ad,))
        if son_hatalar(conn, ad) >= KOD_DENEME:
            bitis = (datetime.now() + timedelta(minutes=kilit_dk)).strftime('%Y-%m-%d %H:%M:%S')
            conn.execute('UPDATE panel_kullanicilari SET kilit_bitis=? WHERE kullanici_adi=?', (bitis, ad))
            db.denetim_yaz(conn, ad, 'giris_kilit', ip=ip, sonuc='uyari', hedef_turu='hesap', hedef_id=ad,
                           aciklama='%d dakikada %d hatalı doğrulama kodu; %d dakika kilit' % (KOD_PENCERE_DK, KOD_DENEME, kilit_dk))
            return True
    return False


IP_PENCERE_DK = 15             # IP başına hatalı deneme penceresi (parola + doğrulama kodu; panel.py _ip_hata_sayisi ile aynı)


def kod_dene(conn, ad, girdi, ip=None, kilit_dk=15, ip_sinir=None, kim=None):
    """Kilit denetimi, deneme sayımı ve kod denetimi TEK işlemde (BEGIN IMMEDIATE): aynı anda gelen istekler sırayla
    işlenir, böylece hesap başına KOD_DENEME / KOD_PENCERE_DK sınırı ve IP sınırı paralel isteklerle aşılamaz.
    Dönüş: 'totp' | 'kurtarma' (doğru) | 'hata' (yanlış, kayıt yazıldı) | 'kilit' (yanlış ve hesap şimdi kilitlendi)
    | 'kilitli' (hesap zaten kilitli ya da pencere dolu; kod hiç denenmedi) | 'ip_sinir' (IP sınırı dolu; kod denenmedi)."""
    with db.transaction(conn):
        u = _kullanici(conn, ad)
        if u and u['kilit_bitis'] and u['kilit_bitis'] > db.simdi():
            return 'kilitli'
        if son_hatalar(conn, ad) >= KOD_DENEME:
            return 'kilitli'
        if ip_sinir is not None:
            esik = (datetime.now() - timedelta(minutes=IP_PENCERE_DK)).strftime('%Y-%m-%d %H:%M:%S')
            n = conn.execute("SELECT COUNT(*) FROM denetim WHERE islem IN ('giris_hata','2fa_hata') AND ip=? AND zaman>?",
                             (ip, esik)).fetchone()[0]
            if n >= ip_sinir:
                return 'ip_sinir'
        tur = kod_kontrol(conn, ad, girdi, ip, kim=kim)
        if tur:
            return tur
        return 'kilit' if hata_kaydet(conn, ad, ip, kilit_dk) else 'hata'


# ---------------------------------------------------------------- giriş öncesi işaret (parola doğru, kod bekleniyor)

def on_giris_olustur(conn, ad, sv, sonraki='/'):
    numara = secrets.token_urlsafe(24)
    with db.transaction(conn):
        _on_giris_temizle(conn)
        db.ayar_yaz(conn, ON_ONEK + numara, json.dumps({'ad': ad, 'sv': sv, 'zaman': time.time(), 'sonraki': sonraki}))
    return numara


def on_giris_al(conn, numara):
    """Geçerli (5 dk içinde, silinmemiş) işaretin verisi ya da None. Süresi geçmişse siler."""
    if not isinstance(numara, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,64}', numara):
        return None
    ham = db.ayar_al(conn, ON_ONEK + numara)
    if not ham:
        return None
    try:
        veri = json.loads(ham)
    except ValueError:
        veri = None
    if not isinstance(veri, dict) or time.time() - float(veri.get('zaman', 0)) > ON_GIRIS_SN:
        on_giris_sil(conn, numara)
        return None
    return veri


def on_giris_sil(conn, numara):
    if isinstance(numara, str):
        with db.transaction(conn):
            conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (ON_ONEK + numara,))


def _on_giris_temizle(conn):
    for r in conn.execute("SELECT anahtar,deger FROM ayarlar WHERE anahtar LIKE 'iki_adim_on:%'").fetchall():
        try:
            eski = time.time() - float(json.loads(r['deger']).get('zaman', 0)) > ON_GIRIS_SN
        except (ValueError, TypeError, AttributeError):
            eski = True
        if eski:
            conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (r['anahtar'],))


# ---------------------------------------------------------------- güvenilen cihazlar

def _ozet(belirtec):
    return hashlib.sha256(str(belirtec).encode('utf-8')).hexdigest()


def tarayici_ozeti(ua):
    """User-Agent'tan kısa, okunur özet (ör. 'Chrome · Android'); tam metin saklanmaz."""
    ua = str(ua or '')
    tarayici = next((ad for desen, ad in ((r'Edg/', 'Edge'), (r'OPR/|Opera', 'Opera'), (r'Firefox/', 'Firefox'), (r'SamsungBrowser', 'Samsung Internet'),
                                         (r'Chrome/|CriOS', 'Chrome'), (r'Safari/', 'Safari')) if re.search(desen, ua)), 'Tarayıcı')
    sistem = next((ad for desen, ad in ((r'Android', 'Android'), (r'iPhone|iPad|iOS', 'iOS'), (r'Windows', 'Windows'), (r'Mac OS X|Macintosh', 'macOS'),
                                       (r'Linux', 'Linux')) if re.search(desen, ua)), 'bilinmeyen sistem')
    return tarayici + ' · ' + sistem


def cihaz_ekle(conn, ad, gun, ip=None, ua=None):
    """Yeni güvenilen cihaz belirteci (düz değer yalnız çereze yazılır). gun<=0 ise None."""
    if gun <= 0:
        return None
    belirtec = secrets.token_urlsafe(32)
    simdi = datetime.now()
    with db.transaction(conn):
        conn.execute('INSERT INTO iki_adim_cihazlar(kullanici_adi,ozet,olusturma,bitis,son_kullanim,son_ip,tarayici) VALUES(?,?,?,?,?,?,?)',
                     (ad, _ozet(belirtec), simdi.strftime('%Y-%m-%d %H:%M:%S'), (simdi + timedelta(days=gun)).strftime('%Y-%m-%d %H:%M:%S'),
                      simdi.strftime('%Y-%m-%d %H:%M:%S'), ip, tarayici_ozeti(ua)))
        db.denetim_yaz(conn, ad, '2fa_cihaz_guven', ip=ip, hedef_turu='hesap', hedef_id=ad,
                       aciklama='Bu cihaz %d gün güvenilir: %s' % (gun, tarayici_ozeti(ua)))
    return belirtec


def _bitis_sql(gun):
    """Cihazın etkin bitişi: kayıttaki bitiş ile (oluşturma + geçerli gün) değerlerinin küçüğü. Böylece sahip süreyi
    sonradan kısaltırsa (ör. 30 → 7 gün) önceden güvenilen cihazlar da yeni süreye uyar; uzatma eski kayıtları uzatmaz."""
    return "MIN(bitis,COALESCE(datetime(olusturma,'+%d days'),bitis))" % int(gun)


def cihaz_gecerli(conn, ad, belirtec, ip=None):
    """Çerezdeki belirteç bu hesap için geçerli ve süresi dolmamış mı? Geçerliyse son kullanım/IP güncellenir.
    Panelde güven süresi 0'a çekildiyse (özellik kapalı) hiçbir cihaz kodu atlatamaz; süre kısaltıldıysa eski cihazlar
    da yeni süreye göre değerlendirilir (_bitis_sql)."""
    gun = guven_gun(conn)
    if not belirtec or not isinstance(belirtec, str) or len(belirtec) > 100 or gun <= 0:
        return False
    with db.transaction(conn):
        row = conn.execute('SELECT id,%s AS bitis FROM iki_adim_cihazlar WHERE kullanici_adi=? AND ozet=?' % _bitis_sql(gun),
                           (ad, _ozet(belirtec))).fetchone()
        if not row:
            return False
        if row['bitis'] <= db.simdi():
            conn.execute('DELETE FROM iki_adim_cihazlar WHERE id=?', (row['id'],))
            return False
        conn.execute('UPDATE iki_adim_cihazlar SET son_kullanim=?,son_ip=? WHERE id=?', (db.simdi(), ip, row['id']))
    return True


def cihazlar(conn, ad):
    """Geçerli güvenilen cihazlar; bitiş, güven süresi sonradan kısaltıldıysa oluşturma + geçerli gün olarak gösterilir."""
    gun = guven_gun(conn)
    bitis = _bitis_sql(gun) if gun > 0 else 'bitis'
    return [dict(r) for r in conn.execute('SELECT id,olusturma,%s AS bitis,son_kullanim,son_ip,tarayici FROM iki_adim_cihazlar '
                                          'WHERE kullanici_adi=? AND %s>? ORDER BY id DESC' % (bitis, bitis), (ad, db.simdi()))]


def cihaz_kaldir(conn, ad, cihaz_id, kim=None, ip=None):
    with db.transaction(conn):
        n = conn.execute('DELETE FROM iki_adim_cihazlar WHERE kullanici_adi=? AND id=?', (ad, int(cihaz_id))).rowcount
        if n:
            db.denetim_yaz(conn, kim or ad, '2fa_cihaz_kaldir', ip=ip, hedef_turu='hesap', hedef_id=ad, aciklama='1 güvenilen cihaz kaldırıldı')
    return n


def cihazlari_kaldir(conn, ad, kim=None, ip=None, neden=None, denetle=True):
    with db.transaction(conn):
        n = conn.execute('DELETE FROM iki_adim_cihazlar WHERE kullanici_adi=?', (ad,)).rowcount
        if n and denetle:
            db.denetim_yaz(conn, kim or ad, '2fa_cihaz_kaldir', ip=ip, hedef_turu='hesap', hedef_id=ad,
                           aciklama='%d güvenilen cihaz kaldırıldı%s' % (n, (': ' + neden) if neden else ''))
    return n


ISLEM_ADLARI = {'2fa_ac': 'İki adımlı doğrulamayı açtı', '2fa_kapat': 'İki adımlı doğrulamayı kapattı',
                '2fa_kurtarma_kullanildi': 'Kurtarma koduyla giriş yaptı', '2fa_sifirla': 'İki adımlı doğrulamayı sıfırladı',
                '2fa_cihaz_guven': 'Cihazı güvenilir olarak işaretledi', '2fa_cihaz_kaldir': 'Güvenilen cihazı kaldırdı',
                '2fa_hata': 'Hatalı doğrulama kodu', '2fa_kurtarma_yenile': 'Yeni kurtarma kodları üretti'}
DENETIM_ADLARI = {'2fa_ac': '2FA açma', '2fa_kapat': '2FA kapatma', '2fa_kurtarma_kullanildi': '2FA kurtarma kodu',
                  '2fa_sifirla': '2FA sıfırlama', '2fa_cihaz_guven': '2FA güvenilen cihaz', '2fa_cihaz_kaldir': '2FA cihaz kaldırma',
                  '2fa_hata': 'Hatalı doğrulama kodu', '2fa_kurtarma_yenile': '2FA kurtarma kodu yenileme'}
