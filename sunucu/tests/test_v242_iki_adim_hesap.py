# -*- coding: utf-8 -*-
"""2.4.2 — Hesap başına iki adımlı doğrulama zorunluluğu (panel_kullanicilari.iki_adim_zorunlu: NULL = politikaya göre,
1 = zorunlu, 0 = zorunlu değil). Operatör isteği: yeni kullanıcı açılırken "2FA zorunlu" otomatik seçili olsun; zorunluluğu
hesap başına kaldırmak isteğe bağlı ve yalnız süperadmin/sahipte (herkesinkini kaldırabilir, başka kimse kaldıramaz).
Kapsam: geçiş (eski şema), etkin zorunluluk (hesap ayarı politikadan önce), Yeni kullanıcı formu (kutu varsayılan işaretli →
1, ilk girişte kurulum ister; işaretsiz → 0), hesap başına zorunluluk formu üç durum + denetim + izinler, Kullanıcılar sayfası
etiketleri ve 'Henüz kurmayan',
CLI 2fa-zorunlu / 2fa-durum sütunu, kullanicilar.ekle varsayılanı (None = politika), API ve /saglik. Tarayıcı senaryosu
tests/iki_adim_tarayici.js içindedir (test_v241_iki_adim.py çalıştırır; ekran görüntüleri /tmp/kanit-ekran/p242)."""
import json
import re
import sys

import pytest

from app import api_anahtarlari as aa, ayarlar, db, iki_adim, kullanicilar
from tests.test_web import web, token, login, csrf  # noqa: F401
from tests.test_v241_iki_adim import PW, hesap, satirlar, baglanti, ayar, sahip_yap, saat, kur, cikis  # noqa: F401

YENI_PW = 'Baska-Parola-789!'


def yeni_kullanici(c, ad, kutu=True, alan=True, rol='admin'):
    """Kullanıcılar → Yeni kullanıcı formu (OF projesi). kutu: 2FA kutusu işaretli (formun varsayılanı);
    alan=False: 2.4.2 öncesi / önbellekteki form gibi alan işareti de yok."""
    veri = {'csrf': csrf(c), 'islem': 'ekle', 'ad': ad, 'gorunen_ad': ad.title(), 'sifre': PW, 'rol': rol, 'projeler': 'OF'}
    if alan:
        veri['iki_adim_alan'] = '1'
    if kutu:
        veri['iki_adim_zorunlu'] = '1'
    return c.post('/yonetim/kullanicilar', data=veri)


def zorunluluk(c, a, ad, secim, surum=True):
    """Satırdaki "İki adımlı doğrulama zorunluluğu" formu (islem=iki_adim_zorunlu)."""
    veri = {'csrf': csrf(c), 'islem': 'iki_adim_zorunlu', 'ad': ad, 'iki_adim_zorunlu': secim}
    if surum:
        veri['expected_version'] = kullanicilar.bul(a, ad)['hesap_surumu']
    return c.post('/yonetim/kullanicilar', data=veri)


def satir_formu(html, ad):
    return html.split('id="duzenle-%s"' % ad)[1].split('</tr>')[0]


def ilk_giris(c, ad):
    """Geçici şifreyle giriş → /sifre → yeni şifre. Dönüş: sonraki '/' yanıtı."""
    assert login(c, ad).status_code == 302
    assert c.get('/').headers['Location'].endswith('/sifre')
    assert c.post('/sifre', data={'csrf': csrf(c), 'eski': PW, 'yeni': YENI_PW, 'yeni2': YENI_PW}).status_code == 302
    return c.get('/')


def bekleyenler(html):
    m = re.search(r'id="iki-adim-bekleyen">Henüz kurmayan: ([^<]*)<', html)
    return m.group(1).split(', ') if m else []


# ================================================================ T1: şema / geçiş

def test_gecis_eski_semada_sutun_eklenir_mevcutlar_null(tmp_path):
    yol = str(tmp_path / 'eski.db')
    c = db.baglan(yol)
    c.execute('ALTER TABLE panel_kullanicilari DROP COLUMN iki_adim_zorunlu')
    c.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_242_iki_adim_hesap'")
    c.execute("INSERT INTO panel_kullanicilari(kullanici_adi,sifre_hash,yetki) VALUES('eski','x','admin')"); c.close()
    c = db.baglan(yol)
    sutunlar = {r['name']: dict(r) for r in c.execute('PRAGMA table_info(panel_kullanicilari)')}
    assert 'iki_adim_zorunlu' in sutunlar and sutunlar['iki_adim_zorunlu']['dflt_value'] is None
    assert c.execute("SELECT iki_adim_zorunlu FROM panel_kullanicilari WHERE kullanici_adi='eski'").fetchone()[0] is None
    assert db.ayar_al(c, 'core_schema_242_iki_adim_hesap') == '1'
    c.close()
    c = db.baglan(yol)  # idempotent
    assert c.execute('SELECT COUNT(*) FROM panel_kullanicilari').fetchone()[0] == 1
    c.close()


def test_gecis_2_4_0_semasindan_iki_bayrak_birlikte(tmp_path):
    """2.4.1 sütunları da yokken (2.4.0 veritabanı) iki geçiş birlikte çalışır."""
    yol = str(tmp_path / 'eski240.db')
    c = db.baglan(yol)
    for sutun in ('iki_adim_acik', 'iki_adim_sir', 'iki_adim_son_sayac', 'iki_adim_tarih', 'iki_adim_zorunlu'):
        c.execute('ALTER TABLE panel_kullanicilari DROP COLUMN ' + sutun)
    c.execute('DROP TABLE iki_adim_kurtarma'); c.execute('DROP TABLE iki_adim_cihazlar')
    c.execute("DELETE FROM ayarlar WHERE anahtar IN ('core_schema_241_iki_adim','core_schema_242_iki_adim_hesap')")
    c.execute("INSERT INTO panel_kullanicilari(kullanici_adi,sifre_hash,yetki) VALUES('eski','x','OF:oku')"); c.close()
    c = db.baglan(yol)
    u = dict(c.execute("SELECT * FROM panel_kullanicilari WHERE kullanici_adi='eski'").fetchone())
    assert u['iki_adim_acik'] == 0 and u['iki_adim_zorunlu'] is None and iki_adim.hesap_ayari(u) == 'politika'
    c.close()


# ================================================================ T2: etkin zorunluluk

def test_zorunlu_mu_hesap_ayari_politikadan_once():
    for pol in ('kapali', 'yonetici', 'hepsi'):
        assert iki_adim.zorunlu_mu({'yetki': 'OF:oku', 'iki_adim_zorunlu': 1}, pol) is True
        assert iki_adim.zorunlu_mu({'yetki': 'admin', 'iki_adim_zorunlu': 0}, pol) is False
        assert iki_adim.zorunlu_mu({'yetki': 'OF:oku', 'iki_adim_zorunlu': None}, pol) is (pol == 'hepsi')
    assert iki_adim.zorunlu_mu({'yetki': 'admin'}, 'yonetici') is True  # sütunsuz eski satır: politika
    kurulu = {'yetki': 'OF:oku', 'iki_adim_zorunlu': 0, 'iki_adim_acik': 1, 'iki_adim_sir': 'X'}
    assert iki_adim.durum_etiketi(kurulu, 'hepsi') == 'acik'
    assert [iki_adim.hesap_ayari_degeri(x) for x in ('politika', '', '1', 'evet', '0', 'hayir')] == [None, None, 1, 1, 0, 0]
    with pytest.raises(ValueError):
        iki_adim.hesap_ayari_degeri('belki')


def test_ekle_varsayilani_politika_semantigini_korur(web):
    c, a = web
    hesap(a, 'cli_hesap', 'OF:oku')
    assert kullanicilar.bul(a, 'cli_hesap')['iki_adim_zorunlu'] is None
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    login(c, 'cli_hesap')
    assert c.get('/kayitlar').headers['Location'].endswith('/profil/iki-adim')
    for kotu in ('1', 2, 'evet'):
        with pytest.raises(ValueError):
            kullanicilar.ekle(a, 'kotu', 'OF:oku', PW, iki_adim_zorunlu=kotu)
    assert kullanicilar.bul(a, 'kotu') is None
    with pytest.raises(ValueError):
        kullanicilar.guncelle(a, 'cli_hesap', iki_adim_zorunlu='zorunlu')


# ================================================================ T3: Yeni kullanıcı formu

def test_yeni_kullanici_formu_kutu_isaretli_ve_metin(web):
    c, a = web
    login(c)
    html = c.get('/yonetim/kullanicilar').data.decode()
    kutu = re.search(r'<input type="checkbox" name="iki_adim_zorunlu"[^>]*>', html).group(0)
    assert 'checked' in kutu and 'value="1"' in kutu
    assert '<input type="hidden" name="iki_adim_alan" value="1">' in html
    assert 'İki adımlı doğrulama zorunlu (ilk girişte kurulum ister)' in html
    assert 'Kutu işaretli kalırsa kullanıcı ilk girişte Google Authenticator kurar; kaldırmak yalnız süperadmin ve sahibe açıktır.' in html
    assert 'yeni hesaplar varsayılan olarak zorunlu; hesap ayarı politikadan önce gelir' in html


def test_kutu_degeri_1_disinda_dolu_gelse_de_isaretli_sayilir(web):
    """Elle yapılmış bir formda kutu value="on" gönderirse de hesap zorunlu açılır; yalnız "0"/"hayir" ya da boş değer kaldırır."""
    c, a = web
    login(c)
    for ad, deger, beklenen in (('on.kisi', 'on', 1), ('evet.kisi', 'evet', 1), ('bos.kisi', '', 0), ('hayir.kisi', 'hayir', 0), ('sifir.kisi', '0', 0)):
        r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': ad, 'gorunen_ad': ad, 'sifre': PW, 'rol': 'admin',
                                                 'projeler': 'OF', 'iki_adim_alan': '1', 'iki_adim_zorunlu': deger})
        assert r.status_code == 302, (ad, r.data[:300])
        assert kullanicilar.bul(a, ad)['iki_adim_zorunlu'] == beklenen, (ad, deger)


@pytest.mark.parametrize('alan', [True, False], ids=['kutu-isaretli', 'alan-yok-eski-form'])
def test_varsayilan_form_zorunlu_kapali_politikada_ilk_giriste_kurulum(web, alan):
    c, a = web
    login(c)  # politika varsayılan: kapalı
    assert yeni_kullanici(c, 'yeni_kisi', kutu=alan, alan=alan).status_code == 302
    u = kullanicilar.bul(a, 'yeni_kisi')
    assert u['iki_adim_zorunlu'] == 1 and u['sifre_degistir'] == 1
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='kullanici_ekle' AND anahtar='yeni_kisi'")[0]
    assert d['kullanici'] == 'testadmin' and d['aciklama'] == '2FA zorunluluğu: zorunlu'
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert re.search(r'id="kullanici-yeni_kisi".*?data-iki-adim="zorunlu_bekliyor".*?data-iki-adim-hesap="zorunlu">hesap ayarı: zorunlu<', html, re.S)
    assert bekleyenler(html) == ['yeni_kisi']
    cikis(c)
    # İlk giriş: önce geçici şifre değişir, sonra yalnız kurulum sayfası açılır
    r = ilk_giris(c, 'yeni_kisi')
    assert r.status_code == 302 and r.headers['Location'].endswith('/profil/iki-adim')
    for yol in ('/kayitlar', '/yonetim/kullanicilar', '/sifre', '/arsiv'):
        r = c.get(yol)
        assert r.status_code == 302 and r.headers['Location'].endswith('/profil/iki-adim'), yol
    assert 'Yönetici kararıyla iki adımlı doğrulama hesabınız için zorunlu' in c.get('/profil/iki-adim').data.decode()


def test_kutu_kaldirilirsa_hepsi_politikasinda_da_zorlanmaz(web):
    c, a = web
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    kullanicilar.guncelle(a, 'testadmin', iki_adim_zorunlu=0)  # yönetici kendisi kurmadan sayfayı görebilsin
    login(c)
    assert yeni_kullanici(c, 'serbest', kutu=False).status_code == 302
    assert kullanicilar.bul(a, 'serbest')['iki_adim_zorunlu'] == 0
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='kullanici_ekle' AND anahtar='serbest'")[0]
    assert d['aciklama'] == '2FA zorunluluğu: zorunlu değil' and json.loads(d['yeni'])['iki_adim_zorunlu'] == 0
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert re.search(r'id="kullanici-serbest".*?data-iki-adim="yok".*?data-iki-adim-hesap="degil">hesap ayarı: zorunlu değil', html, re.S)
    assert 'serbest' not in bekleyenler(html)
    cikis(c)
    r = ilk_giris(c, 'serbest')
    assert r.status_code == 200 and 'id="ana-menu"' in r.data.decode()
    assert c.get('/kayitlar').status_code == 200
    assert c.get('/profil/iki-adim').status_code == 200  # isteyen kendisi kurabilir


# ================================================================ T4: hesap başına zorunluluk formu

def test_zorunluluk_uc_durum_denetim_ve_aninda_etki(web):
    c, a = web
    hesap(a, 'okur', 'OF:oku')
    login(c)
    sec = re.search(r'(<select name="iki_adim_zorunlu".*?</select>)', satir_formu(c.get('/yonetim/kullanicilar').data.decode(), 'okur'), re.S).group(1)
    assert re.search(r'<option value="politika" selected>Politikaya göre \(şu an: isteğe bağlı\)</option>', sec)
    assert '<option value="1" >Zorunlu</option>' in sec and '<option value="0" >Zorunlu değil</option>' in sec
    # okur açık oturumdayken zorunlu yapılır → bir sonraki istekte kurulum sayfası (oturum düşmez)
    okur = c.application.test_client()
    login(okur, 'okur')
    assert okur.get('/kayitlar').status_code == 200
    sv = kullanicilar.bul(a, 'okur')['session_version']
    assert zorunluluk(c, a, 'okur', '1').status_code == 302
    u = kullanicilar.bul(a, 'okur')
    assert u['iki_adim_zorunlu'] == 1 and u['session_version'] == sv
    r = okur.get('/kayitlar')
    assert r.status_code == 302 and r.headers['Location'].endswith('/profil/iki-adim')
    assert '<option value="1" selected>Zorunlu</option>' in satir_formu(c.get('/yonetim/kullanicilar').data.decode(), 'okur')
    # Zorunlu değil → kilit hemen kalkar
    assert zorunluluk(c, a, 'okur', '0').status_code == 302
    assert kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] == 0 and okur.get('/kayitlar').status_code == 200
    # Politikaya göre → NULL; 'hepsi' politikasında yine zorlanır
    assert zorunluluk(c, a, 'okur', 'politika').status_code == 302
    assert kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] is None
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    assert okur.get('/kayitlar').headers['Location'].endswith('/profil/iki-adim')
    aciklamalar = [d['aciklama'] for d in satirlar(a, "SELECT aciklama FROM denetim WHERE islem='kullanici_guncelle' "
                                                      "AND anahtar='okur' AND kullanici='testadmin' ORDER BY id")]
    assert aciklamalar == ['2FA zorunluluğu: politikaya göre → zorunlu', '2FA zorunluluğu: zorunlu → zorunlu değil',
                           '2FA zorunluluğu: zorunlu değil → politikaya göre']
    # Geçersiz değer ve eski sürüm reddedilir; Düzenle formu (islem=guncelle) bu alanı değiştirmez
    ayar(a, 'IKI_ADIM_ZORUNLU', 'kapali')
    kullanicilar.guncelle(a, 'okur', iki_adim_zorunlu=1)
    r = zorunluluk(c, a, 'okur', 'belki')
    assert r.status_code == 200 and 'geçersiz değer' in r.data.decode() and kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] == 1
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_zorunlu', 'ad': 'okur', 'iki_adim_zorunlu': '0', 'expected_version': '0'})
    assert 'başka bir admin' in r.data.decode() and kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] == 1
    u = kullanicilar.bul(a, 'okur')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'okur', 'expected_version': u['hesap_surumu'],
                                              'gorunen_ad': 'Okur Bey', 'aktif': '1', 'rol': 'admin', 'projeler': 'OF', 'iki_adim_zorunlu': '0'})
    assert r.status_code == 302
    u = kullanicilar.bul(a, 'okur')
    assert u['ad'] == 'Okur Bey' and u['iki_adim_zorunlu'] == 1


def test_zorunluluk_degisimi_kilidi_acmaz(web):
    """Yalnız zorunluluk değişince giriş kilidi / hatalı deneme sayacı olduğu gibi kalır (ayrı küçük form)."""
    c, a = web
    hesap(a, 'okur', 'OF:oku')
    con = baglanti(a)
    with db.transaction(con):
        con.execute("UPDATE panel_kullanicilari SET hatali_giris=3 WHERE kullanici_adi='okur'")
    con.close()
    login(c)
    assert zorunluluk(c, a, 'okur', '1').status_code == 302
    assert kullanicilar.bul(a, 'okur')['hatali_giris'] == 3
    assert not satirlar(a, "SELECT 1 FROM denetim WHERE islem='kilit_ac' AND anahtar='okur'")


def test_kurulu_hesapta_zorunlu_degil_2fa_kapatmaz(web, saat):
    c, a = web
    hesap(a, 'okur', 'OF:oku')
    login(c, 'okur'); kur(c, a, saat, 'okur'); cikis(c)
    login(c)
    assert zorunluluk(c, a, 'okur', '0').status_code == 302
    u = kullanicilar.bul(a, 'okur')
    assert u['iki_adim_acik'] == 1 and u['iki_adim_zorunlu'] == 0
    assert re.search(r'id="kullanici-okur".*?data-iki-adim="acik"', c.get('/yonetim/kullanicilar').data.decode(), re.S)


def test_superadmin_ve_sahip_herkesinkini_kaldirir(web, saat):
    c, a = web
    hesap(a, 'ikinci', 'admin'); hesap(a, 'sahip2', 'sahip'); hesap(a, 'okur', 'OF:oku')
    # testadmin süperadmin (sahip değil); kendi zorunluluğunu da kaldırabildiğini görmek için önce 2FA'yı kurar
    login(c); kur(c, a, saat, 'testadmin')
    for ad in ('testadmin', 'ikinci', 'sahip2', 'okur'):
        kullanicilar.guncelle(a, ad, iki_adim_zorunlu=1)
    html = c.get('/yonetim/kullanicilar').data.decode()
    # sahip ve diğer süperadmin satırları başka türlü düzenlenemez, ama zorunluluk formu her satırda var
    for ad in ('testadmin', 'ikinci', 'sahip2', 'okur'):
        assert 'name="islem" value="iki_adim_zorunlu"' in satir_formu(html, ad), ad
    assert 'yalnız <b>sahip</b> düzenleyebilir' in satir_formu(html, 'sahip2')
    # düzenlenemeyen satırda not, zorunluluk formunun aşağıda olduğunu söyler ve Kapat düğmesi formun altındadır
    sahip_satiri = satir_formu(html, 'sahip2')
    assert 'zorunluluğu aşağıdan değiştirilebilir' in sahip_satiri
    assert sahip_satiri.index('name="islem" value="iki_adim_zorunlu"') < sahip_satiri.index('>Kapat</button>')
    for ad in ('ikinci', 'sahip2', 'okur', 'testadmin'):  # başka süperadmin, sahip, proje kullanıcısı, kendisi
        assert zorunluluk(c, a, ad, '0').status_code == 302, ad
        assert kullanicilar.bul(a, ad)['iki_adim_zorunlu'] == 0, ad
    assert satirlar(a, "SELECT kullanici,aciklama FROM denetim WHERE islem='kullanici_guncelle' AND anahtar='sahip2' ORDER BY id")[-1] == \
        {'kullanici': 'testadmin', 'aciklama': '2FA zorunluluğu: zorunlu → zorunlu değil'}
    assert c.get('/kayitlar').status_code == 200  # kendi zorunluluğunu kaldırınca oturumda kalır
    cikis(c)
    # Sahip: süperadmin(ler)in ve kendi hesabının zorunluluğu
    login(c, 'sahip2')
    for ad in ('ikinci', 'testadmin', 'sahip2'):
        assert zorunluluk(c, a, ad, '1').status_code == 302 or ad == 'sahip2', ad
    # sahip2 kendini zorunlu yaptı ve kurmamış: bir sonraki istekte kurulum sayfası; kaldırmak için önce kurar
    assert c.get('/yonetim/kullanicilar').headers['Location'].endswith('/profil/iki-adim')
    kur(c, a, saat, 'sahip2')
    for ad in ('ikinci', 'testadmin', 'sahip2'):
        assert zorunluluk(c, a, ad, '0').status_code == 302, ad
        assert kullanicilar.bul(a, ad)['iki_adim_zorunlu'] == 0, ad
    assert satirlar(a, "SELECT kullanici,aciklama FROM denetim WHERE islem='kullanici_guncelle' AND anahtar='ikinci' ORDER BY id")[-1] == \
        {'kullanici': 'sahip2', 'aciklama': '2FA zorunluluğu: zorunlu → zorunlu değil'}


@pytest.mark.parametrize('rol', ['OF:oku', 'OF:oku,kt'])
def test_proje_yetkilisi_zorunlulugu_degistiremez(web, rol):
    c, a = web
    hesap(a, 'proje', rol); hesap(a, 'hedef', 'OF:oku')
    kullanicilar.guncelle(a, 'proje', iki_adim_zorunlu=0)  # kendisi zorunlu değil: kilide değil yetki denetimine takılsın
    kullanicilar.guncelle(a, 'hedef', iki_adim_zorunlu=1)
    login(c, 'proje')
    assert c.get('/yonetim/kullanicilar').status_code == 403
    for ad, secim in (('hedef', '0'), ('proje', '1'), ('testadmin', '1')):
        r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_zorunlu', 'ad': ad, 'iki_adim_zorunlu': secim})
        assert r.status_code == 403, ad
    assert [kullanicilar.bul(a, x)['iki_adim_zorunlu'] for x in ('hedef', 'proje', 'testadmin')] == [1, 0, None]


def test_kullanici_kendi_zorunlulugunu_kaldiramaz(web, saat):
    c, a = web
    hesap(a, 'okur', 'OF:oku')
    kullanicilar.guncelle(a, 'okur', islem_yapan='testadmin', iki_adim_zorunlu=1)
    login(c, 'okur')
    html = c.get('/profil/iki-adim').data.decode()
    assert 'name="iki_adim_zorunlu"' not in html
    for yol, veri in (('/profil/iki-adim', {'islem': 'zorunlu', 'iki_adim_zorunlu': '0'}),
                      ('/profil/iki-adim', {'islem': 'kapat', 'iki_adim_zorunlu': '0'}),
                      ('/sifre', {'eski': PW, 'yeni': YENI_PW, 'yeni2': YENI_PW, 'iki_adim_zorunlu': '0'})):
        veri['csrf'] = csrf(c)
        c.post(yol, data=veri)
        assert kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] == 1, yol
    assert c.get('/kayitlar').headers['Location'].endswith('/profil/iki-adim')
    # Kurduktan sonra da /sifre ve /profil/iki-adim zorunluluğu kaldırmaz; kapatma reddedilir
    kur(c, a, saat, 'okur')
    assert 'name="iki_adim_zorunlu"' not in c.get('/sifre').data.decode()
    c.post('/sifre', data={'csrf': csrf(c), 'eski': PW, 'yeni': YENI_PW, 'yeni2': YENI_PW, 'iki_adim_zorunlu': '0'})
    c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'iki_adim_zorunlu': '0'})
    u = kullanicilar.bul(a, 'okur')
    assert u['iki_adim_zorunlu'] == 1 and u['iki_adim_acik'] == 1
    assert len(satirlar(a, "SELECT 1 FROM denetim WHERE islem='kullanici_guncelle' AND anahtar='okur' AND aciklama LIKE '2FA%'")) == 1


# ================================================================ T5: Kullanıcılar sayfası

def test_henuz_kurmayan_ve_hesap_ayari_etiketleri(web):
    c, a = web
    hesap(a, 'pol', 'OF:oku'); hesap(a, 'zor', 'OF:oku'); hesap(a, 'degil', 'OF:oku'); hesap(a, 'pasif', 'OF:oku')
    kullanicilar.guncelle(a, 'zor', iki_adim_zorunlu=1); kullanicilar.guncelle(a, 'degil', iki_adim_zorunlu=0)
    kullanicilar.guncelle(a, 'pasif', iki_adim_zorunlu=1, aktif=0)
    kullanicilar.guncelle(a, 'testadmin', iki_adim_zorunlu=0); sahip_yap(a)  # sahip: Düzenle altındaki 2FA notunu da görür
    ayar(a, 'IKI_ADIM_ZORUNLU', 'yonetici')
    login(c)
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert bekleyenler(html) == ['zor']
    beklenen = {'pol': ('yok', 'politika'), 'zor': ('zorunlu_bekliyor', 'zorunlu'), 'degil': ('yok', 'degil'), 'testadmin': ('yok', 'degil')}
    for ad, (durum, hesap_ayari) in beklenen.items():
        hucre = re.search(r'id="kullanici-%s".*?(<td class="iki-adim-hucre".*?</td>)' % ad, html, re.S).group(1)
        telefon = re.search(r'id="kullanici-%s".*?(<span class="iki-adim-telefon".*?</td>)' % ad, html, re.S).group(1)
        for parca in (hucre, telefon):
            assert 'data-iki-adim-hesap="%s"' % hesap_ayari in parca and ('hesap ayarı:' in parca) is (hesap_ayari != 'politika'), ad
        assert 'data-iki-adim="%s"' % durum in hucre, ad
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert bekleyenler(html) == ['pol', 'zor']
    assert 'Hesap ayarı zorunlu kıldığı için' in html


# ================================================================ T6: CLI

def test_cli_2fa_zorunlu_ve_durum_sutunu(web, monkeypatch, capsys):
    from app import cli
    c, a = web
    monkeypatch.setattr(cli, 'AYAR', a)

    def calistir(*argv):
        monkeypatch.setattr(sys, 'argv', ['app.cli', *argv])
        cli.main()
        return capsys.readouterr().out
    hesap(a, 'okur', 'OF:oku')
    out = calistir('2fa-zorunlu', 'okur', 'evet')
    assert 'okur → zorunlu' in out and kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] == 1
    d = satirlar(a, "SELECT kullanici,aciklama FROM denetim WHERE islem='kullanici_guncelle' AND anahtar='okur' ORDER BY id")
    assert d[-1]['kullanici'] == 'sunucu-cli' and d[-1]['aciklama'] == '2FA zorunluluğu: politikaya göre → zorunlu'
    calistir('2fa-zorunlu', 'testadmin', 'hayir')
    out = calistir('2fa-durum')
    assert 'HESAP AYARI' in out and '2fa-zorunlu' in out
    assert re.search(r'okur\s+zorunlu-bekliyor\s+zorunlu\b', out) and re.search(r'testadmin\s+yok\s+zorunlu değil', out)
    veri = json.loads(calistir('2fa-durum', '--json'))
    assert {h['kullanici']: h['hesap_ayari'] for h in veri['hesaplar']} == {'okur': 'zorunlu', 'testadmin': 'zorunlu değil'}
    assert {h['kullanici']: h['hesap_ayari_kod'] for h in veri['hesaplar']} == {'okur': 'zorunlu', 'testadmin': 'degil'}
    calistir('2fa-zorunlu', 'okur', 'politika')
    assert kullanicilar.bul(a, 'okur')['iki_adim_zorunlu'] is None
    assert re.search(r'okur\s+yok\s+politikaya göre', calistir('2fa-durum'))
    with pytest.raises(SystemExit, match='bulunamadı'):
        calistir('2fa-zorunlu', 'yokboyle', 'evet')
    with pytest.raises(SystemExit):
        calistir('2fa-zorunlu', 'okur', 'belki')


# ================================================================ T7, API, sağlık

def test_ayar_yardim_metni_ve_api_saglik_etkilenmez(web):
    c, a = web
    yardim = ayarlar.SOZLUK['IKI_ADIM_ZORUNLU'].yardim
    assert '"Politikaya göre"' in yardim and 'varsayılan olarak zorunludur' in yardim and 'yalnız süperadmin ve sahibe açıktır' in yardim
    assert 'bu ayardan önce gelir' in yardim
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    kullanicilar.guncelle(a, 'testadmin', iki_adim_zorunlu=1)
    con = baglanti(a)
    _, anahtar = aa.olustur(con, 'Rapor', '*', olusturan='testadmin')
    con.close()
    r = c.get('/api/v1/ozet', headers={'Authorization': 'Bearer ' + anahtar})
    assert r.status_code == 200 and 'Set-Cookie' not in r.headers
    assert c.get('/saglik').status_code == 200
    r = login(c)
    assert r.status_code == 302 and c.get('/').headers['Location'].endswith('/profil/iki-adim')
