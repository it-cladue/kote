# -*- coding: utf-8 -*-
"""2.2 düzeltme turu (genel): bot sayfası, giriş yönlendirmesi, oturum düşmesi, çıktı uyarıları,
işlem geçmişi hedefi, /saglik çerezi, bildirim zili alanları, geçici şifre kutusu, kanıt kontrolü notu, arama kapsamı."""
import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, bot_yonetim, katalog, kullanicilar
from test_web import web, seed, login, csrf, token

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def sonraki(response):
    from urllib.parse import urlsplit, parse_qs
    return parse_qs(urlsplit(response.headers['Location']).query).get('sonraki', [''])[0]


def tg_user(config, tg_id, username='', first_name=''):
    conn = db.baglan(config['DB'])
    with db.transaction(conn):
        conn.execute("INSERT INTO tg_kullanicilar(id,username,first_name,onayli,engelli,last_seen) VALUES(?,?,?,0,0,?)", (tg_id, username, first_name, db.simdi()))
    conn.close()


def tg_row(config, tg_id):
    conn = db.baglan(config['DB'])
    row = conn.execute('SELECT username,first_name,onayli,engelli FROM tg_kullanicilar WHERE id=?', (tg_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---- 1. /bot?sure=bad artık 500 vermez ----------------------------------------------------------------
def test_bot_invalid_time_filter_is_ignored(web):
    c, a = web; login(c)
    assert bot_yonetim.sure_normalle('bad') == '' and bot_yonetim.sure_normalle('24saat') == '24saat' and bot_yonetim.sure_normalle(None) == ''
    page = c.get('/bot?sure=bad&tg_durum=zzz')
    assert page.status_code == 200
    html = page.data.decode()
    assert 'Son görülme filtresi tanınmadı' in html
    assert '<option value="" selected>Tüm zamanlar</option>' in html
    assert c.get('/bot?sure=7gun').status_code == 200
    conn = db.baglan(a['DB'])
    assert bot_yonetim.kullanicilari_ara(conn, '', 'hepsi', 'olmayan') == []
    conn.close()


# ---- 2. Onayla: boş ad Telegram adlarını korur, manuel ad yalnız görünen ada yazılır ------------------
def test_bot_approve_keeps_names_and_manual_name_only_sets_first_name(web):
    c, a = web; login(c)
    tg_user(a, '1003', '', 'İsimsiz')
    assert c.post('/bot', data={'csrf': csrf(c), 'islem': 'onayla', 'tg_id': '1003'}).status_code == 200
    row = tg_row(a, '1003')
    assert row['onayli'] == 1 and row['first_name'] == 'İsimsiz' and row['username'] == ''
    # Satır formu artık ad göndermez; eski biçimde ad=ID gelse bile ID ada yazılmaz.
    c.post('/bot', data={'csrf': csrf(c), 'islem': 'onayla', 'tg_id': '1003', 'ad': '1003'})
    assert tg_row(a, '1003')['first_name'] == 'İsimsiz'
    tg_user(a, '1004', 'ali_saha', 'Ali')
    c.post('/bot', data={'csrf': csrf(c), 'islem': 'onayla', 'tg_id': '1004', 'ad': 'Yeni Kişi'})
    row = tg_row(a, '1004')
    assert row['first_name'] == 'Yeni Kişi' and row['username'] == 'ali_saha'
    # Engelle de aynı kuralı izler.
    c.post('/bot', data={'csrf': csrf(c), 'islem': 'engelle', 'tg_id': '1004', 'sebep': 'test'})
    row = tg_row(a, '1004')
    assert row['engelli'] == 1 and row['first_name'] == 'Yeni Kişi' and row['username'] == 'ali_saha'
    # Hiç olmayan kullanıcı için ad, username'e değil first_name'e gider.
    c.post('/bot', data={'csrf': csrf(c), 'islem': 'onayla', 'tg_id': '1005', 'ad': 'Taze Kişi'})
    row = tg_row(a, '1005')
    assert row['first_name'] == 'Taze Kişi' and row['username'] == ''


# ---- 3. Üç ayrı form, anlaşılır bot durumu, okunur arşiv raporu ----------------------------------------
def test_bot_page_three_forms_and_status_message(web):
    c, a = web; login(c)
    html = c.get('/bot').data.decode()
    for text in ('id="bot-onayla-baslik"', 'id="bot-engelle-baslik"', 'id="bot-sifirla-baslik"', 'name="islem" value="onayla"', 'name="islem" value="engelle"', 'name="islem" value="tam_sifirla"', 'data-gecersiz="Telegram ID yalnız rakamlardan oluşur'):
        assert text in html, text
    assert 'name="ad" value="' not in html  # satır formları artık username'i ad olarak göndermiyor
    assert 'Bot henüz sinyal göndermedi' in html and 'durum-etiket notr' in html
    assert 'Bağlantı / süreç kontrolü gerekli' not in html
    conn = db.baglan(a['DB'])
    with db.transaction(conn):
        conn.execute("INSERT INTO tg_durum(bot_id,heartbeat) VALUES('b1',?)", ((datetime.now() - timedelta(minutes=12)).strftime('%Y-%m-%d %H:%M:%S'),))
    conn.close()
    html = c.get('/bot').data.decode()
    assert 'Bot son 12 dakikadır sinyal vermedi' in html and 'durum-etiket silinen' in html
    conn = db.baglan(a['DB'])
    with db.transaction(conn):
        conn.execute("UPDATE tg_durum SET heartbeat=?", (db.simdi(),))
    conn.close()
    html = c.get('/bot').data.decode()
    assert 'Çalışıyor · son sinyal' in html and 'durum-etiket onayli' in html
    assert bot_yonetim.bot_durum_metni(None).startswith('Bot henüz sinyal')
    assert bot_yonetim.bot_durum_metni(7200) == 'Bot son 2 saattir sinyal vermedi'
    assert bot_yonetim.bot_durum_metni(3 * 86400) == 'Bot son 3 gündür sinyal vermedi'


def test_archive_scan_flash_is_plain_turkish(web):
    from app import panel
    c, a = web; login(c)
    page = c.post('/arsiv', data={'csrf': csrf(c), 'islem': 'tara'}, follow_redirects=True)
    html = page.data.decode()
    assert 'Arşiv tarandı: 0 dosya tarandı, 0 dosya indekslendi, 0 görsel kayıtla eşleşti.' in html
    assert '{"tarandi"' not in html
    assert panel._arsiv_rapor_metni({'tarandi': 3, 'indekslendi': 2, 'eslesti': 1, 'eslesmeyen': 1, 'belirsiz': 0, 'hata': None}) == 'Arşiv tarandı: 3 dosya tarandı, 2 dosya indekslendi, 1 görsel kayıtla eşleşti, 1 görsel eşleşmedi.'
    assert panel._arsiv_rapor_metni({'hata': 'arşiv kökü yok'}) == 'Arşiv taranamadı: arşiv kökü yok.'


# ---- 4. Giriş sonrası yönlendirme sorgu dizesini korur, güvensiz hedefi reddeder -----------------------
def test_login_redirect_keeps_query_string_and_rejects_unsafe(web):
    c, a = web
    r = c.get('/kayitlar?durum=onayli&proje=OF')
    assert r.status_code == 302 and sonraki(r) == '/kayitlar?durum=onayli&proje=OF'
    r = c.post('/giris?sonraki=%2Fkayitlar%3Fdurum%3Donayli%26proje%3DOF', data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'Test-Password-123!'})
    assert r.status_code == 302 and r.headers['Location'] == '/kayitlar?durum=onayli&proje=OF'
    c.post('/cikis', data={'csrf': csrf(c)})
    for bad in ('//evil.example/x', 'https://evil.example', '/a\\b'):
        r = c.post('/giris?sonraki=' + bad, data={'csrf': token(c), 'kullanici': 'testadmin', 'sifre': 'Test-Password-123!'})
        assert r.headers['Location'] == '/', bad
        c.post('/cikis', data={'csrf': csrf(c)})
    # Oturumsuz POST hedef olarak taşınmaz.
    r = c.post('/arsiv', data={'csrf': token(c), 'islem': 'tara'})
    assert r.status_code == 302 and sonraki(r) == '/'


# ---- 5. Yetki değişince oturum açıklamayla düşer; XHR'a JSON 401 ------------------------------------
def test_session_drop_is_explained_and_xhr_gets_json_401(web):
    from app import panel
    c, a = web; login(c); kid = seed(a)
    kullanicilar.ekle(a, 'kisitli', 'OF:oku,kt', 'Test-Password-123!'); kullanicilar.guncelle(a, 'kisitli', sifre_degistir=0)
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'kisitli')
    assert c.get('/kayitlar').status_code == 200
    old_csrf = csrf(c)
    kullanicilar.guncelle(a, 'kisitli', yetki='OF:oku')  # süperadmin yetkiyi daralttı → session_version arttı
    # Açık modal'daki XHR: 400 (CSRF) değil, açıklayıcı JSON 401.
    r = c.post(f'/kayit/{kid}/kt', data={'deger': '1'}, headers={'X-CSRF': old_csrf, 'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 401 and r.is_json and r.json['hata'] == 'Oturumunuz sona erdi, sayfayı yenileyin.' and r.json['giris'].startswith('/giris?neden=oturum')
    # Normal sayfa isteği: giriş sayfasına neden ve dönüş adresiyle.
    r = c.get('/kayitlar?durum=onayli')
    assert r.status_code == 302 and 'neden=oturum' in r.headers['Location'] and sonraki(r) == '/kayitlar?durum=onayli'
    html = c.get(r.headers['Location']).data.decode()
    assert panel.OTURUM_MESAJI in html and 'class="bilgi notr"' in html
    # Zil yoklaması da JSON 401 alır (HTML'e yönlendirilmez).
    r = c.get('/bildirim.json', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert r.status_code == 401 and r.is_json
    # Hiç oturum yokken XHR GET de JSON 401; tarayıcı sayfası ise 302.
    assert c.get('/kayitlar', headers={'Accept': 'application/json'}).status_code == 401
    assert c.get('/kayitlar').status_code == 302
    js = (STATIC / 'panel.js').read_text(encoding='utf-8')
    assert 'function oturumDustu(' in js and 'r.status===401' in js and 'neden=oturum' in js


# ---- 6. Çıktı: ters tarih satır içi uyarı, 0 kayıtta indirme öncesi uyarı ----------------------------
def test_export_inverted_dates_inline_and_zero_rows_warning(web):
    c, a = web; login(c)
    r = c.get('/disa-aktar.xlsx?tarih1=2026-02-01&tarih2=2026-01-01&durum=onayli&q=abc&proje=OF')
    assert r.status_code == 400 and 'text/html' in r.content_type
    html = r.data.decode()
    assert 'id="cikti-hata"' in html and 'Başlangıç tarihi bitiş tarihinden sonra olamaz' in html
    assert 'value="2026-02-01"' in html and 'value="2026-01-01"' in html and 'value="abc"' in html and '<option value="onayli" selected>' in html and 'value="OF" checked' in html
    assert 'Hata 400' not in html and '<title>Çıktı (Excel) — Kanıt Paneli</title>' in html
    r = c.get('/disa-aktar.xlsx?tarih1=2026-02-01&tarih2=2026-01-01&sayim=1')
    assert r.status_code == 400 and r.is_json and 'bitiş tarihinden sonra' in r.json['hata']
    r = c.get('/disa-aktar.xlsx?tarih1=2026-02-01&tarih2=2026-01-01', headers={'Accept': 'application/json'})
    assert r.status_code == 400 and r.is_json
    assert c.get('/disa-aktar.xlsx?tarihsiz=1&tarih1=2026-01-01').status_code == 400
    # Sayım: kayıt yokken 0 + uyarı metni; kayıt varken adet.
    r = c.get('/disa-aktar.xlsx?durum=hepsi&sayim=1')
    assert r.status_code == 200 and r.json == dict(ok=True, adet=0, mesaj='Seçime uyan kayıt yok; dosya indirilmedi. Tarih aralığını veya diğer koşulları genişletin.')
    seed(a)
    assert c.get('/disa-aktar.xlsx?durum=hepsi&sayim=1').json['adet'] == 1
    # Doğrudan indirme hâlâ çalışır (tarayıcısız kullanım / eski bağlantılar).
    r = c.get('/disa-aktar.xlsx?durum=hepsi')
    assert r.status_code == 200 and 'spreadsheetml' in r.content_type
    html = c.get('/disa-aktar').data.decode()
    for text in ('id="cikti-uyari"', 'id="cikti-tarih-hata"', 'Yine de boş dosyayı indir', "sayim=1", 'Excel dosyasını indir', 'setCustomValidity'):
        assert text in html, text
    for text in ('KT durumu', 'Excel indir (.xlsx)'):
        assert text not in html, text


# ---- 7. İşlem geçmişi: proje kaydı 'kayit #BETA' değil 'Proje: BETA' ----------------------------------
def test_audit_target_label_for_project_and_missing_record(web):
    c, a = web; login(c)
    conn = db.baglan(a['DB'])
    beta = katalog.get_project(conn, 'BETA')
    katalog.save_project(conn, 'BETA', 'Beta deneme', '#FFA500', active=True, actor='testadmin', expected_revision=beta['revision'])
    row = conn.execute("SELECT hedef_turu,hedef_id FROM denetim WHERE islem='katalog_proje_kaydet' ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ('proje', 'BETA')
    katalog.save_category(conn, 'ozel_kat', 'Özel kategori', mode='custom', projects=['OF'], questions=[{'key': 'not', 'label': 'Not', 'type': 'text', 'required': False, 'options': []}], active=True, actor='testadmin')
    row = conn.execute("SELECT hedef_turu,hedef_id FROM denetim WHERE islem='katalog_kategori_kaydet' ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(row) == ('kategori', 'ozel_kat')
    with db.transaction(conn):
        # 2.1'den kalan eski satır: proje kaydı 'kayit' hedef türüyle yazılmıştı.
        conn.execute("INSERT INTO denetim(zaman,kullanici,islem,proje,anahtar,hedef_turu,hedef_id) VALUES(?,?,?,?,?,?,?)", (db.simdi(), 'eski', 'katalog_proje_kaydet', 'PA', 'PA', 'kayit', 'PA'))
        conn.execute("INSERT INTO denetim(zaman,kullanici,islem,proje,anahtar,hedef_turu,hedef_id) VALUES(?,?,?,?,?,?,?)", (db.simdi(), 'eski', 'sil', 'OF', 'tg:silinmis:1', 'kayit', 'tg:silinmis:1'))
    conn.close()
    html = c.get('/denetim').data.decode()
    assert 'Proje: BETA' in html and 'Proje: PA' in html and 'Kategori: ozel_kat' in html
    assert 'Kayıt #BETA' not in html and 'Kayıt #PA' not in html and 'ac=BETA' not in html
    assert 'Kayıt anahtarı: tg:silinmis:1' in html and 'Kayıt #tg:silinmis:1' not in html
    assert 'Proje kaydı<br><code>katalog_proje_kaydet</code>' in html


# ---- 8. /saglik ve statik dosyalar çerez üretmez --------------------------------------------------------
def test_health_and_static_do_not_set_session_cookie(web):
    c, a = web
    r = c.get('/saglik')
    assert r.status_code == 200 and r.headers.get('X-Kanit-Paneli') == '2.2.0' and 'Set-Cookie' not in r.headers
    r = c.get('/static/stil.css?v=2.2.3')
    assert r.status_code == 200 and 'Set-Cookie' not in r.headers
    assert 'kanit_session=' in c.get('/giris').headers.get('Set-Cookie', '')
    login(c)
    assert 'Set-Cookie' not in c.get('/saglik').headers


# ---- 9. Bildirim zili: kayıt numarası + personel, en çok 15 öğe + Tümünü gör --------------------------
def test_notification_feed_carries_record_fields_and_js_caps_list(web):
    c, a = web; login(c)
    for i in range(23):
        seed(a, key='tg:zil:%d' % i, picture=False)
    data = c.get('/bildirim.json').json
    assert data['okunmamis'] == 23 and len(data['bildirimler']) == 20
    item = data['bildirimler'][0]
    assert item['kayit_id'] and item['personel'] == '00123' and item['kategori'] == 'HGST' and item['metin'] == 'Yeni kanıt eklendi'
    js = (STATIC / 'panel.js').read_text(encoding='utf-8')
    assert 'var LIMIT=15' in js and 'Tümünü gör' in js and "bildirim-kayit" in js and "'#'+esc(kid)" in js
    css = (STATIC / 'stil.css').read_text(encoding='utf-8')
    assert '.bildirim-kutu li .bildirim-kayit' in css


# ---- 10. Kullanıcılar: geçici şifre kutusu ve Türkçe desen ipuçları -----------------------------------
def test_temporary_password_box_and_turkish_validation_hints(web):
    c, a = web; login(c)
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'ekle', 'ad': 'yeni.kisi', 'rol': 'admin', 'projeler': 'OF', 'eylemler_OF': 'kt'})
    assert r.status_code == 302
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'id="gecici-sifre"' in html and 'Şifreyi kopyala' in html and 'data-kopyala="' in html and 'Üretilen geçici şifre' in html
    sifre = html.split('id="gecici-sifre-deger">')[1].split('<')[0]
    assert len(sifre) >= 15 and 'data-kopyala="' + sifre + '"' in html
    # Sayfa yenilenince kutu kaybolur; şifre flash şeridinde tekrar görünmez.
    again = c.get('/yonetim/kullanicilar').data.decode()
    assert 'id="gecici-sifre"' not in again and sifre not in again
    # Üretilen şifreyle giriş mümkün.
    c2 = c.application.test_client()
    c2.get('/giris')
    with c2.session_transaction() as s:
        tk = s['csrf']
    assert c2.post('/giris', data={'csrf': tk, 'kullanici': 'yeni.kisi', 'sifre': sifre}).status_code == 302
    # Geçici şifre üretme işlemi de kutuyu getirir.
    user = kullanicilar.bul(a, 'yeni.kisi')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'sifre', 'ad': 'yeni.kisi', 'expected_version': user['session_version']})
    assert r.status_code == 302
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'id="gecici-sifre"' in html and 'için geçici şifre üretildi' in html
    assert 'data-gecersiz="Kullanıcı adı yalnız küçük harf, rakam, nokta ve alt çizgi içerebilir' in html and 'data-bos="Kullanıcı adı zorunludur."' in html
    js = (STATIC / 'panel.js').read_text(encoding='utf-8')
    assert "addEventListener('invalid'" in js and 'data-gecersiz' in js and 'setCustomValidity' in js


# ---- QA 1.1: kullanıcı düzenleme formu 500 vermez (guncelle() 'ad' çakışması) -------------------------
def test_user_edit_form_saves_display_name_scope_and_flags(web):
    c, a = web; login(c)
    kullanicilar.ekle(a, 'duzenlenen', 'OF:oku,kt', 'Test-Password-123!', 'Eski Ad')
    user = kullanicilar.bul(a, 'duzenlenen')
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'duzenlenen', 'expected_version': user['session_version'],
                                               'gorunen_ad': 'Yeni Ad', 'rol': 'admin', 'projeler': ['OF', 'PA'], 'eylemler_OF': ['kt', 'duzenle'], 'eylemler_PA': ['kt'], 'aktif': '1', 'sifredegistir': '1'})
    assert r.status_code == 302, r.data[:200]
    user = kullanicilar.bul(a, 'duzenlenen')
    assert user['ad'] == 'Yeni Ad' and user['yetki'] == 'OF:oku,gorsel,kt,duzenle;PA:oku,gorsel,kt' and user['sifre_degistir'] == 1 and user['aktif'] == 1
    html = c.get('/yonetim/kullanicilar').data.decode()
    assert 'Hesap ve açık proje kapsamı kaydedildi.' in html and 'Yeni Ad' in html
    # Pasife alma ve aynı sürümle ikinci kayıt denemesi (çakışma) okunur hata verir, 500 değil.
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'duzenlenen', 'expected_version': user['session_version'], 'gorunen_ad': 'Yeni Ad', 'rol': 'admin', 'projeler': ['OF'], 'eylemler_OF': ['kt']})
    assert r.status_code == 302 and kullanicilar.bul(a, 'duzenlenen')['aktif'] == 0
    r = c.post('/yonetim/kullanicilar', data={'csrf': csrf(c), 'islem': 'guncelle', 'ad': 'duzenlenen', 'expected_version': user['session_version'], 'rol': 'admin', 'projeler': ['OF'], 'aktif': '1'})
    assert r.status_code == 200 and 'başka bir admin tarafından değiştirildi' in r.data.decode()
    assert kullanicilar.guncelle(a, 'duzenlenen', gorunen_ad='')['ad'] == 'duzenlenen'


# ---- 11. Kanıt Kontrolü: TXT notu nötr bilgi kutusu, sade Türkçe metinler ---------------------------
def test_evidence_check_txt_note_is_neutral_and_texts_are_plain(web):
    c, a = web; login(c)
    r = c.post('/excel-kontrol', data={'csrf': csrf(c), 'islem': 'yukle', 'excel': (io.BytesIO(b'00123\n00099\n'), 'liste.txt')}, content_type='multipart/form-data')
    assert r.status_code == 200
    html = r.data.decode()
    assert 'id="kaynak-notlari"' in html and 'class="bilgi notr"' in html and 'TXT ID modunda' in html
    assert 'class="bilgi uyari"' not in html and 'uyari-serit' not in html
    for text in ('Dosyayı yükle', 'Önizlemeyi yenile', 'Kayıtlarla karşılaştır', 'Onay durumu', 'Yetkili olduğum tüm projeler', 'Karakter kodlaması'):
        assert text in html, text
    for text in ('boolean', 'snapshot', 'interval', 'KT durumu', 'Projeyi sabitle', 'Yükle ve incele'):
        assert text not in html, text
    r = c.post('/excel-kontrol', data={'csrf': csrf(c), 'islem': 'kontrol', 'id_field': 'personel', 'alan': 'personel', 'project': '', 'kt': 'hepsi', 'header_row': '0', 'text_mode': 'ids'})
    html = r.data.decode()
    assert 'Tüm sonucu Excel olarak indir' in html and 'Yalnız bulunamayanları indir' in html and 'onay durumu: hepsi' in html and 'TXT ID listesi' in html


# ---- 12. Arama kapsamı: açıklama, ekleyen ve kategori ---------------------------------------------------
def test_search_covers_description_adder_and_category(web):
    c, a = web; login(c); seed(a)
    for q, expected in (('Özgün', 1), ('tgtester', 1), ('hgst', 1), ('00123', 1), ('olmayan-metin', 0)):
        assert c.get('/disa-aktar.xlsx?durum=hepsi&sayim=1&q=' + q).json['adet'] == expected, q
        page = c.get('/kayitlar?durum=hepsi&q=' + q).data.decode()
        assert ('<b>%d</b> kayıt' % expected) in page, q
    html = c.get('/').data.decode()
    assert 'id="ana-arama-ipucu"' in html and 'açıklama, ekleyen ve kategori' in html and 'aria-describedby="ana-arama-ipucu"' in html


# ---- Ek kontroller: önbellek sürümü, tablolu sayfalarda taşma önlemi ---------------------------------
def test_asset_version_and_table_wrapper_rule(web):
    c, a = web; login(c)
    for url in ('/bot', '/denetim', '/yonetim/kullanicilar', '/arsiv', '/bildirimler'):
        html = c.get(url).data.decode()
        assert 'stil.css?v=2.2.3' in html and 'panel.js?v=2.2.3' in html, url
    css = (STATIC / 'stil.css').read_text(encoding='utf-8')
    assert '.tablo-sarici, .kaydir, .tablo-kaydir { position: relative; max-width: 100%; }' in css
    assert '.iki-kolon > *, .kullanici-izgara > *' in css and '.kullanici-listesi .tablo { min-width: 0; }' in css
    assert '.bot-islem-izgara { grid-template-columns: 1fr; }' in css
