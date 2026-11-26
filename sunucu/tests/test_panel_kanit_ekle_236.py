# -*- coding: utf-8 -*-
"""2.3.6 — Panelden kanıt ekleme (kategori SMS): yetki matrisi, doğrulama, alan alan kayıt, onaylı/onaysız yol,
bildirim ve denetim, çift gönderim jetonu, liste / ayrıntı / Excel / API / personel raporu / 2 saat hatırlatması,
katalog geçişi (yeni ve eski veritabanı) ve Playwright ekran görüntüleri (Node + Playwright yoksa tarayıcı testi atlanır)."""
import io
import json
import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

import openpyxl
import pytest

from app import api, db, hatirlatma, katalog, kullanicilar, panel
from tests.test_web import web, login  # noqa: F401
from tests.test_personel_ozet_234 import anahtar, B, _playwright_var

ROOT = Path(__file__).resolve().parents[1]
TARAYICI_BETIK = Path(__file__).with_name('panel_kanit_ekle_tarayici.js')
EKRAN_KLASOR = '/tmp/claude-0/p236'
SIFRE = 'Test-Password-123!'
GYAZO = 'https://gyazo.com/0123456789abcdef0123456789abcdef'
GYAZO2 = 'https://i.gyazo.com/fedcba9876543210fedcba9876543210.png'
SNAPPARK = 'https://img.snappark.net/s/AbC_12-x/raw/'
TEAMZONE = 'https://teamzone.gyazo.com/00112233445566778899aabbccddeeff'
XHR = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}


@pytest.fixture(autouse=True)
def _ortam(monkeypatch):
    monkeypatch.delenv('PANEL_EKLEME_KATEGORI', raising=False)
    monkeypatch.delenv('API_ACIK', raising=False)
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()
    yield
    api.HIZ.sifirla(); api.YETKISIZ_HIZ.sifirla()


def hesap(a, ad, rol):
    kullanicilar.ekle(a, ad, rol, SIFRE); kullanicilar.guncelle(a, ad, sifre_degistir=0)


def istemci(ad='testadmin'):
    c = panel.app.test_client(); login(c, ad)
    return c


def csrf(c):
    with c.session_transaction() as s:
        return s['csrf']


def jeton(c):
    r = c.get('/kayit/yeni.json', headers=XHR)
    assert r.status_code == 200, r.data[:300]
    return r.json['jeton']


def gonder(c, json_mu=True, jeton_degeri=None, **alanlar):
    veri = dict(proje='OF', link=GYAZO, personel='AYŞE.K', uye_id='445566', tip='sessiz')
    veri.update(alanlar)
    veri = {k: v for k, v in veri.items() if v is not None}
    veri['csrf'] = csrf(c)
    veri['jeton'] = jeton(c) if jeton_degeri is None else jeton_degeri
    return c.post('/kayit/yeni', data=veri, headers=XHR if json_mu else {})


def satirlar(a, sql, *par):
    con = db.baglan(a['DB'])
    try:
        return [dict(r) for r in con.execute(sql, par)]
    finally:
        con.close()


def kayit(a, kid):
    return satirlar(a, 'SELECT * FROM kayitlar WHERE id=?', kid)[0]


def kayit_sayisi(a):
    return satirlar(a, 'SELECT COUNT(*) n FROM kayitlar')[0]['n']


# ---------------------------------------------------------------- 1. yetki matrisi

def test_yetki_matrisi_gorunum_ve_gonderim(web):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'duzenleyen', 'OF:oku,duzenle'); hesap(a, 'okucu', 'OF:oku'); hesap(a, 'bos', 'PA:oku')
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("UPDATE panel_kullanicilari SET yetki='' WHERE kullanici_adi='bos'")  # hiçbir projesi olmayan hesap
    con.close()
    beklenen = {'testadmin': True, 'lider': True, 'duzenleyen': True, 'okucu': False, 'bos': False}
    for ad, olur in beklenen.items():
        k = istemci(ad)
        liste = k.get('/kayitlar').get_data(as_text=True)
        ana = k.get('/').get_data(as_text=True)
        assert ('data-kanit-ekle' in liste) is olur, ad
        assert ('id="ekle-modal"' in liste) is olur, ad
        assert ('id="ana-kanit-ekle"' in ana) is olur, ad
        assert 'Kanıt ekleme Telegram botundan ya da yetkili kullanıcılar için panelden yapılır' in liste
        assert 'yalnız Telegram' not in ana and 'Telegram botundan' in ana
        assert k.get('/kayit/yeni').status_code == (200 if olur else 403), ad
        r = k.get('/kayit/yeni.json', headers=XHR)
        assert r.status_code == (200 if olur else 403), ad
        r = k.post('/kayit/yeni', data=dict(csrf=csrf(k), jeton=jeton(k) if olur else 'a' * 32, proje='OF', link=GYAZO, personel='X'), headers=XHR)
        assert r.status_code == (200 if olur else 403), (ad, r.json)
        if olur:
            assert r.json['ok'] and r.json['id']
        else:
            assert r.json['ok'] is False and 'yetki' in r.json['hata']
    # Uygun olmayan proje: lider PA'ya ekleyemez (403), admin ekler.
    lider = istemci('lider')
    r = gonder(lider, proje='PA')
    assert r.status_code == 403 and r.json['ok'] is False
    assert gonder(istemci(), proje='PA').status_code == 200
    # Proje listesi yalnız uygun projeler; tek uygun proje önceden seçili.
    d = lider.get('/kayit/yeni.json', headers=XHR).json
    assert [p['code'] for p in d['projeler']] == ['OF'] and d['secili'] == 'OF' and d['kategori'] == 'SMS'
    assert d['projeler'][0]['kt'] is True
    duz = istemci('duzenleyen').get('/kayit/yeni.json', headers=XHR).json
    assert duz['projeler'][0]['kt'] is False
    sayfa = lider.get('/kayit/yeni').get_data(as_text=True)
    assert '<option value="OF" selected' in sayfa and 'data-ekle-onay' in sayfa and 'kategori-rozet' in sayfa
    # Liste süzgecindeki proje ön seçilir (admin için).
    html = istemci().get('/kayitlar?proje=HI').get_data(as_text=True)
    assert 'href="/kayit/yeni?proje=HI"' in html
    assert 'value="HI" selected' in html.split('id="ekle-form"', 1)[1]
    # Pasif proje eklenemez.
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("UPDATE projeler SET aktif=0 WHERE code='GA'")
    con.close()
    admin = istemci()
    assert 'GA' not in [p['code'] for p in admin.get('/kayit/yeni.json', headers=XHR).json['projeler']]
    assert gonder(admin, proje='GA').status_code == 403
    # Oturumsuz istek: JSON 401.
    anonim = panel.app.test_client()
    assert anonim.post('/kayit/yeni', data={}, headers=XHR).status_code == 401


def test_csrf_zorunlu(web):
    c, a = web
    k = istemci()
    j = jeton(k)
    r = k.post('/kayit/yeni', data=dict(jeton=j, proje='OF', link=GYAZO, personel='X'), headers=XHR)
    assert r.status_code == 400 and 'CSRF' in r.json['hata']
    r = k.post('/kayit/yeni', data=dict(csrf='yanlis', jeton=j, proje='OF', link=GYAZO, personel='X'), headers=XHR)
    assert r.status_code == 400
    assert kayit_sayisi(a) == 0


# ---------------------------------------------------------------- 2. doğrulama

HATALI = [
    (dict(link=''), 'link', 'zorunludur'),
    (dict(link='https://evil.example.com/0123456789abcdef0123456789abcdef'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='http://gyazo.com/0123456789abcdef0123456789abcdef'), 'link', 'https://'),
    (dict(link='ftp://gyazo.com/0123456789abcdef0123456789abcdef'), 'link', 'https://'),
    (dict(link='https://gyazo.com@evil.example.com/0123456789abcdef0123456789abcdef'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='https://kim:sifre@gyazo.com/0123456789abcdef0123456789abcdef'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='https://gyazo.com.evil.example.com/0123456789abcdef0123456789abcdef'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='https://gyazo.com:8443/0123456789abcdef0123456789abcdef'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='https://gyazo.com/ abc'), 'link', 'Yalnız şu adreslerin'),
    (dict(link='https://gyazo.com/kisa'), 'link', 'görsel kimliği'),
    (dict(link='https://img.snappark.net/baska-yol'), 'link', 'görsel kimliği'),
    (dict(link='https://gyazo.com/' + 'a' * 2100), 'link', '2048'),
    (dict(gorsel2='http://i.gyazo.com/x.png'), 'gorsel2', 'https://'),
    (dict(gorsel2=GYAZO), 'gorsel2', 'birinciyle aynı'),
    (dict(personel=''), 'personel', 'zorunludur'),
    (dict(personel='   '), 'personel', 'zorunludur'),
    (dict(personel='P' * 101), 'personel', '100'),
    (dict(uye_id='1' * 501), 'uye_id', '500'),
    (dict(lead_id='L' * 501), 'lead_id', '500'),
    (dict(ana_uye_id='a\x00b'), 'ana_uye_id', 'kontrol karakteri'),
    (dict(aciklama='x' * 501), 'aciklama', '500'),
    (dict(aciklama='satır\x07zil'), 'aciklama', 'kontrol karakteri'),
    (dict(tip='baska'), 'tip', 'listedeki'),
    (dict(tip='Sessiz ve telesekreter'), 'tip', 'listedeki'),
    (dict(proje=''), 'proje', 'Proje seçin'),
]


@pytest.mark.parametrize('alanlar,alan,parca', HATALI)
def test_dogrulama_hatalari(web, alanlar, alan, parca):
    c, a = web
    k = istemci()
    r = gonder(k, **alanlar)
    assert r.status_code == 400, r.json
    assert r.json['ok'] is False and alan in r.json['hatalar'], r.json
    assert parca in r.json['hatalar'][alan], r.json['hatalar'][alan]
    assert kayit_sayisi(a) == 0


def test_jeton_ve_duz_sayfa_hatalari(web):
    c, a = web
    k = istemci()
    # Jeton yok / bozuk / bu oturuma verilmemiş.
    r = gonder(k, jeton_degeri='')
    assert r.status_code == 400 and 'Form kimliği' in r.json['hata'] and re.fullmatch('[0-9a-f]{32}', r.json['jeton'])
    assert gonder(k, jeton_degeri='ZZ' * 16).status_code == 400
    r = gonder(k, jeton_degeri='0' * 32)
    assert r.status_code == 400 and 'Form süresi doldu' in r.json['hata'] and r.json['jeton']
    assert kayit_sayisi(a) == 0
    # Düz sayfa (JS yok): hata satır içinde, değerler korunur, durum 400.
    r = gonder(k, json_mu=False, link='http://gyazo.com/0123456789abcdef0123456789abcdef', personel='KORUNAN.AD')
    html = r.get_data(as_text=True)
    assert r.status_code == 400 and 'Bağlantı https:// ile başlamalıdır' in html and 'value="KORUNAN.AD"' in html
    assert 'aria-invalid="true" class="hatali"' in html and 'Formda düzeltilmesi gereken alanlar var.' in html
    # Düz sayfa başarı: kayda yönlendirir, flash iletisi gösterilir.
    sayfa = k.get('/kayit/yeni').get_data(as_text=True)
    j = re.search(r'name="jeton" value="([0-9a-f]{32})"', sayfa).group(1)
    r = k.post('/kayit/yeni', data=dict(csrf=csrf(k), jeton=j, proje='OF', link=GYAZO, personel='DUZ.SAYFA'))
    assert r.status_code == 302
    kid = int(re.search(r'ac=(\d+)', r.headers['Location']).group(1))
    assert '/kayitlar?' in r.headers['Location'] and 'durum=hepsi' in r.headers['Location']
    assert 'Kayıt #%d eklendi' % kid in k.get(r.headers['Location']).get_data(as_text=True)
    # Aynı jeton tekrar (yenile → yeniden gönder): yeni kayıt yok, aynı kayda gider.
    r = k.post('/kayit/yeni', data=dict(csrf=csrf(k), jeton=j, proje='OF', link=GYAZO, personel='DUZ.SAYFA'))
    assert r.status_code == 302 and 'ac=%d' % kid in r.headers['Location'] and kayit_sayisi(a) == 1


# ---------------------------------------------------------------- 3. kayıt, onay, bildirim, denetim

def _bot_sutunlari():
    """bot.py _commit_record INSERT sütun listesi (kaynak koddan): panel kaydı aynı biçimi doldurur."""
    kaynak = (ROOT / 'app' / 'bot.py').read_text(encoding='utf-8')
    blok = kaynak.split('columns = ["anahtar"', 1)[1].split(']', 1)[0]
    return ['anahtar'] + re.findall(r'"([a-z_]+)"', blok)


def test_onayli_ekleme_alan_alan(web):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'lider2', 'OF:oku,kt'); hesap(a, 'okucu', 'OF:oku')
    k = istemci('lider')
    once = datetime.now().replace(microsecond=0)
    r = gonder(k, link='  ' + GYAZO + '  ', gorsel2=SNAPPARK, personel='  AYŞE.K  ', uye_id='445566', ana_uye_id='778899',
               lead_id='L-1', tip='telesekreter', aciklama='  Müşteri SMS ile döndü.\nİkinci satır.  ', onayli='1')
    assert r.status_code == 200 and r.json['ok'], r.json
    kid = r.json['id']
    assert r.json['mesaj'] == 'Kayıt #%d eklendi (onaylı).' % kid and r.json['kt'] == 1 and r.json['kategori'] == 'SMS'
    assert r.json['damga'] and re.fullmatch('[0-9a-f]{32}', r.json['jeton'])
    k_ = kayit(a, kid)
    assert re.fullmatch(r'panel:[0-9a-f]{32}', k_['anahtar'])
    assert (k_['proje'], k_['kategori'], k_['kategori_code'], k_['kategori_mode']) == ('OF', 'SMS', 'sms', 'tek_uye')
    assert (k_['personel'], k_['uye_id'], k_['ana_uye_id'], k_['lead_id'], k_['tip']) == ('AYŞE.K', '445566', '778899', 'L-1', 'telesekreter')
    assert (k_['link'], k_['link_turu'], k_['gorsel2'], k_['gorsel_dosya'], k_['gorsel2_dosya']) == (GYAZO, 'gyazo', SNAPPARK, None, None)
    assert k_['aciklama'] == 'Müşteri SMS ile döndü.\nİkinci satır.'
    assert (k_['kaynak'], k_['giris_tipi'], k_['ekleyen_id'], k_['ekleyen_ad'], k_['ekleyen_guven']) == ('panel', 'panel', 'panel:lider', 'lider', 'panel')
    assert (k_['kt'], k_['kt_kaynak'], k_['kt_kim']) == (1, 'panel', 'lider')
    assert k_['tarih'] == k_['guncelleme'] == k_['kt_zaman'] == k_['tarih_ham']
    assert once <= datetime.strptime(k_['tarih'], '%Y-%m-%d %H:%M:%S') <= datetime.now() + timedelta(seconds=1)
    assert (k_['ilk_gorulme'], k_['silindi'], k_['surum'], k_['excel_durum']) == (None, 0, 1, 'var')
    assert (k_['telegram_bot_id'], k_['chat_id'], k_['message_id'], k_['file_id']) == (None, None, None, None)
    assert k_['kategori_soru_surumu'] == 1
    anlik = json.loads(k_['soru_anlik_json'])
    assert anlik['category_code'] == 'sms' and anlik['project'] == 'OF' and [q['key'] for q in anlik['questions']] == ['personel', 'uye_id']
    assert json.loads(k_['cevaplar_json']) == {'personel': 'AYŞE.K', 'uye_id': '445566'}
    # Bot kaydının doldurduğu (Telegram'a özgü olmayan) her sütun panel kaydında da dolu.
    telegram_ozel = {'telegram_bot_id', 'file_id', 'file_unique_id', 'message_id', 'chat_id', 'gorsel_dosya', 'ana_uye_id', 'lead_id', 'tip'}
    for sutun in _bot_sutunlari():
        assert sutun in k_, sutun
        if sutun not in telegram_ozel and sutun != 'kt':
            assert k_[sutun] not in (None, ''), sutun
    # Onaylı eklendi: onay bildirimi yok; denetim satırı var.
    assert satirlar(a, 'SELECT * FROM bildirimler WHERE kayit_id=?', kid) == []
    den = satirlar(a, "SELECT * FROM denetim WHERE islem='panel_kanit_ekle'")
    assert len(den) == 1 and den[0]['kullanici'] == 'lider' and den[0]['proje'] == 'OF' and den[0]['anahtar'] == k_['anahtar']
    assert den[0]['hedef_turu'] == 'kayit' and den[0]['hedef_id'] == str(kid) and json.loads(den[0]['yeni'])['onayli'] is True
    assert panel.ISLEM_ADLARI['panel_kanit_ekle'] == 'Panelden kanıt ekledi' and panel.DENETIM_ADLARI['panel_kanit_ekle'] == 'Panelden kanıt'
    assert 'Panelden kanıt ekledi' in istemci().get('/').get_data(as_text=True)  # süperadmin: Son işlemler
    # Değişiklik damgası yazıldı (liste yenileme / zil yoklaması).
    assert satirlar(a, "SELECT deger FROM ayarlar WHERE anahtar='son_degisiklik'")[0]['deger']


def test_onaysiz_ekleme_bildirim_ve_yetki(web):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'lider2', 'OF:oku,kt'); hesap(a, 'okucu', 'OF:oku'); hesap(a, 'pa_lider', 'PA:oku,kt')
    hesap(a, 'duzenleyen', 'OF:oku,duzenle')
    k = istemci('lider')
    r = gonder(k, onayli=None, link=TEAMZONE, tip='')  # kutu işaretsiz
    kid = r.json['id']
    k_ = kayit(a, kid)
    assert r.json['kt'] == 0 and 'onay bekliyor' in r.json['mesaj']
    assert (k_['kt'], k_['kt_kim'], k_['kt_zaman'], k_['link_turu'], k_['tip']) == (0, None, None, 'teamzone', None)
    alicilar = sorted(x['kullanici_adi'] for x in satirlar(a, 'SELECT kullanici_adi FROM bildirimler WHERE kayit_id=?', kid))
    assert alicilar == ['lider2', 'testadmin']  # ekleyen (lider) kendine bildirim almaz; okucu ve PA lideri almaz
    # Bildirim akışında 'Yeni kanıt' olarak görünür (2.3.1 takım lideri bildirimi).
    akis = istemci('lider2').get('/bildirim.json', headers=XHR).json
    assert any(n.get('kayit_id') == kid and n.get('tur') == 'kanit' for n in akis['bildirimler']), akis
    assert json.loads(satirlar(a, "SELECT yeni FROM denetim WHERE islem='panel_kanit_ekle'")[0]['yeni'])['onayli'] is False
    # Düzenleme yetkili (kt yok) kullanıcı 'onayli=1' gönderse de kayıt onaysız eklenir.
    d = istemci('duzenleyen')
    r = gonder(d, onayli='1', link=GYAZO2)
    assert r.status_code == 200 and r.json['kt'] == 0 and kayit(a, r.json['id'])['kt'] == 0 and r.json['acilabilir'] is True
    assert kayit(a, r.json['id'])['link_turu'] == 'gyazo'
    alicilar = sorted(x['kullanici_adi'] for x in satirlar(a, 'SELECT kullanici_adi FROM bildirimler WHERE kayit_id=?', r.json['id']))
    assert alicilar == ['lider', 'lider2', 'testadmin']
    # Onay bekleyen kayıt sonra normal yoldan onaylanabilir.
    # ONAYSIZ_GORUNUM=gizle: onay yetkisi olmayan ekleyen kendi onaysız kaydını göremez; ayrıntı açılmaz, ileti söyler.
    monkey_ayar = dict(panel.AYAR, ONAYSIZ_GORUNUM='gizle')
    eski_ayar = panel.AYAR
    panel.AYAR = monkey_ayar
    try:
        r = gonder(d, link=GYAZO2)
        assert r.json['acilabilir'] is False and 'Onaylanınca listede görünür' in r.json['mesaj']
        sayfa = d.get('/kayit/yeni').get_data(as_text=True)
        jj = re.search(r'name="jeton" value="([0-9a-f]{32})"', sayfa).group(1)
        r = d.post('/kayit/yeni', data=dict(csrf=csrf(d), jeton=jj, proje='OF', link=GYAZO, personel='GIZLI'))
        assert r.status_code == 302 and 'ac=' not in r.headers['Location']
        assert gonder(k, link=GYAZO2).json['acilabilir'] is True  # onay yetkili ekleyen görür
    finally:
        panel.AYAR = eski_ayar
    j = k.get('/kayit/%d' % kid, headers=XHR).json
    assert j['izin_kt'] and k.post('/kayit/%d/kt' % kid, data=dict(csrf=csrf(k), deger='1', surum=j['surum']), headers=XHR).json['kt'] == 1


def test_cift_gonderim_tek_kayit(web):
    c, a = web
    k = istemci()
    j = jeton(k)
    r1 = gonder(k, jeton_degeri=j)
    r2 = gonder(k, jeton_degeri=j)
    r3 = gonder(k, jeton_degeri=j, personel='BASKA')  # aynı form başka değerle de yeni kayıt açamaz
    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert r1.json['id'] == r2.json['id'] == r3.json['id'] and r2.json['tekrar'] and 'zaten gönderildi' in r2.json['mesaj']
    assert kayit_sayisi(a) == 1 and kayit(a, r1.json['id'])['personel'] == 'AYŞE.K'
    assert len(satirlar(a, "SELECT * FROM denetim WHERE islem='panel_kanit_ekle'")) == 1
    # Yanıttaki yeni jeton bir sonraki kaydı açar.
    r4 = gonder(k, jeton_degeri=r1.json['jeton'])
    assert r4.status_code == 200 and not r4.json.get('tekrar') and kayit_sayisi(a) == 2
    # Başka kullanıcı aynı jetonu kullanamaz (409) ve kayıt açamaz.
    hesap(a, 'lider', 'OF:oku,kt')
    r5 = gonder(istemci('lider'), jeton_degeri=j)
    assert r5.status_code == 409 and kayit_sayisi(a) == 2
    # Doğrulama hatası jetonu tüketmez: düzeltilip aynı jetonla gönderilir.
    j2 = jeton(k)
    assert gonder(k, jeton_degeri=j2, personel='').status_code == 400
    assert gonder(k, jeton_degeri=j2).status_code == 200 and kayit_sayisi(a) == 3
    # Eşzamanlı iki gönderim (aynı jeton): yine tek kayıt.
    j3 = jeton(k)
    sonuclar = []
    def is_():
        sonuclar.append(gonder(k, jeton_degeri=j3).json['id'])
    isler = [threading.Thread(target=is_) for _ in range(4)]
    [t.start() for t in isler]; [t.join() for t in isler]
    assert len(set(sonuclar)) == 1 and kayit_sayisi(a) == 4


# ---------------------------------------------------------------- 4. ekip ne görür

def test_liste_ayrinti_excel_api_rapor_ve_hatirlatma(web):
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt'); hesap(a, 'okucu', 'OF:oku')
    k = istemci('lider')
    kid = gonder(k, onayli=None, personel='SMS.PERSONEL').json['id']
    onayli = gonder(k, personel='SMS.PERSONEL', link=SNAPPARK, onayli='1').json['id']
    for ad in ('lider', 'okucu', 'testadmin'):
        html = istemci(ad).get('/kayitlar?durum=hepsi').get_data(as_text=True)
        satir = html.split('data-id="%d"' % kid, 1)[1].split('</tr>', 1)[0]
        assert '<td class="k-kategori" title="SMS"><span class="kategori-rozet">SMS</span></td>' in satir and 'lider <small class="panel-etiket">(panel)</small>' in satir
        assert '/telegram/kullanici/' not in satir
        d = istemci(ad).get('/kayit/%d' % kid, headers=XHR).json
        assert (d['kaynak'], d['kaynak_metni'], d['giris_tipi_metni'], d['kategori'], d['ekleyen_ad']) == ('panel', 'Panel', 'Panel (bağlantı)', 'SMS', 'lider')
        assert d['dis_link'] == GYAZO and d['link_kaynak'] == 'gyazo'
        assert any(x['islem'] == 'panel_kanit_ekle' for x in d['gecmis'])
    # Kart görünümü de "(panel)" yazar; kategori süzgecinde SMS seçilebilir ve kaydı bulur.
    kart = k.get('/kayitlar?durum=hepsi&gorunum=kart').get_data(as_text=True)
    assert 'lider (panel)' in kart and '<span class="kat kategori-rozet" title="SMS">SMS</span>' in kart
    assert ' · Panel</small>' in k.get('/kayitlar?durum=hepsi&gorunum=galeri').get_data(as_text=True)
    html = k.get('/kayitlar?durum=hepsi&kategori=SMS').get_data(as_text=True)
    assert '<b>2</b> kayıt' in html
    assert 'SMS' in k.get('/kategoriler.json?proje=OF').json['kategoriler']
    # Excel çıktısı: Kaynak 'Panel', Giriş tipi 'Panel (bağlantı)'.
    wb = openpyxl.load_workbook(io.BytesIO(k.get('/disa-aktar.xlsx?durum=hepsi').data))
    ws = wb['Kayıtlar']
    baslik = [x.value for x in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        r = dict(zip(baslik, row))
        assert (r['Kaynak'], r['Giriş tipi'], r['Kategori'], r['Ekleyen'], r['Ekleyen Telegram ID']) == ('Panel', 'Panel (bağlantı)', 'SMS', 'lider', 'panel:lider')
    # API: kaynak 'panel'.
    _, key = anahtar(a, '*', yalniz_onayli=False, sql_izni=True)
    js = c.get('/api/v1/kayitlar?durum=hepsi', headers=B(key)).json
    assert {x['id']: x['kaynak'] for x in js['kayitlar']} == {kid: 'panel', onayli: 'panel'}
    assert all(x['kategori'] == 'SMS' and x['ekleyen_id'] == 'panel:lider' for x in js['kayitlar'])
    sql = c.post('/api/v1/sorgu', json={'sql': "SELECT kaynak,giris_tipi,kategori_code FROM kayitlar WHERE id=%d" % kid}, headers=B(key))
    assert sql.status_code == 200, sql.json
    assert sql.json['sutunlar'] == ['kaynak', 'giris_tipi', 'kategori_code'] and sql.json['satirlar'] == [['panel', 'panel', 'sms']]
    # Personel raporu: diğer kayıtlar gibi sayılır (SMS sütunu).
    rapor = k.get('/rapor/personel?donem=hepsi&durum=hepsi').get_data(as_text=True)
    assert 'SMS.PERSONEL' in rapor and '>SMS<' in rapor
    # 2 saat hatırlatması: onaysız panel kaydı Telegram kaydı gibi aday; ekleyen dahil kt yetkili herkese gider.
    an = datetime.strptime(kayit(a, kid)['tarih'], '%Y-%m-%d %H:%M:%S') + timedelta(hours=2, minutes=1)
    con = db.baglan(a['DB'])
    try:
        rapor = hatirlatma.uret(con, dict(a, HATIRLATMA_GUN=36500), simdi=lambda: an)
    finally:
        con.close()
    assert rapor['saat']['aday'] == 1 and rapor['saat']['hatirlatma'] >= 1
    olaylar = satirlar(a, "SELECT kullanici_adi,olay FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay=?", 'hatirlatma-saat:%d' % kid)
    assert sorted(x['kullanici_adi'] for x in olaylar) == ['lider', 'testadmin']


def test_bot_sayfasi_kayit_raporu_pasif_kategori_ve_anlik(web):
    """İnceleme düzeltmeleri: bot sayfası ve /kayit_raporu panel ekleyenini Telegram ID gibi göstermez; pasif SMS
    kategorisi panel eklemeyi durdurur; soru anlık görüntüsü panel formunun kuralını yansıtır; görünmez karakterler atılır."""
    from app import admin_commands
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt')
    k = istemci('lider')
    r = gonder(k, uye_id=None, personel='\u200bAYŞE.K', aciklama='a\u202eb\u200dc', onayli='1')
    assert r.status_code == 200, r.json
    k_ = kayit(a, r.json['id'])
    assert (k_['personel'], k_['aciklama'], k_['uye_id']) == ('AYŞE.K', 'abc', None)
    sorular = {q['key']: q['required'] for q in json.loads(k_['soru_anlik_json'])['questions']}
    assert sorular == {'personel': True, 'uye_id': False} and json.loads(k_['cevaplar_json']) == {'personel': 'AYŞE.K'}
    # Kataloğun kendisi değişmez (bot akışı Üye ID'yi yine zorunlu sorar).
    assert satirlar(a, "SELECT required FROM kategori_sorular WHERE kategori_code='sms' AND soru_key='uye_id'")[0]['required'] == 1
    # Bot yönetimi sayfası: "En çok kanıt ekleyenler" panel kullanıcısını bağlantısız, "(panel)" ile gösterir.
    html = istemci().get('/bot').get_data(as_text=True)
    bolum = html.split('id="ekleyen-baslik"', 1)[1].split('</section>', 1)[0]
    assert 'lider <small class="panel-etiket">(panel)</small></td><td>—</td>' in bolum
    assert 'panel:lider' not in bolum and '/telegram/kullanici/panel' not in bolum
    # /kayit_raporu: "lider (panel): 1"
    giden = []

    class SahteBot:
        def _is_allowed_admin(self, uid): return True
        def _admin_active(self, oturum): return True
        def _say(self, chat_id, metin): giden.append(metin)
    con = db.baglan(a['DB'])
    try:
        assert admin_commands.process(SahteBot(), con, 1, {'id': 1}, '/kayit_raporu', {})
    finally:
        con.close()
    assert 'lider (panel): 1' in giden[-1] and 'panel:lider' not in giden[-1]
    # Pasif kategori: panel eklemesi Türkçe 400 ile durur, kayıt açılmaz.
    con = db.baglan(a['DB'])
    try:
        with con:
            con.execute("UPDATE kategoriler SET aktif=0 WHERE code='sms'")
    finally:
        con.close()
    once = kayit_sayisi(a)
    r = gonder(k)
    assert r.status_code == 400 and 'pasif' in r.json['hata'] and kayit_sayisi(a) == once


# ---------------------------------------------------------------- 5. katalog geçişi

def test_sms_kategorisi_yeni_veritabani(web):
    c, a = web
    con = db.baglan(a['DB'])
    try:
        kat = katalog.panel_kategori(con)
        assert kat['code'] == 'sms' and kat['label'] == 'SMS' and kat['aktif'] == 1 and kat['mode'] == 'tek_uye'
        aktif = [p['code'] for p in katalog.list_projects(con, active_only=True)]
        for p in aktif:
            assert 'sms' in [x['code'] for x in katalog.list_categories(con, project_code=p)], p
        assert [q['key'] for q in katalog.questions(con, 'sms')] == ['personel', 'uye_id']
        assert con.execute("SELECT 1 FROM schema_migrations WHERE name='panel_kategori_2_3_6:sms'").fetchone()
        # Tekrar çalıştırmak hiçbir şeyi çoğaltmaz.
        sayi = con.execute('SELECT COUNT(*) FROM kategoriler').fetchone()[0]
        katalog.ensure_schema(con); katalog.panel_kategori(con)
        assert con.execute('SELECT COUNT(*) FROM kategoriler').fetchone()[0] == sayi
        # Admin SMS'i bir projeden kaldırır ya da adını değiştirirse geçiş geri almaz; panel yine aynı kategoriye yazar.
        katalog.save_category(con, 'sms', 'SMS kanıt', mode='tek_uye', projects=['OF'], actor='testadmin')
        katalog.ensure_schema(con)
        assert katalog.get_category(con, 'sms')['label'] == 'SMS kanıt' and katalog.get_category(con, 'sms')['projects'] == ['OF']
        assert katalog.panel_kategori(con)['code'] == 'sms'
    finally:
        con.close()
    r = gonder(istemci(), proje='PA')  # SMS PA'ya bağlı değil; panel ekleme yine çalışır
    assert r.status_code == 200 and kayit(a, r.json['id'])['kategori'] == 'SMS kanıt'


def _eski_veritabani(yol, sms_satiri=None):
    """2.3.5 veritabanını canlandırır: SMS kategorisi ve 2.3.6 geçiş kaydı yok (isteğe bağlı elle açılmış 'sms')."""
    con = db.baglan(str(yol))
    with db.transaction(con):
        con.execute("DELETE FROM kategori_sorular WHERE kategori_code='sms'")
        con.execute("DELETE FROM proje_kategorileri WHERE kategori_code='sms'")
        con.execute("DELETE FROM kategoriler WHERE code='sms'")
        con.execute("DELETE FROM schema_migrations WHERE name LIKE 'panel_kategori_%'")
        con.execute("DELETE FROM ayarlar WHERE anahtar LIKE 'panel_kategori_kodu:%'")
        con.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,kaynak) VALUES('tg:1:2:3','OF','HGST','ESKI','telegram')")
        if sms_satiri:
            con.execute("INSERT INTO kategoriler(code,label,mode,aktif,revision) VALUES(?,?,?,?,7)", sms_satiri)
            con.execute("INSERT INTO proje_kategorileri(proje_code,kategori_code,aktif,sort_order) VALUES('HI','sms',1,99)")
    con.close()


def test_sms_kategorisi_eski_veritabani(tmp_path):
    yol = tmp_path / 'eski.db'
    _eski_veritabani(yol)
    ham = sqlite3.connect(str(yol))
    assert ham.execute("SELECT COUNT(*) FROM kategoriler WHERE code='sms'").fetchone()[0] == 0
    ham.close()
    con = db.baglan(str(yol))  # yeni kodla açılış (ilk istek list_projects → ensure_schema)
    try:
        katalog.list_projects(con)
        kat = dict(con.execute("SELECT * FROM kategoriler WHERE code='sms'").fetchone())
        assert (kat['label'], kat['aktif'], kat['mode']) == ('SMS', 1, 'tek_uye')
        bagli = {r[0] for r in con.execute("SELECT proje_code FROM proje_kategorileri WHERE kategori_code='sms' AND aktif=1")}
        assert bagli == {p['code'] for p in katalog.list_projects(con, active_only=True)}
        assert con.execute("SELECT personel FROM kayitlar WHERE anahtar='tg:1:2:3'").fetchone()[0] == 'ESKI'  # eski kayıt yerinde
    finally:
        con.close()


def test_var_olan_sms_degistirilmez(tmp_path):
    yol = tmp_path / 'eski.db'
    _eski_veritabani(yol, sms_satiri=('sms', 'Sms (eski)', 'ark_ana', 0))
    con = db.baglan(str(yol))
    try:
        kat = katalog.panel_kategori(con)
        assert kat['code'] == 'sms' and kat['label'] == 'Sms (eski)'
        satir = dict(con.execute("SELECT * FROM kategoriler WHERE code='sms'").fetchone())
        assert (satir['label'], satir['mode'], satir['aktif'], satir['revision']) == ('Sms (eski)', 'ark_ana', 0, 7)
        assert [r[0] for r in con.execute("SELECT proje_code FROM proje_kategorileri WHERE kategori_code='sms'")] == ['HI']
        assert con.execute("SELECT COUNT(*) FROM kategori_sorular WHERE kategori_code='sms'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kategoriler WHERE label LIKE 'SMS%' COLLATE NOCASE").fetchone()[0] == 1
    finally:
        con.close()


def test_ortam_degiskeni_baska_kategori(web, monkeypatch):
    c, a = web
    monkeypatch.setenv('PANEL_EKLEME_KATEGORI', 'Kısa Mesaj')
    con = db.baglan(a['DB'])
    try:
        kat = katalog.panel_kategori(con)
        assert (kat['code'], kat['label'], kat['aktif']) == ('kisa_mesaj', 'Kısa Mesaj', 1)
        assert con.execute("SELECT COUNT(*) FROM kategoriler WHERE code='sms'").fetchone()[0] == 1  # SMS de yerinde
    finally:
        con.close()
    k = istemci()
    assert 'Kısa Mesaj' in k.get('/kayit/yeni').get_data(as_text=True)
    r = gonder(k)
    assert (kayit(a, r.json['id'])['kategori'], kayit(a, r.json['id'])['kategori_code']) == ('Kısa Mesaj', 'kisa_mesaj')
    # Katalogda zaten olan bir ad verilirse yeni kategori açılmaz, o kullanılır.
    monkeypatch.setenv('PANEL_EKLEME_KATEGORI', 'hgst')
    con = db.baglan(a['DB'])
    try:
        sayi = con.execute('SELECT COUNT(*) FROM kategoriler').fetchone()[0]
        assert katalog.panel_kategori(con)['code'] == 'hgst'
        assert con.execute('SELECT COUNT(*) FROM kategoriler').fetchone()[0] == sayi
    finally:
        con.close()


# ---------------------------------------------------------------- 6. arayüz işaretleri ve belgeler

def test_arayuz_isaretleri_ve_metinler(web):
    c, a = web
    k = istemci()
    html = k.get('/kayitlar').get_data(as_text=True)
    form = html.split('id="ekle-form"', 1)[1].split('</form>', 1)[0]
    for parca in ('name="link"', 'name="gorsel2"', 'name="personel" maxlength="100"', 'name="uye_id"', 'name="ana_uye_id"', 'name="lead_id"',
                  'name="tip"', '<option value="sessiz"', '<option value="telesekreter"', 'name="aciklama"', 'name="onayli" value="1" checked',
                  'Onaylı olarak ekle', 'data-ekle-kategori>SMS<', 'gyazo.com, i.gyazo.com, t.gyazo.com, img.snappark.net, snappark.net, teamzone.gyazo.com'):
        assert parca in form, parca
    assert '<select id="ekle-kategori"' not in form  # kategori seçilmez, sabit rozet
    assert 'role="dialog" aria-modal="true" aria-labelledby="ekle-baslik"' in html
    giris = panel.app.test_client().get('/giris').get_data(as_text=True)
    assert 'Kanıt ekleme Telegram botundan ya da yetkili kullanıcılar için panelden yapılır' in giris
    js = (ROOT / 'app' / 'static' / 'panel.js').read_text(encoding='utf-8')
    assert 'kanitEkle:kanitEkle' in js and "'/kayit/yeni.json'" in js and "k.kaynak==='panel'" in js
    assert '.ekle-form .ekle-izgara' in (ROOT / 'app' / 'static' / 'kayit.css').read_text(encoding='utf-8')
    assert "'panel':'Panel (bağlantı)'" in (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')


def test_belgeler_236():
    degisiklik = (ROOT / 'DEGISIKLIKLER_v2.3.6.md').read_text(encoding='utf-8')
    for parca in ('Kanıt ekle', 'SMS', 'Onaylı olarak ekle', 'PANEL_EKLEME_KATEGORI'):
        assert parca in degisiklik, parca
    assert '2.3.6 ile gelenler' in (ROOT / 'KURULUM_ADIMLARI_v2.3.md').read_text(encoding='utf-8')
    assert 'PANEL_EKLEME_KATEGORI' in (ROOT / '.env.example').read_text(encoding='utf-8')
    assert 'test_panel_kanit_ekle_236.py' in (ROOT / 'TEST_SONUCLARI.md').read_text(encoding='utf-8')
    assert '`panel`' in (ROOT / 'API_KULLANIM.md').read_text(encoding='utf-8')
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'Panelden kanıt ekleme' in readme


# ---------------------------------------------------------------- 7. tarayıcı

@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_kanit_ekleme(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    hesap(a, 'lider', 'OF:oku,kt')
    con = db.baglan(a['DB'])
    with db.transaction(con):
        for i in range(3):
            con.execute("INSERT INTO kayitlar(anahtar,proje,kategori,personel,uye_id,kaynak,giris_tipi,ekleyen_ad,ekleyen_id,tarih) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)", ('tg:t:%d' % i, 'OF', 'HGST', 'TG.%d' % i, '10%d' % i, 'telegram', 'resim', 'tgkisi', '555%d' % i, db.simdi()))
    con.close()
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
    satir = satirlar(a, "SELECT * FROM kayitlar WHERE kaynak='panel' ORDER BY id")
    assert [x['personel'] for x in satir] == ['TARAYICI.MASAUSTU', 'TARAYICI.TELEFON', 'ANA.SAYFA']
    assert all(x['kategori'] == 'SMS' for x in satir) and satir[0]['kt'] == 1 and satir[1]['kt'] == 0
