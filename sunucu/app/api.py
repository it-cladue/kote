"""2.3.2 — Dış sistemler için salt okunur JSON API (/api/v1/*).

Kimlik: yalnız ``Authorization: Bearer kp_…``; oturum çerezi kimlik sayılmaz, CSRF uygulanmaz (çerez yok → CSRF riski yok).
Kapsam: anahtarın proje listesi; ``yalniz_onayli`` ise yalnız ``kt=1 AND silindi=0``; aksi hâlde silinmişler yine hariç.
SQL ucu: ayrı ``mode=ro`` bağlantı + ``set_authorizer`` (yalnız SELECT/READ/FUNCTION); okunabilen tek şey kapsamla süzülmüş
TEMP görünümlerdir. Görünümlerin iç adı her istekte rastgele üretilir; böylece kullanıcının yazdığı aynı adlı bir CTE
(``WITH kayitlar AS (SELECT * FROM main.kayitlar)``) authorizer'ın 5. argümanını taklit edip ana tabloya ulaşamaz."""
import math
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, current_app, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from . import api_anahtarlari as aa
from . import db, erisim

bp = Blueprint('api', __name__, url_prefix='/api/v1')

EN_BUYUK_GOVDE = 64 * 1024
SQL_SURE_SN = 5.0
SQL_EN_COK_SATIR = 1000
SQL_EN_COK_BAYT = 8 * 1024 * 1024    # 2.3.2-inc: yanıttaki toplam değer boyutu üst sınırı (bellek tüketme DoS'una karşı)
SQL_DEGER_EN_UZUN = 64 * 1024        # tek değer (metin/blob) üst sınırı: SQLITE_LIMIT_LENGTH
SQL_ESZAMANLI_VARSAYILAN = 2         # süreç genelinde aynı anda çalışan sorgu (waitress threads=8'in altında)
SQL_ESZAMANLI_EN_COK = 6
SQL_RETRY_AFTER = 2
SQL_EN_UZUN = 20000
SQL_EN_COK_PARAMETRE = 100
YETKISIZ_IP_SINIRI = 30  # dakikada IP başına geçersiz anahtar denemesi; aşan istekler günlüğe yazılmadan 429 alır
HIZ = aa.HizSiniri()
YETKISIZ_HIZ = aa.HizSiniri()

KAYIT_ALANLARI = ('id', 'proje', 'kategori', 'personel', 'uye_id', 'ana_uye_id', 'lead_id', 'tip', 'tarih', 'kt', 'kt_kim', 'kt_zaman',
                  'ekleyen_id', 'ekleyen_ad', 'link', 'link_turu', 'aciklama', 'kaynak')  # 2.3.6: kaynak (telegram / panel / legacy_excel)
# SQL ucundaki ``kayitlar`` görünümünün sütunları (ham DB adlarıyla). Dosya yolu, Telegram sohbet/mesaj kimliği gibi iç alanlar yok.
SQL_KAYIT_SUTUNLARI = ('id', 'proje', 'kategori', 'kategori_code', 'kategori_mode', 'personel', 'uye_id', 'ana_uye_id', 'lead_id', 'tip',
                       'tarih', 'kt', 'kt_kim', 'kt_zaman', 'ekleyen_id', 'ekleyen_ad', 'link', 'link_turu', 'aciklama', 'kaynak',
                       'giris_tipi', 'ilk_gorulme', 'guncelleme')
SQL_YORUM_SUTUNLARI = ('id', 'kayit_id', 'kullanici', 'tur', 'metin', 'zaman', 'yanit_id')
SQL_GORUNUMLER = ('kayitlar', 'yorumlar', 'kategoriler', 'tg_kullanicilar')
YASAK_FONKSIYONLAR = frozenset({'load_extension', 'zeroblob', 'randomblob', 'readfile', 'writefile', 'fts3_tokenizer', 'edit'})
# 'sqlite_' önekli işlevler (sqlite_version, sqlite_source_id, sqlite_compileoption_get/used, sqlite_offset ...) derleme bilgisi açar: kapalı.
YASAK_ONEKLER = ('sqlite_',)
_SQL_KILIT = threading.Lock()
_SQL_AKTIF = {}        # anahtar özeti -> çalışan sorgu sayısı
_SQL_TOPLAM = [0]      # süreç genelinde çalışan sorgu sayısı


def _panel():
    from . import panel
    return panel


API_ACIK_DEGERLER = ('1', 'true', 'evet', 'acik', 'açık', 'on', 'yes')


def acik_mi():
    """Beyaz liste: boş/tanımsız ya da açık anlamlı değer → açık; tanınmayan her değer (ör. 'kapat') → kapalı (güvenli taraf)."""
    return str(os.getenv('API_ACIK', '1') or '1').strip().lower() in API_ACIK_DEGERLER


def sorgu_eszamanli_siniri():
    """API_SORGU_ESZAMANLI (varsayılan 2, en çok 6): /sorgu ucunda süreç genelinde aynı anda çalışabilecek sorgu."""
    try:
        deger = int(str(os.getenv('API_SORGU_ESZAMANLI', '') or '').strip() or SQL_ESZAMANLI_VARSAYILAN)
    except (TypeError, ValueError):
        return SQL_ESZAMANLI_VARSAYILAN
    if deger < 1:
        return SQL_ESZAMANLI_VARSAYILAN
    return min(deger, SQL_ESZAMANLI_EN_COK)


def dakika_siniri():
    try:
        deger = int(str(os.getenv('API_DAKIKA_SINIRI', '') or '').strip() or 120)
    except (TypeError, ValueError):
        return 120
    return deger if deger >= 1 else 120


def _hata(kod, mesaj, **ek):
    resp = jsonify(ok=False, hata=mesaj, kod=kod, **ek)
    resp.status_code = kod
    return resp


class _Red(Exception):
    def __init__(self, kod, mesaj, **ek):
        super().__init__(mesaj)
        self.kod, self.mesaj, self.ek = kod, mesaj, ek


@bp.errorhandler(_Red)
def _red_yaniti(error):
    return _hata(error.kod, error.mesaj, **error.ek)


HTTP_MESAJLARI = {400: 'İstek geçersiz veya eksik.', 401: 'Geçerli bir API anahtarı gerekli.', 403: 'Bu anahtarın kapsamı bu işleme izin vermiyor.',
                  404: 'Kayıt ya da uç bulunamadı.', 405: 'Bu uç bu yöntemle çağrılamaz.', 413: 'İstek gövdesi en çok 64 KB olabilir.',
                  429: 'Dakikalık istek sınırı aşıldı.'}


@bp.errorhandler(HTTPException)
def _http_hatasi(error):
    return _hata(error.code or 500, HTTP_MESAJLARI.get(error.code, 'İstek işlenemedi.'))


@bp.errorhandler(Exception)
def _sunucu_hatasi(error):
    ref = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(3).upper()
    current_app.logger.error('API beklenmeyen hata [kayit no %s] %s %s', ref, request.method, request.path,
                             exc_info=(type(error), error, error.__traceback__))
    return _hata(500, 'Beklenmeyen hata, kayıt no ' + ref + '. Sorun sürerse bu numarayı panel yöneticisine iletin.', kayit_no=ref)


def yol_hatasi():
    """panel.before() /api/ altındaki her istekte çağırır: eşleşmeyen yol/yöntem için JSON 404/405 (HTML hata sayfası yok)."""
    hata = getattr(request, 'routing_exception', None)
    if hata is None:
        return None
    kod = getattr(hata, 'code', 404) or 404
    if kod not in (404, 405) or not acik_mi():
        kod = 404
    return _hata(kod, HTTP_MESAJLARI.get(kod, HTTP_MESAJLARI[404]))


def _bearer():
    deger = request.headers.get('Authorization', '')
    parca = deger.split(None, 1)
    if len(parca) != 2 or parca[0].lower() != 'bearer':
        return ''
    return parca[1].strip()


def _ip_red(ip):
    return _hata(403, 'Bu adresten API erişimi izinli değil (IP: ' + str(ip or '?') + '). Panel sahibi Yönetim → Erişim sınırı '
                 'ya da API anahtarları sayfasından adresi ekleyebilir.', neden='ip_izinsiz', ip=str(ip or ''))


@bp.before_request
def _kimlik():
    g.api_basla = time.perf_counter(); g.api_anahtar = None; g.api_satir = None; g.api_gunluk = False
    if not acik_mi():
        return _hata(404, HTTP_MESAJLARI[404])
    buyuk = request.content_length is not None and request.content_length > EN_BUYUK_GOVDE
    request.max_content_length = EN_BUYUK_GOVDE
    c = _panel().baglanti()
    # 2.4.0: IP izin listesi — genel API listesi anahtar doğrulamasından ÖNCE (izinsiz adres anahtar deneyemez),
    # anahtarın kendi listesi doğrulamadan sonra ve kapsam/hız denetiminden önce. Adres panelle aynı: request.remote_addr.
    istemci_ip = request.remote_addr
    izinli, _ = erisim.api_izinli(c, istemci_ip)
    if not izinli:
        erisim.red_kaydet(c, istemci_ip, request.method + ' ' + request.path, 'api')
        return _ip_red(istemci_ip)
    anahtar, neden = aa.dogrula(c, _bearer())
    if anahtar:
        izinli, _ = erisim.api_izinli(c, istemci_ip, anahtar)
        if not izinli:
            g.api_anahtar = anahtar; g.api_gunluk = True
            erisim.red_kaydet(c, istemci_ip, request.method + ' ' + request.path, 'api')  # anahtara özel liste de İşlem Geçmişi'ne düşsün
            return _ip_red(istemci_ip)
    if not anahtar:
        # Kimliksiz/geçersiz istek (413 dahil): IP başına sınır; aşan istekler günlüğe yazılmadan 429 alır.
        izin, bekle = YETKISIZ_HIZ.dene('ip:' + str(request.remote_addr), YETKISIZ_IP_SINIRI)
        if not izin:
            resp = _hata(429, 'Çok fazla geçersiz anahtar denemesi. ' + str(bekle) + ' saniye sonra tekrar deneyin.')
            resp.headers['Retry-After'] = str(bekle)
            return resp
        g.api_gunluk = True
        if buyuk:
            return _hata(413, HTTP_MESAJLARI[413])
        mesaj = {'yok': 'API anahtarı gerekli: Authorization: Bearer kp_… başlığını gönderin. Oturum çerezi kabul edilmez.',
                 'iptal': 'Bu API anahtarı iptal edilmiş. Panel yöneticisinden yeni anahtar isteyin.',
                 'suresi_doldu': 'Bu API anahtarının süresi dolmuş. Panel yöneticisinden yeni anahtar isteyin.'}.get(
                     neden, 'API anahtarı geçersiz. Anahtarı eksiksiz kopyaladığınızdan emin olun.')
        resp = _hata(401, mesaj)
        resp.headers['WWW-Authenticate'] = 'Bearer realm="kanit-paneli-api"'
        return resp
    g.api_anahtar = anahtar; g.api_gunluk = True
    if buyuk:
        return _hata(413, HTTP_MESAJLARI[413])
    sinir = dakika_siniri()
    izin, bekle = HIZ.dene(anahtar['ozet'], sinir)
    if not izin:
        resp = _hata(429, 'Dakikada en çok ' + str(sinir) + ' istek gönderilebilir. ' + str(bekle) + ' saniye sonra tekrar deneyin.')
        resp.headers['Retry-After'] = str(bekle)
        return resp
    return None


@bp.after_request
def _sonra(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers.pop('Set-Cookie', None)
    if g.get('api_gunluk'):
        try:
            sure = int((time.perf_counter() - g.get('api_basla', time.perf_counter())) * 1000)
            anahtar = g.get('api_anahtar') or {}
            aa.gunluk_yaz(_panel().baglanti(), anahtar.get('id'), request.method + ' ' + request.path, request.remote_addr,
                          response.status_code, sure, g.get('api_satir'))
        except Exception as error:  # günlük yazılamasa da yanıt verilir
            current_app.logger.warning('API günlüğü yazılamadı: %s', type(error).__name__)
    return response


# ------------------------------------------------------------------ kapsam ve süzgeç

def _kapsam():
    """(proje listesi, tumu_mu, yalniz_onayli) — o anki tanımlı projelere göre."""
    anahtar = g.api_anahtar
    projeler, tumu = aa.kapsam_projeleri(anahtar, _panel().projeler())
    return projeler, tumu, bool(anahtar['yalniz_onayli'])


def _kapsam_sql(alias=''):
    """Anahtar kapsamının WHERE parçası (silinmişler her zaman hariç)."""
    a = (alias + '.') if alias else ''
    projeler, tumu, yalniz = _kapsam()
    kosul = [a + 'silindi=0']; par = []
    if not tumu:
        if not projeler:
            kosul.append('1=0')
        else:
            kosul.append(a + 'proje IN (%s)' % ','.join('?' * len(projeler))); par.extend(projeler)
    if yalniz:
        kosul.append(a + 'kt=1')
    return kosul, par


def _secili_projeler():
    secili = []
    for deger in request.args.getlist('proje'):
        for p in str(deger).split(','):
            p = p.strip().upper()
            if p and p != 'HEPSI':
                secili.append(p)
    secili = list(dict.fromkeys(secili))
    if secili:
        projeler, _, _ = _kapsam()
        disarida = [p for p in secili if p not in projeler]
        if disarida:
            raise _Red(403, 'Bu anahtarın kapsamı dışındaki proje istendi: ' + ', '.join(disarida[:5]) + '.')
    return secili


def _tarih_suzgeci(kosul, par):
    uyari = None
    t1 = (request.args.get('tarih1') or '').strip(); t2 = (request.args.get('tarih2') or '').strip()
    for v in (t1, t2):
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                raise _Red(400, 'Tarih YYYY-AA-GG biçiminde olmalı (ör. 2026-11-01).')
    if t1 and t2 and t1 > t2:
        t1, t2 = t2, t1
        uyari = 'Başlangıç tarihi bitişten sonraydı; tarihler yer değiştirildi (' + t1 + ' → ' + t2 + ').'
    if request.args.get('tarihsiz') == '1':
        if t1 or t2:
            raise _Red(400, 'Tarihsiz süzgeç tarih aralığıyla birlikte kullanılamaz.')
        kosul.append("(tarih IS NULL OR tarih='')")
    if t1:
        kosul.append('tarih >= ?'); par.append(t1)  # 2.3.4: saatsiz eski Excel tarihi de başlangıç gününe dahil
    if t2:
        kosul.append('tarih <= ?'); par.append(t2 + ' 23:59:59')
    return dict(tarih1=t1, tarih2=t2), uyari


def _suzgec(durum_kullan=True):
    kosul, par = _kapsam_sql()
    secili = _secili_projeler()
    if secili:
        kosul.append('proje IN (%s)' % ','.join('?' * len(secili))); par.extend(secili)
    yalniz = bool(g.api_anahtar['yalniz_onayli'])
    durum = 'onayli' if yalniz else 'hepsi'
    durum_uyari = None
    if durum_kullan and yalniz and (request.args.get('durum') or '').strip().lower() not in ('', 'onayli'):
        durum_uyari = 'Bu anahtar yalnız onaylı kayıtları görür; durum süzgeci yok sayıldı.'
    if durum_kullan and not yalniz:
        durum = (request.args.get('durum') or 'hepsi').strip().lower()
        if durum not in ('onayli', 'bekleyen', 'hepsi'):
            raise _Red(400, 'durum yalnız onayli, bekleyen ya da hepsi olabilir.')
        if durum == 'onayli':
            kosul.append('kt=1')
        elif durum == 'bekleyen':
            kosul.append('kt=0')
    tarihler, uyari = _tarih_suzgeci(kosul, par)
    if durum_uyari:
        uyari = durum_uyari + (' ' + uyari if uyari else '')
    meta = dict(proje=secili, durum=durum, **tarihler)
    if durum_kullan:
        kategori = (request.args.get('kategori') or '').strip()[:120]
        if kategori:
            kosul.append('kategori COLLATE UNICODE_NOCASE=?'); par.append(kategori)
        q = (request.args.get('q') or '').strip()[:200]
        if q:
            kosul.append('(personel LIKE ? OR uye_id LIKE ? OR ana_uye_id LIKE ? OR lead_id LIKE ? OR link LIKE ? OR aciklama LIKE ? OR ekleyen_ad LIKE ? OR kategori LIKE ?)')
            par += ['%' + q + '%'] * 8
        ekleyen = (request.args.get('ekleyen') or '').strip()[:100]
        if ekleyen:
            kosul.append('(ekleyen_ad LIKE ? OR ekleyen_id=?)'); par += ['%' + ekleyen + '%', ekleyen]
        meta.update(kategori=kategori, q=q, ekleyen=ekleyen)
    return ' AND '.join(kosul), par, meta, uyari


def _metin(v):
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    if isinstance(v, float) and not math.isfinite(v):
        return None  # JSON'da Infinity/NaN geçerli değil (RFC 8259); null olarak verilir
    return v


def _gorsel_var(row):
    panel = _panel()
    d = {k: _metin(row[k]) for k in row.keys()}
    try:
        yol, _ = panel.COZUCU.yerel_dosya(d)
        # 2.3.2-inc: Snappark/Teamzone da /api/v1/gorsel ile sunulur (panel kayit_sozluk ile aynı kural; ağa çıkmaz).
        return bool(yol) or bool(panel.COZUCU.gyazo_mumkun(d)) or bool(panel.COZUCU.dis_mumkun(d))
    except Exception:
        return False


def _kayit_json(row):
    d = {k: _metin(row[k]) for k in KAYIT_ALANLARI}
    d['onayli'] = bool(d.pop('kt')); d['onaylayan'] = d.pop('kt_kim'); d['onay_zamani'] = d.pop('kt_zaman')
    d['yorum_sayisi'] = row['yorum_sayisi'] if 'yorum_sayisi' in row.keys() else None
    if g.api_anahtar['gorsel_izni']:
        d['gorsel_url'] = '/api/v1/gorsel/%d' % row['id'] if _gorsel_var(row) else None
    return d


def _tam_sayi(ad, varsayilan, en_az, en_cok):
    ham = (request.args.get(ad) or '').strip()
    if not ham:
        return varsayilan
    try:
        deger = int(ham)
    except ValueError:
        raise _Red(400, ad + ' bir tam sayı olmalı.')
    if deger < en_az or deger > en_cok:
        raise _Red(400, '%s %d ile %d arasında olmalı.' % (ad, en_az, en_cok))
    return deger


# ------------------------------------------------------------------ uçlar

@bp.route('/ozet')
def ozet():
    c = _panel().baglanti()
    where, par, meta, uyari = _suzgec(durum_kullan=False)
    toplam = c.execute(f'SELECT COUNT(*) n,COALESCE(SUM(kt=1),0) onayli,COALESCE(SUM(kt=0),0) bekleyen FROM kayitlar WHERE {where}', par).fetchone()
    projeler = [dict(r) for r in c.execute(f'SELECT proje,COUNT(*) toplam,COALESCE(SUM(kt=1),0) onayli,COALESCE(SUM(kt=0),0) bekleyen FROM kayitlar WHERE {where} GROUP BY proje ORDER BY proje', par)]
    capraz = [dict(r) for r in c.execute(f"SELECT COALESCE(kategori,'') kategori,COALESCE(tip,'') tip,COUNT(*) toplam,COALESCE(SUM(kt=1),0) onayli FROM kayitlar WHERE {where} GROUP BY 1,2 ORDER BY toplam DESC,1,2", par)]
    ekleyenler = [dict(r) for r in c.execute(f"SELECT COALESCE(ekleyen_id,'') ekleyen_id,MAX(ekleyen_ad) ekleyen_ad,COUNT(*) toplam,COALESCE(SUM(kt=1),0) onayli FROM kayitlar WHERE {where} GROUP BY 1 ORDER BY toplam DESC,1 LIMIT 50", par)]
    g.api_satir = len(projeler) + len(capraz) + len(ekleyenler)
    sonuc = dict(ok=True, suzgec=meta, toplam=toplam['n'], onayli=toplam['onayli'], bekleyen=toplam['bekleyen'],
                 projeler=projeler, kategori_tip=capraz, ekleyenler=ekleyenler)
    if uyari:
        sonuc['uyari'] = uyari
    return jsonify(sonuc)


@bp.route('/personel-ozet')
def personel_ozet():
    """2.3.4: personel (veya ekleyen) × kategori (veya tip) sayım tablosu; panelin /rapor/personel sayfasıyla aynı işlev."""
    from . import personel_ozeti as po
    projeler, _, yalniz = _kapsam()
    secili = _secili_projeler()
    if len(secili) > 1:
        raise _Red(400, 'proje tek bir proje kodu olmalı (boş = kapsamdaki tüm projeler).')
    args = {k: request.args.get(k, '') for k in ('donem', 'durum', 'grup', 'sutun', 'tarih1', 'tarih2', 'kategori', 'esik')}
    durumlar_iste = (request.args.get('durumlar') or '').strip().lower()
    if durumlar_iste not in ('', '0', '1', 'evet', 'hayir', 'hayır', 'true', 'false'):
        raise _Red(400, 'durumlar için geçersiz değer (geçerli: 0, 1).')
    args['proje'] = secili[0] if secili else ''
    try:
        f, hatalar, uyarilar = po.filtre_coz(args, projeler, bugun=datetime.now().date())
    except PermissionError:
        raise _Red(403, 'Bu anahtarın kapsamı dışındaki proje istendi.')
    if hatalar:
        raise _Red(400, ' '.join(hatalar))
    if yalniz:
        if f['durum'] != 'onayli' and (request.args.get('durum') or '').strip():
            uyarilar.insert(0, 'Bu anahtar yalnız onaylı kayıtları görür; durum süzgeci yok sayıldı.')
        f['durum'] = 'onayli'
    if f.get('kategori'):
        # 2.3.5: kategori adı panelle aynı biçimde (katalog adı, harf duyarsız) eşlenir; bilinmeyen ad sıfır satır döndürür.
        secili_kapsam = [f['proje']] if f['proje'] else list(projeler)
        f['kategori'] = po.kategori_kanonik(po.kategori_secenekleri(_panel().baglanti(), secili_kapsam), f['kategori'])
    ozet_ = po.personel_ozeti(_panel().baglanti(), projeler, None, f)
    g.api_satir = ozet_['kisi_sayisi']
    sonuc = dict(ok=True, **po.api_gorunumu(ozet_, f))
    if durumlar_iste in ('1', 'evet', 'true'):
        # 2.3.7: panelin Durumlar bölümüyle aynı hesap; önceki dönem aynı süzgeçlerle sayılır.
        onceki_f = po.onceki_filtre(f, datetime.now().date())
        onceki_o = po.personel_ozeti(_panel().baglanti(), projeler, None, onceki_f) if onceki_f else None
        sonuc['durumlar'] = po.durumlar_api(po.durumlar(ozet_, onceki_o, f['esik'], f))
        sonuc['filtre']['esik'] = f['esik']
    if uyarilar:
        sonuc['uyari'] = ' '.join(uyarilar)
    return jsonify(sonuc)


@bp.route('/kayitlar')
def kayitlar():
    c = _panel().baglanti()
    where, par, meta, uyari = _suzgec()
    sayfa = _tam_sayi('sayfa', 1, 1, 1000000)
    adet = _tam_sayi('adet', 100, 1, 500)
    toplam = c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {where}', par).fetchone()[0]
    rows = c.execute(f"SELECT k.*,(SELECT COUNT(*) FROM yorumlar y WHERE y.kayit_id=k.id) yorum_sayisi FROM kayitlar k WHERE {where} "
                     f"ORDER BY COALESCE(tarih,'0000') DESC,id DESC LIMIT ? OFFSET ?", (*par, adet, (sayfa - 1) * adet)).fetchall()
    g.api_satir = len(rows)
    sonuc = dict(ok=True, toplam=toplam, sayfa=sayfa, adet=adet, sayfa_sayisi=max(1, math.ceil(toplam / adet)), suzgec=meta,
                 kayitlar=[_kayit_json(r) for r in rows])
    if uyari:
        sonuc['uyari'] = uyari
    return jsonify(sonuc)


def _kapsamdaki_kayit(kid):
    kosul, par = _kapsam_sql()
    row = _panel().baglanti().execute('SELECT k.*,(SELECT COUNT(*) FROM yorumlar y WHERE y.kayit_id=k.id) yorum_sayisi FROM kayitlar k WHERE id=? AND '
                                      + ' AND '.join(kosul), (kid, *par)).fetchone()
    if not row:
        # Kapsam dışı ya da hiç yok: aynı yanıt (kaydın varlığı sızdırılmaz).
        raise _Red(404, 'Kayıt bulunamadı ya da bu anahtarın kapsamında değil.')
    return row


@bp.route('/kayit/<int:kid>')
def kayit(kid):
    row = _kapsamdaki_kayit(kid)
    d = _kayit_json(row)
    d['yorumlar'] = [dict(r) for r in _panel().baglanti().execute(
        "SELECT kullanici,COALESCE(tur,'yorum') tur,metin,zaman FROM yorumlar WHERE kayit_id=? ORDER BY id", (kid,))]
    g.api_satir = 1
    return jsonify(ok=True, kayit=d)


def _gorsel_bekleme():
    from . import gorsel as gorsel_modulu
    return gorsel_modulu.GORSEL_ISTEK_BEKLEME_SN


@bp.route('/gorsel/<int:kid>')
def gorsel(kid):
    if not g.api_anahtar['gorsel_izni']:
        raise _Red(403, 'Bu anahtarın görsel indirme izni yok. Panel yöneticisi anahtar kapsamında "Görsel indirme"yi açmalı.')
    row = _kapsamdaki_kayit(kid)
    panel = _panel()
    d = {k: _metin(row[k]) for k in row.keys()}
    if request.args.get('ikinci') == '1':
        d.update(gorsel_dosya=row['gorsel2_dosya'], link=row['gorsel2'], anahtar=str(row['anahtar'] or row['id']) + ':2')
    try:
        yol, _ = panel.COZUCU.gorsel_yolu(d, bekle=_gorsel_bekleme())
    except Exception:
        yol = None
    if not yol:
        raise _Red(404, 'Bu kaydın görseli yok ya da şu an alınamıyor.')
    if not panel.COZUCU.gecerli(yol):
        raise _Red(422, 'Kaydın görsel dosyası bozuk ya da görsel değil. Panel yöneticisine bildirin.')
    g.api_satir = 1
    try:
        return send_file(yol, conditional=True, download_name='kayit-%d%s' % (kid, Path(yol).suffix.lower() or '.jpg'))
    except FileNotFoundError:
        raise _Red(404, 'Bu kaydın görseli yok ya da şu an alınamıyor.')


# ------------------------------------------------------------------ SQL ucu

class SorguHatasi(Exception):
    def __init__(self, kod, mesaj, neden):
        super().__init__(mesaj)
        self.kod, self.mesaj, self.neden = kod, mesaj, neden


def tek_ifade(sql):
    """Tek SELECT ifadesi: sondaki tek ';' atılır; ';' sonrasında metin (yorum dahil) varsa reddedilir."""
    if not isinstance(sql, str):
        raise SorguHatasi(400, '"sql" alanı metin olmalı.', 'girdi')
    s = sql.strip()
    if not s:
        raise SorguHatasi(400, '"sql" alanı boş.', 'girdi')
    if len(s) > SQL_EN_UZUN or '\x00' in s:
        raise SorguHatasi(400, 'Sorgu çok uzun ya da geçersiz karakter içeriyor (en çok %d karakter).' % SQL_EN_UZUN, 'girdi')
    for i, ch in enumerate(s):
        if ch == ';' and sqlite3.complete_statement(s[:i + 1]):
            if s[i + 1:].strip():
                raise SorguHatasi(400, 'Tek bir SELECT ifadesi gönderin; noktalı virgülden sonra metin olamaz.', 'tek_ifade')
            s = s[:i].rstrip()
            break
    if not re.match(r'(?is)^(select|with|values)\b', s):
        raise SorguHatasi(400, 'Yalnız SELECT sorguları çalıştırılabilir (SELECT, WITH ya da VALUES ile başlamalı).', 'yalniz_select')
    return s


class Yetkilendirici:
    """sqlite3 authorizer: yalnız SELECT, FUNCTION (yasaklılar hariç) ve izinli READ. Diğer her şey SQLITE_DENY.

    READ kuralları:
      * ``main.<tablo>``: yalnız 5. argüman (en içteki görünüm) bu istekte rastgele adla kurulan iç görünümlerden biri ve
        tablo o görünümün izinli tablosu ise;
      * ``temp.<görünüm>``: yalnız kullanıcıya açılan dört görünüm ve iç görünümler.
    Böylece ``panel_kullanicilari``, ``ayarlar``, ``denetim``, ``tg_gelen``, ``sqlite_master``, PRAGMA tablo işlevleri vb. okunamaz."""

    def __init__(self, ic_kaynaklar, temp_adlari):
        self.ic_kaynaklar = ic_kaynaklar      # iç görünüm adı → izinli main tablo kümesi
        self.temp_adlari = frozenset(temp_adlari)
        self.cagri = 0
        self.red = 0

    def __call__(self, eylem, a1, a2, veritabani, kaynak):
        self.cagri += 1
        if eylem == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if eylem == sqlite3.SQLITE_FUNCTION:
            ad = str(a2 or '').lower()
            if ad in YASAK_FONKSIYONLAR or ad.startswith(YASAK_ONEKLER):
                self.red += 1
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if eylem == sqlite3.SQLITE_READ:
            if veritabani == 'main' and kaynak in self.ic_kaynaklar and a1 in self.ic_kaynaklar[kaynak]:
                return sqlite3.SQLITE_OK
            if veritabani == 'temp' and a1 in self.temp_adlari:
                return sqlite3.SQLITE_OK
        self.red += 1
        return sqlite3.SQLITE_DENY


def _sql_liste(projeler):
    temiz = [p for p in projeler if aa.PROJE_RX.fullmatch(p)]
    return ','.join("'" + p + "'" for p in temiz)


def gorunumleri_kur(conn, projeler, tumu, yalniz_onayli):
    """Kapsamla süzülmüş TEMP görünümleri kurar (authorizer kurulmadan önce). (iç kaynaklar, temp adları) döndürür."""
    kosul = ['k.silindi=0']
    if not tumu:
        liste = _sql_liste(projeler)
        kosul.append('k.proje IN (%s)' % liste if liste else '1=0')
    if yalniz_onayli:
        kosul.append('k.kt=1')
    where = ' AND '.join(kosul)
    etiket = '_kp_' + secrets.token_hex(8)
    ic = {ad: etiket + '_' + ad for ad in SQL_GORUNUMLER}
    tanimlar = {
        'kayitlar': ('SELECT %s FROM main.kayitlar k WHERE %s' % (','.join('k.' + s for s in SQL_KAYIT_SUTUNLARI), where), {'kayitlar'}),
        'yorumlar': ('SELECT %s FROM main.yorumlar y JOIN main.kayitlar k ON k.id=y.kayit_id WHERE %s'
                     % (','.join('y.' + s for s in SQL_YORUM_SUTUNLARI), where), {'yorumlar', 'kayitlar'}),
        'kategoriler': ('SELECT code,label,mode FROM main.kategoriler', {'kategoriler'}),
        # 2.3.2-inc: tüm projeler kapsamlı anahtar dışında yalnız kapsamdaki kayıtları ekleyen Telegram kullanıcıları görünür.
        'tg_kullanicilar': (('SELECT u.id,u.username,u.first_name,u.onayli,u.engelli FROM main.tg_kullanicilar u' if tumu and not yalniz_onayli else
                             'SELECT u.id,u.username,u.first_name,u.onayli,u.engelli FROM main.tg_kullanicilar u WHERE u.id IN '
                             '(SELECT k.ekleyen_id FROM main.kayitlar k WHERE %s)' % where), {'tg_kullanicilar', 'kayitlar'}),
    }
    kaynaklar = {}
    for ad, (secim, tablolar) in tanimlar.items():
        conn.execute('CREATE TEMP VIEW "%s" AS %s' % (ic[ad], secim))
        conn.execute('CREATE TEMP VIEW "%s" AS SELECT * FROM temp."%s"' % (ad, ic[ad]))
        kaynaklar[ic[ad]] = frozenset(tablolar)
    return kaynaklar, set(SQL_GORUNUMLER) | set(ic.values())


def _hata_ozeti(error):
    metin = str(error).lower()
    if 'not authorized' in metin or 'authorization denied' in metin or 'prohibited' in metin or 'no such table' in metin:
        return SorguHatasi(403, 'Sorgu izin verilmeyen bir tabloya ya da işleme erişiyor. Yalnız kayitlar, yorumlar, kategoriler ve '
                                'tg_kullanicilar görünümleri okunabilir; yazma, PRAGMA, ATTACH ve özyinelemeli (RECURSIVE) sorgular kapalı.', 'yetki')
    if 'interrupted' in metin:
        return SorguHatasi(400, 'Sorgu %g saniyede bitmedi ve durduruldu. Süzgeç ekleyin ya da sorguyu sadeleştirin.' % SQL_SURE_SN, 'sure')
    if 'no such column' in metin:
        return SorguHatasi(400, 'Sorguda bilinmeyen bir sütun var. İzinli sütunlar için API_KULLANIM.md belgesine bakın.', 'sutun')
    if 'no such function' in metin:
        return SorguHatasi(400, 'Sorguda bilinmeyen bir işlev var.', 'islev')
    if 'syntax error' in metin or 'incomplete input' in metin or 'unrecognized token' in metin:
        return SorguHatasi(400, 'SQL söz dizimi hatalı. Sorguyu kontrol edin.', 'sozdizimi')
    if 'too big' in metin or 'too many' in metin:
        return SorguHatasi(400, 'Sorgu ya da sonuç değeri izin verilen boyutu aşıyor.', 'boyut')
    if 'binding' in metin or 'parameter' in metin:
        return SorguHatasi(400, 'Parametre sayısı sorgudaki ? sayısıyla uyuşmuyor.', 'parametre')
    return SorguHatasi(400, 'Sorgu çalıştırılamadı. Sorguyu kontrol edin.', 'diger')


def _golge_hata(sql, parametreler):
    """'no such column' hatasında şema varlığı sızmasın: sorgu yalnız dört izinli görünümün BOŞ kopyasını içeren bellek içi bir
    veritabanında derlenir (EXPLAIN, çalıştırılmaz). Orada tablo bulunamıyorsa kullanıcı izinli olmayan bir tabloya (var ya da yok)
    başvurmuştur → her durumda aynı 403. Yalnız izinli görünümlerde gerçekten olmayan sütun 400 'sutun' alır."""
    golge = sqlite3.connect(':memory:', isolation_level=None)
    try:
        golge.create_collation('UNICODE_NOCASE', lambda a, b: 0)
        for ad, sutunlar in (('kayitlar', SQL_KAYIT_SUTUNLARI), ('yorumlar', SQL_YORUM_SUTUNLARI), ('kategoriler', ('code', 'label', 'mode')),
                             ('tg_kullanicilar', ('id', 'username', 'first_name', 'onayli', 'engelli'))):
            golge.execute('CREATE TEMP TABLE "%s" (%s)' % (ad, ','.join('"%s"' % x for x in sutunlar)))
        bitis = time.monotonic() + 1.0
        golge.set_progress_handler(lambda: 1 if time.monotonic() > bitis else 0, 1000)
        golge.execute('EXPLAIN ' + sql, parametreler).fetchall()
    except sqlite3.Error as error:
        metin = str(error).lower()
        if 'no such table' in metin or 'no such column' not in metin:
            return _hata_ozeti(sqlite3.OperationalError('not authorized'))
        return _hata_ozeti(error)
    except Exception:
        return _hata_ozeti(sqlite3.OperationalError('not authorized'))
    finally:
        golge.close()
    return _hata_ozeti(sqlite3.OperationalError('not authorized'))


def _parametre_dogrula(parametreler):
    if parametreler is None:
        parametreler = []
    if not isinstance(parametreler, list) or len(parametreler) > SQL_EN_COK_PARAMETRE or any(
            p is not None and not isinstance(p, (str, int, float, bool)) for p in parametreler):
        raise SorguHatasi(400, '"parametreler" en çok %d öğelik bir liste olmalı (metin, sayı ya da null).' % SQL_EN_COK_PARAMETRE, 'parametre')
    temiz = []
    for p in parametreler:
        if isinstance(p, bool):
            p = int(p)
        elif isinstance(p, int) and not (-2 ** 63 <= p < 2 ** 63):
            raise SorguHatasi(400, 'Parametredeki tam sayı 64 bit aralığını aşıyor.', 'girdi')
        elif isinstance(p, float) and not math.isfinite(p):
            raise SorguHatasi(400, 'Parametrede NaN ya da sonsuz sayı kullanılamaz.', 'girdi')
        elif isinstance(p, str):
            try:
                p.encode('utf-8')
            except UnicodeError:
                raise SorguHatasi(400, 'Parametrede geçersiz (eşi olmayan vekil) karakter var.', 'girdi')
            if len(p) > SQL_DEGER_EN_UZUN:
                raise SorguHatasi(400, 'Metin parametresi en çok %d karakter olabilir.' % SQL_DEGER_EN_UZUN, 'boyut')
        temiz.append(p)
    return temiz


def _deger_boyutu(v):
    if isinstance(v, (str, bytes)):
        # JSON'da ASCII dışı karakter \uXXXX olarak (6 bayt) yazılır; üst sınır güvenli tarafta hesaplanır.
        return len(v) if isinstance(v, bytes) or v.isascii() else 6 * len(v)
    return 24


def sorgu_calistir(db_yolu, sql, parametreler, projeler, tumu, yalniz_onayli, sure_sn=None, en_cok=None, en_cok_bayt=None):
    """Authorizer'lı salt okunur bağlantıda sorgu. dict döndürür; hata → SorguHatasi.

    Sınırlar: süre (SQL_SURE_SN), satır (SQL_EN_COK_SATIR), toplam değer boyutu (SQL_EN_COK_BAYT), tek değer (SQL_DEGER_EN_UZUN).
    Satırlar tek tek alınır; sınırlardan biri dolunca durulur ve ``kesildi=True, neden='satir'|'boyut'`` döner."""
    sure_sn = SQL_SURE_SN if sure_sn is None else sure_sn
    en_cok = SQL_EN_COK_SATIR if en_cok is None else en_cok
    en_cok_bayt = SQL_EN_COK_BAYT if en_cok_bayt is None else en_cok_bayt
    sql = tek_ifade(sql)
    try:
        sql.encode('utf-8')
    except UnicodeError:
        raise SorguHatasi(400, 'Sorguda geçersiz (eşi olmayan vekil) karakter var.', 'girdi')
    parametreler = _parametre_dogrula(parametreler)
    uri = 'file:' + quote(str(Path(db_yolu).resolve())) + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    try:
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, SQL_DEGER_EN_UZUN)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, SQL_EN_UZUN + 1000)
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, SQL_EN_COK_PARAMETRE)
        conn.create_collation('UNICODE_NOCASE', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
        kaynaklar, temp_adlari = gorunumleri_kur(conn, projeler, tumu, yalniz_onayli)
        yetkili = Yetkilendirici(kaynaklar, temp_adlari)
        conn.set_authorizer(yetkili)
        # Öz denetim: authorizer gerçekten devrede mi? Ana tabloya doğrudan okuma reddedilmeli; reddedilmezse sorgu ÇALIŞTIRILMAZ.
        once = yetkili.red
        try:
            conn.execute('SELECT 1 FROM main.ayarlar LIMIT 1').fetchall()
            denetim_gecti = False
        except sqlite3.DatabaseError:
            denetim_gecti = yetkili.red > once
        if not denetim_gecti:
            raise RuntimeError('SQL yetkilendiricisi devrede değil; sorgu çalıştırılmadı.')
        bitis = time.monotonic() + sure_sn
        conn.set_progress_handler(lambda: 1 if time.monotonic() > bitis else 0, 1000)
        basla = time.perf_counter()
        satirlar, toplam, neden = [], 0, None
        try:
            # Kullanıcı ifadesi metin birleştirmeyle sarılmaz (kapanmamış /* ya da ')' ile dış sorgudan çıkış yok);
            # satır ve boyut sınırı aşağıdaki döngüde uygulanır. İlerleme işleyicisi döngü boyunca da etkindir.
            cur = conn.execute(sql, parametreler)
            for r in cur:
                if len(satirlar) >= en_cok:
                    neden = 'satir'
                    break
                toplam += sum(_deger_boyutu(v) for v in r)
                if toplam > en_cok_bayt:
                    neden = 'boyut'
                    break
                satirlar.append(r)
        except sqlite3.Error as error:
            if 'no such column' in str(error).lower():
                raise _golge_hata(sql, parametreler)
            raise _hata_ozeti(error)
        except (OverflowError, UnicodeError, ValueError):
            raise SorguHatasi(400, 'Sorgu ya da parametre değeri işlenemedi (çok büyük sayı ya da geçersiz karakter).', 'girdi')
        sutunlar = [d[0] for d in cur.description or []]
        satirlar = [[_metin(v) for v in r] for r in satirlar]
        sonuc = dict(sutunlar=sutunlar, satirlar=satirlar, satir_sayisi=len(satirlar), kesildi=neden is not None,
                     sure_ms=int((time.perf_counter() - basla) * 1000))
        if neden:
            sonuc['neden'] = neden
        return sonuc
    finally:
        conn.close()


def _sorgu_kapisi_al(ozet):
    """(None, None) ya da (neden, mesaj). Süreç genelinde en çok API_SORGU_ESZAMANLI, anahtar başına aynı anda 1 sorgu."""
    sinir = sorgu_eszamanli_siniri()
    with _SQL_KILIT:
        if _SQL_AKTIF.get(ozet):
            return 'es_zamanli_anahtar', 'Bu anahtarla zaten bir sorgu çalışıyor; o bitince yenisini gönderin.'
        if _SQL_TOPLAM[0] >= sinir:
            return 'es_zamanli', 'SQL sorgu kuyruğu dolu, birkaç saniye sonra deneyin.'
        _SQL_TOPLAM[0] += 1
        _SQL_AKTIF[ozet] = 1
    return None, None


def _sorgu_kapisi_birak(ozet):
    with _SQL_KILIT:
        _SQL_TOPLAM[0] = max(0, _SQL_TOPLAM[0] - 1)
        _SQL_AKTIF.pop(ozet, None)


@bp.route('/sorgu', methods=['POST'])
def sorgu():
    if not g.api_anahtar['sql_izni']:
        raise _Red(403, 'Bu anahtarın SQL sorgu izni yok. Panel yöneticisi anahtar kapsamında "SQL sorgusu"nu açmalı.')
    veri = request.get_json(silent=True)
    if not isinstance(veri, dict):
        raise _Red(400, 'Gövde JSON olmalı: {"sql": "SELECT …", "parametreler": […]}. Content-Type: application/json gönderin.')
    projeler, tumu, yalniz = _kapsam()
    ozet = g.api_anahtar['ozet']
    neden, mesaj = _sorgu_kapisi_al(ozet)
    if neden:
        resp = _hata(429, mesaj, neden=neden)
        resp.headers['Retry-After'] = str(SQL_RETRY_AFTER)
        return resp
    try:
        sonuc = sorgu_calistir(_panel().AYAR['DB'], veri.get('sql'), veri.get('parametreler'), projeler, tumu, yalniz)
    except SorguHatasi as error:
        raise _Red(error.kod, error.mesaj, neden=error.neden)
    finally:
        _sorgu_kapisi_birak(ozet)
    g.api_satir = sonuc['satir_sayisi']
    return jsonify(ok=True, **sonuc)
