"""2.4.0 — Erişim sınırı (IP izin listesi): panel ve API için ayrı listeler.

Listeler 'ayarlar' tablosunda tutulur (anahtarlar: izinli_ipler, api_izinli_ipler). Tabloda satır yoksa ortam değişkeni
(IZINLI_IPLER / API_IZINLI_IPLER) kullanılır; tabloda BOŞ satır "sınır yok" demektir ve ortam değerini de geçersiz kılar
(acil durum komutu `python -m app.cli erisim-izin --temizle` bu yüzden her zaman işe yarar).

Değer biçimi: virgül, noktalı virgül, boşluk ya da satır sonuyla ayrılmış IPv4/IPv6 adresleri veya CIDR blokları
(ör. "85.105.12.34, 85.0.0.0/8, 2a02:4780::/32"). '#' ile başlayan satır sonu açıklamadır. Boş liste = sınır yok.

İstemci adresi panelin her yerde kullandığı adrestir (request.remote_addr). Nginx arkasında TRUST_PROXY=1 olmalı:
waitress X-Forwarded-For'u yalnız GUVENILEN_PROXY'den (127.0.0.1) kabul eder; Cloudflare yolunda nginx gerçek adresi
CF-Connecting-IP'den, IP:18443 yolunda doğrudan bağlantıdan alır. TRUST_PROXY=0 iken her istek 127.0.0.1 görünür;
bu durum (döngü adresi + X-Forwarded-For başlığı) 'vekil şüphesi' sayılır, döngü muafiyeti UYGULANMAZ (kapalı kalır)
ve ayar ekranı "TRUST_PROXY=1 gerekli" uyarısı gösterir."""
import html
import ipaddress
import os
import re
import threading
import time

from . import db

TURLER = {
    'panel': ('izinli_ipler', 'IZINLI_IPLER', 'Panel'),
    'api': ('api_izinli_ipler', 'API_IZINLI_IPLER', 'API'),
}
EN_COK_GIRDI = 200
_AYIRICI = re.compile(r'[\s,;]+')
_RED_KILIT = threading.Lock()
_RED_SON = {}            # ip -> son denetim satırı zamanı (monotonic); dakikada en çok bir 'erisim_red' satırı
RED_ARALIK_SN = 60.0


class ListeHatasi(ValueError):
    pass


# ------------------------------------------------------------------ ayrıştırma

def ip_coz(deger):
    """İstemci adresini ip_address'e çevirir; IPv4-eşlemeli IPv6 (::ffff:1.2.3.4) IPv4 sayılır. Çözülemezse None."""
    metin = str(deger or '').strip()
    if metin.startswith('[') and ']' in metin:
        metin = metin[1:metin.index(']')]
    metin = metin.split('%', 1)[0]
    try:
        adres = ipaddress.ip_address(metin)
    except ValueError:
        return None
    if isinstance(adres, ipaddress.IPv6Address) and adres.ipv4_mapped:
        return adres.ipv4_mapped
    return adres


def _parcalar(metin):
    satirlar = []
    for satir in str(metin or '').splitlines():
        satirlar.append(satir.split('#', 1)[0])
    return [p for p in _AYIRICI.split(' '.join(satirlar)) if p]


def liste_coz(metin):
    """Metni ağ listesine çevirir. Geçersiz girdide ListeHatasi (hatalı parçalar mesajda)."""
    aglar, hatali = [], []
    for parca in _parcalar(metin):
        try:
            ag = ipaddress.ip_network(parca, strict=False)
        except ValueError:
            hatali.append(parca)
            continue
        if isinstance(ag, ipaddress.IPv6Network) and ag.prefixlen >= 96 and ag.network_address.ipv4_mapped:
            ag = ipaddress.ip_network('%s/%d' % (ag.network_address.ipv4_mapped, ag.prefixlen - 96))
        if ag not in aglar:
            aglar.append(ag)
    if hatali:
        raise ListeHatasi('Geçersiz adres: ' + ', '.join(hatali[:10]) + ('…' if len(hatali) > 10 else '') +
                          '. Örnek: 85.105.12.34 (tek adres) ya da 85.105.12.0/24 (blok).')
    if len(aglar) > EN_COK_GIRDI:
        raise ListeHatasi('En çok %d adres/blok yazılabilir.' % EN_COK_GIRDI)
    return aglar


def ag_metni(ag):
    """Tek adres bloklarını /32 (/128) olmadan yazar."""
    if ag.prefixlen == ag.max_prefixlen:
        return str(ag.network_address)
    return str(ag)


def liste_metni(aglar):
    return '\n'.join(ag_metni(a) for a in aglar)


def normalle(metin):
    """Kaydedilecek kanonik metin (satır başına bir girdi). Geçersizse ListeHatasi."""
    return liste_metni(liste_coz(metin))


def izinli_mi(adres, aglar):
    """Boş liste → her adres izinli. Çözülemeyen adres → izinsiz."""
    if not aglar:
        return True
    ip = adres if isinstance(adres, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ip_coz(adres)
    if ip is None:
        return False
    return any(ip.version == ag.version and ip in ag for ag in aglar)


def dongu_mu(adres):
    ip = adres if isinstance(adres, (ipaddress.IPv4Address, ipaddress.IPv6Address)) else ip_coz(adres)
    return bool(ip is not None and ip.is_loopback)


# ------------------------------------------------------------------ ayar saklama (Ayarlar sayfası da bu iki işlevi çağırır)

def _tur(tur):
    if tur not in TURLER:
        raise ValueError('Bilinmeyen erişim listesi: ' + str(tur))
    return TURLER[tur]


def ayar_oku(conn, tur='panel'):
    """{'metin', 'kaynak': 'veritabani'|'ortam'|'yok', 'aglar', 'hata'} döndürür.
    Bozuk saklanan değer (elle düzenlenmiş) fail-closed değil, 'hata' ile birlikte geçerli parçalarla döner."""
    anahtar, ortam, _ = _tur(tur)
    deger = db.ayar_al(conn, anahtar)
    kaynak = 'veritabani'
    if deger is None:
        deger = os.getenv(ortam, '') or ''
        kaynak = 'ortam' if deger.strip() else 'yok'
    hata = None
    try:
        aglar = liste_coz(deger)
    except ListeHatasi as e:
        hata = str(e)
        aglar = []
        for parca in _parcalar(deger):
            try:
                aglar.append(ipaddress.ip_network(parca, strict=False))
            except ValueError:
                pass
        if not aglar:
            # Hiç geçerli girdi yoksa sınır yok saymak yerine kapalı kal: yalnız döngü adresi (sunucunun kendisi).
            aglar = [ipaddress.ip_network('127.0.0.1/32')]
    if kaynak == 'veritabani' and not deger.strip():
        kaynak = 'yok'
    return {'metin': liste_metni(aglar) if not hata else deger, 'kaynak': kaynak, 'aglar': aglar, 'hata': hata}


def ayar_yaz(conn, tur, metin, kim, ip=None, aciklama=None):
    """Listeyi doğrulayıp kaydeder ve İşlem Geçmişi'ne 'erisim_ayar' (eski/yeni) yazar. Kanonik metni döndürür.
    Kendini dışarıda bırakma denetimi çağıranın işidir (panel rotası ve CLI farklı kurallar uygular)."""
    anahtar, _, ad = _tur(tur)
    yeni = normalle(metin)
    with db.transaction(conn):
        eski = ayar_oku(conn, tur)
        db.ayar_yaz(conn, anahtar, yeni)
        if eski['metin'] != yeni or eski['kaynak'] == 'ortam':
            db.denetim_yaz(conn, kim, 'erisim_ayar', ip=ip, hedef_turu='ayar', hedef_id=anahtar,
                           eski={'liste': ad, 'adresler': eski['metin'].split('\n') if eski['metin'] else [], 'kaynak': eski['kaynak']},
                           yeni={'liste': ad, 'adresler': yeni.split('\n') if yeni else []},
                           aciklama=aciklama or (ad + ' erişim listesi ' + ('temizlendi (sınır yok)' if not yeni else 'güncellendi')))
    return yeni


# ------------------------------------------------------------------ istek denetimi

def dongu_serbest():
    """ERISIM_LOOPBACK_SERBEST=1 (varsayılan): sunucunun kendisinden doğrudan gelen istek (X-Forwarded-For'suz) sınırdan muaf."""
    return str(os.getenv('ERISIM_LOOPBACK_SERBEST', '1') or '1').strip().lower() not in ('0', 'false', 'hayir', 'hayır', 'kapali', 'kapalı', 'off', 'no')


def istemci(request):
    """{'ip', 'xff', 'vekil_suphesi'}: vekil şüphesi = adres döngü ama istekte X-Forwarded-For var (TRUST_PROXY=0 belirtisi)."""
    adres = request.remote_addr or ''
    xff = request.headers.get('X-Forwarded-For', '')
    return {'ip': adres, 'xff': xff, 'vekil_suphesi': bool(dongu_mu(adres) and xff.strip())}


def muaf_mi(request, endpoint=None):
    endpoint = endpoint if endpoint is not None else request.endpoint
    if endpoint == 'static':
        return True
    bilgi = istemci(request)
    if endpoint == 'saglik' and dongu_mu(bilgi['ip']):
        # Sunucu kendini kendi nginx'i üzerinden de denetler (X-Forwarded-For: 127.0.0.1); /saglik yalnız 'OK' döndürür.
        return True
    if bilgi['vekil_suphesi']:
        return False
    return bool(dongu_mu(bilgi['ip']) and dongu_serbest())


def panel_izinli(conn, request, endpoint=None):
    """(izinli_mi, istemci_ip). Liste boşsa her zaman izinli."""
    if muaf_mi(request, endpoint):
        return True, request.remote_addr
    aglar = ayar_oku(conn, 'panel')['aglar']
    return izinli_mi(request.remote_addr, aglar), request.remote_addr


RED_EN_COK = 10000


def red_kaydet(conn, ip, yol, liste='panel'):
    """Engellenen istek: IP başına dakikada en çok bir 'erisim_red' satırı (saldırı altında günlük şişmez)."""
    simdi = time.monotonic()
    anahtar = liste + ':' + str(ip)
    with _RED_KILIT:
        if len(_RED_SON) > 5000:
            for k in [k for k, t in _RED_SON.items() if simdi - t >= RED_ARALIK_SN]:
                del _RED_SON[k]
        if len(_RED_SON) >= RED_EN_COK and anahtar not in _RED_SON:
            # Çok sayıda farklı adresten gelen sel: bellek ve günlük şişmesin; yeni adres için satır yazılmaz (istek yine 403).
            return False
        son = _RED_SON.get(anahtar)
        if son is not None and simdi - son < RED_ARALIK_SN:
            return False
        _RED_SON[anahtar] = simdi
    try:
        db.denetim_yaz(conn, '(erişim engeli)', 'erisim_red', ip=str(ip or '')[:45], sonuc='uyari', hedef_turu='sistem',
                       hedef_id=TURLER[liste][0], aciklama=(('API ' if liste == 'api' else '') + str(yol or ''))[:200])
    except Exception:
        return False
    return True


def red_sayfasi(ip):
    """Engellenen tarayıcıya sade Türkçe 403 (şablon/oturum yok)."""
    guvenli = html.escape(str(ip or 'bilinmiyor'))
    return ('<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Erişim izinli değil — Kanıt Paneli</title></head>'
            '<body style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.5;color:#1d2433;background:#fff">'
            '<h1 style="font-size:22px">Bu adresten erişim izinli değil (IP: ' + guvenli + ')</h1>'
            '<p>Kanıt Paneli yalnız izin verilen adreslerden açılır. Ofis dışındaysanız ya da internet bağlantınız değiştiyse '
            '(mobil veri, evden bağlantı) panel bu adresi tanımaz.</p>'
            '<p><b>Ne yapmalıyım?</b> Bu sayfadaki IP adresini panel sahibine iletin; sahip <i>Yönetim → Erişim sınırı</i> '
            'sayfasından adresinizi ekleyebilir.</p>'
            '<p style="color:#5b6475;font-size:14px">Panel sahibi kendini dışarıda bıraktıysa: sunucuda '
            '<code>python -m app.cli erisim-izin --goster</code> listeyi gösterir, <code>--ekle ' + guvenli + '</code> bu adresi ekler, '
            '<code>--temizle</code> sınırı kaldırır.</p></body></html>')


def api_izinli(conn, ip, anahtar=None):
    """API: önce genel liste (api_izinli_ipler), anahtar verilmişse anahtarın kendi listesi (izinli_ipler sütunu).
    (izinli, hangi_liste) döndürür; hangi_liste: None | 'genel' | 'anahtar'."""
    if not izinli_mi(ip, ayar_oku(conn, 'api')['aglar']):
        return False, 'genel'
    if anahtar is not None:
        metin = anahtar.get('izinli_ipler') if hasattr(anahtar, 'get') else None
        if metin:
            try:
                aglar = liste_coz(metin)
            except ListeHatasi:
                return False, 'anahtar'  # bozuk anahtar listesi: kapalı kal
            if not izinli_mi(ip, aglar):
                return False, 'anahtar'
    return True, None


def durum_ozeti(conn, request=None):
    """Erişim sınırı sayfası ve Ayarlar için: iki listenin durumu, şu anki adres ve TRUST_PROXY uyarısı."""
    panel = ayar_oku(conn, 'panel')
    api = ayar_oku(conn, 'api')
    sonuc = {'panel': panel, 'api': api, 'dongu_serbest': dongu_serbest()}
    if request is not None:
        bilgi = istemci(request)
        sonuc.update(ip=bilgi['ip'], vekil_suphesi=bilgi['vekil_suphesi'], muaf=muaf_mi(request),
                     ip_listede=izinli_mi(bilgi['ip'], panel['aglar']) if panel['aglar'] else True)
    return sonuc
