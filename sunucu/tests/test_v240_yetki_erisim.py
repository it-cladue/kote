# -*- coding: utf-8 -*-
"""2.4.0 (B1) — Sahip rolü, sahip kapıları, ilk sahip ataması, yazılı onaylar, IP izin listesi (panel + API, anahtar başına),
İşlem Geçmişi araması / IP sütunu / okunur ayrıntı / CSV, başlıktaki rol etiketi ve CLI komutları."""
import csv
import io
import ipaddress
import re
import sys

import pytest

from app import api_anahtarlari as aa, db, erisim, kullanicilar, yetki
from tests.test_web import web, token, login, csrf, seed  # noqa: F401

PW = 'Test-Password-123!'


def hesap(a, ad, rol):
    kullanicilar.ekle(a, ad, rol, PW); kullanicilar.guncelle(a, ad, sifre_degistir=0)


def satirlar(a, sql, par=()):
    c = db.baglan(a['DB'])
    try:
        return [dict(r) for r in c.execute(sql, par)]
    finally:
        c.close()


def kullanici(a, ad):
    return kullanicilar.bul(a, ad)


def sahip_yap(a, ad='testadmin'):
    kullanicilar.guncelle(a, ad, yetki='sahip')


def liste_yaz(a, tur, metin):
    c = db.baglan(a['DB'])
    try:
        return erisim.ayar_yaz(c, tur, metin, 'test')
    finally:
        c.close()


def adres(c, ip):
    c.environ_base['REMOTE_ADDR'] = ip
    return c


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    erisim._RED_SON.clear()
    for ad in ('IZINLI_IPLER', 'API_IZINLI_IPLER', 'ERISIM_LOOPBACK_SERBEST'):
        monkeypatch.delenv(ad, raising=False)
    from app import api
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    yield
    erisim._RED_SON.clear()


# ---------------------------------------------------------------- S1: rol ayrıştırma

def test_sahip_rolu_cozumleme_es_anlamlilar_ve_ozet():
    y = yetki.coz('sahip')
    assert y['admin'] and y['sahip'] and y['gecerli'] and yetki.izin(y, 'OF', 'sil')
    assert yetki.coz('admin')['admin'] and not yetki.coz('admin')['sahip']
    assert not yetki.coz('OF:oku')['sahip']
    for metin in ('sahip', 'Sahip', 'SAHİP', 'owner', 'OWNER', 'sistem sahibi', 'Sistem  Sahibi', 'SİSTEM SAHİBİ'):
        assert yetki.kanonikle(metin) == 'sahip', metin
    for metin in ('superadmin', 'Süperadmin', 'SÜPERADMİN', 'admin'):
        assert yetki.kanonikle(metin) == 'admin', metin
    assert yetki.ozet('sahip') == 'Sahip — her şey, süperadminleri ve API anahtarlarını yönetir'
    assert yetki.ozet('admin').startswith('Süperadmin')
    # Rol adları proje kodu olamaz (SAHIP:oku gibi bir metin sahip yetkisi vermez; fail-closed).
    assert not yetki.coz('SAHIP:oku')['gecerli'] and not yetki.coz('OWNER')['gecerli']
    assert yetki.rol_kodu('sahip') == 'sahip' and yetki.rol_kodu('admin') == 'superadmin' and yetki.rol_kodu('OF:oku') == 'proje'
    assert [yetki.rol_etiketi(yetki.coz(m)) for m in ('sahip', 'admin', 'OF:oku,kt;PA:oku', 'OF:oku,duzenle', 'OF:oku', '')] == \
        ['Sahip', 'Süperadmin', 'Takım lideri', 'Düzenleyici', 'Görüntüleyici', 'Görüntüleyici']
    from app import panel  # noqa: F401  (uçlar içe aktarılınca kaydolur)
    assert 'yonetim_api_anahtarlari' in yetki.SAHIP_GEREKLI_EYLEMLER and 'yonetim_erisim' in yetki.SAHIP_GEREKLI_EYLEMLER


def test_baslik_rol_etiketi_gercek_yetkiden(web):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'duzen', 'OF:oku,duzenle'); hesap(a, 'bakan', 'OF:oku')
    beklenen = {'testadmin': 'Süperadmin', 'lider': 'Takım lideri', 'duzen': 'Düzenleyici', 'bakan': 'Görüntüleyici'}
    for ad, etiket in beklenen.items():
        login(c, ad)
        html = c.get('/').data.decode()
        assert ('data-rol="%s"' % etiket) in html, ad
        assert 'data-rol="Admin"' not in html
        c.post('/cikis', data={'csrf': csrf(c)})
    sahip_yap(a); login(c)
    html = c.get('/').data.decode()
    assert 'data-rol="Sahip"' in html and 'href="/yonetim/api-anahtarlari"' in html and 'href="/yonetim/erisim"' in html


# ---------------------------------------------------------------- S1: sahip kapıları

def test_sahip_kapilari_admin_403_sahip_200(web):
    c, a = web
    hesap(a, 'ikinci', 'admin'); hesap(a, 'okur', 'OF:oku')
    login(c)
    html = c.get('/').data.decode()
    assert 'href="/yonetim/api-anahtarlari"' not in html and 'href="/yonetim/erisim"' not in html  # menüde görünmez
    assert c.get('/yonetim/api-anahtarlari').status_code == 403
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'x', 'kapsam': 'hepsi'}).status_code == 403
    assert c.get('/yonetim/erisim').status_code == 403
    assert c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '', 'api': ''}).status_code == 403
    ik = kullanici(a, 'ikinci'); ok = kullanici(a, 'okur')
    yasak = [
        dict(islem='ekle', ad='yeni.super', rol='superadmin', onay='yeni.super'),
        dict(islem='ekle', ad='yeni.sahip', rol='sahip', onay='yeni.sahip'),
        dict(islem='guncelle', ad='ikinci', expected_version=ik['hesap_surumu'], rol='admin', projeler=['OF'], aktif='1', onay='ikinci'),
        dict(islem='guncelle', ad='ikinci', expected_version=ik['hesap_surumu'], rol='superadmin', aktif='1', gorunen_ad='Yeni Ad'),
        dict(islem='sifre', ad='ikinci', expected_version=ik['hesap_surumu']),
        dict(islem='pasif', ad='ikinci', expected_version=ik['hesap_surumu'], onay='ikinci'),
        dict(islem='guncelle', ad='okur', expected_version=ok['hesap_surumu'], rol='superadmin', aktif='1', onay='okur'),
        dict(islem='yetki', ad='okur', expected_version=ok['hesap_surumu'], rol='sahip', onay='okur'),
    ]
    for veri in yasak:
        r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **veri})
        assert r.status_code == 403, veri
        assert 'yalnız sahip' in r.data.decode()
    assert kullanici(a, 'yeni.super') is None and kullanici(a, 'ikinci')['yetki'] == 'admin' and kullanici(a, 'ikinci')['aktif'] == 1
    assert kullanici(a, 'okur')['yetki'] == 'OF:oku,gorsel'
    # Süperadmin, proje kullanıcılarını yönetmeye devam eder (rol sınıfı değişmeden).
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'okur', 'expected_version': ok['hesap_surumu'],
                                              'rol': 'admin', 'projeler': ['OF'], 'eylemler_OF': ['kt'], 'aktif': '1'})
    assert r.status_code == 302 and kullanici(a, 'okur')['yetki'] == 'OF:oku,gorsel,kt'
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'proje.kisi', 'rol': 'admin', 'projeler': ['OF']}).status_code == 302
    for url in ('/yonetim/katalog', '/bot', '/denetim', '/disa-aktar', '/yonetim/katalog/kategori-temizligi'):
        assert c.get(url).status_code == 200, url
    # Süperadmin satırında düzenleme formu yok, açıklama var.
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'Süperadmin hesabını yalnız <b>sahip</b> düzenleyebilir' in html
    # Sahip olunca hepsi açılır.
    c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sahip_ata', 'ad': 'testadmin', 'onay': 'testadmin'})
    assert kullanici(a, 'testadmin')['yetki'] == 'sahip'
    assert c.get('/yonetim/api-anahtarlari').status_code == 200 and c.get('/yonetim/erisim').status_code == 200
    ik = kullanici(a, 'ikinci')
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'ikinci', 'expected_version': ik['hesap_surumu']}).status_code == 302
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'yeni.super', 'rol': 'superadmin', 'onay': 'yeni.super'}).status_code == 302
    assert kullanici(a, 'yeni.super')['yetki'] == 'admin'


def test_sahip_gerekli_kancasi_genisletilebilir(web):
    from app import panel
    c, a = web
    yetki.SAHIP_GEREKLI_EYLEMLER.add('bot_sayfasi')
    try:
        login(c)
        assert c.get('/bot').status_code == 403
        sahip_yap(a); login(c)
        assert c.get('/bot').status_code == 200
    finally:
        yetki.SAHIP_GEREKLI_EYLEMLER.discard('bot_sayfasi')
    assert callable(panel.sahip_gerekli)


def test_ilk_sahip_atamasi_bir_kez_ve_onayli(web):
    c, a = web
    hesap(a, 'ikinci', 'admin')
    login(c)
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'id="sahip-ata"' in html and 'Sahip hesabını belirleyin' in html
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sahip_ata', 'ad': 'testadmin', 'onay': 'yanlis'})
    assert r.status_code == 200 and 'Hata:' in r.data.decode() and kullanici(a, 'testadmin')['yetki'] == 'admin'
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sahip_ata', 'ad': 'testadmin', 'onay': 'TestAdmin '})
    assert r.status_code == 302 and kullanici(a, 'testadmin')['yetki'] == 'sahip'
    assert c.get('/').status_code == 200  # kendini atayan oturumda kalır
    assert 'id="sahip-ata"' not in c.get('/yonetim/kullanicilar').data.decode()
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='sahip_atama'")
    assert len(d) == 1 and d[0]['kullanici'] == 'testadmin' and '"sahip"' in d[0]['yeni'] and '"admin"' in d[0]['eski']
    # İkinci süperadmin artık atama yapamaz.
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ikinci')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sahip_ata', 'ad': 'ikinci', 'onay': 'ikinci'})
    assert r.status_code == 403 and kullanici(a, 'ikinci')['yetki'] == 'admin'
    with pytest.raises(ValueError):
        kullanicilar.sahip_ata(a, 'ikinci', 'test')


def test_son_sahip_korunur_ve_rol_degisince_oturum_duser(web):
    from app import panel
    c, a = web
    sahip_yap(a); hesap(a, 'okur', 'OF:oku')
    with pytest.raises(ValueError, match='Son sahip'):
        kullanicilar.guncelle(a, 'testadmin', yetki='admin')
    c2 = panel.app.test_client(); login(c2, 'okur')
    assert c2.get('/').status_code == 200
    login(c)
    ok = kullanici(a, 'okur')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'okur', 'expected_version': ok['hesap_surumu'],
                                              'rol': 'superadmin', 'aktif': '1', 'onay': 'okur'})
    assert r.status_code == 302 and kullanici(a, 'okur')['yetki'] == 'admin'
    r = c2.get('/')
    assert r.status_code == 302 and 'neden=oturum' in r.headers['Location']
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='kullanici_guncelle' AND anahtar='okur' ORDER BY id DESC LIMIT 1")[0]
    assert '"yetki"' in d['eski'] and '"admin"' in d['yeni']


# ---------------------------------------------------------------- S3: yazılı onaylar (sunucuda)

def test_tehlikeli_islemler_yazili_onay_ister(web):
    c, a = web
    sahip_yap(a); hesap(a, 'okur', 'OF:oku'); hesap(a, 'ikinci', 'admin')
    login(c)
    ok = kullanici(a, 'okur')
    temel = {'islem': 'guncelle', 'ad': 'okur', 'expected_version': ok['hesap_surumu'], 'rol': 'superadmin', 'aktif': '1'}
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **temel})
    assert r.status_code == 200 and 'yazılı onay' in r.data.decode() and kullanici(a, 'okur')['yetki'] == 'OF:oku,gorsel'
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **temel, 'onay': 'ikinci'}).data.decode().count('id="kullanici-mesaj"') == 1
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **temel, 'onay': 'okur'}).status_code == 302
    # Süperadmini pasife alma
    ik = kullanici(a, 'ikinci')
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'pasif', 'ad': 'ikinci', 'expected_version': ik['hesap_surumu']}).data.decode().count('id="kullanici-mesaj"') == 1
    assert kullanici(a, 'ikinci')['aktif'] == 1
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'pasif', 'ad': 'ikinci', 'expected_version': ik['hesap_surumu'], 'onay': 'ikinci'}).status_code == 302
    assert kullanici(a, 'ikinci')['aktif'] == 0
    # Formdan süperadmin düşürme (proje kullanıcısı yapma) da onay ister
    ok = kullanici(a, 'okur')
    geri = {'islem': 'guncelle', 'ad': 'okur', 'expected_version': ok['hesap_surumu'], 'rol': 'admin', 'projeler': ['OF'], 'aktif': '1'}
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **geri}).data.decode().count('id="kullanici-mesaj"') == 1
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), **geri, 'onay': 'okur'}).status_code == 302
    # Yeni süperadmin hesabı açmak da onay ister
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'ucuncu', 'rol': 'superadmin'}).data.decode().count('id="kullanici-mesaj"') == 1
    assert kullanici(a, 'ucuncu') is None
    # Proje kullanıcısını pasife almak onay istemez (eski davranış)
    ok = kullanici(a, 'okur')
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'pasif', 'ad': 'okur', 'expected_version': ok['hesap_surumu']}).status_code == 302
    # API anahtarı iptali: anahtar adı yazılmalı
    con = db.baglan(a['DB']); kid, _ = aa.olustur(con, 'Rapor sunucusu', '*', olusturan='testadmin'); con.close()
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'iptal', 'id': kid}).status_code == 400
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'iptal', 'id': kid, 'onay': 'Rapor'}).status_code == 400
    assert satirlar(a, 'SELECT iptal FROM api_anahtarlari WHERE id=?', (kid,))[0]['iptal'] == 0
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'iptal', 'id': kid, 'onay': 'rapor sunucusu'}).status_code == 302
    assert satirlar(a, 'SELECT iptal FROM api_anahtarlari WHERE id=?', (kid,))[0]['iptal'] == 1
    # Erişim listesini temizleme: kendi kullanıcı adı
    liste_yaz(a, 'api', '85.1.2.3')
    assert c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'temizle', 'tur': 'api', 'onay': 'x'}).status_code == 400
    assert erisim.ayar_oku(db.baglan(a['DB']), 'api')['metin'] == '85.1.2.3'
    assert c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '', 'api': ''}).status_code == 400  # boşaltma = temizleme
    assert c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'temizle', 'tur': 'api', 'onay': 'testadmin'}).status_code == 302
    assert erisim.ayar_oku(db.baglan(a['DB']), 'api')['aglar'] == []


# ---------------------------------------------------------------- S2: IP listesi

def test_liste_ayristirma_matrisi():
    aglar = erisim.liste_coz('85.105.12.34, 10.0.0.0/8;\n2001:db8::/32  # ofis\n::ffff:192.0.2.5\n85.105.12.34')
    assert [erisim.ag_metni(x) for x in aglar] == ['85.105.12.34', '10.0.0.0/8', '2001:db8::/32', '192.0.2.5']
    assert erisim.normalle('10.1.2.3/8') == '10.0.0.0/8'
    with pytest.raises(erisim.ListeHatasi, match='Geçersiz adres: 300.1.1.1'):
        erisim.liste_coz('300.1.1.1, 85.1.1.1')
    with pytest.raises(ValueError):
        erisim.normalle('ofis')
    for ip, beklenen in [('85.105.12.34', True), ('85.105.12.35', False), ('10.200.3.4', True), ('2001:db8:5::1', True),
                         ('2001:db9::1', False), ('::ffff:10.1.1.1', True), ('192.0.2.5', True), ('bozuk', False), ('', False)]:
        assert erisim.izinli_mi(ip, aglar) is beklenen, ip
    assert erisim.izinli_mi('1.2.3.4', []) is True and erisim.izinli_mi('bozuk', []) is True
    assert erisim.dongu_mu('127.0.0.1') and erisim.dongu_mu('::1') and not erisim.dongu_mu('85.1.1.1')


def test_panel_ip_engeli_giris_dahil_muafiyetler_ve_denetim(web, monkeypatch):
    c, a = web
    for ip in ('85.1.2.3', '10.9.9.9', '2001:db8::7', '1.1.1.1'):
        assert adres(c, ip).get('/giris').status_code == 200, ip  # liste boş: sınır yok
    liste_yaz(a, 'panel', '85.1.2.3\n10.0.0.0/8\n2001:db8::/32')
    for ip in ('85.1.2.3', '10.9.9.9', '2001:db8::7'):
        assert adres(c, ip).get('/giris').status_code == 200, ip
    r = adres(c, '1.1.1.1').get('/giris')
    assert r.status_code == 403 and 'Bu adresten erişim izinli değil (IP: 1.1.1.1)' in r.data.decode() and 'erisim-izin' in r.data.decode()
    assert adres(c, '1.1.1.1').post('/giris', data={'kullanici': 'testadmin', 'sifre': PW}).status_code == 403
    assert adres(c, '1.1.1.1').get('/kayitlar', headers={'Accept': 'application/json', 'X-Requested-With': 'fetch'}).status_code == 403
    assert adres(c, '1.1.1.1').get('/static/stil.css').status_code == 200  # statik dosyalar muaf
    assert adres(c, '1.1.1.1').get('/saglik').status_code == 403
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='erisim_red'")
    assert len(d) == 1 and d[0]['ip'] == '1.1.1.1' and d[0]['sonuc'] == 'uyari'  # dakikada IP başına bir satır
    assert adres(c, '1.1.1.2').get('/').status_code == 403
    assert len(satirlar(a, "SELECT * FROM denetim WHERE islem='erisim_red'")) == 2
    # Sunucunun kendisi (döngü adresi, X-Forwarded-For yok) muaf; ERISIM_LOOPBACK_SERBEST=0 iken yalnız /saglik açık.
    assert adres(c, '127.0.0.1').get('/giris').status_code == 200 and adres(c, '::1').get('/saglik').status_code == 200
    monkeypatch.setenv('ERISIM_LOOPBACK_SERBEST', '0')
    assert adres(c, '127.0.0.1').get('/giris').status_code == 403 and adres(c, '127.0.0.1').get('/saglik').status_code == 200
    monkeypatch.delenv('ERISIM_LOOPBACK_SERBEST')
    # İzinli adresten giriş ve gezinme çalışır.
    adres(c, '85.1.2.3'); assert login(c).status_code == 302 and c.get('/kayitlar').status_code == 200
    # Ortam değişkeni yedeği: veritabanında satır yokken IZINLI_IPLER geçerli; panelde boş kayıt onu geçersiz kılar.
    con = db.baglan(a['DB']); con.execute("DELETE FROM ayarlar WHERE anahtar='izinli_ipler'"); con.close()
    monkeypatch.setenv('IZINLI_IPLER', '203.0.113.0/24')
    assert adres(c, '203.0.113.9').get('/giris').status_code == 200 and adres(c, '85.1.2.3').get('/giris').status_code == 403
    liste_yaz(a, 'panel', '')
    assert adres(c, '85.1.2.3').get('/giris').status_code == 200


def test_trust_proxy_acik_kapali_x_forwarded_for(web):
    """TRUST_PROXY=0: waitress X-Forwarded-For'u uygulamaz, istek 127.0.0.1 görünür → muafiyet YOK, liste doluysa kapalı.
    TRUST_PROXY=1: waitress gerçek adresi REMOTE_ADDR'a yazar (aşağıda waitress ara katmanıyla birebir)."""
    from waitress.proxy_headers import proxy_headers_middleware
    from werkzeug.test import Client
    from app import panel
    c, a = web
    liste_yaz(a, 'panel', '85.1.2.3')
    # TRUST_PROXY=0 benzetimi: bağlantı nginx'ten (127.0.0.1), başlık var ama uygulanmıyor.
    r = adres(c, '127.0.0.1').get('/giris', headers={'X-Forwarded-For': '85.1.2.3'})
    assert r.status_code == 403 and 'IP: 127.0.0.1' in r.data.decode()
    # TRUST_PROXY=1: waitress'in kendi ara katmanı (sunucu_ayarlari() ile aynı parametreler).
    ayar = dict(trusted_proxy='127.0.0.1', trusted_proxy_count=1, trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'})
    istemci = Client(proxy_headers_middleware(panel.app, **ayar))
    assert istemci.get('/giris', headers={'X-Forwarded-For': '85.1.2.3'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}).status_code == 200
    assert istemci.get('/giris', headers={'X-Forwarded-For': '9.9.9.9'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}).status_code == 403
    # Güvenilmeyen kaynaktan sahte başlık yok sayılır (başlık temizlenir, gerçek bağlantı adresi kullanılır).
    assert istemci.get('/giris', headers={'X-Forwarded-For': '85.1.2.3'}, environ_base={'REMOTE_ADDR': '9.9.9.9'}).status_code == 403
    assert panel.sunucu_ayarlari().get('trusted_proxy') in (None, '127.0.0.1')
    # Ayar ekranı uyarısı: döngü + X-Forwarded-For → "TRUST_PROXY=1 gerekli"; panel listesi kaydedilemez.
    liste_yaz(a, 'panel', '')
    sahip_yap(a); adres(c, '127.0.0.1'); login(c)
    html = c.get('/yonetim/erisim', headers={'X-Forwarded-For': '85.1.2.3'}).data.decode()
    assert 'TRUST_PROXY=1 gerekli' in html and 'id="trust-proxy-uyari"' in html
    assert 'TRUST_PROXY=1 gerekli' not in c.get('/yonetim/erisim').data.decode()
    r = c.post('/yonetim/erisim', headers={'X-Forwarded-For': '85.1.2.3'}, data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '85.1.2.3', 'api': ''})
    assert r.status_code == 400 and 'TRUST_PROXY=1 gerekli' in r.data.decode()


def test_kendini_disarida_birakma_korumasi_ve_ayar_denetimi(web):
    c, a = web
    sahip_yap(a); adres(c, '85.1.2.3'); login(c)
    html = c.get('/yonetim/erisim').data.decode()
    assert 'Şu anki adresiniz' in html and '<code id="su-anki-ip">85.1.2.3</code>' in html and 'data-ip-ekle="85.1.2.3"' in html
    assert '85.0.0.0/8' in html and 'Cloudflare' in html
    r = c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '10.0.0.0/8', 'api': ''})
    assert r.status_code == 400 and 'Kendi adresimi dışarıda bırakmayı anlıyorum' in r.data.decode()
    assert erisim.ayar_oku(db.baglan(a['DB']), 'panel')['aglar'] == []
    r = c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '85.1.2.0/24, 10.0.0.0/8', 'api': '203.0.113.5'})
    assert r.status_code == 302 and c.get('/yonetim/erisim').status_code == 200
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='erisim_ayar' ORDER BY id")
    assert len(d) == 2 and d[0]['kullanici'] == 'testadmin' and d[0]['ip'] == '85.1.2.3' and '85.1.2.0/24' in d[0]['yeni'] and '"adresler": []' in d[0]['eski']
    # Geçersiz girdi kaydedilmez
    r = c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '85.1.2.0/24, ofis-ip', 'api': '203.0.113.5'})
    assert r.status_code == 400 and 'Geçersiz adres: ofis-ip' in r.data.decode()
    # Bilinçli olarak kendini dışarıda bırakma
    r = c.post('/yonetim/erisim', data={'csrf': csrf(c), 'islem': 'kaydet', 'panel': '10.0.0.0/8', 'api': '203.0.113.5', 'kendimi_disarida': '1'})
    assert r.status_code == 302
    assert c.get('/').status_code == 403
    # İşlem Geçmişi'nde okunur ayrıntı
    adres(c, '10.1.1.1')
    html = c.get('/denetim?islem=erisim_ayar').data.decode()
    assert 'Panel listesi: 85.1.2.0/24, 10.0.0.0/8 → 10.0.0.0/8' in html and '<summary>Ham</summary>' in html


def test_cli_erisim_izin_ve_rol_komutlari(web, monkeypatch, capsys):
    from app import cli
    c, a = web
    monkeypatch.setattr(cli, 'AYAR', a)
    hesap(a, 'okur', 'OF:oku')

    def calistir(*argv):
        monkeypatch.setattr(sys, 'argv', ['app.cli', *argv])
        cli.main()
        return capsys.readouterr().out

    liste_yaz(a, 'panel', '10.0.0.0/8')
    out = calistir('erisim-izin', '--goster')
    assert 'Panel listesi' in out and '10.0.0.0/8' in out and 'API listesi' in out
    out = calistir('erisim-izin', '--ekle', '85.1.2.3')
    assert 'EKLENDI' in out and erisim.ayar_oku(db.baglan(a['DB']), 'panel')['metin'] == '10.0.0.0/8\n85.1.2.3'
    with pytest.raises(SystemExit, match='Geçersiz adres'):
        calistir('erisim-izin', '--ekle', 'ofis')
    out = calistir('erisim-izin', '--temizle')
    assert out.count('TEMIZLENDI') == 2 and erisim.ayar_oku(db.baglan(a['DB']), 'panel')['aglar'] == []
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='erisim_ayar' AND kullanici='sunucu-cli'")[0]['n'] >= 2
    sahip_yap(a)  # son sahip kuralı: okur düşürülebilsin diye ikinci sahip
    out = calistir('kullanici-rol', 'okur', 'sahip')
    assert 'Rol güncellendi' in out and kullanici(a, 'okur')['yetki'] == 'sahip'
    calistir('kullanici-rol', 'okur', 'süperadmin'); assert kullanici(a, 'okur')['yetki'] == 'admin'
    calistir('kullanici-rol', 'okur', 'OF:oku,kt'); assert kullanici(a, 'okur')['yetki'] == 'OF:oku,gorsel,kt'
    with pytest.raises(SystemExit, match='bulunamadı'):
        calistir('kullanici-rol', 'yokboyle', 'sahip')
    monkeypatch.setenv('KANIT_TEST_PW', 'Baska-Parola-456!')
    out = calistir('admin-ekle', 'patron', '--sahip', '--password-env', 'KANIT_TEST_PW')
    assert 'Panel hesabı hazır' in out and kullanici(a, 'patron')['yetki'] == 'sahip' and kullanici(a, 'patron')['sifre_degistir'] == 0


# ---------------------------------------------------------------- S2: API

def test_api_genel_ve_anahtar_basina_ip_listesi(web):
    c, a = web
    con = db.baglan(a['DB'])
    _, k_sinirli = aa.olustur(con, 'Sınırlı', '*', olusturan='testadmin', izinli_ipler='85.1.2.3, 2001:db8::/32')
    kid_serbest, k_serbest = aa.olustur(con, 'Serbest', '*', olusturan='testadmin')
    con.close()
    B = lambda k: {'Authorization': 'Bearer ' + k}  # noqa: E731
    assert adres(c, '85.1.2.3').get('/api/v1/ozet', headers=B(k_sinirli)).status_code == 200
    assert adres(c, '2001:db8::5').get('/api/v1/ozet', headers=B(k_sinirli)).status_code == 200
    r = adres(c, '85.1.2.4').get('/api/v1/ozet', headers=B(k_sinirli))
    assert r.status_code == 403 and r.json['neden'] == 'ip_izinsiz' and r.json['ip'] == '85.1.2.4' and 'Set-Cookie' not in r.headers
    assert adres(c, '85.1.2.4').get('/api/v1/ozet', headers=B(k_serbest)).status_code == 200
    g = satirlar(a, "SELECT * FROM api_gunlugu WHERE durum=403")
    assert len(g) == 1 and g[0]['ip'] == '85.1.2.4'
    # Panel listesi API'yi etkilemez; genel API listesi her anahtardan (ve anahtarsız istekten) önce uygulanır.
    liste_yaz(a, 'panel', '10.0.0.0/8')
    assert adres(c, '85.1.2.4').get('/api/v1/ozet', headers=B(k_serbest)).status_code == 200
    liste_yaz(a, 'api', '85.1.2.0/24')
    assert adres(c, '85.1.2.4').get('/api/v1/ozet', headers=B(k_serbest)).status_code == 200
    r = adres(c, '9.9.9.9').get('/api/v1/ozet', headers=B(k_serbest))
    assert r.status_code == 403 and r.json['neden'] == 'ip_izinsiz'
    assert adres(c, '9.9.9.9').get('/api/v1/ozet').json['neden'] == 'ip_izinsiz'  # anahtar denemesine bile geçilmez
    assert len(satirlar(a, "SELECT * FROM denetim WHERE islem='erisim_red' AND ip='9.9.9.9'")) == 1
    # Sayfadan anahtar IP listesi düzenleme (sahip, panel listesindeki adresten)
    liste_yaz(a, 'panel', ''); sahip_yap(a); adres(c, '85.1.2.3'); login(c)
    html = c.get('/yonetim/api-anahtarlari').data.decode()
    assert 'İzinli IP: <span class="anahtar-ip-liste">85.1.2.3, 2001:db8::/32</span>' in html and 'name="izinli_ipler"' in html
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'ip', 'id': kid_serbest, 'izinli_ipler': 'yanlis'}).status_code == 400
    assert c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'ip', 'id': kid_serbest, 'izinli_ipler': '85.1.2.9'}).status_code == 302
    assert adres(c, '85.1.2.4').get('/api/v1/ozet', headers=B(k_serbest)).status_code == 403
    assert adres(c, '85.1.2.9').get('/api/v1/ozet', headers=B(k_serbest)).status_code == 200
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='api_anahtar_ip'")
    assert len(d) == 1 and '85.1.2.9' in d[0]['yeni']
    # Oluştururken IP listesi
    adres(c, '85.1.2.3')
    r = c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'Yeni', 'kapsam': 'hepsi', 'izinli_ipler': '198.51.100.0/24'})
    assert r.status_code == 200 and satirlar(a, "SELECT izinli_ipler FROM api_anahtarlari WHERE ad='Yeni'")[0]['izinli_ipler'] == '198.51.100.0/24'


def test_eski_veritabani_izinli_ipler_sutunu_eklenir(tmp_path):
    yol = str(tmp_path / 'eski.db')
    c = db.baglan(yol)
    c.execute('ALTER TABLE api_anahtarlari DROP COLUMN izinli_ipler')
    c.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_240_erisim'"); c.close()
    c = db.baglan(yol)
    assert 'izinli_ipler' in {r['name'] for r in c.execute('PRAGMA table_info(api_anahtarlari)')}
    c.close()


# ---------------------------------------------------------------- S4: İşlem Geçmişi

def test_denetim_arama_ip_okunur_ayrinti_ve_csv(web):
    c, a = web
    kid = seed(a)
    adres(c, '85.1.2.3'); login(c)
    d = c.get(f'/kayit/{kid}').json
    assert c.post(f'/kayit/{kid}/kt', data={'csrf': csrf(c), 'deger': '1', 'surum': d['surum']}).json['kt'] == 1
    hesap(a, 'okur', 'OF:oku')
    ok = kullanici(a, 'okur')
    c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'okur', 'expected_version': ok['hesap_surumu'],
                                          'rol': 'admin', 'projeler': ['OF'], 'eylemler_OF': ['kt'], 'aktif': '1'})
    con = db.baglan(a['DB'])
    db.denetim_yaz(con, 'kotu', 'yorum_ekle', proje='OF', anahtar='tg:1:2:3', aciklama='=HYPERLINK("http://x")', ip='9.9.9.9'); con.close()
    # Personel (kayıtlar tablosundan), kayıt no, IP ve açıklama ile arama
    html = c.get('/denetim?q=00123').data.decode()
    assert 'Onay: bekliyor → onaylı' in html and '<small title="Personel">00123</small>' in html
    assert 'Kayıt #%d' % kid in c.get('/denetim?q=%23' + str(kid)).data.decode()
    html = c.get('/denetim?q=85.1.2.3').data.decode()
    assert '<th>IP</th>' in html and '>85.1.2.3</a>' in html and 'Kullanıcı güncelleme' in html and '9.9.9.9' not in html
    assert 'HYPERLINK' in c.get('/denetim?q=HYPERLINK').data.decode()
    # Rol değişikliği okunur biçimde, ham değer "Ham" altında
    html = c.get('/denetim?islem=kullanici_guncelle').data.decode()
    assert 'Rol: OF: oku, gorsel → OF: oku, gorsel, kt' in html and '<summary>Ham</summary>' in html
    # Hızlı tarih düğmeleri ve CSV bağlantısı filtreyi taşır
    html = c.get('/denetim?q=00123').data.decode()
    for ad in ('Bugün', 'Son 7 gün', 'Son 30 gün', 'Bu ay'):
        assert ad in html
    assert 'href="/denetim.csv?q=00123"' in html
    r = c.get('/denetim.csv?q=HYPERLINK')
    assert r.status_code == 200 and r.mimetype == 'text/csv' and r.data.startswith('﻿'.encode())
    satir = list(csv.reader(io.StringIO(r.data.decode('utf-8-sig')), delimiter=';'))
    assert satir[0][:3] == ['Zaman', 'Kullanıcı', 'İşlem'] and satir[0][-1] == 'IP'
    assert len(satir) == 2 and satir[1][9].startswith("'=HYPERLINK") and satir[1][-1] == '9.9.9.9'
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='denetim_aktar'")[0]['n'] == 1
    # Yönetici olmayan kullanıcı IP sütununu ve IP aramasını görmez
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'okur')
    html = c.get('/denetim').data.decode()
    assert '<th>IP</th>' not in html and '85.1.2.3' not in html
    assert 'Onay: bekliyor → onaylı' not in c.get('/denetim?q=85.1.2.3').data.decode()
    satir = list(csv.reader(io.StringIO(c.get('/denetim.csv').data.decode('utf-8-sig')), delimiter=';'))
    assert satir[0][-1] != 'IP'


# ---------------------------------------------------------------- Tarayıcı (Node + Playwright yoksa atlanır)

TARAYICI_BETIK = __import__('pathlib').Path(__file__).with_name('yetki_erisim_tarayici.js')


def _playwright_var():
    import shutil
    import subprocess
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_sahip_onay_erisim_ve_denetim(web, tmp_path):
    import os
    import subprocess
    import threading
    from waitress.server import create_server
    from app import panel
    c, a = web
    hesap(a, 'okur', 'OF:oku')
    # Canlıdaki gibi: güvenilen vekil 127.0.0.1 (TRUST_PROXY=1); tarayıcının X-Forwarded-For başlığı gerçek adres sayılır.
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6, trusted_proxy='127.0.0.1', trusted_proxy_count=1,
                           trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto', 'x-forwarded-host'})
    threading.Thread(target=sunucu.run, daemon=True).start()
    klasor = os.getenv('KT_EKRAN_KLASORU') or str(tmp_path)
    try:
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, EKRAN_KLASORU=klasor)
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=180, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        try:
            sunucu.close()
        except Exception:
            pass


# ---------------------------------------------------------------- inceleme düzeltmeleri (2.4.0-B1)

def test_denetim_uzun_sayi_aramasi_500_vermez(web):
    """20+ haneli sayı SQLite INTEGER'a sığmaz: kayıt no koşulu atlanır, LIKE aramaları sürer (sayfa ve CSV 200)."""
    c, a = web
    login(c)
    for q in ('99999999999999999999', '#123456789012345678901234567890', '９９'):
        assert c.get('/denetim', query_string={'q': q}).status_code == 200, q
        assert c.get('/denetim.csv', query_string={'q': q}).status_code == 200, q


def test_saglik_nginx_uzerinden_dongu_xff_ile_muaf(web):
    """Sunucunun kendi nginx'i üzerinden /saglik (döngü + X-Forwarded-For: 127.0.0.1) liste doluyken de 200; başka uç 403."""
    c, a = web
    liste_yaz(a, 'panel', '85.1.1.1')
    r = adres(c, '127.0.0.1').get('/saglik', headers={'X-Forwarded-For': '127.0.0.1'})
    assert r.status_code == 200
    assert adres(c, '127.0.0.1').get('/giris', headers={'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    assert adres(c, '9.9.9.9').get('/saglik').status_code == 403


def _waitress_uygulamasi(panel):
    """Üretimdeki gibi waitress sunucusu kurulur (sunucu_ayarlari ile); istekler sunucunun sardığı uygulamaya gider."""
    from waitress.server import create_server
    srv = create_server(panel.app, host='127.0.0.1', port=0, **panel.sunucu_ayarlari())
    return srv, srv.application


def test_trust_proxy_kapali_gercek_waitress_ile_kapali_kalir(web):
    """TRUST_PROXY=0: waitress X-Forwarded-For'u silmemeli; panel döngü + XFF'i görüp muafiyet vermez (fail-closed) ve uyarır."""
    from werkzeug.test import Client
    from app import panel
    c, a = web
    a['TRUST_PROXY'] = '0'
    srv, uyg = _waitress_uygulamasi(panel)
    try:
        ist = Client(uyg)
        liste_yaz(a, 'panel', '10.0.0.0/8')
        ort = {'REMOTE_ADDR': '127.0.0.1'}
        assert ist.get('/giris', headers={'X-Forwarded-For': '9.9.9.9'}, environ_base=ort).status_code == 403
        assert ist.get('/giris', environ_base=ort).status_code == 200  # doğrudan yerel istek muaf
        assert ist.get('/saglik', headers={'X-Forwarded-For': '127.0.0.1'}, environ_base=ort).status_code == 200
    finally:
        srv.close()
    # TRUST_PROXY=1: gerçek adres uygulanır, güvenilmeyen kaynaktan başlık yok sayılır.
    a['TRUST_PROXY'] = '1'
    srv, uyg = _waitress_uygulamasi(panel)
    try:
        ist = Client(uyg)
        assert ist.get('/giris', headers={'X-Forwarded-For': '10.1.2.3'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}).status_code == 200
        assert ist.get('/giris', headers={'X-Forwarded-For': '9.9.9.9'}, environ_base={'REMOTE_ADDR': '127.0.0.1'}).status_code == 403
        assert ist.get('/giris', headers={'X-Forwarded-For': '10.1.2.3'}, environ_base={'REMOTE_ADDR': '9.9.9.9'}).status_code == 403
    finally:
        srv.close()


def test_api_anahtari_olusturma_hatasinda_form_korunur(web):
    c, a = web
    sahip_yap(a); login(c)
    r = c.post('/yonetim/api-anahtarlari', data={'csrf': csrf(c), 'islem': 'olustur', 'ad': 'Muhasebe', 'kapsam': 'hepsi',
                                                 'sql_izni': '1', 'izinli_ipler': 'bozuk-ip'})
    html = r.data.decode()
    assert r.status_code == 400 and 'Hata:' in html
    assert 'value="Muhasebe"' in html and '>bozuk-ip</textarea>' in html
    assert 'name="kapsam" value="hepsi" checked' in html and 'name="sql_izni" value="1" checked' in html


def test_erisim_red_onbellegi_ust_sinirli(web, monkeypatch):
    c, a = web
    monkeypatch.setattr(erisim, 'RED_EN_COK', 3)
    con = db.baglan(a['DB'])
    try:
        sonuc = [erisim.red_kaydet(con, '2001:db8::%x' % i, '/giris') for i in range(6)]
    finally:
        con.close()
    assert sonuc == [True, True, True, False, False, False] and len(erisim._RED_SON) == 3
