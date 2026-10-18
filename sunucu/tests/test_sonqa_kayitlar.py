# -*- coding: utf-8 -*-
"""Son QA düzeltme turu (kayıtlar ekibi, K1–K8): toplu araç çubuğu Yenile sonrası, geçmişte silme sebebi,
kayıp görsel dosyası, kendi işlemi sonrası şerit, boş yorum uyarısı, tarayıcıda açılan /kayit /gorsel /kucuk
adresleri için Türkçe HTML hata sayfası, yetkisiz ?ac= penceresi, telefonda ≥40px form alanları."""
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db, kullanicilar  # noqa: E402
from test_web import web, seed, login, csrf  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
XHR = {'X-Requested-With': 'XMLHttpRequest'}
HTML = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'row:' + str(time.time_ns())); cols.setdefault('guncelleme', db.simdi())
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def png(path, color=(0, 120, 255)):
    Image.new('RGB', (40, 30), color).save(path, 'PNG'); return str(path)


def static(name):
    return (ROOT / 'app' / 'static' / name).read_text(encoding='utf-8')


def template(name):
    return (ROOT / 'app' / 'templates' / name).read_text(encoding='utf-8')


def js_kayit_bolumu():
    js = static('panel.js'); return js[js.index('function topluKur('):js.index('function initRecordFilters(')]


# ---------------------------------------------------------------- K1: toplu araç çubuğu Yenile sonrası
def test_k1_bulk_toolbar_is_looked_up_per_update_and_delegated(web):
    c, a = web; login(c); seed(a); insert(a, personel='B')
    js = js_kayit_bolumu()
    toplu = js[js.index('function topluKur('):js.index('function kayitSayfasi(')]
    # Öğe bir kez yakalanmıyor: her güncellemede DOM'dan alınır
    assert "var arac=document.getElementById('toplu-arac');" not in toplu
    assert "function arac(){return document.getElementById('toplo-arac');}" not in toplu
    assert "function arac(){return document.getElementById('toplu-arac');}" in toplu and 'var bar=arac()' in toplu
    assert "arac.addEventListener('click'" not in toplu
    # Düğmeler document düzeyinde delege: '#toplu-arac [data-toplu]'
    assert "t.closest('#toplu-arac [data-toplu]')" in toplu and "t.closest('#toplu-arac [data-toplu-temizle]')" in toplu
    assert 'function clear(){' in toplu and 'return {update:update,selected:selected,clear:clear};' in toplu
    # Yenile sonrası seçim sıfırlanır (eski DOM dışı öğe güncellenmez)
    yenile = js[js.index('function refreshResults('):js.index('function formOpen(')]
    assert 'old.replaceWith(fresh)' in yenile and 'toplu.clear();' in yenile and 'toplu.update();' not in yenile
    # Yenilenen HTML aynı araç çubuğunu ve kutuları taşır (toplu onay yetkisi olan kullanıcı)
    html = c.get('/kayitlar?durum=hepsi', headers=XHR).data.decode()
    assert 'id="toplu-arac"' in html and html.count('class="kayit-sec"') == 2 and 'id="sec-hepsi"' in html
    # Sunucu toplu onayı: yanıt damga taşır
    ids = [int(x) for x in re.findall(r'class="kayit-sec" value="(\d+)"', html)]
    r = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': ids, 'deger': '1'})
    assert r.status_code == 200 and r.json['degisen'] == 2 and r.json['damga'] and 'onaylandı' in r.json['mesaj']


# ---------------------------------------------------------------- K2: silme sebebi ve okunur geçmiş satırları
def test_k2_record_history_carries_delete_reason(web):
    c, a = web; login(c); kid = seed(a)
    d = c.get(f'/kayit/{kid}', headers=XHR).json
    assert c.post(f'/kayit/{kid}/kt', data={'csrf': csrf(c), 'deger': '1', 'surum': d['surum']}).json['kt'] == 1
    assert c.post(f'/kayit/{kid}/sil', data={'csrf': csrf(c), 'sebep': 'yanlış proje'}).json['ok']
    gecmis = c.get(f'/kayit/{kid}', headers=XHR).json['gecmis']
    sil = next(h for h in gecmis if h['islem'] == 'sil'); onay = next(h for h in gecmis if h['islem'] == 'onayla')
    assert sil['aciklama'] == 'yanlış proje' and sil['kullanici'] == 'testadmin'
    assert 'aciklama' in onay and onay['aciklama'] is None
    js = js_kayit_bolumu()
    assert "h.islem==='sil'?'Sebep: ':'Not: '" in js and "esc(h.aciklama)" in js
    assert "onayla:'Onaylandı',onay_kaldir:'Onay kaldırıldı'" in static('panel.js') and "sil:'Silindi'" in static('panel.js')
    # JSON'da Türkçe karakterler kaçışsız
    raw = c.get(f'/kayit/{kid}', headers=XHR).data.decode('utf-8')
    assert 'yanlış proje' in raw and '\\u0131' not in raw


# ---------------------------------------------------------------- K3: dosyası sunucuda olmayan kayıt ayrı durum
def test_k3_missing_file_is_distinguished_from_no_image(web):
    c, a = web; login(c)
    yok = insert(a, personel='HICYOK')                                                   # hiç görseli yok
    kayip = insert(a, personel='KAYIP', gorsel_dosya=str(Path(a['GORSEL_KLASOR']) / 'alt' / 'silinmis-dosya.png'))  # yol var, dosya yok
    var = seed(a)
    d_yok = c.get(f'/kayit/{yok}', headers=XHR).json; d_kayip = c.get(f'/kayit/{kayip}', headers=XHR).json; d_var = c.get(f'/kayit/{var}', headers=XHR).json
    assert d_yok['gorsel_kaynak'] == 'yok' and d_yok['gorsel_kayip'] is False and d_yok['gorsel_dosya_adi'] is None
    assert d_kayip['gorsel_kaynak'] == 'kayip' and d_kayip['gorsel_kayip'] is True and d_kayip['gorsel_dosya_adi'] == 'silinmis-dosya.png'
    assert not d_kayip['gorsel_var'] and d_kayip['gorsel_url'] is None and 'gorsel_dosya' not in d_kayip  # tam yol sızmaz
    assert d_var['gorsel_kaynak'] == 'yerel' and d_var['gorsel_kayip'] is False
    for view in ('tablo', 'kart', 'galeri'):
        html = c.get(f'/kayitlar?durum=hepsi&gorunum={view}').data.decode()
        assert html.count('Dosya yok') == 1 and 'bos kayip' in html or (view != 'tablo' and 'kayip' in html), view
        assert 'Görsel dosyası sunucuda bulunamadı' in html
    tablo = c.get('/kayitlar?durum=hepsi').data.decode()
    assert '<span class="mini-kutu mini-tablo bos" title="Görsel yok">—</span>' in tablo and 'bos kayip" title="Görsel dosyası sunucuda bulunamadı' in tablo
    # Pencere: turuncu uyarı kutusu + ayrı yer tutucu metni
    assert 'id="m-gorsel-kayip" class="kayit-uyari bilgi gizli"' in template('kayitlar.html')
    js = js_kayit_bolumu()
    assert "if(k.gorsel_kayip){kayip.innerHTML='<b>Görsel dosyası sunucuda bulunamadı</b> (silinmiş veya taşınmış olabilir). Arşiv\\'den yeniden ilişkilendirebilirsiniz.'" in js
    assert "else if(k.gorsel_kayip)html='<b>Görsel dosyası sunucuda bulunamadı</b>" in js
    css = static('kayit.css'); assert '.kayit-sayfa .mini-kutu.bos.kayip {' in css


# ---------------------------------------------------------------- K4: kendi işlemi şerit çıkarmasın
def test_k4_own_action_returns_change_stamp_matching_poll(web):
    c, a = web; login(c); kid = seed(a); other = insert(a, personel='B')
    page = c.get('/kayitlar?durum=hepsi').data.decode()
    damga0 = re.search(r'<section id="kayit-sonuclari"[^>]*data-damga="([^"]*)"', page).group(1).replace('&#34;', '"').replace('&quot;', '"')
    assert damga0 and damga0 == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    d = c.get(f'/kayit/{kid}', headers=XHR).json
    r = c.post(f'/kayit/{kid}/kt', data={'csrf': csrf(c), 'deger': '1', 'surum': d['surum']}).json
    assert r['damga'] and r['damga'] != damga0 and r['damga'] == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    r = c.post(f'/kayit/{kid}/duzenle', data={'csrf': csrf(c), 'personel': 'yeni'}).json
    assert r['degisiklik'] is True and r['damga'] == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    r = c.post(f'/kayit/{other}/sil', data={'csrf': csrf(c), 'sebep': 'test'}).json
    assert r['damga'] == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    r = c.post(f'/kayit/{other}/geri-al', data={'csrf': csrf(c)}).json; assert r['damga']
    r = c.post(f'/kayit/{kid}/yorum', data={'csrf': csrf(c), 'yorum': 'not'}).json
    assert r['ok'] and r['damga'] == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    r = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': [other], 'deger': '1'}).json
    assert r['degisen'] == 1 and r['damga'] == c.get('/bildirim.json', headers=XHR).json['degisiklik']
    # Yenilenen sonuç alanı damgayı taşır; arayüz bu damgayı beklenen değer sayar
    fresh = c.get('/kayitlar?durum=hepsi', headers=XHR).data.decode()
    assert 'data-damga="' in fresh
    js = js_kayit_bolumu()
    assert 'var beklenenDamga=damgaOku(),sessizYoklama=false;' in js and 'function kendiIslem(r){if(r&&r.damga)beklenenDamga=r.damga;else sessizYoklama=true;}' in js
    assert "document.addEventListener('kp:degisti',function(e){var d=(e&&e.detail)||{};if(d.degisiklik&&beklenenDamga&&d.degisiklik===beklenenDamga)" in js
    assert 'toplu.clear();beklenenDamga=damgaOku();' in js and "if(action!=='gyazo'&&r.degisiklik!==false)kendiIslem(r);" in js and 'kendiIslem(d);clearDraft' in js


# ---------------------------------------------------------------- K5: boş yorum Türkçe uyarı
def test_k5_empty_comment_has_turkish_validation_text(web):
    html = template('kayitlar.html')
    assert '<textarea id="m-yorum" name="yorum" required maxlength="5000" rows="7" placeholder="Kontrol notunuzu veya sorunuzu yazın" data-bos="Göndermeden önce bir yorum yazın."' in html
    js = static('panel.js')
    assert "document.addEventListener('invalid'" in js and "t.getAttribute('data-bos')" in js
    c, a = web; login(c); kid = seed(a)
    r = c.post(f'/kayit/{kid}/yorum', data={'csrf': csrf(c), 'yorum': '   '})
    assert r.status_code == 400 and r.json['ok'] is False and r.json['hata']


# ---------------------------------------------------------------- K6: tarayıcıda doğrudan açılan adresler HTML hata sayfası, fetch JSON
def test_k6_direct_browser_errors_are_html_pages_and_fetch_gets_json(web):
    c, a = web; login(c)
    for url in ('/kayit/99999', '/gorsel/99999', '/kucuk/99999'):
        r = c.get(url, headers=HTML)
        body = r.data.decode()
        assert r.status_code == 404 and r.headers['Content-Type'].startswith('text/html'), url
        assert 'Sayfa bulunamadı' in body and 'hata-sayfa' in body and 'Ana sayfa' in body and '"hata":' not in body, url
        r = c.get(url, headers=XHR); assert r.status_code == 404 and r.json['ok'] is False and 'bulunamadı' in r.json['hata'], url
        r = c.get(url, headers={'Accept': 'application/json'}); assert r.status_code == 404 and r.json['kod'] == 404, url
    account(a, 'ofonly', 'OF:oku'); pa = seed(a, 'PA', 'pa:1')
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofonly')
    r = c.get(f'/kayit/{pa}', headers=HTML); assert r.status_code == 403 and 'Yetkiniz yok' in r.data.decode() and r.headers['Content-Type'].startswith('text/html')
    r = c.get(f'/gorsel/{pa}', headers=HTML); assert r.status_code == 403 and 'hata-sayfa' in r.data.decode()
    # POST uçları her zaman JSON (form gönderimi de fetch ile yapılır)
    r = c.post(f'/kayit/{pa}/kt', data={'csrf': csrf(c)}); assert r.status_code == 403 and r.json['ok'] is False and r.json['proje'] == 'PA'
    r = c.post('/kayit/99999/sil', data={'csrf': csrf(c)}); assert r.status_code == 404 and r.json['ok'] is False
    # ensure_ascii kapalı: Türkçe karakterler kaçışsız
    raw = c.get('/kayit/99999', headers=XHR).data.decode('utf-8')
    assert 'bulunamadı' in raw and '\\u0131' not in raw
    from app import panel
    assert panel.app.json.ensure_ascii is False


# ---------------------------------------------------------------- K7: yetkisiz/olmayan kayıt penceresi
def test_k7_unauthorized_record_message_names_project_and_modal_is_reset(web):
    c, a = web; login(c); pa = seed(a, 'PA', 'pa:1')
    account(a, 'ofadmin', 'OF:oku,kt,duzenle,sil'); c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'ofadmin')
    r = c.get(f'/kayit/{pa}', headers=XHR)
    assert r.status_code == 403 and r.json['proje'] == 'PA' and 'PA projesine ait' in r.json['hata'] and 'yetkiniz yok' in r.json['hata']
    page = c.get(f'/kayitlar?durum=hepsi&ac={pa}').data.decode()
    assert f'data-acik="{pa}"' in page and 'id="m-gorsel-araclar"' in page
    js = js_kayit_bolumu()
    assert "modalHata(id,e);" in js and "document.getElementById('modal-baslik').textContent='Kayıt açılamadı';" in js
    assert "var MODAL_BOLUMLER=['m-onay-ozet','m-konusma-kutu','m-gecmis-kutu','m-gorsel-araclar','m-proje'];" in js
    assert "acikKayit=k;var n=neighbours();modalBolumleriGoster();" in js
    assert "e.status===403?'Bu kayıt için yetkiniz yok':e.status===404?'Kayıt bulunamadı':'Açılamadı'" in js
    assert "if(proje&&mesaj.indexOf(proje)<0)mesaj+=' Kayıt '+proje+' projesine ait.';" in js
    # Oturum düşmesi: 401 / "Geçersiz CSRF" 400 → giriş sayfası (neden=oturum, sonraki)
    assert "function oturumKontrol(e){if(!e)return false;if(e.status===401||(e.status===400&&/csrf/i.test(e.message||''))){window.location='/giris?neden=oturum&sonraki='+encodeURIComponent(location.pathname+location.search);return true;}return false;}" in static('panel.js')
    recordAction = js[js.index('function recordAction('):js.index('function renderGyazo(')]
    assert '.catch(function(e){button.disabled=false;if(oturumKontrol(e))return;' in recordAction


# ---------------------------------------------------------------- K8: telefonda ≥40px form alanları
def test_k8_phone_filter_and_edit_fields_are_tall_enough():
    css = static('kayit.css')
    phone = css[css.index('@media (max-width: 700px)'):]
    assert '.kayit-sayfa .filtre-alan input, .kayit-sayfa .filtre-alan select, .kayit-sayfa .duzenle-izgara input, .kayit-sayfa .duzenle-izgara select, .kayit-sayfa .yorum-form select { min-height: 40px;' in phone
    assert '.kayit-sayfa .duzenle-dugmeler .btn { min-height: 40px; }' in phone
