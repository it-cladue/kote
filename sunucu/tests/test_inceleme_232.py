"""2.3.2 bağımsız inceleme sonrası regresyonlar (inc232: sql_ucu / api_kimlik / dis_gorsel / uyum bulguları).

Her ORTA+ bulgu önce bu dosyada başarısız test olarak yeniden üretildi, sonra kapatıldı.
"""
import io
import os
import socket
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests
from PIL import Image

from app import api, db, gorsel
from test_web import web, login  # noqa: F401
from test_api_232 import anahtar, B, ekle, sorgu, veri
from test_dis_gorsel_232 import SahteDis, ayar_yap, png, sha1, SP_ID, SP_RAW, TZ, TZ_ID, URLOturum
from test_gyazo_toplu import SahteYanit


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    monkeypatch.delenv('API_ACIK', raising=False); monkeypatch.delenv('API_DAKIKA_SINIRI', raising=False)
    monkeypatch.delenv('API_SORGU_ESZAMANLI', raising=False)
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


def _bos_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


# ================================================================ 1. [YÜKSEK, sql_ucu] toplam yanıt boyutu

def test_sql_toplam_yanit_boyutu_8mb_ile_kesilir(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    v = ','.join('(%d)' % i for i in range(20))
    # 60 KB × 200 satır = ~12 MB ham veri: 8 MB'ta durmalı.
    r = sorgu(c, k, "SELECT printf('%%.*c', 60000, 'a') FROM (VALUES %s) a, (VALUES %s) b LIMIT 200" % (v, v))
    assert r.status_code == 200 and r.json['kesildi'] is True and r.json.get('neden') == 'boyut'
    assert len(r.data) < 9 * 1024 * 1024 and r.json['satir_sayisi'] < 200


def test_sql_tek_deger_64kb_ve_satir_siniri_1000(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    r = sorgu(c, k, "SELECT printf('%.*c', 999999, 'a')")  # 1 MB tek değer: 64 KB sınırında SQLite printf NULL döndürür
    assert r.status_code == 200 and r.json['satirlar'] == [[None]]
    v2 = ','.join('(%d)' % i for i in range(3))
    r = sorgu(c, k, "SELECT group_concat(printf('%%.*c', 30000, 'a')) FROM (VALUES %s)" % v2)  # 90 KB birleşik değer
    assert r.status_code == 400 and r.json['neden'] == 'boyut'
    assert sorgu(c, k, "SELECT printf('%.*c', 60000, 'a')").status_code == 200
    assert api.SQL_EN_COK_SATIR == 1000
    v = ','.join('(%d)' % i for i in range(40))
    r = sorgu(c, k, 'SELECT a.column1 FROM (VALUES %s) a, (VALUES %s) b' % (v, v))  # 1600 satır
    assert r.status_code == 200 and r.json['kesildi'] is True and r.json['satir_sayisi'] == 1000 and r.json.get('neden') == 'satir'
    r = sorgu(c, k, 'SELECT 1')
    assert r.json['kesildi'] is False and 'neden' not in r.json


# ================================================================ 2. [ORTA, sql_ucu + uyum] eşzamanlılık

def _bekleten_sorgu(monkeypatch):
    """sorgu_calistir'i olay bekleyen sahte ile değiştirir; (giren sayacı, bırak olayı)."""
    giren = []
    birak = threading.Event()

    def sahte(*a, **kw):
        giren.append(1)
        birak.wait(10)
        return dict(sutunlar=['x'], satirlar=[[1]], satir_sayisi=1, kesildi=False, sure_ms=1)
    monkeypatch.setattr(api, 'sorgu_calistir', sahte)
    return giren, birak


def _bekle(kosul, sn=5):
    son = time.monotonic() + sn
    while time.monotonic() < son:
        if kosul():
            return True
        time.sleep(0.01)
    return False


def test_sql_eszamanli_en_cok_2_ucuncu_429(web, monkeypatch):
    c, a = web
    anahtarlar = [anahtar(a, '*', sql_izni=True, ad='s%d' % i)[1] for i in range(3)]
    giren, birak = _bekleten_sorgu(monkeypatch)
    sonuc = {}
    iplikler = [threading.Thread(target=lambda i=i: sonuc.__setitem__(i, sorgu(c, anahtarlar[i], 'SELECT 1').status_code)) for i in range(2)]
    for t in iplikler:
        t.start()
    assert _bekle(lambda: len(giren) == 2)
    r = sorgu(c, anahtarlar[2], 'SELECT 1')
    assert r.status_code == 429 and r.headers['Retry-After'] == '2' and 'sorgu kuyruğu dolu' in r.json['hata'] and r.json['neden'] == 'es_zamanli'
    assert c.get('/saglik').status_code == 200  # panel bu sırada yanıt veriyor
    birak.set()
    for t in iplikler:
        t.join(5)
    assert sonuc == {0: 200, 1: 200}
    assert sorgu(c, anahtarlar[2], 'SELECT 1').status_code == 200  # kapı serbest bırakıldı


def test_sql_anahtar_basina_ayni_anda_1(web, monkeypatch):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    _, k2 = anahtar(a, '*', sql_izni=True, ad='ikinci')
    giren, birak = _bekleten_sorgu(monkeypatch)
    t = threading.Thread(target=lambda: sorgu(c, k, 'SELECT 1'))
    t.start()
    assert _bekle(lambda: len(giren) == 1)
    r = sorgu(c, k, 'SELECT 1')
    assert r.status_code == 429 and r.headers['Retry-After'] == '2' and r.json['neden'] == 'es_zamanli_anahtar'
    birak.set(); t.join(5)
    giren.clear(); birak.clear()
    birak.set()
    assert sorgu(c, k2, 'SELECT 1').status_code == 200 and sorgu(c, k, 'SELECT 1').status_code == 200


def test_sql_eszamanli_ayari(monkeypatch):
    for deger, beklenen in (('', 2), ('3', 3), ('0', 2), ('abc', 2), ('-1', 2), ('6', 6), ('50', 6)):
        monkeypatch.setenv('API_SORGU_ESZAMANLI', deger)
        assert api.sorgu_eszamanli_siniri() == beklenen, deger


# ================================================================ 6. [ORTA, uyum] gorsel_url Snappark/Teamzone

def test_api_gorsel_url_snappark_ve_teamzone(web):
    c, a = web
    from app import panel
    s = SahteDis()
    try:
        panel.COZUCU.dis_test_host = '127.0.0.1:%d' % s.port
        oturum = requests.Session(); oturum.trust_env = False; panel.COZUCU._http = oturum
        s.gorsel('/img.snappark.net/s/%s/raw/' % SP_ID, png())
        sp = ekle(a, kt=1, link='https://snappark.net/s/%s' % SP_ID, link_turu='snappark')
        tz = ekle(a, kt=1, link=TZ, link_turu='teamzone')
        _, k = anahtar(a, ['OF'], gorsel_izni=True)
        assert c.get('/api/v1/kayit/%d' % sp, headers=B(k)).json['kayit']['gorsel_url'] == '/api/v1/gorsel/%d' % sp
        liste = {x['id']: x for x in c.get('/api/v1/kayitlar', headers=B(k)).json['kayitlar']}
        assert liste[sp]['gorsel_url'] == '/api/v1/gorsel/%d' % sp and liste[tz]['gorsel_url'] == '/api/v1/gorsel/%d' % tz
        r = c.get('/api/v1/gorsel/%d' % sp, headers=B(k))
        assert r.status_code == 200 and r.data[:4] == b'\x89PNG'
        assert c.get('/api/v1/kayit/%d' % sp, headers=B(k)).json['kayit']['gorsel_url'] == '/api/v1/gorsel/%d' % sp  # önbellekten sonra da
        _, k0 = anahtar(a, ['OF'], ad='izinsiz')
        assert 'gorsel_url' not in c.get('/api/v1/kayit/%d' % sp, headers=B(k0)).json['kayit']
    finally:
        s.close()


# ================================================================ 3. [ORTA, dis_gorsel] tek ölü bağlantı tüm servisi atlatmasın

def _yavas_sunucu(host='127.0.0.1'):
    """Basit sahte: yollar[yol] = (durum, başlık, gövde, gecikme_sn)."""
    class S:
        pass
    s = S(); s.hits = []; s.yollar = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            s.hits.append(self.path)
            durum, basliklar, govde, gecikme = s.yollar.get(self.path, (404, {}, b'', 0))
            if gecikme:
                time.sleep(gecikme)
            try:
                self.send_response(durum)
                for k_, v_ in basliklar.items():
                    self.send_header(k_, v_)
                if 'Content-Length' not in basliklar:
                    self.send_header('Content-Length', str(len(govde)))
                self.end_headers()
                if govde:
                    self.wfile.write(govde)
            except OSError:
                pass
    s.server = ThreadingHTTPServer((host, 0), H)
    s.server.daemon_threads = True
    s.port = s.server.server_address[1]
    threading.Thread(target=s.server.serve_forever, daemon=True).start()
    s.close = lambda: (s.server.shutdown(), s.server.server_close())
    return s


def _dis_db(tmp_path, linkler):
    a = ayar_yap(tmp_path)
    conn = db.baglan(a['DB'])
    for i, link in enumerate(linkler):
        conn.execute('INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)', ('d%d' % i, 'OF', str(i), link))
    conn.commit()
    return a, conn


def test_toplu_404_ve_200_karisik_yalniz_404_acilamaz(tmp_path):
    s = _yavas_sunucu()
    try:
        idler = ['Olu404', 'Iyi1', 'Iyi2', 'Iyi3']
        a, conn = _dis_db(tmp_path, ['https://snappark.net/s/%s' % i for i in idler])
        for i in idler[1:]:
            s.yollar['/img.snappark.net/s/%s/raw/' % i] = (200, {'Content-Type': 'image/png'}, png(), 0)
        c = gorsel.GorselCozucu(a, a['ONBELLEK']); c.dis_test_host = '127.0.0.1:%d' % s.port
        o = requests.Session(); o.trust_env = False; c._http = o
        r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0)
        assert r['indirilen'] == 3 and r['acilamayan'] == 1 and 'dis_erisim_yok' not in r
    finally:
        s.close()


@pytest.mark.parametrize('senaryo', ['bozuk_location', 'asili', 'kopan_govde'])
def test_toplu_bagilantiya_ozgu_hata_servisi_atlatmaz(tmp_path, monkeypatch, senaryo):
    s = _yavas_sunucu()
    try:
        idler = ['Sorun1', 'Iyi1', 'Iyi2', 'Iyi3']
        a, conn = _dis_db(tmp_path, ['https://snappark.net/s/%s' % i for i in idler])
        for i in idler[1:]:
            s.yollar['/img.snappark.net/s/%s/raw/' % i] = (200, {'Content-Type': 'image/png'}, png(), 0)
        ilk = '/img.snappark.net/s/Sorun1/raw/'
        if senaryo == 'bozuk_location':
            s.yollar[ilk] = (302, {'Location': 'http://img.snappark.net:99999/x'}, b'', 0)
        elif senaryo == 'asili':
            monkeypatch.setattr(gorsel, 'GYAZO_ZAMAN_ASIMI', 0.5)
            s.yollar[ilk] = (200, {'Content-Type': 'image/png'}, png(), 2)
        else:
            s.yollar[ilk] = (200, {'Content-Type': 'image/png', 'Content-Length': '5000'}, b'\x89PNG' + b'x' * 16, 0)
        c = gorsel.GorselCozucu(a, a['ONBELLEK']); c.dis_test_host = '127.0.0.1:%d' % s.port
        o = requests.Session(); o.trust_env = False; c._http = o
        r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0)
        assert r['indirilen'] == 3 and r['acilamayan'] == 1 and 'dis_erisim_yok' not in r, r
    finally:
        s.close()


def test_toplu_art_arda_3_baglanti_hatasi_servisi_atlar(tmp_path):
    kapali = _bos_port()
    idler = ['Ag1', 'Ag2', 'Ag3', 'Ag4', 'Ag5']
    a, conn = _dis_db(tmp_path, ['https://snappark.net/s/%s' % i for i in idler])
    c = gorsel.GorselCozucu(a, a['ONBELLEK']); c.dis_test_host = '127.0.0.1:%d' % kapali
    o = requests.Session(); o.trust_env = False; c._http = o
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0, log=loglar.append)
    assert r['dis_erisim_yok'] == ['Snappark'] and r['acilamayan'] == 5 and r['indirilen'] == 0
    sebepler = [x[4] for x in r['acilamayan_ornek']]
    assert sebepler[:3] == ['bağlantı kurulamadı (DNS / bağlantı reddi / zaman aşımı)'] * 3
    assert all('art arda 3 bağlantı kurulamadı' in x and 'denenmedi' in x for x in sebepler[3:]) and len(sebepler) == 5
    assert any('art arda 3' in m for m in loglar)


def test_toplu_baglanti_hatasi_sonra_basari_sayaci_sifirlar(tmp_path):
    plan = {}
    idler = ['Ag01', 'Ag02', 'Iyi', 'Ag03', 'Ag04', 'Son']
    for i in idler:
        u = 'https://img.snappark.net/s/%s/raw/' % i
        if i in ('Iyi', 'Son'):
            g = png(); plan[u] = [SahteYanit(200, g, {'Content-Type': 'image/png', 'Content-Length': str(len(g))})]
        else:
            plan[u] = [requests.exceptions.ConnectionError('Failed to establish a new connection')] * 2
    a, conn = _dis_db(tmp_path, ['https://snappark.net/s/%s' % i for i in idler])
    c = gorsel.GorselCozucu(a, a['ONBELLEK']); c._http = URLOturum(plan)
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0)
    assert r['indirilen'] == 2 and r['acilamayan'] == 4 and 'dis_erisim_yok' not in r


def test_teamzone_tek_aday_hatasi_digerlerini_engellemez(tmp_path):
    a = ayar_yap(tmp_path)
    c = gorsel.GorselCozucu(a, a['ONBELLEK'])
    g = png()
    c._http = URLOturum({'https://i.gyazo.com/%s.png' % TZ_ID: [requests.exceptions.ReadTimeout('yavaş')],
                         'https://i.gyazo.com/%s.jpg' % TZ_ID: [SahteYanit(200, g, {'Content-Type': 'image/png', 'Content-Length': str(len(g))})]})
    assert c.dis_indir({'link': TZ}) and c._dis_son_durum == 200


# ================================================================ 4. [ORTA, dis_gorsel] URL / yönlendirme host denetimi (SSRF)

IZINLI = ('img.snappark.net', 'snappark.net')


@pytest.mark.parametrize('url', [
    'http://127.0.0.2:18823\\@img.snappark.net/ic-backslash', 'https://127.0.0.2\\@img.snappark.net/x', 'https://evil.com\\@img.snappark.net/x',
    'https://img.snappark.net@127.0.0.2/ic', 'https://x@img.snappark.net/s/a/raw/', 'https://img.snappark.net:x@evil.com/',
    'https://[::1]/ic', 'https://[::ffff:127.0.0.1]/x', 'http://169.254.169.254/latest/meta-data/', 'http://10.0.0.1/x',
    'https://img.snappark.net.evil.com/s/x/raw/', 'https://cdn.img.snappark.net.evil.com/', 'https://evilsnappark.net/',
    'https://img.snappark.net:99999/x', 'https://img.snappark.net:8443/x', 'https://img.snappark.net:80/x',
    'http://img.snappark.net/s/a/raw/', 'ftp://img.snappark.net/x', '//img.snappark.net/x', 'img.snappark.net/x',
    'https://img.snappark.net /x', 'https://img.snappark.net/x y', 'https://img.snappark.net/\tx', 'https://img.snappark.net/x\r\nX: y',
    'https://img.snappark.net\x00.evil/', 'https://img%2esnappark.net/x', 'https://img.snappark.net%2f@evil.com/', 'https://İmg.snappark.net/x',
    'https://img.snappark.net。evil.com/', 'https://sub.snappark.net/x', '', None, 12,
])
def test_guvenli_url_reddeder(url):
    assert gorsel._guvenli_url(url, IZINLI) is False


@pytest.mark.parametrize('url', ['https://img.snappark.net/s/%s/raw/' % SP_ID, 'https://IMG.snappark.net/s/a/raw/', 'https://snappark.net/s/a',
                                 'https://img.snappark.net:443/s/a/raw/', 'https://img.snappark.net/s/a/raw/?x=1%20'])
def test_guvenli_url_mesrulari_kabul(url):
    assert gorsel._guvenli_url(url, IZINLI) is True


def test_guvenli_url_test_hostu_yalniz_tam_host_port():
    assert gorsel._guvenli_url('http://127.0.0.1:18701/img.snappark.net/s/a/raw/', IZINLI, test_host='127.0.0.1:18701')
    for u in ('http://127.0.0.1:18702/x', 'http://127.0.0.1/x', 'http://localhost:18701/x', 'http://127.0.0.1:18701\\@img.snappark.net/'):
        assert not gorsel._guvenli_url(u, IZINLI, test_host='127.0.0.1:18701'), u


IC_YUKLER = ['http://{ic}\\@img.snappark.net/ic-backslash', 'http://img.snappark.net@{ic}/ic', 'http://[::1]:{p}/ic',
             'http://169.254.169.254/latest/meta-data/', 'http://10.0.0.1/x', 'https://img.snappark.net.evil.com/s/x/raw/',
             'http://127.0.0.1:{p}/ic-baska-port', 'http://img.snappark.net:99999/x', 'http://{ic}\\@i.gyazo.com/rd',
             'http://{ic}/%2e%2e/ic', ' http://{ic}/ic', 'http://{ic}\t/ic']


@pytest.mark.parametrize('yuk', IC_YUKLER)
def test_yonlendirme_ic_adrese_gitmez_dis_yolu(tmp_path, yuk):
    """İnceleyicinin yükleri: izinli hosttan dönen kötü Location ile iç servise (127.0.0.2) istek atılmamalı, önbelleğe yazılmamalı."""
    dis = _yavas_sunucu(); ic = _yavas_sunucu('127.0.0.2')
    try:
        ic.yollar['/ic'] = ic.yollar['/ic-backslash'] = (200, {'Content-Type': 'image/png'}, png(), 0)
        hedef = yuk.format(ic='127.0.0.2:%d' % ic.port, p=ic.port)
        dis.yollar['/img.snappark.net/s/Rd1/raw/'] = (302, {'Location': hedef}, b'', 0)
        a = ayar_yap(tmp_path)
        c = gorsel.GorselCozucu(a, a['ONBELLEK']); c.dis_test_host = '127.0.0.1:%d' % dis.port
        o = requests.Session(); o.trust_env = False; c._http = o
        assert c.dis_indir({'link': 'https://snappark.net/s/Rd1'}) is None
        assert ic.hits == [] and dis.hits == ['/img.snappark.net/s/Rd1/raw/'] and not list(Path(c.dis_klasor).glob('*.png'))
    finally:
        dis.close(); ic.close()


def test_yonlendirme_ic_adrese_gitmez_gyazo_yolu(tmp_path):
    dis = _yavas_sunucu(); ic = _yavas_sunucu('127.0.0.2')
    try:
        ic.yollar['/rd'] = (200, {'Content-Type': 'image/png'}, png(), 0)
        gid = 'a' * 32
        dis.yollar['/%s.jpg' % gid] = (302, {'Location': 'http://127.0.0.2:%d\\@i.gyazo.com/rd' % ic.port}, b'', 0)
        a = ayar_yap(tmp_path)
        c = gorsel.GorselCozucu(a, a['ONBELLEK']); c.dis_test_host = '127.0.0.1:%d' % dis.port
        c.gyazo_kaynak = 'http://127.0.0.1:%d/{id}.jpg' % dis.port
        o = requests.Session(); o.trust_env = False; c._http = o
        assert c.gyazo_indir({'link': 'https://gyazo.com/' + gid}) is None
        assert ic.hits == [] and dis.hits == ['/%s.jpg' % gid]
    finally:
        dis.close(); ic.close()


def test_mesru_snappark_ve_gyazo_yonlendirmeleri_calisir(tmp_path):
    a = ayar_yap(tmp_path)
    c = gorsel.GorselCozucu(a, a['ONBELLEK'])
    g = png()
    tam = lambda: SahteYanit(200, g, {'Content-Type': 'image/png', 'Content-Length': str(len(g))})
    c._http = URLOturum({SP_RAW: [SahteYanit(302, b'', {'Location': 'https://img.snappark.net/s/%s/raw/dosya.png' % SP_ID})],
                         'https://img.snappark.net/s/%s/raw/dosya.png' % SP_ID: [tam()]})
    assert c.dis_indir({'link': SP_RAW})
    gid = 'b' * 32
    c._http = URLOturum({'https://i.gyazo.com/%s.jpg' % gid: [SahteYanit(301, b'', {'Location': '/%s.png' % gid})],
                         'https://i.gyazo.com/%s.png' % gid: [tam()]})
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + gid})
    # 5 yönlendirme izlenir (6. istek son yanıt)
    c._http = URLOturum({'https://img.snappark.net/s/Zin%d/raw/' % i: [SahteYanit(302, b'', {'Location': '/s/Zin%d/raw/' % (i + 1)})] for i in range(5)})
    c._http.plan['https://img.snappark.net/s/Zin5/raw/'] = [tam()]
    assert c.dis_indir({'link': 'https://snappark.net/s/Zin0'})


def test_cozulen_ip_ozel_ise_baglanilmaz(tmp_path, monkeypatch):
    a = ayar_yap(tmp_path)
    c = gorsel.GorselCozucu(a, a['ONBELLEK'])
    c._gyazo_http().trust_env = False
    baglanti = []
    monkeypatch.setattr(socket, 'create_connection', lambda *x, **k: baglanti.append(x) or (_ for _ in ()).throw(OSError('bağlanılmamalıydı')))
    for ip in ('10.1.2.3', '127.0.0.1', '169.254.169.254', '192.168.1.1', '172.16.0.1', '::1', 'fc00::1', '100.64.0.1', '0.0.0.0'):
        aile = socket.AF_INET6 if ':' in ip else socket.AF_INET
        monkeypatch.setattr(gorsel.socket, 'getaddrinfo', lambda *x, ip=ip, aile=aile, **k: [(aile, socket.SOCK_STREAM, 6, '', (ip, 443))])
        anahtar_ = sha1(SP_RAW)
        try:
            os.unlink(os.path.join(c.dis_klasor, anahtar_ + '.yok'))
        except OSError:
            pass
        assert c.dis_indir({'link': SP_RAW}) is None and c._dis_son_durum == 'ic_adres', ip
    assert baglanti == []
    # DNS çözülemezse bağlantı düzeyi hata ('erisim')
    def coz_yok(*x, **k):
        raise socket.gaierror(-2, 'Name or service not known')
    monkeypatch.setattr(gorsel.socket, 'getaddrinfo', coz_yok)
    os.unlink(os.path.join(c.dis_klasor, sha1(SP_RAW) + '.yok'))
    assert c.dis_indir({'link': SP_RAW}) is None and c._dis_son_durum == 'erisim'


def test_test_hostu_guvenli_oturumda_yalniz_o_port(tmp_path):
    s = _yavas_sunucu()
    try:
        s.yollar['/img.snappark.net/s/%s/raw/' % SP_ID] = (200, {'Content-Type': 'image/png'}, png(), 0)
        a = ayar_yap(tmp_path, DIS_GORSEL_TEST_HOST='127.0.0.1:%d' % s.port)
        c = gorsel.GorselCozucu(a, a['ONBELLEK'])
        c._gyazo_http().trust_env = False
        assert c.dis_indir({'link': SP_RAW})  # meşru test hostu: loopback olduğu hâlde izinli
        assert not c._dis_izinli('snappark')('http://127.0.0.1:%d/x' % (s.port + 1))
    finally:
        s.close()


# ================================================================ 5. [ORTA, dis_gorsel] /kucuk dış indirmede bloklamaz

def test_kucuk_dis_indirmede_bloklamaz_yer_tutucu_doner(web):
    cl, a = web; login(cl)
    from app import panel
    s = _yavas_sunucu()
    try:
        c = panel.COZUCU
        c.dis_test_host = '127.0.0.1:%d' % s.port
        o = requests.Session(); o.trust_env = False; c._http = o
        kayitlar = []
        for i in range(8):
            sid = 'Yavas%d' % i
            s.yollar['/img.snappark.net/s/%s/raw/' % sid] = (200, {'Content-Type': 'image/png'}, png(), 2)
            kayitlar.append(ekle(a, kt=1, link='https://snappark.net/s/' + sid, link_turu='snappark'))
        sureler, durumlar = {}, {}

        def iste(kid):
            t0 = time.monotonic(); r = cl.get('/kucuk/%d' % kid)
            sureler[kid] = time.monotonic() - t0; durumlar[kid] = (r.status_code, r.headers.get('X-Gorsel-Durum'), r.headers.get('Cache-Control'))
        ip = [threading.Thread(target=iste, args=(k,)) for k in kayitlar]
        for t in ip:
            t.start()
        for t in ip:
            t.join(10)
        assert max(sureler.values()) < 1.0, sureler
        assert all(d[:2] == (200, 'hazirlaniyor') and 'no-store' in d[2] for d in durumlar.values()), durumlar
        assert cl.get('/saglik').status_code == 200
        # arka planda en çok 2 eşzamanlı indirme
        assert _bekle(lambda: len(s.hits) >= 2, 5)
        time.sleep(0.3)
        assert len(s.hits) <= 2
        # tekil /gorsel beklemeli indirir
        r = cl.get('/gorsel/%d' % kayitlar[-1])
        assert r.status_code == 200 and r.data[:4] == b'\x89PNG'
        # sonraki açılışlarda arka plan indirmesi biter; /kucuk önbellekten gerçek küçük resim verir
        def hazir():
            r = cl.get('/kucuk/%d' % kayitlar[0])
            return r.status_code == 200 and r.data[:2] == b'\xff\xd8'
        assert _bekle(hazir, 15)
    finally:
        s.close()


def test_gorsel_semafor_beklemesi_10_sn_ile_sinirli(tmp_path):
    assert gorsel.GORSEL_ISTEK_BEKLEME_SN == 10 and gorsel.DIS_TOPLAM_SURE_SN <= 30


# ================================================================ düşük / bilgi bulguları

def test_sql_sarmalayicidan_cikis_kapali(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    v = ','.join('(%d)' % i for i in range(40))
    r = sorgu(c, k, 'SELECT a.column1 FROM (VALUES %s) a, (VALUES %s) b) /*' % (v, v))
    assert r.status_code == 400
    r = sorgu(c, k, 'SELECT 1) UNION ALL SELECT * FROM (SELECT 2')
    assert r.status_code == 400


def test_sql_sema_varligi_hata_turunden_sizmaz(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    kodlar = {sql: sorgu(c, k, sql).status_code for sql in (
        'SELECT yok_sutun FROM panel_kullanicilari', 'SELECT yok_sutun FROM yok_tablo', 'SELECT kullanici_adi FROM panel_kullanicilari',
        'SELECT main.panel_kullanicilari.yok FROM main.panel_kullanicilari')}
    assert set(kodlar.values()) == {403}, kodlar
    r = sorgu(c, k, 'SELECT yok_sutun FROM kayitlar')
    assert r.status_code == 400 and r.json['neden'] == 'sutun'  # izinli görünümde yanlış sütun: yararlı hata korunur


def test_sql_buyuk_tamsayi_ve_vekil_karakter_400(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    for sql, p in (('SELECT ?', [2 ** 64]), ('SELECT ?', ['\ud800']), ('SELECT \'\ud800\'', []), ('SELECT ?', [float('nan')]),
                   ('SELECT ?', [float('inf')])):
        r = c.post('/api/v1/sorgu', data=__import__('json').dumps({'sql': sql, 'parametreler': p}), headers=dict(B(k), **{'Content-Type': 'application/json'}))
        assert r.status_code == 400 and r.json['ok'] is False, (sql, p, r.status_code)


def test_sql_sonsuz_deger_gecerli_json(web):
    c, a = web
    _, k = anahtar(a, '*', sql_izni=True)
    r = sorgu(c, k, 'SELECT 1e999, -1e999, 1.5')
    assert r.status_code == 200 and b'Infinity' not in r.data and r.json['satirlar'] == [[None, None, 1.5]]


def test_sql_tg_kullanicilar_kapsamla_suzulur(web):
    c, a = web
    ekle(a, kt=1, ekleyen_id='11'); ekle(a, proje='PA', kt=1, ekleyen_id='22'); ekle(a, kt=0, ekleyen_id='33')
    con = db.baglan(a['DB'])
    with db.transaction(con):
        for i in ('11', '22', '33', '44'):
            con.execute("INSERT OR REPLACE INTO tg_kullanicilar(id,username,first_name,onayli) VALUES(?,?,?,1)", (i, 'u' + i, 'U'))
    con.close()
    _, k = anahtar(a, ['OF'], sql_izni=True)  # yalnız onaylı OF
    assert sorgu(c, k, 'SELECT id FROM tg_kullanicilar ORDER BY id').json['satirlar'] == [['11']]
    _, k2 = anahtar(a, ['OF'], yalniz_onayli=False, sql_izni=True, ad='ofhepsi')
    assert sorgu(c, k2, 'SELECT id FROM tg_kullanicilar ORDER BY id').json['satirlar'] == [['11'], ['33']]
    _, k3 = anahtar(a, '*', yalniz_onayli=False, sql_izni=True, ad='tumu')
    assert [x[0] for x in sorgu(c, k3, 'SELECT id FROM tg_kullanicilar ORDER BY id').json['satirlar']] == ['11', '22', '33', '44']


def test_sql_count_yildiz_ana_tablo_kapali_ve_sqlite_bilgi_islevleri_kapali(web):
    c, a = web
    veri(a)
    _, k = anahtar(a, '*', yalniz_onayli=False, sql_izni=True)
    # İnceleyicinin önerisi (veritabani=None ve sütunsuz READ'e izin) DENENDİ ve REDDEDİLDİ: sarmalayıcı kalkınca
    # 'SELECT count(*) FROM ayarlar' aynı biçimde (db=None, sütun='') geliyor. Bu yüzden somutlaştırılmış CTE count(*) 403 kalır.
    assert sorgu(c, k, 'SELECT count(*) FROM ayarlar').status_code == 403
    assert sorgu(c, k, 'WITH x AS MATERIALIZED (SELECT id FROM kayitlar) SELECT count(*) FROM x').status_code == 403
    assert sorgu(c, k, 'WITH x AS MATERIALIZED (SELECT id FROM kayitlar) SELECT count(id) FROM x').json['satirlar'] == [[3]]
    for f in ('sqlite_version()', 'sqlite_source_id()', "sqlite_compileoption_get(0)", "sqlite_compileoption_used('THREADSAFE')"):
        assert sorgu(c, k, 'SELECT ' + f).status_code == 403, f


def test_api_413_kimliksiz_gunluk_sisirmez(web):
    c, a = web
    buyuk = b'x' * (70 * 1024)
    for _ in range(40):
        r = c.post('/api/v1/sorgu', data=buyuk, headers={'Content-Type': 'application/json'})
        assert r.status_code in (413, 429)
    con = db.baglan(a['DB'])
    n = con.execute('SELECT COUNT(*) FROM api_gunlugu').fetchone()[0]; con.close()
    assert n <= api.YETKISIZ_IP_SINIRI
    _, k = anahtar(a, '*', sql_izni=True)
    api.YETKISIZ_HIZ.sifirla()
    assert c.post('/api/v1/sorgu', data=buyuk, headers=dict(B(k), **{'Content-Type': 'application/json'})).status_code == 413


def test_api_gorsel_bozuk_dosya_json_hata(web):
    c, a = web
    yol = Path(a['GORSEL_KLASOR']) / 'bozuk.jpg'; yol.write_bytes(b'<html>degil</html>')
    kid = ekle(a, kt=1, gorsel_dosya=str(yol))
    _, k = anahtar(a, ['OF'], gorsel_izni=True)
    r = c.get('/api/v1/gorsel/%d' % kid, headers=B(k))
    assert r.status_code == 422 and r.is_json and 'bozuk' in r.json['hata']


def test_api_yalniz_onayli_anahtar_durum_uyarisi(web):
    c, a = web
    veri(a)
    _, k = anahtar(a, ['OF'])
    r = c.get('/api/v1/kayitlar?durum=bekleyen', headers=B(k))
    assert r.status_code == 200 and 'yalnız onaylı' in r.json['uyari'] and r.json['suzgec']['durum'] == 'onayli'
    assert 'uyari' not in c.get('/api/v1/kayitlar', headers=B(k)).json


def test_api_acik_taninmayan_deger_kapali(monkeypatch):
    for deger, acik in (('', True), ('1', True), ('evet', True), ('acik', True), ('on', True), ('0', False), ('kapat', False),
                        ('disabled', False), ('none', False)):
        monkeypatch.setenv('API_ACIK', deger)
        assert api.acik_mi() is acik, deger
    monkeypatch.delenv('API_ACIK')
    assert api.acik_mi() is True


def test_api_gunlugu_budamasi_saatlik_ve_deterministik(web, monkeypatch):
    from app import api_anahtarlari as aa
    c, a = web
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.executemany('INSERT INTO api_gunlugu(anahtar_id,zaman,uc,ip,durum,sure_ms,satir) VALUES(NULL,?,?,?,?,?,?)',
                        [('2020-01-01 00:00:00', 'GET /x', '1', 200, 1, 0)] * 50)
    monkeypatch.setattr(aa, '_SON_BUDAMA', -1e9)
    aa.gunluk_yaz(con, None, 'GET /y', '1', 200, 1, 0)
    assert con.execute("SELECT COUNT(*) FROM api_gunlugu WHERE zaman<'2021'").fetchone()[0] == 0
    con.close()


def test_toplu_gyazo_kapaliyken_dis_kopyalama_calisir(tmp_path):
    a = ayar_yap(tmp_path, GYAZO_PROXY='0', DIS_GORSEL_PROXY='1')
    conn = db.baglan(a['DB'])
    conn.execute('INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)', ('g', 'OF', '1', 'https://i.gyazo.com/%s.jpg' % ('c' * 32)))
    conn.execute('INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)', ('s', 'OF', '2', SP_RAW))
    conn.commit()
    c = gorsel.GorselCozucu(a, a['ONBELLEK'])
    g = png()
    c._http = URLOturum({SP_RAW: [SahteYanit(200, g, {'Content-Type': 'image/png', 'Content-Length': str(len(g))})]})
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0, on_kontrol=True)
    assert r['indirilen'] == 1 and r['turler']['gyazo']['taninmayan'] == 1 and r['turler']['gyazo']['baglanti'] == 0
    a2 = ayar_yap(tmp_path, GYAZO_PROXY='0', DIS_GORSEL_PROXY='0')
    with pytest.raises(ValueError):
        gorsel.gyazo_toplu_indir(conn, gorsel.GorselCozucu(a2, a2['ONBELLEK']), a2)


def test_toplu_dis_429_yalniz_o_servisi_durdurur(tmp_path):
    a = ayar_yap(tmp_path)
    conn = db.baglan(a['DB'])
    gid = 'd' * 32
    for i, link in enumerate(['https://snappark.net/s/Hiz1', 'https://snappark.net/s/Hiz2', 'https://i.gyazo.com/%s.jpg' % gid]):
        conn.execute('INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)', ('h%d' % i, 'OF', str(i), link))
    conn.commit()
    c = gorsel.GorselCozucu(a, a['ONBELLEK'])
    from test_gyazo_toplu import jpeg
    c._http = URLOturum({'https://img.snappark.net/s/Hiz1/raw/': [SahteYanit(429)] * 5,
                         'https://i.gyazo.com/%s.jpg' % gid: [SahteYanit(200, jpeg())]})
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda x: None, bekleme_sn=0)
    assert r['turler']['gyazo']['indirilen'] == 1 and r['bitis_nedeni'] == 'tamam'
    assert r['turler']['snappark']['acilamayan'] == 2 and 'https://img.snappark.net/s/Hiz2/raw/' not in c._http.istekler
    assert r['dis_hiz_siniri'] == ['Snappark']
