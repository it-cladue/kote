# -*- coding: utf-8 -*-
"""QA düzeltme turu (2.3.0 son tur, WEB ekibi): web.txt + yukseltme.txt bulgularının regresyon testleri.
1 çıkış/iyimser kilit ayrışması (hesap_surumu) ve 2.3.0 şemalı DB yükseltmesi; 2 gz alanı olmayan oturum mesajı;
3 geçici parola kayıtlarının süre temizliği; 4 "kaydet = kilidi aç"; 5 send_file yarışı ve her isabette dokunma;
6 Gyazo önbellek varsayılanları; 7 CIKTI_SATIR_SINIRI 30.000; 8 superadmin eş anlamlısı (yetki + CLI)."""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import db, kullanicilar, panel, yetki, gorsel, settings
from tests.test_web import web, token, login, csrf, seed  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
XHR = {'X-Requested-With': 'XMLHttpRequest'}
SIFRE = 'Test-Password-123!'


def hesap(a, ad):
    return kullanicilar.bul(a, ad)


def denetim(a, islem):
    con = db.baglan(a['DB'])
    try:
        return [dict(r) for r in con.execute('SELECT * FROM denetim WHERE islem=? ORDER BY id', (islem,))]
    finally:
        con.close()


def ikinci_istemci(c, ad):
    c2 = c.application.test_client()
    assert login(c2, ad).status_code == 302
    return c2


def sayfadaki_surum(html, ad):
    m = re.search(r'name="ad" value="%s"><input type="hidden" name="expected_version" value="(\d+)"' % re.escape(ad), html)
    assert m, 'formda expected_version yok'
    return int(m.group(1))


# ---- 1. Çıkış session_version'ı artırır ama admin formunun iyimser kilidi (hesap_surumu) düşmez -----------------
def test_kullanici_cikisi_admin_formunu_dusurmez_eski_cerez_yine_reddedilir(web):
    c, a = web; login(c)
    kullanicilar.ekle(a, 'ayse', 'OF:oku,kt', SIFRE); kullanicilar.guncelle(a, 'ayse', sifre_degistir=0)
    u0 = hesap(a, 'ayse'); assert u0['hesap_surumu'] == 2 and u0['session_version'] == 2  # ekle(1) + guncelle(+1), ikisi birlikte
    html = c.get('/yonetim/kullanicilar').data.decode()
    ev = sayfadaki_surum(html, 'ayse'); assert ev == u0['hesap_surumu']
    assert html.count('name="ad" value="ayse"><input type="hidden" name="expected_version" value="%d"' % ev) == 3  # guncelle + sifre + 2FA zorunluluğu (2.4.2) formları aynı sayacı taşır
    # Kullanıcı iki cihazda girer; giriş sürümü artırmaz. Cihaz 1 çıkış yapar.
    cihaz1 = ikinci_istemci(c, 'ayse'); cihaz2 = ikinci_istemci(c, 'ayse')
    assert hesap(a, 'ayse')['session_version'] == 2
    eski_cerez = cihaz1.get_cookie('kanit_session').value
    assert cihaz1.post('/cikis', data={'csrf': csrf(cihaz1)}).status_code == 302
    u1 = hesap(a, 'ayse'); assert u1['session_version'] == 3 and u1['hesap_surumu'] == 2  # çıkış yalnız oturum sürümünü artırır
    # Admin, sayfayı yenilemeden ESKİ expected_version ile kaydeder: artık 302 (eskiden 'Hesap başka bir admin tarafından değiştirildi').
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'ayse', 'expected_version': ev, 'gorunen_ad': 'Ayşe Y.',
                                               'rol': 'admin', 'projeler': ['OF'], 'eylemler_OF': ['kt'], 'aktif': '1'})
    assert r.status_code == 302, r.data[:300]
    u2 = hesap(a, 'ayse'); assert u2['ad'] == 'Ayşe Y.' and u2['hesap_surumu'] == 3 and u2['session_version'] == 4
    # Geçici şifre üretimi de çıkıştan etkilenmez: yeni sayfa sürümü alınır, kullanıcı tekrar çıkar, admin yine eski sürümle 302.
    ev2 = sayfadaki_surum(c.get('/yonetim/kullanicilar').data.decode(), 'ayse'); assert ev2 == 3
    cihaz3 = ikinci_istemci(c, 'ayse'); assert cihaz3.post('/cikis', data={'csrf': csrf(cihaz3)}).status_code == 302
    assert hesap(a, 'ayse')['session_version'] == 5 and hesap(a, 'ayse')['hesap_surumu'] == 3
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'ayse', 'expected_version': ev2})
    assert r.status_code == 302 and 'id="gecici-sifre"' in c.get('/yonetim/kullanicilar').data.decode()
    assert hesap(a, 'ayse')['hesap_surumu'] == 4
    # Gerçek çakışma hâlâ yakalanır (bayat sayaçla ikinci gönderim).
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'ayse', 'expected_version': ev2})
    assert r.status_code == 200 and 'başka bir admin tarafından değiştirildi' in r.data.decode()
    # 2.3.0 kazanımı korunur: çıkış öncesi kopyalanan çerez reddedilir (XHR 401, sayfa 302).
    cihaz1.set_cookie('kanit_session', eski_cerez)
    r = cihaz1.get('/bildirim.json', headers=XHR); assert r.status_code == 401 and r.json['ok'] is False
    cihaz1.set_cookie('kanit_session', eski_cerez)
    assert cihaz1.get('/kayitlar').status_code == 302
    # Diğer cihaz düşer ve açıklama artık çıkışı da söyler.
    r = cihaz2.get('/kayitlar'); assert r.status_code == 302 and 'neden=oturum' in r.headers['Location']
    giris = cihaz2.get(r.headers['Location']).data.decode()
    assert panel.OTURUM_MESAJI in giris and 'başka bir cihazdan çıkış yapıldı' in panel.OTURUM_MESAJI
    # Çekirdek API: expected_version hesap_surumu ile karşılaştırılır.
    with pytest.raises(ValueError, match='başka bir admin'):
        kullanicilar.guncelle(a, 'ayse', expected_version=hesap(a, 'ayse')['session_version'], aktif=1)
    kullanicilar.guncelle(a, 'ayse', expected_version=hesap(a, 'ayse')['hesap_surumu'], aktif=1)


def test_230_semali_veritabani_acilinca_hesap_surumu_eklenir_ve_satirlar_korunur(tmp_path):
    yol = str(tmp_path / 'panel.db'); ayar = {'DB': yol}
    con = db.baglan(yol)
    kullanicilar.ekle(ayar, 'eski.admin', 'admin', SIFRE); kullanicilar.ekle(ayar, 'eski.of', 'OF:oku,kt', SIFRE)
    con.execute("UPDATE panel_kullanicilari SET session_version=7 WHERE kullanici_adi='eski.of'")
    # 2.3.0 durumu: core_schema_21=1 yazılı, core_schema_23 ve hesap_surumu sütunu YOK (ensure_schema erken döner).
    con.execute('ALTER TABLE panel_kullanicilari DROP COLUMN hesap_surumu')
    con.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_23'")
    assert db.ayar_al(con, 'core_schema_21') == '1' and db.ayar_al(con, 'rol_gecis_21') == '1'
    assert 'hesap_surumu' not in {r['name'] for r in con.execute('PRAGMA table_info(panel_kullanicilari)')}
    assert not db._ready(con)
    con.close()
    con = db.baglan(yol)  # servis yeniden başlayınca ilk bağlantı
    kolonlar = {r['name'] for r in con.execute('PRAGMA table_info(panel_kullanicilari)')}
    assert 'hesap_surumu' in kolonlar and db.ayar_al(con, 'core_schema_23') == '1' and db.ayar_al(con, 'core_schema_21') == '1'
    rows = {r['kullanici_adi']: dict(r) for r in con.execute('SELECT * FROM panel_kullanicilari')}
    assert rows['eski.of']['session_version'] == 7 and rows['eski.of']['hesap_surumu'] == 1 and rows['eski.of']['yetki'] == 'OF:oku,gorsel,kt'
    assert rows['eski.admin']['yetki'] == 'admin' and rows['eski.admin']['hesap_surumu'] == 1
    assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='yetki_kanonik'").fetchone()[0] == 0  # rol geçişi tekrar koşmadı
    assert db._ready(con); con.close()
    # Yükseltilmiş DB'de iyimser kilit çalışır; ikinci açılış idempotent.
    kullanicilar.guncelle(ayar, 'eski.of', expected_version=1, aktif=0)
    assert hesap(ayar, 'eski.of')['hesap_surumu'] == 2 and hesap(ayar, 'eski.of')['aktif'] == 0
    db.baglan(yol).close()
    # Taze DB'de de sütun şemadan gelir.
    con = db.baglan(str(tmp_path / 'taze.db'))
    assert 'hesap_surumu' in {r['name'] for r in con.execute('PRAGMA table_info(panel_kullanicilari)')} and db.ayar_al(con, 'core_schema_23') == '1'
    con.close()


# ---- 2. gz alanı olmayan (2.3 öncesi) ya da bozuk oturum: '24 saat doldu' değil genel açıklama ----------------
def test_gz_alani_olmayan_oturum_genel_mesaj_alir(web):
    c, a = web
    for gz in (None, 'abc', 1.5):
        login(c)
        with c.session_transaction() as s:
            if gz is None: s.pop('gz', None)
            else: s['gz'] = gz
        r = c.get('/kayitlar'); assert r.status_code == 302 and 'neden=oturum' in r.headers['Location']
        with c.session_transaction() as s:
            assert s.get('dustu') and s.get('dustu_neden') == 'degisti', repr(gz)
        html = c.get('/giris').data.decode()
        assert panel.OTURUM_MESAJI in html and panel.SURE_MESAJI not in html and '24 saat' not in html, repr(gz)
    # Gerçek süre aşımı hâlâ 'sure' mesajı verir.
    login(c)
    with c.session_transaction() as s:
        s['gz'] = int(time.time()) - panel.MUTLAK_OTURUM_SN - 5
    assert c.get('/kayitlar').status_code == 302
    with c.session_transaction() as s:
        assert s.get('dustu_neden') == 'sure'
    assert panel.SURE_MESAJI in c.get('/giris').data.decode()


# ---- 3. Geçici parola: süresi geçen kayıt admin sonucu hiç görmese de silinir --------------------------------
def gecici_satirlar(a):
    con = db.baglan(a['DB'])
    try:
        return {r['anahtar']: json.loads(r['deger']) for r in con.execute("SELECT anahtar,deger FROM ayarlar WHERE anahtar LIKE 'gecici_sifre:%'")}
    finally:
        con.close()


def eskit(a, anahtar, dakika):
    con = db.baglan(a['DB'])
    try:
        deger = json.loads(db.ayar_al(con, anahtar)); deger['zaman'] = (datetime.now() - timedelta(minutes=dakika)).strftime('%Y-%m-%d %H:%M:%S')
        with db.transaction(con):
            db.ayar_yaz(con, anahtar, json.dumps(deger, ensure_ascii=False))
    finally:
        con.close()


def test_suresi_gecen_gecici_parola_kayitlari_her_yoldan_silinir(web):
    c, a = web; login(c)
    kullanicilar.ekle(a, 'yeni.kisi', 'OF:oku', SIFRE)
    # Admin üretir ama sonucu görmez (sekme kapandı): satır kaldı.
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'yeni.kisi', 'expected_version': hesap(a, 'yeni.kisi')['hesap_surumu']}).status_code == 302
    satirlar = gecici_satirlar(a); assert len(satirlar) == 1
    (anahtar, veri), = satirlar.items(); assert veri['ad'] == 'yeni.kisi' and len(veri['sifre']) >= 15
    eskit(a, anahtar, 11)
    # (a) Token'ı OLMAYAN başka bir admin oturumunun GET'i süresi geçen satırı siler.
    diger = c.application.test_client(); kullanicilar.ekle(a, 'ikinci.admin', 'admin', SIFRE); kullanicilar.guncelle(a, 'ikinci.admin', sifre_degistir=0)
    assert login(diger, 'ikinci.admin').status_code == 302 and diger.get('/yonetim/kullanicilar').status_code == 200
    assert gecici_satirlar(a) == {}
    # Token'ı olan admin sonra gelirse kutu çıkmaz (süresi geçti), 500 yok.
    html = c.get('/yonetim/kullanicilar').data.decode(); assert 'id="gecici-sifre"' not in html and veri['sifre'] not in html
    # (b) Süresi geçmemiş satır GET'te silinmez ve token sahibine bir kez gösterilir.
    assert c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'yeni.kisi', 'expected_version': hesap(a, 'yeni.kisi')['hesap_surumu']}).status_code == 302
    assert diger.get('/yonetim/kullanicilar').status_code == 200 and len(gecici_satirlar(a)) == 1
    html = c.get('/yonetim/kullanicilar').data.decode(); assert 'id="gecici-sifre"' in html and gecici_satirlar(a) == {}
    # (c) Periyodik/süreç başı temizlik kendi bağlantısıyla çalışır; hatalı JSON'lu kayıt da gider; taze kayıt kalır.
    con = db.baglan(a['DB'])
    with db.transaction(con):
        db.ayar_yaz(con, 'gecici_sifre:' + 'a' * 32, json.dumps({'ad': 'x', 'sifre': 'p', 'zaman': '2000-01-01 00:00:00'}))
        db.ayar_yaz(con, 'gecici_sifre:' + 'b' * 32, 'bozuk-json')
        db.ayar_yaz(con, 'gecici_sifre:' + 'c' * 32, json.dumps({'ad': 'y', 'sifre': 'q', 'zaman': db.simdi()}))
        db.ayar_yaz(con, 'baska_ayar', 'kalir')
    con.close()
    assert panel.gecici_sifreleri_temizle() == 2
    kalan = gecici_satirlar(a); assert list(kalan) == ['gecici_sifre:' + 'c' * 32]
    con = db.baglan(a['DB']); assert db.ayar_al(con, 'baska_ayar') == 'kalir'; con.close()
    assert panel.GECICI_SIFRE_OMRU_DK == 10 and panel.GECICI_SIFRE_TEMIZLIK_SN <= 600
    # Süreç başlangıcı (calistir) ve dönüşüm işçisi döngüsü bu temizliği çağırır.
    kaynak = (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')
    assert 'eski_kontrolleri_temizle();gecici_sifreleri_temizle()' in kaynak and 'GECICI_SIFRE_TEMIZLIK_SN:\n                    son_temizlik=time.time();gecici_sifreleri_temizle(conn)' in kaynak


# ---- 4. "Kaydet" kilidi açar: alan değişmese bile sayaç/kilit sıfırlanır, denetime kilit_ac yazılır ----------
def kilitle(c, ad, adet=5):
    k = c.application.test_client()
    for _ in range(adet):
        assert k.post('/giris', data={'csrf': token(k), 'kullanici': ad, 'sifre': 'yanlis-parola'}).status_code == 200


def test_degisiklik_olmasa_da_kaydet_kilidi_acar_ve_denetime_yazar(web):
    c, a = web; login(c)
    kullanicilar.ekle(a, 'kilitli', 'OF:oku,kt', SIFRE, 'Kilitli Kişi'); kullanicilar.guncelle(a, 'kilitli', sifre_degistir=0)
    kilitle(c, 'kilitli')
    u = hesap(a, 'kilitli'); assert u['hatali_giris'] == 5 and kullanicilar.kilitli_mi(u)
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'Kilitli: %s kadar' % u['kilit_bitis'][11:16] in html and 'kilidi hemen açar' in html and 'kaydet = kilidi aç' not in html
    guncelle_sayisi = len(denetim(a, 'kullanici_guncelle'))
    # Hiçbir alan değişmeden "Değişiklikleri kaydet".
    ayni = {'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'kilitli', 'expected_version': u['hesap_surumu'], 'gorunen_ad': 'Kilitli Kişi',
            'rol': 'admin', 'projeler': ['OF'], 'eylemler_OF': ['kt'], 'aktif': '1'}
    assert c.post('/yonetim/kullanicilar', data=ayni).status_code == 302
    u2 = hesap(a, 'kilitli')
    assert u2['hatali_giris'] == 0 and u2['kilit_bitis'] is None
    assert u2['session_version'] == u['session_version'] and u2['hesap_surumu'] == u['hesap_surumu']  # değişiklik yok: sürümler aynı, oturum düşmez
    kayit = denetim(a, 'kilit_ac'); assert len(kayit) == 1 and kayit[0]['kullanici'] == 'testadmin' and kayit[0]['hedef_id'] == 'kilitli'
    assert '5 hatalı deneme' in kayit[0]['aciklama'] and 'kadar sürecekti' in kayit[0]['aciklama'] and kayit[0]['sonuc'] == 'ok'
    assert len(denetim(a, 'kullanici_guncelle')) == guncelle_sayisi  # değişiklik yok: kullanici_guncelle yazılmaz, yalnız kilit_ac
    assert 'Kilitli:' not in c.get('/yonetim/kullanicilar').data.decode()
    # Kullanıcı 15 dakika beklemeden girer.
    assert kullanicilar.dogrula(a, 'kilitli', SIFRE)[0]
    # Yalnız sayaç dolu (kilit yok) → yine sıfırlanır; temiz hesapta kaydet kilit_ac yazmaz.
    kilitle(c, 'kilitli', 2); assert hesap(a, 'kilitli')['hatali_giris'] == 2
    assert c.post('/yonetim/kullanicilar', data=dict(ayni, csrf=csrf(c), expected_version=hesap(a, 'kilitli')['hesap_surumu'])).status_code == 302
    assert hesap(a, 'kilitli')['hatali_giris'] == 0 and len(denetim(a, 'kilit_ac')) == 2
    assert c.post('/yonetim/kullanicilar', data=dict(ayni, csrf=csrf(c), expected_version=hesap(a, 'kilitli')['hesap_surumu'])).status_code == 302
    assert len(denetim(a, 'kilit_ac')) == 2
    # Alan değişikliğiyle birlikte açılan kilit de kaydedilir; İşlem Geçmişi ve ana akış kodu Türkçe adlandırır.
    kilitle(c, 'kilitli')
    assert c.post('/yonetim/kullanicilar', data=dict(ayni, csrf=csrf(c), expected_version=hesap(a, 'kilitli')['hesap_surumu'], gorunen_ad='Yeni Ad')).status_code == 302
    assert hesap(a, 'kilitli')['kilit_bitis'] is None and len(denetim(a, 'kilit_ac')) == 3 and len(denetim(a, 'kullanici_guncelle')) == guncelle_sayisi + 1
    assert panel.ISLEM_ADLARI['kilit_ac'] == 'Hesap kilidini açtı' and panel.DENETIM_ADLARI['kilit_ac'] == 'Kilit açma'
    assert 'Kilit açma' in c.get('/denetim').data.decode()


# ---- 5. Önbellek budaması ile send_file yarışı: 500 yerine yeniden çözümleme / yer tutucu -----------------------
def test_budama_send_file_arasinda_dosyayi_silse_500_olmaz(web, monkeypatch):
    c, a = web; login(c); kid = seed(a)
    r = c.get(f'/kucuk/{kid}'); assert r.status_code == 200 and r.mimetype == 'image/jpeg'
    thumb = [p for p in (Path(a['ONBELLEK']) / 'thumbs').iterdir() if p.suffix == '.jpg']; assert len(thumb) == 1
    # Budama tam send_file öncesinde dosyayı siliyor (ilk çağrıda): yeniden üretilir ve 200 JPEG döner.
    orijinal = panel.send_file; silinen = []

    def yarisli_send_file(yol, **kw):
        if not silinen:
            silinen.append(str(yol)); os.unlink(yol)
        return orijinal(yol, **kw)
    monkeypatch.setattr(panel, 'send_file', yarisli_send_file)
    r = c.get(f'/kucuk/{kid}')
    assert r.status_code == 200 and r.mimetype == 'image/jpeg' and silinen == [str(thumb[0])] and thumb[0].exists()
    assert denetim(a, 'sunucu_hata') == []
    # Orijinal görsel (önbellek değil) gerçekten silinmişse yeniden çözüm eşleşme bulamaz: 500 değil 404.
    silinen.clear(); r = c.get(f'/gorsel/{kid}')
    assert r.status_code == 404 and len(silinen) == 1 and denetim(a, 'sunucu_hata') == []
    monkeypatch.setattr(panel, 'send_file', orijinal)
    # Her iki çözümleme de var olmayan yol veriyorsa yer tutucu (200, X-Gorsel-Durum: yok), 500 değil.
    monkeypatch.setattr(panel, '_gorsel_yolu', lambda kid, kucuk=False: (str(Path(a['ONBELLEK']) / 'thumbs' / 'yok.jpg'), False))
    r = c.get(f'/kucuk/{kid}')
    assert r.status_code == 200 and r.headers['X-Gorsel-Durum'] == 'yok' and r.mimetype == 'image/svg+xml' and 'no-store' in r.headers['Cache-Control']
    r = c.get(f'/gorsel/{kid}')
    assert r.status_code == 200 and r.headers['X-Gorsel-Durum'] == 'yok' and 'sayfayı yenileyin' in r.data.decode()
    # Yeniden çözümleme var olan dosyayı veriyorsa o servis edilir.
    yollar = iter([str(Path(a['ONBELLEK']) / 'thumbs' / 'yok.jpg'), str(thumb[0])])
    monkeypatch.setattr(panel, '_gorsel_yolu', lambda kid, kucuk=False: (next(yollar), False))
    r = c.get(f'/kucuk/{kid}'); assert r.status_code == 200 and r.mimetype == 'image/jpeg'
    assert denetim(a, 'sunucu_hata') == []


def test_arsiv_kucuk_resmi_yarista_silinirse_yeniden_uretilir(web, monkeypatch):
    c, a = web; login(c)
    from PIL import Image
    kaynak = Path(a['ARSIV_KLASOR']) / 'OF' / 'a.png'; kaynak.parent.mkdir(parents=True); Image.new('RGB', (12, 12), (0, 0, 255)).save(kaynak, 'PNG')
    con = db.baglan(a['DB'])
    with db.transaction(con):
        aid = con.execute("INSERT INTO arsiv_dosyalar(yol,ad,proje,kimlik,guncelleme) VALUES(?,?,?,?,?)", (str(kaynak), 'a.png', 'OF', 'a', db.simdi())).lastrowid
    con.close()
    assert c.get(f'/arsiv/gorsel/{aid}?kucuk=1').status_code == 200
    orijinal = panel.send_file; silinen = []

    def yarisli(yol, **kw):
        if not silinen:
            silinen.append(str(yol)); os.unlink(yol)
        return orijinal(yol, **kw)
    monkeypatch.setattr(panel, 'send_file', yarisli)
    r = c.get(f'/arsiv/gorsel/{aid}?kucuk=1')
    assert r.status_code == 200 and r.mimetype == 'image/jpeg' and len(silinen) == 1 and Path(silinen[0]).exists()
    monkeypatch.setattr(panel, 'send_file', orijinal)
    # Küçük resim üretilemezse (kaynak bozuk sayılır) orijinal dosya verilir.
    monkeypatch.setattr(panel.COZUCU, 'kucuk', lambda kayit, yol: None)
    assert c.get(f'/arsiv/gorsel/{aid}?kucuk=1').status_code == 404  # ilk üretim başarısız: mevcut davranış korunur
    monkeypatch.setattr(panel.COZUCU, 'kucuk', lambda kayit, yol: str(Path(a['ONBELLEK']) / 'thumbs' / 'yok.jpg'))
    r = c.get(f'/arsiv/gorsel/{aid}?kucuk=1'); assert r.status_code == 200 and r.mimetype == 'image/png'  # yeniden çözüm de yok → orijinal


def test_servis_edilen_onbellek_dosyasina_her_isabette_dokunulur(web):
    c, a = web; login(c); kid = seed(a); coz = panel.COZUCU
    assert c.get(f'/kucuk/{kid}').status_code == 200
    thumb, = [p for p in (Path(c.application.view_functions and a['ONBELLEK']) / 'thumbs').iterdir() if p.suffix == '.jpg']
    # 100 sn önce dokunulmuş görünsün: eski davranışta (saatlik eşik) utime yapılmazdı, şimdi her isabette yapılır.
    eski = time.time() - 100; os.utime(thumb, (eski, eski))
    assert c.get(f'/kucuk/{kid}').status_code == 200 and time.time() - thumb.stat().st_mtime < 5
    # Gyazo önbelleğinde de aynı: okunan dosya ONBELLEK_TAZE_SN boyunca budamadan korunur.
    g = Path(coz.gyazo_klasor); kimlik = 'c' * 32; dosya = g / (kimlik + '.jpg'); dosya.write_bytes(b'x' * 2048)
    os.utime(dosya, (eski, eski)); assert coz._gyazo_onbellek(kimlik) == str(dosya) and time.time() - dosya.stat().st_mtime < 5
    coz.gyazo_sinir_bayt = 1024  # sınır dolu olsa da az önce okunan (taze) dosya silinmez
    rapor = coz.onbellek_temizle(zorla=True)['gyazo']; assert rapor['silinen'] == 0 and dosya.exists()
    assert not hasattr(gorsel, 'ONBELLEK_DOKUNMA_SN') and gorsel.ONBELLEK_TAZE_SN == 60


# ---- 6. Gyazo kopyaları kanıt kopyasıdır: yaş budaması varsayılan kapalı, 2000 MB ---------------------------------
def test_gyazo_onbellek_varsayilanlari_yas_siniri_yok_2000_mb(monkeypatch):
    for ad in ('GYAZO_ONBELLEK_MB', 'GYAZO_ONBELLEK_GUN', 'KUCUK_ONBELLEK_MB'):
        monkeypatch.delenv(ad, raising=False)
    a = settings.settings()
    assert a['GYAZO_ONBELLEK_GUN'] == 0 and a['GYAZO_ONBELLEK_MB'] == 2000 and a['KUCUK_ONBELLEK_MB'] == 300
    assert gorsel.ONBELLEK_VARSAYILAN == {'GYAZO_ONBELLEK_MB': 2000, 'GYAZO_ONBELLEK_GUN': 0, 'KUCUK_ONBELLEK_MB': 300}
    coz = gorsel.GorselCozucu(dict(a, BOT_KLASOR=str(settings.DATA)), str(settings.DATA / 'tmp'))
    assert coz.gyazo_yas_sn == 0 and coz.gyazo_sinir_bayt == 2000 * 1024 * 1024
    d = coz.onbellek_durumu(); assert d['gyazo']['yas_gun'] == 0 and d['gyazo']['sinir_mb'] == 2000
    # 0 = yaş sınırı yok: 400 günlük dosya kalır; boyut sınırı dolunca en eski yine silinir.
    import tempfile, shutil
    kok = tempfile.mkdtemp(prefix='qa-gyazo-')
    try:
        g = os.path.join(kok, 'gyazo'); os.makedirs(g)
        yollar = []
        for i in range(4):
            p = os.path.join(g, ('%032x' % i) + '.jpg'); open(p, 'wb').write(b'x' * 1024); t = time.time() - (400 - i) * 86400; os.utime(p, (t, t)); yollar.append(p)
        assert gorsel._onbellek_buda(g, 0, 0)['silinen'] == 0 and all(os.path.exists(p) for p in yollar)
        rapor = gorsel._onbellek_buda(g, 2 * 1024, 0)
        assert rapor['silinen'] == 3 and not os.path.exists(yollar[0]) and os.path.exists(yollar[3])  # %90 hedefi: en eskiden başlar
    finally:
        shutil.rmtree(kok, ignore_errors=True)
    # .env ile açıkça gün verilirse yaş budaması yine çalışır.
    monkeypatch.setenv('GYAZO_ONBELLEK_GUN', '45'); assert settings.settings()['GYAZO_ONBELLEK_GUN'] == 45


# ---- 7. Excel çıktısı varsayılan üst sınırı 30.000 -----------------------------------------------------------
def test_cikti_satir_siniri_varsayilani_30000():
    if os.getenv('CIKTI_SATIR_SINIRI'):
        pytest.skip('ortamda CIKTI_SATIR_SINIRI tanımlı')
    assert panel.CIKTI_SATIR_SINIRI == 30000
    mesaj = panel._cikti_sinir_mesaji(45000)
    assert 'Seçime 45.000 kayıt uyuyor' in mesaj and 'en çok 30.000 kayıt' in mesaj and 'parça hâlinde indirin' in mesaj
    kaynak = (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')
    assert "os.getenv('CIKTI_SATIR_SINIRI','30000')" in kaynak and '100000' not in kaynak.split('CIKTI_SATIR_SINIRI=', 1)[1][:200]


# ---- 8. superadmin / süperadmin = admin (yetki.kanonikle, web formu, CLI yardımı) --------------------------------
def test_superadmin_es_anlamlisi_kabul_edilir():
    for metin in ('superadmin', 'süperadmin', 'SUPERADMIN', 'SÜPERADMİN', ' Superadmin ', 'admin'):
        assert yetki.kanonikle(metin) == 'admin', metin
    assert yetki.kanonikle('OF:oku,kt', ['OF']) == 'OF:oku,gorsel,kt'
    for kotu in ('superadmin:OF', 'OF,superadmin', 'admin:oku', '*', ''):
        with pytest.raises(ValueError):
            yetki.kanonikle(kotu, ['OF'])
    assert yetki.coz('superadmin')['gecerli'] is False  # saklanan değer her zaman kanonik 'admin'
    assert yetki.ozet('admin') == 'Süperadmin — tüm projeler ve yönetim'


def _cli(tmp_path, *args, env=None):
    ortam = dict(os.environ, PANEL_VERI=str(tmp_path / 'veri'), GYAZO_WORKER='0'); ortam.update(env or {})
    return subprocess.run([sys.executable, '-m', 'app.cli', *args], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)


def test_cli_superadmin_yetkisi_ve_yardim_metni(tmp_path):
    yardim = _cli(tmp_path, 'admin-ekle', '--help')
    assert yardim.returncode == 0 and 'admin (süperadmin)' in yardim.stdout and 'admin, superadmin' not in yardim.stdout
    r = _cli(tmp_path, 'admin-ekle', 'ikinci', '--yetki', 'superadmin', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'Guclu-Parola-77'})
    assert r.returncode == 0, r.stderr + r.stdout
    ayar = {'DB': str(tmp_path / 'veri' / 'panel.db')}
    u = kullanicilar.bul(ayar, 'ikinci'); assert u['yetki'] == 'admin' and u['sifre_degistir'] == 0
    r = _cli(tmp_path, 'admin-ekle', 'ucuncu', '--yetki', 'süperadmin', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'Guclu-Parola-77'})
    assert r.returncode == 0 and kullanicilar.bul(ayar, 'ucuncu')['yetki'] == 'admin'
    r = _cli(tmp_path, 'admin-ekle', 'dorduncu', '--yetki', 'superadmin:OF', '--password-env', 'KANIT_PW', env={'KANIT_PW': 'Guclu-Parola-77'})
    assert r.returncode != 0 and 'Geçerli rol' in (r.stderr + r.stdout)
    # Web formunun serbest 'yetki' alanı da eş anlamlıyı kabul eder.
    kullanicilar.ekle(ayar, 'besinci', 'SuperAdmin', 'Guclu-Parola-77'); assert kullanicilar.bul(ayar, 'besinci')['yetki'] == 'admin'
