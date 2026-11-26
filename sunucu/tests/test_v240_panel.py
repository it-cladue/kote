# -*- coding: utf-8 -*-
"""2.4.0 (A ekibi) — Kayıtlar paneli: bildirim gürültüsü (A1), gün sonu alıcıları (A2), onay bekleyen görünümü (A3),
onaylayıp sonrakine geçme (A4), dönemler ve Excel çıktısı (A5), küçük arayüz işleri (A6).
Tarayıcı senaryosu tests/v240_panel_tarayici.js (Node + Playwright yoksa tarayıcı testleri atlanır)."""
import io
import json
import os
import subprocess
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import openpyxl
import pytest

from app import db, discussion, hatirlatma, panel, personel_ozeti
from test_web import web, seed, login, csrf  # noqa: F401  (ortak fixture/yardımcılar)
from test_bildirim_231 import account, insert, rows, logout
from test_bildirim_popup_233 import _Yardimci, _playwright_var
from test_hatirlatma_233 import uret as gs_uret, gun_sonu_satirlari, IST

ROOT = Path(__file__).resolve().parents[1]
TARAYICI_BETIK = Path(__file__).with_name('v240_panel_tarayici.js')
EKRAN_KLASOR = '/tmp/claude-0/p240a'
XHR = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}


def ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def once(**kw):
    return ts(datetime.now() - timedelta(**kw))


def kt(c, kid, deger='1'):
    r = c.post('/kayit/%d/kt' % kid, data={'csrf': csrf(c), 'deger': deger})
    assert r.status_code == 200, r.data[:300]
    return r.json


# =============================================================== A1 — bildirim gürültüsü
def _bildirim_ortami(a, kid):
    """Kayda bağlı: 'Yeni kanıt' (bildirimler), kayıt hatırlatması, liste özeti (gün sonu), soru satırı."""
    con = db.baglan(a['DB'])
    with db.transaction(con):
        db.bildirim_uret(con, kid)
        for ad in ('lider', 'lider2', 'testadmin'):
            hatirlatma._ekle(con, ad, kid, 'OF', 'hatirlatma:%d:%s' % (kid, date.today().isoformat()), 'Bu ID bekliyor.')
            hatirlatma._ekle(con, ad, kid, 'OF', 'gun-sonu:%s:%d' % (date.today().isoformat(), kid), 'Gün sonu özeti')
    con.close()
    con = db.baglan(a['DB'])
    try:
        discussion.add(con, kid, 'lider2', 'Bu kanıt doğru mu?', 'lider')
    finally:
        con.close()


def _okunmamis(a, kid):
    kanit = rows(a, 'SELECT kullanici_adi FROM bildirimler WHERE kayit_id=? AND okundu=0', kid)
    mesaj = rows(a, 'SELECT tur,olay,kullanici_adi FROM mesaj_bildirimleri WHERE kayit_id=? AND okundu=0', kid)
    return dict(kanit=len(kanit), hatirlatma=sum(1 for m in mesaj if m['olay'].startswith('hatirlatma:')),
                ozet=sum(1 for m in mesaj if m['olay'].startswith('gun-sonu:')), soru=sum(1 for m in mesaj if m['tur'] == 'soru'))


@pytest.mark.parametrize('eylem', ['onayla', 'onay_kaldir', 'sil', 'geri_al'])
def test_a1_kayit_bildirimleri_herkes_icin_okundu(web, eylem):
    c, a = web
    account(a, 'lider', 'OF:oku,kt'); account(a, 'lider2', 'OF:oku,kt,sil')
    kid = insert(a, personel='A1', kt=1 if eylem == 'onay_kaldir' else 0, silindi=1 if eylem == 'geri_al' else 0)
    _bildirim_ortami(a, kid)
    once_ = _okunmamis(a, kid)
    assert once_ == dict(kanit=3, hatirlatma=3, ozet=3, soru=1), once_
    login(c, 'lider2')
    if eylem == 'onayla':
        kt(c, kid, '1')
    elif eylem == 'onay_kaldir':
        kt(c, kid, '0')
    elif eylem == 'sil':
        assert c.post('/kayit/%d/sil' % kid, data={'csrf': csrf(c), 'sebep': 'yanlış'}).json['ok']
    else:
        assert c.post('/kayit/%d/geri-al' % kid, data={'csrf': csrf(c)}).json['ok']
    sonra = _okunmamis(a, kid)
    # 'Yeni kanıt' ve kayıt hatırlatması herkes için okundu; liste özeti ve soru satırı dokunulmadan kalır.
    assert sonra == dict(kanit=0, hatirlatma=0, ozet=3, soru=1), (eylem, sonra)


def test_a1_toplu_onay_da_okundu_yapar_ve_zil_sayaci_duser(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt')
    ids = [insert(a, personel='T%d' % i) for i in range(3)]
    con = db.baglan(a['DB'])
    with db.transaction(con):
        for kid in ids:
            db.bildirim_uret(con, kid)
    con.close()
    login(c, 'lider')
    assert c.get('/bildirim.json').json['okunmamis'] == 3
    logout(c); login(c)
    r = c.post('/kayitlar/toplu-kt', data={'csrf': csrf(c), 'ids': ids, 'deger': '1'})
    assert r.json['degisen'] == 3
    logout(c); login(c, 'lider')
    assert c.get('/bildirim.json').json['okunmamis'] == 0


def test_a1_bildirim_onay_ayari(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt'); account(a, 'lider2', 'OF:oku,kt')
    assert hatirlatma.ayarlar(dict(a))['bildirim_onay'] is False                      # varsayılan 0
    assert hatirlatma.ayarlar(dict(a, BILDIRIM_ONAY='1'))['bildirim_onay'] is True
    assert hatirlatma.ayarlar(dict(a, BILDIRIM_ONAY='hayır'))['bildirim_onay'] is False
    k1 = insert(a, personel='O1'); k2 = insert(a, personel='O2')
    login(c, 'lider')
    kt(c, k1); kt(c, k1, '0')
    assert rows(a, "SELECT * FROM mesaj_bildirimleri WHERE tur IN ('onay','onay_kaldir')") == []
    assert [r['islem'] for r in rows(a, "SELECT islem FROM denetim WHERE islem IN ('onayla','onay_kaldir') ORDER BY id")] == ['onayla', 'onay_kaldir']
    a['BILDIRIM_ONAY'] = '1'
    kt(c, k2)
    alanlar = rows(a, "SELECT kullanici_adi,tur FROM mesaj_bildirimleri WHERE tur='onay' AND kayit_id=?", k2)
    assert sorted(x['kullanici_adi'] for x in alanlar) == ['lider2', 'testadmin']


# =============================================================== A2 — gün sonu alıcıları
def test_a2_gun_sonu_varsayilan_alicilar_kendi_onay_projeleri(web):
    c, a = web
    account(a, 'oflider', 'OF:oku,kt;PA:oku'); account(a, 'okucu', 'OF:oku;PA:oku'); account(a, 'palider', 'PA:oku,kt')
    bas = datetime(2026, 11, 26)
    for _ in range(3):
        insert(a, ilk_gorulme=ts(bas - timedelta(days=1)), tarih=ts(bas - timedelta(days=1)))
    for _ in range(2):
        insert(a, proje='PA', ilk_gorulme=ts(bas - timedelta(days=1)), tarih=ts(bas - timedelta(days=1)))
    r = gs_uret(a, datetime(2026, 11, 26, 18, 1))
    assert r['gun_sonu']['bildirim'] == 3
    satir = {x['kullanici_adi']: x for x in gun_sonu_satirlari(a)}
    assert sorted(satir) == ['oflider', 'palider', 'testadmin']                        # okuyucu almaz
    assert '5 kayıt onaylanmadı (OF 3, PA 2)' in satir['testadmin']['metin']           # yönetici: tüm projeler
    assert '3 kayıt onaylanmadı (OF 3)' in satir['oflider']['metin'] and satir['oflider']['proje'] == 'OF'
    assert '2 kayıt onaylanmadı (PA 2)' in satir['palider']['metin'] and satir['palider']['proje'] == 'PA'
    # Günde bir satır: ikinci çalıştırma yeni satır üretmez.
    assert gs_uret(a, datetime(2026, 11, 26, 19, 0))['gun_sonu']['bildirim'] == 0 and len(gun_sonu_satirlari(a)) == 3


def test_a2_gun_sonu_alicilar_ayari_yine_onceliklidir(web):
    c, a = web
    account(a, 'oflider', 'OF:oku,kt'); account(a, 'okucu', 'OF:oku;PA:oku')
    bas = datetime(2026, 11, 26)
    insert(a, ilk_gorulme=ts(bas - timedelta(days=1)), tarih=ts(bas - timedelta(days=1)))
    insert(a, proje='PA', ilk_gorulme=ts(bas - timedelta(days=1)), tarih=ts(bas - timedelta(days=1)))
    r = gs_uret(a, datetime(2026, 11, 26, 18, 1), ayar={'GUN_SONU_ALICILAR': 'okucu'})
    satir = gun_sonu_satirlari(a)
    assert r['gun_sonu']['bildirim'] == 1 and [x['kullanici_adi'] for x in satir] == ['okucu']
    assert '2 kayıt onaylanmadı' in satir[0]['metin']                                    # listedeki ad görebildiği projeleri alır


# =============================================================== A3 — onay bekleyen görünümü
def _karma_ortam(a):
    account(a, 'karma', 'OF:oku,kt;PA:oku'); account(a, 'ofci', 'OF:oku,kt'); account(a, 'okucu', 'OF:oku;PA:oku')
    of = [insert(a, personel='OF%d' % i, ilk_gorulme=once(hours=10 - i), tarih=once(hours=10 - i)) for i in range(3)]
    pa = [insert(a, proje='PA', personel='PA%d' % i, ilk_gorulme=once(hours=5), tarih=once(hours=5)) for i in range(2)]
    insert(a, personel='ONAYLI', kt=1)
    return of, pa


def _sayac(html, ad):
    import re
    m = re.search(r'id="sayac-%s">(\d+)<' % ad, html)
    return int(m.group(1)) if m else None


def test_a3_sayilar_admin_kt_karma_ve_yalniz_okuyan(web):
    c, a = web; of, pa = _karma_ortam(a)
    beklenen = {'testadmin': (5, None, 5), 'ofci': (3, None, 3), 'karma': (3, 2, 3), 'okucu': (5, None, 5)}
    for ad, (sekme, not_, kpi) in beklenen.items():
        login(c, ad)
        html = c.get('/kayitlar?durum=bekleyen').get_data(as_text=True)
        assert _sayac(html, 'bekleyen') == sekme, ad
        assert html.count('class="kayit ') == sekme, ad                                    # liste sayıyla birebir
        if not_:
            assert '+%d görüntüleyebildiğiniz projelerde' % not_ in html and 'id="bekleyen-disi-not"' in html, ad
        else:
            assert 'id="bekleyen-disi-not"' not in html, ad
        ana = c.get('/').get_data(as_text=True)
        assert 'data-kpi="bekleyen">%d<' % kpi in ana, ad
        assert ('+%d görüntüleyebildiğiniz projelerde' % not_ in ana) if not_ else ('id="kpi-bekleyen-oku"' not in ana), ad
        logout(c)
    # Karma kullanıcı PA'yı açıkça seçerse PA bekleyenleri listelenir (not yok).
    login(c, 'karma')
    html = c.get('/kayitlar?durum=bekleyen&proje=PA').get_data(as_text=True)
    assert _sayac(html, 'bekleyen') == 2 and 'id="bekleyen-disi-not"' not in html
    # Not bağlantısı PA bekleyenlerine gider.
    html = c.get('/kayitlar?durum=bekleyen').get_data(as_text=True)
    import re
    parca = re.search(r'<a class="bekleyen-disi-not[^>]*>', html).group(0)
    assert 'proje=PA' in parca and 'durum=bekleyen' in parca


def test_a3_sira_varsayilan_eski_ve_parametre(web):
    c, a = web
    yeni = insert(a, personel='YENI', tarih=once(minutes=5))
    eski = insert(a, personel='ESKI', tarih=once(days=4))
    orta = insert(a, personel='ORTA', ilk_gorulme=once(days=2), tarih=once(minutes=1))   # başlangıç ilk_gorulme'den
    onayli_eski = insert(a, personel='OE', kt=1, tarih=once(days=9))
    login(c)

    def sira(url):
        import re
        return [int(x) for x in re.findall(r'class="kayit [^"]*" data-id="(\d+)"', c.get(url).get_data(as_text=True))]
    assert sira('/kayitlar?durum=bekleyen') == [eski, orta, yeni]                            # en uzun bekleyen önce
    assert sira('/kayitlar?durum=bekleyen&sirala=yeni') == [orta, yeni, eski]               # tarih alanına göre en yeni önce
    assert sira('/kayitlar?durum=hepsi')[0] == orta and sira('/kayitlar?durum=hepsi')[-1] == onayli_eski
    assert sira('/kayitlar?durum=hepsi&sirala=eski')[0] == onayli_eski
    html = c.get('/kayitlar?durum=bekleyen&sirala=yeni').get_data(as_text=True)
    assert 'name="sirala" value="yeni"' in html                                             # süzgeç gönderiminde korunur
    assert 'href="/kayitlar?durum=onayli' in html and 'sirala=yeni' not in html.split('class="sekmeler"')[1].split('</div>')[0]  # sekme değişince varsayılana döner
    # Bildirim / özet bağlantıları bekleyen listesini açar; varsayılan sıra en eski önce.
    with panel.app.test_request_context():
        assert panel._bildirim_hedef({'olay': 'gun-sonu:2026-11-26'}) == '/kayitlar?durum=bekleyen'
        assert panel._siralama({}, 'bekleyen') == 'eski' and panel._siralama({}, 'hepsi') == 'yeni'


def test_a3_bekleme_etiketleri_ve_esikler(web):
    c, a = web
    assert [panel.bekleme_etiketi(s) for s in (0, 59, 45 * 60, 3599, 3600, 5 * 3600 + 59, 86399, 86400, 3 * 86400 + 5)] == \
        ['1 dk', '1 dk', '45 dk', '59 dk', '1 sa', '5 sa', '23 sa', '1 gün', '3 gün']
    an = datetime(2026, 11, 26, 12, 0, 0)
    with panel.app.test_request_context():
        def b(**kw):
            d = dict(kt=0, silindi=0, ilk_gorulme=None, tarih=None, guncelleme=None); d.update(kw)
            return panel.bekleme_bilgisi(d, an)
        assert b(tarih=ts(an - timedelta(minutes=45))) ['etiket'] == '45 dk' and b(tarih=ts(an - timedelta(minutes=45)))['seviye'] == 'normal'
        assert b(tarih=ts(an - timedelta(hours=2)))['seviye'] == 'turuncu'                     # BEKLEME_UYARI_SAAT=2
        assert b(tarih=ts(an - timedelta(hours=5)))['etiket'] == '5 sa'
        assert b(tarih=ts(an - timedelta(days=3)))['seviye'] == 'kirmizi' and b(tarih=ts(an - timedelta(days=3)))['etiket'] == '3 gün'
        assert b(tarih=ts(an - timedelta(days=2, hours=23)))['seviye'] == 'turuncu'
        # Başlangıç hatırlatmalarla aynı: ilk_gorulme > tarih > guncelleme.
        assert b(ilk_gorulme=ts(an - timedelta(days=4)), tarih=ts(an - timedelta(minutes=3)))['etiket'] == '4 gün'
        assert b(guncelleme=ts(an - timedelta(hours=1)))['etiket'] == '1 sa'
        assert b(tarih='2026-11-25')['etiket'] == '1 gün'                                       # saatsiz eski Excel tarihi
        assert b(tarih='bozuk') is None and b() is None
        assert panel.bekleme_bilgisi(dict(kt=1, silindi=0, tarih=ts(an)), an) is None
        assert panel.bekleme_bilgisi(dict(kt=0, silindi=1, tarih=ts(an)), an) is None
    with panel.app.test_request_context():
        a['BEKLEME_UYARI_SAAT'] = 6; a['HATIRLATMA_GUN'] = 1
        d = dict(kt=0, silindi=0, tarih=ts(an - timedelta(hours=5)))
        assert panel.bekleme_bilgisi(d, an)['seviye'] == 'normal'
        assert panel.bekleme_bilgisi(dict(d, tarih=ts(an - timedelta(hours=7))), an)['seviye'] == 'turuncu'
        assert panel.bekleme_bilgisi(dict(d, tarih=ts(an - timedelta(hours=25))), an)['seviye'] == 'kirmizi'


def test_a3_bekleme_rozeti_listede_ve_ayrintida(web):
    c, a = web
    k1 = insert(a, personel='K1', tarih=once(days=4)); k2 = insert(a, personel='K2', tarih=once(hours=3))
    k3 = insert(a, personel='K3', tarih=once(minutes=20)); k4 = insert(a, personel='K4', tarih=once(days=5), kt=1)
    login(c)
    for gorunum in ('tablo', 'kart', 'galeri'):
        html = c.get('/kayitlar?durum=hepsi&gorunum=' + gorunum).get_data(as_text=True)
        assert html.count('class="bekleme-rozet kirmizi"') == 1 and html.count('class="bekleme-rozet turuncu"') == 1, gorunum
        assert html.count('class="bekleme-rozet normal"') == 1 and '>4 gün</span>' in html and '>3 sa</span>' in html, gorunum
    d = c.get('/kayit/%d' % k2, headers=XHR).json
    assert d['bekleme']['etiket'] == '3 sa' and d['bekleme']['seviye'] == 'turuncu'
    assert c.get('/kayit/%d' % k4, headers=XHR).json['bekleme'] is None
    assert 'id="m-bekleme"' in c.get('/kayitlar').get_data(as_text=True)


# =============================================================== A5 — dönemler ve çıktı
def test_a5_personel_donemleri_gecen_hafta_ve_gecen_ay(web):
    bugun = date(2026, 11, 25)                                  # çarşamba
    assert personel_ozeti.donem_araligi('gecen_hafta', bugun) == (date(2026, 11, 16), date(2026, 11, 22))
    assert personel_ozeti.donem_araligi('gecen_ay', bugun) == (date(2026, 10, 1), date(2026, 10, 31))
    assert personel_ozeti.donem_araligi('gecen_ay', date(2026, 3, 1)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert personel_ozeti.donem_araligi('gecen_hafta', date(2026, 11, 23)) == (date(2026, 11, 16), date(2026, 11, 22))  # pazartesi
    f, hatalar, _ = personel_ozeti.filtre_coz({'donem': 'gecen_hafta'}, ['OF'], bugun=bugun)
    assert not hatalar and (f['tarih1'], f['tarih2']) == ('2026-11-16', '2026-11-22')
    assert personel_ozeti.onceki_aralik(f, bugun) == (date(2026, 11, 9), date(2026, 11, 15))
    f, hatalar, _ = personel_ozeti.filtre_coz({'donem': 'gecen_ay'}, ['OF'], bugun=bugun)
    assert not hatalar and personel_ozeti.onceki_aralik(f, bugun) == (date(2026, 9, 1), date(2026, 9, 30))  # önceki takvim ayı
    assert personel_ozeti.donem_etiketi(f) == 'Geçen ay (01.10.2026 – 31.10.2026)'
    c, a = web; login(c)
    html = c.get('/rapor/personel?donem=gecen_hafta').get_data(as_text=True)
    assert 'value="gecen_hafta" data-po-degisim checked' in html and 'value="gecen_ay"' in html and 'Geçen hafta' in html
    assert c.get('/rapor/personel.xlsx?donem=gecen_ay').status_code == 200
    assert 'value="gecen_ay"' in c.get('/').get_data(as_text=True)                              # ana sayfa kartı da


def test_a5_hizli_donem_dugmeleri_ve_tarih_olcutu_alanlari(web):
    c, a = web; login(c)
    for url in ('/kayitlar', '/disa-aktar'):
        html = c.get(url).get_data(as_text=True)
        for kod, ad in panel.HIZLI_DONEMLER:
            assert 'data-donem="%s">%s</button>' % (kod, ad) in html, (url, kod)
        assert 'name="tarih_alani"' in html and 'Onay zamanı' in html, url


def test_a5_tarih_olcutu_onay_zamani_suzer(web):
    c, a = web
    eklendi_once_onay_simdi = insert(a, personel='EO', tarih='2026-10-05 10:00:00', kt=1, kt_zaman='2026-11-18 09:00:00')
    eklendi_simdi = insert(a, personel='ES', tarih='2026-11-18 10:00:00', kt=1, kt_zaman='2026-11-30 09:00:00')
    bekleyen = insert(a, personel='BK', tarih='2026-11-18 11:00:00', kt=0, kt_zaman='2026-11-18 12:00:00')  # onayı kaldırılmış
    login(c)

    def ids(url):
        import re
        return {int(x) for x in re.findall(r'data-id="(\d+)"', c.get(url).get_data(as_text=True).split('id="modal"')[0])}
    q = 'durum=hepsi&tarih1=2026-11-17&tarih2=2026-11-23'
    assert ids('/kayitlar?' + q) == {eklendi_simdi, bekleyen}
    assert ids('/kayitlar?' + q + '&tarih_alani=onay') == {eklendi_once_onay_simdi}
    r = c.get('/disa-aktar.xlsx?' + q + '&tarih_alani=onay')
    ws = openpyxl.load_workbook(io.BytesIO(r.data))['Kayıtlar']
    assert [row[0] for row in ws.iter_rows(min_row=2, values_only=True)] == [eklendi_once_onay_simdi]
    assert 'kanit-kayitlari-hepsi-onay-2026-11-17_2026-11-23.xlsx' in r.headers['Content-Disposition']


def test_a5_excel_dosya_adi_bilgi_sayfasi_ve_tarih_hucreleri(web):
    c, a = web
    k1 = insert(a, personel='X1', tarih='2026-11-18 10:15:00', kt=1, kt_kim='testadmin', kt_zaman='2026-11-19 08:30:00')
    k2 = insert(a, personel='X2', tarih='2026-11-20', kt=1, kt_zaman='2026-11-20 09:00:00')
    insert(a, personel='X3', tarih='2026-11-21 12:00:00', silindi=1, silme_zamani='2026-11-22 13:45:10', kt=1)
    login(c)
    r = c.get('/disa-aktar.xlsx?proje=OF&durum=onayli&tarih1=2026-11-17&tarih2=2026-11-23&q=X')
    assert r.status_code == 200
    assert r.headers['Content-Disposition'].endswith('kanit-kayitlari-OF-onayli-2026-11-17_2026-11-23.xlsx')
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ['Bilgi', 'Kayıtlar', 'Proje özeti'] and wb.active.title == 'Kayıtlar'
    bilgi = {row[0]: row[1] for row in wb['Bilgi'].iter_rows(values_only=True)}
    assert bilgi['Proje'] == 'OF' and bilgi['Durum'] == 'Onaylı' and bilgi['Tarih ölçütü'] == 'Eklenme tarihi'
    assert bilgi['Tarih aralığı'] == '17.11.2026 – 23.11.2026' and bilgi['Arama'] == 'X' and bilgi['Kayıt sayısı'] == 2
    assert bilgi['Oluşturan'] == 'testadmin' and len(bilgi['Oluşturma zamanı']) == 16
    ws = wb['Kayıtlar']; hdr = [x.value for x in ws[1]]
    satirlar = {row[0].value: row for row in ws.iter_rows(min_row=2)}
    t = satirlar[k1][hdr.index('Tarih')]; o = satirlar[k1][hdr.index('Onay zamanı')]
    assert t.is_date and t.value == datetime(2026, 11, 18, 10, 15) and t.number_format == 'dd.mm.yyyy hh:mm'
    assert o.is_date and o.value == datetime(2026, 11, 19, 8, 30)
    t2 = satirlar[k2][hdr.index('Tarih')]
    assert t2.is_date and t2.value == datetime(2026, 11, 20) and t2.number_format == 'dd.mm.yyyy'   # saatsiz: yalnız tarih
    # Silinenler: Silme zamanı da gerçek tarih; boş zaman hücresi boş kalır.
    r = c.get('/disa-aktar.xlsx?durum=silinen')
    assert r.headers['Content-Disposition'].endswith('kanit-kayitlari-silinen.xlsx')
    ws = openpyxl.load_workbook(io.BytesIO(r.data))['Kayıtlar']; hdr = [x.value for x in ws[1]]
    s = list(ws.iter_rows(min_row=2))[0][hdr.index('Silme zamanı')]
    assert s.is_date and s.value == datetime(2026, 11, 22, 13, 45, 10)
    # Tarihsiz seçimi ve çok proje dosya adına yazılır.
    assert 'kanit-kayitlari-OF+PA-hepsi-tarihsiz.xlsx' in c.get('/disa-aktar.xlsx?proje=OF&proje=PA&tarihsiz=1&durum=hepsi').headers['Content-Disposition']
    with panel.app.test_request_context():
        assert panel.cikti_dosya_adi(dict(proje=['OF', 'PA', 'HI', 'VI', 'GA', 'PP'], durum='bekleyen')) == 'kanit-kayitlari-OF+PA+HI+VI+2-proje-bekleyen.xlsx'
        assert panel.cikti_dosya_adi(dict(proje=[], durum='hepsi', tarih1='2026-11-01')) == 'kanit-kayitlari-hepsi-2026-11-01_bugun.xlsx'


def test_a5_cikti_sayfasi_bekleyenleri_tum_goruntulenen_projelerden_alir(web):
    """Düzeltme: onay projesiyle sınırlama yalnız Kayıtlar'daki "Excel (bu görünüm)" bağlantısında (kapsam=kayitlar);
    Çıktı sayfası (aynı uç nokta) karma kullanıcıya PA bekleyenlerini de verir."""
    c, a = web; of, pa = _karma_ortam(a)
    login(c, 'karma')
    def projeler_(url):
        r = c.get(url); assert r.status_code == 200, r.data[:300]
        wb = openpyxl.load_workbook(io.BytesIO(r.data))
        hdr = [x.value for x in wb['Kayıtlar'][1]]
        return sorted(row[hdr.index('Proje')] for row in wb['Kayıtlar'].iter_rows(min_row=2, values_only=True)), \
            {row[0]: row[1] for row in wb['Bilgi'].iter_rows(values_only=True)}, wb, r
    # Çıktı sayfası: 3 OF + 2 PA, sayım da 5; dosya adı kt yetkisiz projedeki onaysızları uyarır (uyar modu).
    p_, bilgi, wb, r = projeler_('/disa-aktar.xlsx?durum=bekleyen')
    assert p_ == ['OF'] * 3 + ['PA'] * 2 and 'PA hariç' not in (bilgi.get('Not') or '') and 'PA' in bilgi['Proje']
    assert c.get('/disa-aktar.xlsx?durum=bekleyen&sayim=1').json['adet'] == 5
    assert 'ONAYSIZ' in r.headers['Content-Disposition']
    assert wb['Bilgi'].column_dimensions['B'].width == 70                                # write_only: genişlik uygulanır
    # Kayıtlar "Excel (bu görünüm)": bağlantı kapsam=kayitlar taşır; dosya sekmeyle aynı 3 OF kaydı.
    html = c.get('/kayitlar?durum=bekleyen').get_data(as_text=True)
    import re, html as html_
    href = html_.unescape(re.search(r'href="([^"]*disa-aktar\.xlsx[^"]*)"', html).group(1))
    assert 'kapsam=kayitlar' in href and 'durum=bekleyen' in href
    p_, bilgi, _, _ = projeler_(href)
    assert p_ == ['OF'] * 3 and 'PA hariç' in bilgi['Not'] and bilgi['Proje'] == 'Tüm yetkili projeler (OF)'


def test_a5_excel_formul_ve_bozuk_tarih_metin_kalir(web):
    c, a = web
    insert(a, personel='=1+1', tarih='eski-tarih', kt=1)
    login(c)
    ws = openpyxl.load_workbook(io.BytesIO(c.get('/disa-aktar.xlsx?durum=hepsi').data))['Kayıtlar']; hdr = [x.value for x in ws[1]]
    row = list(ws.iter_rows(min_row=2, values_only=True))[0]
    assert row[hdr.index('Tarih')] == 'eski-tarih' and row[hdr.index('Personel')] == "'=1+1"


# =============================================================== A6 — küçük arayüz işleri
def test_a6_gyazo_bilgisi_yalniz_evet_hayir_ve_suzgec_dugmesi(web, monkeypatch):
    c, a = web; login(c)
    kid = seed(a)
    monkeypatch.delenv('GYAZO_TOKEN', raising=False)
    html = c.get('/kayitlar?durum=hepsi&q=00123&kategori=HGST').get_data(as_text=True)
    assert 'data-gyazo-hazir="0"' in html and c.get('/kayit/%d' % kid, headers=XHR).json['gyazo_hazir'] is False
    assert 'id="suzgec-ac"' in html and 'Süzgeçler (2 etkin)' in html and 'kp.kayitSuzgecAcik' in html
    monkeypatch.setenv('GYAZO_TOKEN', 'gizli-deger-123')
    html = c.get('/kayitlar').get_data(as_text=True)
    assert 'data-gyazo-hazir="1"' in html and 'gizli-deger-123' not in html
    d = c.get('/kayit/%d' % kid, headers=XHR)
    assert d.json['gyazo_hazir'] is True and b'gizli-deger-123' not in d.data
    assert 'Süzgeçler</button>' in c.get('/kayitlar').get_data(as_text=True)                   # etkin süzgeç yoksa sayı yok


def test_a6_js_sozdizimi_ve_kisayol_ipucu(web):
    import shutil
    if shutil.which('node'):
        r = subprocess.run(['node', '--check', str(ROOT / 'app' / 'static' / 'panel.js')], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    c, a = web; login(c)
    html = c.get('/kayitlar').get_data(as_text=True)
    assert 'O onayla ve sonraki · U geri al · S soru · D düzenle · Del sil · ? kısayollar' in html and 'id="m-kisayollar"' in html
    assert '<kbd>U</kbd> son onayı geri al' in html


# =============================================================== Tarayıcı (A1 ses, A3, A4, A5, A6)
class _SesYardimci(_Yardimci):
    """Popup yardımcısına onay ve soru bildirimi ekleyen sürüm (testadmin için)."""

    def islem(self, ad, veri):
        if ad in ('onay', 'soru'):
            con = db.baglan(self.ayar['DB'])
            try:
                with db.transaction(con):
                    self.sira += 1
                    kid = con.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih,guncelleme) VALUES(?,?,?,?,?,?)",
                                      ('ses:%d' % self.sira, 'OF', 'S%d' % self.sira, 'telegram', db.simdi(), db.simdi())).lastrowid
                    con.execute('INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                                ('testadmin', kid, 'OF', '%s:%d' % (ad, self.sira), ad, 'lider', 'Kanıt onaylandı.' if ad == 'onay' else 'Soru?', db.simdi()))
                    db.degisti(con)
                return {'kayit_id': kid}
            finally:
                con.close()
        return super().islem(ad, veri)


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_v240_kayitlar_ve_ses(web, tmp_path, monkeypatch):
    from waitress.server import create_server
    c, a = web
    monkeypatch.delenv('GYAZO_TOKEN', raising=False)
    account(a, 'lider', 'OF:oku,kt,duzenle,sil;PA:oku')
    ids = dict(
        a=seed(a, key='v240:a'), b=seed(a, key='v240:b'), c=seed(a, key='v240:c'), d=seed(a, key='v240:d'))
    con = db.baglan(a['DB'])
    with db.transaction(con):
        for ad, yas in (('a', timedelta(days=4)), ('b', timedelta(hours=5)), ('c', timedelta(minutes=30)), ('d', timedelta(minutes=10))):
            con.execute('UPDATE kayitlar SET tarih=?,personel=? WHERE id=?', (ts(datetime.now() - yas), 'P-' + ad.upper(), ids[ad]))
        db.degisti(con)
    con.close()
    insert(a, proje='PA', personel='PA-OKU', tarih=once(hours=1))
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    yardimci = _SesYardimci(a)
    try:
        ekran = os.environ.get('KP_EKRAN_KLASOR', EKRAN_KLASOR)
        Path(ekran).mkdir(parents=True, exist_ok=True)
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, YARDIMCI_URL=yardimci.url, EKRAN_KLASOR=ekran,
                     KAYITLAR=json.dumps(ids))
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=400, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-4000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-5000:]
    finally:
        yardimci.kapat()
        try:
            sunucu.close()
        except Exception:
            pass
    # Onayla ve sonraki + Geri al denetime yazıldı: a önce onaylandı, geri alındı, sonra yeniden onaylandı.
    denetim = [x['islem'] for x in rows(a, "SELECT d.islem FROM denetim d JOIN kayitlar k ON k.anahtar=d.anahtar WHERE k.id=? AND d.islem IN ('onayla','onay_kaldir') ORDER BY d.id", ids['a'])]
    assert denetim == ['onayla', 'onay_kaldir', 'onayla'], denetim
    son = {x['id']: x for x in rows(a, 'SELECT id,kt,silindi,personel FROM kayitlar')}
    assert all(son[ids[k]]['kt'] == 1 for k in 'abcd') and all(son[ids[k]]['silindi'] == 0 for k in 'abcd')
