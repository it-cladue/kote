# -*- coding: utf-8 -*-
"""2.3.4 — Personel bazında kanıt özeti: veri işlevi, ana sayfa kartı, /rapor/personel (+ .xlsx / .csv / yazdır),
Kayıtlar hücre bağlantıları, /api/v1/personel-ozet ve Playwright ekran görüntüleri (Node + Playwright yoksa atlanır)."""
import csv
import io
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import openpyxl
import pytest

from app import api, api_anahtarlari as aa, db, kullanicilar, panel, personel_ozeti as po
from tests.test_web import web, login  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
TARAYICI_BETIK = Path(__file__).with_name('personel_ozet_tarayici.js')
EKRAN_KLASOR = '/tmp/kanit-ekran/p234'

BUGUN = date.today()
HAFTA_BASI = BUGUN - timedelta(days=BUGUN.weekday())
AY_BASI = BUGUN.replace(day=1)
GECEN_AY = (AY_BASI - timedelta(days=1)).replace(day=10)
GUN40 = BUGUN - timedelta(days=40)


def ts(d, saat='10:00:00'):
    return d.isoformat() + ' ' + saat


# (proje, personel, kategori, tip, tarih, kt, silindi, ekleyen_ad, kaynak)
KAYITLAR = [
    ('OF', 'ali', 'CVPS', 'Sessiz', ts(BUGUN), 1, 0, 'tg_mehmet', 'telegram'),
    ('OF', 'ali', 'CVPS', 'Sessiz', ts(BUGUN, '11:00:00'), 0, 0, 'tg_mehmet', 'telegram'),
    ('OF', 'ali', 'cvps', 'Telesekreter', ts(HAFTA_BASI, '09:00:00'), 1, 0, 'tg_mehmet', 'telegram'),
    ('OF', 'ali', 'DDS', 'Sessiz', ts(GECEN_AY), 1, 0, 'tg_zeynep', 'telegram'),
    ('OF', 'ayse', 'HGST', 'Sessiz', ts(BUGUN), 1, 0, 'tg_zeynep', 'telegram'),
    ('OF', 'ayse', 'HGST', '', AY_BASI.isoformat(), 1, 0, '', 'legacy_excel'),  # eski Excel: saatsiz tarih, ayın ilk günü
    ('OF', 'can', 'DDS', 'Telesekreter', ts(GUN40), 0, 0, 'tg_mehmet', 'telegram'),
    ('OF', 'can', 'DDS', 'Sessiz', ts(BUGUN), 1, 1, 'tg_mehmet', 'telegram'),   # silinmiş: hiçbir yerde sayılmaz
    ('OF', '', 'ARK', 'Sessiz', ts(BUGUN), 0, 0, 'tg_mehmet', 'telegram'),       # personeli boş
    ('PA', 'deniz', 'ARK', 'Sessiz', ts(BUGUN), 1, 0, 'tg_ayla', 'telegram'),
    ('PA', 'deniz', 'ARK', 'Sessiz', ts(HAFTA_BASI, '08:00:00'), 0, 0, 'tg_ayla', 'telegram'),
    ('PA', 'ece', 'EskiKategori', 'Sessiz', ts(BUGUN), 1, 0, 'tg_ayla', 'telegram'),  # katalogda yok: sona eklenir
    ('PA', 'ali', 'CVPS', 'Sessiz', ts(GUN40), 1, 0, 'tg_ayla', 'telegram'),
    ('HI', 'fatma', 'PRCST', 'Telesekreter', ts(BUGUN), 0, 0, 'tg_hasan', 'telegram'),
    ('HI', 'fatma', 'PRCST', 'Telesekreter', ts(BUGUN, '12:00:00'), 1, 0, 'tg_hasan', 'telegram'),
    ('HI', 'ece', '', 'Sessiz', None, 1, 0, '', 'legacy_excel'),                 # kategorisiz + tarihsiz
    ('OF', 'zed', 'HGST', 'Sessiz', ts(GECEN_AY), 1, 0, 'tg_zeynep', 'telegram'),
    ('OF', 'zed', 'HGST ', 'Sessiz', ts(GECEN_AY, '11:00:00'), 1, 0, '', 'legacy_excel'),  # sonda boşluklu eski kategori: HGST sütununda sayılır
    ('OF', 'zed', ' DDS', 'Sessiz', ts(GECEN_AY, '12:00:00'), 0, 0, '', 'legacy_excel'),   # başta boşluklu eski kategori: DDS sütununda sayılır
]


def tohumla(a, ekstra=()):
    c = db.baglan(a['DB'])
    ids = []
    with db.transaction(c):
        for i, (proje, per, kat, tip, tarih, kt, sil, ekl, kaynak) in enumerate(list(KAYITLAR) + list(ekstra)):
            ids.append(c.execute('INSERT INTO kayitlar(anahtar,proje,personel,kategori,tip,tarih,kt,silindi,ekleyen_ad,kaynak) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                 ('po:%d:%d' % (i, time.time_ns()), proje, per, kat, tip, tarih, kt, sil, ekl, kaynak)).lastrowid)
    c.close()
    return ids


def hesap(a, ad, rol):
    kullanicilar.ekle(a, ad, rol, 'Test-Password-123!'); kullanicilar.guncelle(a, ad, sifre_degistir=0)


def beklenen(projeler, f, kayitlar=KAYITLAR):
    """Bağımsız başvuru hesabı: (grup değeri, sütun değeri casefold) → sayı."""
    out = {}
    for proje, per, kat, tip, tarih, kt, sil, ekl, _ in kayitlar:
        if sil or proje not in projeler:
            continue
        if f['durum'] == 'onayli' and not kt or f['durum'] == 'bekleyen' and kt:
            continue
        gun = (tarih or '')[:10]
        if f.get('tarih1') and (not gun or gun < f['tarih1']):
            continue
        if f.get('tarih2') and (not gun or gun > f['tarih2']):
            continue
        g_ = (per if f['grup'] == 'personel' else ekl).strip() or po.BOS
        s_ = ((kat if f['sutun'] == 'kategori' else tip) or '').strip().casefold() or po.BOS.casefold()
        out[(g_, s_)] = out.get((g_, s_), 0) + 1
    return out


def matris(o):
    out = {}
    for x in o['satirlar']:
        for s_, n in x['sutunlar'].items():
            if n:
                out[(x['personel'], s_.casefold())] = n
    return out


def anahtar(a, projeler='*', **kw):
    c = db.baglan(a['DB'])
    try:
        return aa.olustur(c, kw.pop('ad', 'Rapor sistemi'), projeler, olusturan='testadmin', **kw)
    finally:
        c.close()


def B(k):
    return {'Authorization': 'Bearer ' + k}


def sonuc_sayisi(html):
    m = re.search(r'<p class="sonuc-ozeti"><b>(\d+)</b> kayıt', html)
    assert m, html[:500]
    return int(m.group(1))


@pytest.fixture(autouse=True)
def _api_sinir(monkeypatch):
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    monkeypatch.delenv('API_ACIK', raising=False)
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


# ---------------------------------------------------------------- 1. veri işlevi

def test_filtre_coz_beyaz_liste_ve_donem_araliklari():
    f, h, u = po.filtre_coz({}, ['OF'], bugun=date(2026, 11, 26))
    assert (f['donem'], f['durum'], f['grup'], f['sutun'], f['proje']) == ('ay', 'hepsi', 'personel', 'kategori', '') and not h
    assert (f['tarih1'], f['tarih2']) == ('2026-11-01', '2026-11-26')
    gun = date(2026, 11, 26)  # perşembe → hafta pazartesi 23'ünde başlar
    beklenen_aralik = {'bugun': ('2026-11-26', '2026-11-26'), 'hafta': ('2026-11-23', '2026-11-26'), 'ay': ('2026-11-01', '2026-11-26'),
                       'son30': ('2026-10-28', '2026-11-26'), 'hepsi': ('', '')}
    for d, (t1, t2) in beklenen_aralik.items():
        f, h, _ = po.filtre_coz({'donem': d}, ['OF'], bugun=gun)
        assert (f['tarih1'], f['tarih2']) == (t1, t2) and not h, d
    f, h, u = po.filtre_coz({'donem': 'ozel', 'tarih1': '2026-11-20', 'tarih2': '2026-11-02'}, ['OF'], bugun=gun)
    assert (f['tarih1'], f['tarih2']) == ('2026-11-02', '2026-11-20') and u and not h
    f, h, _ = po.filtre_coz({'tarih1': '2026-10-01'}, ['OF'], bugun=gun)
    assert f['donem'] == 'ozel' and f['tarih1'] == '2026-10-01' and f['tarih2'] == ''
    for kotu in ({'donem': 'yil'}, {'durum': 'silinen'}, {'grup': "x' OR 1=1"}, {'sutun': 'kt'}, {'donem': 'ozel', 'tarih1': '2026-13-01'},
                 {'donem': 'ozel'}):
        f, h, _ = po.filtre_coz(kotu, ['OF'], bugun=gun)
        assert h and f['donem'] in po.DONEM_ADLARI and f['durum'] in po.DURUM_ADLARI and f['grup'] in po.GRUP_ADLARI and f['sutun'] in po.SUTUN_ADLARI
    with pytest.raises(PermissionError):
        po.filtre_coz({'proje': 'PA'}, ['OF'])
    assert po.filtre_coz({'proje': 'of'}, ['OF'])[0]['proje'] == 'OF'


def test_matris_her_donem_durum_grup_sutun_birlesimi(web):
    c, a = web
    tohumla(a)
    con = db.baglan(a['DB'])
    try:
        for proje in ('', 'OF', 'PA'):
            for donem in ('bugun', 'hafta', 'ay', 'son30', 'hepsi'):
                for durum in ('hepsi', 'onayli', 'bekleyen'):
                    for grup in ('personel', 'ekleyen'):
                        for sutun in ('kategori', 'tip'):
                            f, h, _ = po.filtre_coz(dict(proje=proje, donem=donem, durum=durum, grup=grup, sutun=sutun), ['OF', 'PA', 'HI'])
                            assert not h
                            o = po.personel_ozeti(con, ['OF', 'PA', 'HI'], None, f)
                            projeler = [proje] if proje else ['OF', 'PA', 'HI']
                            bek = beklenen(projeler, f)
                            assert matris(o) == bek, (proje, donem, durum, grup, sutun)
                            assert o['toplam']['toplam'] == sum(bek.values()) == o['kayit_sayisi']
                            assert o['toplam']['onayli'] + o['toplam']['bekleyen'] == o['toplam']['toplam']
                            assert sum(o['toplam']['sutunlar'].values()) == o['toplam']['toplam']
                            assert o['kisi_sayisi'] == len({k[0] for k in bek})
                            sirali = [(-x['toplam'], x['personel'].casefold()) for x in o['satirlar'] if not x['bos']]
                            assert sirali == sorted(sirali)
        # Özel aralık: geçen ayın 10'u tek gün.
        f, _, _ = po.filtre_coz(dict(donem='ozel', tarih1=GECEN_AY.isoformat(), tarih2=GECEN_AY.isoformat()), ['OF'])
        assert matris(po.personel_ozeti(con, ['OF'], None, f)) == {('ali', 'dds'): 1, ('zed', 'hgst'): 2, ('zed', 'dds'): 1}  # boşluklu kategoriler kırpılıp birleşir
        # Ayrıntılar: harf duyarsız birleştirme (cvps → CVPS), katalog sırası, katalog dışı sona, boş en sonda.
        f, _, _ = po.filtre_coz(dict(donem='hepsi'), ['OF', 'PA', 'HI'])
        o = po.personel_ozeti(con, ['OF', 'PA', 'HI'], None, f)
        ali = next(x for x in o['satirlar'] if x['personel'] == 'ali')
        assert ali['sutunlar']['CVPS'] == 4 and 'cvps' not in ali['sutunlar'] and ali['toplam'] == 5 and ali['onayli'] == 4 and ali['bekleyen'] == 1
        assert ali['onay_orani'] == 80 and o['satirlar'][0]['personel'] == 'ali'
        katalog_sira = [k['label'] for k in __import__('app.katalog', fromlist=['x']).list_categories(con, project_code='OF')]
        assert o['sutunlar'][:len(katalog_sira)] == katalog_sira
        assert o['sutunlar'][-2:] == ['EskiKategori', po.BOS]
        assert any(x['personel'] == po.BOS and x['bos'] for x in o['satirlar'])
        assert o['donem']['kod'] == 'hepsi' and 'Tümü' in o['donem']['etiket']
        # Eski Excel kaydının saatsiz tarihi ayın ilk günü olarak "Bu ay"a girer.
        f, _, _ = po.filtre_coz(dict(donem='ay', proje='OF'), ['OF'])
        ayse = next(x for x in po.personel_ozeti(con, ['OF'], None, f)['satirlar'] if x['personel'] == 'ayse')
        assert ayse['sutunlar']['HGST'] == 2
        # gizle koşulu dışarıdan verilir: OF onaysızları gizlenir.
        f, _, _ = po.filtre_coz(dict(donem='hepsi'), ['OF'])
        o = po.personel_ozeti(con, ['OF'], ('NOT (proje IN (?) AND (kt=0 OR silindi=1))', ['OF']), f)
        assert o['toplam']['bekleyen'] == 0 and o['toplam']['toplam'] == 7
    finally:
        con.close()


# ---------------------------------------------------------------- 2. ana sayfa kartı

def test_ana_sayfa_karti_ilk_10_lider_ve_rapor_baglantisi(web):
    c, a = web
    ekstra = [('OF', 'kisi%02d' % i, 'DDS', 'Sessiz', ts(BUGUN), 1, 0, 'tg_x', 'telegram') for i in range(12)]
    tohumla(a, ekstra)
    login(c)
    html = c.get('/?donem=bugun').get_data(as_text=True)
    kart = html.split('id="personel-ozet"', 1)[1].split('<div class="ana-alt-izgara">', 1)[0]
    assert html.index('Proje bazında iş yükü') < html.index('Personel bazında kanıtlar') < html.index('Son işlemler')
    assert 'Tüm tablo ve rapor' in kart and 'href="/rapor/personel?donem=bugun' in unescape(kart)
    govde = kart.split('<tbody>', 1)[1].split('</tbody>', 1)[0]
    assert govde.count('<tr>') == 10
    # 2.3.5: "İlk 3" şeridi yerine herkes için kişi kartı; ilk üçte madalya, ilk 6 görünür.
    assert 'kişi daha var' in kart and 'po-kisi-kart sira-1' in kart and 'po-kisi-kart sira-3' in kart and 'sira-4' not in kart
    n_kart = len(re.findall(r'data-po-kart(?=[ >])', kart))
    assert n_kart > 12 and kart.count('data-po-kart hidden') == n_kart - 6 and 'Daha fazla göster (%d kişi daha)' % (n_kart - 6) in kart
    for parca in ('name="proje"', 'name="donem"', 'value="hafta"', 'value="son30"', 'name="durum"', 'name="grup"', 'value="ekleyen"', 'data-po-otomatik',
                  'data-po-kartlar', 'name="kategori"', 'class="po-pay"', '>Bugün<', '>Bu hafta<', '>Bu ay<', '>Son 30 gün<', '>Tümü<'):
        assert parca in kart, parca
    assert 'value="ozel"' not in kart  # özel aralık yalnız rapor sayfasında
    assert 'rapor.js?v=' + panel.SURUM in html
    # Kartta sıfır toplamlı katalog sütunları gizlenir.
    basliklar = re.findall(r'<th scope="col" class="po-sayi po-kat"[^>]*title="([^"]+)"', kart)
    assert set(basliklar) == {'CVPS', 'HGST', 'DDS', 'ARK', 'EskiKategori', 'PRCST'}
    # Süzgeç durumu adreste: proje + durum + grup seçimi korunur.
    html = c.get('/?proje=PA&donem=hepsi&durum=onayli&grup=ekleyen').get_data(as_text=True)
    kart = html.split('id="personel-ozet"', 1)[1].split('<div class="ana-alt-izgara">', 1)[0]
    assert '<option value="PA" selected' in kart and 'value="ekleyen" data-po-degisim checked' in kart and 'tg_ayla' in kart and 'tg_mehmet' not in kart
    assert '<option value="onayli" selected' in kart


def test_hucre_baglantilari_kayitlar_listesiyle_birebir(web):
    c, a = web
    tohumla(a)
    login(c)
    denenen = 0
    for sorgu in ('donem=hepsi', 'donem=hepsi&durum=onayli', 'donem=ay&durum=bekleyen', 'donem=hafta&grup=ekleyen', 'donem=hepsi&sutun=tip',
                  'donem=son30&proje=OF', 'donem=hepsi&grup=ekleyen&sutun=tip&proje=PA'):
        html = c.get('/rapor/personel?' + sorgu).get_data(as_text=True)
        tablo = html.split('<table class="tablo po-tablo"', 1)[1].split('</table>', 1)[0]
        hucreler = re.findall(r'<a href="(/kayitlar\?[^"]+)" title="[^"]*: (\d+) kayıt">', tablo)
        assert hucreler, sorgu
        for url, n in hucreler:
            sayfa = c.get(unescape(url) + '&boy=96').get_data(as_text=True)
            assert sonuc_sayisi(sayfa) == int(n), (sorgu, url)
            assert 'id="rapor-suzgec-notu"' in sayfa and 'Silinenler hariç' in sayfa
            denenen += 1
        # Satır toplamı bağlantısı (personel adı) ve toplam satırı da aynı sayıyı verir.
        for url, ad in re.findall(r'<th scope="row" class="po-ad-sutun" data-deger="[^"]*"><a href="(/kayitlar\?[^"]+)" title="([^"]+) — kayıtları aç">', tablo):
            toplam = int(re.search(re.escape(ad) + r' — kayıtları aç">.*?</th>\s*<td class="po-sayi po-toplam" data-deger="(\d+)"', unescape(tablo), re.S).group(1))
            assert sonuc_sayisi(c.get(unescape(url) + '&boy=96').get_data(as_text=True)) == toplam, (sorgu, ad)
        alt = tablo.split('<tfoot>', 1)[1]
        url, n = re.search(r'<a href="(/kayitlar\?[^"]+)"><b>(\d+)</b></a>', alt).groups()
        assert sonuc_sayisi(c.get(unescape(url) + '&boy=96').get_data(as_text=True)) == int(n)
    assert denenen >= 20
    # Sıfır hücre bağlantı değildir; 2.3.5: boş kategori sütunu '__bos__' ile Kayıtlar'da açılır.
    html = c.get('/rapor/personel?donem=hepsi').get_data(as_text=True)
    assert '<span class="po-sifir">0</span>' in html and 'kategori=%28bo%C5%9F%29' not in html and 'kategori=__bos__' in html
    # Boş personel: __bos__ işareti.
    sayfa = c.get('/kayitlar?durum=hepsi&personel=__bos__&silinmemis=1').get_data(as_text=True)
    assert sonuc_sayisi(sayfa) == 1 and 'Personel: (boş)' in sayfa
    # Kayıtlar başlangıç tarihi artık saatsiz eski Excel tarihini de kapsar.
    sayfa = c.get('/kayitlar?durum=hepsi&personel=ayse&tarih1=%s&tarih2=%s' % (AY_BASI, AY_BASI)).get_data(as_text=True)
    assert sonuc_sayisi(sayfa) == (2 if AY_BASI == BUGUN else 1)
    # Excel (bu görünüm) da aynı yeni süzgeçleri taşır.
    r = c.get('/disa-aktar.xlsx?durum=hepsi&personel=ali&kategori=CVPS&silinmemis=1')
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb['Kayıtlar'].max_row - 1 == 4


# ---------------------------------------------------------------- 3. yetki kapsamı

def test_yetki_kapsami_ve_gizle_kurali(web):
    c, a = web
    tohumla(a)
    a['ONAYSIZ_GORUNUM'] = 'gizle'
    hesap(a, 'okucu', 'PA:oku')
    hesap(a, 'ktci', 'OF')
    login(c, 'okucu')
    html = c.get('/rapor/personel?donem=hepsi').get_data(as_text=True)
    assert 'deniz' in html and 'ayse' not in html and 'fatma' not in html
    assert 'Onay yetkiniz olmayan projelerde onay bekleyen kayıtlar sayılmaz' in html
    tablo = html.split('<tfoot>', 1)[1]
    assert re.search(r'<a href="/kayitlar\?[^"]+"><b>3</b></a>', tablo)  # PA onaylılar: deniz 1 + ece 1 + ali 1
    assert '<select name="durum" data-po-degisim disabled' in html
    # bekleyen istense de onaylıya sabitlenir; OF istenirse 403.
    html = c.get('/rapor/personel?donem=hepsi&durum=bekleyen').get_data(as_text=True)
    assert re.search(r'<tfoot>.*?<b>3</b>', html, re.S)
    assert c.get('/rapor/personel?proje=OF').status_code == 403
    assert c.get('/rapor/personel.xlsx?proje=OF').status_code == 403
    assert c.get('/?proje=OF').status_code == 403
    wb = openpyxl.load_workbook(io.BytesIO(c.get('/rapor/personel.xlsx?donem=hepsi&durum=bekleyen').data))
    assert [r[0].value for r in wb['Özet'].iter_rows(min_row=2)][-1] == 'Toplam' and wb['Özet'].cell(wb['Özet'].max_row, 2).value == 3
    # Ana sayfa kartı da aynı kapsamı kullanır.
    kart = c.get('/?donem=hepsi').get_data(as_text=True).split('id="personel-ozet"', 1)[1].split('<div class="ana-alt-izgara">', 1)[0]
    assert '<b>3</b> kanıt' in kart and '<b>0</b> bekleyen' in kart
    # kt yetkili OF kullanıcısı: yalnız OF, bekleyenler görünür (kural kt'si olmayan projelere uygulanır).
    c2 = panel.app.test_client(); login(c2, 'ktci')
    html = c2.get('/rapor/personel?donem=hepsi').get_data(as_text=True)
    assert 'deniz' not in html and 'fatma' not in html and 'ayse' in html
    alt = html.split('<tfoot>', 1)[1]
    assert re.search(r'<b>11</b>', alt)  # OF silinmemiş 11 kayıt
    assert c2.get('/rapor/personel?proje=PA').status_code == 403
    # Menüde "Rapor" bağlantısı: projesi olan herkes görür.
    assert '>Rapor</a>' in html and '/rapor/personel' in html


# ---------------------------------------------------------------- 4. rapor sayfası, çıktılar ve yazdırma

def test_rapor_sayfasi_suzgecler_toplam_isi_ve_siralama(web):
    c, a = web
    tohumla(a)
    login(c)
    html = c.get('/rapor/personel?donem=hepsi').get_data(as_text=True)
    for parca in ('Personel bazında kanıtlar', 'value="ozel"', 'Özel aralık', 'name="tarih1"', 'name="tarih2"', 'name="sutun"', '>Kategori<', '>Tip<',
                  "Excel'e aktar", '>CSV<', '>Yazdır<', 'data-po-sirala', 'data-po-sirala-dugme', 'aria-sort="descending"', '<tfoot>',
                  'isi-5', 'Oluşturma:', 'Yalnız silinmemiş kayıtlar sayılır', 'aria-current="page">Rapor</a>', 'po-lider'):
        assert parca in html, parca
    assert '/rapor/personel.xlsx?donem=hepsi' in unescape(html) and '/rapor/personel.csv?donem=hepsi' in unescape(html)
    assert 'data-po-tarihler hidden' in html
    html = c.get('/rapor/personel?donem=ozel&tarih1=2020-01-01&tarih2=2030-12-31&sutun=tip').get_data(as_text=True)
    assert 'data-po-tarihler >' in html or 'data-po-tarihler>' in html.replace(' >', '>')
    assert 'value="2020-01-01"' in html and 'title="Telesekreter"' in html
    # Kaçış: personel adındaki HTML yazılmaz.
    tohumla(a, [('OF', '<img src=x onerror=alert(1)>', 'DDS', 'Sessiz', ts(BUGUN), 1, 0, 'tg', 'telegram')])
    html = c.get('/rapor/personel?donem=hepsi').get_data(as_text=True)
    assert '<img src=x' not in html and '&lt;img src=x' in html


def test_excel_csv_ve_yazdir(web):
    c, a = web
    tohumla(a, [('OF', '=HYPERLINK("http://x")', 'DDS', 'Sessiz', ts(BUGUN), 1, 0, '@tg', 'telegram')])
    login(c)
    r = c.get('/rapor/personel.xlsx?donem=hepsi&proje=OF')
    assert r.status_code == 200 and r.mimetype.endswith('spreadsheetml.sheet')
    ad = re.search(r'filename=([^;]+)', r.headers['Content-Disposition']).group(1).strip('"')
    assert ad == 'rapor-personel-of-hepsi-%s.xlsx' % BUGUN.isoformat()
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ['Özet', 'Durumlar', 'Bilgi']  # 2.3.7: ikinci sayfa Durumlar
    ws = wb['Özet']
    con = db.baglan(a['DB'])
    f, _, _ = po.filtre_coz({'donem': 'hepsi', 'proje': 'OF'}, ['OF', 'PA', 'HI'])
    o = po.personel_ozeti(con, ['OF', 'PA', 'HI'], None, f); con.close()
    baslik = [x.value for x in ws[1]]
    assert baslik == ['Personel', 'Toplam', 'Onaylı', 'Bekleyen', 'Onay %'] + o['sutunlar']
    satirlar = [[x.value for x in row] for row in ws.iter_rows(min_row=2)]
    assert len(satirlar) == len(o['satirlar']) + 1
    for satir, x in zip(satirlar, o['satirlar']):
        assert satir[0] == (x['personel'] if not x['personel'].startswith('=') else "'" + x['personel'])
        assert satir[1:5] == [x['toplam'], x['onayli'], x['bekleyen'], x['onay_orani']]
        assert satir[5:] == [x['sutunlar'][s] for s in o['sutunlar']]
    assert satirlar[-1][:4] == ['Toplam', o['toplam']['toplam'], o['toplam']['onayli'], o['toplam']['bekleyen']]
    assert satirlar[-1][5:] == [o['toplam']['sutunlar'][s] for s in o['sutunlar']]
    assert ws.freeze_panes == 'B2' and ws['A1'].font.bold and ws['A1'].fill.fgColor.rgb.endswith('1F2937')
    assert ws[ws.max_row][0].font.bold and ws.column_dimensions['A'].width >= 12
    assert not any(isinstance(v, str) and v.startswith('=') for row in satirlar for v in row)
    bilgi = {r[0].value: r[1].value for r in wb['Bilgi'].iter_rows()}
    assert bilgi['Proje'] == 'OF' and bilgi['Dönem'].startswith('Tümü') and bilgi['Oluşturan'] == 'testadmin'
    # CSV: UTF-8 BOM, noktalı virgül, aynı tablo.
    r = c.get('/rapor/personel.csv?donem=hepsi&proje=OF')
    assert r.status_code == 200 and r.mimetype == 'text/csv' and r.data.startswith(b'\xef\xbb\xbf')
    assert 'rapor-personel-of-hepsi-%s.csv' % BUGUN.isoformat() in r.headers['Content-Disposition']
    metin = r.data.decode('utf-8-sig')
    assert '\r\n' in metin
    rows = list(csv.reader(io.StringIO(metin), delimiter=';'))
    assert rows[0] == baslik and rows[-1][0] == 'Toplam' and rows[-1][1] == str(o['toplam']['toplam'])
    assert any(r_[0] == '\'=HYPERLINK("http://x")' for r_ in rows) and not any(r_[0].startswith('=') for r_ in rows)
    # Ekleyen gruplaması: "@tg" de korunur.
    rows = list(csv.reader(io.StringIO(c.get('/rapor/personel.csv?donem=hepsi&grup=ekleyen&sutun=tip').data.decode('utf-8-sig')), delimiter=';'))
    assert rows[0][0] == 'Ekleyen' and "'@tg" in [x[0] for x in rows] and 'Telesekreter' in rows[0]
    # İşlem geçmişine yazılır.
    c_ = db.baglan(a['DB']); n = c_.execute("SELECT COUNT(*) FROM denetim WHERE islem='rapor_aktar'").fetchone()[0]; c_.close()
    assert n == 3 and panel.ISLEM_ADLARI['rapor_aktar'] and panel.DENETIM_ADLARI['rapor_aktar']
    # Yazdır: ?yazdir=1 sayfayı yazdırma kipinde açar; baskı stili menü ve süzgeçleri gizler, A4 yatay.
    html = c.get('/rapor/personel?donem=hepsi&yazdir=1').get_data(as_text=True)
    assert 'data-po-yazdir' in html and re.search(r'href="/rapor/personel\?donem=hepsi[^"]*yazdir=1"', unescape(html))
    css = (ROOT / 'app' / 'static' / 'stil.css').read_text(encoding='utf-8')
    baski = css.split('@media print {', 1)[1]
    assert 'size: A4 landscape' in baski and '.ust' in baski and '.po-filtre' in baski and '.rapor-eylemler' in baski
    js = (ROOT / 'app' / 'static' / 'rapor.js').read_text(encoding='utf-8')
    assert 'window.print()' in js and '[data-po-yazdir]' in js
    if shutil.which('node'):
        assert subprocess.run(['node', '--check', str(ROOT / 'app' / 'static' / 'rapor.js')], capture_output=True, timeout=60).returncode == 0


def test_gecersiz_parametreler_500_vermez(web):
    c, a = web
    tohumla(a)
    login(c)
    for sorgu in ('donem=yil', 'durum=silinen', "grup=x'--", 'sutun=kt', 'donem=ozel&tarih1=2026-13-45', 'donem=ozel', 'tarih1=abc&tarih2=def',
                  'proje=', 'proje=hepsi', 'donem=ozel&tarih1=2026-12-31&tarih2=2026-01-01'):
        for yol in ('/', '/rapor/personel', '/rapor/personel.xlsx', '/rapor/personel.csv'):
            r = c.get(yol + '?' + sorgu)
            assert r.status_code == 200, (yol, sorgu, r.status_code)
    html = c.get('/rapor/personel?donem=yil').get_data(as_text=True)
    assert 'geçersiz değer' in html and 'role="status"' in html
    for yol in ('/', '/rapor/personel', '/rapor/personel.xlsx', '/rapor/personel.csv'):
        assert c.get(yol + '?proje=YOKPROJE').status_code == 403
    # Girişsiz istek giriş sayfasına gider.
    anon = panel.app.test_client()
    for yol in ('/rapor/personel', '/rapor/personel.xlsx', '/rapor/personel.csv'):
        assert anon.get(yol).status_code == 302


def test_projesiz_kullanici(web):
    c, a = web
    hesap(a, 'bos', 'PA:oku')
    con = db.baglan(a['DB']); con.execute("UPDATE panel_kullanicilari SET yetki='' WHERE kullanici_adi='bos'"); con.close()
    login(c, 'bos')
    r = c.get('/rapor/personel')
    if r.status_code == 200:
        html = r.get_data(as_text=True)
        assert 'Yetkili proje yok' in html and '>Rapor</a>' not in html
        assert c.get('/rapor/personel.xlsx').status_code == 403


# ---------------------------------------------------------------- 5. API

def test_api_personel_ozet(web):
    c, a = web
    tohumla(a)
    assert c.get('/api/v1/personel-ozet').status_code == 401
    _, k_hep = anahtar(a, '*', yalniz_onayli=False)
    r = c.get('/api/v1/personel-ozet?donem=hepsi', headers=B(k_hep))
    assert r.status_code == 200 and r.json['ok'] is True
    d = r.json
    assert set(d) >= {'satirlar', 'sutunlar', 'toplam', 'kisi_sayisi', 'kayit_sayisi', 'donem', 'filtre'}
    assert d['filtre'] == dict(proje=None, projeler=d['filtre']['projeler'], donem='hepsi', durum='hepsi', grup='personel', sutun='kategori', kategori=None,
                               tarih1=None, tarih2=None)
    assert d['toplam']['toplam'] == 18 and set(d['satirlar'][0]) == {'personel', 'bos', 'toplam', 'onayli', 'bekleyen', 'onay_orani', 'sutunlar'}
    assert d['satirlar'][0]['personel'] == 'ali' and d['satirlar'][0]['sutunlar']['CVPS'] == 4
    assert 'Cache-Control' in r.headers and 'no-store' in r.headers['Cache-Control']
    r = c.get('/api/v1/personel-ozet?donem=bugun&grup=ekleyen&sutun=tip&durum=bekleyen', headers=B(k_hep)).json
    bek = {('tg_mehmet', 'Sessiz'), ('tg_hasan', 'Telesekreter')} | ({('tg_ayla', 'Sessiz')} if HAFTA_BASI == BUGUN else set())
    assert {(x['personel'], s) for x in r['satirlar'] for s, n in x['sutunlar'].items() if n} == bek
    assert r['donem']['tarih1'] == r['donem']['tarih2'] == BUGUN.isoformat()
    # Proje kapsamı.
    _, k_pa = anahtar(a, ['PA'], yalniz_onayli=False)
    d = c.get('/api/v1/personel-ozet?donem=hepsi', headers=B(k_pa)).json
    assert d['filtre']['projeler'] == ['PA'] and d['toplam']['toplam'] == 4 and {x['personel'] for x in d['satirlar']} == {'deniz', 'ece', 'ali'}
    r = c.get('/api/v1/personel-ozet?proje=OF', headers=B(k_pa))
    assert r.status_code == 403 and r.json['ok'] is False
    assert c.get('/api/v1/personel-ozet?proje=OF,PA', headers=B(k_hep)).status_code == 400
    # yalniz_onayli: durum onaylıya sabitlenir.
    _, k_onay = anahtar(a, '*')
    d = c.get('/api/v1/personel-ozet?donem=hepsi&durum=bekleyen', headers=B(k_onay)).json
    assert d['filtre']['durum'] == 'onayli' and d['toplam']['bekleyen'] == 0 and d['toplam']['toplam'] == 12 and 'yalnız onaylı' in d['uyari']
    # Geçersiz parametre → 400 (500 değil).
    for q in ('donem=yil', 'durum=x', 'grup=y', 'sutun=z', 'donem=ozel&tarih1=2026-99-01', 'donem=ozel'):
        r = c.get('/api/v1/personel-ozet?' + q, headers=B(k_hep))
        assert r.status_code == 400 and r.json['ok'] is False, q
    # Günlüğe yazılır.
    con = db.baglan(a['DB'])
    try:
        assert con.execute("SELECT COUNT(*) FROM api_gunlugu WHERE uc LIKE '%personel-ozet%'").fetchone()[0] >= 5
    finally:
        con.close()


def test_belgeler_guncel():
    api_doc = (ROOT / 'API_KULLANIM.md').read_text(encoding='utf-8')
    assert '/api/v1/personel-ozet' in api_doc and 'curl' in api_doc.split('/api/v1/personel-ozet', 1)[1]
    assert (ROOT / 'DEGISIKLIKLER_v2.3.4.md').exists()
    assert '2.3.4 ile gelenler' in (ROOT / 'KURULUM_ADIMLARI_v2.3.md').read_text(encoding='utf-8')
    assert 'Personel bazında kanıt' in (ROOT / 'README.md').read_text(encoding='utf-8')


# ---------------------------------------------------------------- 6. tarayıcı: ekran görüntüleri ve taşma denetimi

def _playwright_var():
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_kart_ve_rapor_acik_koyu_telefon(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    isimler = ['AHMET.Y', 'BURCU.K', 'CEM.T', 'DERYA.S', 'EMRE.A', 'FUNDA.O', 'GÖKHAN.E', 'HANDE.B', 'İLKER.Ç', 'JALE.M', 'KEREM.U', 'LALE.N']
    kats = ['CVPS', 'DDS', 'HGST', 'ARK', 'PRCST', 'DDT', 'LPST']
    ekstra = []
    for i, ad in enumerate(isimler):
        for j in range(14 - i):
            ekstra.append((['OF', 'PA', 'HI'][j % 3], ad, kats[(i + j) % len(kats)], 'Sessiz' if j % 2 else 'Telesekreter',
                           ts(BUGUN - timedelta(days=j % 5)), 1 if j % 4 else 0, 0, 'tg_%d' % (j % 4), 'telegram'))
    # Baskı/telefon denetimi: aynı önekli uzun adlar ilk 3'te; çok sayıda kişi tabloyu birkaç A4 sayfasına yayar.
    for ad, n in (('AYŞEGÜL KARAKOYUNLU-YILDIRIM.A', 20), ('AYŞEGÜL KARAKOYUNLU-YILDIRIM.B', 18)):
        ekstra += [('OF', ad, kats[j % len(kats)], 'Sessiz', ts(BUGUN), 1, 0, 'tg_0', 'telegram') for j in range(n)]
    ekstra += [('PA', 'PERSONEL.%02d' % i, kats[i % len(kats)], 'Sessiz', ts(BUGUN), i % 2, 0, 'tg_1', 'telegram') for i in range(60)]
    tohumla(a, ekstra)
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    try:
        ekran = os.environ.get('KP_EKRAN_KLASOR', EKRAN_KLASOR)
        Path(ekran).mkdir(parents=True, exist_ok=True)
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, EKRAN_KLASOR=ekran)
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=180, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        try:
            sunucu.close()
        except Exception:
            pass
