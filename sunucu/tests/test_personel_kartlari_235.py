# -*- coding: utf-8 -*-
"""2.3.5 — Personel raporu: kategori süzgeci, herkes için kişi kartları (ilk 6 + "Daha fazla göster"), kart içi kategori
kutuları (bağlantılar Kayıtlar listesiyle birebir), hatırlanan süzgeçler, Excel/CSV/API kategori parametresi ve
Playwright ekran görüntüleri (Node + Playwright yoksa tarayıcı testi atlanır)."""
import csv
import io
import os
import re
import subprocess
import threading
from datetime import timedelta
from html import unescape
from pathlib import Path

import openpyxl
import pytest

from app import api, db, panel, personel_ozeti as po
from tests.test_web import web, login  # noqa: F401
from tests.test_personel_ozet_234 import (BUGUN, KAYITLAR, B, anahtar, hesap, matris, sonuc_sayisi, tohumla, ts,
                                          _playwright_var)

ROOT = Path(__file__).resolve().parents[1]
TARAYICI_BETIK = Path(__file__).with_name('personel_kartlari_tarayici.js')
EKRAN_KLASOR = '/tmp/claude-0/p235'
PROJELER = ['OF', 'PA', 'HI']


@pytest.fixture(autouse=True)
def _api_sinir(monkeypatch):
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    monkeypatch.delenv('API_ACIK', raising=False)
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


def sql_beklenen(con, projeler, f):
    """Bağımsız SQL başvurusu: veri işlevinden ayrı, düz WHERE + Python'da kırpma/casefold ile (grup, sütun) → sayı."""
    kosul, par = ['silindi=0', 'proje IN (%s)' % ','.join('?' * len(projeler))], list(projeler)
    if f['durum'] == 'onayli':
        kosul.append('kt=1')
    elif f['durum'] == 'bekleyen':
        kosul.append('kt=0')
    if f.get('tarih1'):
        kosul.append("tarih IS NOT NULL AND substr(tarih,1,10) >= ?"); par.append(f['tarih1'])
    if f.get('tarih2'):
        kosul.append("tarih IS NOT NULL AND substr(tarih,1,10) <= ?"); par.append(f['tarih2'])
    out = {}
    for r in con.execute('SELECT personel,ekleyen_ad,kategori,tip FROM kayitlar WHERE ' + ' AND '.join(kosul), par):
        kat = (r['kategori'] or '').strip()
        if f.get('kategori'):
            hedef = '' if f['kategori'] == po.BOS_DEGER else f['kategori'].strip().casefold()
            if kat.casefold() != hedef:
                continue
        g_ = ((r['personel'] if f['grup'] == 'personel' else r['ekleyen_ad']) or '').strip() or po.BOS
        s_ = ((kat if f['sutun'] == 'kategori' else (r['tip'] or '').strip()) or po.BOS).casefold()
        out[(g_, s_)] = out.get((g_, s_), 0) + 1
    return out


# ---------------------------------------------------------------- 1. veri işlevi

# Hazır dönemler + özel aralık (iki tarih, yalnız başlangıç, yalnız bitiş, donem yazılmadan yalnız tarih).
DONEM_DENEMELERI = [dict(donem=d) for d in ('bugun', 'hafta', 'ay', 'son30', 'hepsi')] + [
    dict(donem='ozel', tarih1=(BUGUN - timedelta(days=45)).isoformat(), tarih2=(BUGUN - timedelta(days=5)).isoformat()),
    dict(donem='ozel', tarih1=(BUGUN - timedelta(days=12)).isoformat(), tarih2=BUGUN.isoformat()),
    dict(donem='ozel', tarih1=(BUGUN - timedelta(days=20)).isoformat()),
    dict(donem='ozel', tarih2=(BUGUN - timedelta(days=1)).isoformat()),
    dict(tarih1=BUGUN.isoformat(), tarih2=BUGUN.isoformat()),
]

def test_kategori_suzgeci_tum_birlesimler_bagimsiz_sql(web):
    c, a = web
    tohumla(a)
    con = db.baglan(a['DB'])
    try:
        denenen = 0
        for kategori in ('CVPS', 'cvps', ' HGST ', 'DDS', 'ARK', 'EskiKategori', po.BOS_DEGER, '(boş)', 'YOK-BOYLE'):
            for proje in ('', 'OF', 'PA'):
                for donem in DONEM_DENEMELERI:
                    for durum in ('hepsi', 'onayli', 'bekleyen'):
                        for grup in ('personel', 'ekleyen'):
                            for sutun in ('kategori', 'tip'):
                                f, h, _ = po.filtre_coz(dict(proje=proje, durum=durum, grup=grup, sutun=sutun, kategori=kategori, **donem), PROJELER)
                                assert not h
                                o = po.personel_ozeti(con, PROJELER, None, f)
                                bek = sql_beklenen(con, [proje] if proje else PROJELER, f)
                                assert matris(o) == bek, (kategori, proje, donem, durum, grup, sutun)
                                assert o['toplam']['toplam'] == sum(bek.values())
                                assert sum(o['toplam']['sutunlar'].values()) == o['toplam']['toplam']
                                if sutun == 'kategori':
                                    assert len(o['sutunlar']) == 1, o['sutunlar']  # yalnız seçilen kategori sütunu
                                denenen += 1
        assert denenen > 2500
        # Harf biçimi katalog adına eşlenir; '(boş)' ve '__bos__' aynı anlamdadır.
        f, _, _ = po.filtre_coz(dict(donem='hepsi', kategori='cvps'), PROJELER)
        o = po.personel_ozeti(con, PROJELER, None, f)
        assert o['sutunlar'] == ['CVPS'] and o['kategori_adi'] == 'CVPS' and o['toplam']['toplam'] == 4
        assert po.filtre_coz(dict(kategori='(boş)'), PROJELER)[0]['kategori'] == po.BOS_DEGER
        f, _, _ = po.filtre_coz(dict(donem='hepsi', kategori=po.BOS_DEGER), PROJELER)
        o = po.personel_ozeti(con, PROJELER, None, f)
        assert o['sutunlar'] == [po.BOS] and o['toplam']['toplam'] == 1 and o['kategori_adi'] == po.BOS
        # Bilinmeyen kategori: hata değil, sıfır satır; sütun sıfırla görünür.
        f, h, _ = po.filtre_coz(dict(donem='hepsi', kategori='YOK-BOYLE'), PROJELER)
        o = po.personel_ozeti(con, PROJELER, None, f)
        assert not h and o['satirlar'] == [] and o['sutunlar'] == ['YOK-BOYLE'] and o['toplam']['toplam'] == 0
        # Sütun = tip: tipler seçilen kategori içinde sayılır.
        f, _, _ = po.filtre_coz(dict(donem='hepsi', kategori='CVPS', sutun='tip'), PROJELER)
        o = po.personel_ozeti(con, PROJELER, None, f)
        ali = next(x for x in o['satirlar'] if x['personel'] == 'ali')
        assert ali['sutunlar'] == {'Sessiz': 3, 'Telesekreter': 1}
        # Seçenekler: önce katalog sırası, sonra kayıtlardaki diğer adlar, en sonda (boş).
        sec = po.kategori_secenekleri(con, PROJELER)
        adlar = [s['ad'] for s in sec]
        assert adlar[-2:] == ['EskiKategori', po.BOS] and sec[-1]['deger'] == po.BOS_DEGER and 'cvps' not in adlar and 'HGST ' not in adlar
        assert po.dosya_parcasi('S.ARK') == 's-ark' and po.dosya_parcasi('30gün') == '30gun' and po.dosya_parcasi(po.BOS_DEGER) == 'bos'
    finally:
        con.close()


# ---------------------------------------------------------------- 2. kartlar ve kutu bağlantıları

def _kartlar(html):
    return re.findall(r'<li class="po-lider-kart po-kisi-kart[^"]*" data-po-kart( hidden)?>(.*?)\n    </li>', html, re.S)


def test_kart_kutulari_ve_ad_baglantilari_kayitlarla_birebir(web):
    c, a = web
    ekstra = [('OF', 'kisi%02d' % i, ['CVPS', 'DDS', 'HGST', 'ARK', ''][i % 5], 'Sessiz', ts(BUGUN), i % 2, 0, 'tg_%d' % (i % 3), 'telegram')
              for i in range(14) for _ in range(1 + i % 3)]
    tohumla(a, ekstra)
    login(c)
    denenen = 0
    for sorgu in ('donem=hepsi', 'donem=hepsi&durum=onayli', 'donem=ay&durum=bekleyen', 'donem=hepsi&grup=ekleyen', 'donem=hepsi&sutun=tip',
                  'donem=hepsi&kategori=CVPS', 'donem=hepsi&kategori=cvps&sutun=tip', 'donem=hepsi&kategori=__bos__', 'donem=son30&proje=OF&kategori=DDS',
                  'donem=hepsi&grup=ekleyen&sutun=tip&kategori=HGST', 'donem=hepsi&proje=PA',
                  'donem=ozel&tarih1=%s&tarih2=%s&kategori=CVPS' % ((BUGUN - timedelta(days=45)).isoformat(), BUGUN.isoformat()),
                  'donem=ozel&tarih1=%s&grup=ekleyen' % (BUGUN - timedelta(days=20)).isoformat(),
                  'tarih1=%s&tarih2=%s&kategori=__bos__' % (BUGUN.isoformat(), BUGUN.isoformat())):
        html = c.get('/rapor/personel?' + sorgu).get_data(as_text=True)
        kartlar = _kartlar(html)
        assert kartlar, sorgu
        for _, kart in kartlar[:10]:
            ad_url, ad = re.search(r'<a class="po-lider-ad" href="([^"]+)" title="([^"]+) — tüm kayıtlarını aç">', kart).groups()
            n = int(re.search(r'<div class="po-lider-sayi"><b>(\d+)</b>', kart).group(1))
            assert sonuc_sayisi(c.get(unescape(ad_url) + '&boy=96').get_data(as_text=True)) == n, (sorgu, ad)
            kutular = re.findall(r'<a class="po-kat-kutu" href="([^"]+)"[^>]*title="[^"]*: (\d+) kayıt — listeyi aç">', kart)
            assert kutular and sum(int(k[1]) for k in kutular) == n, (sorgu, ad)
            sayilar = [int(k[1]) for k in kutular]
            assert sayilar == sorted(sayilar, reverse=True)
            for url, k in kutular:
                assert sonuc_sayisi(c.get(unescape(url) + '&boy=96').get_data(as_text=True)) == int(k), (sorgu, url)
                denenen += 1
        if 'grup=ekleyen' in sorgu:
            assert 'ekleyen_ad=' in unescape(kartlar[0][1])
        if 'sutun=tip' in sorgu:
            assert '&tip=' in unescape(kartlar[0][1])
        if 'kategori=' in sorgu:
            assert 'Kategori: ' in html
            if 'sutun=tip' not in sorgu:  # kategori seçiliyken kartta yalnız o kategorinin kutusu kalır
                assert all(len(re.findall(r'class="po-kat-kutu"', k)) == 1 for _, k in kartlar)
    assert denenen >= 80
    # Boş kategori Kayıtlar'da '(boş)' olarak görünür.
    sayfa = c.get('/kayitlar?durum=hepsi&kategori=__bos__&silinmemis=1').get_data(as_text=True)
    assert '(boş) — kategorisi olmayanlar' in sayfa


def test_kirpma_ic_bosluk_ve_turkce_harf_kayitlarla_birebir(web):
    """Sekme / bölünmez boşluk / iç çift boşluk ve İ-ı harf biçimleri: seçenek, süzgeç, kutu ve Kayıtlar aynı sayıyı verir."""
    c, a = web
    gun = ts(BUGUN)
    ekstra = [('OF', 'ali', 'S  ARK', 'Sessiz', gun, 1, 0, 'tg', 'telegram'), ('OF', 'ali', 'S  ARK', 'Sessiz', gun, 1, 0, 'tg', 'telegram'),
              ('OF', 'veli', 'CVPS\t', 'Sessiz', gun, 1, 0, 'tg', 'telegram'), ('OF', 'veli', 'ARK\xa0', 'Sessiz', gun, 1, 0, 'tg', 'telegram'),
              ('OF', 'n\xa0b', 'CVPS', 'Sessiz\t', gun, 1, 0, 'tg\xa0', 'telegram'),
              ('OF', 'tr', 'İPTAL', 'Sessiz', gun, 1, 0, 'tg', 'telegram'), ('OF', 'tr', 'İPTAL', 'Sessiz', gun, 1, 0, 'tg', 'telegram'),
              ('OF', 'tr', 'iptal', 'Sessiz', gun, 1, 0, 'tg', 'telegram'), ('OF', 'tr', 'iptal', 'Sessiz', gun, 1, 0, 'tg', 'telegram'),
              ('OF', 'tr', 'iptal', 'Sessiz', gun, 1, 0, 'tg', 'telegram')]
    tohumla(a, ekstra)
    login(c)
    # Kırpma iç boşluğa dokunmaz; sekme ve bölünmez boşluk SQL tarafıyla aynı biçimde kırpılır.
    assert po.filtre_coz(dict(kategori='S  ARK'), PROJELER)[0]['kategori'] == 'S  ARK'
    assert po.filtre_coz(dict(kategori='ARK\xa0'), PROJELER)[0]['kategori'] == 'ARK'
    html = c.get('/rapor/personel?donem=hepsi&proje=OF').get_data(as_text=True)
    secim = html.split('<select name="kategori"', 1)[1].split('</select>')[0]
    degerler = [unescape(v) for v in re.findall(r'<option value="([^"]*)"', secim)][1:]
    assert 'S  ARK' in degerler and 'İPTAL' in degerler and 'iptal' in degerler
    assert not any(d != d.strip(po.KIRP) for d in degerler), degerler
    for d in degerler:
        rapor = c.get('/rapor/personel', query_string=dict(donem='hepsi', proje='OF', kategori=d)).get_data(as_text=True)
        f, _, _ = po.filtre_coz(dict(donem='hepsi', proje='OF', kategori=d), PROJELER)
        con = db.baglan(a['DB'])
        try:
            beklenen = po.personel_ozeti(con, PROJELER, None, f)['toplam']['toplam']
        finally:
            con.close()
        liste = c.get('/kayitlar', query_string=dict(durum='hepsi', silinmemis='1', proje='OF', kategori=d, boy='96')).get_data(as_text=True)
        assert sonuc_sayisi(liste) == beklenen, (d, beklenen)
        assert 'Kategori: ' in rapor
    sayilar = {}
    for sorgu in ('donem=hepsi&proje=OF', 'donem=hepsi&proje=OF&grup=ekleyen', 'donem=hepsi&proje=OF&sutun=tip',
                  'donem=hepsi&proje=OF&kategori=%C4%B0PTAL', 'donem=hepsi&proje=OF&kategori=iptal&sutun=tip'):
        for _, kart in _kartlar(c.get('/rapor/personel?' + sorgu).get_data(as_text=True)):
            for url, k in re.findall(r'<a class="po-kat-kutu" href="([^"]+)"[^>]*title="([^"]*: \d+) kayıt — listeyi aç">', kart):
                n = int(k.rsplit(': ', 1)[1])
                assert sonuc_sayisi(c.get(unescape(url) + '&boy=96').get_data(as_text=True)) == n, (sorgu, unescape(url), n)
                sayilar[(sorgu, k)] = n
    assert sayilar[('donem=hepsi&proje=OF', 'tr · İPTAL: 2')] == 2 and sayilar[('donem=hepsi&proje=OF', 'tr · iptal: 3')] == 3
    assert sayilar[('donem=hepsi&proje=OF', 'ali · S  ARK: 2')] == 2
    # Kayıtlar: elle yazılan Türkçe harf biçimi kapsamda casefold eşi yoksa yine Türkçe kuralla eşlenir.
    assert panel._tr_kucuk('İPTAL') == panel._tr_kucuk('iptal')
    # Ana sayfa: sonuç yokken telefonda (tablo gizli) boş durum iletisi kartların yerinde görünür.
    ana = c.get('/?kategori=YOKBOYLE').get_data(as_text=True)
    assert 'class="bos-tablo po-mobil-bos">Bu dönemde ve seçimde kanıt yok. Kategori süzgecini kaldırmayı' in ana
    assert 'po-mobil-bos' not in c.get('/?donem=hepsi').get_data(as_text=True)


def test_kart_izgarasi_ilk_6_daha_fazla_ve_hepsi(web):
    c, a = web
    tohumla(a, [('OF', 'kisi%02d' % i, 'DDS', 'Sessiz', ts(BUGUN), 1, 0, 'tg', 'telegram') for i in range(30)])
    login(c)
    for yol in ('/rapor/personel?donem=hepsi', '/?donem=hepsi'):
        html = c.get(yol).get_data(as_text=True)
        kartlar = _kartlar(html)
        toplam = len(kartlar)
        assert toplam >= 36 and sum(1 for h, _ in kartlar if not h) == 6 and all(h for h, _ in kartlar[6:])
        assert 'Daha fazla göster (%d kişi daha)' % (toplam - 6) in html and 'Daha az göster' in html
        assert 'data-po-kart-dugmeler hidden' in html and '<noscript>' in html and 'kartlar=hepsi' in html
        assert 'po-kisi-kart sira-1' in html and 'po-kisi-kart sira-3' in html and 'sira-4' not in html
        html = c.get(yol + '&kartlar=hepsi').get_data(as_text=True)
        assert not any(h for h, _ in _kartlar(html)) and len(_kartlar(html)) == toplam
    # Baskıda kartlar yalnız ?yazdir=1&kartlar=1 ile basılır.
    assert 'po-kartlar-baski' in c.get('/rapor/personel?donem=hepsi&yazdir=1&kartlar=1').get_data(as_text=True)
    assert 'po-kartlar-baski' not in c.get('/rapor/personel?donem=hepsi&yazdir=1').get_data(as_text=True)
    css = (ROOT / 'app' / 'static' / 'stil.css').read_text(encoding='utf-8').split('@media print {', 1)[1]
    assert '.po-kartlar, .po-kart-dugmeler { display: none !important; }' in css and '.po-kartlar.po-kartlar-baski' in css
    # Kişi yoksa kart bölümü yok.
    html = c.get('/rapor/personel?donem=hepsi&kategori=YOK').get_data(as_text=True)
    assert 'data-po-kartlar' not in html and 'YOK (bu seçimde yok)' in html


# ---------------------------------------------------------------- 3. süzgeç çubuğu ve yetki

def test_kategori_secenekleri_yalniz_kendi_projeleri(web):
    c, a = web
    tohumla(a, [('HI', 'x', 'GizliKat', 'Sessiz', ts(BUGUN), 1, 0, 'tg', 'telegram'),
                ('PA', 'y', 'PaOzel', 'Sessiz', ts(BUGUN), 0, 0, 'tg', 'telegram')])
    a['ONAYSIZ_GORUNUM'] = 'gizle'
    hesap(a, 'okucu', 'PA:oku')
    login(c, 'okucu')
    for yol in ('/rapor/personel', '/'):
        html = c.get(yol).get_data(as_text=True)
        secim = html.split('<select name="kategori"', 1)[1].split('</select>', 1)[0]
        degerler = re.findall(r'<option value="([^"]*)"', secim)
        assert degerler[0] == '' and 'Tüm kategoriler' in secim
        assert 'EskiKategori' in degerler and 'ARK' in degerler
        assert 'GizliKat' not in degerler and 'PaOzel' not in degerler  # PaOzel yalnız onaysız kayıtta: gizle kuralı
        assert 'HGST ' not in degerler
    c2 = panel.app.test_client(); login(c2)
    secim = c2.get('/rapor/personel?proje=PA').get_data(as_text=True).split('<select name="kategori"', 1)[1].split('</select>', 1)[0]
    assert 'PaOzel' in secim and 'GizliKat' not in secim
    secim = c2.get('/rapor/personel').get_data(as_text=True).split('<select name="kategori"', 1)[1].split('</select>', 1)[0]
    assert 'GizliKat' in secim and 'value="__bos__"' in secim and '>(boş)<' in secim
    # Seçim adreste korunur; ana sayfadaki rapor bağlantısı kartın süzgeçlerini taşır.
    html = c2.get('/?donem=hepsi&kategori=cvps').get_data(as_text=True)
    assert '<option value="CVPS" selected' in html and 'href="/rapor/personel?donem=hepsi&durum=hepsi&grup=personel&sutun=kategori&kategori=CVPS"' in unescape(html)
    html = c2.get('/').get_data(as_text=True)
    assert 'href="/rapor/personel">Tüm tablo ve rapor' in html  # süzgeçsiz kart: yalın adres (hatırlanan süzgeç uygulanabilsin)


def test_rapor_basligi_ciktilar_ve_api_kategori(web):
    c, a = web
    tohumla(a)
    login(c)
    html = c.get('/rapor/personel?donem=hepsi&kategori=cvps').get_data(as_text=True)
    assert 'Kategori: CVPS · Durum:' in html and 'kategori=CVPS' in unescape(html.split('Excel', 1)[0].rsplit('href=', 1)[1])
    r = c.get('/rapor/personel.xlsx?donem=hepsi&proje=OF&kategori=cvps')
    ad = re.search(r'filename=([^;]+)', r.headers['Content-Disposition']).group(1).strip('"')
    assert ad == 'rapor-personel-of-hepsi-cvps-%s.xlsx' % BUGUN.isoformat()
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert [x.value for x in wb['Özet'][1]] == ['Personel', 'Toplam', 'Onaylı', 'Bekleyen', 'Onay %', 'CVPS']
    bilgi = {x[0].value: x[1].value for x in wb['Bilgi'].iter_rows()}
    assert bilgi['Kategori'] == 'CVPS' and wb['Özet'].cell(wb['Özet'].max_row, 2).value == 3
    assert {x[0].value: x[1].value for x in openpyxl.load_workbook(io.BytesIO(c.get('/rapor/personel.xlsx').data))['Bilgi'].iter_rows()}['Kategori'] == 'Tüm kategoriler'
    r = c.get('/rapor/personel.csv?donem=hepsi&kategori=__bos__')
    assert 'rapor-personel-tum-hepsi-bos-' in r.headers['Content-Disposition']
    rows = list(csv.reader(io.StringIO(r.data.decode('utf-8-sig')), delimiter=';'))
    assert rows[0][-1] == po.BOS and rows[-1][1] == '1'
    for yol in ('/', '/rapor/personel', '/rapor/personel.xlsx', '/rapor/personel.csv'):
        for q in ('kategori=YOK', 'kategori=' + 'x' * 500, "kategori=' OR 1=1--", 'kategori=%00'):
            assert c.get(yol + '?' + q).status_code == 200, (yol, q)
    # API
    _, k = anahtar(a, '*', yalniz_onayli=False)
    d = c.get('/api/v1/personel-ozet?donem=hepsi&kategori=cvps', headers=B(k)).json
    assert d['ok'] and d['filtre']['kategori'] == 'CVPS' and d['sutunlar'] == ['CVPS'] and d['toplam']['toplam'] == 4
    d = c.get('/api/v1/personel-ozet?donem=hepsi&kategori=YOK', headers=B(k)).json
    assert d['ok'] and d['satirlar'] == [] and d['toplam']['toplam'] == 0
    d = c.get('/api/v1/personel-ozet?donem=hepsi&kategori=(boş)&sutun=tip', headers=B(k)).json
    assert d['filtre']['kategori'] == po.BOS and d['toplam']['toplam'] == 1
    assert c.get('/api/v1/personel-ozet?donem=hepsi', headers=B(k)).json['filtre']['kategori'] is None


def test_hatirlanan_suzgec_isaretleri(web):
    c, a = web
    tohumla(a)
    login(c)
    html = c.get('/rapor/personel').get_data(as_text=True)
    assert 'data-po-hatirla="kp.raporSuzgec.testadmin"' in html and 'Son kullandığınız süzgeçler' not in html
    html = c.get('/rapor/personel?proje=PA&donem=ay&kategori=CVPS&hatirlanan=1').get_data(as_text=True)
    assert 'Son kullandığınız süzgeçler uygulandı.' in html and 'href="/rapor/personel?sifirla=1">Varsayılana dön' in html and 'data-po-not-kapat' in html
    html = c.get('/rapor/personel?sifirla=1').get_data(as_text=True)
    assert 'data-po-sifirla' in html
    js = (ROOT / 'app' / 'static' / 'rapor.js').read_text(encoding='utf-8')
    assert 'kp.raporSuzgec' in js and 'sessionStorage' in js and 'location.replace' in js


def test_belgeler_235():
    assert (ROOT / 'DEGISIKLIKLER_v2.3.5.md').exists()
    assert '2.3.5 ile gelenler' in (ROOT / 'KURULUM_ADIMLARI_v2.3.md').read_text(encoding='utf-8')
    api_doc = (ROOT / 'API_KULLANIM.md').read_text(encoding='utf-8')
    assert 'kategori=CVPS' in api_doc and '`kategori`' in api_doc.split('/api/v1/personel-ozet', 1)[1]
    assert 'test_personel_kartlari_235.py' in (ROOT / 'TEST_SONUCLARI.md').read_text(encoding='utf-8')
    assert 'Daha fazla göster' in (ROOT / 'README.md').read_text(encoding='utf-8')


# ---------------------------------------------------------------- 4. tarayıcı

@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_kartlar_kutular_ve_hatirlanan_suzgec(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    kats = ['CVPS', 'DDS', 'HGST', 'ARK', 'PRCST', 'DDT', 'LPST', 'btagsz', 'S.ARK']
    ekstra = []
    for i in range(40):
        for j in range(max(1, 26 - i)):
            ekstra.append((['OF', 'PA'][j % 2] if i % 7 else 'PA', 'PERSONEL.%02d' % i if i % 9 else 'AYŞEGÜL KARAKOYUNLU-YILDIRIM.%d' % i,
                           kats[(i + j * (1 + i % 3)) % len(kats)], 'Sessiz' if j % 2 else 'Telesekreter',
                           ts(BUGUN - timedelta(days=j % 4)), 1 if j % 3 else 0, 0, 'tg_%d' % (j % 4), 'telegram'))
    tohumla(a, ekstra)
    hesap(a, 'lider', 'PA')
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
