"""2.3.2 — API anahtarları ve salt okunur /api/v1 uçları."""
import json
import re
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app import api, api_anahtarlari as aa, db
from test_web import web, login, csrf  # noqa: F401

SAHTE_GECERSIZ = 'kp_' + 'A' * 40


@pytest.fixture(autouse=True)
def _temiz_sinir(monkeypatch):
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    monkeypatch.delenv('API_ACIK', raising=False); monkeypatch.delenv('API_DAKIKA_SINIRI', raising=False)
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


def ekle(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'api:' + str(time.time_ns())); cols.setdefault('kaynak', 'telegram')
    cols.setdefault('personel', 'ali'); cols.setdefault('tarih', db.simdi()); cols.setdefault('kategori', 'CVPS'); cols.setdefault('tip', 'sessiz')
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close()
    return kid


def anahtar(a, projeler='*', **kw):
    c = db.baglan(a['DB'])
    try:
        return aa.olustur(c, kw.pop('ad', 'Test sistemi'), projeler, olusturan='testadmin', **kw)
    finally:
        c.close()


def B(k):
    return {'Authorization': 'Bearer ' + k}


def sorgu(c, k, sql, parametreler=None):
    return c.post('/api/v1/sorgu', json={'sql': sql, 'parametreler': parametreler or []}, headers=B(k))


def veri(a):
    """OF: onaylı + bekleyen + silinmiş; PA: onaylı. Yorum OF onaylıda ve PA'da."""
    ids = dict(of_onay=ekle(a, kt=1, kt_kim='testadmin', personel='ayse', tarih='2026-11-03 10:00:00'),
               of_bek=ekle(a, kt=0, personel='ayse', tarih='2026-11-04 10:00:00', kategori='DDS'),
               of_sil=ekle(a, kt=1, silindi=1, personel='gizli', tarih='2026-11-05 10:00:00'),
               pa_onay=ekle(a, proje='PA', kt=1, personel='veli', tarih='2026-10-01 10:00:00'))
    c = db.baglan(a['DB'])
    with db.transaction(c):
        c.execute("INSERT INTO yorumlar(kayit_id,kullanici,metin,zaman) VALUES(?,?,?,?)", (ids['of_onay'], 'testadmin', 'OF yorumu', db.simdi()))
        c.execute("INSERT INTO yorumlar(kayit_id,kullanici,metin,zaman) VALUES(?,?,?,?)", (ids['pa_onay'], 'testadmin', 'PA yorumu', db.simdi()))
        c.execute("INSERT OR REPLACE INTO tg_kullanicilar(id,username,first_name,onayli) VALUES('77','tguser','Tg',1)")
    c.close()
    return ids


def satirlar(a, sql, *p):
    c = db.baglan(a['DB'])
    try:
        return [dict(r) for r in c.execute(sql, p)]
    finally:
        c.close()


# ---------------------------------------------------------------- anahtar yaşam döngüsü

def test_anahtar_uretme_bicim_ozet_ve_denetim(web):
    c, a = web
    kid, k = anahtar(a, ['OF'])
    assert re.fullmatch(r'kp_[A-Za-z0-9]{40}', k)
    row = satirlar(a, 'SELECT * FROM api_anahtarlari WHERE id=?', kid)[0]
    assert row['ozet'] == aa.ozet(k) and row['onek'] == k[3:11] and k not in json.dumps(row)
    assert row['yalniz_onayli'] == 1 and row['sql_izni'] == 0 and row['gorsel_izni'] == 0 and row['projeler'] == '["OF"]'
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='api_anahtar_olustur'")
    assert len(d) == 1 and k not in json.dumps(d) and d[0]['hedef_id'] == str(kid)
    assert c.get('/api/v1/ozet', headers=B(k)).status_code == 200
    con = db.baglan(a['DB']); assert aa.iptal(con, kid, 'testadmin') is True and aa.iptal(con, kid, 'testadmin') is False; con.close()
    r = c.get('/api/v1/ozet', headers=B(k))
    assert r.status_code == 401 and 'iptal' in r.json['hata']
    assert len(satirlar(a, "SELECT * FROM denetim WHERE islem='api_anahtar_iptal'")) == 1


def test_son_kullanma_tarihi(web):
    c, a = web
    con = db.baglan(a['DB'])
    with pytest.raises(ValueError):
        aa.olustur(con, 'x', '*', olusturan='t', son_kullanma=(date.today() - timedelta(days=1)).isoformat())
    with pytest.raises(ValueError):
        aa.olustur(con, '', '*', olusturan='t')
    with pytest.raises(ValueError):
        aa.olustur(con, 'x', [], olusturan='t')
    con.close()
    kid, k = anahtar(a, son_kullanma=date.today().isoformat())
    assert c.get('/api/v1/ozet', headers=B(k)).status_code == 200  # bugün son gün: geçerli
    con = db.baglan(a['DB']); con.execute('UPDATE api_anahtarlari SET son_kullanma=? WHERE id=?', ((date.today() - timedelta(days=1)).isoformat(), kid)); con.close()
    r = c.get('/api/v1/ozet', headers=B(k))
    assert r.status_code == 401 and 'süresi' in r.json['hata']


def test_kimlik_yok_gecersiz_ve_oturum_cerezi_reddi(web):
    c, a = web
    login(c)  # süperadmin oturumu açık; çerez API'de kimlik sayılmaz
    for h in ({}, {'Authorization': 'Bearer yanlis'}, B(SAHTE_GECERSIZ), {'Authorization': 'Basic ' + SAHTE_GECERSIZ}):
        r = c.get('/api/v1/kayitlar', headers=h)
        assert r.status_code == 401 and r.is_json and r.json['ok'] is False and r.json['hata']
        assert 'no-store' in r.headers['Cache-Control'] and r.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'Set-Cookie' not in r.headers
    # CSRF uygulanmaz ama oturumla da POST geçmez
    assert c.post('/api/v1/sorgu', json={'sql': 'SELECT 1'}, headers={'X-CSRF': csrf(c)}).status_code == 401
    _, k = anahtar(a)
    r = c.get('/api/v1/kayitlar', headers=B(k))
    assert r.status_code == 200 and 'Set-Cookie' not in r.headers and 'no-store' in r.headers['Cache-Control']
    assert c.get('/api/v1/yok', headers=B(k)).json['ok'] is False and c.get('/api/v1/yok', headers=B(k)).status_code == 404
    assert c.delete('/api/v1/kayitlar', headers=B(k)).status_code == 405
    assert c.get('/api/v1/yok', headers={'Accept': 'text/html'}).is_json


def test_api_kapali_404(web, monkeypatch):
    c, a = web
    _, k = anahtar(a)
    monkeypatch.setenv('API_ACIK', '0')
    for url in ('/api/v1/ozet', '/api/v1/kayitlar', '/api/v1/kayit/1'):
        assert c.get(url, headers=B(k)).status_code == 404
    assert c.post('/api/v1/sorgu', json={'sql': 'SELECT 1'}, headers=B(k)).status_code == 404


# ---------------------------------------------------------------- kapsam ve uçlar

def test_kayitlar_kapsam_ve_yalniz_onayli(web):
    c, a = web
    ids = veri(a)
    _, k_of = anahtar(a, ['OF'])  # yalnız onaylı (varsayılan)
    r = c.get('/api/v1/kayitlar', headers=B(k_of)).json
    assert [x['id'] for x in r['kayitlar']] == [ids['of_onay']] and r['toplam'] == 1 and r['suzgec']['durum'] == 'onayli'
    x = r['kayitlar'][0]
    assert x['onayli'] is True and x['onaylayan'] == 'testadmin' and x['yorum_sayisi'] == 1 and 'gorsel_url' not in x
    assert not {'gorsel_dosya', 'file_id', 'chat_id', 'anahtar'} & set(x)
    assert c.get('/api/v1/kayitlar?durum=bekleyen', headers=B(k_of)).json['toplam'] == 1  # durum yok sayılır: onaylıya sabit
    assert c.get('/api/v1/kayitlar?proje=PA', headers=B(k_of)).status_code == 403
    _, k_hep = anahtar(a, '*', yalniz_onayli=False)
    r = c.get('/api/v1/kayitlar', headers=B(k_hep)).json
    assert {x['id'] for x in r['kayitlar']} == {ids['of_onay'], ids['of_bek'], ids['pa_onay']}  # silinmiş hiçbir zaman
    assert {x['id'] for x in c.get('/api/v1/kayitlar?durum=bekleyen', headers=B(k_hep)).json['kayitlar']} == {ids['of_bek']}
    assert c.get('/api/v1/kayitlar?durum=silinen', headers=B(k_hep)).status_code == 400
    assert {x['id'] for x in c.get('/api/v1/kayitlar?proje=PA', headers=B(k_hep)).json['kayitlar']} == {ids['pa_onay']}
    assert {x['id'] for x in c.get('/api/v1/kayitlar?q=veli', headers=B(k_hep)).json['kayitlar']} == {ids['pa_onay']}
    assert {x['id'] for x in c.get('/api/v1/kayitlar?kategori=dds', headers=B(k_hep)).json['kayitlar']} == {ids['of_bek']}
    assert {x['id'] for x in c.get('/api/v1/kayitlar?tarih1=2026-11-01&tarih2=2026-11-30', headers=B(k_hep)).json['kayitlar']} == {ids['of_onay'], ids['of_bek']}
    ters = c.get('/api/v1/kayitlar?tarih1=2026-11-30&tarih2=2026-11-01', headers=B(k_hep)).json
    assert ters['toplam'] == 2 and 'yer değiştirildi' in ters['uyari']
    assert c.get('/api/v1/kayitlar?tarih1=2026-13-01', headers=B(k_hep)).status_code == 400
    s = c.get('/api/v1/kayitlar?adet=1&sayfa=2', headers=B(k_hep)).json
    assert s['adet'] == 1 and s['sayfa'] == 2 and len(s['kayitlar']) == 1 and s['toplam'] == 3
    assert c.get('/api/v1/kayitlar?adet=501', headers=B(k_hep)).status_code == 400


def test_tek_kayit_ve_kapsam_disi_404(web):
    c, a = web
    ids = veri(a)
    _, k = anahtar(a, ['OF'])
    r = c.get('/api/v1/kayit/%d' % ids['of_onay'], headers=B(k))
    assert r.status_code == 200 and r.json['kayit']['yorumlar'][0]['metin'] == 'OF yorumu' and r.json['kayit']['yorumlar'][0]['tur'] == 'yorum'
    for kid in (ids['pa_onay'], ids['of_bek'], ids['of_sil'], 999999):
        r = c.get('/api/v1/kayit/%d' % kid, headers=B(k))
        assert r.status_code == 404 and r.json['hata'] == 'Kayıt bulunamadı ya da bu anahtarın kapsamında değil.'


def test_ozet(web):
    c, a = web
    ids = veri(a)
    _, k = anahtar(a, '*', yalniz_onayli=False)
    r = c.get('/api/v1/ozet', headers=B(k)).json
    assert (r['toplam'], r['onayli'], r['bekleyen']) == (3, 2, 1)
    assert {p['proje']: p['toplam'] for p in r['projeler']} == {'OF': 2, 'PA': 1}
    assert {(x['kategori'], x['tip']): x['toplam'] for x in r['kategori_tip']} == {('CVPS', 'sessiz'): 2, ('DDS', 'sessiz'): 1}
    assert r['ekleyenler'][0]['toplam'] == 3
    r = c.get('/api/v1/ozet?proje=OF&tarih1=2026-11-04&tarih2=2026-11-30', headers=B(k)).json
    assert (r['toplam'], r['onayli'], r['bekleyen']) == (1, 0, 1)
    _, k2 = anahtar(a, ['PA'])
    r = c.get('/api/v1/ozet', headers=B(k2)).json
    assert (r['toplam'], r['onayli'], r['bekleyen']) == (1, 1, 0) and [p['proje'] for p in r['projeler']] == ['PA']
    assert ids


def test_gorsel_izin_ve_bayt(web):
    c, a = web
    yol = Path(a['GORSEL_KLASOR']) / 'api.png'; Image.new('RGB', (8, 8), (0, 255, 0)).save(yol, 'PNG')
    kid = ekle(a, kt=1, gorsel_dosya=str(yol)); yok = ekle(a, kt=1); pa = ekle(a, proje='PA', kt=1, gorsel_dosya=str(yol))
    _, k_yok = anahtar(a, ['OF'])
    assert c.get('/api/v1/gorsel/%d' % kid, headers=B(k_yok)).status_code == 403
    _, k = anahtar(a, ['OF'], gorsel_izni=True)
    r = c.get('/api/v1/gorsel/%d' % kid, headers=B(k))
    assert r.status_code == 200 and r.data[:8] == b'\x89PNG\r\n\x1a\n' and 'Set-Cookie' not in r.headers
    assert c.get('/api/v1/gorsel/%d' % yok, headers=B(k)).status_code == 404
    assert c.get('/api/v1/gorsel/%d' % pa, headers=B(k)).status_code == 404
    liste = {x['id']: x for x in c.get('/api/v1/kayitlar', headers=B(k)).json['kayitlar']}
    assert liste[kid]['gorsel_url'] == '/api/v1/gorsel/%d' % kid and liste[yok]['gorsel_url'] is None


# ---------------------------------------------------------------- hız sınırı ve günlük

def test_hiz_siniri_429_ve_retry_after(web, monkeypatch):
    c, a = web
    monkeypatch.setenv('API_DAKIKA_SINIRI', '3')
    _, k = anahtar(a); _, k2 = anahtar(a, ad='ikinci')
    assert [c.get('/api/v1/ozet', headers=B(k)).status_code for _ in range(3)] == [200, 200, 200]
    r = c.get('/api/v1/ozet', headers=B(k))
    assert r.status_code == 429 and 1 <= int(r.headers['Retry-After']) <= 60 and r.json['hata']
    assert c.get('/api/v1/ozet', headers=B(k2)).status_code == 200  # anahtar başına
    s = aa.HizSiniri()
    assert s.dene('x', 1, simdi=0)[0] and not s.dene('x', 1, simdi=30)[0] and s.dene('x', 1, simdi=60.5)[0]


def test_gunluk_satirlari_ve_sayaclar(web):
    c, a = web
    veri(a)
    kid, k = anahtar(a, '*', yalniz_onayli=False, sql_izni=True)
    c.get('/api/v1/kayitlar', headers=B(k)); c.get('/api/v1/kayit/999999', headers=B(k)); sorgu(c, k, 'SELECT id FROM kayitlar')
    c.get('/api/v1/ozet', headers=B(SAHTE_GECERSIZ))
    g = satirlar(a, 'SELECT * FROM api_gunlugu ORDER BY id')
    assert [(x['anahtar_id'], x['uc'], x['durum']) for x in g] == [
        (kid, 'GET /api/v1/kayitlar', 200), (kid, 'GET /api/v1/kayit/999999', 404), (kid, 'POST /api/v1/sorgu', 200), (None, 'GET /api/v1/ozet', 401)]
    assert g[0]['satir'] == 3 and g[2]['satir'] == 3 and all(x['sure_ms'] is not None and x['ip'] for x in g)
    row = satirlar(a, 'SELECT * FROM api_anahtarlari WHERE id=?', kid)[0]
    assert row['istek_sayisi'] == 3 and row['son_kullanim'] and row['son_ip']


def test_yetkisiz_ip_siniri(web):
    c, a = web
    kodlar = [c.get('/api/v1/ozet', headers=B(SAHTE_GECERSIZ)).status_code for _ in range(api.YETKISIZ_IP_SINIRI + 2)]
    assert kodlar[:api.YETKISIZ_IP_SINIRI] == [401] * api.YETKISIZ_IP_SINIRI and kodlar[-1] == 429
    assert len(satirlar(a, 'SELECT * FROM api_gunlugu')) == api.YETKISIZ_IP_SINIRI  # aşan istekler günlüğü şişirmez


def test_govde_64kb_siniri(web):
    c, a = web
    _, k = anahtar(a, sql_izni=True)
    r = c.post('/api/v1/sorgu', data='{"sql":"SELECT 1","x":"' + 'a' * (70 * 1024) + '"}', content_type='application/json', headers=B(k))
    assert r.status_code == 413 and r.is_json


# ---------------------------------------------------------------- SQL ucu

def test_sql_izinli_select_ve_kapsam(web):
    c, a = web
    ids = veri(a)
    _, k = anahtar(a, ['OF'], sql_izni=True)  # yalnız onaylı
    r = sorgu(c, k, 'SELECT id, personel, kt FROM kayitlar ORDER BY id;')
    assert r.status_code == 200 and r.json['sutunlar'] == ['id', 'personel', 'kt'] and r.json['satirlar'] == [[ids['of_onay'], 'ayse', 1]]
    assert r.json['kesildi'] is False and r.json['satir_sayisi'] == 1
    assert sorgu(c, k, 'SELECT count(*) FROM kayitlar WHERE proje=?', ['PA']).json['satirlar'] == [[0]]
    assert sorgu(c, k, 'SELECT metin FROM yorumlar').json['satirlar'] == [['OF yorumu']]  # PA yorumu görünmez
    assert sorgu(c, k, "SELECT label FROM kategoriler WHERE code='cvpsz'").json['satirlar'] == [['CVPS']]
    assert sorgu(c, k, 'SELECT id, username FROM tg_kullanicilar').json['satirlar'] == [['77', 'tguser']]
    r = sorgu(c, k, 'WITH x AS (SELECT personel FROM kayitlar) SELECT personel, count(*) n FROM x GROUP BY personel')
    assert r.status_code == 200 and r.json['satirlar'] == [['ayse', 1]]
    _, k2 = anahtar(a, '*', yalniz_onayli=False, sql_izni=True)
    assert sorgu(c, k2, 'SELECT count(*) FROM kayitlar').json['satirlar'] == [[3]]  # silinmiş yok
    assert sorgu(c, k2, 'SELECT count(*) FROM kayitlar WHERE personel=?', ['gizli']).json['satirlar'] == [[0]]


YASAK_SORGULAR = [
    'SELECT * FROM main.kayitlar',
    'SELECT count(*) FROM main.kayitlar',
    'SELECT * FROM panel_kullanicilari',
    'SELECT sifre_hash FROM main.panel_kullanicilari',
    'SELECT * FROM ayarlar',
    'SELECT count(*) FROM ayarlar',
    'SELECT * FROM denetim',
    'SELECT * FROM tg_gelen',
    'SELECT * FROM api_anahtarlari',
    'SELECT name, sql FROM sqlite_master',
    'SELECT * FROM sqlite_temp_master',
    'SELECT * FROM temp.sqlite_master',
    "SELECT * FROM pragma_table_info('panel_kullanicilari')",
    'SELECT 1 WHERE EXISTS (SELECT 1 FROM panel_kullanicilari)',
    'SELECT (SELECT deger FROM ayarlar LIMIT 1)',
    'SELECT k.id FROM kayitlar k JOIN main.kayitlar m ON m.id = k.id',
    # Görünüm adını taklit eden CTE: authorizer'ın 5. argümanı 'kayitlar' olur; iç görünüm adı rastgele olduğu için reddedilir.
    'WITH kayitlar AS (SELECT * FROM main.kayitlar) SELECT * FROM kayitlar',
    'WITH kayitlar AS (SELECT sifre_hash FROM main.panel_kullanicilari) SELECT * FROM kayitlar',
    'WITH yorumlar AS (SELECT * FROM main.kayitlar WHERE silindi=1) SELECT * FROM yorumlar',
    'WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c) SELECT n FROM c',
    "SELECT * FROM json_each('[1,2]')",
    'SELECT zeroblob(10)',
    "SELECT load_extension('x')",
]

REDDEDILEN_IFADELER = [
    'SELECT gorsel_dosya FROM kayitlar',  # görünümde olmayan sütun: 400 'sutun'
    'PRAGMA table_info(kayitlar)',
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "DELETE FROM kayitlar",
    "UPDATE kayitlar SET kt=1",
    "INSERT INTO ayarlar VALUES('a','b')",
    "DROP TABLE kayitlar",
    "CREATE TABLE z(a)",
    "SELECT 1; DELETE FROM kayitlar",
    "SELECT 1; SELECT 2",
    "SELECT 1; -- yorum",
    "VACUUM",
    "SELECT 1) UNION SELECT sifre_hash FROM (SELECT * FROM panel_kullanicilari",
    "",
]


@pytest.mark.parametrize('sql', YASAK_SORGULAR)
def test_sql_yasak_okumalar_403(web, sql):
    c, a = web
    veri(a)
    _, k = anahtar(a, ['OF'], sql_izni=True)
    r = sorgu(c, k, sql)
    assert r.status_code == 403, (sql, r.json)
    assert r.json['ok'] is False and r.json['neden'] == 'yetki'
    assert not re.search(r'panel_kullanicilari|sifre_hash|_kp_|sqlite_master|not authorized|prohibited', r.json['hata'])


@pytest.mark.parametrize('sql', REDDEDILEN_IFADELER)
def test_sql_yazma_pragma_attach_coklu_400_403(web, sql):
    c, a = web
    veri(a)
    _, k = anahtar(a, '*', yalniz_onayli=False, sql_izni=True)
    once = satirlar(a, 'SELECT count(*) n, sum(kt) s FROM kayitlar')
    r = sorgu(c, k, sql)
    assert r.status_code in (400, 403), (sql, r.json)
    assert r.json['ok'] is False
    assert satirlar(a, 'SELECT count(*) n, sum(kt) s FROM kayitlar') == once
    assert satirlar(a, "SELECT count(*) n FROM ayarlar WHERE anahtar='a'")[0]['n'] == 0


def test_sql_izni_kapali_403(web):
    c, a = web
    _, k = anahtar(a)
    r = sorgu(c, k, 'SELECT 1')
    assert r.status_code == 403 and 'SQL' in r.json['hata']
    _, k2 = anahtar(a, sql_izni=True)
    assert c.post('/api/v1/sorgu', data='SELECT 1', headers=B(k2)).status_code == 400
    assert c.post('/api/v1/sorgu', json={'sql': 'SELECT ?', 'parametreler': [{'a': 1}]}, headers=B(k2)).status_code == 400
    assert c.post('/api/v1/sorgu', json={'sql': 'SELECT ?, ?', 'parametreler': [1]}, headers=B(k2)).status_code == 400
    assert sorgu(c, k2, 'SELECT ? AS a, ? AS b', ['x', 2]).json['satirlar'] == [['x', 2]]
    assert c.get('/api/v1/sorgu', headers=B(k2)).status_code == 405


def test_sql_5000_satir_kesme(web):
    c, a = web
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.executemany('INSERT INTO kayitlar(anahtar,proje,kt,personel) VALUES(?,?,?,?)', [('k%d' % i, 'OF', 1, 'p') for i in range(5003)])
    con.close()
    _, k = anahtar(a, ['OF'], sql_izni=True)
    r = sorgu(c, k, 'SELECT id FROM kayitlar')
    assert r.status_code == 200 and r.json['kesildi'] is True and r.json['satir_sayisi'] == 5000 and len(r.json['satirlar']) == 5000
    r = sorgu(c, k, 'SELECT id FROM kayitlar LIMIT 10')
    assert r.json['kesildi'] is False and r.json['satir_sayisi'] == 10


def test_sql_sure_siniri(web, monkeypatch):
    c, a = web
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.executemany('INSERT INTO kayitlar(anahtar,proje,kt,personel) VALUES(?,?,?,?)', [('s%d' % i, 'OF', 1, 'p') for i in range(60)])
    con.close()
    monkeypatch.setattr(api, 'SQL_SURE_SN', 0.2)
    _, k = anahtar(a, ['OF'], sql_izni=True)
    basla = time.monotonic()
    r = sorgu(c, k, 'SELECT count(*) FROM kayitlar a, kayitlar b, kayitlar c, kayitlar d, kayitlar e')
    assert r.status_code == 400 and r.json['neden'] == 'sure' and time.monotonic() - basla < 5


def test_sql_authorizer_olmadan_calismaz(web, monkeypatch):
    """Öz denetim: authorizer bir şekilde devre dışı kalırsa (burada no-op ile benzetim) sorgu çalıştırılmaz, 500 döner."""
    c, a = web
    veri(a)
    _, k = anahtar(a, sql_izni=True)
    monkeypatch.setattr(api.Yetkilendirici, '__call__', lambda self, *x: sqlite3.SQLITE_OK)
    r = sorgu(c, k, 'SELECT * FROM kayitlar')
    assert r.status_code == 500 and r.json['ok'] is False and 'satirlar' not in r.json


def test_sql_baglantisi_salt_okunur(web):
    c, a = web
    veri(a)
    con = sqlite3.connect('file:' + a['DB'] + '?mode=ro', uri=True)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO ayarlar VALUES('x','y')")
    con.close()
    with pytest.raises(api.SorguHatasi) as e:
        api.sorgu_calistir(a['DB'], 'SELECT * FROM ayarlar', [], ['OF'], False, True)
    assert e.value.kod == 403


def test_tek_ifade_yardimcisi():
    assert api.tek_ifade(' SELECT 1 ; ') == 'SELECT 1'
    assert api.tek_ifade("SELECT ';' AS x") == "SELECT ';' AS x"
    assert api.tek_ifade('select 1 -- son yorum') == 'select 1 -- son yorum'
    for bad in ('SELECT 1; SELECT 2', 'DELETE FROM kayitlar', '  ', 'SELECT 1;;'):
        with pytest.raises(api.SorguHatasi):
            api.tek_ifade(bad)


# ---------------------------------------------------------------- yönetim sayfası

def test_yonetim_sayfasi_olustur_goster_iptal(web):
    c, a = web
    login(c)
    r = c.get('/yonetim/api-anahtarlari')
    assert r.status_code == 200 and 'API anahtarı oluştur'.encode() in r.data and b'API anahtarlar' in r.data
    assert b'href="/yonetim/api-anahtarlari"' in c.get('/').data  # yönetim menüsü bağlantısı
    nonce = re.search(r"script-src 'self' 'nonce-([^']+)'", r.headers['Content-Security-Policy']).group(1)
    assert ('nonce="' + nonce + '"').encode() in r.data
    r = c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'Rapor', 'kapsam': 'secili', 'projeler': ['OF'],
                                                  'yalniz_onayli': '1', 'sql_izni': '1'})
    assert r.status_code == 200
    k = re.search(rb'<code>(kp_[A-Za-z0-9]{40})</code>', r.data).group(1).decode()
    row = satirlar(a, 'SELECT * FROM api_anahtarlari')[0]
    assert row['ozet'] == aa.ozet(k) and row['sql_izni'] == 1 and row['gorsel_izni'] == 0 and row['projeler'] == '["OF"]'
    assert c.get('/api/v1/ozet', headers=B(k)).status_code == 200
    sayfa = c.get('/yonetim/api-anahtarlari').data
    assert k.encode() not in sayfa and ('kp_' + k[3:11]).encode() in sayfa and b'GET /api/v1/ozet' in sayfa
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'x', 'kapsam': 'secili', 'projeler': ['YOKPROJE']}).status_code == 400
    assert c.post('/yonetim/api-anahtarlari', data={'islem': 'iptal', 'id': row['id']}).status_code == 400  # CSRF
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'iptal', 'id': row['id']}).status_code == 302
    assert c.get('/api/v1/ozet', headers=B(k)).status_code == 401
    adlar = {d['islem'] for d in satirlar(a, 'SELECT islem FROM denetim')}
    assert {'api_anahtar_olustur', 'api_anahtar_iptal'} <= adlar
    assert 'API anahtarı oluşturma'.encode() in c.get('/denetim').data


def test_yonetim_sayfasi_yalniz_superadmin(web):
    from app import kullanicilar
    c, a = web
    kullanicilar.ekle(a, 'okur', 'OF:oku,kt', 'Test-Password-123!'); kullanicilar.guncelle(a, 'okur', sifre_degistir=0)
    assert c.get('/yonetim/api-anahtarlari').status_code == 302
    login(c, 'okur')
    assert c.get('/yonetim/api-anahtarlari').status_code == 403
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'x', 'kapsam': 'hepsi'}).status_code == 403
    assert satirlar(a, 'SELECT count(*) n FROM api_anahtarlari')[0]['n'] == 0
    assert b'api-anahtarlari' not in c.get('/').data


def test_diger_sayfalarda_csp_ve_oturum_bozulmadi(web):
    c, a = web
    login(c)
    for url in ('/', '/kayitlar', '/yonetim/kullanicilar'):
        r = c.get(url)
        assert r.status_code == 200 and "script-src 'self' 'nonce-" in r.headers['Content-Security-Policy']
    assert c.get('/kayitlar').headers['Cache-Control'] == 'private, no-store'


def test_sema_bayragi_24_ve_eski_db_gecisi(tmp_path):
    yol = str(tmp_path / 'panel.db')
    con = db.baglan(yol)
    assert db.ayar_al(con, 'core_schema_24') == '1'
    con.execute('DROP TABLE api_gunlugu'); con.execute('DROP TABLE api_anahtarlari')
    con.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_24'")  # 2.3.1 durumu
    assert not db._ready(con); con.close()
    con = db.baglan(yol)
    tablolar = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'api_anahtarlari', 'api_gunlugu'} <= tablolar and db._ready(con)
    con.close()


def test_authorizer_tek_basina_yazma_pragma_attach_reddeder(web):
    """Metin ön süzgeci atlanmış olsa bile (yazılabilir bağlantıda, doğrudan ifadeyle) authorizer her şeyi reddeder."""
    c, a = web
    veri(a)
    con = sqlite3.connect(a['DB'])  # bilerek mode=ro DEĞİL: koruma yalnız authorizer'dan gelmeli
    kaynaklar, temp_adlari = api.gorunumleri_kur(con, ['OF'], False, True)
    con.set_authorizer(api.Yetkilendirici(kaynaklar, temp_adlari))
    for ifade in ('PRAGMA table_info(kayitlar)', 'PRAGMA journal_mode=DELETE', "ATTACH DATABASE ':memory:' AS x", 'DELETE FROM main.kayitlar',
                  "UPDATE main.kayitlar SET kt=0", "INSERT INTO main.ayarlar VALUES('x','y')", 'CREATE TEMP TABLE z(a)', 'DROP VIEW kayitlar',
                  'SELECT * FROM main.panel_kullanicilari', 'SELECT * FROM sqlite_master', 'VACUUM', 'DETACH temp', 'BEGIN', 'ANALYZE',
                  'SELECT * FROM main.kayitlar'):
        with pytest.raises(sqlite3.DatabaseError) as e:
            con.execute(ifade).fetchall()
        assert re.search(r'not authorized|authorization denied|prohibited', str(e.value)), (ifade, e.value)
    assert [r[0] for r in con.execute('SELECT personel FROM kayitlar')] == ['ayse']
    con.close()
    assert satirlar(a, 'SELECT count(*) n FROM kayitlar')[0]['n'] == 4
