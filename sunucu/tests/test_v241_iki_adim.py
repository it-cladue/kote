# -*- coding: utf-8 -*-
"""2.4.1 — İki adımlı doğrulama (TOTP): RFC 4226/6238 vektörleri, base32, ±1 adım, tekrar reddi, kurtarma kodları, giriş akışı
(parola → kod → oturum), ön işaretin süresi ve tek kullanımı, kilit sayacı, güvenilen cihaz çerezi ve iptalleri, zorunlu kılma
politikası ve yönlendirme, sahip sıfırlama / cihaz iptali (yazılı onay + denetim), CLI, API'nin etkilenmemesi, Kullanıcılar
sütunu, Çalışma ayarları anahtarları, QR üreticisi ve tarayıcı senaryosu."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import api_anahtarlari as aa, ayarlar, db, iki_adim, kullanicilar, qr_svg
from tests.test_web import web, token, login, csrf  # noqa: F401

PW = 'Test-Password-123!'
CEREZ = 'kanit_cihaz'


def hesap(a, ad, rol):
    kullanicilar.ekle(a, ad, rol, PW); kullanicilar.guncelle(a, ad, sifre_degistir=0)


def satirlar(a, sql, par=()):
    c = db.baglan(a['DB'])
    try:
        return [dict(r) for r in c.execute(sql, par)]
    finally:
        c.close()


def baglanti(a):
    return db.baglan(a['DB'])


def ayar(a, ad, deger):
    c = baglanti(a)
    try:
        ayarlar.yaz(c, ad, deger, 'test')
    finally:
        c.close()


def sahip_yap(a, ad='testadmin'):
    kullanicilar.guncelle(a, ad, yetki='sahip')


@pytest.fixture
def saat(monkeypatch):
    """TOTP saatini test kontrol eder: her kod() çağrısı bir sonraki 30 saniyelik adımı üretir (tekrar reddine takılmaz)."""
    durum = {'t': 1_800_000_000.0}
    monkeypatch.setattr(iki_adim, '_saat', lambda: durum['t'])

    def kod(sir, ilerle=True):
        if ilerle:
            durum['t'] += iki_adim.ADIM_SN
        return iki_adim.totp(sir, durum['t'])
    kod.durum = durum
    return kod


def bekleyen_sir(a, ad):
    c = baglanti(a)
    try:
        return iki_adim.bekleyen_al(c, ad)
    finally:
        c.close()


def kur(c, a, saat, ad='testadmin', sifre=None):
    """Oturumu açık kullanıcı için kurulum: başlat → sayfadaki anahtar → kod → kurtarma kodları. Dönüş (sir, kodlar)."""
    veri = {'csrf': csrf(c), 'islem': 'baslat'}
    if sifre:
        veri['sifre'] = sifre
    r = c.post('/profil/iki-adim', data=veri)
    assert r.status_code == 302, r.data[:500]
    html = c.get('/profil/iki-adim').data.decode()
    sir = re.search(r'data-anahtar="([A-Z2-7]+)"', html).group(1)
    assert sir == bekleyen_sir(a, ad)
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'etkinlestir', 'kod': saat(sir)})
    assert r.status_code == 200
    kodlar = re.findall(r'<li><code>([a-z0-9]{5}-[a-z0-9]{5})</code></li>', r.data.decode())
    assert len(kodlar) == 8
    return sir, kodlar


def cikis(c):
    c.post('/cikis', data={'csrf': csrf(c)})


def parola_adimi(c, ad='testadmin', sonraki=None):
    yol = '/giris' + ('?sonraki=' + sonraki if sonraki else '')
    c.get('/giris')
    return c.post(yol, data={'csrf': csrf(c), 'kullanici': ad, 'sifre': PW})


def kod_adimi(c, kod, guven=False):
    veri = {'csrf': csrf(c), 'kod': kod}
    if guven:
        veri['guven'] = '1'
    return c.post('/giris/dogrulama', data=veri)


def oturum_var(c):
    with c.session_transaction() as s:
        return bool(s.get('kad'))


# ================================================================ T7: algoritma

def test_rfc4226_hotp_ve_rfc6238_totp_vektorleri():
    anahtar = b'12345678901234567890'
    # RFC 4226 Ek D
    beklenen = ['755224', '287082', '359152', '969429', '338314', '254676', '287922', '162583', '399871', '520489']
    assert [iki_adim.hotp(anahtar, i) for i in range(10)] == beklenen
    # RFC 6238 Ek B (SHA1, 8 hane)
    for t, kod in ((59, '94287082'), (1111111109, '07081804'), (1111111111, '14050471'), (1234567890, '89005924'),
                   (2000000000, '69279037'), (20000000000, '65353130')):
        assert iki_adim.totp(anahtar, t, hane=8) == kod, t
    # Aynı anahtar base32 ile (uygulamaların okuduğu biçim) aynı sonucu verir; 6 hane = 8 hanenin son 6'sı.
    b32 = 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ'
    assert iki_adim.sir_coz(b32) == anahtar and iki_adim.totp(b32, 59) == '287082'


def test_base32_anahtar_uretimi_cozumu_ve_gruplama():
    s1, s2 = iki_adim.sir_uret(), iki_adim.sir_uret()
    assert s1 != s2 and re.fullmatch(r'[A-Z2-7]{32}', s1) and len(iki_adim.sir_coz(s1)) == 20  # 160 bit
    # Elle girişte boşluk, tire, küçük harf ve dolgu hoş görülür
    assert iki_adim.sir_coz(' '.join(s1[i:i + 4] for i in range(0, 32, 4)).lower()) == iki_adim.sir_coz(s1)
    assert iki_adim.sir_coz('JBSWY3DPEHPK3PXP') == iki_adim.sir_coz('jbsw-y3dp ehpk 3pxp====')
    for bozuk in ('', '0189', 'ABC!'):
        with pytest.raises(ValueError):
            iki_adim.sir_coz(bozuk)
    assert iki_adim.sir_grupla('ABCDEFGHIJKL') == 'ABCD EFGH IJKL'


def test_kayma_penceresi_tekrar_reddi_ve_bicim():
    sir = iki_adim.sir_uret()
    t = 1_700_000_000
    c = iki_adim.sayac(t)
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t), 0, t) == c
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t - 30), 0, t) == c - 1   # 30 sn geride
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t + 30), 0, t) == c + 1   # 30 sn ileride
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t - 60), 0, t) is None    # pencere dışı
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t + 60), 0, t) is None
    # Tekrar: son kullanılan sayaç ve öncesi reddedilir
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t), c, t) is None
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t - 30), c, t) is None
    assert iki_adim.kod_dogrula(sir, iki_adim.totp(sir, t + 30), c, t) == c + 1
    kod = iki_adim.totp(sir, t)
    assert iki_adim.kod_dogrula(sir, kod[:3] + ' ' + kod[3:], 0, t) == c       # boşluklu yazım
    for bozuk in ('', '12345', '1234567', 'abcdef', None):
        assert iki_adim.kod_dogrula(sir, bozuk, 0, t) is None


def test_otpauth_uri_bicimi():
    uri = iki_adim.otpauth_uri('ali.veli', 'JBSWY3DPEHPK3PXP')
    assert uri == ('otpauth://totp/Kan%C4%B1t%20Paneli:ali.veli?secret=JBSWY3DPEHPK3PXP&issuer=Kan%C4%B1t%20Paneli'
                   '&digits=6&period=30&algorithm=SHA1')


def test_kurtarma_kodu_bicimi():
    kodlar = iki_adim.kurtarma_kodlari_uret()
    assert len(kodlar) == 8 and len(set(kodlar)) == 8 and all(re.fullmatch('[a-z2-9]{10}', k) for k in kodlar)
    assert not any(ch in ''.join(kodlar) for ch in '01ilo')
    g = iki_adim.kurtarma_goster(kodlar[0])
    assert g[5] == '-' and iki_adim.kurtarma_temizle(g.upper()) == kodlar[0] and iki_adim.kurtarma_bicimi_mi(g)


# ================================================================ QR

def test_qr_bilinen_vektorler():
    # ISO/IEC 18004 örneğiyle aynı bilinen vektör: "HELLO WORLD" 1-M veri kod sözcükleri → 10 hata düzeltme kod sözcüğü
    veri = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr_svg.reed_solomon(veri, 10) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
    # Biçim bilgisi tablosu (düzey M, maske 0..7) ve sürüm 7 bilgisi
    assert [format(qr_svg.bicim_bitleri(m), '015b') for m in range(8)] == [
        '101010000010010', '101000100100101', '101111001111100', '101101101001011',
        '100010111111001', '100000011001110', '100111110010111', '100101010100000']
    assert format(qr_svg.surum_bitleri(7), '018b') == '000111110010010100'
    assert format(qr_svg.surum_bitleri(10), '018b') == '001010010011010011'
    # Bayt kipi M kapasiteleri: sürüm 1 = 14, 7 = 122, 10 = 213 bayt
    assert qr_svg.surum_sec(14) == 1 and qr_svg.surum_sec(15) == 2
    assert qr_svg.surum_sec(122) == 7 and qr_svg.surum_sec(123) == 8 and qr_svg.surum_sec(213) == 10
    m = qr_svg.matris('otpauth://totp/x?secret=JBSWY3DPEHPK3PXP')
    n = len(m)
    assert n == 17 + 4 * qr_svg.surum_sec(len('otpauth://totp/x?secret=JBSWY3DPEHPK3PXP'))
    # Bulucu desenleri ve karanlık modül
    for y, x in ((0, 0), (0, n - 7), (n - 7, 0)):
        assert all(m[y][x + i] and m[y + 6][x + i] and m[y + i][x] and m[y + i][x + 6] for i in range(7))
        assert m[y + 3][x + 3] and not m[y + 1][x + 1]
    assert m[n - 8][8]
    svg = qr_svg.svg('deneme', baslik='QR <x>')
    assert svg.startswith('<svg') and '<path fill="#000" d="M' in svg and 'QR &lt;x&gt;' in svg
    with pytest.raises(ValueError):
        qr_svg.matris('x' * 1000)


def _arase_klasoru():
    for kok in ('/opt/node22', '/opt/node24', '/usr/lib', '/usr/local/lib', '/usr'):
        for yol in Path(kok).glob('**/qrcode-terminal/vendor/QRCode') if Path(kok).exists() else []:
            return str(yol)
    return None


@pytest.mark.skipif(not shutil.which('node'), reason='Node yok; bağımsız QR karşılaştırması atlandı')
def test_qr_bagimsiz_uygulamayla_birebir_ayni():
    """Kazuhiko Arase'nin MIT lisanslı QRCode for JavaScript uygulamasıyla (npm'in qrcode-terminal paketi içinde) aynı
    sürüm ve maskede modül modül aynı matris. Paket bulunamazsa atlanır."""
    klasor = _arase_klasoru()
    if not klasor:
        pytest.skip('qrcode-terminal/vendor/QRCode bulunamadı')
    metinler = ['A', 'HELLO WORLD', iki_adim.otpauth_uri('testadmin', 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP'),
                iki_adim.otpauth_uri('cok.uzun.bir_kullanici.adi.kirk.karakter', iki_adim.sir_uret()), 'z' * 60, 'x' * 150, 'y' * 200]
    isler = [[m, qr_svg.surum_sec(len(m)), mk] for m in metinler for mk in range(8)]
    r = subprocess.run(['node', str(Path(__file__).with_name('qr_karsilastir.js')), klasor], input=json.dumps(isler),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    for (m, s, mk), beklenen in zip(isler, json.loads(r.stdout)):
        bizim = [''.join('1' if v else '0' for v in sat) for sat in qr_svg.matris(m, maske=mk, surum=s)]
        assert bizim == beklenen, (s, mk, m[:30])
    assert {s for _, s, _ in isler} >= {1, 4, 8, 10}


# ================================================================ T1: kurulum

def test_kurulum_kod_dogrulaninca_yazilir_ve_kurtarma_kodlari_bir_kez(web, saat):
    c, a = web
    login(c)
    html = c.get('/profil/iki-adim').data.decode()
    assert 'İki adımlı doğrulamayı aç' in html and 'data-durum="kapali"' in html
    assert 'İki adımlı doğrulama: kapalı' in c.get('/').data.decode()  # başlık / menü
    assert c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'baslat'}).status_code == 302
    html = c.get('/profil/iki-adim').data.decode()
    sir = re.search(r'data-anahtar="([A-Z2-7]+)"', html).group(1)
    # QR (satır içi SVG), dokunulabilir bağlantı, 4'lü gruplu anahtar, sunucu saati, adımlar
    assert '<svg' in html and 'class="qr-svg"' in html and 'id="qr-kodu"' in html
    assert 'href="otpauth://totp/Kan%C4%B1t%20Paneli:testadmin?secret=' + sir + '&amp;issuer=Kan%C4%B1t%20Paneli&amp;digits=6&amp;period=30&amp;algorithm=SHA1"' in html
    assert iki_adim.sir_grupla(sir) in html and 'Sunucu saati' in html
    for adim in ('1. Uygulamayı kurun', '2. QR kodu okutun', '3. Kodu doğrulayın', '4. Kurtarma kodlarını saklayın'):
        assert adim in html
    # Anahtar doğrulanmadan hesaba yazılmaz; yanlış kod reddedilir
    u = kullanicilar.bul(a, 'testadmin')
    assert not u['iki_adim_acik'] and not u['iki_adim_sir']
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'etkinlestir', 'kod': '000000'})
    assert r.status_code == 400 and 'Kod doğrulanamadı' in r.data.decode()
    assert not kullanicilar.bul(a, 'testadmin')['iki_adim_acik']
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'etkinlestir', 'kod': saat(sir)})
    sayfa = r.data.decode()
    kodlar = re.findall(r'<li><code>([a-z0-9]{5}-[a-z0-9]{5})</code></li>', sayfa)
    assert r.status_code == 200 and len(kodlar) == 8 and 'bir daha gösterilmez' in sayfa and 'Kodları kopyala' in sayfa and 'Yazdır' in sayfa
    u = kullanicilar.bul(a, 'testadmin')
    assert u['iki_adim_acik'] == 1 and u['iki_adim_sir'] == sir and u['iki_adim_son_sayac'] == iki_adim.sayac(saat.durum['t'])
    # Kurtarma kodları karmalı saklanır; düz metin veritabanında yok
    k = satirlar(a, 'SELECT * FROM iki_adim_kurtarma WHERE kullanici_adi=?', ('testadmin',))
    assert len(k) == 8 and all(r['kod_hash'].startswith(('scrypt:', 'pbkdf2:')) for r in k)
    assert not any(x.replace('-', '') in json.dumps(k) for x in kodlar)
    # Yeniden açılan sayfada kodlar yok; bekleyen anahtar silindi; denetim
    html = c.get('/profil/iki-adim').data.decode()
    assert kodlar[0] not in html and 'data-durum="acik"' in html and 'Kullanılmamış kurtarma kodu: <b>8</b>' in html
    assert bekleyen_sir(a, 'testadmin') is None
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_ac' AND kullanici='testadmin'")[0]['n'] == 1
    assert 'İki adımlı doğrulama: açık' in c.get('/').data.decode() and '2FA: açık' in c.get('/').data.decode()
    # Yeniden kurulum parola ister ve yeni anahtar üretir
    assert c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'baslat', 'sifre': 'yanlis'}).status_code == 400
    yeni, _ = kur(c, a, saat, sifre=PW)
    assert yeni != sir and kullanicilar.bul(a, 'testadmin')['iki_adim_sir'] == yeni
    assert 'yeniden kuruldu' in satirlar(a, "SELECT aciklama FROM denetim WHERE islem='2fa_ac' ORDER BY id DESC LIMIT 1")[0]['aciklama']


def test_mevcut_hesaplar_kapali_baslar_ve_eski_veritabani_tasinir(tmp_path):
    yol = str(tmp_path / 'eski.db')
    c = db.baglan(yol)
    for sutun in ('iki_adim_acik', 'iki_adim_sir', 'iki_adim_son_sayac', 'iki_adim_tarih'):
        c.execute('ALTER TABLE panel_kullanicilari DROP COLUMN ' + sutun)
    c.execute('DROP TABLE iki_adim_kurtarma'); c.execute('DROP TABLE iki_adim_cihazlar')
    c.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_241_iki_adim'")
    c.execute("INSERT INTO panel_kullanicilari(kullanici_adi,sifre_hash,yetki) VALUES('eski','x','admin')"); c.close()
    c = db.baglan(yol)
    sutunlar = {r['name'] for r in c.execute('PRAGMA table_info(panel_kullanicilari)')}
    assert {'iki_adim_acik', 'iki_adim_sir', 'iki_adim_son_sayac', 'iki_adim_tarih'} <= sutunlar
    assert c.execute("SELECT iki_adim_acik FROM panel_kullanicilari WHERE kullanici_adi='eski'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM iki_adim_cihazlar").fetchone()[0] == 0
    assert db.ayar_al(c, 'core_schema_241_iki_adim') == '1'
    c.close()


# ================================================================ T2: giriş akışı

def test_giris_parola_sonra_kod_sonra_oturum(web, saat):
    c, a = web
    login(c); sir, _ = kur(c, a, saat); cikis(c)
    r = parola_adimi(c, sonraki='/kayitlar')
    assert r.status_code == 302 and r.headers['Location'].endswith('/giris/dogrulama')
    # Ön işaret tam oturum değil: panel içeriği açılmaz, JSON uçları 401
    assert not oturum_var(c)
    assert c.get('/').status_code == 302 and '/giris' in c.get('/').headers['Location']
    assert c.get('/kayitlar').status_code == 302
    assert c.get('/bildirim.json', headers={'X-Requested-With': 'XMLHttpRequest'}).status_code == 401
    html = c.get('/giris/dogrulama').data.decode()
    assert 'Doğrulama kodu' in html and 'name="kod"' in html and 'autocomplete="one-time-code"' in html and 'Bu cihazda 30 gün sorma' in html
    r = kod_adimi(c, '000000')
    assert r.status_code == 200 and 'Kod doğrulanamadı' in r.data.decode() and not oturum_var(c)
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_hata' AND kullanici='testadmin'")[0]['n'] == 1
    r = kod_adimi(c, saat(sir))
    assert r.status_code == 302 and r.headers['Location'].endswith('/kayitlar') and oturum_var(c)
    assert c.get('/').status_code == 200
    son = satirlar(a, "SELECT aciklama FROM denetim WHERE islem='giris' ORDER BY id DESC LIMIT 1")[0]
    assert son['aciklama'] == 'iki adımlı doğrulama: uygulama kodu'
    assert c.get_cookie(CEREZ) is None  # kutu işaretlenmedi: güvenilen cihaz çerezi yok
    # Aynı kod (aynı sayaç) ikinci girişte reddedilir
    cikis(c); parola_adimi(c)
    eski = iki_adim.totp(sir, saat.durum['t'])
    assert 'Kod doğrulanamadı' in kod_adimi(c, eski).data.decode()
    assert kod_adimi(c, saat(sir)).status_code == 302


def test_iki_adim_kapaliyken_giris_degismez(web):
    c, a = web
    r = login(c)
    assert r.status_code == 302 and r.headers['Location'].endswith('/') and oturum_var(c)
    assert c.get('/giris/dogrulama').status_code == 302  # işaret yok → ana sayfaya


def test_on_isaret_suresi_ve_tek_kullanim(web, saat):
    c, a = web
    login(c); sir, _ = kur(c, a, saat); cikis(c)
    parola_adimi(c)
    with c.session_transaction() as s:
        numara = s['ia']
    # Süre dolumu (5 dk): sunucudaki işaretin zamanı geri alınır
    con = baglanti(a)
    veri = json.loads(db.ayar_al(con, iki_adim.ON_ONEK + numara)); veri['zaman'] -= iki_adim.ON_GIRIS_SN + 1
    with db.transaction(con):
        db.ayar_yaz(con, iki_adim.ON_ONEK + numara, json.dumps(veri))
    con.close()
    r = kod_adimi(c, saat(sir))
    assert r.status_code == 302 and r.headers['Location'].endswith('/giris') and not oturum_var(c)
    assert 'süresi doldu' in c.get('/giris').data.decode()
    assert not satirlar(a, "SELECT * FROM ayarlar WHERE anahtar=?", (iki_adim.ON_ONEK + numara,))
    # Tek kullanım: başarılı doğrulamadan sonra eski işaretli çerez yeniden kullanılamaz
    parola_adimi(c)
    with c.session_transaction() as s:
        numara = s['ia']; eski_csrf = s['csrf']
    assert kod_adimi(c, saat(sir)).status_code == 302 and oturum_var(c)
    with c.session_transaction() as s:
        s.clear(); s['ia'] = numara; s['csrf'] = eski_csrf
    r = kod_adimi(c, saat(sir))
    assert r.status_code == 302 and r.headers['Location'].endswith('/giris') and not oturum_var(c)
    # Sahte / biçimsiz işaret
    with c.session_transaction() as s:
        s['ia'] = 'x' * 30
    assert kod_adimi(c, saat(sir)).status_code == 302 and not oturum_var(c)
    # Parola adımından sonra hesabın sürümü değişirse (ör. sahip sıfırladı) işaret geçersiz
    parola_adimi(c)
    kullanicilar.guncelle(a, 'testadmin', gorunen_ad='Yeni Ad')
    assert kod_adimi(c, saat(sir)).headers['Location'].endswith('/giris') and not oturum_var(c)


def test_hatali_kodlar_hesabi_kilitler(web, saat):
    c, a = web
    login(c); sir, _ = kur(c, a, saat); cikis(c)
    parola_adimi(c)
    for i in range(iki_adim.KOD_DENEME - 1):
        r = kod_adimi(c, '000000')
        assert r.status_code == 200 and 'Kalan deneme: %d' % (iki_adim.KOD_DENEME - 1 - i) in r.data.decode()
    r = kod_adimi(c, '000000')
    assert r.status_code == 429 and 'kilitlendi' in r.data.decode()
    u = kullanicilar.bul(a, 'testadmin')
    assert kullanicilar.kilitli_mi(u) and u['hatali_giris'] >= iki_adim.KOD_DENEME
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='giris_kilit' AND kullanici='testadmin'")[0]['n'] == 1
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_hata' AND kullanici='testadmin'")[0]['n'] == iki_adim.KOD_DENEME
    # Kilitliyken doğru parola da kod adımına geçmez (parola akışındaki genel mesaj)
    r = parola_adimi(c)
    assert r.status_code == 200 and kullanicilar.GENEL_HATA in r.data.decode() and not oturum_var(c)
    # Kilit kalkınca (süre doldu) doğru kodla girilir
    con = baglanti(a)
    with db.transaction(con):
        con.execute("UPDATE panel_kullanicilari SET kilit_bitis='2000-01-01 00:00:00'")
        con.execute("UPDATE denetim SET zaman='2000-01-01 00:00:00' WHERE islem='2fa_hata'")
    con.close()
    parola_adimi(c)
    assert kod_adimi(c, saat(sir)).status_code == 302 and oturum_var(c)


def test_kurtarma_kodu_tek_kullanim_ve_azalinca_uyari(web, saat):
    c, a = web
    login(c); sir, kodlar = kur(c, a, saat); cikis(c)
    parola_adimi(c)
    r = kod_adimi(c, kodlar[0].upper())  # büyük harf ve tire hoş görülür
    assert r.status_code == 302 and oturum_var(c)
    assert satirlar(a, "SELECT aciklama FROM denetim WHERE islem='giris' ORDER BY id DESC LIMIT 1")[0]['aciklama'] == 'iki adımlı doğrulama: kurtarma kodu'
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='2fa_kurtarma_kullanildi'")
    assert len(d) == 1 and '7 kod kaldı' in d[0]['aciklama']
    cikis(c); parola_adimi(c)
    assert 'Kod doğrulanamadı' in kod_adimi(c, kodlar[0]).data.decode()  # ikinci kez kullanılamaz
    for kod in kodlar[1:6]:
        assert kod_adimi(c, kod).status_code == 302
        cikis(c); parola_adimi(c)
    r = kod_adimi(c, kodlar[6], )
    assert r.status_code == 302
    html = c.get('/').data.decode()
    assert '1 kod kaldı' in html and 'yeni kurtarma kodları' in html
    html = c.get('/profil/iki-adim').data.decode()
    assert 'id="kurtarma-uyari"' in html and 'Kullanılmamış kurtarma kodu: <b>1</b>' in html
    # Yenileme parola ister; yeni 8 kod, eskiler geçersiz
    assert c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kurtarma_yenile', 'sifre': 'yanlis'}).status_code == 400
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kurtarma_yenile', 'sifre': PW})
    yeni = re.findall(r'<li><code>([a-z0-9]{5}-[a-z0-9]{5})</code></li>', r.data.decode())
    assert len(yeni) == 8 and satirlar(a, "SELECT COUNT(*) n FROM iki_adim_kurtarma WHERE kullanildi IS NULL")[0]['n'] == 8
    cikis(c); parola_adimi(c)
    assert 'Kod doğrulanamadı' in kod_adimi(c, kodlar[7]).data.decode()
    assert kod_adimi(c, yeni[0]).status_code == 302


# ================================================================ T3: güvenilen cihaz

def test_guvenilen_cihaz_cerezi_ve_iptalleri(web, saat):
    c, a = web
    login(c); sir, _ = kur(c, a, saat); cikis(c)
    parola_adimi(c)
    r = kod_adimi(c, saat(sir), guven=True)
    assert r.status_code == 302
    cerez = [h for h in r.headers.getlist('Set-Cookie') if h.startswith(CEREZ + '=')]
    assert len(cerez) == 1 and 'HttpOnly' in cerez[0] and 'Max-Age=%d' % (30 * 86400) in cerez[0] and 'SameSite=Lax' in cerez[0]
    belirtec = c.get_cookie(CEREZ).value
    d = satirlar(a, 'SELECT * FROM iki_adim_cihazlar')
    assert len(d) == 1 and d[0]['kullanici_adi'] == 'testadmin' and belirtec not in json.dumps(d)  # yalnız özet saklanır
    assert d[0]['bitis'][:10] > d[0]['olusturma'][:10]
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_cihaz_guven'")[0]['n'] == 1
    # Güvenilen cihaz: parola yeterli, kod adımı atlanır
    cikis(c)
    r = parola_adimi(c)
    assert r.status_code == 302 and r.headers['Location'].endswith('/') and oturum_var(c)
    assert 'güvenilen cihaz' in satirlar(a, "SELECT aciklama FROM denetim WHERE islem='giris' ORDER BY id DESC LIMIT 1")[0]['aciklama']
    # Sayfada listelenir ve kaldırılır → kod yeniden sorulur
    html = c.get('/profil/iki-adim').data.decode()
    assert 'data-cihaz="%d"' % d[0]['id'] in html and 'Güvenilen cihazlar' in html
    assert c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'cihaz_kaldir', 'id': d[0]['id']}).status_code == 302
    cikis(c)
    assert parola_adimi(c).headers['Location'].endswith('/giris/dogrulama')
    # Başka hesabın çerezi geçmez
    kod_adimi(c, saat(sir), guven=True); cikis(c)
    hesap(a, 'ikinci', 'OF:oku')
    con = baglanti(a)
    assert not iki_adim.cihaz_gecerli(con, 'ikinci', c.get_cookie(CEREZ).value)
    assert iki_adim.cihaz_gecerli(con, 'testadmin', c.get_cookie(CEREZ).value)
    con.close()
    # Parola değişikliği bütün cihazları iptal eder
    parola_adimi(c)
    assert oturum_var(c)
    r = c.post('/sifre', data={'csrf': csrf(c), 'eski': PW, 'yeni': 'Yepyeni-Parola-789!', 'yeni2': 'Yepyeni-Parola-789!'})
    assert r.status_code == 302 and not satirlar(a, 'SELECT * FROM iki_adim_cihazlar')
    assert 'parola değişti' in satirlar(a, "SELECT aciklama FROM denetim WHERE islem='2fa_cihaz_kaldir' ORDER BY id DESC LIMIT 1")[0]['aciklama']
    kullanicilar.guncelle(a, 'testadmin', sifre=PW, sifre_degistir=0)
    # Rol değişikliği de iptal eder
    cikis(c); parola_adimi(c); kod_adimi(c, saat(sir), guven=True)
    assert len(satirlar(a, 'SELECT * FROM iki_adim_cihazlar')) == 1
    sahip_yap(a)
    assert not satirlar(a, 'SELECT * FROM iki_adim_cihazlar')
    # Süre 0: kutu görünmez, cihaz eklenmez, mevcut çerez de atlatamaz
    cikis(c); parola_adimi(c); kod_adimi(c, saat(sir), guven=True); cikis(c)
    ayar(a, 'IKI_ADIM_GUVEN_GUN', '0')
    assert parola_adimi(c).headers['Location'].endswith('/giris/dogrulama')
    assert 'gün sorma' not in c.get('/giris/dogrulama').data.decode()
    n = len(satirlar(a, 'SELECT * FROM iki_adim_cihazlar'))
    kod_adimi(c, saat(sir), guven=True)
    assert len(satirlar(a, 'SELECT * FROM iki_adim_cihazlar')) == n
    # Süresi geçmiş cihaz da geçersiz
    ayar(a, 'IKI_ADIM_GUVEN_GUN', '7')
    con = baglanti(a)
    with db.transaction(con):
        con.execute("UPDATE iki_adim_cihazlar SET bitis='2000-01-01 00:00:00'")
    con.close()
    cikis(c)
    assert parola_adimi(c).headers['Location'].endswith('/giris/dogrulama')
    assert not satirlar(a, 'SELECT * FROM iki_adim_cihazlar')
    # Süre sonradan kısaltılınca önceden güvenilen cihazlar da yeni süreye uyar: 30 günlük cihaz 10 gün önce oluşturulmuş sayılır
    ayar(a, 'IKI_ADIM_GUVEN_GUN', '30')
    kod_adimi(c, saat(sir), guven=True); cikis(c)
    con = baglanti(a)
    with db.transaction(con):
        con.execute("UPDATE iki_adim_cihazlar SET olusturma=datetime('now','localtime','-10 days')")
    assert len(iki_adim.cihazlar(con, 'testadmin')) == 1 and iki_adim.cihazlar(con, 'testadmin')[0]['bitis'] > db.simdi()
    con.close()
    r = parola_adimi(c)                                      # 30 gün: cihaz hâlâ geçerli, kod sorulmaz
    assert not r.headers['Location'].endswith('/giris/dogrulama') and oturum_var(c)
    cikis(c)
    ayar(a, 'IKI_ADIM_GUVEN_GUN', '7')                       # 7 gün: 10 günlük cihaz listede görünmez ve kodu atlatamaz
    con = baglanti(a)
    assert iki_adim.cihazlar(con, 'testadmin') == []
    con.close()
    assert parola_adimi(c).headers['Location'].endswith('/giris/dogrulama') and not oturum_var(c)
    assert not satirlar(a, 'SELECT * FROM iki_adim_cihazlar')  # süresi dolan kayıt silindi
    ayar(a, 'IKI_ADIM_GUVEN_GUN', '30')                      # uzatma geçmiş kaydı geri getirmez
    assert parola_adimi(c).headers['Location'].endswith('/giris/dogrulama')


# ================================================================ kapatma

def test_kapatma_parola_ve_kod_ister(web, saat):
    c, a = web
    login(c); sir, kodlar = kur(c, a, saat)
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': 'yanlis', 'kod': saat(sir)})
    assert r.status_code == 400 and 'parolanız yanlış' in r.data.decode()
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': PW, 'kod': '000000'})
    assert r.status_code == 400 and kullanicilar.bul(a, 'testadmin')['iki_adim_acik'] == 1
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': PW, 'kod': kodlar[3]})  # kurtarma koduyla da
    assert r.status_code == 302
    u = kullanicilar.bul(a, 'testadmin')
    assert not u['iki_adim_acik'] and u['iki_adim_sir'] is None
    assert not satirlar(a, 'SELECT * FROM iki_adim_kurtarma') and not satirlar(a, 'SELECT * FROM iki_adim_cihazlar')
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_kapat'")[0]['n'] == 1
    cikis(c)
    assert login(c).headers['Location'].endswith('/')  # yalnız parola


def test_kapatmada_kod_deneme_siniri_ve_kilit(web, saat):
    """İnceleme bulgusu: 'kapat' yolunda da 5 dakikada 5 hatalı kod sınırı; kilitliyken doğru kod da reddedilir, 2FA açık kalır."""
    c, a = web
    login(c); sir, kodlar = kur(c, a, saat)
    for i in range(iki_adim.KOD_DENEME):
        r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': PW, 'kod': '000000'})
        assert r.status_code == 400
    assert 'kilitlendi' in r.data.decode()
    assert kullanicilar.kilitli_mi(kullanicilar.bul(a, 'testadmin'))
    for kod in (saat(sir), kodlar[0]):
        r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': PW, 'kod': kod})
        assert r.status_code == 400 and 'kilitlendi' in r.data.decode() and 'açık kaldı' in r.data.decode()
    assert kullanicilar.bul(a, 'testadmin')['iki_adim_acik'] == 1
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_hata'")[0]['n'] == iki_adim.KOD_DENEME
    assert satirlar(a, "SELECT COUNT(*) n FROM iki_adim_kurtarma WHERE kullanildi IS NULL")[0]['n'] == 8  # kurtarma kodu harcanmadı
    assert not satirlar(a, "SELECT * FROM denetim WHERE islem='2fa_kapat'")


def test_paralel_kod_denemeleri_siniri_asamaz(web, saat):
    """İnceleme bulgusu: aynı ön işaretle aynı anda gönderilen 40 hatalı kod; kilit + sayım + kod denetimi tek işlemde
    olduğundan en çok KOD_DENEME deneme işlenir, gerisi 429 alır."""
    import threading
    from app import panel
    c, a = web
    login(c); kur(c, a, saat); cikis(c)
    parola_adimi(c)
    cerez = c.get_cookie(panel.app.config.get('SESSION_COOKIE_NAME') or 'session')
    assert cerez is not None
    belirtec = csrf(c); sonuc = []; engel = threading.Barrier(40)

    def dene():
        cl = panel.app.test_client(); cl.set_cookie(cerez.key, cerez.value)
        engel.wait()
        sonuc.append(cl.post('/giris/dogrulama', data={'csrf': belirtec, 'kod': '000000'}).status_code)
    isler = [threading.Thread(target=dene) for _ in range(40)]
    [t.start() for t in isler]; [t.join() for t in isler]
    assert len(sonuc) == 40
    n = satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_hata' AND kullanici='testadmin'")[0]['n']
    assert n == iki_adim.KOD_DENEME, (n, sorted(sonuc))
    assert sonuc.count(429) >= 40 - iki_adim.KOD_DENEME and kullanicilar.kilitli_mi(kullanicilar.bul(a, 'testadmin'))


def test_kod_dene_ip_siniri_tek_islemde(web, saat):
    c, a = web
    login(c); sir, _ = kur(c, a, saat); cikis(c)
    con = baglanti(a)
    with db.transaction(con):
        for _ in range(20):
            db.denetim_yaz(con, 'baskasi', 'giris_hata', ip='10.0.0.9')
    assert iki_adim.kod_dene(con, 'testadmin', saat(sir), ip='10.0.0.9', ip_sinir=20) == 'ip_sinir'
    assert iki_adim.kod_dene(con, 'testadmin', saat(sir), ip='10.0.0.8', ip_sinir=20) == 'totp'
    con.close()


def test_kurtarma_kodlari_sayfasi_yeniden_gonderilince_yaniltmaz(web, saat):
    """İnceleme bulgusu: kodlar sayfası yenilenip form yeniden gönderilince 400 'Kurulum süresi doldu' yerine bilgi + yönlendirme."""
    c, a = web
    login(c); sir, _ = kur(c, a, saat)
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'etkinlestir', 'kod': saat(sir)})
    assert r.status_code == 302 and r.headers['Location'].endswith('/profil/iki-adim')
    html = c.get('/profil/iki-adim').data.decode()
    assert 'zaten açık; kurtarma kodları yalnız bir kez gösterilir' in html and 'Kurulum süresi doldu' not in html
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='2fa_ac'")[0]['n'] == 1


def test_kod_alanlari_harf_klavyesi_acar(web, saat):
    """Kurtarma kodu harf içerir: telefonda rakam klavyesi açılmamalı (giriş adımı ve kapatma formu)."""
    c, a = web
    login(c); kur(c, a, saat)
    sayfa = c.get('/profil/iki-adim').data.decode()
    kapat = re.search(r'<input name="kod"[^>]*>', sayfa).group(0)
    assert 'inputmode="text"' in kapat and 'autocapitalize="off"' in kapat
    cikis(c); parola_adimi(c)
    alan = re.search(r'<input id="dogrulama-kodu"[^>]*>', c.get('/giris/dogrulama').data.decode()).group(0)
    assert 'inputmode="text"' in alan and 'autocomplete="one-time-code"' in alan and 'numeric' not in alan


def test_kullanicilar_telefon_2fa_rozeti(web, saat):
    c, a = web
    sahip_yap(a); hesap(a, 'okur', 'OF:oku'); ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    login(c); kur(c, a, saat)
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert re.search(r'id="kullanici-okur".*?data-iki-adim-telefon="zorunlu_bekliyor">2FA: <span[^>]*>zorunlu, bekliyor', html, re.S)
    assert re.search(r'id="kullanici-testadmin".*?data-iki-adim-telefon="acik">2FA: <span[^>]*>açık', html, re.S)
    css = (Path(__file__).resolve().parents[1] / 'app' / 'static' / 'stil.css').read_text(encoding='utf-8')
    assert '.kullanici-listesi .tablo .iki-adim-hucre' in css and '.iki-adim-telefon { display: none; }' in css


# ================================================================ T4: politika

def test_politika_kipleri_ve_yonlendirme(web, saat):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'bakan', 'OF:oku'); hesap(a, 'gecici', 'OF:oku')
    kullanicilar.guncelle(a, 'gecici', sifre_degistir=1)
    yonetici = {'testadmin': True, 'lider': True, 'bakan': False}
    for ad, beklenen in yonetici.items():
        assert iki_adim.zorunlu_mu(kullanicilar.bul(a, ad), 'yonetici') is beklenen
        assert iki_adim.zorunlu_mu(kullanicilar.bul(a, ad), 'hepsi') and not iki_adim.zorunlu_mu(kullanicilar.bul(a, ad), 'kapali')
    # Varsayılan kapalı: kimse yönlendirilmez
    login(c, 'lider'); assert c.get('/kayitlar').status_code == 200; cikis(c)
    ayar(a, 'IKI_ADIM_ZORUNLU', 'yonetici')
    login(c, 'bakan'); assert c.get('/kayitlar').status_code == 200; cikis(c)
    login(c, 'lider')
    r = c.get('/kayitlar')
    assert r.status_code == 302 and r.headers['Location'].endswith('/profil/iki-adim')
    r = c.get('/bildirim.json', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 403 and r.json['iki_adim'] == '/profil/iki-adim'
    html = c.get('/profil/iki-adim').data.decode()
    assert 'Yönetici kararıyla iki adımlı doğrulama hesabınız için zorunlu' in html and 'id="ana-menu"' not in html and 'ust-kilit' in html
    assert 'Çıkış' in html
    # Kurulunca serbest; kapatma reddedilir
    sir, kodlar = kur(c, a, saat, 'lider')
    assert c.get('/kayitlar').status_code == 200
    r = c.post('/profil/iki-adim', data={'csrf': csrf(c), 'islem': 'kapat', 'sifre': PW, 'kod': saat(sir)})
    assert r.status_code == 400 and 'zorunlu' in r.data.decode() and kullanicilar.bul(a, 'lider')['iki_adim_acik'] == 1
    assert c.post('/cikis', data={'csrf': csrf(c)}).status_code == 302
    # 'hepsi': görüntüleyici de yönlendirilir; geçici şifreli hesap önce şifresini değiştirir
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    login(c, 'bakan'); assert c.get('/').headers['Location'].endswith('/profil/iki-adim'); cikis(c)
    login(c, 'gecici')
    assert c.get('/').headers['Location'].endswith('/sifre')
    c.post('/sifre', data={'csrf': csrf(c), 'eski': PW, 'yeni': 'Baska-Parola-789!', 'yeni2': 'Baska-Parola-789!'})
    assert c.get('/').headers['Location'].endswith('/profil/iki-adim')
    # Kurulum bekleyen hesap /sifre'yi de açamaz ("kurulum bitene kadar başka hiçbir şey")
    assert c.get('/sifre').headers['Location'].endswith('/profil/iki-adim')
    cikis(c)
    # Sahip de kendini dışarıda bırakamaz: kurulum sayfası her zaman açık
    sahip_yap(a); login(c)
    assert c.get('/yonetim/ayarlar').headers['Location'].endswith('/profil/iki-adim')
    assert c.get('/profil/iki-adim').status_code == 200
    assert c.get('/saglik').status_code == 200


def test_calisma_ayarlari_anahtarlari(web):
    c, a = web
    assert 'Güvenlik' in ayarlar.GRUPLAR
    z, gun = ayarlar.SOZLUK['IKI_ADIM_ZORUNLU'], ayarlar.SOZLUK['IKI_ADIM_GUVEN_GUN']
    assert z.varsayilan == 'kapali' and [k for k, _ in z.secenekler] == ['kapali', 'yonetici', 'hepsi']
    assert gun.varsayilan == '30' and gun.en_az == 0 and gun.en_cok == 365
    for ham, beklenen in (('Hepsi', 'hepsi'), ('yonetici', 'yonetici')):
        assert ayarlar.dogrula('IKI_ADIM_ZORUNLU', ham) == beklenen
    for kotu in ('evet', ''):
        with pytest.raises(ValueError):
            ayarlar.dogrula('IKI_ADIM_ZORUNLU', kotu)
    with pytest.raises(ValueError):
        ayarlar.dogrula('IKI_ADIM_GUVEN_GUN', '400')
    assert ayarlar.okuyucu_degeri('IKI_ADIM_ZORUNLU', 'saçma') == ('kapali', 'varsayilan')
    assert ayarlar.okuyucu_degeri('IKI_ADIM_ZORUNLU', 'hepsi') == ('hepsi', 'aynen')
    assert ayarlar.okuyucu_degeri('ONAYSIZ_GORUNUM', 'gizle') == ('gizle', 'aynen')
    con = baglanti(a)
    assert iki_adim.politika(con) == 'kapali' and iki_adim.guven_gun(con) == 30
    con.close()
    sahip_yap(a); login(c)
    html = c.get('/yonetim/ayarlar').data.decode()
    assert 'id="ayar-IKI_ADIM_ZORUNLU"' in html and 'id="ayar-IKI_ADIM_GUVEN_GUN"' in html and '>Güvenlik<' in html
    assert 'Yöneticiler (sahip, süperadmin, onay yetkilileri)' in html and '0 = kapalı' in html
    r = c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'IKI_ADIM_GUVEN_GUN', 'islem': 'kaydet', 'deger': '14'})
    assert r.status_code == 302
    con = baglanti(a)
    assert iki_adim.guven_gun(con) == 14
    con.close()
    assert satirlar(a, "SELECT COUNT(*) n FROM denetim WHERE islem='ayar_degistir' AND hedef_id='IKI_ADIM_GUVEN_GUN'")[0]['n'] == 1


# ================================================================ T4: sahip işlemleri ve Kullanıcılar sayfası

def test_kullanicilar_sutunu_ve_sahip_sifirlama(web, saat):
    c, a = web
    hesap(a, 'ikinci', 'admin'); hesap(a, 'okur', 'OF:oku')
    # okur kurar ve bir cihaza güvenir
    login(c, 'okur'); sir, _ = kur(c, a, saat, 'okur'); cikis(c)
    parola_adimi(c, 'okur'); kod_adimi(c, saat(sir), guven=True); cikis(c)
    ayar(a, 'IKI_ADIM_ZORUNLU', 'yonetici')
    # Süperadmin (sahip değil): sütunu görür, sıfırlayamaz
    login(c, 'ikinci')
    kur(c, a, saat, 'ikinci')
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert '<th class="iki-adim-baslik">2FA</th>' in html
    assert re.search(r'id="kullanici-okur".*?data-iki-adim="acik"', html, re.S)
    assert re.search(r'id="kullanici-testadmin".*?data-iki-adim="zorunlu_bekliyor"', html, re.S)
    assert 'zorunlu, bekliyor' in html and 'Henüz kurmayan: testadmin' in html and 'data-iki-adim-sifirla><input' not in html
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_sifirla', 'ad': 'okur', 'onay': 'okur'})
    assert r.status_code == 403 and kullanicilar.bul(a, 'okur')['iki_adim_acik'] == 1
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_cihazlar', 'ad': 'okur'}).status_code == 403
    cikis(c)
    # Sahip: önce kendisi kurmalı (politika), sonra sıfırlar
    sahip_yap(a); login(c)
    assert c.get('/yonetim/kullanicilar').headers['Location'].endswith('/profil/iki-adim')
    kur(c, a, saat)
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'data-iki-adim-sifirla><input' in html and 'Güvenilen cihazları iptal et (1)' in html and '1 güvenilen cihaz' in html
    # Cihaz iptali
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_cihazlar', 'ad': 'okur'})
    assert r.status_code == 302 and not satirlar(a, "SELECT * FROM iki_adim_cihazlar WHERE kullanici_adi='okur'")
    assert 'sahip iptal etti' in satirlar(a, "SELECT aciklama FROM denetim WHERE islem='2fa_cihaz_kaldir' AND kullanici='testadmin'")[0]['aciklama']
    # Sıfırlama yazılı onay ister
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_sifirla', 'ad': 'okur', 'onay': 'yanlis'})
    assert r.status_code == 200 and 'yazılı onay ister' in r.data.decode() and kullanicilar.bul(a, 'okur')['iki_adim_acik'] == 1
    sv = kullanicilar.bul(a, 'okur')['session_version']
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'iki_adim_sifirla', 'ad': 'okur', 'onay': ' OKUR '})
    assert r.status_code == 302
    u = kullanicilar.bul(a, 'okur')
    assert not u['iki_adim_acik'] and u['iki_adim_sir'] is None and u['session_version'] == sv + 1
    assert not satirlar(a, "SELECT * FROM iki_adim_kurtarma WHERE kullanici_adi='okur'")
    d = satirlar(a, "SELECT * FROM denetim WHERE islem='2fa_sifirla'")
    assert len(d) == 1 and d[0]['kullanici'] == 'testadmin' and d[0]['hedef_id'] == 'okur'
    assert 'sıfırlandı' in c.get('/yonetim/kullanicilar').data.decode()
    # İşlem Geçmişi Türkçe adlar
    from app import panel
    for kod in ('2fa_ac', '2fa_kapat', '2fa_kurtarma_kullanildi', '2fa_sifirla', '2fa_cihaz_guven', '2fa_hata', '2fa_cihaz_kaldir'):
        assert kod in panel.ISLEM_ADLARI and kod in panel.DENETIM_ADLARI
    assert '2FA sıfırlama' in c.get('/denetim').data.decode()
    # okur artık yalnız parolayla girer (politika onu kapsamıyor)
    cikis(c)
    assert login(c, 'okur').headers['Location'].endswith('/')


# ================================================================ CLI, API, sağlık

def test_cli_2fa_sifirla_ve_durum(web, saat, monkeypatch, capsys):
    from app import cli
    c, a = web
    monkeypatch.setattr(cli, 'AYAR', a)

    def calistir(*argv):
        monkeypatch.setattr(sys, 'argv', ['app.cli', *argv])
        cli.main()
        return capsys.readouterr().out
    login(c); kur(c, a, saat); cikis(c)
    hesap(a, 'okur', 'OF:oku')
    ayar(a, 'IKI_ADIM_ZORUNLU', 'yonetici')
    out = calistir('2fa-durum')
    assert 'yöneticilere zorunlu' in out and '30 gün' in out
    assert re.search(r'testadmin\s+açık', out) and re.search(r'okur\s+yok', out)
    veri = json.loads(calistir('2fa-durum', '--json'))
    assert veri['politika'] == 'yonetici' and {h['kullanici']: h['durum'] for h in veri['hesaplar']} == {'testadmin': 'acik', 'okur': 'yok'}
    out = calistir('2fa-sifirla', 'testadmin')
    assert 'sıfırlandı' in out and not kullanicilar.bul(a, 'testadmin')['iki_adim_acik']
    assert satirlar(a, "SELECT kullanici FROM denetim WHERE islem='2fa_sifirla'")[0]['kullanici'] == 'sunucu-cli'
    assert re.search(r'testadmin\s+zorunlu-bekliyor', calistir('2fa-durum'))
    assert 'zaten kapalıydı' in calistir('2fa-sifirla', 'okur')
    with pytest.raises(SystemExit, match='bulunamadı'):
        calistir('2fa-sifirla', 'yokboyle')


def test_api_ve_saglik_etkilenmez(web):
    c, a = web
    ayar(a, 'IKI_ADIM_ZORUNLU', 'hepsi')
    con = baglanti(a)
    _, anahtar = aa.olustur(con, 'Rapor', '*', olusturan='testadmin')
    con.close()
    r = c.get('/api/v1/ozet', headers={'Authorization': 'Bearer ' + anahtar})
    assert r.status_code == 200 and 'Set-Cookie' not in r.headers
    assert c.get('/saglik').status_code == 200
    # Zorunlu ama kurmamış süperadmin parolayla girer, yalnız kurulum sayfasına yönlenir (kod sorulmaz, kilitlenmez)
    r = login(c)
    assert r.status_code == 302 and oturum_var(c)
    assert c.get('/').headers['Location'].endswith('/profil/iki-adim')


# ================================================================ Tarayıcı (Node + Playwright yoksa atlanır)

TARAYICI_BETIK = Path(__file__).with_name('iki_adim_tarayici.js')


def _playwright_var():
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_kurulum_kodla_giris_guvenilen_cihaz(web):
    import threading
    from waitress.server import create_server
    from app import panel
    c, a = web
    sahip_yap(a); hesap(a, 'okur', 'OF:oku')
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    klasor = os.getenv('KT_EKRAN_KLASORU') or '/tmp/kanit-ekran/p241'
    os.makedirs(klasor, exist_ok=True)
    try:
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, EKRAN_KLASORU=klasor)
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=240, env=ortam, cwd=klasor)
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        try:
            sunucu.close()
        except Exception:
            pass
    assert kullanicilar.bul(a, 'testadmin')['iki_adim_acik'] == 1
