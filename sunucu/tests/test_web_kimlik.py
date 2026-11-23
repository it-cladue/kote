"""Kimlik/oturum denetimi bulgularının regresyon testleri (denetçinin hazır testleri; WEB ekibi düzeltmelerine uyarlandı:
kilit mesajı genel, /sifre ayrı sayaç, frame-ancestors 'none')."""
import time
from pathlib import Path
import pytest
from app import db, kullanicilar
from tests.test_web import web, token, login, csrf


def test_sonraki_kontrol_karakterleri_acik_yonlendirme_degil(web):
    c, a = web
    for bad in ['/%09/evil.example', '/%0b/evil.example', '/%0d%0a/evil.example', '//evil.example', '/\\evil.example', 'https://evil.example', '/%5C/evil.example']:
        r = c.post('/giris?sonraki=' + bad, data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'Test-Password-123!'})
        assert r.status_code == 302 and r.headers['Location'] == '/', bad
        c.post('/cikis', data={'csrf': csrf(c)})
    r = c.post('/giris?sonraki=%2Fkayitlar%3Fdurum%3Donayli', data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'Test-Password-123!'})
    assert r.headers['Location'] == '/kayitlar?durum=onayli'


def test_cikis_eski_cerezi_gecersiz_kilar(web):
    c, a = web
    login(c)
    eski = c.get_cookie('kanit_session').value
    c.post('/cikis', data={'csrf': csrf(c)})
    c.set_cookie('kanit_session', eski)
    r = c.get('/')
    assert r.status_code in (302, 401)
    con = db.baglan(a['DB']); assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='cikis'").fetchone()[0] == 1; con.close()


def test_kilit_suresi_dolunca_sayac_sifirlanir_ve_denetime_yazilir(web):
    c, a = web
    for _ in range(5): c.post('/giris', data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'bad'})
    con = db.baglan(a['DB'])
    row = con.execute("SELECT hatali_giris,kilit_bitis FROM panel_kullanicilari WHERE kullanici_adi='testadmin'").fetchone()
    assert row['hatali_giris'] == 5 and row['kilit_bitis']
    assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='giris_kilit'").fetchone()[0] == 1
    con.execute("UPDATE panel_kullanicilari SET kilit_bitis='2000-01-01 00:00:00' WHERE kullanici_adi='testadmin'"); con.commit()
    c.post('/giris', data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'bad'})
    row = con.execute("SELECT hatali_giris,kilit_bitis FROM panel_kullanicilari WHERE kullanici_adi='testadmin'").fetchone()
    assert row['hatali_giris'] == 1 and row['kilit_bitis'] is None
    con.close()


def test_var_olmayan_kullanici_da_hash_maliyeti_oder(web):
    c, a = web
    t = time.perf_counter(); kullanicilar.dogrula(a, 'yokboylebiri', 'x'); yok = time.perf_counter() - t
    t = time.perf_counter(); kullanicilar.dogrula(a, 'testadmin', 'x'); var = time.perf_counter() - t
    assert yok > var * 0.5  # scrypt maliyeti her iki yolda da ödenir


def test_manus_routes_giris_gerektirir(web):
    c, a = web
    assert c.get('/manus-routes.json').status_code in (302, 401)
    login(c); assert c.get('/manus-routes.json').status_code == 200


def test_guvenlik_basliklari_ve_nonce(web):
    c, a = web
    login(c); r = c.get('/')
    csp = r.headers['Content-Security-Policy']
    assert "script-src 'self' 'nonce-" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    nonce = csp.split("'nonce-")[1].split("'")[0]
    html = r.get_data(as_text=True)
    assert '<script>' not in html and ('nonce="' + nonce + '"') in html
    assert r.headers['Permissions-Policy'] and r.headers['Cross-Origin-Opener-Policy'] == 'same-origin'


def test_gecici_sifre_cerezde_degil(web):
    c, a = web
    login(c)
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'yeni.kisi', 'rol': 'admin', 'projeler': ['OF']})
    assert r.status_code == 302
    cerez = c.get_cookie('kanit_session').value
    with c.session_transaction() as s:
        token_value = s['gecici_sifre']; assert isinstance(token_value, str) and len(token_value) == 32
    html = c.get('/yonetim/kullanicilar').get_data(as_text=True)
    assert 'id="gecici-sifre-deger">' in html
    sifre = html.split('id="gecici-sifre-deger">')[1].split('<')[0]
    assert sifre not in cerez and len(sifre) >= 15
    assert kullanicilar.dogrula(a, 'yeni.kisi', sifre)[0]
    assert 'id="gecici-sifre-deger">' not in c.get('/yonetim/kullanicilar').get_data(as_text=True)  # tek kullanımlık


def test_admin_parolasi_zorunlu_degisim_ister(web):
    c, a = web
    login(c)
    kullanicilar.ekle(a, 'duzenlenen', 'OF:oku', 'Parola-123456'); kullanicilar.guncelle(a, 'duzenlenen', sifre_degistir=0)
    user = kullanicilar.bul(a, 'duzenlenen')
    c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'duzenlenen', 'expected_version': user['session_version'], 'rol': 'admin', 'projeler': ['OF'], 'aktif': '1', 'sifre': 'AdminBiliyor1'})
    assert kullanicilar.bul(a, 'duzenlenen')['sifre_degistir'] == 1


def test_sifre_sayfasi_kilit_mesaji_ve_denetim(web):
    c, a = web
    login(c)
    for _ in range(5): c.post('/sifre', data={'csrf': csrf(c), 'eski': 'yanlis', 'yeni': 'Yeniparola12', 'yeni2': 'Yeniparola12'})
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': 'Test-Password-123!', 'yeni': 'Yeniparola12', 'yeni2': 'Yeniparola12'})
    assert 'Çok fazla hatalı deneme' in r.get_data(as_text=True)
    con = db.baglan(a['DB']); assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='sifre_hata'").fetchone()[0] == 5
    # Giriş kilidi ETKİLENMEZ; bekleme ayrı sayaçtan (denetimdeki sifre_hata satırları) gelir.
    row = con.execute("SELECT hatali_giris,kilit_bitis FROM panel_kullanicilari WHERE kullanici_adi='testadmin'").fetchone()
    assert row['hatali_giris'] == 0 and row['kilit_bitis'] is None
    con.execute("UPDATE denetim SET zaman='2000-01-01 00:00:00' WHERE islem='sifre_hata'"); con.commit(); con.close()
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': 'Test-Password-123!', 'yeni': 'Test-Password-123!', 'yeni2': 'Test-Password-123!'})
    assert 'eskisiyle aynı' in r.get_data(as_text=True)
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': 'Test-Password-123!', 'yeni': 'testadmin12', 'yeni2': 'testadmin12'})
    assert 'kullanıcı adını' in r.get_data(as_text=True)


def test_mutlak_oturum_suresi(web):
    c, a = web
    login(c)
    with c.session_transaction() as s: s['gz'] = int(time.time()) - 25 * 3600
    r = c.get('/'); assert r.status_code in (302, 401)
    with c.session_transaction() as s: assert 'kad' not in s


def test_ip_siniri_denetime_bir_kez_yazilir(web):
    c, a = web
    for i in range(22): c.post('/giris', data={'csrf': token(c), 'kullanici': 'yok%d' % i, 'sifre': 'x'})
    con = db.baglan(a['DB'])
    assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='giris_sinir'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='giris_hata'").fetchone()[0] == 20
    con.close()
