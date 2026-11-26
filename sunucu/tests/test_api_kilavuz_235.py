# -*- coding: utf-8 -*-
"""2.3.5 — API anahtarları sayfasındaki "Kullanım kılavuzu": beş örnek bloğu gerçek panel adresiyle, örneklerdeki uçlar gerçekten
var (anahtarla çağrılır, 404 değil), örnek yanıtlar aynı veriyle yapılan gerçek çağrıyla birebir aynı, hata tablosundaki kodlar
gerçekten üretiliyor; curl ve Python örnekleri yerel bir waitress sunucusuna karşı çalıştırılır (curl yoksa o kısım atlanır)."""
import json
import re
import shutil
import subprocess
import sys
import threading
from html import unescape

import pytest

from app import api, api_anahtarlari as aa, api_kilavuz, db, kullanicilar, panel
from tests.test_web import web, login  # noqa: F401

BLOKLAR = ('curl', 'powershell', 'python', 'excel', 'sheets')


@pytest.fixture(autouse=True)
def _testadmin_sahip(request):
    """2.4.0: API anahtarları sayfası yalnız sahibe açık; bu dosyadaki testlerde testadmin sahip olur."""
    if 'web' in request.fixturenames:
        kullanicilar.guncelle(request.getfixturevalue('web')[1], 'testadmin', yetki='sahip')


def ornek_veri(a):
    """api_kilavuz.ORNEK_* ile aynı iki kayıt."""
    c = db.baglan(a['DB'])
    with db.transaction(c):
        c.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,uye_id,tip,tarih,kt,kt_kim,kt_zaman,ekleyen_id,ekleyen_ad,link,link_turu,kaynak) "
                  "VALUES('ok:1','OF','CVPS','P123','445566','Sessiz','2026-11-20 14:05:00',1,'admin','2026-11-20 15:10:00','5551234','ahmet',"
                  "'https://gyazo.com/abc123','gyazo','telegram')")
        c.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,uye_id,tip,tarih,kt,ekleyen_id,ekleyen_ad,kaynak) "
                  "VALUES('ok:2','OF','DDS','P124','445567','Telesekreter','2026-11-21 10:00:00',0,'5559876','zeynep','telegram')")
    c.close()


def anahtar(a, **kw):
    c = db.baglan(a['DB'])
    try:
        return aa.olustur(c, kw.pop('ad', 'Kılavuz'), kw.pop('projeler', '*'), olusturan='testadmin', **kw)[1]
    finally:
        c.close()


def B(k):
    return {'Authorization': 'Bearer ' + k}


def sayfa(c):
    login(c)
    r = c.get('/yonetim/api-anahtarlari')
    assert r.status_code == 200
    return r.data.decode()


def bloklar(html):
    out = {}
    for kimlik, govde in re.findall(r'<div class="api-ornek" id="api-ornek-([a-z]+)" data-api-ornek="[a-z]+">(.*?)</div>\s*(?=<div class="api-ornek"|</details>)', html, re.S):
        kod = re.search(r'<pre class="api-kod"><code>(.*?)</code></pre>', govde, re.S).group(1)
        kopya = re.search(r'data-kopyala="(.*?)">Kopyala</button>', govde, re.S).group(1)
        out[kimlik] = dict(kod=unescape(kod), kopya=unescape(kopya), govde=govde)
    return out


def test_kilavuz_karti_bes_ornek_gercek_adresle(web):
    c, a = web
    html = sayfa(c)
    assert 'id="kullanim-kilavuzu"' in html and '>Kullanım kılavuzu</h2>' in html and 'href="#kullanim-kilavuzu"' in html
    b = bloklar(html)
    assert tuple(b) == BLOKLAR
    for kimlik, x in b.items():
        assert x['kod'] == x['kopya'], kimlik  # Kopyala düğmesi gösterilen metnin aynısını kopyalar
        assert 'kp_ANAHTARINIZ' in x['kod'] and 'http://localhost' in x['kod'], kimlik
        assert 'api/v1/' in x['kod'], kimlik
    assert 'curl.exe' in b['curl']['govde'] and 'Invoke-RestMethod' in b['powershell']['kod'] and '-Headers $basliklar' in b['powershell']['kod']
    assert 'import requests' in b['python']['kod'] and 'Web.Contents' in b['excel']['kod'] and "Veri → Veri Al" in unescape(b['excel']['govde'])
    assert 'UrlFetchApp.fetch' in b['sheets']['kod'] and 'IMPORTDATA' in b['sheets']['govde']
    # Uç tablosu personel-ozet dahil; hata tablosu ve istek sınırı
    uclar = re.findall(r'data-api-uc="([A-Z]+) ([^"]+)"', html)
    assert ('GET', '/api/v1/personel-ozet') in uclar and ('POST', '/api/v1/sorgu') in uclar and len(uclar) == 6
    assert re.findall(r'data-api-hata="(\d+)"', html) == ['400', '401', '403', '404', '429']
    assert '<b data-api-dakika>%d</b>' % api.dakika_siniri() in html
    assert 'Anahtar paroladır' in html and 'İptal et' in html and 'API_KULLANIM.md' in html
    # Ters vekil/alan adı: örnekler isteğin geldiği dış adresi kullanır
    dis = 'https://panel.ornek.com'
    c2 = panel.app.test_client()
    c2.get('/giris', base_url=dis)
    with c2.session_transaction(base_url=dis) as s:
        belirtec = s['csrf']
    c2.post('/giris', base_url=dis, data={'csrf': belirtec, 'kullanici': 'testadmin', 'sifre': 'Test-Password-123!'})
    html2 = c2.get('/yonetim/api-anahtarlari', base_url=dis).data.decode()
    assert 'https://panel.ornek.com/api/v1/ozet' in unescape(html2) and 'http://localhost' not in html2


def test_yetkisiz_kullanici_kilavuzu_goremez(web):
    c, a = web
    kullanicilar.ekle(a, 'lider', 'OF:oku,kt', 'Test-Password-123!'); kullanicilar.guncelle(a, 'lider', sifre_degistir=0)
    login(c, 'lider')
    r = c.get('/yonetim/api-anahtarlari')
    assert r.status_code == 403 and b'kullanim-kilavuzu' not in r.data


def test_orneklerdeki_uclar_var_ve_calisir(web):
    c, a = web
    ornek_veri(a)
    html = sayfa(c)
    k = anahtar(a, yalniz_onayli=False, sql_izni=True, gorsel_izni=True)
    adresler = set()
    for x in bloklar(html).values():
        for url in re.findall(r'http://localhost(/api/v1/[^\s"\']*)', x['kod']):
            adresler.add(url)
    # Excel / Sheets örneklerindeki RelativePath ve Query parçaları
    assert 'RelativePath = "api/v1/kayitlar"' in bloklar(html)['excel']['kod']
    adresler.add('/api/v1/kayitlar?durum=onayli&adet=500&sayfa=1')
    assert {'/api/v1/ozet', '/api/v1/personel-ozet?donem=ay&grup=personel&sutun=kategori'} <= adresler
    assert any(u.startswith('/api/v1/kayitlar?durum=onayli&tarih1=') for u in adresler)
    for url in sorted(adresler):
        r = c.get(url, headers=B(k))
        assert r.status_code == 200 and r.get_json()['ok'] is True, (url, r.status_code, r.data[:200])
    # Uç tablosundaki her uç gerçek (404/405 değil)
    for yontem, yol in re.findall(r'data-api-uc="([A-Z]+) ([^"]+)"', html):
        yol = unescape(yol).replace('<id>', '1')
        if yontem == 'GET':
            r = c.get(yol, headers=B(k))
            assert r.status_code not in (404, 405) or yol.startswith('/api/v1/gorsel/'), (yol, r.status_code)
            if yol.startswith('/api/v1/gorsel/'):
                assert r.get_json()['hata'].startswith('Bu kaydın görseli yok')  # uç var; kaydın görseli yok
        else:
            r = c.post(yol, headers=B(k), json={'sql': 'SELECT count(*) AS n FROM kayitlar'})
            assert r.status_code == 200 and r.get_json()['satirlar'] == [[2]]
    assert c.get('/api/v1/yok-boyle-uc', headers=B(k)).status_code == 404  # kontrol: gerçekten olmayan uç 404


def test_ornek_yanitlar_gercek_cagriyla_ayni(web):
    c, a = web
    ornek_veri(a)
    k = anahtar(a, yalniz_onayli=False)
    assert c.get('/api/v1/ozet', headers=B(k)).get_json() == api_kilavuz.ORNEK_OZET
    assert c.get(api_kilavuz.ORNEK_KAYITLAR_YOLU, headers=B(k)).get_json() == api_kilavuz.ORNEK_KAYITLAR
    html = sayfa(c)
    for ad, beklenen in (('ozet', api_kilavuz.ORNEK_OZET), ('kayitlar', api_kilavuz.ORNEK_KAYITLAR)):
        metin = re.search(r'<pre class="api-kod" data-api-yanit="%s"><code>(.*?)</code></pre>' % ad, html, re.S).group(1)
        assert json.loads(unescape(metin)) == beklenen
    kayit = api_kilavuz.ORNEK_KAYIT
    assert {'onayli', 'onaylayan', 'onay_zamani'} <= set(kayit) and kayit['onayli'] is True


def test_hata_tablosundaki_kodlar_gercek(web, monkeypatch):
    c, a = web
    ornek_veri(a)
    k = anahtar(a, projeler=['OF'])
    assert c.get('/api/v1/kayitlar?tarih1=01.11.2026', headers=B(k)).status_code == 400
    assert c.get('/api/v1/personel-ozet?donem=x', headers=B(k)).status_code == 400
    assert c.get('/api/v1/kayitlar?durum=x', headers=B(anahtar(a, ad='Hepsi', yalniz_onayli=False))).status_code == 400
    assert c.get('/api/v1/kayitlar?adet=9999', headers=B(k)).status_code == 400
    r = c.get('/api/v1/ozet', headers=B('kp_' + 'x' * 40))
    hata = json.loads(api_kilavuz.kilavuz('http://x/', 1)['ornek_hata'])
    assert r.status_code == 401 and r.get_json() == hata
    assert c.get('/api/v1/ozet').status_code == 401
    assert c.get('/api/v1/kayitlar?proje=PA', headers=B(k)).status_code == 403
    assert c.get('/api/v1/gorsel/1', headers=B(k)).status_code == 403
    assert c.get('/api/v1/kayit/999999', headers=B(k)).status_code == 404
    monkeypatch.setenv('API_DAKIKA_SINIRI', '2')
    k2 = anahtar(a, ad='Sınır')
    kodlar = [c.get('/api/v1/ozet', headers=B(k2)).status_code for _ in range(3)]
    assert kodlar == [200, 200, 429]
    r = c.get('/api/v1/ozet', headers=B(k2))
    assert r.status_code == 429 and int(r.headers['Retry-After']) >= 1
    login(c)
    assert '<b data-api-dakika>2</b>' in c.get('/yonetim/api-anahtarlari').data.decode()


def test_not_metninde_adres_kacislanir():
    o = api_kilavuz.ornekler('http://x/"><script>alert(1)</script>')
    excel = next(x for x in o if x['kimlik'] == 'excel')
    assert '<script>' not in ' '.join(excel['notlar']) and '&lt;script&gt;' in ' '.join(excel['notlar'])


@pytest.fixture
def canli(web):
    """panel.app'i gerçek bir waitress sunucusunda (rastgele port) çalıştırır."""
    from waitress.server import create_server
    c, a = web
    srv = create_server(panel.app, host='127.0.0.1', port=0, threads=4)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    try:
        yield c, a, 'http://127.0.0.1:%d/' % int(srv.effective_port)
    finally:
        srv.close()


def test_curl_ve_python_ornekleri_canli_sunucuda_calisir(canli):
    c, a, taban = canli
    ornek_veri(a)
    k = anahtar(a, yalniz_onayli=False)
    o = {x['kimlik']: x['metin'].replace(api_kilavuz.ANAHTAR_YER_TUTUCU, k) for x in api_kilavuz.ornekler(taban)}
    r = subprocess.run([sys.executable, '-c', o['python']], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert 'Toplam: 2' in r.stdout and '1 kayıt' in r.stdout  # durum=onayli → 1 kayıt
    if not shutil.which('curl'):
        pytest.skip('curl yok')
    r = subprocess.run(['bash', '-c', o['curl']], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    yanitlar = [json.loads(s) for s in r.stdout.splitlines() if s.strip()]
    assert len(yanitlar) == 3 and all(y['ok'] for y in yanitlar)
    assert yanitlar[0] == api_kilavuz.ORNEK_OZET
    if shutil.which('pwsh'):
        r = subprocess.run(['pwsh', '-NoProfile', '-Command', o['powershell'].replace('Export-Csv -Path kayitlar.csv', 'Out-Null #')],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == 0 and '2' in r.stdout, r.stderr


def test_excel_ve_sheets_ornekleri_butun_sayfalari_ceker(web, tmp_path):
    """500'den çok kayıtta Excel ve Sheets örnekleri yalnız ilk sayfayla kalmamalı: Sheets kodu node'da sahte UrlFetchApp ile
    (yanıtlar gerçek /api/v1/kayitlar çağrılarından) çalıştırılır ve bütün kayıtları yazmalı."""
    c, a = web
    cx = db.baglan(a['DB'])
    with db.transaction(cx):
        for i in range(620):
            cx.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,tarih,kt,kaynak) VALUES(?,?,?,?,?,1,'telegram')",
                       ('s:%d' % i, 'OF', 'CVPS', 'P%d' % i, '2026-11-%02d 10:00:00' % (1 + i % 28)))
    cx.close()
    k = anahtar(a)
    o = {x['kimlik']: x for x in api_kilavuz.ornekler('http://localhost/')}
    assert 'List.Generate' in o['excel']['metin'] and 'Ilk[sayfa_sayisi]' in o['excel']['metin']
    assert 'sayfa_sayisi' in ' '.join(o['excel']['notlar']) and 'sayfa_sayisi' in ' '.join(o['sheets']['notlar'])
    yanitlar = {}
    for n in (1, 2, 3):
        url = '/api/v1/kayitlar?durum=onayli&adet=500&sayfa=%d' % n
        r = c.get(url, headers=B(k))
        assert r.status_code == 200
        yanitlar['http://localhost' + url] = r.get_data(as_text=True)
    assert json.loads(yanitlar['http://localhost/api/v1/kayitlar?durum=onayli&adet=500&sayfa=1'])['sayfa_sayisi'] == 2
    if not shutil.which('node'):
        pytest.skip('node yok')
    js = ('var Y = %s, istenen = [], yazilan = null;\n'
          'var UrlFetchApp = {fetch: function (u, s) { istenen.push(u); if (s.headers.Authorization !== "Bearer %s") throw new Error("başlık");\n'
          '  return {getResponseCode: function () { return 200; }, getContentText: function () { return Y[u]; }}; }};\n'
          'var SpreadsheetApp = {getActiveSpreadsheet: function () { return {getSheetByName: function () { return {\n'
          '  clearContents: function () {}, getRange: function () { return {setValues: function (v) { yazilan = v; }}; }}; }}; }};\n'
          '%s\nkanitKayitlariniGetir();\nconsole.log(JSON.stringify({istenen: istenen, satir: yazilan.length}));\n'
          % (json.dumps(yanitlar), api_kilavuz.ANAHTAR_YER_TUTUCU, o['sheets']['metin']))
    betik = tmp_path / 'sheets_ornegi.js'
    betik.write_text(js, encoding='utf-8')
    r = subprocess.run(['node', str(betik)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    sonuc = json.loads(r.stdout)
    assert sonuc['satir'] == 621 and len(sonuc['istenen']) == 2  # başlık + 620 kayıt, iki istek
