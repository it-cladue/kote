"""2.4.0 — Çalışma ayarları: .env'e dokunmadan panelden değiştirilebilen (sır OLMAYAN) ayarlar.

Öncelik (yüksekten düşüğe):
  1. Veritabanı: ayarlar tablosunda 'ayar:<AD>' satırı (panelde /yonetim/ayarlar ya da 'python -m app.cli ayar AD DEGER').
  2. .env / ortam değişkeni (sunucu açılışında okunan değer).
  3. Varsayılan (aşağıdaki KAYIT listesinde).
Veritabanına yalnız doğrulanmış, kanonik değer yazılır. .env değerini okuyucular daha hoşgörülü okur (geçersiz → varsayılan,
bazı üst sınırlar kırpılır, bazıları olduğu gibi kullanılır); ayarlar sayfası okuyucunun GERÇEKTE kullandığı değeri gösterir
(okuyucu_degeri) ve panel kurallarına uymayan .env değerini uyarı olarak yazar. DIS_GORSEL_PROXY .env'de yoksa GYAZO_PROXY geçerlidir. Değişiklik yeniden başlatma gerekmeden bir sonraki istekte / iş turunda geçerlidir
(KAYIT'ta 'yeniden' alanı dolu olanlar hariç; sayfada açıkça yazar).

Sırlar (TELEGRAM/GYAZO anahtarları, parolalar, SESSION_SECRET), dosya yolları, port/dinleme adresi bu listede YOKTUR ve
hiçbir zaman buradan yazılamaz: yaz() yalnız KAYIT'taki adları kabul eder.
"""
import os
import re
import sqlite3
import sys

from . import db

ONEK = 'ayar:'


class Ayar:
    __slots__ = ('ad', 'grup', 'etiket', 'yardim', 'tur', 'varsayilan', 'en_az', 'en_cok', 'secenekler', 'okuyan', 'yeniden', 'sifir')

    def __init__(self, ad, grup, etiket, yardim, tur, varsayilan, en_az=None, en_cok=None, secenekler=None, okuyan='',
                 yeniden='', sifir=''):
        self.ad, self.grup, self.etiket, self.yardim, self.tur = ad, grup, etiket, yardim, tur
        self.varsayilan, self.en_az, self.en_cok = varsayilan, en_az, en_cok
        self.secenekler = secenekler or []
        self.okuyan, self.yeniden, self.sifir = okuyan, yeniden, sifir


GRUPLAR = ('Hatırlatmalar', 'Bildirimler', 'Görünürlük', 'API', 'Görseller')
_EVET = [('1', 'Açık'), ('0', 'Kapalı')]

KAYIT = [
    # ---------------------------------------------------------------- Hatırlatmalar
    Ayar('HATIRLATMA_GUN', 'Hatırlatmalar', 'Kaç gündür bekleyen kayıt hatırlatılsın', 'Onaysız kayıt bu kadar gün beklerse '
         'onay yetkilisine "kontrolü N gündür bekliyor" bildirimi gider. Kayıtlar sayfasındaki "geciken" sayısı da bu eşiği kullanır.',
         'tam', '3', 1, 365, okuyan='Hatırlatma işi (10 dk), ana sayfa ve kayıt sayaçları'),
    Ayar('HATIRLATMA_TEKRAR_GUN', 'Hatırlatmalar', 'Aynı kayıt kaç günde bir yeniden hatırlatılsın',
         'Bir kayıt için aynı kişiye en erken bu kadar gün sonra yeniden hatırlatma gider.', 'tam', '3', 1, 365, okuyan='Hatırlatma işi'),
    Ayar('HATIRLATMA_GUNLUK_SINIR', 'Hatırlatmalar', 'Kişi başına günlük en çok hatırlatma',
         'Aşan kayıtlar tek tek bildirilmez; o günün proje özetine katlanır (zil dolmasın).', 'tam', '50', 1, 10000, okuyan='Hatırlatma işi'),
    Ayar('HATIRLATMA_KONTROL_DK', 'Hatırlatmalar', 'Hatırlatma işi kaç dakikada bir çalışsın',
         'Arka plandaki hatırlatma / özet işinin çalışma aralığı. 0 = iş durur (bildirim üretilmez).', 'tam', '10', 0, 7 * 24 * 60,
         okuyan='Hatırlatma işi (web süreci)', sifir='0 = kapalı',
         yeniden='Sunucu 0 ile açıldıysa işi yeniden açmak için bir kez: sudo systemctl restart kanit-web'),
    Ayar('HATIRLATMA_SAAT', 'Hatırlatmalar', 'Kayıt başına "N saattir bekliyor" bildirimi (saat)',
         'Onaysız kayıt bu kadar saati doldurunca yetkililere bir kez bildirilir. 2.3.8\'den beri yerini "bekleyen özeti" aldı.',
         'tam', '0', 0, 720, okuyan='Hatırlatma işi', sifir='0 = kapalı'),
    Ayar('HATIRLATMA_SAAT_TOPLU', 'Hatırlatmalar', 'Saat bildiriminde toplu satır eşiği',
         'Aynı turda aynı projeden bundan fazla kayıt eşiği geçerse tek toplu bildirim gider.', 'tam', '5', 1, 1000, okuyan='Hatırlatma işi'),
    # ---------------------------------------------------------------- Bildirimler
    Ayar('BEKLEYEN_OZET_SAAT', 'Bildirimler', 'Bekleyen özeti kaç saatte bir',
         '"Onay bekleyen N kayıt var" özeti bu aralıkla, aşağıdaki saat penceresi içinde gönderilir.', 'tam', '2', 0, 24,
         okuyan='Hatırlatma işi', sifir='0 = kapalı'),
    Ayar('BEKLEYEN_OZET_PENCERE', 'Bildirimler', 'Bekleyen özeti saat penceresi (İstanbul)',
         'SS:DD-SS:DD biçiminde, ör. 08:00-20:00. Boş bırakılırsa bütün gün.', 'pencere', '08:00-20:00', okuyan='Hatırlatma işi'),
    Ayar('BEKLEYEN_OZET_YONETICI', 'Bildirimler', 'Süperadminler de bekleyen özeti alsın',
         'Kapalıysa özet yalnız proje onay yetkililerine gider.', 'evet', '1', secenekler=_EVET, okuyan='Hatırlatma işi'),
    Ayar('GUN_SONU_SAAT', 'Bildirimler', 'Gün sonu özeti saati (İstanbul)',
         'Her gün bu saatte "bugün onaylanmayan kayıtlar" özeti gider. SS:DD biçiminde; 0 = kapalı.', 'saat', '18:00',
         okuyan='Hatırlatma işi', sifir='0 = kapalı'),
    Ayar('GUN_SONU_ALICILAR', 'Bildirimler', 'Gün sonu özeti alıcıları',
         'Virgülle ayrılmış panel kullanıcı adları. Boş = tüm etkin süperadminler.', 'kullanicilar', '', okuyan='Hatırlatma işi'),
    # ---------------------------------------------------------------- Görünürlük
    Ayar('ONAYSIZ_GORUNUM', 'Görünürlük', 'Onaysız kayıtlar (onay yetkisi olmayana)',
         '"Uyar": kırmızı rozetle görünür. "Gizle": onay yetkisi olmayan kullanıcı onaysız kaydı liste, arama, ayrıntı ve çıktıda hiç görmez.',
         'secim', 'uyar', secenekler=[('uyar', 'Uyar (görünsün, kırmızı rozet)'), ('gizle', 'Gizle')], okuyan='Panel (her istek)'),
    Ayar('PANEL_EKLEME_KATEGORI', 'Görünürlük', 'Panelden eklenen kanıtların kategorisi',
         'Katalogda yoksa ilk kullanımda oluşturulur (etkin, tüm etkin projelere bağlı).', 'metin', 'SMS', en_cok=120,
         okuyan='Kanıt ekle sayfası'),
    # ---------------------------------------------------------------- API
    Ayar('API_ACIK', 'API', 'API (/api/v1) açık', 'Kapalıyken bütün /api/v1 adresleri 404 döner; anahtarlar silinmez, açınca yeniden çalışır.', 'evet', '1',
         secenekler=_EVET, okuyan='API (her istek)'),
    Ayar('API_DAKIKA_SINIRI', 'API', 'API anahtarı başına dakikada en çok istek', 'Aşan istek 429 alır.', 'tam', '120', 1, 100000,
         okuyan='API (her istek)'),
    # ---------------------------------------------------------------- Görseller
    Ayar('GYAZO_PROXY', 'Görseller', 'Gyazo görsellerini sunucu üzerinden getir',
         'Kapalıysa Gyazo bağlantıları panelde gösterilmez ve gece işi Gyazo\'yu denemez.', 'evet', '1', secenekler=_EVET,
         okuyan='Görsel gösterimi, gece görsel işi', yeniden='Panel görünümü için: sudo systemctl restart kanit-web (gece işi bir sonraki çalışmada uygular)'),
    Ayar('DIS_GORSEL_PROXY', 'Görseller', 'Snappark / Teamzone görsellerini sunucu üzerinden getir',
         'Kapalıysa bu servislerin bağlantıları panelde gösterilmez ve gece işi denemez.', 'evet', '1', secenekler=_EVET,
         okuyan='Görsel gösterimi, gece görsel işi', yeniden='Panel görünümü için: sudo systemctl restart kanit-web (gece işi bir sonraki çalışmada uygular)'),
]
SOZLUK = {a.ad: a for a in KAYIT}
_KULLANICI = re.compile(r'[a-z0-9_.]{1,40}')
_PENCERE = re.compile(r'(\d{1,2})(?:[:.](\d{2}))?\s*[-–]\s*(\d{1,2})(?:[:.](\d{2}))?')
_EVET_DEGERLER = {'1': '1', 'true': '1', 'evet': '1', 'acik': '1', 'açık': '1', 'on': '1', 'yes': '1',
                  '0': '0', 'false': '0', 'hayir': '0', 'hayır': '0', 'kapali': '0', 'kapalı': '0', 'off': '0', 'no': '0'}


# ---------------------------------------------------------------- okuma

def _istek_baglantisi():
    """Panel isteği içindeysek isteğin bağlantısı (testte panel.AYAR['DB']); değilse None."""
    try:
        from flask import has_request_context
    except Exception:  # pragma: no cover
        return None
    panel = sys.modules.get('app.panel')
    if panel is None or not has_request_context():
        return None
    try:
        return panel.baglanti()
    except Exception:
        return None


def _oku_tablo(conn):
    try:
        return {r[0][len(ONEK):]: r[1] for r in conn.execute("SELECT anahtar,deger FROM ayarlar WHERE anahtar LIKE 'ayar:%'")
                if r[0][len(ONEK):] in SOZLUK}
    except sqlite3.Error:
        return {}


def db_degerleri(conn=None):
    """{AD: kanonik değer} — yalnız veritabanında üzerine yazılmış KAYIT ayarları.
    conn verilmezse: panel isteğinde isteğin bağlantısı (istek boyunca önbellekli), değilse settings'teki veritabanı."""
    if conn is not None:
        return _oku_tablo(conn)
    istek = _istek_baglantisi()
    if istek is not None:
        from flask import g
        onbellek = g.get('_calisma_ayarlari')
        if onbellek is None:
            onbellek = _oku_tablo(istek)
            g._calisma_ayarlari = onbellek
        return onbellek
    from .settings import AYAR
    yol = AYAR.get('DB')
    if not yol or not os.path.exists(yol):
        return {}
    try:
        c = sqlite3.connect('file:' + os.path.abspath(yol) + '?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return {}
    try:
        return _oku_tablo(c)
    finally:
        c.close()


def _onbellegi_bosalt():
    try:
        from flask import g, has_app_context
        if has_app_context():
            g.pop('_calisma_ayarlari', None)
    except Exception:
        pass


def ust(ad, yedek, conn=None):
    """Veritabanında değer varsa o, yoksa 'yedek' (ör. açılışta .env'den okunmuş AYAR değeri)."""
    deger = db_degerleri(conn).get(ad)
    return yedek if deger is None else deger


def deger(ad, varsayilan=None, conn=None):
    """Öncelik: veritabanı > ortam (.env) > varsayilan > KAYIT varsayılanı. Ham metin döner (okuyucu kendi doğrulamasını yapar)."""
    d = db_degerleri(conn).get(ad)
    if d is not None:
        return d
    ortam = _ortam_ham(ad)
    if ortam is not None and str(ortam).strip() != '':
        return ortam
    if varsayilan is not None:
        return varsayilan
    a = SOZLUK.get(ad)
    return a.varsayilan if a else None


def _ortam_ham(ad):
    """Ortam değeri; DIS_GORSEL_PROXY tanımsızsa settings.py gibi GYAZO_PROXY'ye düşer."""
    ham = os.getenv(ad)
    if ham is None and ad == 'DIS_GORSEL_PROXY':
        ham = os.getenv('GYAZO_PROXY')
    return ham


def birlesik(ayar, conn=None):
    """ayar sözlüğünün (AYAR) kopyası; veritabanındaki KAYIT değerleri üstüne yazılmış olarak."""
    sonuc = dict(ayar or {})
    sonuc.update(db_degerleri(conn))
    return sonuc


# ---------------------------------------------------------------- doğrulama

def dogrula(ad, ham, conn=None):
    """Girdiyi kanonik metne çevirir; geçersizse Türkçe açıklamalı ValueError."""
    a = SOZLUK.get(ad)
    if a is None:
        raise ValueError('Bu ayar panelden değiştirilemez: %s. Değiştirilebilenler: python -m app.cli ayar --listele' % str(ad)[:60])
    metin = db.metin_temizle(ham, 400).strip()
    if a.tur == 'tam':
        try:
            sayi = int(metin)
        except (TypeError, ValueError):
            raise ValueError('%s: tam sayı girin (%d ile %d arası).' % (a.etiket, a.en_az, a.en_cok)) from None
        if sayi < a.en_az or sayi > a.en_cok:
            raise ValueError('%s: %d ile %d arasında olmalı (girilen: %d).' % (a.etiket, a.en_az, a.en_cok, sayi))
        return str(sayi)
    if a.tur == 'evet':
        sonuc = _EVET_DEGERLER.get(metin.casefold())
        if sonuc is None:
            raise ValueError('%s: Açık (1) ya da Kapalı (0) seçin.' % a.etiket)
        return sonuc
    if a.tur == 'secim':
        izinli = [k for k, _ in a.secenekler]
        if metin.lower() not in izinli:
            raise ValueError('%s: şunlardan biri olmalı: %s.' % (a.etiket, ', '.join(izinli)))
        return metin.lower()
    if a.tur == 'saat':
        if metin.casefold() in ('', '0', 'kapali', 'kapalı'):
            return '0'
        m = re.fullmatch(r'(\d{1,2})[:.](\d{2})', metin)
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise ValueError('%s: SS:DD biçiminde girin (ör. 18:00) ya da kapatmak için 0.' % a.etiket)
        return '%02d:%02d' % (int(m.group(1)), int(m.group(2)))
    if a.tur == 'pencere':
        if metin == '':
            return ''
        m = _PENCERE.fullmatch(metin)
        if m:
            bas = _dk(m.group(1), m.group(2))
            bit = _dk(m.group(3), m.group(4))
            if bas is not None and bit is not None and bas < bit and bas < 24 * 60:
                return '%02d:%02d-%02d:%02d' % (bas // 60, bas % 60, bit // 60, bit % 60)
        raise ValueError('%s: SS:DD-SS:DD biçiminde ve başlangıç bitişten önce olmalı (ör. 08:00-20:00); bütün gün için boş bırakın.' % a.etiket)
    if a.tur == 'kullanicilar':
        adlar = []
        for parca in metin.split(','):
            parca = parca.strip()
            if not parca:
                continue
            if not _KULLANICI.fullmatch(parca):
                raise ValueError('%s: "%s" geçerli bir kullanıcı adı değil (küçük harf, rakam, _ ve .).' % (a.etiket, parca[:40]))
            if parca not in adlar:
                adlar.append(parca)
        if conn is not None and adlar:
            var = {r[0] for r in conn.execute('SELECT kullanici_adi FROM panel_kullanicilari WHERE aktif=1')}
            eksik = [x for x in adlar if x not in var]
            if eksik:
                raise ValueError('%s: etkin panel kullanıcısı bulunamadı: %s.' % (a.etiket, ', '.join(eksik)))
        return ','.join(adlar)
    if a.tur == 'metin':
        metin = metin.replace('\n', ' ').strip()
        if not metin:
            raise ValueError('%s: boş olamaz.' % a.etiket)
        if a.en_cok and len(metin) > a.en_cok:
            raise ValueError('%s: en çok %d karakter.' % (a.etiket, a.en_cok))
        return metin
    raise ValueError('Bilinmeyen ayar türü.')  # pragma: no cover


def _dk(saat, dakika):
    saat, dakika = int(saat), int(dakika or 0)
    if dakika > 59 or saat > 24 or (saat == 24 and dakika):
        return None
    return saat * 60 + dakika


# ---------------------------------------------------------------- yazma

def yaz(conn, ad, ham, kim, ip=None):
    """Doğrular, veritabanına yazar, İşlem Geçmişi'ne eski/yeni değerle satır ekler. Dönüş: kanonik değer."""
    yeni = dogrula(ad, ham, conn)
    with db.transaction(conn):
        eski = db.ayar_al(conn, ONEK + ad)
        if eski == yeni:
            return yeni
        db.ayar_yaz(conn, ONEK + ad, yeni)
        db.denetim_yaz(conn, kim, 'ayar_degistir', eski={'ad': ad, 'deger': eski, 'kaynak': 'veritabanı' if eski is not None else _env_kaynak(ad)},
                       yeni={'ad': ad, 'deger': yeni}, ip=ip, hedef_turu='ayar', hedef_id=ad)
    _onbellegi_bosalt()
    return yeni


def sil(conn, ad, kim, ip=None):
    """Veritabanındaki değeri siler (varsayılana / .env'e dön). Dönüş: silindiyse True."""
    if ad not in SOZLUK:
        dogrula(ad, '')  # Türkçe hata
    with db.transaction(conn):
        eski = db.ayar_al(conn, ONEK + ad)
        if eski is None:
            return False
        conn.execute('DELETE FROM ayarlar WHERE anahtar=?', (ONEK + ad,))
        db.denetim_yaz(conn, kim, 'ayar_varsayilan', eski={'ad': ad, 'deger': eski}, yeni={'ad': ad, 'deger': None, 'kaynak': _env_kaynak(ad)},
                       ip=ip, hedef_turu='ayar', hedef_id=ad)
    _onbellegi_bosalt()
    return True


def _env_kaynak(ad):
    ham = _ortam_ham(ad)
    return '.env' if ham is not None and (str(ham).strip() != '' or getattr(SOZLUK.get(ad), 'tur', '') in ('pencere', 'kullanicilar', 'saat')) else 'varsayılan'


# ---------------------------------------------------------------- sayfa / CLI görünümü

# Okuyucuların .env değerine gerçekte ne yaptığı (settings.py + hatirlatma.ayarlar + api + katalog + gorsel ile aynı kurallar).
# Ayarlar sayfası "Şu an geçerli değer" sütununu buna göre gösterir; panelden kaydetme ise dogrula() ile katıdır.
_UST_KIRPAN = {'HATIRLATMA_KONTROL_DK', 'HATIRLATMA_SAAT', 'BEKLEYEN_OZET_SAAT'}  # üst sınırı aşan değer sınıra indirilir
_EVET_BEYAZ = {'API_ACIK': ('1', 'true', 'evet', 'acik', 'açık', 'on', 'yes'),
               'GYAZO_PROXY': ('1', 'true', 'evet'), 'DIS_GORSEL_PROXY': ('1', 'true', 'evet')}


def okuyucu_degeri(ad, ham):
    """.env'deki ham metin için okuyucunun kullandığı kanonik değer ve kural: (değer, 'aynen'|'varsayilan'|'kirpildi'|'serbest')."""
    a = SOZLUK[ad]
    metin = str(ham).strip()
    if a.tur == 'tam':
        try:
            # API_DAKIKA_SINIRI doğrudan int() ile okunur; diğerleri settings.py'de int(float()) ile.
            sayi = int(metin) if ad == 'API_DAKIKA_SINIRI' else int(float(metin))
        except (TypeError, ValueError, OverflowError):
            return a.varsayilan, 'varsayilan'
        if ad == 'HATIRLATMA_KONTROL_DK' and sayi < 0:
            sayi = 0  # settings.py: negatif → 0 (iş kapalı)
        if sayi < a.en_az:
            return a.varsayilan, 'varsayilan'
        if sayi > a.en_cok:
            return (str(a.en_cok), 'kirpildi') if ad in _UST_KIRPAN else (str(sayi), 'serbest')
        return str(sayi), 'aynen'
    if a.tur == 'evet':
        kucuk = metin.lower()
        if ad in _EVET_BEYAZ:  # tanınmayan değer = kapalı (boş API_ACIK açık sayılır)
            if ad == 'API_ACIK' and kucuk == '':
                return '1', 'aynen'
            return ('1' if kucuk in _EVET_BEYAZ[ad] else '0'), 'aynen'
        return ('0' if metin.casefold() in ('0', 'false', 'hayir', 'hayır', 'no', 'kapali', 'kapalı') else '1'), 'aynen'
    if a.tur == 'secim':
        return ('gizle' if metin.lower() == 'gizle' else 'uyar'), 'aynen'
    if a.tur == 'saat':
        if metin in ('', '0'):
            return '0', 'aynen'
        m = re.fullmatch(r'(\d{1,2})[:.](\d{2})', metin)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return '%02d:%02d' % (int(m.group(1)), int(m.group(2))), 'aynen'
        return a.varsayilan, 'varsayilan'
    if a.tur == 'kullanicilar':
        adlar = []
        for parca in metin.split(','):
            parca = parca.strip()
            if parca and parca not in adlar:
                adlar.append(parca)
        return ','.join(adlar), 'aynen'
    if a.tur == 'metin':
        temiz = db.metin_temizle(metin, 200).replace('\n', ' ').strip()
        return (temiz, 'aynen') if temiz else (a.varsayilan, 'varsayilan')
    try:
        return dogrula(ad, metin), 'aynen'
    except ValueError:
        return a.varsayilan, 'varsayilan'


def _sinir_metni(a):
    return ' Panelden kaydederken %d–%d arası girin.' % (a.en_az, a.en_cok) if a.tur == 'tam' else ''


def tablo(conn):
    """Ayarlar sayfası ve CLI için satırlar: her ayarın GERÇEKTE kullanılan değeri ve nereden geldiği."""
    dbd = db_degerleri(conn)
    satirlar = []
    for a in KAYIT:
        ortam = _ortam_ham(a.ad)
        # Boş değer yalnız boşluğun anlamlı olduğu türlerde (pencere = bütün gün, alıcılar = tümü, saat = kapalı) ve görsel
        # anahtarlarında (boş = kapalı) 'tanımlı' sayılır.
        bos_anlamli = a.tur in ('pencere', 'kullanicilar', 'saat') or a.ad in ('GYAZO_PROXY', 'DIS_GORSEL_PROXY')
        ortam = None if ortam is None or (str(ortam).strip() == '' and not bos_anlamli) else str(ortam).strip()
        ortam_uyari, ortam_degeri, kural = None, None, None
        if ortam is not None:
            ortam_degeri, kural = okuyucu_degeri(a.ad, ortam)
            try:
                dogrula(a.ad, ortam)
                kati_gecerli = True
            except ValueError:
                kati_gecerli = False
            if kural == 'varsayilan':
                ortam_uyari = '.env değeri geçersiz (%r); okuyucu varsayılanı (%s) kullanıyor.%s' % (ortam[:40], a.varsayilan or '(boş)', _sinir_metni(a))
            elif kural == 'kirpildi':
                ortam_uyari = '.env değeri sınırın üstünde (%r); okuyucu %s ile sınırlıyor.%s' % (ortam[:40], ortam_degeri, _sinir_metni(a))
            elif kural == 'serbest':
                ortam_uyari = ('.env değeri panel sınırlarının dışında (%r); okuyucu yine de %s kullanıyor.%s'
                               % (ortam[:40], ortam_degeri, _sinir_metni(a)))
            elif not kati_gecerli:
                ortam_uyari = ('.env değeri panelin kabul ettiği biçimde değil (%r); okuyucu bunu %s olarak kullanıyor.'
                               % (ortam[:40], gosterim(dict(tur=a.tur, gecerli=ortam_degeri, secenekler=a.secenekler, sifir=a.sifir)) or '(boş)'))
            if a.ad == 'DIS_GORSEL_PROXY' and os.getenv('DIS_GORSEL_PROXY') is None:
                ortam_uyari = ((ortam_uyari + ' ') if ortam_uyari else '') + '.env\'de DIS_GORSEL_PROXY yok; GYAZO_PROXY değeri kullanılıyor.'
        if a.ad in dbd:
            gecerli, kaynak = dbd[a.ad], 'DB'
        elif ortam is not None and kural != 'varsayilan':
            gecerli, kaynak = ortam_degeri, '.env'
        else:
            gecerli, kaynak = a.varsayilan, 'varsayılan'
        satirlar.append(dict(ad=a.ad, grup=a.grup, etiket=a.etiket, yardim=a.yardim, tur=a.tur, varsayilan=a.varsayilan,
                             en_az=a.en_az, en_cok=a.en_cok, secenekler=a.secenekler, okuyan=a.okuyan, yeniden=a.yeniden, sifir=a.sifir,
                             gecerli=gecerli, kaynak=kaynak, db=dbd.get(a.ad), ortam=ortam, ortam_uyari=ortam_uyari))
        satirlar[-1]['varsayilan_gosterim'] = gosterim(dict(satirlar[-1], gecerli=a.varsayilan)) if a.varsayilan != '' else '(boş)'
    return satirlar


def gosterim(satir):
    """Değerin insan okur metni (boş pencere = bütün gün vb.)."""
    d = satir['gecerli']
    if satir['tur'] == 'evet':
        return 'Açık' if d == '1' else 'Kapalı'
    if satir['tur'] == 'secim':
        return dict(satir['secenekler']).get(d, d)
    if satir['tur'] == 'pencere' and d == '':
        return 'bütün gün'
    if satir['tur'] == 'kullanicilar' and d == '':
        return 'tüm süperadminler'
    if satir['tur'] in ('tam', 'saat') and str(d) == '0' and satir['sifir']:
        return '0 (kapalı)'
    return d
