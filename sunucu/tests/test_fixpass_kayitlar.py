# -*- coding: utf-8 -*-
"""2.2 düzeltme turu (kayıtlar alanı, madde 13–25): 404/arşiv mesajları, küçük resim klasörü, bozuk görsel,
kategori seçimi, Gyazo iş durumu, derin bağlantı, telefon düzeni, arama rozeti, ters tarih uyarısı."""
import io
import os
import re
import shutil
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, kullanicilar  # noqa: E402
from test_web import web, seed, login, csrf  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
GID = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'row:' + str(time.time_ns())); cols.setdefault('guncelleme', db.simdi())
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def png(path, size=(40, 30), color=(0, 120, 255)):
    Image.new('RGB', size, color).save(path, 'PNG'); return str(path)


def static(name):
    return (ROOT / 'app' / 'static' / name).read_text(encoding='utf-8')


def template(name):
    return (ROOT / 'app' / 'templates' / name).read_text(encoding='utf-8')


# ---------------------------------------------------------------- 13: olmayan kayıt 404, arşiv satır içi mesaj
def test_missing_record_is_404_everywhere_and_archive_link_reports_inline(web):
    c, a = web; login(c)
    for url in ('/kayit/424242', '/gorsel/424242', '/kucuk/424242'):
        r = c.get(url); assert r.status_code == 404, url
        assert 'bulunamadı' in r.json['hata']
    assert c.post('/kayit/424242/kt', data={'csrf': csrf(c)}).status_code == 404
    # Arşiv: yanlış kayıt numarası hata sayfası yerine arşiv sayfasında okunur mesaj
    arsiv = Path(a['ARSIV_KLASOR']) / 'IMG_1.jpg'; png(arsiv)
    con = db.baglan(a['DB'])
    with db.transaction(con):
        aid = con.execute('INSERT INTO arsiv_dosyalar(yol,ad,proje,guncelleme) VALUES(?,?,?,?)', (str(arsiv.resolve()), 'IMG_1.jpg', 'OF', db.simdi())).lastrowid
    con.close()
    r = c.post('/arsiv', data={'csrf': csrf(c), 'islem': 'esle', 'arsiv_id': aid, 'kayit_id': 999999}, follow_redirects=True)
    body = r.data.decode()
    assert r.status_code == 200 and 'Kayıt bulunamadı' in body and '#999999' in body and 'Hata 403' not in body and 'Hata 404' not in body
    # Yetkisiz proje: 403 sayfası yerine açıklama
    account(a, 'ofedit', 'OF:oku,kt,duzenle'); pa = seed(a, 'PA', 'pa:1', picture=False)
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofedit')
    assert c.get('/arsiv').status_code == 403  # arşiv sayfası süperadmin işi; yalnız rota mesajı değişti
    c.post('/cikis', data={'csrf': csrf(c)}); login(c)
    r = c.post('/arsiv', data={'csrf': csrf(c), 'islem': 'esle', 'arsiv_id': aid, 'kayit_id': pa}, follow_redirects=True)
    assert 'ilişkilendirildi' in r.data.decode()
    con = db.baglan(a['DB']); row = con.execute('SELECT gorsel_dosya FROM kayitlar WHERE id=?', (pa,)).fetchone(); con.close()
    assert row['gorsel_dosya'] == str(arsiv.resolve())


# ---------------------------------------------------------------- 19: "zaten görsel var" açıklaması + Değiştir onayı
def test_archive_link_existing_image_explains_and_replace_checkbox_works(web):
    c, a = web; login(c); kid = seed(a)
    arsiv = Path(a['ARSIV_KLASOR']) / 'IMG_2.jpg'; png(arsiv, color=(9, 9, 9))
    con = db.baglan(a['DB'])
    with db.transaction(con):
        aid = con.execute('INSERT INTO arsiv_dosyalar(yol,ad,proje,guncelleme) VALUES(?,?,?,?)', (str(arsiv.resolve()), 'IMG_2.jpg', 'OF', db.simdi())).lastrowid
    con.close()
    r = c.post('/arsiv', data={'csrf': csrf(c), 'islem': 'esle', 'arsiv_id': aid, 'kayit_id': kid}, follow_redirects=True)
    body = r.data.decode()
    assert r.status_code == 200 and 'zaten bir görsel bağı var' in body and 'değiştir' in body.lower() and 'test.png' in body
    assert 'Kayıt değişti' not in body and 'Hata 409' not in body
    r = c.post('/arsiv', data={'csrf': csrf(c), 'islem': 'esle', 'arsiv_id': aid, 'kayit_id': kid, 'degistir': '1'}, follow_redirects=True)
    assert 'ilişkilendirildi' in r.data.decode()
    con = db.baglan(a['DB']); row = con.execute('SELECT gorsel_dosya FROM kayitlar WHERE id=?', (kid,)).fetchone(); con.close()
    assert row['gorsel_dosya'] == str(arsiv.resolve())


# ---------------------------------------------------------------- 14: thumbs klasörü çalışma anında silinirse
def test_thumbnail_folder_recreated_at_runtime(web):
    c, a = web; login(c); kid = seed(a)
    assert c.get(f'/kucuk/{kid}').status_code == 200
    thumbs = Path(a['ONBELLEK']) / 'thumbs'; assert thumbs.is_dir()
    shutil.rmtree(thumbs)
    r = c.get(f'/kucuk/{kid}')
    assert r.status_code == 200 and thumbs.is_dir() and list(thumbs.glob('*.jpg')) and 'svg' not in r.headers['Content-Type']
    shutil.rmtree(thumbs)
    kid2 = insert(a, gorsel_dosya=png(Path(a['GORSEL_KLASOR']) / 'ikinci.png', color=(1, 2, 3)), personel='B')
    assert c.get(f'/kucuk/{kid2}').status_code == 200 and thumbs.is_dir()


# ---------------------------------------------------------------- 15: bozuk görsel → yer tutucu, listede "Görsel açılamadı"
def test_corrupt_image_gets_placeholder_not_raw_bytes(web):
    c, a = web; login(c)
    bad = Path(a['GORSEL_KLASOR']) / 'bozuk.jpg'; bad.write_bytes(b'\xff\xd8\xff bozuk veri ' * 20)
    kid = insert(a, gorsel_dosya=str(bad), personel='BOZUK')
    for url in (f'/kucuk/{kid}', f'/gorsel/{kid}'):
        r = c.get(url)
        assert r.status_code == 200 and r.headers['Content-Type'].startswith('image/svg+xml') and r.headers['X-Gorsel-Durum'] == 'bozuk', url
        assert 'Görsel açılamadı' in r.data.decode('utf-8') and b'bozuk veri' not in r.data
    # İndirme isteği ham dosyayı yine verir (yerel inceleme için)
    r = c.get(f'/gorsel/{kid}?indir=1'); assert r.status_code == 200 and b'bozuk veri' in r.data and 'attachment' in r.headers['Content-Disposition']
    d = c.get(f'/kayit/{kid}').json
    assert d['gorsel_bozuk'] is True and d['gorsel_var'] and d['indir_url']
    ok = seed(a); assert c.get(f'/kayit/{ok}').json['gorsel_bozuk'] is False
    assert c.get(f'/kucuk/{ok}').headers['Content-Type'].startswith('image/jpeg')
    css = static('kayit.css'); assert "content: 'Görsel açılamadı'" in css and "content: 'Görsel yok'" not in css
    js = static('panel.js'); assert 'gorsel_bozuk' in js and 'Dosya sunucuda var ama bozuk' in js
    # Liste sayfası yer tutucu için 4xx istek üretmez
    assert c.get('/kayitlar?durum=hepsi').status_code == 200


# ---------------------------------------------------------------- 16: küçük/karışık harfli kategori seçimi korunur
def test_lowercase_category_filter_keeps_selection(web):
    c, a = web; login(c)
    insert(a, kategori='30gün', personel='K1'); insert(a, kategori='Saha ziyareti', personel='K2'); seed(a)
    html = c.get('/kayitlar?durum=hepsi&kategori=30gün').data.decode()
    assert re.search(r'<option value="30gün" selected>30gün</option>', html) and '(seçili projelerde yok)' not in html
    assert html.count('class="kayit ') == 1 and 'K1' in html
    html = c.get('/kayitlar', query_string={'durum': 'hepsi', 'kategori': 'SAHA ZİYARETİ'}).data.decode()
    assert 'K2' in html and html.count('class="kayit ') == 1 and 'selected>Saha ziyareti<' in html
    html = c.get('/kayitlar', query_string={'durum': 'hepsi', 'kategori': '30GÜN'}).data.decode()
    assert 'K1' in html and html.count('class="kayit ') == 1 and 'selected>30gün<' in html
    html = c.get('/kayitlar?durum=hepsi&kategori=yokboyle').data.decode()
    assert 'yokboyle (seçili projelerde yok)' in html and html.count('class="kayit ') == 0


# ---------------------------------------------------------------- 17/18/20: XHR hata mesajı, klavye, sayaç (kaynak denetimi)
def test_js_error_keyboard_and_counter_wiring():
    js = static('panel.js')
    kayit = js[js.index('function kayitSayfasi'):js.index('function initRecordFilters')]
    # 17: 409 → gerçek mesaj gösterilir ve pencere yeniden yüklenir
    assert "if(e.status===409){toast(e.message,true);openRecord(k.id,acan);}" in kayit
    assert "function kayitHata(status,d){var e=new Error((d&&d.hata)||HATA_METIN[status]" in js
    # 18: ok tuşları yalnız yazı alanlarında engellenir (düğme sayılmaz)
    assert "(e.key==='ArrowLeft'||e.key==='ArrowRight')&&!yaziAlani(e.target)&&!formOpen()" in kayit
    assert "n==='input'||n==='textarea'||n==='select'||!!t.isContentEditable" in js
    assert "editable(e.target)" not in kayit
    # 20: onay/sil sonrası sekme sayaçları ve satır rozeti güncellenir
    assert "function sayacGuncelle(card,action,r)" in kayit and "bump('bekleyen',r.kt?-1:1);bump('onayli',r.kt?1:-1)" in kayit
    assert "rz.className='durum-rozet '+(r.kt?'onayli':'bekliyor')" in kayit
    # 25: kapatırken kaydedilmemiş düzenleme sorusu, işlem hatası kutusu, silinmiş kayıt açıklaması
    assert 'Kaydedilmemiş düzenleme var' in kayit and "if(!force&&!leaveOk())return" in kayit
    assert 'Son otomatik işlem başarısız oldu' in kayit and 'Geri alma yetkiniz olmadığı için' in kayit
    assert "modal.querySelector('.modal-kapat').addEventListener('click',function(){closeRecord();})" in kayit


# ---------------------------------------------------------------- 21: Gyazo iş durumu, hata metni, deneme sayısı, tekrar dene
def test_gyazo_job_status_error_and_retry(web, monkeypatch):
    from app import panel
    c, a = web; login(c); kid = seed(a)
    monkeypatch.setenv('GYAZO_TOKEN', 'test-token')
    d = c.get(f'/kayit/{kid}').json
    assert d['gyazo_hazir'] and d['gyazo_is'] is None and d['gyazo_bekliyor'] is False
    r = c.post(f'/kayit/{kid}/gyazo', data={'csrf': csrf(c), 'surum': d['surum']}).json
    assert r['pending'] and r['durum'] == 'bekliyor' and r['durum_adi'] == 'Sırada bekliyor' and r['deneme'] == 0 and r['tekrar_olur'] is False
    # Tekrar istek: ikinci iş açılmaz, "zaten sürüyor" mesajı
    r2 = c.post(f'/kayit/{kid}/gyazo', data={'csrf': csrf(c)}).json
    assert r2['pending'] and 'zaten sürüyor' in r2['mesaj']
    con = db.baglan(a['DB'])
    assert con.execute('SELECT COUNT(*) FROM donusum_isleri WHERE record_id=?', (kid,)).fetchone()[0] == 1
    with db.transaction(con):
        con.execute("UPDATE donusum_isleri SET durum='tekrar',deneme=2,hata='Gyazo bağlantısı kurulamadı (zaman aşımı)' WHERE record_id=?", (kid,))
    con.close()
    s = c.get(f'/kayit/{kid}/gyazo-durum').json
    assert s['pending'] and s['durum'] == 'tekrar' and s['durum_adi'] == 'Yeniden denenecek' and s['deneme'] == 2 and 'zaman aşımı' in s['hata'] and '2. deneme' in s['mesaj']
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("UPDATE donusum_isleri SET durum='hata',deneme=3,hata='Gyazo bağlantısı kurulamadı (zaman aşımı)' WHERE record_id=?", (kid,))
    con.close()
    s = c.get(f'/kayit/{kid}/gyazo-durum').json
    assert not s['pending'] and s['durum'] == 'hata' and s['durum_adi'] == 'Başarısız' and s['deneme'] == 3 and s['tekrar_olur'] is True and '3 deneme' in s['mesaj']
    d = c.get(f'/kayit/{kid}').json
    assert d['gyazo_is']['durum'] == 'hata' and d['gyazo_is']['tekrar_olur'] and d['gyazo_bekliyor'] is False
    # tekrar=1 olmadan: yeni iş açılmaz, "Tekrar dene" yönlendirmesi
    r = c.post(f'/kayit/{kid}/gyazo', data={'csrf': csrf(c)}).json
    assert not r['pending'] and 'Tekrar dene' in r['mesaj']
    con = db.baglan(a['DB']); assert con.execute('SELECT COUNT(*) FROM donusum_isleri WHERE record_id=?', (kid,)).fetchone()[0] == 1; con.close()
    # tekrar=1: biten iş canlandırılmaz, yeni iş kaydı açılır
    r = c.post(f'/kayit/{kid}/gyazo', data={'csrf': csrf(c), 'tekrar': '1'}).json
    assert r['pending'] and r['durum'] == 'bekliyor' and r['deneme'] == 0
    con = db.baglan(a['DB'])
    rows = con.execute('SELECT job_key,durum FROM donusum_isleri WHERE record_id=? ORDER BY id', (kid,)).fetchall(); con.close()
    assert len(rows) == 2 and rows[0]['durum'] == 'hata' and rows[1]['durum'] == 'bekliyor' and ':tekrar' in rows[1]['job_key']
    con = db.baglan(a['DB']); assert con.execute("SELECT COUNT(*) FROM denetim WHERE islem='gyazo_istek'").fetchone()[0] == 2; con.close()
    # Arayüz: durum kutusu ve "tekrar dene" düğmesi
    js = static('panel.js'); assert 'function renderGyazo' in js and 'data-tekrar="1"' in js and 'Gyazo’yu tekrar dene' in js
    assert 'id="m-gyazo"' in template('kayitlar.html')
    # Anahtar yokken açıklama
    monkeypatch.delenv('GYAZO_TOKEN')
    assert c.post(f'/kayit/{kid}/gyazo', data={'csrf': csrf(c)}).status_code == 400
    assert panel.GYAZO_DURUM_ADLARI['belirsiz'] == 'Sonuç belirsiz'


# ---------------------------------------------------------------- 22: kategori listeden seçilir
def test_edit_category_must_come_from_project_catalog(web):
    c, a = web; account(a, 'ofedit', 'OF:oku,kt,duzenle'); login(c); kid = seed(a)
    html = template('kayitlar.html')
    assert '<select name="kategori" id="m-kategori-secim">' in html and 'list="kategori-listesi"' not in html and 'datalist' not in html
    cats = c.get('/kategoriler.json?proje=OF').json['kategoriler']; assert 'HGST' in cats
    # Süperadmin bile tanımsız kategori yazamaz: 400 + okunur mesaj
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': 'YENIKAT'})
    assert r.status_code == 400 and 'OF projesinde tanımlı değil' in r.json['hata'] and 'Katalog' in r.json['hata']
    # Büyük/küçük harf farkı listedeki adla eşlenir
    assert c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': 'hgst', 'personel': 'yeni'}).json['ok']
    con = db.baglan(a['DB']); row = con.execute('SELECT kategori FROM kayitlar WHERE id=?', (kid,)).fetchone(); con.close()
    assert row['kategori'] == 'HGST'
    # Mevcut değer değişmiyorsa (eski kayıtlarda tanımsız kategori) kabul edilir
    old = insert(a, kategori='ESKIKAT', personel='E')
    assert c.post(f'/kayit/{old}/duzenle', data={'csrf': csrf(c), 'kategori': 'ESKIKAT', 'personel': 'E2'}).json['ok']
    assert c.post(f'/kayit/{old}/duzenle', data={'csrf': csrf(c), 'kategori': ''}).json['ok']
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofedit')
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'kategori': 'YOK_BOYLE'})
    assert r.status_code == 403 and 'tanımlı değil' in r.json['hata']
    js = static('panel.js'); assert "kayitIstek('/kategoriler.json?proje='+encodeURIComponent(k.proje||''))" in js and 'bu projede tanımlı değil' in js


# ---------------------------------------------------------------- 23: ?ac derin bağlantı adres çubuğunda kalır
def test_deep_link_stays_in_url_and_navigation_links_drop_it(web):
    c, a = web; login(c); kid = seed(a)
    html = c.get(f'/kayitlar?durum=hepsi&ac={kid}').data.decode()
    assert f'data-acik="{kid}"' in html
    # Sekme/görünüm/sayfa bağlantıları ac taşımaz (başka sekmeye geçince kayıt yeniden açılmaz)
    for m in re.finditer(r'href="(/kayitlar\?[^"]*)"', html):
        assert 'ac=' not in m.group(1), m.group(1)
    assert c.get('/kayitlar?durum=hepsi&ac=abc').status_code == 200
    js = static('panel.js')
    assert "u.searchParams.delete('ac');history.replaceState(null,''" not in js
    assert "function urlAc(id)" in js and "urlAc(id)" in js and "urlAc(null)" in js
    assert "if(n.i<0){toast('Bu kayıt şu anki listede yok" in js


# ---------------------------------------------------------------- 24: telefon düzeni
def test_phone_layout_rules_and_card_bulk_select(web):
    c, a = web; login(c); seed(a); insert(a, personel='B')
    css = static('kayit.css')
    phone = css[css.index('@media (max-width: 700px)'):]
    assert '.kayit-sayfa .kayit-tablo { min-width: 0; display: block;' in phone
    assert 'grid-template-areas: "sec gorsel personel personel islem"' in phone and '[data-toplu-kt="0"] .kayit-tablo tbody tr.kayit' in phone
    assert 'min-height: 40px' in phone and '.kayit-sayfa .eylem-cubugu { position: sticky; bottom: 0;' in css
    html = c.get('/kayitlar?durum=hepsi').data.decode()
    for cls in ('k-gorsel', 'k-proje', 'k-kategori', 'k-personel', 'k-uye', 'k-tarih', 'k-ekleyen', 'k-durum', 'k-islem'):
        assert f'<td class="{cls}' in html, cls
    assert 'class="eylem-cubugu"' in html and 'id="m-eylem-notu"' in html and 'id="m-uyari"' in html
    # Kart görünümünde toplu seçim kutuları ve "Sayfadakileri seç"
    kart = c.get('/kayitlar?durum=hepsi&gorunum=kart').data.decode()
    assert kart.count('class="kart-sec"') == 2 and 'id="sec-hepsi"' in kart and 'Sayfadakileri seç' in kart
    galeri = c.get('/kayitlar?durum=hepsi&gorunum=galeri').data.decode()
    assert 'kart-sec' not in galeri and 'id="sec-hepsi"' not in galeri
    account(a, 'reader', 'OF:oku'); c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'reader')
    assert 'kart-sec' not in c.get('/kayitlar?durum=hepsi&gorunum=kart').data.decode()


# ---------------------------------------------------------------- (c) uzun değerler, (e) arama rozeti, (f) ters tarih uyarısı, arama kapsamı
def test_long_values_search_badge_and_date_warning(web):
    c, a = web; login(c)
    long_p = 'PERSONEL-' + 'X' * 60; long_u = 'U' * 50
    kid = insert(a, personel=long_p, uye_id=long_u, aciklama='Müşteri ekran görüntüsü', ekleyen_ad='Ayşe K.', kategori='HGST')
    html = c.get('/kayitlar?durum=hepsi').data.decode()
    assert f'<td class="k-personel" title="{long_p}">' in html and f'<td class="k-uye" title="{long_u}">' in html
    css = static('kayit.css'); assert '.kayit-sayfa .kayit-tablo td { overflow-wrap: anywhere;' in css and 'td.k-personel { max-width: 220px; }' in css
    # Arama rozeti + Aramayı temizle (ana sayfadan gelen ?q=)
    html = c.get('/kayitlar?durum=hepsi&q=ekran').data.decode()
    assert 'id="arama-rozet"' in html and 'Arama: <b>ekran</b>' in html and 'Aramayı temizle' in html and html.count('class="kayit ') == 1
    link = re.search(r'class="arama-temizle"', html); assert link
    temizle = re.search(r'href="([^"]+)" class="arama-temizle"', html).group(1).replace('&amp;', '&')
    assert 'q=' not in temizle and 'durum=hepsi' in temizle
    assert 'id="arama-rozet"' not in c.get('/kayitlar?durum=hepsi').data.decode()
    # Arama kapsamı: açıklama, ekleyen, kategori
    for q in ('ekran', 'Ayşe', 'hgst'):
        assert str(kid) in c.get('/kayitlar?durum=hepsi&q=' + q).data.decode(), q
    assert 'açıklama, ekleyen ve kategori içinde arar' in html
    # Ters tarih: 400 yerine satır içi uyarı ve düzeltilmiş aralık
    r = c.get('/kayitlar?durum=hepsi&tarih1=2026-12-31&tarih2=2026-01-01')
    body = r.data.decode()
    assert r.status_code == 200 and 'yer değiştirildi' in body and 'value="2026-01-01"' in body and 'value="2026-12-31"' in body and 'Hata 400' not in body
    assert 'class="filtre-uyari "' in body and str(kid) in body
    r = c.get('/kayitlar?durum=hepsi&tarihsiz=1&tarih1=2026-01-01'); assert r.status_code == 200 and 'seçimi kaldırıldı' in r.data.decode()
    assert c.get('/kayitlar?durum=hepsi&tarih1=bozuk').status_code == 400
    # Boş görünümde Excel düğmesi pasif
    body = c.get('/kayitlar?durum=hepsi&q=olmayan-sey').data.decode()
    assert 'aria-disabled="true" title="Bu görünümde kayıt olmadığı için' in body and 'aramayı temizleyin' in body
