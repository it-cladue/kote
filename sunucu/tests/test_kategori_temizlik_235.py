# -*- coding: utf-8 -*-
"""2.3.5 — Kategori temizliği: gruplama (üretimdeki 33 farklı değerin benzeri), önizleme (yazmaz), uygulama (yalnız hedeflenen
satırlar, silinmişler dahil ve ayrı raporlanır), İşlem Geçmişi satırları, idempotentlik, eşzamanlılık reddi, CSRF/yetki, CLI ve
sonrasında Kayıtlar süzgeci / personel raporu (API) / katalog sayfası sayıları."""
import json
import os
import re
import subprocess
import sys
import time
from html import unescape
from pathlib import Path

import pytest

from app import api_anahtarlari as aa, db, katalog, kategori_temizlik as kt, kullanicilar
from tests.test_web import web, login, csrf  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]

# Üretim verisindeki 33 farklı değer (sayılar küçültülmüş). '' = kategorisiz.
DEGERLER = [
    ('CVPS', 26), ('ARK', 13), ('DDS', 10), ('LPST', 5), ('', 4), ('HGST', 4), ('BTAGSZ', 3), ('PRCST', 2), ('DDT', 2), ('30GÜN', 2),
    ('CD', 3), ('DD', 2), ('S.ARK', 2), ('PRC', 1), ('HGS', 1), ('30 GÜN', 2), ('BTAGSIZ', 2), ('DDST', 1),
    ('WP kanıt telegrama  eklenmiştir', 2), ('SMS KANIT', 2), ('prc sms', 1), ('cd', 1), ('anlık', 1), ('YT', 1), ('TLSKRT', 1),
    ('R.Cumada Görüşme mevcuttur.', 1), ('PRCKPTTI', 1), ('MEVCUT ÜYE', 1), ('MEVCUT', 1), ('LP', 1), ('HG', 1), ('CVPSZ', 1),
    ('2667965 LEAD', 1),
]
PROJELER = ('OF', 'PA', 'HI')


def tohumla(a):
    """Her değer için kayıtlar: proje sırayla, her 3. kayıt onaylı, her 7. kayıt silinmiş. Ek olarak boşluklu ' HGST ' ve NULL."""
    c = db.baglan(a['DB'])
    i = 0
    with db.transaction(c):
        # Üretimdeki katalogda 'cd' de var (görünen ad küçük harf).
        katalog.save_category(c, 'cd', 'cd', mode='tek_uye', projects=['OF', 'PA', 'HI'], questions=None, actor='test')
        for deger, adet in DEGERLER:
            for _ in range(adet):
                c.execute('INSERT INTO kayitlar(anahtar,proje,kategori,personel,tarih,kt,silindi,kaynak) VALUES(?,?,?,?,?,?,?,?)',
                          ('kt235:%d:%d' % (i, time.time_ns()), PROJELER[i % 3], deger, 'P%d' % (i % 5), db.simdi(),
                           1 if i % 3 == 0 else 0, 1 if i % 7 == 6 else 0, 'legacy_excel'))
                i += 1
        c.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,tarih,kt,kaynak) VALUES('kt235:bosluk','OF',' HGST ','P9',?,1,'legacy_excel')", (db.simdi(),))
        c.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,tarih,kt,kaynak) VALUES('kt235:null','PA',NULL,'P9',?,0,'legacy_excel')", (db.simdi(),))
        c.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,tarih,kt,kaynak,kategori_code,kategori_mode) VALUES('kt235:bot','OF','CVPS','P1',?,0,'telegram','cvpsz','tek_uye')", (db.simdi(),))
    c.close()


def durum_al(a):
    c = db.baglan(a['DB'])
    try:
        return {r['id']: (r['kategori'], r['kategori_code'], r['surum']) for r in c.execute('SELECT id,kategori,kategori_code,surum FROM kayitlar')}
    finally:
        c.close()


def denetim_satirlari(a):
    c = db.baglan(a['DB'])
    try:
        return [dict(r) for r in c.execute("SELECT * FROM denetim WHERE islem='kategori_birlestir' ORDER BY id")]
    finally:
        c.close()


def grup_haritasi(a):
    c = db.baglan(a['DB'])
    try:
        return {g['anahtar']: g for g in kt.gruplar(c)}
    finally:
        c.close()


# Operatörün seçimi: anahtar (normalleştirilmiş) → hedef kategori kodu ya da (boş)
SECIM = {'30 gün': '30gn', '30gün': '30gn', 'btagsiz': 'btagsz', 'btagsz': 'btagsz', 'cvpsz': 'cvpsz', 'hgs': 'hgst', 'hg': 'hgst',
         'wp kanıt telegrama  eklenmiştir': kt.BOS_HEDEF, 'cd': 'cd', 'hgst': 'hgst', 's.ark': 'sark'}


def beklenen_durum(once, a):
    """Bağımsız başvuru: seçimdeki gruplarda kategori ≠ hedef adı olan satırlar hedef ada/koda çekilir, gerisi aynı kalır."""
    c = db.baglan(a['DB'])
    try:
        adlar = {k['code']: k['label'] for k in katalog.list_categories(c, active_only=False)}
    finally:
        c.close()
    out = {}
    for kid, (kat, kod, surum) in once.items():
        a_ = str(kat or '').strip(' ').casefold()
        if a_ in SECIM:
            hedef = SECIM[a_]
            ad, hkod = ('', None) if hedef == kt.BOS_HEDEF else (adlar[hedef], hedef)
            if (kat or '') != ad:
                out[kid] = (ad, hkod, (surum or 1) + 1)
                continue
        out[kid] = (kat, kod, surum)
    return out


def form_verisi(token, secim, islem='onizle', damga=None):
    veri = {'csrf': token, 'islem': islem, 'g': list(secim.keys()), 'h': list(secim.values())}
    if damga is not None:
        veri['damga'] = damga
    return veri


def hesap(a, ad, rol):
    kullanicilar.ekle(a, ad, rol, 'Test-Password-123!'); kullanicilar.guncelle(a, ad, sifre_degistir=0)


# ------------------------------------------------------------------ gruplama

def test_gruplama_uretim_benzeri_33_deger(web):
    c, a = web
    tohumla(a)
    g = grup_haritasi(a)
    # 33 farklı ham değer + ' HGST ' + NULL; 'CD'/'cd', 'HGST'/' HGST ', ''/NULL aynı grupta → 32 grup
    assert len(g) == 32
    assert {y['deger']: y['adet'] for y in g['cd']['yazimlar']} == {'CD': 3, 'cd': 1}
    assert g['cd']['katalog'] == {'code': 'cd', 'label': 'cd', 'aktif': True} and not g['cd']['duzgun'] and g['cd']['varsayilan'] == 'cd'
    assert {y['deger'] for y in g['hgst']['yazimlar']} == {'HGST', ' HGST '} and g['hgst']['hepsi'] == 5
    assert g['30gün']['katalog']['label'] == '30gün' and g['30gün']['varsayilan'] == '30gn'
    assert g['30 gün']['katalog'] is None and g['30 gün']['varsayilan'] == ''
    assert g['btagsz']['katalog']['code'] == 'btagsz' and g['btagsiz']['katalog'] is None
    assert g['cvpsz']['katalog'] is None and g['cvpsz']['kod_onerisi'] == {'code': 'cvpsz', 'label': 'CVPS'}
    assert g['cvps']['duzgun'] and g['cvps']['katalog']['code'] == 'cvpsz'
    bos = g['']
    assert bos['bos'] and bos['gorunen'] == '(boş)' and bos['hepsi'] == 5 and {y['deger'] for y in bos['yazimlar']} == {''}
    # Sayımlar: toplam/onaylı/bekleyen silinmemişlerden; silinmiş ayrı; projeler listelenir
    for x in g.values():
        assert x['toplam'] == x['onayli'] + x['bekleyen'] and x['hepsi'] == x['toplam'] + x['silinen']
        assert sum(p['adet'] for p in x['projeler']) == x['toplam']
    assert sum(x['hepsi'] for x in g.values()) == sum(n for _, n in DEGERLER) + 3
    assert any(x['silinen'] for x in g.values())


def test_sayfa_yonetici_icin_gruplari_ve_derin_baglantilari_gosterir(web):
    c, a = web
    tohumla(a)
    login(c)
    r = c.get('/yonetim/katalog/kategori-temizligi')
    assert r.status_code == 200
    html = r.data.decode()
    assert html.count('data-kt-grup=') == 32
    for ad in ('30 GÜN', 'BTAGSIZ', 'R.Cumada Görüşme mevcuttur.', '2667965 LEAD', '(boş)'):
        assert ad in unescape(html)
    assert 'Katalogda var' in html and 'Kodu eşleşiyor' in html and '— değiştirme —' in html and '(boş) yap' in html
    # Katalogdaki adla eşleşen grup kendi kategorisine önceden seçili; eşleşmeyen "değiştirme"de
    satir_30 = re.search(r'<tr data-kt-grup="30gün".*?</tr>', html, re.S).group(0)
    assert re.search(r'<option value="30gn" selected>', satir_30)
    satir_30b = re.search(r'<tr data-kt-grup="30 gün".*?</tr>', html, re.S).group(0)
    assert re.search(r'<option value="" selected>', satir_30b)
    # Geri yüklenebilir yedek önerilir (Bot sayfasının .sqlite3 yedeği --geri-yukle ile açılmaz)
    assert 'YEDEK_DOGRULANDI' in html and 'kanit-yedek.sh --geri-yukle' in html
    # Kayıtlar derin bağlantısı (o değer, tüm durumlar)
    assert '/kayitlar?durum=hepsi&amp;kategori=30+G%C3%9CN&amp;silinmemis=1' in html  # Toplam gibi silinmişler hariç
    liste = c.get('/kayitlar?durum=hepsi&kategori=30+G%C3%9CN&gorunum=tablo').data.decode()
    assert re.search(r'<p class="sonuc-ozeti"><b>2</b> kayıt', liste)


def test_yetki_ve_csrf(web):
    c, a = web
    tohumla(a)
    hesap(a, 'lider', 'OF:oku,kt')
    once = durum_al(a)
    login(c, 'lider')
    assert c.get('/yonetim/katalog/kategori-temizligi').status_code == 403
    assert c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM, 'uygula', 'x')).status_code == 403
    c2 = c.application.test_client()
    login(c2)
    assert c2.post('/yonetim/katalog/kategori-temizligi', data=form_verisi('yanlis', SECIM, 'uygula', 'x')).status_code == 400
    assert c2.post('/yonetim/katalog/kategori-temizligi', data={'islem': 'onizle', 'g': ['cd'], 'h': ['cd']}).status_code == 400
    assert durum_al(a) == once and denetim_satirlari(a) == []


# ------------------------------------------------------------------ önizleme / uygulama

def test_onizleme_yazmaz_uygulama_yalniz_hedefleneni_degistirir(web):
    c, a = web
    tohumla(a)
    login(c)
    once = durum_al(a)
    r = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM))
    assert r.status_code == 200
    html = r.data.decode()
    assert durum_al(a) == once and denetim_satirlari(a) == []  # önizleme hiçbir şey yazmaz
    beklenen = beklenen_durum(once, a)
    degisen = {k for k in once if once[k] != beklenen[k]}
    m = re.search(r'<h2 id="kt-onizleme-baslik">(\d+) kayıt değişecek</h2>', html)
    assert m and int(m.group(1)) == len(degisen)
    kalem = dict(re.findall(r'data-kt-kalem="([^"]*)" data-degisecek="(\d+)"', html))
    assert int(kalem['30 gün']) == 2 and int(kalem['cd']) == 3 and int(kalem['cvpsz']) == 1
    assert int(kalem['30gün']) == 2 and int(kalem['hgst']) == 1 and int(kalem['s.ark']) == 0  # 'HGST'×4 aynı kalır, ' HGST ' düzelir
    damga = re.search(r'name="damga" value="([0-9a-f]+)"', html).group(1)
    # Uygula: önizleme formundaki gizli alanlarla
    g = re.findall(r'<input type="hidden" name="g" value="([^"]*)"><input type="hidden" name="h" value="([^"]*)">', html)
    assert dict((unescape(x), unescape(y)) for x, y in g) == SECIM
    r2 = c.post('/yonetim/katalog/kategori-temizligi', data={'csrf': csrf(c), 'islem': 'uygula', 'damga': damga,
                                                             'g': [unescape(x) for x, _ in g], 'h': [unescape(y) for _, y in g]})
    assert r2.status_code == 200, r2.data.decode()[:500]
    sonra = durum_al(a)
    assert sonra == beklenen
    html2 = r2.data.decode()
    assert '%d kayıt güncellendi' % len(degisen) in html2
    # Silinmiş kayıtlar da değişti ve ayrıca raporlandı
    cdb = db.baglan(a['DB'])
    silinen_degisen = cdb.execute('SELECT COUNT(*) FROM kayitlar WHERE silindi=1 AND id IN (%s)' % ','.join(map(str, degisen))).fetchone()[0]
    cdb.close()
    assert silinen_degisen >= 1 and 'Silinmiş kayıtlardan %d tanesi' % silinen_degisen in html2
    # Seçilmeyen gruplar ve bot kaydının kodu dokunulmadı
    for kid, (kat, kod, _) in once.items():
        if str(kat or '').strip(' ').casefold() not in SECIM:
            assert sonra[kid] == once[kid]
    # İşlem Geçmişi: değişen her grup için bir satır
    satirlar = denetim_satirlari(a)
    degisen_grup = {str(once[k][0] or '').strip(' ').casefold() for k in degisen}
    assert len(satirlar) == len(degisen_grup)
    s30 = next(s for s in satirlar if json.loads(s['aciklama'])['eski'] == '30 GÜN')
    ayr = json.loads(s30['aciklama'])
    assert ayr == {'eski': '30 GÜN', 'yazimlar': {'30 GÜN': 2}, 'hedef': '30gün', 'kod': '30gn', 'adet': 2, 'silinen': ayr['silinen']}
    assert s30['kullanici'] == 'testadmin' and s30['hedef_turu'] == 'kategori' and s30['yeni'].startswith('30gün · 2 kayıt')
    sbos = next(s for s in satirlar if json.loads(s['aciklama'])['hedef'] == '')
    assert sbos['hedef_id'] == kt.BOS_HEDEF and sbos['yeni'].startswith('(boş) · 2 kayıt')
    gecmis = c.get('/denetim?islem=kategori_birlestir').data.decode()
    assert 'Kategori birleştirme' in gecmis
    # İdempotent: aynı seçimle önizleme 0, uygulama hiçbir şey yazmaz
    r3 = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM))
    assert '<h2 id="kt-onizleme-baslik">0 kayıt değişecek</h2>' in r3.data.decode() and 'name="damga"' not in r3.data.decode()
    cdb = db.baglan(a['DB'])
    try:
        p = kt.uygula(cdb, SECIM, 'testadmin')
    finally:
        cdb.close()
    assert p['uygulanan'] == 0 and durum_al(a) == sonra and len(denetim_satirlari(a)) == len(satirlar)
    # Gruplar birleşti: '30 gün', 'btagsiz', 'cvpsz', 'hgs', 'hg' artık yok; boş grup büyüdü
    g2 = grup_haritasi(a)
    assert not {'30 gün', 'btagsiz', 'cvpsz', 'hgs', 'hg', 'wp kanıt telegrama  eklenmiştir'} & set(g2)
    assert {y['deger'] for y in g2['cd']['yazimlar']} == {'cd'} and g2['cd']['duzgun']
    assert g2['']['hepsi'] == 5 + 2


def test_onizlemeden_sonra_degisiklik_varsa_uygulama_reddedilir(web):
    c, a = web
    tohumla(a)
    login(c)
    html = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM)).data.decode()
    damga = re.search(r'name="damga" value="([0-9a-f]+)"', html).group(1)
    # Önizlemeden sonra bot aynı tuhaf yazımla yeni kayıt ekler
    cdb = db.baglan(a['DB'])
    with db.transaction(cdb):
        cdb.execute("INSERT INTO kayitlar(anahtar,proje,kategori,kaynak) VALUES('kt235:yeni','OF','BTAGSIZ','telegram')")
    cdb.close()
    once = durum_al(a)
    r = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM, 'uygula', damga))
    assert r.status_code == 409
    html2 = r.data.decode()
    assert 'Önizlemeden sonra kayıtlar değişti' in html2 and durum_al(a) == once and denetim_satirlari(a) == []
    yeni_damga = re.search(r'name="damga" value="([0-9a-f]+)"', html2).group(1)
    assert yeni_damga != damga
    r2 = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), SECIM, 'uygula', yeni_damga))
    assert r2.status_code == 200 and durum_al(a) == beklenen_durum(once, a)
    # Önizlemeden sonra yalnız onay/silinme durumu değişirse de (kimlikler aynı) reddedilir
    cdb = db.baglan(a['DB'])
    try:
        p1 = kt.plan(cdb, {'s.ark': 'ark'})
        assert p1['toplam_degisecek'] > 0
        with db.transaction(cdb):
            cdb.execute("UPDATE kayitlar SET kt=1-COALESCE(kt,0) WHERE lower(trim(kategori))='s.ark'")
        with pytest.raises(kt.Cakisma):
            kt.uygula(cdb, {'s.ark': 'ark'}, 'x', damga=p1['damga'])
        assert cdb.execute("SELECT COUNT(*) FROM kayitlar WHERE kategori='S.ARK'").fetchone()[0] == p1['toplam_degisecek']
    finally:
        cdb.close()
    # Modül düzeyinde de aynı: eski damga → Cakisma, hiçbir şey yazılmaz
    cdb = db.baglan(a['DB'])
    try:
        with pytest.raises(kt.Cakisma):
            kt.uygula(cdb, {'anlık': 'ark'}, 'x', damga='0' * 20)
        assert cdb.execute("SELECT COUNT(*) FROM kayitlar WHERE kategori='anlık'").fetchone()[0] == 1
    finally:
        cdb.close()


def test_gecersiz_ve_pasif_hedef_reddedilir(web):
    c, a = web
    tohumla(a)
    login(c)
    once = durum_al(a)
    r = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), {'anlık': 'olmayan_kod'}))
    assert r.status_code == 400 and 'katalogda etkin değil' in r.data.decode()
    cdb = db.baglan(a['DB'])
    with db.transaction(cdb):
        k = katalog.get_category(cdb, 'ddt')
        katalog.save_category(cdb, 'ddt', 'DDT', mode=k['mode'], projects=k['projects'], questions=None, active=False, actor='test',
                              expected_revision=k['revision'])
    cdb.close()
    r = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), {'dd': 'ddt'}))
    assert r.status_code == 400
    html = c.get('/yonetim/katalog/kategori-temizligi').data.decode()
    assert '<option value="ddt"' not in html and 'Katalogda var (pasif)' in html
    r = c.post('/yonetim/katalog/kategori-temizligi', data=form_verisi(csrf(c), {'anlık': ''}))
    assert r.status_code == 400 and 'değiştirilecek bir şey yok' in r.data.decode()
    r = c.post('/yonetim/katalog/kategori-temizligi', data={'csrf': csrf(c), 'islem': 'onizle', 'g': ['a', 'b'], 'h': ['ark']})
    assert r.status_code == 400
    assert durum_al(a) == once


# ------------------------------------------------------------------ sistemin geri kalanı birleşmiş değeri görür

def test_kayitlar_suzgeci_personel_raporu_ve_katalog_sayilari(web):
    c, a = web
    tohumla(a)
    login(c)
    cdb = db.baglan(a['DB'])
    _, anahtar = aa.olustur(cdb, 'Rapor', '*', yalniz_onayli=False, olusturan='testadmin')
    cdb.close()
    B = {'Authorization': 'Bearer ' + anahtar}
    once = c.get('/api/v1/personel-ozet?donem=hepsi', headers=B).get_json()
    assert {'30 GÜN', 'BTAGSIZ', 'CVPSZ', 'HGS'} <= set(once['sutunlar'])
    kat = c.get('/yonetim/katalog').data.decode()
    assert 'Pasif yapınca bot yeni kanıt için sunmaz; eski kayıtlar etiketini korur' in kat
    assert '/yonetim/katalog/kategori-temizligi' in kat
    g = grup_haritasi(a)
    sayi_30 = re.search(r'<b>30gün</b><code>30gn</code><small class="katalog-kayit-sayi" data-kayit-sayisi="(\d+)"', kat)
    assert sayi_30 and int(sayi_30.group(1)) == g['30gün']['toplam']
    sayi_cd = re.search(r'<b>cd</b><code>cd</code><small class="katalog-kayit-sayi" data-kayit-sayisi="(\d+)"', kat)
    assert int(sayi_cd.group(1)) == g['cd']['toplam']
    cdb = db.baglan(a['DB'])
    try:
        kt.uygula(cdb, SECIM, 'testadmin')
    finally:
        cdb.close()
    sonra = c.get('/api/v1/personel-ozet?donem=hepsi', headers=B).get_json()
    assert not {'30 GÜN', 'BTAGSIZ', 'CVPSZ', 'HGS', 'HG', 'WP kanıt telegrama  eklenmiştir'} & set(sonra['sutunlar'])
    assert sonra['kayit_sayisi'] == once['kayit_sayisi']
    t0, t1 = once['toplam']['sutunlar'], sonra['toplam']['sutunlar']
    assert t1['30gün'] == t0['30gün'] + t0['30 GÜN']
    assert t1['btagsz'] == t0['btagsz'] + t0['BTAGSIZ']
    assert t1['CVPS'] == t0['CVPS'] + t0['CVPSZ']
    assert t1['(boş)'] == t0['(boş)'] + t0['WP kanıt telegrama  eklenmiştir']
    # Kayıtlar süzgeci (tüm durumlar = silinmişler dahil) birleşmiş değeri görür
    g2 = grup_haritasi(a)
    liste = c.get('/kayitlar?durum=hepsi&kategori=30g%C3%BCn&gorunum=tablo').data.decode()
    assert int(re.search(r'<p class="sonuc-ozeti"><b>(\d+)</b> kayıt', liste).group(1)) == g2['30gün']['hepsi']
    bos = c.get('/kayitlar?durum=hepsi&kategori=30+G%C3%9CN&gorunum=tablo').data.decode()
    assert re.search(r'<p class="sonuc-ozeti"><b>0</b> kayıt', bos)
    # API kategori süzgeci de
    api_liste = c.get('/api/v1/kayitlar?kategori=btagsz&adet=500', headers=B).get_json()
    assert api_liste['toplam'] == g2['btagsz']['toplam']
    kat2 = c.get('/yonetim/katalog').data.decode()
    sayi_30b = re.search(r'<b>30gün</b><code>30gn</code><small class="katalog-kayit-sayi" data-kayit-sayisi="(\d+)"', kat2)
    assert int(sayi_30b.group(1)) == g2['30gün']['toplam'] > g['30gün']['toplam']


# ------------------------------------------------------------------ CLI

def cli(tmp_path, *args):
    ortam = dict(os.environ, PANEL_VERI=str(tmp_path), GYAZO_WORKER='0')
    return subprocess.run([sys.executable, '-m', 'app.cli', 'kategori-temizle', *args], cwd=str(ROOT), env=ortam,
                          capture_output=True, text=True, timeout=120)


def test_cli_listele_onizle_uygula_ve_cikis_kodlari(web, tmp_path):
    c, a = web
    assert a['DB'] == str(tmp_path / 'panel.db')
    tohumla(a)
    once = durum_al(a)
    r = cli(tmp_path, '--listele')
    assert r.returncode == 0, r.stderr
    veri = json.loads(r.stdout)
    assert len(veri['gruplar']) == 32 and 'Katalogda var: 30gün' in r.stderr and '32 farklı değer' in r.stderr
    assert {h['code'] for h in veri['hedefler']} >= {'30gn', 'btagsz', 'cd', 'cvpsz'}
    arg = ['--donustur', '30 GÜN=30gün', '--donustur', 'BTAGSIZ=btagsz', '--donustur', 'WP kanıt telegrama  eklenmiştir=(boş)',
           '--donustur', 'cvpsz=CVPS']
    r = cli(tmp_path, *arg, '--onizle')
    assert r.returncode == 0, r.stderr
    p = json.loads(r.stdout)
    assert p['onizleme'] is True and p['toplam_degisecek'] == 2 + 2 + 2 + 1 and 'ÖNİZLEME' in r.stderr
    assert durum_al(a) == once and denetim_satirlari(a) == []
    r = cli(tmp_path, *arg)
    assert r.returncode == 0, r.stderr
    p = json.loads(r.stdout)
    assert p['uygulanan'] == 7 and 'UYGULANDI: 7 kayıt' in r.stderr
    satirlar = denetim_satirlari(a)
    assert len(satirlar) == 4 and {s['kullanici'] for s in satirlar} == {'sunucu-cli'}
    r = cli(tmp_path, *arg)  # idempotent
    assert r.returncode == 0 and json.loads(r.stdout)['uygulanan'] == 0 and len(denetim_satirlari(a)) == 4
    # Hatalar: çıkış kodu 1, hiçbir şey yazılmaz
    simdi = durum_al(a)
    for hatali in (['--donustur', 'anlık=yok_boyle'], ['--donustur', 'anlık'], ['--donustur', 'anlık='], [],
                   ['--listele', '--donustur', 'a=ark'], ['--donustur', 'anlık=ark', '--donustur', 'Anlık=dds']):
        r = cli(tmp_path, *hatali)
        assert r.returncode == 1 and 'Hata' in r.stderr, (hatali, r.stderr)
    assert durum_al(a) == simdi
    assert 'kategori-temizle' in subprocess.run([sys.executable, '-m', 'app.cli', '--help'], cwd=str(ROOT), capture_output=True,
                                                text=True, timeout=120, env=dict(os.environ, PANEL_VERI=str(tmp_path))).stdout
