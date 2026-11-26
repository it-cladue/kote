# -*- coding: utf-8 -*-
"""2.3.8 — "Bekleyen özeti": İstanbul saatiyle pencere içinde (varsayılan 08:00-20:00) 2 saatte bir, onay yetkisi olan her
kullanıcıya tek satır "Onay bekleyen N kayıt var …". Yeni özet gelince öncekiler okundu sayılır; bekleyen yoksa satır yok.
Kayıt başına 2 saat bildirimi (HATIRLATMA_SAAT) varsayılan kapalı.

Saat enjekte edilir (test_hatirlatma_233.py ile aynı kalıp): uret(simdi=..., yerel_tz=..., tz=IST).
3 gün kuralı, kayıt başına 2 saat bildirimi ve gün sonu özeti bu dosyada kapalıdır; yalnız yeni adım sınanır.
Sondaki tarayıcı testi Node + Playwright yoksa atlanır.
"""
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest

from app import db, hatirlatma, kullanicilar, panel
from test_web import web, login, csrf  # noqa: F401  (ortak fixture/yardımcılar)
from test_bildirim_231 import account, insert, rows

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
TARAYICI_BETIK = Path(__file__).with_name('bekleyen_ozet_tarayici.js')
IST = ZoneInfo('Europe/Istanbul')
UTC = timezone.utc
SIMDI = datetime(2026, 11, 26, 10, 0, 0)  # İstanbul sunucusu: 10:00 (08:00'dan sonraki ikinci dilim)


def ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def uret(a, an, yerel_tz=IST, **kw):
    ayar = dict(a, HATIRLATMA_GUN=36500, HATIRLATMA_SAAT=0, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=2,
                BEKLEYEN_OZET_PENCERE='08:00-20:00', BEKLEYEN_OZET_YONETICI='1')
    ayar.update(kw.pop('ayar', {}))
    c = db.baglan(a['DB'])
    try:
        return hatirlatma.uret(c, ayar, simdi=lambda: an, yerel_tz=yerel_tz, tz=IST, **kw)
    finally:
        c.close()


def ozetler(a, ad=None):
    sql = "SELECT * FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'bekleyen-ozet:%'" + (' AND kullanici_adi=?' if ad else '')
    return rows(a, sql + ' ORDER BY kullanici_adi,id', *([ad] if ad else []))


def dk(saat, dakika=0):
    return saat * 60 + dakika


def ist(saat, dakika=0):
    return datetime(2026, 11, 26, saat, dakika)


# =============================================================== Dilim hesabı
def test_dilimler_cesitli_aralik_ve_pencere():
    gun = (dk(8), dk(20))
    assert hatirlatma.ozet_dilimleri(gun, 2) == [dk(h) for h in (8, 10, 12, 14, 16, 18, 20)]       # 20:00 dâhil
    assert hatirlatma.ozet_dilimleri(gun, 3) == [dk(h) for h in (8, 11, 14, 17, 20)]
    assert hatirlatma.ozet_dilimleri(gun, 5) == [dk(h) for h in (8, 13, 18)]
    assert hatirlatma.ozet_dilimleri((0, 24 * 60), 2) == [dk(h) for h in range(0, 24, 2)]           # 24:00 yok (ertesi günün 00:00'ı)
    assert hatirlatma.ozet_dilimleri((0, 24 * 60), 5) == [dk(h) for h in (0, 5, 10, 15, 20)]
    assert hatirlatma.ozet_dilimleri((dk(8, 30), dk(19, 30)), 2) == [dk(h, 30) for h in (8, 10, 12, 14, 16, 18)]
    assert hatirlatma.ozet_dilimleri(gun, 0) == []
    d = hatirlatma.ozet_dilimi
    # 2 saat, 08:00-20:00: dilim bir sonrakine kadar geçerli; bitişteki 20:00 dilimi en geç 1 saat geç gönderilir.
    for saat, beklenen in ((ist(7, 59), None), (ist(8, 0), dk(8)), (ist(9, 59), dk(8)), (ist(10, 5), dk(10)), (ist(19, 59), dk(18)),
                           (ist(20, 0), dk(20)), (ist(20, 59), dk(20)), (ist(21, 0), None), (ist(23, 30), None), (ist(0, 0), None)):
        assert d(saat, gun, 2) == beklenen, saat
    # 3 saat: 17:00 dilimi 20:00'a kadar; 5 saat: son dilim 18:00, pencere bitişinden 1 saat sonrasına (21:00) kadar.
    assert d(ist(19, 0), gun, 3) == dk(17) and d(ist(20, 10), gun, 3) == dk(20)
    assert d(ist(19, 30), gun, 5) == dk(18) and d(ist(20, 30), gun, 5) == dk(18) and d(ist(21, 0), gun, 5) is None
    # Bitişi ızgaraya denk gelmeyen pencere: 08:00-19:00, 2 saat → son dilim 18:00; 20:00 dilim değildir.
    assert d(ist(19, 30), (dk(8), dk(19)), 2) == dk(18) and d(ist(20, 10), (dk(8), dk(19)), 2) is None
    # Bütün gün: gece yarısından itibaren.
    assert d(ist(23, 59), (0, 24 * 60), 2) == dk(22) and d(ist(0, 1), (0, 24 * 60), 2) == 0
    # Zorla: pencere dışında da ızgaradaki son nokta (negatif olmaz).
    assert d(ist(7, 0), (dk(8, 30), dk(19, 30)), 2, zorla=True) == dk(6, 30)
    assert d(ist(0, 30), gun, 5, zorla=True) == 0 and d(ist(22, 0), gun, 2, zorla=True) == dk(22)


def test_utc_sunucu_istanbul_dilimi(web):
    c, a = web
    insert(a, ilk_gorulme=None, tarih='2026-11-26 04:30:00')  # UTC; İstanbul 07:30
    r = uret(a, datetime(2026, 11, 26, 4, 59), yerel_tz=UTC)          # İstanbul 07:59
    assert r['bekleyen_ozet']['durum'] == 'pencere dışı' and r['bekleyen_ozet']['istanbul_saati'] == '07:59' and ozetler(a) == []
    assert 'Bekleyen özeti: pencere dışında (İstanbul saati 07:59, pencere 08:00-20:00, 2 saatte bir)' in hatirlatma.rapor_metni(r)
    r = uret(a, datetime(2026, 11, 26, 5, 0), yerel_tz=UTC)           # İstanbul 08:00
    assert r['bekleyen_ozet']['dilim'] == '2026-11-26 08:00' and r['bekleyen_ozet']['bildirim'] == 1
    satir = ozetler(a)[0]
    assert satir['olay'] == 'bekleyen-ozet:2026-11-26 08:00' and satir['zaman'] == '2026-11-26 05:00:00'
    assert satir['metin'] == 'Onay bekleyen 1 kayıt var (OF 1); en eskisi 1 saatten kısa süredir bekliyor. Son 2 saatte 1 yeni kayıt geldi.'
    # UTC 21:30 = İstanbul 27.11 00:30: pencere dışı; bütün gün penceresinde 27.11'in 00:00 dilimi.
    assert uret(a, datetime(2026, 11, 26, 21, 30), yerel_tz=UTC)['bekleyen_ozet']['durum'] == 'pencere dışı'
    r = uret(a, datetime(2026, 11, 26, 21, 30), yerel_tz=UTC, ayar={'BEKLEYEN_OZET_PENCERE': ''})
    assert r['bekleyen_ozet']['dilim'] == '2026-11-27 00:00' and r['bekleyen_ozet']['pencere'] == 'bütün gün'
    # Aynı UTC saati İstanbul sunucusunda 05:00 demektir: pencere dışı.
    assert uret(a, datetime(2026, 11, 27, 5, 0), yerel_tz=IST)['bekleyen_ozet']['durum'] == 'pencere dışı'


# =============================================================== Metin, kapsam, alıcılar
def _veri(a):
    ids = dict(
        of_eski=insert(a, ilk_gorulme=ts(SIMDI - timedelta(days=3, hours=2)), tarih=ts(SIMDI - timedelta(days=3, hours=2))),
        of_sinir=insert(a, ilk_gorulme=None, tarih=ts(SIMDI - timedelta(hours=2))),             # tam 2 saat önce: "yeni" değil
        ga_bes=insert(a, proje='GA', ilk_gorulme=None, tarih=ts(SIMDI - timedelta(hours=5))),
        ga_yeni1=insert(a, proje='GA', ilk_gorulme=None, tarih=ts(SIMDI - timedelta(hours=1, minutes=50))),
        ga_yeni2=insert(a, proje='GA', ilk_gorulme=None, tarih=ts(SIMDI - timedelta(minutes=30))),
        pa=insert(a, proje='PA', ilk_gorulme=ts(SIMDI - timedelta(hours=7)), tarih=ts(SIMDI - timedelta(hours=7))),
    )
    insert(a, kt=1, ilk_gorulme=None, tarih=ts(SIMDI - timedelta(hours=1)))         # onaylı: bekleyen değil, ama son 2 saatte geldi
    insert(a, silindi=1, ilk_gorulme=None, tarih=ts(SIMDI - timedelta(minutes=10)))  # silinmiş: hiç sayılmaz
    return ids


def test_metin_sayilar_kapsam_ve_alicilar(web):
    c, a = web
    account(a, 'lider', 'OF:oku,kt;GA:oku,kt'); account(a, 'okuyucu', 'OF:oku'); account(a, 'pa', 'PA:oku,kt'); account(a, 'hi', 'HI:oku,kt')
    ids = _veri(a)
    tum = uret(a, SIMDI); r = tum['bekleyen_ozet']
    assert r['dilim'] == '2026-11-26 10:00' and r['durum'] == 'gönderildi' and r['bildirim'] == 3 and r['bos'] == 1   # hi: bekleyeni yok
    assert 'Bekleyen özeti (2026-11-26 10:00): 3 alıcıya gönderildi, 0 önceki özet okundu sayıldı, 1 alıcının bekleyeni yok; durum: gönderildi.' in hatirlatma.rapor_metni(tum)
    satir = {x['kullanici_adi']: x for x in ozetler(a)}
    assert set(satir) == {'testadmin', 'lider', 'pa'}                 # okuyucu (kt yok) ve hi (bekleyen yok) almaz
    assert satir['testadmin']['metin'] == 'Onay bekleyen 6 kayıt var (GA 3, OF 2, PA 1); en eskisi 3 gündür bekliyor. Son 2 saatte 3 yeni kayıt geldi.'
    assert satir['lider']['metin'] == 'Onay bekleyen 5 kayıt var (GA 3, OF 2); en eskisi 3 gündür bekliyor. Son 2 saatte 3 yeni kayıt geldi.'
    assert satir['pa']['metin'] == 'Onay bekleyen 1 kayıt var (PA 1); en eskisi 7 saattir bekliyor.'   # yeni kayıt yok: son cümle yok
    for ad, x in satir.items():
        assert x['olay'] == 'bekleyen-ozet:2026-11-26 10:00' and x['kim'] == 'sistem' and x['okundu'] == 0 and x['zaman'] == ts(SIMDI)
    # Rozet/bağlantı projesi en kalabalık proje; satırın kaydı o projenin en eski bekleyeni.
    assert (satir['testadmin']['proje'], satir['testadmin']['kayit_id']) == ('GA', ids['ga_bes'])
    assert (satir['lider']['proje'], satir['lider']['kayit_id']) == ('GA', ids['ga_bes'])
    assert (satir['pa']['proje'], satir['pa']['kayit_id']) == ('PA', ids['pa'])
    assert rows(a, "SELECT COUNT(*) n FROM denetim WHERE islem='hatirlatma_uret' AND hedef_id='bekleyen-ozet:2026-11-26 10:00'")[0]['n'] == 1
    ikinci = uret(a, SIMDI + timedelta(minutes=10))['bekleyen_ozet']
    assert ikinci['bildirim'] == 0 and ikinci['durum'] == 'bu dilim zaten gönderildi' and len(ozetler(a)) == 3


def test_dilim_basina_bir_satir_ve_onceki_ozet_okundu(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt')
    insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    assert uret(a, SIMDI)['bekleyen_ozet']['bildirim'] == 2
    for dakika in (10, 60, 119):                                       # aynı dilim: yeni satır yok
        r = uret(a, SIMDI + timedelta(minutes=dakika))['bekleyen_ozet']
        assert r['bildirim'] == 0 and r['durum'] == 'bu dilim zaten gönderildi', dakika
    assert len(ozetler(a, 'lider')) == 1
    # 12:00 dilimi: yeni satır; lider'in 10:00 özeti okundu sayılır (zilde yalnız son özet).
    r = uret(a, SIMDI + timedelta(hours=2))['bekleyen_ozet']
    assert r['bildirim'] == 2 and r['eskiyen'] == 2 and r['dilim'] == '2026-11-26 12:00'
    liste = ozetler(a, 'lider')
    assert [(x['olay'], x['okundu']) for x in liste] == [('bekleyen-ozet:2026-11-26 10:00', 1), ('bekleyen-ozet:2026-11-26 12:00', 0)]
    assert liste[1]['metin'] == 'Onay bekleyen 1 kayıt var (OF 1); en eskisi 5 saattir bekliyor.'
    # Başka türden okunmamış hatırlatmalara dokunulmaz.
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES('lider',?,'OF','gun-sonu:2026-11-26','hatirlatma','sistem','x',?)",
                    (liste[1]['kayit_id'], ts(SIMDI)))
    con.close()
    uret(a, SIMDI + timedelta(hours=4))
    assert rows(a, "SELECT okundu FROM mesaj_bildirimleri WHERE kullanici_adi='lider' AND olay='gun-sonu:2026-11-26'")[0]['okundu'] == 0
    assert [x['okundu'] for x in ozetler(a, 'lider')] == [1, 1, 0]
    # Panel kapalıyken kaçan dilimler sonradan gönderilmez: 14:00'ten 19:30'a atlanır → yalnız 18:00 dilimi.
    r = uret(a, SIMDI + timedelta(hours=9, minutes=30))['bekleyen_ozet']
    assert r['dilim'] == '2026-11-26 18:00' and [x['olay'][-5:] for x in ozetler(a, 'lider')] == ['10:00', '12:00', '14:00', '18:00']


def test_bekleyen_yoksa_satir_yok_ve_onceki_okundu(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt')
    kid = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    uret(a, SIMDI)
    login(c, 'lider')
    assert c.post('/kayit/%d/kt' % kid, data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    r = uret(a, SIMDI + timedelta(hours=2))['bekleyen_ozet']
    assert r['bildirim'] == 0 and r['bos'] == 2 and r['eskiyen'] == 2 and r['durum'] == 'bekleyen kayıt yok'
    assert [(x['kullanici_adi'], x['okundu']) for x in ozetler(a)] == [('lider', 1), ('testadmin', 1)]
    assert not [x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma']


def test_yonetici_ayari_ve_gizle_modu(web):
    c, a = web
    account(a, 'sef', 'OF:oku;PA:oku,kt'); account(a, 'mudur', 'superadmin')
    insert(a, proje='OF', ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    insert(a, proje='OF', ilk_gorulme=ts(SIMDI - timedelta(hours=4)))
    insert(a, proje='PA', ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    # BEKLEYEN_OZET_YONETICI=0: yöneticiler almaz; kt yetkili kullanıcılar alır.
    r = uret(a, SIMDI, ayar={'BEKLEYEN_OZET_YONETICI': '0'})['bekleyen_ozet']
    assert r['bildirim'] == 1 and [x['kullanici_adi'] for x in ozetler(a)] == ['sef']
    # Kapsam yalnız onay yetkisi olan projeler: OF'u okuyabilen ama onaylayamayan sef'e OF sayılmaz.
    assert ozetler(a, 'sef')[0]['metin'] == 'Onay bekleyen 1 kayıt var (PA 1); en eskisi 3 saattir bekliyor.'
    r = uret(a, SIMDI + timedelta(hours=2))['bekleyen_ozet']                  # varsayılan 1: yöneticiler de alır (tüm projeler)
    assert {x['kullanici_adi'] for x in ozetler(a) if x['olay'].endswith('12:00')} == {'sef', 'testadmin', 'mudur'}
    assert ozetler(a, 'mudur')[0]['metin'].startswith('Onay bekleyen 3 kayıt var (OF 2, PA 1); en eskisi 6 saattir')
    # ONAYSIZ_GORUNUM=gizle: aynı kapsam; satır sef'in zilinde görünür.
    a['ONAYSIZ_GORUNUM'] = 'gizle'
    uret(a, SIMDI + timedelta(hours=4))
    son = ozetler(a, 'sef')[-1]
    assert son['proje'] == 'PA' and son['metin'].startswith('Onay bekleyen 1 kayıt var (PA 1)')
    login(c, 'sef')
    assert [x['olay'] for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma'] == ['bekleyen-ozet:2026-11-26 14:00']


def test_kapali_ve_kalabalik_proje_dokumu(web):
    c, a = web
    insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    r = uret(a, SIMDI, ayar={'BEKLEYEN_OZET_SAAT': 0})
    assert r['bekleyen_ozet']['durum'] == 'kapalı' and ozetler(a) == []
    assert 'Bekleyen özeti: kapalı (BEKLEYEN_OZET_SAAT=0).' in hatirlatma.rapor_metni(r)
    # 9 proje: ilk 8'i adıyla, kalanı "diğer".
    for i, p in enumerate(('PA', 'GA', 'HI', 'VI', 'PP', 'BETA', 'X1', 'X2', 'X3')):
        for _ in range(9 - i):
            insert(a, proje=p, ilk_gorulme=ts(SIMDI - timedelta(hours=1)))
    uret(a, SIMDI)
    metin = ozetler(a)[0]['metin']
    assert metin.startswith('Onay bekleyen 46 kayıt var (PA 9, GA 8, HI 7, VI 6, PP 5, BETA 4, X1 3, X2 2, diğer 2 proje 2); en eskisi 3 saattir')


# =============================================================== Ayarlar
def test_ayarlar_dogrulama_ve_varsayilanlar(capsys):
    from app import settings
    v = hatirlatma.ayarlar({})
    assert (v['ozet_saat'], v['ozet_pencere'], v['ozet_yonetici'], v['saat']) == (2, (480, 1200), True, 0)
    for ham, beklenen in ((None, 2), ('x', 2), (-1, 2), (0, 0), ('0', 0), (3, 3), (100, 24)):
        assert hatirlatma.ayarlar({'BEKLEYEN_OZET_SAAT': ham})['ozet_saat'] == beklenen, ham
    hatirlatma._LOGLANAN.clear()
    for ham, beklenen in (('', (0, 1440)), ('  ', (0, 1440)), ('08-20', (480, 1200)), ('8.30-19.30', (510, 1170)), ('07:00 - 22:00', (420, 1320)),
                          ('00:00-24:00', (0, 1440)), (None, (480, 1200)), ('20:00-08:00', (480, 1200)), ('abc', (480, 1200)), ('25:00-26:00', (480, 1200))):
        assert hatirlatma.ayarlar({'BEKLEYEN_OZET_PENCERE': ham})['ozet_pencere'] == beklenen, ham
    cikti = capsys.readouterr().out
    assert "BEKLEYEN_OZET_PENCERE geçersiz ('20:00-08:00')" in cikti and cikti.count("'abc'") == 1
    hatirlatma.ayarlar({'BEKLEYEN_OZET_PENCERE': 'abc'})
    assert capsys.readouterr().out == ''                                       # bir kez
    for ham, beklenen in (('0', False), ('hayır', False), ('1', True), ('', True), (None, True), ('evet', True)):
        assert hatirlatma.ayarlar({'BEKLEYEN_OZET_YONETICI': ham})['ozet_yonetici'] is beklenen, ham
    for anahtar in ('BEKLEYEN_OZET_SAAT', 'BEKLEYEN_OZET_PENCERE', 'BEKLEYEN_OZET_YONETICI'):
        assert anahtar in settings.AYAR and anahtar in (ROOT / '.env.example').read_text(encoding='utf-8')


def test_ortam_varsayilanlari(monkeypatch):
    from app import settings
    for k in ('HATIRLATMA_SAAT', 'BEKLEYEN_OZET_SAAT', 'BEKLEYEN_OZET_PENCERE', 'BEKLEYEN_OZET_YONETICI'):
        monkeypatch.delenv(k, raising=False)
    v = hatirlatma.ayarlar(settings.settings())
    assert (v['saat'], v['ozet_saat'], v['ozet_pencere'], v['ozet_yonetici']) == (0, 2, (480, 1200), True)
    monkeypatch.setenv('HATIRLATMA_SAAT', '2'); monkeypatch.setenv('BEKLEYEN_OZET_SAAT', '0'); monkeypatch.setenv('BEKLEYEN_OZET_PENCERE', '')
    v = hatirlatma.ayarlar(settings.settings())
    assert (v['saat'], v['ozet_saat'], v['ozet_pencere']) == (2, 0, (0, 1440))


def test_kayit_basina_iki_saat_varsayilan_kapali_ve_yeniden_acilir(web):
    c, a = web
    kid = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    ayar = {k: v for k, v in a.items() if k != 'HATIRLATMA_SAAT'}
    con = db.baglan(a['DB'])
    try:
        r = hatirlatma.uret(con, dict(ayar, HATIRLATMA_GUN=36500, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=0), simdi=lambda: SIMDI, yerel_tz=IST, tz=IST)
        assert r['saat']['durum'] == 'kapalı' and '2 saat kuralı: kapalı' in hatirlatma.rapor_metni(r)
        r = hatirlatma.uret(con, dict(ayar, HATIRLATMA_GUN=36500, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=0, HATIRLATMA_SAAT=2),
                            simdi=lambda: SIMDI, yerel_tz=IST, tz=IST)
        assert r['saat']['hatirlatma'] == 1
    finally:
        con.close()
    assert rows(a, "SELECT COUNT(*) n FROM mesaj_bildirimleri WHERE olay=?", 'hatirlatma-saat:%d' % kid)[0]['n'] == 1


def test_gun_sonu_metni_varsayilanda_degismez(web):
    """Kayıt başına 2 saat kapalıyken gün sonundaki "2 saatten uzun bekleyen" parçası özet aralığıyla (2) yazılır."""
    c, a = web
    insert(a, ilk_gorulme=ts(datetime(2026, 11, 26, 9)))
    r = uret(a, datetime(2026, 11, 26, 18, 1), ayar={'GUN_SONU_SAAT': '18:00'})
    assert r['gun_sonu']['bildirim'] == 1
    metin = rows(a, "SELECT metin FROM mesaj_bildirimleri WHERE olay='gun-sonu:2026-11-26'")[0]['metin']
    assert metin.endswith(', 2 saatten uzun bekleyen 1.')


# =============================================================== Bağlantı, akış, arayüz
def test_bildirim_json_ozet_ve_derin_baglanti(web):
    c, a = web
    account(a, 'lider', 'OF:oku,kt;GA:oku,kt'); account(a, 'karma', 'OF:oku,kt;GA:oku;PA:oku,kt')
    _veri(a)
    uret(a, SIMDI)
    login(c)
    hat = [x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma']
    assert len(hat) == 1 and hat[0]['ozet'] is True and hat[0]['url'] == '/kayitlar?durum=bekleyen' and hat[0]['etiket'] == 'Hatırlatma'
    assert hat[0]['metin'].startswith('Onay bekleyen 6 kayıt var') and hat[0]['olay'] == 'bekleyen-ozet:2026-11-26 10:00'
    html = c.get('/bildirimler?tur=hatirlatma').data.decode()
    assert 'Bekleyenleri aç' in html and 'data-bildirim-hedef="/kayitlar?durum=bekleyen"' in html and 'Kayıt #' not in html
    c.post('/cikis', data={'csrf': csrf(c)})
    login(c, 'lider')                                                   # tüm görebildiği projelerde onay yetkisi var: süzgeç yok
    assert [x['url'] for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma'] == ['/kayitlar?durum=bekleyen']
    c.post('/cikis', data={'csrf': csrf(c)})
    login(c, 'karma')                                                   # GA'yı yalnız okur: bağlantı OF + PA bekleyenleri
    hat = [x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma']
    assert len(hat) == 1 and hat[0]['metin'].startswith('Onay bekleyen 3 kayıt var (OF 2, PA 1)')
    url = urlparse(hat[0]['url'])
    assert url.path == '/kayitlar' and sorted(parse_qs(url.query)['proje']) == ['OF', 'PA'] and parse_qs(url.query)['durum'] == ['bekleyen']
    assert c.get(hat[0]['url']).status_code == 200


def test_panel_js_bekleyen_ozeti_pencereyi_acmaz():
    js = (STATIC / 'panel.js').read_text(encoding='utf-8')
    blok = js[js.index('/* ===== 2.3.3: bildirim pop-up kartları'):js.index('/* ===== 2.3.3: bildirim pop-up bloğu (son) ===== */')]
    assert "indexOf('bekleyen-ozet:')===0" in blok and "'Bekleyen özeti'" in blok
    assert 'if(yeniler.some(pencereAcarMi))hpAc(false);' in blok and 'if(hatYeni)hpAc(false);' not in blok
    assert 'return pencereAcarMi(n)&&!b[bildirimAnahtari(n)];' in blok
    from app import bildirim_gecmisi
    assert 'bekleyen-ozet:' in bildirim_gecmisi.OZET_ONEKLERI


# =============================================================== CLI
def test_cli_bekleyen_ozet_zorla(tmp_path):
    veri = tmp_path / 'veri'
    ortam = dict(os.environ, PANEL_VERI=str(veri), GYAZO_WORKER='0', GUN_SONU_SAAT='')
    for k in ('HATIRLATMA_SAAT', 'BEKLEYEN_OZET_SAAT', 'BEKLEYEN_OZET_YONETICI', 'HATIRLATMA_GUN'):
        ortam.pop(k, None)
    ortam['BEKLEYEN_OZET_PENCERE'] = '08:00-08:01'   # pencere neredeyse hiç açık değil: zorla olmadan çoğu saatte gönderilmez
    kur = subprocess.run([sys.executable, '-m', 'app.cli', 'veritabani-kur'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert kur.returncode == 0, kur.stderr
    ayar = {'DB': str(veri / 'panel.db')}
    kullanicilar.ekle(ayar, 'patron', 'admin', 'Guclu-Parola-77')
    con = db.baglan(ayar['DB'])
    with db.transaction(con):
        con.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih) VALUES('x:1','OF','P1','telegram',?)", (ts(datetime.now() - timedelta(hours=3)),))
    con.close()
    yardim = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--help'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120).stdout
    assert '--bekleyen-ozet-zorla' in yardim
    r = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--bekleyen-ozet-zorla'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    rapor = json.loads(r.stdout)
    b = rapor['bekleyen_ozet']
    assert b['bildirim'] == 1 and b['durum'] == 'gönderildi' and b['aralik_saat'] == 2 and b['pencere'] == '08:00-08:01'
    assert rapor['saat']['durum'] == 'kapalı'                      # 2.3.8: kayıt başına 2 saat varsayılan kapalı
    assert 'Bekleyen özeti (%s): 1 alıcıya gönderildi' % b['dilim'] in r.stderr and '2 saat kuralı: kapalı' in r.stderr
    satir = rows(ayar, "SELECT kullanici_adi,olay,metin FROM mesaj_bildirimleri WHERE olay LIKE 'bekleyen-ozet:%'")
    assert len(satir) == 1 and satir[0]['kullanici_adi'] == 'patron' and satir[0]['olay'] == 'bekleyen-ozet:' + b['dilim']
    assert satir[0]['metin'] == 'Onay bekleyen 1 kayıt var (OF 1); en eskisi 3 saattir bekliyor.'
    r2 = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--bekleyen-ozet-zorla'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0, r2.stderr
    b2 = json.loads(r2.stdout)['bekleyen_ozet']
    if b2['dilim'] == b['dilim']:                                   # aynı dilim (sınırda saat dönmediyse): yeni satır yok
        assert b2['bildirim'] == 0 and 'zaten gönderildi' in r2.stderr


# =============================================================== Tarayıcı (Node + Playwright yoksa atlanır)
def _playwright_var():
    import shutil
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class _Yardimci:
    """Tarayıcı betiğinin çağırdığı yerel HTTP yardımcısı: bekleyen kayıt + özet üretir, kayıt hatırlatması ekler."""

    def __init__(self, ayar):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.ayar = ayar; self.sira = 0; self.kilit = threading.Lock(); yardimci = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                veri = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                try:
                    with yardimci.kilit:
                        govde, durum = json.dumps(yardimci.islem(self.path.strip('/'), veri)).encode(), 200
                except Exception as e:
                    govde, durum = json.dumps({'hata': repr(e)}).encode(), 500
                self.send_response(durum); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(govde)))
                self.end_headers(); self.wfile.write(govde)

        self.sunucu = ThreadingHTTPServer(('127.0.0.1', 0), H); self.sunucu.daemon_threads = True
        threading.Thread(target=self.sunucu.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d' % self.sunucu.server_address[1]

    def islem(self, ad, veri):
        con = db.baglan(self.ayar['DB'])
        try:
            if ad == 'ozet':
                # Bekleyen kayıt ekle ve bekleyen özetini sıradaki dilim için üret (her çağrı ayrı dilim: önceki özet okundu olur).
                self.sira += 1
                with db.transaction(con):
                    con.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih) VALUES(?,?,?,?,?)",
                                ('oz:%d' % self.sira, 'OF', 'P%d' % self.sira, 'telegram', db.simdi()))
                an = datetime.now() + timedelta(hours=2 * self.sira)
                hatirlatma.uret(con, dict(self.ayar, HATIRLATMA_GUN=36500, HATIRLATMA_SAAT=0, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=2,
                                          BEKLEYEN_OZET_PENCERE=''), simdi=lambda: an, bekleyen_ozet_zorla=True)
                satir = con.execute("SELECT id,kayit_id FROM mesaj_bildirimleri WHERE kullanici_adi='testadmin' AND olay LIKE 'bekleyen-ozet:%' "
                                    'ORDER BY id DESC LIMIT 1').fetchone()
                return {'id': satir['id'], 'kayit_id': satir['kayit_id']}
            if ad == 'hatirlatma':
                self.sira += 1
                with db.transaction(con):
                    kid = con.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih) VALUES(?,?,?,?,?)",
                                      ('hk:%d' % self.sira, 'OF', 'H%d' % self.sira, 'telegram', db.simdi())).lastrowid
                    bid = con.execute('INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                                      ('testadmin', kid, 'OF', 'hatirlatma:%d:%s' % (kid, datetime.now().date().isoformat()), 'hatirlatma',
                                       hatirlatma.KIM, hatirlatma.kayit_metni(4), db.simdi())).lastrowid
                return {'id': bid, 'kayit_id': kid}
            if ad == 'okundu':
                return {'okundu': con.execute('SELECT okundu FROM mesaj_bildirimleri WHERE id=?', (int(veri['id']),)).fetchone()[0]}
            raise ValueError(ad)
        finally:
            con.close()

    def kapat(self):
        self.sunucu.shutdown(); self.sunucu.server_close()


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_bekleyen_ozeti_kart_zil_pencere_acmaz(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    yardimci = _Yardimci(a)
    try:
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, YARDIMCI_URL=yardimci.url)
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=150, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        yardimci.kapat()
        try:
            sunucu.close()
        except Exception:
            pass
