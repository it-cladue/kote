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
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, current_app, g, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

from . import api_anahtarlari as aa
from . import db

bp = Blueprint('api', __name__, url_prefix='/api/v1')

EN_BUYUK_GOVDE = 64 * 1024
SQL_SURE_SN = 5.0
SQL_EN_COK_SATIR = 5000
SQL_EN_UZUN = 20000
SQL_EN_COK_PARAMETRE = 100
YETKISIZ_IP_SINIRI = 30  # dakikada IP başına geçersiz anahtar denemesi; aşan istekler günlüğe yazılmadan 429 alır
HIZ = aa.HizSiniri()
YETKISIZ_HIZ = aa.HizSiniri()

KAYIT_ALANLARI = ('id', 'proje', 'kategori', 'personel', 'uye_id', 'ana_uye_id', 'lead_id', 'tip', 'tarih', 'kt', 'kt_kim', 'kt_zaman',
                  'ekleyen_id', 'ekleyen_ad', 'link', 'link_turu', 'aciklama')
# SQL ucundaki ``kayitlar`` görünümünün sütunları (ham DB adlarıyla). Dosya yolu, Telegram sohbet/mesaj kimliği gibi iç alanlar yok.
SQL_KAYIT_SUTUNLARI = ('id', 'proje', 'kategori', 'kategori_code', 'kategori_mode', 'personel', 'uye_id', 'ana_uye_id', 'lead_id', 'tip',
                       'tarih', 'kt', 'kt_kim', 'kt_zaman', 'ekleyen_id', 'ekleyen_ad', 'link', 'link_turu', 'aciklama', 'kaynak',
                       'giris_tipi', 'ilk_gorulme', 'guncelleme')
SQL_YORUM_SUTUNLARI = ('id', 'kayit_id', 'kullanici', 'tur', 'metin', 'zaman', 'yanit_id')
SQL_GORUNUMLER = ('kayitlar', 'yorumlar', 'kategoriler', 'tg_kullanicilar')
YASAK_FONKSIYONLAR = frozenset({'load_extension', 'zeroblob', 'randomblob', 'readfile', 'writefile', 'fts3_tokenizer', 'edit'})


def _panel():
    from . import panel
    return panel


def acik_mi():
    return str(os.getenv('API_ACIK', '1') or '1').strip().lower() not in ('0', 'false', 'hayir', 'hayır', 'kapali', 'kapalı', 'no', 'off')


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


@bp.before_request
def _kimlik():
    g.api_basla = time.perf_counter(); g.api_anahtar = None; g.api_satir = None; g.api_gunluk = False
    if not acik_mi():
        return _hata(404, HTTP_MESAJLARI[404])
    if request.content_length is not None and request.content_length > EN_BUYUK_GOVDE:
        g.api_gunluk = True
        return _hata(413, HTTP_MESAJLARI[413])
    request.max_content_length = EN_BUYUK_GOVDE
    c = _panel().baglanti()
    anahtar, neden = aa.dogrula(c, _bearer())
    if not anahtar:
        izin, bekle = YETKISIZ_HIZ.dene('ip:' + str(request.remote_addr), YETKISIZ_IP_SINIRI)
        if not izin:
            resp = _hata(429, 'Çok fazla geçersiz anahtar denemesi. ' + str(bekle) + ' saniye sonra tekrar deneyin.')
            resp.headers['Retry-After'] = str(bekle)
            return resp
        g.api_gunluk = True
        mesaj = {'yok': 'API anahtarı gerekli: Authorization: Bearer kp_… başlığını gönderin. Oturum çerezi kabul edilmez.',
                 'iptal': 'Bu API anahtarı iptal edilmiş. Panel yöneticisinden yeni anahtar isteyin.',
                 'suresi_doldu': 'Bu API anahtarının süresi dolmuş. Panel yöneticisinden yeni anahtar isteyin.'}.get(
                     neden, 'API anahtarı geçersiz. Anahtarı eksiksiz kopyaladığınızdan emin olun.')
        resp = _hata(401, mesaj)
        resp.headers['WWW-Authenticate'] = 'Bearer realm="kanit-paneli-api"'
        return resp
    g.api_anahtar = anahtar; g.api_gunluk = True
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
        kosul.append('tarih >= ?'); par.append(t1 + ' 00:00:00')
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
    if durum_kullan and not yalniz:
        durum = (request.args.get('durum') or 'hepsi').strip().lower()
        if durum not in ('onayli', 'bekleyen', 'hepsi'):
            raise _Red(400, 'durum yalnız onayli, bekleyen ya da hepsi olabilir.')
        if durum == 'onayli':
            kosul.append('kt=1')
        elif durum == 'bekleyen':
            kosul.append('kt=0')
    tarihler, uyari = _tarih_suzgeci(kosul, par)
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
    return v


def _gorsel_var(row):
    panel = _panel()
    d = {k: _metin(row[k]) for k in row.keys()}
    try:
        yol, _ = panel.COZUCU.yerel_dosya(d)
        return bool(yol) or panel.COZUCU.gyazo_mumkun(d)
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
        yol, _ = panel.COZUCU.gorsel_yolu(d)
    except Exception:
        yol = None
    if not yol:
        raise _Red(404, 'Bu kaydın görseli yok ya da şu an alınamıyor.')
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
            if str(a2 or '').lower() in YASAK_FONKSIYONLAR:
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
        'tg_kullanicilar': ('SELECT id,username,first_name,onayli,engelli FROM main.tg_kullanicilar', {'tg_kullanicilar'}),
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


def sorgu_calistir(db_yolu, sql, parametreler, projeler, tumu, yalniz_onayli, sure_sn=None, en_cok=None):
    """Authorizer'lı salt okunur bağlantıda sorgu. dict döndürür; hata → SorguHatasi."""
    sure_sn = SQL_SURE_SN if sure_sn is None else sure_sn
    en_cok = SQL_EN_COK_SATIR if en_cok is None else en_cok
    sql = tek_ifade(sql)
    if parametreler is None:
        parametreler = []
    if not isinstance(parametreler, list) or len(parametreler) > SQL_EN_COK_PARAMETRE or any(
            p is not None and not isinstance(p, (str, int, float, bool)) for p in parametreler):
        raise SorguHatasi(400, '"parametreler" en çok %d öğelik bir liste olmalı (metin, sayı ya da null).' % SQL_EN_COK_PARAMETRE, 'parametre')
    parametreler = [int(p) if isinstance(p, bool) else p for p in parametreler]
    uri = 'file:' + quote(str(Path(db_yolu).resolve())) + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=5, isolation_level=None)
    try:
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1000000)
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
        try:
            cur = conn.execute('SELECT * FROM (\n' + sql + '\n) LIMIT %d' % (en_cok + 1), parametreler)
            satirlar = cur.fetchmany(en_cok + 1)
        except sqlite3.Error as error:
            raise _hata_ozeti(error)
        sutunlar = [d[0] for d in cur.description or []]
        kesildi = len(satirlar) > en_cok
        satirlar = [[_metin(v) for v in r] for r in satirlar[:en_cok]]
        return dict(sutunlar=sutunlar, satirlar=satirlar, satir_sayisi=len(satirlar), kesildi=kesildi,
                    sure_ms=int((time.perf_counter() - basla) * 1000))
    finally:
        conn.close()


@bp.route('/sorgu', methods=['POST'])
def sorgu():
    if not g.api_anahtar['sql_izni']:
        raise _Red(403, 'Bu anahtarın SQL sorgu izni yok. Panel yöneticisi anahtar kapsamında "SQL sorgusu"nu açmalı.')
    veri = request.get_json(silent=True)
    if not isinstance(veri, dict):
        raise _Red(400, 'Gövde JSON olmalı: {"sql": "SELECT …", "parametreler": […]}. Content-Type: application/json gönderin.')
    projeler, tumu, yalniz = _kapsam()
    try:
        sonuc = sorgu_calistir(_panel().AYAR['DB'], veri.get('sql'), veri.get('parametreler'), projeler, tumu, yalniz)
    except SorguHatasi as error:
        raise _Red(error.kod, error.mesaj, neden=error.neden)
    g.api_satir = sonuc['satir_sayisi']
    return jsonify(ok=True, **sonuc)
