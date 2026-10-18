"""Kayıtlar 2.2: sağlam ayrıntı, proje çipleri, toplu onay, Gyazo vekili, görsel yolları, 409."""
import io
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests
from PIL import Image

from app import db, kullanicilar, yetki
from test_web import web, seed, login, csrf

GID = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
GID2 = 'ffffffffffffffffffffffffffffffff'


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'row:' + str(time.time_ns()))
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def png_bytes(color=(0, 120, 255), size=(24, 16)):
    stream = io.BytesIO(); Image.new('RGB', size, color).save(stream, 'PNG'); return stream.getvalue()


# ---------------------------------------------------------------- ayrıntı (Detay)
def test_detail_json_for_every_record_shape(web):
    c, a = web; login(c)
    normal = seed(a)
    lead_only = insert(a, lead_id='LEAD-77', kaynak='telegram', giris_tipi='lead')
    legacy = insert(a, kaynak='excel', link='https://gyazo.com/' + GID, link_turu='gyazo', excel_satir=5, tarih_ham='01.02.2023', excel_durum='silinmis', kt=1, kt_kaynak='excel')
    missing_file = insert(a, gorsel_dosya=str(Path(a['GORSEL_KLASOR']) / 'yok.png'), personel='X1')
    deleted = insert(a, personel='SIL', silindi=1, silen='testadmin', silme_zamani=db.simdi())
    broken_json = insert(a, soru_anlik_json='{bozuk', cevaplar_json='[1,2', personel='Q')
    odd_values = insert(a, aciklama=b'\xff\xfe ham bayt', link=12345, gorsel2='not-a-link', personel=b'P\xc3\xbc')
    second_missing = insert(a, gorsel2='https://gyazo.com/' + GID2, gorsel2_dosya=str(Path(a['GORSEL_KLASOR']) / 'yok2.png'), personel='G2')
    path2 = Path(a['GORSEL_KLASOR']) / 'ikinci.png'; path2.write_bytes(png_bytes((9, 9, 9)))
    second_ok = insert(a, gorsel2_dosya=str(path2), personel='G3')
    assert c.post(f'/kayit/{normal}/yorum', data={'csrf': csrf(c), 'yorum': 'Not'}).json['ok']
    for kid in (normal, lead_only, legacy, missing_file, deleted, broken_json, odd_values, second_missing, second_ok):
        r = c.get(f'/kayit/{kid}')
        assert r.status_code == 200, kid
        d = r.json
        assert d['id'] == kid and 'gorsel_dosya' not in d and 'file_id' not in d
        for key in ('gorsel_var', 'gorsel_kaynak', 'gorsel2_var', 'izin_kt', 'izin_sil', 'yorumlar', 'gecmis', 'soru_cevaplar', 'renk'):
            assert key in d, (kid, key)
    d = c.get(f'/kayit/{normal}').json
    assert d['gorsel_var'] and d['gorsel_kaynak'] == 'yerel' and d['gorsel_url'] and d['indir_url'].endswith('indir=1') and len(d['yorumlar']) == 1
    d = c.get(f'/kayit/{lead_only}').json
    assert d['lead_id'] == 'LEAD-77' and not d['gorsel_var'] and d['gorsel_url'] is None and d['dis_link'] is None
    d = c.get(f'/kayit/{legacy}').json
    assert d['gorsel_kaynak'] == 'gyazo' and d['gorsel_var'] and d['dis_link'] == 'https://gyazo.com/' + GID and d['kt'] == 1 and d['excel_durum'] == 'silinmis'
    d = c.get(f'/kayit/{missing_file}').json
    assert not d['gorsel_var'] and d['gorsel_kaynak'] == 'kayip' and d['gorsel_kayip'] and d['gorsel_url'] is None  # dosya yolu var, dosya yok (son QA K3)
    d = c.get(f'/kayit/{deleted}').json
    assert d['silindi'] == 1 and d['geri_al_olur'] and d['silen'] == 'testadmin'
    d = c.get(f'/kayit/{broken_json}').json
    assert d['soru_cevaplar'] == []
    d = c.get(f'/kayit/{odd_values}').json
    assert d['dis_link'] is None and d['link'] == '12345' and 'ham bayt' in d['aciklama'] and d['dis_link2'] is None
    d = c.get(f'/kayit/{second_missing}').json
    assert not d['gorsel2_var'] or d['gorsel_kaynak'] == 'yok'
    d = c.get(f'/kayit/{second_ok}').json
    assert d['gorsel2_var'] and d['gorsel2_url'] and c.get(f'/gorsel/{second_ok}?ikinci=1').status_code == 200 and c.get(f'/kucuk/{second_ok}?ikinci=1').status_code == 200


def test_detail_errors_are_json_with_turkish_message(web):
    c, a = web; login(c)
    xhr = {'X-Requested-With': 'XMLHttpRequest'}  # fetch() çağrısı JSON alır; tarayıcıda doğrudan açılan adres HTML hata sayfası (son QA K6)
    r = c.get('/kayit/999999', headers=xhr); assert r.status_code == 404 and 'bulunamadı' in r.json['hata']
    account(a, 'ofonly', 'OF:oku'); pa = seed(a, 'PA', 'pa:1')
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofonly')
    r = c.get(f'/kayit/{pa}', headers=xhr); assert r.status_code == 403 and r.json['hata']
    r = c.post(f'/kayit/{pa}/kt', data={'csrf': csrf(c)}); assert r.status_code == 403 and r.json['ok'] is False


def test_kayit_sozluk_tolerates_null_key_and_resolver_failure(web, monkeypatch):
    from app import panel
    c, a = web; login(c)
    with panel.app.test_request_context('/kayitlar'):
        panel.g.yk = yetki.coz('admin'); panel.g.k = {'kullanici_adi': 'testadmin'}
        d = panel.kayit_sozluk({'id': 7, 'anahtar': None, 'proje': None, 'link': None, 'silindi': None, 'kt': None, 'gorsel_dosya': 3})
        assert d['anahtar'] == 'id:7' and d['silindi'] == 0 and d['kt'] == 0 and not d['gorsel_var']
        monkeypatch.setattr(panel.COZUCU, 'yerel_dosya', lambda row: (_ for _ in ()).throw(RuntimeError('boom')))
        d = panel.kayit_sozluk({'id': 8, 'anahtar': 'x', 'proje': 'OF', 'link': 'https://gyazo.com/' + GID})
        assert d['gorsel_kaynak'] == 'gyazo' and d['dis_link']


# ---------------------------------------------------------------- filtreler ve çipler
def test_project_chips_and_empty_selection_means_all(web):
    from app import panel
    from werkzeug.datastructures import MultiDict
    c, a = web; login(c); of = seed(a); pa = seed(a, 'PA', 'pa:2')
    with panel.app.test_request_context('/kayitlar'):
        panel.g.yk = yetki.coz('admin'); panel.g.k = {'kullanici_adi': 'testadmin'}
        allowed = ['OF', 'PA']
        w, p, f = panel._filtre_sql(MultiDict(), allowed)
        assert p[:2] == allowed and f['proje'] == [] and f['proje_etkin'] == allowed and '1=0' not in w
        w, p, f = panel._filtre_sql(MultiDict([('proje', ''), ('proje', 'hepsi')]), allowed)
        assert f['proje'] == [] and f['proje_etkin'] == allowed
        w, p, f = panel._filtre_sql(MultiDict([('proje', 'pa'), ('proje', 'PA')]), allowed)
        assert f['proje'] == ['PA'] and f['proje_etkin'] == ['PA']
        w, p, f = panel._filtre_sql(MultiDict(), [])
        assert w == '1=0'
    html = c.get('/kayitlar?durum=hepsi').data.decode()
    assert 'filtre-tum-projeler' not in html and 'proje-cip' in html and 'id="filtre-tumu"' in html
    assert 'Excel (bu görünüm)' in html and 'id="sayfa-boyu"' in html and 'id="sec-hepsi"' in html
    assert html.count('class="kayit ') == 2
    assert c.get('/kayitlar?durum=hepsi&proje=').status_code == 200
    page = c.get('/kayitlar?durum=hepsi&proje=OF').data.decode()
    assert page.count('class="kayit ') == 1 and 'value="OF" checked' in page and '1 proje seçili' in page
    assert c.get('/kategoriler.json?proje=').json['kategoriler'] == c.get('/kategoriler.json').json['kategoriler']
    assert c.get('/kayitlar?gorunum=bilinmez').status_code == 200
    for size, expect in (('96', 'value="96"'), ('7', '<option value="/kayitlar?durum=hepsi&amp;boy=48&amp;s=1" selected>')):
        body = c.get('/kayitlar?durum=hepsi&boy=' + size).data.decode()
        assert ('selected>96' in body) == (size == '96')
    account(a, 'ofonly', 'OF:oku'); c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofonly')
    page = c.get('/kayitlar?durum=hepsi').data.decode()
    assert 'value="PA"' not in page and 'value="OF"' in page and 'sec-hepsi' not in page and 'kayit-sec' not in page
    assert c.get('/kayitlar?proje=PA').status_code == 403


# ---------------------------------------------------------------- toplu onay
def test_bulk_approve_rules_counts_and_permissions(web):
    c, a = web; account(a, 'ofadmin', 'OF:oku,kt'); account(a, 'reader', 'OF:oku'); login(c)
    r1 = seed(a); r2 = insert(a, personel='B'); already = insert(a, personel='C', kt=1); gone = insert(a, personel='D', silindi=1); pa = seed(a, 'PA', 'pa:3')
    r = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': [r1, r2, already, gone, 424242], 'deger': '1'})
    assert r.status_code == 200
    d = r.json
    assert d['ok'] and d['degisen'] == 2 and d['zaten'] == 1 and d['silinen'] == 1 and d['bulunamadi'] == 1 and sorted(d['ids']) == [r1, r2] and '2 kayıt onaylandı' in d['mesaj']
    con = db.baglan(a['DB'])
    assert con.execute('SELECT COUNT(*) FROM kayitlar WHERE kt=1 AND id IN (?,?)', (r1, r2)).fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='onayla'").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM mesaj_bildirimleri WHERE kullanici_adi='ofadmin' AND tur='onay'").fetchone()[0] == 2
    assert con.execute('SELECT surum FROM kayitlar WHERE id=?', (r1,)).fetchone()[0] == 2; con.close()
    r = c.post('/kayitlar/toplu-kt', json={'ids': [r1, pa], 'deger': 0}, headers={'X-CSRF': csrf(c)})
    assert r.json['degisen'] == 1 and r.json['zaten'] == 1 and r.json['kt'] == 0
    assert c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': []}).status_code == 400
    assert c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': ['x']}).status_code == 400
    assert c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': list(range(1, 302))}).status_code == 400
    assert c.post('/kayitlar/toplu-kt', data={'ids': [r1]}).status_code == 400
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofadmin')
    d = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': [r1, pa], 'deger': '1'}).json
    assert d['degisen'] == 1 and d['yetkisiz'] == 1 and d['ids'] == [r1]
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'reader')
    d = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': [r2], 'deger': '1'}).json
    assert d['degisen'] == 0 and d['yetkisiz'] == 1
    assert 'toplu-arac' not in c.get('/kayitlar?durum=hepsi').data.decode()


# ---------------------------------------------------------------- Gyazo vekili
class FakeGyazo:
    def __init__(self):
        self.hits = []; self.png = png_bytes()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def do_GET(self):
                outer.hits.append(self.path); path = self.path
                if path == '/' + GID + '.jpg' or path == '/redir-target.jpg':
                    self.send_response(200); self.send_header('Content-Type', 'image/png'); self.send_header('Content-Length', str(len(outer.png))); self.end_headers(); self.wfile.write(outer.png)
                elif path == '/' + ('b' * 32) + '.jpg':
                    self.send_response(302); self.send_header('Location', '/redir-target.jpg'); self.end_headers()
                elif path == '/' + ('c' * 32) + '.jpg':
                    self.send_response(302); self.send_header('Location', 'http://localhost:' + str(outer.port) + '/redir-target.jpg'); self.end_headers()
                elif path == '/' + ('d' * 32) + '.jpg':
                    self.send_response(200); self.send_header('Content-Type', 'image/jpeg'); self.send_header('Content-Length', str(50 * 1024 * 1024)); self.end_headers()
                elif path == '/' + ('e' * 32) + '.jpg':
                    body = b'<html>not an image</html>'; self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler); self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self): self.server.shutdown(); self.server.server_close()


@pytest.fixture
def fake_gyazo(web):
    from app import panel
    server = FakeGyazo()
    cozucu = panel.COZUCU
    cozucu.gyazo_kaynak = 'http://127.0.0.1:%d/{id}.jpg' % server.port
    cozucu.gyazo_hostlar = ('127.0.0.1',)
    session = requests.Session(); session.trust_env = False; cozucu._http = session
    yield server, cozucu
    server.close()


def test_gyazo_proxy_downloads_caches_and_serves(web, fake_gyazo):
    c, a = web; login(c); server, cozucu = fake_gyazo
    kid = insert(a, link='https://gyazo.com/' + GID, link_turu='gyazo', kaynak='excel', personel='GY')
    assert c.get(f'/kayit/{kid}').json['gorsel_kaynak'] == 'gyazo'
    r = c.get(f'/gorsel/{kid}'); assert r.status_code == 200 and r.data == server.png
    cache = Path(a['ONBELLEK']) / 'gyazo' / (GID + '.png'); assert cache.is_file()
    assert c.get(f'/kucuk/{kid}').status_code == 200
    r = c.get(f'/gorsel/{kid}?indir=1'); assert r.status_code == 200 and 'attachment' in r.headers['Content-Disposition'] and f'kayit-{kid}.png' in r.headers['Content-Disposition']
    assert server.hits.count('/' + GID + '.jpg') == 1
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('b' * 32)}) and server.hits[-1] == '/redir-target.jpg'


def test_gyazo_proxy_refuses_other_hosts_sizes_and_negative_caches(web, fake_gyazo):
    c, a = web; login(c); server, cozucu = fake_gyazo
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('c' * 32)}) is None
    assert '/redir-target.jpg' not in server.hits[-1:]
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('d' * 32)}) is None
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('e' * 32)}) is None
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('f' * 32)}) is None
    marker = Path(a['ONBELLEK']) / 'gyazo' / ('f' * 32 + '.yok'); assert marker.is_file()
    before = len(server.hits); assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('f' * 32)}) is None and len(server.hits) == before
    old = time.time() - 700; os.utime(marker, (old, old))
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + ('f' * 32)}) is None and len(server.hits) == before + 1
    kid = insert(a, link='https://gyazo.com/' + ('f' * 32), link_turu='gyazo', personel='YOK')
    assert c.get(f'/gorsel/{kid}').status_code == 404 and c.get(f'/kucuk/{kid}').status_code == 404
    detail = c.get(f'/kayit/{kid}').json
    assert detail['gorsel_kaynak'] == 'yok' and not detail['gorsel_var'] and detail['gorsel_url'] is None and detail['dis_link']
    assert cozucu.gyazo_indir({'link': 'https://teamzone.gyazo.com/x/' + GID}) is None
    assert cozucu.gyazo_indir({'link': 'https://example.com/' + GID}) is None
    cozucu.gyazo_hostlar = ('gyazo.com', 'i.gyazo.com')
    assert cozucu._gyazo_host_izinli('https://i.gyazo.com/' + GID + '.jpg') and cozucu._gyazo_host_izinli('https://gyazo.com/' + GID)
    for bad in ('https://gyazo.com.evil.example/' + GID, 'https://evil.example/gyazo.com/' + GID, 'ftp://gyazo.com/x', 'http://127.0.0.1/x', ''):
        assert not cozucu._gyazo_host_izinli(bad), bad
    assert cozucu.gyazo_indir({'link': 'https://gyazo.com/' + GID}) is None and server.hits.count('/' + GID + '.jpg') == 0


def test_gyazo_proxy_can_be_disabled(web, fake_gyazo):
    c, a = web; login(c); server, cozucu = fake_gyazo
    cozucu.gyazo_acik = False
    kid = insert(a, link='https://gyazo.com/' + GID, link_turu='gyazo')
    d = c.get(f'/kayit/{kid}').json
    assert d['gorsel_kaynak'] == 'yok' and not d['gorsel_var'] and d['dis_link']
    assert c.get(f'/gorsel/{kid}').status_code == 404 and server.hits == []


# ---------------------------------------------------------------- görsel yolları
def test_image_routes_reject_paths_outside_allowed_roots(web, tmp_path):
    c, a = web; login(c)
    outside = tmp_path / 'outside.png'; outside.write_bytes(png_bytes())
    inside = Path(a['GORSEL_KLASOR']) / 'ic.png'; inside.write_bytes(png_bytes())
    traversal = insert(a, gorsel_dosya='../outside.png')
    absolute = insert(a, gorsel_dosya=str(outside))
    link_path = insert(a, link='C:\\Users\\x\\outside.png', link_turu='dosya')
    second = insert(a, gorsel_dosya=str(inside), gorsel2_dosya=str(outside))
    for kid in (traversal, absolute, link_path):
        assert c.get(f'/gorsel/{kid}').status_code == 404 and c.get(f'/kucuk/{kid}').status_code == 404, kid
        assert not c.get(f'/kayit/{kid}').json['gorsel_var']
    assert c.get(f'/gorsel/{second}').status_code == 200 and c.get(f'/gorsel/{second}?ikinci=1').status_code == 404
    assert not c.get(f'/kayit/{second}').json['gorsel2_var']
    assert c.get('/gorsel/999').status_code == 404
    account(a, 'ofonly', 'OF:oku'); pa = seed(a, 'PA', 'pa:9')
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofonly')
    assert c.get(f'/gorsel/{pa}').status_code == 403 and c.get(f'/kucuk/{pa}').status_code == 403
    assert c.get(f'/kucuk/{second}').status_code == 200


# ---------------------------------------------------------------- 409, silme nedeni, doğrulama
def test_conflict_delete_reason_and_edit_validation(web):
    c, a = web; account(a, 'ofedit', 'OF:oku,kt,duzenle,sil'); login(c); kid = seed(a)
    d = c.get(f'/kayit/{kid}').json
    assert c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'personel': 'new', 'surum': d['surum']}).json['ok']
    for url, extra in ((f'/kayit/{kid}/kt', {'deger': '1'}), (f'/kayit/{kid}/duzenle', {'personel': 'z'}), (f'/kayit/{kid}/sil', {}), (f'/kayit/{kid}/gyazo', {})):
        r = c.post(url, data=dict(extra, csrf=csrf(c), surum=d['surum']))
        assert r.status_code == 409 and r.json['ok'] is False and 'değiştirildi' in r.json['hata'], url
    r = c.post(f'/kayit/{kid}/sil', data={'csrf': csrf(c), 'sebep': 'Yanlış proje'}); assert r.json['ok'] and r.json['degisiklik']
    con = db.baglan(a['DB']); row = con.execute("SELECT aciklama FROM denetim WHERE islem='sil' ORDER BY id DESC LIMIT 1").fetchone(); assert row['aciklama'] == 'Yanlış proje'; con.close()
    assert c.post(f'/kayit/{kid}/sil', data={'csrf': csrf(c)}).json['degisiklik'] is False
    r = c.post(f'/kayit/{kid}/kt', data={'csrf': csrf(c)}); assert r.status_code == 400 and 'geri alın' in r.json['hata']
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'personel': 'q'}); assert r.status_code == 400 and r.json['hata']
    assert c.post(f'/kayit/{kid}/geri-al', data={'csrf': csrf(c)}).json['ok']
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'personel': 'a\x01b'}); assert r.status_code == 400 and 'kontrol karakteri' in r.json['hata']
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofedit')
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': 'YOK_BOYLE_KATEGORI'}); assert r.status_code == 403 and 'kategori' in r.json['hata'].lower()
    assert c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': ''}).json['ok']
    assert c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': 'HGST'}).json['ok']
