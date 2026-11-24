# -*- coding: utf-8 -*-
"""Güvenlik düzeltme turu (WEB ekibi): web kimlik / oturum / girdi doğrulama bulgularının regresyon testleri.
Kapsam: açık yönlendirme atlatmaları, çıkışta oturum düşmesi, kilit sayacı ve genel kilit mesajı, CSP+nonce (tüm sayfalar),
/manus-routes.json yetkisi, /saglik sürüm başlığı, /sifre ayrı sayacı ve parola politikası, kontrol karakteri temizliği,
stderr günlük satırı biçimi (fail2ban), waitress vekil ayarı, Excel satır üst sınırı, csrf_hata denetimi, SESSION_SECRET_ESKI."""
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import openpyxl
import pytest

from app import db, kullanicilar, panel
from tests.test_web import web, token, login, csrf, seed  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
XHR = {'X-Requested-With': 'XMLHttpRequest'}
SIFRE = 'Test-Password-123!'
GUNLUK = re.compile(r'^kanit-web (GIRIS_HATA|GIRIS_SINIR|GIRIS_KILIT|CSRF_HATA) ip=[0-9a-fA-F.:]+( kullanici=[a-z0-9_.-]+)?$')


def giris_dene(c, ad, sifre, sonraki=None):
    url = '/giris' + ('?sonraki=' + sonraki if sonraki is not None else '')
    return c.post(url, data={'csrf': token(c), 'kullanici': ad, 'sifre': sifre})


def denetim_say(a, islem, **kosul):
    con = db.baglan(a['DB'])
    sql = 'SELECT COUNT(*) FROM denetim WHERE islem=?'; par = [islem]
    for k, v in kosul.items():
        sql += ' AND ' + k + '=?'; par.append(v)
    n = con.execute(sql, par).fetchone()[0]; con.close(); return n


def hesap(a, ad='testadmin'):
    con = db.baglan(a['DB']); row = dict(con.execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?', (ad,)).fetchone()); con.close(); return row


# ---- 1. Açık yönlendirme: kontrol karakteri, protokol-göreli, ters bölü, şema, CRLF → '/' ----------------------
def test_acik_yonlendirme_atlatmalari_reddedilir(web):
    c, a = web
    kotu = ['/%09/evil.example', '/%0a/evil.example', '/%0d%0a/evil.example', '/%0b/evil.example', '//evil.example', '/%5Cevil.example',
            '/\\evil.example', 'https://evil.example', 'http://evil.example/', '/%00/evil', 'javascript:alert(1)', '/' + 'a' * 2100]
    for bad in kotu:
        r = giris_dene(c, 'testadmin', SIFRE, sonraki=bad)
        assert r.status_code == 302 and r.headers['Location'] == '/', bad
        assert 'evil' not in r.headers['Location']
        c.post('/cikis', data={'csrf': csrf(c)})
    # Geçerli site içi hedef ve sorgu dizesi korunur.
    r = giris_dene(c, 'testadmin', SIFRE, sonraki='%2Fkayitlar%3Fdurum%3Donayli%26proje%3DOF')
    assert r.headers['Location'] == '/kayitlar?durum=onayli&proje=OF'
    assert denetim_say(a, 'sunucu_hata') == 0  # CRLF artık 500 üretmiyor


def test_guvenli_yol_yardimcisi():
    assert panel._guvenli_yol('/kayitlar?s=2') == '/kayitlar?s=2'
    for bad in ('', None, '/\t/evil', '/\r\n/evil', '//evil', '/\\evil', 'https://evil', '/x\x7f', 'kayitlar', '/\x00'):
        assert panel._guvenli_yol(bad) == '/', repr(bad)


# ---- 2. Çıkış sunucu tarafında geçersizleştirir -------------------------------------------------------------
def test_cikis_sonrasi_eski_cerez_giris_sayfasina_gider(web):
    c, a = web
    login(c)
    eski = c.get_cookie('kanit_session').value
    sv = hesap(a)['session_version']
    r = c.post('/cikis', data={'csrf': csrf(c)})
    assert r.status_code == 302 and r.headers['Location'].endswith('/giris')
    assert hesap(a)['session_version'] == sv + 1
    c.set_cookie('kanit_session', eski)
    r = c.get('/')
    assert r.status_code == 302 and '/giris' in r.headers['Location']
    c.set_cookie('kanit_session', eski)
    r = c.get('/bildirim.json', headers=XHR)
    assert r.status_code == 401 and r.json['ok'] is False
    c.set_cookie('kanit_session', eski)
    assert c.get('/yonetim/kullanicilar').status_code in (302, 401)
    assert denetim_say(a, 'cikis', kullanici='testadmin') == 1
    # Oturumsuz çıkış denetim yazmaz, giriş sayfasına yönlendirir.
    c2 = panel.app.test_client(); r = c2.post('/cikis', data={})
    assert r.status_code == 302 and denetim_say(a, 'cikis') == 1


# ---- 3. Kilit: sayaç sıfırlanır, mesaj genel, denetim ve etiket -------------------------------------------
def test_kilit_mesaji_genel_ve_sayac_sifirlanir(web, capfd):
    c, a = web
    genel = 'Kullanıcı adı veya parola hatalı.'
    for _ in range(5):
        r = giris_dene(c, 'testadmin', 'yanlis'); assert genel in r.get_data(as_text=True)
    row = hesap(a); assert row['hatali_giris'] == 5 and row['kilit_bitis'] > db.simdi()
    assert denetim_say(a, 'giris_kilit', kullanici='testadmin') == 1
    # Kilitliyken doğru parola da aynı genel mesajı alır; kilit süresi ve sayaç değişmez; 'Çok fazla' metni sızmaz.
    r = giris_dene(c, 'testadmin', SIFRE)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and genel in html and 'Çok fazla' not in html and 'kilit' not in html.lower()
    assert hesap(a)['hatali_giris'] == 5 and hesap(a)['kilit_bitis'] == row['kilit_bitis']
    err = capfd.readouterr().err
    assert 'kanit-web GIRIS_KILIT ip=127.0.0.1 kullanici=testadmin' in err
    # Kilit Kullanıcılar sayfasında görünür (başka bir süperadmin ile).
    kullanicilar.ekle(a, 'ikinci', 'admin', SIFRE); kullanicilar.guncelle(a, 'ikinci', sifre_degistir=0)
    login(c, 'ikinci'); html = c.get('/yonetim/kullanicilar').get_data(as_text=True)
    assert 'Kilitli:' in html
    c.post('/cikis', data={'csrf': csrf(c)})
    # Süre dolunca tek hatalı deneme sayacı 1'e döndürür (süresiz kilit yok) ve ardından doğru parola girer.
    con = db.baglan(a['DB']); con.execute("UPDATE panel_kullanicilari SET kilit_bitis='2000-01-01 00:00:00' WHERE kullanici_adi='testadmin'"); con.commit(); con.close()
    giris_dene(c, 'testadmin', 'yanlis')
    row = hesap(a); assert row['hatali_giris'] == 1 and row['kilit_bitis'] is None
    assert giris_dene(c, 'testadmin', SIFRE).status_code == 302
    assert hesap(a)['hatali_giris'] == 0


def test_olmayan_kullanici_ve_pasif_hesap_ayni_mesaj(web):
    c, a = web
    genel = 'Kullanıcı adı veya parola hatalı.'
    kullanicilar.ekle(a, 'pasif', 'OF:oku', SIFRE); kullanicilar.guncelle(a, 'pasif', aktif=0)
    for ad, sifre in (('yokboyle', 'x'), ('pasif', SIFRE), ('testadmin', 'x')):
        assert genel in giris_dene(c, ad, sifre).get_data(as_text=True), ad
    # Geçersiz biçimli ad denetime '[geçersiz ad]' olarak yazılır (yanlış kutuya yazılan parola sızmaz).
    giris_dene(c, 'Gizli-Parola-Yanlis-Kutu!', 'x')
    assert denetim_say(a, 'giris_hata', kullanici='[geçersiz ad]') == 1
    assert denetim_say(a, 'giris_hata', kullanici='gizli-parola-yanlis-kutu!') == 0


# ---- 4. Güvenlik başlıkları: her sayfada CSP, nonce şablonla eşleşir, satır içi olay işleyici yok -------------
def _csp_kontrol(r, html_bekle=True):
    csp = r.headers.get('Content-Security-Policy', '')
    for parca in ("default-src 'self'", "script-src 'self' 'nonce-", "style-src 'self' 'unsafe-inline'", "img-src 'self' data:",
                  "connect-src 'self'", "frame-ancestors 'none'", "form-action 'self'", "base-uri 'self'", "object-src 'none'"):
        assert parca in csp, (parca, csp)
    assert r.headers['Permissions-Policy'].startswith('camera=()') and r.headers['Cross-Origin-Opener-Policy'] == 'same-origin'
    assert r.headers['X-Content-Type-Options'] == 'nosniff' and r.headers['X-Frame-Options'] == 'SAMEORIGIN'
    nonce = csp.split("'nonce-")[1].split("'")[0]
    assert len(nonce) >= 16
    if html_bekle and r.mimetype == 'text/html':
        html = r.get_data(as_text=True)
        for m in re.finditer(r'<script\b[^>]*>', html):
            etiket = m.group(0)
            assert 'src=' in etiket or ('nonce="' + nonce + '"') in etiket, etiket
        assert not re.search(r'\son[a-z]+\s*=\s*["\']', html), 'satır içi olay işleyici CSP ile kırılır'
        assert 'javascript:' not in html
        for m in re.finditer(r'<img[^>]+src="([^"]+)"', html):
            assert m.group(1).startswith('/') or m.group(1).startswith('data:'), m.group(0)
    return nonce


def test_her_sayfada_csp_ve_nonce(web):
    c, a = web
    kid = seed(a)
    r = c.get('/giris'); assert r.status_code == 200; _csp_kontrol(r)
    r = c.get('/'); assert r.status_code == 302; _csp_kontrol(r)
    login(c)
    kullanicilar.ekle(a, 'yardimci', 'OF:oku,kt', SIFRE)
    c.post(f'/kayit/{kid}/yorum', data={'csrf': csrf(c), 'yorum': 'merhaba', 'alici': 'yardimci'})
    con = db.baglan(a['DB']); con.execute("INSERT INTO tg_kullanicilar(id,username,first_name,onayli) VALUES('12345','tgtester','Test',1)"); con.commit(); con.close()
    sayfalar = ['/', '/kayitlar', '/kayitlar?gorunum=kart', '/kayitlar?gorunum=galeri', f'/kayitlar?durum=hepsi&ac={kid}', '/yonetim/kullanicilar',
                '/yonetim/katalog', '/bot', '/denetim', '/bildirimler', '/disa-aktar', '/excel-kontrol', '/arsiv', '/sifre',
                '/telegram/kullanici/12345/kanitlar', '/bot/kullanici/12345', '/manus-routes.json', '/durum.json', f'/kayit/{kid}', '/bildirim.json']
    nonces = set()
    for url in sayfalar:
        r = c.get(url)
        assert r.status_code == 200, (url, r.status_code)
        nonces.add(_csp_kontrol(r))
    assert len(nonces) == len(sayfalar)  # her yanıt için yeni nonce
    # Hata sayfaları ve görsel yanıtları da başlık taşır; bozuk görsel yer tutucusunun kendi CSP'si korunur.
    r = c.get('/olmayan-sayfa'); assert r.status_code == 404; _csp_kontrol(r)
    r = c.get(f'/kucuk/{kid}'); assert r.status_code == 200 and 'Content-Security-Policy' in r.headers
    r = c.get('/static/panel.js?v=2.3.1'); assert r.status_code == 200 and 'Content-Security-Policy' in r.headers
    assert 'includeSubDomains' not in r.headers.get('Strict-Transport-Security', '')


def test_statik_js_csp_uyumlu():
    for name in ('panel.js', 'katalog.js', 'tema.js'):
        js = (ROOT / 'app' / 'static' / name).read_text(encoding='utf-8')
        assert not re.search(r'\beval\s*\(|new Function\s*\(|setTimeout\s*\(\s*["\']|setInterval\s*\(\s*["\']', js), name
        assert not re.search(r'\son(click|change|submit|load|input|keyup|keydown|mouseover)\s*=\s*["\']', js), name
    for tpl in (ROOT / 'app' / 'templates').glob('*.html'):
        html = tpl.read_text(encoding='utf-8')
        for m in re.finditer(r'<script\b[^>]*>', html):
            assert 'src=' in m.group(0) or 'nonce="{{ csp_nonce }}"' in m.group(0), (tpl.name, m.group(0))
        assert not re.search(r'\son[a-z]+\s*=\s*["\']', html), tpl.name


# ---- 5. /manus-routes.json yalnız süperadmin; /saglik sürümü yalnız yerelden -------------------------------
def test_rota_listesi_ve_saglik_basligi(web):
    c, a = web
    assert c.get('/manus-routes.json').status_code in (302, 401)
    assert c.get('/manus-routes.json', headers=XHR).status_code == 401
    kullanicilar.ekle(a, 'okuyucu', 'OF:oku', SIFRE); kullanicilar.guncelle(a, 'okuyucu', sifre_degistir=0)
    login(c, 'okuyucu'); assert c.get('/manus-routes.json').status_code == 403
    c.post('/cikis', data={'csrf': csrf(c)}); login(c); assert c.get('/manus-routes.json').status_code == 200
    r = c.get('/saglik'); assert r.status_code == 200 and r.headers.get('X-Kanit-Paneli') == panel.SURUM and 'Set-Cookie' not in r.headers
    r = c.get('/saglik', headers={'X-Forwarded-For': '203.0.113.9'}); assert r.status_code == 200 and 'X-Kanit-Paneli' not in r.headers
    r = c.get('/saglik', environ_base={'REMOTE_ADDR': '203.0.113.9'}); assert r.status_code == 200 and 'X-Kanit-Paneli' not in r.headers


# ---- 6. /sifre: ayrı sayaç, doğru mesaj, parola politikası -----------------------------------------------
def test_sifre_sayfasi_hesabi_kilitlemez_ve_politika(web):
    c, a = web
    login(c)
    for _ in range(5):
        r = c.post('/sifre', data={'csrf': csrf(c), 'eski': 'yanlis', 'yeni': 'Guclu-Yeni-Parola-1', 'yeni2': 'Guclu-Yeni-Parola-1'})
        assert 'Mevcut parolanız yanlış.' in r.get_data(as_text=True) and 'Eski parola' not in r.get_data(as_text=True)
    row = hesap(a); assert row['hatali_giris'] == 0 and row['kilit_bitis'] is None  # giriş kilidi etkilenmedi
    assert denetim_say(a, 'sifre_hata', kullanici='testadmin') == 5
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': SIFRE, 'yeni': 'Guclu-Yeni-Parola-1', 'yeni2': 'Guclu-Yeni-Parola-1'})
    assert '10 dakika' in r.get_data(as_text=True) and 'kilitlenmedi' in r.get_data(as_text=True)
    assert denetim_say(a, 'sifre_hata') == 5  # bekleme sırasında sayaç büyümez (süresiz bekleme yok)
    assert c.get('/').status_code == 200  # oturum açık kalır, giriş yapılabilir
    con = db.baglan(a['DB']); con.execute("UPDATE denetim SET zaman='2000-01-01 00:00:00' WHERE islem='sifre_hata'"); con.commit(); con.close()
    beklenen = [('telecc123', 'çok yaygın'), ('Password1', 'çok yaygın'), ('123456789', 'çok yaygın'), (SIFRE, 'eskisiyle aynı'),
                ('xxTestAdmin99', 'kullanıcı adını'), ('kisa1', 'en az 8'), ('Guclu-Yeni-Parola-1', 'aynı değil')]
    for yeni, metin in beklenen:
        r = c.post('/sifre', data={'csrf': csrf(c), 'eski': SIFRE, 'yeni': yeni, 'yeni2': yeni if metin != 'aynı değil' else 'farkli-123456'})
        assert metin in r.get_data(as_text=True), (yeni, metin)
    assert hesap(a)['session_version'] == 2
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': SIFRE, 'yeni': 'Guclu-Yeni-Parola-1', 'yeni2': 'Guclu-Yeni-Parola-1'})
    assert r.status_code == 302 and kullanicilar.parola_dogru(a, 'testadmin', 'Guclu-Yeni-Parola-1')
    assert c.get('/').status_code == 200  # kendi oturumu sürer (sv güncellendi)


def test_parola_politikasi_yardimcisi():
    assert kullanicilar.parola_politikasi('ali', 'Guclu-Parola-99') is None
    assert 'yaygın' in kullanicilar.parola_politikasi('ali', 'qwerty123')
    assert 'yaygın' in kullanicilar.parola_politikasi('ali', 'Admin123!')
    assert 'kullanıcı adını' in kullanicilar.parola_politikasi('ali.veli', 'Ali.Veli2024')
    assert 'aynı' in kullanicilar.parola_politikasi('ali', 'AyniParola1', 'AyniParola1')
    assert 'en az 8' in kullanicilar.parola_politikasi('ali', 'kisa')


# ---- 7. Admin'in belirlediği parola: politika ve zorunlu değişim ---------------------------------------------
def test_admin_parolasi_politika_ve_zorunlu_degisim(web):
    c, a = web
    login(c)
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'yeni.kisi', 'rol': 'admin', 'projeler': ['OF'], 'sifre': 'password123'})
    assert r.status_code == 200 and 'çok yaygın' in r.get_data(as_text=True) and kullanicilar.bul(a, 'yeni.kisi') is None
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'yeni.kisi', 'rol': 'admin', 'projeler': ['OF'], 'sifre': 'Gecici-Parola-77', 'gorunen_ad': 'Ad\x00 Soyad\x07'})
    assert r.status_code == 302
    u = kullanicilar.bul(a, 'yeni.kisi'); assert u['sifre_degistir'] == 1 and u['ad'] == 'Ad Soyad'
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'yeni.kisi', 'expected_version': u['hesap_surumu'], 'rol': 'admin', 'projeler': ['OF'], 'aktif': '1', 'sifre': 'telecc123'})
    assert 'çok yaygın' in r.get_data(as_text=True)
    kullanicilar.guncelle(a, 'yeni.kisi', sifre_degistir=0); u = kullanicilar.bul(a, 'yeni.kisi')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'yeni.kisi', 'expected_version': u['hesap_surumu'], 'rol': 'admin', 'projeler': ['OF'], 'aktif': '1', 'sifre': 'Admin-Biliyor-1'})
    assert r.status_code == 302 and kullanicilar.bul(a, 'yeni.kisi')['sifre_degistir'] == 1
    html = c.get('/yonetim/kullanicilar').get_data(as_text=True)
    assert 'ilk girişte' in html.lower()


# ---- 8. Kontrol karakterleri: yorum, mesaj bildirimi, silme sebebi, görünen ad -----------------------------
def test_kontrol_karakterleri_temizlenir(web):
    c, a = web
    login(c); kid = seed(a)
    kullanicilar.ekle(a, 'alici', 'OF:oku,kt', SIFRE)
    r = c.post(f'/kayit/{kid}/yorum', data={'csrf': csrf(c), 'yorum': 'hello\x00world\x07\r\nikinci\tsatır\x1b', 'alici': 'alici'})
    assert r.status_code == 200 and r.json['ok']
    con = db.baglan(a['DB'])
    assert con.execute('SELECT metin FROM yorumlar WHERE id=?', (r.json['yorum_id'],)).fetchone()[0] == 'helloworld\nikinci\tsatır'
    assert con.execute("SELECT metin FROM mesaj_bildirimleri WHERE kullanici_adi='alici'").fetchone()[0] == 'helloworld\nikinci\tsatır'
    con.close()
    d = c.get(f'/kayit/{kid}').json
    assert d['yorumlar'][0]['metin'] == 'helloworld\nikinci\tsatır'
    assert c.post(f'/kayit/{kid}/yorum', data={'csrf': csrf(c), 'yorum': '\x00\x07'}).status_code == 400  # temizlenince boş → hata
    assert c.post(f'/kayit/{kid}/sil', data={'csrf': csrf(c), 'sebep': 'yanlış\x00 kayıt\x0c'}).json['ok']
    con = db.baglan(a['DB']); assert con.execute("SELECT aciklama FROM denetim WHERE islem='sil'").fetchone()[0] == 'yanlış kayıt'; con.close()
    assert db.metin_temizle('a\x00b\x1fc\r\nd', 3) == 'abc' and db.metin_temizle(None) == ''


# ---- 9. stderr günlük satırları (fail2ban biçimi) ------------------------------------------------------------
def test_stderr_gunluk_satirlari(web, capfd):
    c, a = web
    giris_dene(c, 'testadmin', 'yanlis')
    giris_dene(c, 'Parola Gibi Bir Sey!', 'x')
    err = capfd.readouterr().err
    satirlar = [s for s in err.splitlines() if s.startswith('kanit-web ')]
    assert 'kanit-web GIRIS_HATA ip=127.0.0.1 kullanici=testadmin' in satirlar
    assert 'kanit-web GIRIS_HATA ip=127.0.0.1 kullanici=-' in satirlar  # geçersiz ad yazılmaz
    assert all(GUNLUK.match(s) for s in satirlar), satirlar
    for i in range(19): giris_dene(c, 'yok%d' % i, 'x')
    r = giris_dene(c, 'yok99', 'x'); assert r.status_code == 429
    err = capfd.readouterr().err
    assert 'kanit-web GIRIS_SINIR ip=127.0.0.1' in err.splitlines()
    assert denetim_say(a, 'giris_sinir') == 1
    # Oturumlu kullanıcıdan geçersiz CSRF: tek satır + denetimde dakikada en çok 1 kayıt.
    con = db.baglan(a['DB']); con.execute("DELETE FROM denetim WHERE islem='giris_hata'"); con.commit(); con.close()
    login(c)
    for _ in range(3): assert c.post('/sifre', data={'csrf': 'bozuk', 'eski': 'x', 'yeni': 'y', 'yeni2': 'y'}).status_code == 400
    err = capfd.readouterr().err
    assert err.splitlines().count('kanit-web CSRF_HATA ip=127.0.0.1 kullanici=testadmin') == 1
    assert denetim_say(a, 'csrf_hata', kullanici='testadmin') == 1
    assert c.get('/').status_code == 200  # oturum açık kalır
    # Oturumsuz geçersiz CSRF denetim yazmaz (giriş sayfasına yönlendirilir).
    c2 = panel.app.test_client(); c2.post('/arsiv', data={'csrf': 'x'})
    assert denetim_say(a, 'csrf_hata') == 1
    # Günlük satırında satır sonu/boşluk enjeksiyonu yok.
    with panel.app.test_request_context('/', environ_base={'REMOTE_ADDR': '203.0.113.5'}):
        panel.guvenlik_gunlugu('GIRIS_HATA', 'kotu\nkanit-web GIRIS_HATA ip=1.1.1.1')
    satir = [s for s in capfd.readouterr().err.splitlines() if s.startswith('kanit-web ')]
    assert satir == ['kanit-web GIRIS_HATA ip=203.0.113.5 kullanici=-']


# ---- 10. waitress: tek güvenilen vekil, gövde üst sınırı ---------------------------------------------------
def test_sunucu_ayarlari_vekil_ve_govde(web, monkeypatch):
    c, a = web
    a['TRUST_PROXY'] = '1'; monkeypatch.delenv('GUVENILEN_PROXY', raising=False)
    s = panel.sunucu_ayarlari()
    assert s['trusted_proxy'] == '127.0.0.1' and s['trusted_proxy_count'] == 1 and s['trusted_proxy_headers'] == {'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'}
    assert s['max_request_body_size'] == panel.app.config['MAX_CONTENT_LENGTH'] + 1024 * 1024 == 13 * 1024 * 1024
    monkeypatch.setenv('GUVENILEN_PROXY', '10.0.0.5'); assert panel.sunucu_ayarlari()['trusted_proxy'] == '10.0.0.5'
    a['TRUST_PROXY'] = '0'; s = panel.sunucu_ayarlari()
    assert 'trusted_proxy' not in s and s['threads'] == 8 and s['max_request_body_size'] == 13 * 1024 * 1024
    from waitress.adjustments import Adjustments
    a['TRUST_PROXY'] = '1'; monkeypatch.delenv('GUVENILEN_PROXY')
    adj = Adjustments(**dict(panel.sunucu_ayarlari(), host='127.0.0.1', port=0))  # waitress parametre adları geçerli
    assert adj.trusted_proxy == '127.0.0.1' and adj.max_request_body_size == 13 * 1024 * 1024


# ---- 11. Excel çıktısı: satır üst sınırı, write_only biçimi korunur ----------------------------------------
def test_excel_satir_ust_siniri_ve_bicim(web, monkeypatch):
    c, a = web
    login(c)
    for i in range(3): seed(a, key='row:%d' % i, picture=False)
    monkeypatch.setattr(panel, 'CIKTI_SATIR_SINIRI', 2)
    r = c.get('/disa-aktar.xlsx?durum=hepsi')
    assert r.status_code == 400 and r.mimetype == 'text/html'
    html = r.get_data(as_text=True); assert 'en çok 2 kayıt' in html and 'Tarih aralığını daraltın' in html
    r = c.get('/disa-aktar.xlsx?durum=hepsi', headers=XHR); assert r.status_code == 400 and 'daraltın' in r.json['hata']
    r = c.get('/disa-aktar.xlsx?durum=hepsi&sayim=1', headers=XHR); assert r.status_code == 400 and r.json['adet'] == 3
    assert denetim_say(a, 'disa_aktar') == 0
    monkeypatch.setattr(panel, 'CIKTI_SATIR_SINIRI', 30000)
    r = c.get('/disa-aktar.xlsx?durum=hepsi'); assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data)); ws = wb['Kayıtlar']
    assert ws.max_row == 4 and len([x for x in ws[1]]) == 29 and ws[1][0].font.bold and ws[1][0].fill.fgColor.rgb.endswith('1F2937')
    assert ws.freeze_panes == 'A2' and ws.auto_filter.ref == 'A1:AC4' and ws.column_dimensions['A'].width >= 12
    ozet = list(wb['Proje özeti'].iter_rows(values_only=True)); assert ozet[0] == ('Proje', 'Kayıt', 'KT onaylı', 'KT bekleyen') and ozet[1] == ('OF', 3, 0, 3)
    assert denetim_say(a, 'disa_aktar') == 1
    assert panel._cikti_sinir_mesaji(123456).startswith('Seçime 123.456 kayıt uyuyor')


# ---- 12. Mutlak oturum süresi mesajı, eski kontrol klasörleri, ortam değişkenleri -------------------------
def test_mutlak_sure_mesaji_ve_eski_kontroller(web):
    c, a = web
    login(c)
    with c.session_transaction() as s: s['gz'] = int(time.time()) - 25 * 3600
    r = c.get('/kayitlar'); assert r.status_code == 302
    html = c.get('/giris').get_data(as_text=True); assert 'Oturum süreniz doldu' in html
    with c.session_transaction() as s: assert 'kad' not in s and s.get('dustu') == 1
    assert login(c).status_code == 302 and c.get('/').status_code == 200
    parent = Path(a['BOT_KLASOR']) / 'checks'; parent.mkdir()
    eski = parent / ('a' * 32); eski.mkdir(); (eski / 'owner.json').write_text('{}'); os.utime(eski, (time.time() - 90000, time.time() - 90000))
    yeni = parent / ('b' * 32); yeni.mkdir()
    assert panel.eski_kontrolleri_temizle() == 1 and not eski.exists() and yeni.exists()
    assert panel.eski_kontrolleri_temizle() == 0


def test_guvenilmeyen_host_400_verir(web, monkeypatch):
    c, a = web
    monkeypatch.setitem(panel.app.config, 'TRUSTED_HOSTS', ['panel.example.test', '127.0.0.1', 'localhost'])
    for yol in ('/giris', '/', '/saglik', '/olmayan'):
        r = c.get(yol, headers={'Host': 'evil.example'})
        assert r.status_code == 400 and 'tanımlı değil' in r.get_data(as_text=True), yol
        assert 'Set-Cookie' not in r.headers
    r = c.post('/giris', data={'kullanici': 'x', 'sifre': 'y'}, headers={'Host': 'evil.example:443'}); assert r.status_code == 400
    r = c.post('/kayit/1/kt', data={}, headers={'Host': 'evil.example', **XHR}); assert r.status_code == 400
    assert denetim_say(a, 'sunucu_hata') == 0
    assert c.get('/saglik', headers={'Host': '127.0.0.1:18080'}).status_code == 200
    assert c.get('/giris', headers={'Host': 'panel.example.test'}).status_code == 200
    assert c.get('/giris', headers={'Host': 'localhost:8080'}).status_code == 200
    login(c); assert c.get('/').status_code == 200  # güvenilen varsayılan host (localhost) ile oturum çalışır


def test_ortam_degiskenleri_fallback_host_ve_cerez(tmp_path):
    env = dict(os.environ, PANEL_VERI=str(tmp_path), SESSION_SECRET='a' * 64, SESSION_SECRET_ESKI='b' * 40 + ',' + 'c' * 32 + ',kisa',
               GUVENILEN_HOSTLAR='panel.example.test, 203.0.113.7', HTTPS='1', GYAZO_WORKER='0')
    kod = ('from app import panel; import json; print(json.dumps(dict(fb=panel.app.config.get("SECRET_KEY_FALLBACKS"), '
           'th=panel.app.config.get("TRUSTED_HOSTS"), ad=panel.app.config["SESSION_COOKIE_NAME"], sec=panel.app.config["SESSION_COOKIE_SECURE"])))')
    out = subprocess.run([sys.executable, '-c', kod], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    d = json.loads(out.stdout.strip().splitlines()[-1])
    assert d['fb'] == ['b' * 40, 'c' * 32] and d['th'] == ['panel.example.test', '203.0.113.7', '127.0.0.1', 'localhost']
    assert d['ad'] == '__Host-kanit_session' and d['sec'] is True
    env.pop('SESSION_SECRET_ESKI'); env.pop('GUVENILEN_HOSTLAR'); env['HTTPS'] = '0'
    out = subprocess.run([sys.executable, '-c', kod], cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120)
    d = json.loads(out.stdout.strip().splitlines()[-1])
    assert d['fb'] is None and d['th'] is None and d['ad'] == 'kanit_session'
