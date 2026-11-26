# -*- coding: utf-8 -*-
"""2.3.7 — Personel raporunda "Durumlar": ortalamanın altında kalanlar, hiç eklenmeyen sütunlar, önceki döneme göre düşüş,
onay bekleyeni yüksek olanlar ve öne çıkanlar. Elle hesaplanmış örnekler (her grup ve her eşik), önceki dönem sınırları,
yalnız önceki dönemde kaydı olanlar, kişi sayısı ≤ 1, kategori süzgeci, tip / ekleyen kipleri, sıralama ve sınırlar,
bağlantıların açtığı kayıt sayısı, Excel "Durumlar" sayfası, API ve yetki, ana sayfa özet satırı ve tarayıcı senaryosu
(Node + Playwright yoksa tarayıcı testi atlanır)."""
import io
import os
import re
import subprocess
import threading
import time
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import openpyxl
import pytest

from app import api, db, panel, personel_ozeti as po
from tests.test_web import web, login  # noqa: F401
from tests.test_personel_ozet_234 import BUGUN, B, anahtar, hesap, sonuc_sayisi, ts, _playwright_var

ROOT = Path(__file__).resolve().parents[1]
TARAYICI_BETIK = Path(__file__).with_name('rapor_durumlar_tarayici.js')
EKRAN_KLASOR = '/tmp/kanit-ekran/p237'

# Örnek pencere: 11–20 Mart 2025 (10 gün) → önceki dönem 1–10 Mart 2025.
T1, T2 = '2025-03-11', '2025-03-20'
ONCEKI = ('2025-03-01', '2025-03-10')
SORGU = 'proje=OF&donem=ozel&tarih1=%s&tarih2=%s' % (T1, T2)

# Bu dönem: kişi → [(kategori, adet, bekleyen adedi)]. Sütun toplamları CVPS 42, HGST 21, ARK 10, DDS 2; 5 kişi, 75 kayıt.
# Ortalamalar: CVPS 8,4 · HGST 4,2 · ARK 2,0 · DDS 0,4 (2'nin altı, yok sayılır) · genel 15,0.
BU_DONEM = {
    '210': [('CVPS', 3, 0), ('HGST', 4, 3), ('DDS', 1, 0)],
    '273': [('CVPS', 12, 0), ('ARK', 2, 0)],
    '280': [('CVPS', 20, 0), ('HGST', 8, 0), ('ARK', 3, 0), ('DDS', 1, 0)],
    '171': [('CVPS', 5, 0), ('HGST', 6, 4), ('ARK', 1, 0)],
    '255': [('CVPS', 2, 0), ('HGST', 3, 0), ('ARK', 4, 2)],
}
# Önceki dönem: 190 ve 199 bu dönem hiç yok; 171 31 → 12 (%61), 210 12 → 8 (%33); 280 40 → 32 (%20, işaretlenmez).
ONCEKI_DONEM = {'210': [('CVPS', 12, 0)], '171': [('HGST', 31, 0)], '280': [('CVPS', 40, 0)], '273': [('ARK', 3, 0)],
                '255': [('ARK', 2, 0)], '190': [('DDS', 12, 0)], '199': [('CVPS', 2, 0)]}
TIP = {'CVPS': 'Sessiz'}  # diğerleri Telesekreter

BEKLENEN_50 = {
    'ortalama_alti': ['210, ARK kategorisinde ortalamanın yarısından az kayıt ekledi (0 / ort. 2,0 · %0)',
                      '255, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (2 / ort. 8,4 · %24)',
                      '210, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (3 / ort. 8,4 · %36)'],
    'hic_eklemedi': ['273 bu dönemde hiç HGST eklemedi (ort. 4,2)'],
    'dusus': ['190: bu dönem hiç kayıt yok (önceki dönem 12)', '199: bu dönem hiç kayıt yok (önceki dönem 2)',
              '171: önceki döneme göre %61 düşüş (31 → 12)', '210: önceki döneme göre %33 düşüş (12 → 8)'],
    'bekleyen': ['210: onay bekleyen oranı yüksek (3 / 8 · %38)', '171: onay bekleyen oranı yüksek (4 / 12 · %33)'],
    'one_cikan': ['280, CVPS kategorisinde en çok kaydı ekledi (20 / ort. 8,4 · %238)', '280 ortalamanın üstünde (32 / ort. 15,0 · %213)'],
}
ALTI_75 = ['210, ARK kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (0 / ort. 2,0 · %0)',
           '255, CVPS kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (2 / ort. 8,4 · %24)',
           '210, CVPS kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (3 / ort. 8,4 · %36)',
           '171, ARK kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (1 / ort. 2,0 · %50)',
           '210 toplamda ortalamanın dörtte üçünden az kayıt ekledi (8 / ort. 15,0 · %53)',
           '171, CVPS kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (5 / ort. 8,4 · %60)',
           '255 toplamda ortalamanın dörtte üçünden az kayıt ekledi (9 / ort. 15,0 · %60)',
           '255, HGST kategorisinde ortalamanın dörtte üçünden az kayıt ekledi (3 / ort. 4,2 · %71)']
ALTI_100 = {('210', 'CVPS'), ('255', 'CVPS'), ('171', 'CVPS'), ('210', 'HGST'), ('255', 'HGST'), ('210', 'ARK'), ('171', 'ARK'),
            ('210', None), ('255', None), ('171', None), ('273', None)}


@pytest.fixture(autouse=True)
def _api_sinir(monkeypatch):
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    monkeypatch.delenv('API_ACIK', raising=False)
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


def ekle(a, donem, gun, proje='OF'):
    """donem: kişi → [(kategori, adet, bekleyen)] — gun tarihine kayıt ekler (ekleyen_ad = 'tg_' + kişi)."""
    c = db.baglan(a['DB'])
    with db.transaction(c):
        for kisi, parcalar in donem.items():
            for kat, adet, bekleyen in parcalar:
                for i in range(adet):
                    c.execute('INSERT INTO kayitlar(anahtar,proje,personel,kategori,tip,tarih,kt,silindi,ekleyen_ad,kaynak) VALUES(?,?,?,?,?,?,?,?,?,?)',
                              ('d237:%s:%s:%d:%d' % (kisi, kat, i, time.time_ns()), proje, kisi, kat, TIP.get(kat, 'Telesekreter'),
                               '%s %02d:00:00' % (gun, 8 + i % 10), 0 if i < bekleyen else 1, 0, 'tg_' + kisi, 'telegram'))
    c.close()


def ornek(a):
    ekle(a, BU_DONEM, '2025-03-15')
    ekle(a, ONCEKI_DONEM, '2025-03-05')
    ekle(a, {'210': [('CVPS', 9, 0)]}, '2025-02-28')   # önceki pencerenin hemen dışı: sayılmaz
    ekle(a, {'210': [('CVPS', 7, 0)]}, '2025-03-21')   # bu pencerenin hemen dışı: sayılmaz


def hesapla(a, **arg):
    con = db.baglan(a['DB'])
    try:
        f, h, _ = po.filtre_coz(dict(dict(proje='OF', donem='ozel', tarih1=T1, tarih2=T2), **arg), ['OF', 'PA', 'HI'])
        assert not h, h
        o = po.personel_ozeti(con, ['OF', 'PA', 'HI'], None, f)
        of = po.onceki_filtre(f, BUGUN)
        oo = po.personel_ozeti(con, ['OF', 'PA', 'HI'], None, of) if of else None
        return po.durumlar(o, oo, f['esik'], f)
    finally:
        con.close()


def metinler(d):
    return {g['kod']: [o['aciklama'] for o in g['ogeler']] for g in d['gruplar']}


def bolum(html):
    m = re.search(r'<section class="kart po-kart po-durumlar" id="durumlar".*?</section>', html, re.S)
    assert m, 'Durumlar bölümü yok'
    return m.group(0)


def satirlar(html):
    """Durumlar bölümündeki satırlar: [(grup kodu, href, düz metin, gizli mi)]."""
    out = []
    for kod, govde in re.findall(r'<div class="po-durum-grup po-durum-(\w+)" data-po-durum-grup[^>]*>(.*?)</ul>', bolum(html), re.S):
        for gizli, href, ic in re.findall(r'<li data-po-durum-oge( hidden)?><a href="([^"]+)"[^>]*>(.*?)</a></li>', govde, re.S):
            out.append((kod, unescape(href), unescape(re.sub(r'<[^>]+>', '', ic)).strip(), bool(gizli)))
    return out


# ---------------------------------------------------------------- 1. önceki dönem

def test_onceki_aralik_her_donem():
    gun = date(2026, 11, 26)  # perşembe
    def aralik(donem, bugun=gun, **ek):
        f, h, _ = po.filtre_coz(dict(donem=donem, **ek), ['OF'], bugun=bugun)
        assert not h
        r = po.onceki_aralik(f, bugun)
        return (r[0].isoformat(), r[1].isoformat()) if r else None
    assert aralik('bugun') == ('2026-11-25', '2026-11-25')
    assert aralik('hafta') == ('2026-11-16', '2026-11-19')                     # pazartesi–perşembe → geçen pazartesi–perşembe
    assert aralik('hafta', bugun=date(2026, 11, 23)) == ('2026-11-16', '2026-11-16')  # pazartesi
    assert aralik('ay') == ('2026-10-06', '2026-10-31')                        # 1–26 Kasım (26 gün) → 1 Kasım'dan önceki 26 gün
    assert aralik('ay', bugun=date(2026, 12, 1)) == ('2026-11-30', '2026-11-30')  # ayın ilk günü → önceki tek gün
    assert aralik('ay', bugun=date(2026, 3, 31)) == ('2026-01-29', '2026-02-28')  # 31 gün, şubat kısa
    assert aralik('ay', bugun=date(2024, 3, 2)) == ('2024-02-28', '2024-02-29')   # artık yıl
    assert aralik('son30') == ('2026-09-28', '2026-10-27')
    assert aralik('ozel', tarih1='2026-11-10', tarih2='2026-11-12') == ('2026-11-07', '2026-11-09')
    assert aralik('ozel', tarih1='2026-11-12', tarih2='2026-11-10') == ('2026-11-07', '2026-11-09')  # ters tarih yer değiştirir
    assert aralik('ozel', tarih1='2026-01-01', tarih2='2026-01-01') == ('2025-12-31', '2025-12-31')  # yıl dönümü
    assert aralik('ozel', tarih1='2026-11-20') == ('2026-11-13', '2026-11-19')  # yalnız başlangıç: bitiş bugün
    assert aralik('ozel', tarih2='2026-11-20') is None                         # başlangıçsız aralık: karşılaştırma yok
    assert aralik('hepsi') is None
    f = po.onceki_filtre(po.filtre_coz(dict(donem='ay', kategori='CVPS', durum='onayli', grup='ekleyen', sutun='tip', proje='OF'), ['OF'], bugun=gun)[0], gun)
    assert (f['donem'], f['tarih1'], f['tarih2'], f['kategori'], f['durum'], f['grup'], f['sutun'], f['proje']) == \
        ('ozel', '2026-10-06', '2026-10-31', 'CVPS', 'onayli', 'ekleyen', 'tip', 'OF')
    # Eşik: 50 / 75 / 100 ("%75" de olur); başka değer hata, varsayılan %50.
    assert po.filtre_coz({}, ['OF'])[0]['esik'] == 50
    assert po.filtre_coz({'esik': '%75'}, ['OF'])[0]['esik'] == 75
    f, h, _ = po.filtre_coz({'esik': '33'}, ['OF'])
    assert f['esik'] == 50 and h and 'esik' in h[0]


def test_onceki_donem_sinirlari_veritabaninda(web):
    """Önceki pencerenin ilk ve son günü sayılır, bir gün dışı sayılmaz; ay başı ve özel aralık."""
    c, a = web
    ornek(a)
    d = hesapla(a)
    assert (d['onceki']['tarih1'], d['onceki']['tarih2']) == ONCEKI
    assert d['onceki']['etiket'] == '01.03.2025 – 10.03.2025' and d['onceki']['kayit_sayisi'] == 102
    ekle(a, {'777': [('CVPS', 4, 0)]}, '2025-03-01')   # önceki pencerenin ilk günü
    ekle(a, {'778': [('CVPS', 5, 0)]}, '2025-03-10')   # son günü
    ekle(a, {'779': [('CVPS', 6, 0)]}, '2025-02-28')   # dışı
    metin = metinler(hesapla(a))['dusus']
    assert '777: bu dönem hiç kayıt yok (önceki dönem 4)' in metin and '778: bu dönem hiç kayıt yok (önceki dönem 5)' in metin
    assert not any(m.startswith('779') for m in metin)
    # Gerçek "bu ay": önceki dönem ayın 1'inden önceki aynı sayıda gündür.
    ay_basi = BUGUN.replace(day=1)
    ilk = ay_basi - timedelta(days=BUGUN.day)
    ekle(a, {'AY1': [('CVPS', 3, 0)]}, ilk.isoformat())
    ekle(a, {'AY2': [('CVPS', 3, 0)]}, (ilk - timedelta(days=1)).isoformat())
    ekle(a, {'AY3': [('CVPS', 3, 0)]}, (ay_basi - timedelta(days=1)).isoformat())
    d = hesapla(a, donem='ay', tarih1='', tarih2='')
    assert (d['onceki']['tarih1'], d['onceki']['tarih2']) == (ilk.isoformat(), (ay_basi - timedelta(days=1)).isoformat())
    kisiler = {o['kisi'] for g in d['gruplar'] for o in g['ogeler']}
    assert {'AY1', 'AY3'} <= kisiler and 'AY2' not in kisiler
    # Tümü: karşılaştırma yok, düşüş grubu boş.
    d = hesapla(a, donem='hepsi', tarih1='', tarih2='')
    assert d['onceki'] is None and 'dusus' not in metinler(d)


# ---------------------------------------------------------------- 2. elle hesaplanmış örnek

def test_elle_hesaplanan_gruplar_esik_50(web):
    c, a = web
    ornek(a)
    d = hesapla(a)
    assert (d['kisi_sayisi'], d['kayit_sayisi'], d['genel_ortalama'], d['esik']) == (5, 75, 15.0, 50)
    assert d['ortalamalar']['CVPS'] == 8.4 and d['ortalamalar']['HGST'] == 4.2 and d['ortalamalar']['ARK'] == 2.0 and d['ortalamalar']['DDS'] == 0.4
    assert metinler(d) == BEKLENEN_50
    assert [g['kod'] for g in d['gruplar']] == ['ortalama_alti', 'hic_eklemedi', 'dusus', 'bekleyen', 'one_cikan']
    alti = d['gruplar'][0]['ogeler']
    assert (alti[1]['kisi'], alti[1]['sutun'], alti[1]['sayi'], alti[1]['ortalama'], alti[1]['yuzde']) == ('255', 'CVPS', 2, 8.4, 24)
    dus = d['gruplar'][2]['ogeler']
    assert (dus[2]['kisi'], dus[2]['sayi'], dus[2]['onceki'], dus[2]['degisim_yuzde']) == ('171', 12, 31, -61)
    assert (dus[0]['onceki'], dus[0]['degisim_yuzde'], dus[0]['baglanti']) == (12, -100, 'onceki')
    assert [p['metin'] for p in d['ozet_parcalar']] == ['2 kişi ortalamanın altında', '1 kişi bazı kategorilerde hiç eklemedi', '4 düşüş',
                                                         '2 kişi onay bekleyeni yüksek', '1 kişi öne çıkıyor']
    assert d['isaret_sayisi'] == 12 and d['kiyas'] and not d['kiyas_notu']


def test_elle_hesaplanan_esik_75_ve_100(web):
    c, a = web
    ornek(a)
    d = hesapla(a, esik='75')
    assert metinler(d)['ortalama_alti'] == ALTI_75
    for kod in ('hic_eklemedi', 'dusus', 'bekleyen', 'one_cikan'):  # eşik yalnız "ortalamanın altında"yı değiştirir
        assert metinler(d)[kod] == BEKLENEN_50[kod]
    d = hesapla(a, esik='100')
    alti = d['gruplar'][0]['ogeler']
    assert {(o['kisi'], o['sutun']) for o in alti} == ALTI_100 and len(alti) == 11
    oranlar = [o['sayi'] / o['ortalama'] for o in alti]
    assert oranlar == sorted(oranlar)  # en kötü önce
    assert all('ortalamadan az' in o['aciklama'] for o in alti)
    # 273'ün HGST sıfırı "hiç eklemedi"de kalır, "ortalamanın altında"ya ayrıca girmez.
    assert ('273', 'HGST') not in {(o['kisi'], o['sutun']) for o in alti}


def test_durum_onayli_bekleyen_grubu_yok_ve_kucuk_kume(web):
    c, a = web
    ornek(a)
    assert 'bekleyen' not in metinler(hesapla(a, durum='onayli'))
    # Tek kişi: kıyaslı gruplar yok, not gösterilir; bekleyen ve düşüş yine hesaplanır.
    ekle(a, {'210': [('CVPS', 6, 3)]}, '2025-06-05')
    ekle(a, {'210': [('CVPS', 20, 0)]}, '2025-05-28')
    d = hesapla(a, tarih1='2025-06-01', tarih2='2025-06-10')
    assert d['kisi_sayisi'] == 1 and not d['kiyas'] and d['kiyas_notu'] == 'Kıyas için en az 2 kişi gerekir.'
    assert metinler(d) == {'dusus': ['210: önceki döneme göre %70 düşüş (20 → 6)'], 'bekleyen': ['210: onay bekleyen oranı yüksek (3 / 6 · %50)']}
    # Hiç kimse yok: kıyas notu, boş liste.
    d = hesapla(a, tarih1='2025-08-01', tarih2='2025-08-10')
    assert d['kisi_sayisi'] == 0 and d['gruplar'] == [] and d['kiyas_notu']
    # İki kişi: sütun kıyası var, "toplamda ortalamanın altında" (en az 3 kişi ister) yok.
    ekle(a, {'A': [('CVPS', 10, 0), ('HGST', 1, 0)], 'B': [('CVPS', 2, 0), ('HGST', 5, 0)]}, '2025-07-05')
    d = hesapla(a, tarih1='2025-07-01', tarih2='2025-07-10')
    assert metinler(d)['ortalama_alti'] == ['B, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (2 / ort. 6,0 · %33)',
                                           'A, HGST kategorisinde ortalamanın yarısından az kayıt ekledi (1 / ort. 3,0 · %33)']


def test_kategori_suzgeci_tip_ve_ekleyen(web):
    c, a = web
    ornek(a)
    # Kategori = CVPS: tek sütun; "toplamda" satırları ve sütun liderleri yinelenmesin diye çıkmaz.
    d = hesapla(a, kategori='CVPS')
    assert metinler(d) == {
        'ortalama_alti': ['255, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (2 / ort. 8,4 · %24)',
                          '210, CVPS kategorisinde ortalamanın yarısından az kayıt ekledi (3 / ort. 8,4 · %36)'],
        'dusus': ['199: bu dönem hiç kayıt yok (önceki dönem 2)', '210: önceki döneme göre %75 düşüş (12 → 3)',
                  '280: önceki döneme göre %50 düşüş (40 → 20)'],
        'one_cikan': ['280 ortalamanın üstünde (20 / ort. 8,4 · %238)']}
    # Sütun = tip: Sessiz 42 (ort. 8,4), Telesekreter 33 (ort. 6,6).
    d = hesapla(a, sutun='tip')
    alti = metinler(d)['ortalama_alti']
    assert '273, Telesekreter tipinde ortalamanın yarısından az kayıt ekledi (2 / ort. 6,6 · %30)' in alti
    assert '255, Sessiz tipinde ortalamanın yarısından az kayıt ekledi (2 / ort. 8,4 · %24)' in alti
    assert d['ozet_parcalar'][0]['metin'].endswith('kişi ortalamanın altında')
    # Grupla = ekleyen: aynı sayılar, ekleyen adlarıyla; açıklamada "ekleyen".
    d = hesapla(a, grup='ekleyen')
    assert metinler(d)['ortalama_alti'] == [m.replace('210', 'tg_210').replace('255', 'tg_255') for m in BEKLENEN_50['ortalama_alti']]
    assert d['isim'] == 'ekleyen' and d['ozet_parcalar'][0]['metin'] == '2 ekleyen ortalamanın altında'


def test_siralama_esitlik_ve_sinirlar(web, monkeypatch):
    c, a = web
    # Eşit oranlar: önce büyük ortalamalı sütun, sonra ad (harf duyarsız), sonra sütun sırası.
    ekle(a, {'b': [('CVPS', 1, 0), ('HGST', 10, 0)], 'A': [('CVPS', 1, 0), ('HGST', 10, 0)], 'c': [('CVPS', 13, 0), ('HGST', 10, 0)]}, '2025-09-05')
    d = hesapla(a, tarih1='2025-09-01', tarih2='2025-09-10')
    assert [o['kisi'] for o in d['gruplar'][0]['ogeler']] == ['A', 'b']
    assert hesapla(a, tarih1='2025-09-01', tarih2='2025-09-10') == d  # belirlenimci
    # Sınır: grupta en çok DURUM_AZAMI satır; sayaç tüm sayıyı verir.
    ornek(a)
    monkeypatch.setattr(po, 'DURUM_AZAMI', 3)
    g = hesapla(a, esik='75')['gruplar'][0]
    assert (g['sayi'], len(g['ogeler']), g['kesildi'], g['kisi_sayisi']) == (8, 3, 5, 3)
    # Kişisi boş satırlar ve kategorisi boş sütunlar ortalamaya katılır, işaretlenmez.
    ekle(a, {'': [('CVPS', 1, 1), ('', 30, 0)]}, '2025-10-05')
    ekle(a, {'x': [('CVPS', 9, 0)], 'y': [('CVPS', 9, 0)]}, '2025-10-05')
    d = hesapla(a, tarih1='2025-10-01', tarih2='2025-10-10')
    assert not any(o['kisi'] == po.BOS or o['sutun'] == po.BOS for g in d['gruplar'] for o in g['ogeler'])
    assert d['kisi_sayisi'] == 3 and d['genel_ortalama'] == round(49 / 3, 1)


# ---------------------------------------------------------------- 3. rapor sayfası, bağlantılar, ana sayfa

def test_rapor_bolumu_ve_baglantilar_birebir(web):
    c, a = web
    ornek(a)
    login(c)
    html = c.get('/rapor/personel?' + SORGU).get_data(as_text=True)
    b = bolum(html)
    assert 'Ortalama = dönemdeki kişi başına kayıt (75 kayıt ÷ 5 kişi = 15,0); eşik %50: ortalamanın yarısının altı.' in b
    assert 'Önceki dönem: 01.03.2025 – 10.03.2025.' in b and 'değerlendirme değildir' in b
    assert html.index('class="po-ozet"') < html.index('id="durumlar"') < html.index('id="po-kartlar"')  # çiplerle kartlar arasında
    assert 'Durumlar eşiği: %50' in html
    assert len(re.findall(r'name="esik" value="(\d+)" form="po-filtre-form"', b)) == 3 and 'id="po-filtre-form"' in html
    assert re.search(r'value="50" form="po-filtre-form" data-po-esik checked', b)
    rozetler = dict(re.findall(r'po-durum-(\w+)" data-po-durum-grup.*?<span class="po-rozet"[^>]*>(\d+)</span>', b, re.S))
    assert rozetler == {k: str(len(v)) for k, v in BEKLENEN_50.items()}
    sat = satirlar(html)
    assert {k: [m for kk, _, m, _ in sat if kk == k] for k in BEKLENEN_50} == BEKLENEN_50
    assert not any(gizli for *_, gizli in sat)  # 8'den az: hepsi görünür
    denenen = 0
    for kod, href, metin, _ in sat:
        assert href.startswith('/kayitlar?') and 'silinmemis=1' in href and 'proje=OF' in href, href
        n = sonuc_sayisi(c.get(href + '&boy=96').get_data(as_text=True))
        sayilar = [int(x) for x in re.findall(r'\d+', metin.split('(', 1)[1])]
        if kod == 'dusus' and 'hiç kayıt yok' in metin:
            assert n == sayilar[0] and 'tarih1=%s' % ONCEKI[0] in href and 'tarih2=%s' % ONCEKI[1] in href, (metin, n, href)
        elif kod == 'dusus':
            assert n == sayilar[1], (metin, n)                       # bu dönemin kayıtları (31 → 12'de 12)
        elif kod == 'hic_eklemedi':
            kisi = metin.split(' ', 1)[0]
            assert n == sum(x[1] for x in BU_DONEM[kisi])             # kişinin dönemdeki tüm kayıtları
        elif kod == 'bekleyen':
            assert n == sayilar[0] and 'durum=bekleyen' in href
        elif ' ARK kategorisinde' in metin and sayilar[0] == 0:
            assert n == 8 and 'kategori=' not in href                 # sıfır: kişinin tüm kayıtları açılır
        else:
            assert n == sayilar[0], (metin, n, href)
        denenen += 1
    assert denenen == 12
    # Eşik %100: 11 satır → 8 görünür, 3 gizli + "Daha fazla göster"; geçersiz eşik uyarı verir.
    html = c.get('/rapor/personel?' + SORGU + '&esik=100').get_data(as_text=True)
    alti = [s for s in satirlar(html) if s[0] == 'ortalama_alti']
    assert len(alti) == 11 and sum(1 for s in alti if s[3]) == 3
    assert 'Daha fazla göster (3 satır daha)' in bolum(html) and 'Durumlar eşiği: %100' in html
    assert 'esik=100' in unescape(re.search(r'href="([^"]+)" download>Excel', html).group(1))
    html = c.get('/rapor/personel?' + SORGU + '&esik=33').get_data(as_text=True)
    assert 'esik için geçersiz değer' in html and 'Durumlar eşiği: %50' in html
    # Unicode rakamlar (², ７５) 500 değil, uyarı verir; ana sayfa ve Excel de açılır.
    for kotu in ('²', '７５', '٥0'):
        r = c.get('/rapor/personel?' + SORGU + '&esik=' + kotu)
        assert r.status_code == 200 and 'esik için geçersiz değer' in r.get_data(as_text=True), kotu
        assert c.get('/rapor/personel.xlsx?' + SORGU + '&esik=' + kotu).status_code == 200, kotu
        assert c.get('/?esik=' + kotu).status_code == 200, kotu
    # Yazdırma görünümünde bölüm vardır.
    assert 'id="durumlar"' in c.get('/rapor/personel?' + SORGU + '&yazdir=1').get_data(as_text=True)
    # Tip ve ekleyen kipleri: bağlantılar tip= / ekleyen_ad= taşır, sayılar tutar.
    for ek, anahtar_ in (('&sutun=tip', 'tip='), ('&grup=ekleyen', 'ekleyen_ad=')):
        sat = satirlar(c.get('/rapor/personel?' + SORGU + ek).get_data(as_text=True))
        hucre = [s for s in sat if s[0] == 'ortalama_alti' and 'toplamda' not in s[2] and '(0 /' not in s[2]]
        assert hucre
        for _, href, metin, _ in hucre:
            assert anahtar_ in href
            assert sonuc_sayisi(c.get(href + '&boy=96').get_data(as_text=True)) == int(re.search(r'\((\d+) /', metin).group(1))


def test_bos_durum_ve_kiyas_notu_sayfada(web):
    c, a = web
    ekle(a, {'x': [('CVPS', 4, 0)], 'y': [('CVPS', 4, 0)], 'z': [('CVPS', 4, 0)]}, '2025-05-05')
    ekle(a, {'tek': [('CVPS', 2, 0)]}, '2025-11-05')
    login(c)
    b = bolum(c.get('/rapor/personel?proje=OF&donem=ozel&tarih1=2025-05-01&tarih2=2025-05-10').get_data(as_text=True))
    assert 'Bu dönemde dikkat çeken bir durum yok.' in b and 'data-po-durum-grup' not in b
    b = bolum(c.get('/rapor/personel?proje=OF&donem=ozel&tarih1=2025-11-01&tarih2=2025-11-10').get_data(as_text=True))
    assert 'Kıyas için en az 2 kişi gerekir.' in b
    b = bolum(c.get('/rapor/personel?proje=OF&donem=hepsi').get_data(as_text=True))
    assert 'Önceki dönemle karşılaştırma yok' in b


def test_ana_sayfa_ozet_satiri(web):
    c, a = web
    login(c)
    html = c.get('/').get_data(as_text=True)
    assert 'data-po-durum-ozet' not in html and 'id="durumlar"' not in html  # kayıt yok: satır gizli
    ekle(a, {'x': [('CVPS', 4, 0)], 'y': [('CVPS', 4, 0)], 'z': [('CVPS', 4, 0)]}, BUGUN.isoformat())
    assert 'data-po-durum-ozet' not in c.get('/').get_data(as_text=True)  # dikkat çeken yok: satır gizli
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("DELETE FROM kayitlar WHERE personel IN ('x','y','z')")
    con.close()
    ekle(a, BU_DONEM, BUGUN.isoformat())
    html = c.get('/').get_data(as_text=True)
    m = re.search(r'<p class="po-durum-ozet" data-po-durum-ozet>(.*?)</p>', html, re.S)
    assert m, 'özet satırı yok'
    metin = unescape(re.sub(r'<[^>]+>', '', m.group(1)))
    assert re.sub(r'\s+', ' ', metin).strip() == ('Durumlar: 2 kişi ortalamanın altında · 1 kişi bazı kategorilerde hiç eklemedi · '
                                                  '2 kişi onay bekleyeni yüksek · 1 kişi öne çıkıyor Rapor →')
    href = unescape(re.search(r'<a class="metin-baglanti" href="([^"]+)">Rapor', m.group(1)).group(1))
    assert href.startswith('/rapor/personel?') and href.endswith('#durumlar') and 'donem=ay' in href
    assert html.index('class="po-ozet"') < html.index('data-po-durum-ozet') < html.index('id="po-kartlar"')
    # Kart süzgeci bağlantıya taşınır.
    html = c.get('/?proje=OF&donem=bugun&kategori=CVPS').get_data(as_text=True)
    href = unescape(re.search(r'data-po-durum-ozet>.*?href="([^"]+)">Rapor', html, re.S).group(1))
    assert 'proje=OF' in href and 'donem=bugun' in href and 'kategori=CVPS' in href and href.endswith('#durumlar')


# ---------------------------------------------------------------- 4. Excel, CSV, API

def test_excel_durumlar_sayfasi_ve_csv(web):
    c, a = web
    ornek(a)
    login(c)
    wb = openpyxl.load_workbook(io.BytesIO(c.get('/rapor/personel.xlsx?' + SORGU).data))
    assert wb.sheetnames == ['Özet', 'Durumlar', 'Bilgi']
    ws = wb['Durumlar']
    rows = [[x.value for x in r] for r in ws.iter_rows()]
    assert rows[0] == ['Grup', 'Kişi', 'Kategori/Sütun', 'Sayı', 'Ortalama', 'Yüzde/Değişim', 'Açıklama']
    assert [r[6] for r in rows[1:]] == [m for k in BEKLENEN_50 for m in BEKLENEN_50[k]]
    assert rows[2] == ['Ortalamanın altında', '255', 'CVPS', 2, 8.4, 0.24, BEKLENEN_50['ortalama_alti'][1]]
    assert rows[4] == ['Hiç eklemedi', '273', 'HGST', 0, 4.2, 0, BEKLENEN_50['hic_eklemedi'][0]]
    assert rows[7][:6] == ['Önceki döneme göre düşüş', '171', 'Toplam', 12, None, -0.61]
    assert rows[9][:6] == ['Onay bekleyeni yüksek', '210', 'Toplam', 3, None, 0.38]
    assert ws.cell(3, 6).number_format == '0%' and ws.cell(3, 5).number_format == '0.0'
    bilgi = {r[0].value: r[1].value for r in wb['Bilgi'].iter_rows()}
    assert bilgi['Durumlar eşiği'] == '%50 (ortalamanın yarısının altı)' and bilgi['Önceki dönem'] == '01.03.2025 – 10.03.2025'
    ws = openpyxl.load_workbook(io.BytesIO(c.get('/rapor/personel.xlsx?' + SORGU + '&esik=75').data))['Durumlar']
    assert [r[6].value for r in ws.iter_rows(min_row=2) if r[0].value == 'Ortalamanın altında'] == ALTI_75
    ws = openpyxl.load_workbook(io.BytesIO(c.get('/rapor/personel.xlsx?proje=OF&donem=ozel&tarih1=2025-12-01&tarih2=2025-12-02').data))['Durumlar']
    assert ws.max_row == 2 and ws.cell(2, 7).value == 'Kıyas için en az 2 kişi gerekir.'
    # CSV değişmedi: tek tablo, Durumlar yok.
    csv_metin = c.get('/rapor/personel.csv?' + SORGU).data.decode('utf-8-sig')
    assert 'Durumlar' not in csv_metin and 'ortalama' not in csv_metin and csv_metin.splitlines()[0].startswith('Personel;Toplam;')


def test_api_durumlar(web):
    c, a = web
    ornek(a)
    yol = '/api/v1/personel-ozet?' + SORGU
    assert c.get(yol + '&durumlar=1').status_code == 401  # anahtarsız
    _, k = anahtar(a, '*', yalniz_onayli=False)
    d = c.get(yol, headers=B(k)).json
    assert d['ok'] and 'durumlar' not in d and 'esik' not in d['filtre']
    d = c.get(yol + '&durumlar=1', headers=B(k)).json
    du = d['durumlar']
    assert d['filtre']['esik'] == 50 and (du['esik'], du['kisi_sayisi'], du['kayit_sayisi'], du['genel_ortalama'], du['kiyas']) == (50, 5, 75, 15.0, True)
    assert du['onceki_donem'] == dict(tarih1=ONCEKI[0], tarih2=ONCEKI[1], kayit_sayisi=102) and du['ortalamalar']['CVPS'] == 8.4
    assert [g['kod'] for g in du['gruplar']] == ['ortalama_alti', 'hic_eklemedi', 'dusus', 'bekleyen', 'one_cikan']
    assert {g['kod']: [o['aciklama'] for o in g['ogeler']] for g in du['gruplar']} == BEKLENEN_50
    assert du['gruplar'][0]['ogeler'][1] == dict(kisi='255', sutun='CVPS', sayi=2, ortalama=8.4, yuzde=24, onceki=None, degisim_yuzde=None,
                                                aciklama=BEKLENEN_50['ortalama_alti'][1])
    assert du['gruplar'][2]['ogeler'][2] == dict(kisi='171', sutun=None, sayi=12, ortalama=None, yuzde=None, onceki=31, degisim_yuzde=-61,
                                                aciklama=BEKLENEN_50['dusus'][2])
    d = c.get(yol + '&durumlar=1&esik=75', headers=B(k)).json
    assert [o['aciklama'] for o in d['durumlar']['gruplar'][0]['ogeler']] == ALTI_75
    for kotu in ('&durumlar=1&esik=33', '&durumlar=2', '&esik=abc', '&durumlar=1&esik=²', '&durumlar=1&esik=７５', '&esik=٥0'):
        r = c.get(yol + kotu, headers=B(k))
        assert r.status_code == 400 and r.json['ok'] is False, kotu
    d = c.get('/api/v1/personel-ozet?proje=OF&donem=hepsi&durumlar=1', headers=B(k)).json
    assert d['durumlar']['onceki_donem'] is None and d['durumlar']['gruplar'][2]['ogeler'] == []
    # Yalnız onaylı anahtar: bekleyen grubu boş; kapsam dışı proje 403.
    _, k2 = anahtar(a, ['OF'], yalniz_onayli=True, ad='Onaylı')
    d = c.get(yol + '&durumlar=1', headers=B(k2)).json
    assert d['filtre']['durum'] == 'onayli' and d['durumlar']['gruplar'][3]['ogeler'] == []
    assert c.get('/api/v1/personel-ozet?proje=PA&durumlar=1', headers=B(k2)).status_code == 403


def test_yetki_kapsami(web):
    """Takım lideri yalnız kendi projesinin kişilerini görür; başka projeden kişi önceki dönemde bile listelenmez."""
    c, a = web
    ornek(a)
    ekle(a, {'PAKISI': [('CVPS', 9, 0)]}, '2025-03-05', proje='PA')
    hesap(a, 'lider', 'OF')
    login(c, 'lider')
    html = c.get('/rapor/personel?donem=ozel&tarih1=%s&tarih2=%s' % (T1, T2)).get_data(as_text=True)
    assert 'PAKISI' not in bolum(html) and '190: bu dönem hiç kayıt yok' in bolum(html)
    assert c.get('/rapor/personel?proje=PA&donem=ay').status_code == 403


def test_belgeler_237():
    assert (ROOT / 'DEGISIKLIKLER_v2.3.7.md').exists()
    assert '2.3.7 ile gelenler:' in (ROOT / 'KURULUM_ADIMLARI_v2.3.md').read_text(encoding='utf-8')
    api_doc = (ROOT / 'API_KULLANIM.md').read_text(encoding='utf-8').split('/api/v1/personel-ozet', 1)[1]
    assert 'durumlar=1' in api_doc and '"degisim_yuzde"' in api_doc and '`esik`' in api_doc
    assert 'test_rapor_durumlar_237.py' in (ROOT / 'TEST_SONUCLARI.md').read_text(encoding='utf-8')
    assert 'Durumlar' in (ROOT / 'README.md').read_text(encoding='utf-8')


# ---------------------------------------------------------------- 5. tarayıcı

@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_durumlar(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    ay_basi = BUGUN.replace(day=1)
    kats = ['CVPS', 'HGST', 'ARK', 'DDS', 'PRCST', 'LPST', 'DDT']
    bu, once = {}, {}
    for i in range(30):
        ad = '%d' % (200 + i) if i % 11 else 'AYŞEGÜL KARAKOYUNLU-YILDIRIM.%d' % i
        bu[ad] = [(kats[j], max(0, (12 - i // 3) - 2 * j + (i % 4)), (i % 5 == 0) * 3) for j in range(len(kats))]
        bu[ad] = [p for p in bu[ad] if p[1] > 0] or [('CVPS', 1, 0)]
        once[ad] = [('CVPS', 6 + i % 9, 0)]
    once['190'] = [('DDS', 12, 0)]
    ekle(a, bu, BUGUN.isoformat())
    ekle(a, once, (ay_basi - timedelta(days=1)).isoformat())
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    try:
        ekran = os.environ.get('KP_EKRAN_KLASOR', EKRAN_KLASOR)
        Path(ekran).mkdir(parents=True, exist_ok=True)
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, EKRAN_KLASOR=ekran)
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=300, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        try:
            sunucu.close()
        except Exception:
            pass
