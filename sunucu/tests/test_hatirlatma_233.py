"""2.3.3 — Hatırlatma zamanlaması: 2 saat bildirimi (tek tek / toplu) ve İstanbul saatiyle 18:00 gün sonu özeti.

Saat enjekte edilir: uret(simdi=..., yerel_tz=..., tz=...). 'simdi' sunucunun yerel saatidir (db.simdi() ile aynı saat);
yerel_tz o saatin dilimi (UTC ya da İstanbul sunucusu canlandırılır), tz İstanbul dilimidir.
3 gün kuralı bu dosyada etkisizdir (HATIRLATMA_GUN çok büyük): yalnız yeni adımlar sınanır.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app import db, hatirlatma, kullanicilar
from test_web import web, login, csrf  # noqa: F401  (ortak fixture/yardımcılar)
from test_bildirim_231 import account, insert, rows

ROOT = Path(__file__).resolve().parents[1]
IST = ZoneInfo('Europe/Istanbul')
UTC = timezone.utc
SIMDI = datetime(2026, 11, 26, 15, 0, 0)  # İstanbul sunucusu: 15:00
SAAT_OLAY = "(olay LIKE 'hatirlatma-saat:%' OR olay LIKE 'hatirlatma-saat-ozet:%')"


def ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def uret(a, an, yerel_tz=IST, **kw):
    # 2.3.8: kayıt başına 2 saat bildirimi varsayılan kapalı; bu dosya onu sınar (HATIRLATMA_SAAT=2). Bekleyen özeti
    # test_bekleyen_ozet_238.py'de sınanır, burada kapalı.
    ayar = dict(a, HATIRLATMA_GUN=36500, HATIRLATMA_SAAT=2, BEKLEYEN_OZET_SAAT=0)
    ayar.update(kw.pop('ayar', {}))
    c = db.baglan(a['DB'])
    try:
        return hatirlatma.uret(c, ayar, simdi=lambda: an, yerel_tz=yerel_tz, tz=IST, **kw)
    finally:
        c.close()


def saat_satirlari(a, ad=None):
    sql = "SELECT * FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND " + SAAT_OLAY + (' AND kullanici_adi=?' if ad else '') + ' ORDER BY id'
    return rows(a, sql, *([ad] if ad else []))


def gun_sonu_satirlari(a):
    return rows(a, "SELECT * FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'gun-sonu:%' ORDER BY kullanici_adi,id")


# =============================================================== R1 — 2 saat bildirimi
def test_iki_saat_esigi_alicilar_idempotent_ve_onayla_kapanir(web):
    c, a = web
    account(a, 'lider', 'OF:oku,kt'); account(a, 'okuyucu', 'OF:oku'); account(a, 'baska', 'PA:oku,kt')
    kid = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=1, minutes=59)), tarih=ts(SIMDI), personel='Ayşe K.')
    eski1 = insert(a, kaynak='legacy_excel', ilk_gorulme=ts(SIMDI - timedelta(days=9)), tarih='2026-11-17')
    eski2 = insert(a, kaynak='excel', ilk_gorulme=ts(SIMDI - timedelta(days=9)), tarih='2026-11-17')
    silik = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=5)), silindi=1)
    onayli = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=5)), kt=1)
    r = uret(a, SIMDI)
    assert r['saat']['aday'] == 0 and saat_satirlari(a) == []      # 1 sa 59 dk: henüz yok
    r = uret(a, SIMDI + timedelta(minutes=1))                       # tam 2 saat
    alinan = saat_satirlari(a)
    assert r['saat']['hatirlatma'] == 2 and {x['kullanici_adi'] for x in alinan} == {'testadmin', 'lider'}
    for x in alinan:
        assert x['kayit_id'] == kid and x['olay'] == 'hatirlatma-saat:%d' % kid and x['kim'] == 'sistem' and x['okundu'] == 0
        assert x['metin'] == 'Kayıt #%d (Ayşe K.) 2 saattir onay bekliyor.' % kid
        assert x['zaman'] == ts(SIMDI + timedelta(minutes=1))
    assert not {eski1, eski2, silik, onayli} & {x['kayit_id'] for x in saat_satirlari(a)}
    assert rows(a, "SELECT COUNT(*) n FROM hatirlatma_isaret WHERE tur='saat'")[0]['n'] == 2
    # Yeniden çalıştırma (10 dk sonra, ertesi gün) yeni satır eklemez: kayıt başına kullanıcıya bir kez.
    assert uret(a, SIMDI + timedelta(minutes=11))['saat']['hatirlatma'] == 0
    assert uret(a, SIMDI + timedelta(days=1))['saat']['hatirlatma'] == 0 and len(saat_satirlari(a)) == 2
    # Onaylama: kaydın 2 saat hatırlatmaları okundu olur ve akıştan düşer.
    login(c, 'lider')
    assert c.post('/kayit/%d/kt' % kid, data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    assert {x['okundu'] for x in saat_satirlari(a)} == {1}


def test_iki_saat_baslangic_zamani_telegram_ve_guncelleme(web):
    c, a = web
    # Telegram kaydı: ilk_gorulme boş, tarih eklenme anı. Sonradan düzenleme (guncelleme) sayacı sıfırlamaz.
    tg = insert(a, ilk_gorulme=None, tarih=ts(SIMDI - timedelta(hours=3)), guncelleme=ts(SIMDI - timedelta(minutes=10)), personel='')
    bos = insert(a, ilk_gorulme='', tarih=None, guncelleme=ts(SIMDI - timedelta(hours=26)), personel='P9')
    taze = insert(a, ilk_gorulme=None, tarih=ts(SIMDI - timedelta(minutes=30)))
    uret(a, SIMDI)
    metinler = {x['kayit_id']: x['metin'] for x in saat_satirlari(a, 'testadmin')}
    assert set(metinler) == {tg, bos}
    assert metinler[tg] == 'Kayıt #%d 3 saattir onay bekliyor.' % tg               # personel boşsa parantez yok
    assert metinler[bos] == 'Kayıt #%d (P9) 1 gündür onay bekliyor.' % bos           # 24 saati geçen: gün
    assert taze not in metinler


def test_iki_saat_toplu_kural_ve_sonraki_kayit(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt;PA:oku,kt')
    of = [insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3, minutes=i)), personel='OF%d' % i) for i in range(6)]
    pa = [insert(a, proje='PA', ilk_gorulme=ts(SIMDI - timedelta(hours=4, minutes=i))) for i in range(5)]  # tam 5: toplu değil
    r = uret(a, SIMDI)
    satir = saat_satirlari(a, 'lider')
    ozet = [x for x in satir if x['olay'].startswith('hatirlatma-saat-ozet:')]
    tekil = [x for x in satir if x['olay'].startswith('hatirlatma-saat:')]
    assert len(ozet) == 1 and ozet[0]['olay'] == 'hatirlatma-saat-ozet:OF:2026-11-26 15:00' and ozet[0]['proje'] == 'OF'
    en_eski = of[5]  # en uzun süredir bekleyen (3 sa 5 dk)
    assert ozet[0]['kayit_id'] == en_eski
    assert ozet[0]['metin'] == 'OF: 6 kayıt en az 2 saattir onay bekliyor (#%d, #%d, #%d, …).' % (of[5], of[4], of[3])
    assert sorted(x['kayit_id'] for x in tekil) == sorted(pa)
    assert r['saat']['ozet'] == 2 and r['saat']['toplu_kapsanan'] == 12 and r['saat']['hatirlatma'] == 10  # lider + testadmin
    assert rows(a, "SELECT COUNT(*) n FROM hatirlatma_isaret WHERE kullanici_adi='lider'")[0]['n'] == 11
    # Sonraki çalıştırmalar ekleme yapmaz; toplu satırdaki kayıtlar tek tek de bildirilmez.
    assert uret(a, SIMDI + timedelta(minutes=10))['saat'] == dict(r['saat'], aday=11, hatirlatma=0, ozet=0, toplu_kapsanan=0)
    assert len(saat_satirlari(a)) == len(satir) * 2
    # Yedinci OF kaydı sonra eşiği geçer: tek başına olduğu için kayıt satırı gelir.
    yedi = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=1)), personel='Yedi')
    assert uret(a, SIMDI + timedelta(minutes=50))['saat']['hatirlatma'] == 0
    r = uret(a, SIMDI + timedelta(hours=1))
    assert r['saat']['hatirlatma'] == 2 and r['saat']['ozet'] == 0
    assert [x['olay'] for x in saat_satirlari(a, 'lider')][-1] == 'hatirlatma-saat:%d' % yedi


def test_iki_saat_ayni_dakikada_ikinci_toplu_satir_kaybolmaz(web):
    c, a = web
    for i in range(6):
        insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    uret(a, SIMDI)
    ikinci = [insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3))) for _ in range(6)]
    assert uret(a, SIMDI + timedelta(seconds=30))['saat']['ozet'] == 1
    olaylar = [x['olay'] for x in saat_satirlari(a, 'testadmin')]
    assert olaylar == ['hatirlatma-saat-ozet:OF:2026-11-26 15:00', 'hatirlatma-saat-ozet:OF:2026-11-26 15:00:%d' % ikinci[0]]


# =============================================================== R2 — gün sonu özeti
def _gun_sonu_verisi(a, bugun_bas):
    """bugun_bas: İstanbul gününün başı, sunucu yerel saatiyle (naive)."""
    ids = dict(
        of_bugun=insert(a, ilk_gorulme=None, tarih=ts(bugun_bas + timedelta(hours=9))),           # bugün eklendi, 2 saati geçti
        of_taze=insert(a, ilk_gorulme=None, tarih=ts(bugun_bas + timedelta(hours=17, minutes=30))),  # bugün eklendi, taze
        of_eski=insert(a, ilk_gorulme=ts(bugun_bas - timedelta(days=4)), tarih=ts(bugun_bas - timedelta(days=4))),
        pa_eski=insert(a, proje='PA', ilk_gorulme=ts(bugun_bas - timedelta(days=2)), tarih=ts(bugun_bas - timedelta(days=2))),
        pa_excel=insert(a, proje='PA', kaynak='legacy_excel', ilk_gorulme=ts(bugun_bas - timedelta(days=40)), tarih='2026-10-01'),
        ga=insert(a, proje='GA', ilk_gorulme=ts(bugun_bas - timedelta(hours=1)), tarih=ts(bugun_bas - timedelta(hours=1))),  # dün eklendi
    )
    insert(a, proje='PA', kt=1, kt_zaman=ts(bugun_bas + timedelta(hours=10)), ilk_gorulme=ts(bugun_bas - timedelta(days=1)))   # bugün onaylandı
    insert(a, proje='GA', kt=1, kt_zaman=ts(bugun_bas - timedelta(minutes=1)), ilk_gorulme=ts(bugun_bas - timedelta(days=1)))  # dün onaylandı
    insert(a, proje='GA', silindi=1, ilk_gorulme=ts(bugun_bas + timedelta(hours=2)))                                            # silinmiş: sayılmaz
    return ids


def test_gun_sonu_saat_sayilar_yinelenmez_ve_ertesi_gun(web):
    c, a = web; account(a, 'yonetici2', 'superadmin'); account(a, 'lider', 'OF:oku,kt')
    bas = datetime(2026, 11, 26)
    ids = _gun_sonu_verisi(a, bas)
    r = uret(a, datetime(2026, 11, 26, 17, 59, 59))
    assert r['gun_sonu']['durum'] == 'saati gelmedi' and r['gun_sonu']['istanbul_saati'] == '17:59' and gun_sonu_satirlari(a) == []
    r = uret(a, datetime(2026, 11, 26, 18, 0, 5))
    assert r['gun_sonu']['bildirim'] == 2 and r['gun_sonu']['durum'] == 'gönderildi' and r['gun_sonu']['tarih'] == '2026-11-26'
    satir = gun_sonu_satirlari(a)
    assert [x['kullanici_adi'] for x in satir] == ['testadmin', 'yonetici2']   # yalnız yöneticiler; lider almaz
    beklenen = 'Gün sonu 26.11.2026: 6 kayıt onaylanmadı (OF 3, PA 2, GA 1). Bugün eklenen 2, bugün onaylanan 1, 2 saatten uzun bekleyen 5.'
    for x in satir:
        assert x['olay'] == 'gun-sonu:2026-11-26' and x['metin'] == beklenen and x['kim'] == 'sistem'
        assert x['proje'] == 'OF' and x['kayit_id'] == ids['of_eski']          # en kalabalık proje, en eski bekleyen kaydı
    assert uret(a, datetime(2026, 11, 26, 18, 30))['gun_sonu']['bildirim'] == 0
    assert uret(a, datetime(2026, 11, 26, 23, 59))['gun_sonu']['durum'] == 'bugün zaten gönderildi' and len(gun_sonu_satirlari(a)) == 2
    # Ertesi gün 18:00'dan önce yok, sonra yeni satır.
    assert uret(a, datetime(2026, 11, 27, 9, 0))['gun_sonu']['bildirim'] == 0
    r = uret(a, datetime(2026, 11, 27, 18, 4))
    assert r['gun_sonu']['bildirim'] == 2
    yeni = [x for x in gun_sonu_satirlari(a) if x['olay'] == 'gun-sonu:2026-11-27']
    assert len(yeni) == 2 and yeni[0]['metin'].startswith('Gün sonu 27.11.2026: 6 kayıt onaylanmadı (OF 3, PA 2, GA 1). Bugün eklenen 0, bugün onaylanan 0')


def test_gun_sonu_alicilar_degistirilir_ve_bilinmeyen_kullanici(web, capsys):
    c, a = web; account(a, 'lider', 'OF:oku,kt'); account(a, 'pasif', 'OF:oku,kt'); account(a, 'yonetici2', 'admin')
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("UPDATE panel_kullanicilari SET aktif=0 WHERE kullanici_adi='pasif'")
    con.close()
    _gun_sonu_verisi(a, datetime(2026, 11, 26))
    hatirlatma._LOGLANAN.clear()
    ayar = {'GUN_SONU_ALICILAR': ' lider, yok_kisi ,pasif,lider'}
    r = uret(a, datetime(2026, 11, 26, 18, 1), ayar=ayar)
    satir = gun_sonu_satirlari(a)
    assert r['gun_sonu']['bildirim'] == 1 and [x['kullanici_adi'] for x in satir] == ['lider']   # liste yöneticilerin YERİNE geçer
    assert satir[0]['metin'] == 'Gün sonu 26.11.2026: 3 kayıt onaylanmadı (OF 3). Bugün eklenen 2, bugün onaylanan 0, 2 saatten uzun bekleyen 2.'
    cikti = capsys.readouterr().out
    assert "'yok_kisi' kullanıcısı yok ya da pasif" in cikti and "'pasif' kullanıcısı yok ya da pasif" in cikti
    uret(a, datetime(2026, 11, 27, 18, 1), ayar=ayar)
    assert 'yok_kisi' not in capsys.readouterr().out   # süreç başına bir kez
    # Hiç bekleyen görmeyen alıcıya satır gitmez (satır bir kayda bağlı olmak zorunda).
    account(a, 'bosproje', 'HI:oku,kt')
    r = uret(a, datetime(2026, 11, 28, 18, 1), ayar={'GUN_SONU_ALICILAR': 'bosproje'})
    assert r['gun_sonu']['bildirim'] == 0 and r['gun_sonu']['bos'] == 1 and r['gun_sonu']['durum'] == 'bekleyen kayıt yok'


def test_gun_sonu_utc_sunucu_istanbul_gun_siniri(web):
    c, a = web
    # Sunucu saati UTC: İstanbul 18:00 = UTC 15:00. İstanbul 27.11 günü = UTC 26.11 21:00 → 27.11 21:00.
    ist, bas, bit = hatirlatma.istanbul_gunu(datetime(2026, 11, 26, 22, 30), UTC, IST)
    assert ist.date().isoformat() == '2026-11-27' and ist.strftime('%H:%M') == '01:30'
    assert (bas, bit) == ('2026-11-26 21:00:00', '2026-11-27 21:00:00')
    ist, bas, bit = hatirlatma.istanbul_gunu(datetime(2026, 11, 26, 22, 30), IST, IST)
    assert ist.date().isoformat() == '2026-11-26' and (bas, bit) == ('2026-11-26 00:00:00', '2026-11-27 00:00:00')
    # Saat dilimi yoksa sunucu saati kullanılır.
    an = datetime(2026, 11, 26, 22, 30)
    assert hatirlatma.istanbul_gunu(an, None, None) == (an, '2026-11-26 00:00:00', '2026-11-27 00:00:00')
    # UTC sunucusunda kayıt zamanları da UTC yazılır: 26.11 21:30 UTC = İstanbul 27.11 00:30 → 27.11'in "bugün eklenen"i.
    insert(a, ilk_gorulme=None, tarih='2026-11-26 21:30:00')
    insert(a, ilk_gorulme=None, tarih='2026-11-26 20:59:59')
    insert(a, proje='PA', kt=1, kt_zaman='2026-11-27 20:59:00', ilk_gorulme='2026-11-20 10:00:00')
    insert(a, proje='PA', kt=1, kt_zaman='2026-11-27 21:00:00', ilk_gorulme='2026-11-20 10:00:00')  # İstanbul 28.11
    r = uret(a, datetime(2026, 11, 27, 14, 59), yerel_tz=UTC)
    assert r['gun_sonu']['durum'] == 'saati gelmedi' and r['gun_sonu']['istanbul_saati'] == '17:59'
    r = uret(a, datetime(2026, 11, 27, 15, 0), yerel_tz=UTC)
    assert r['gun_sonu']['tarih'] == '2026-11-27' and r['gun_sonu']['bildirim'] == 1
    metin = gun_sonu_satirlari(a)[0]['metin']
    assert metin.startswith('Gün sonu 27.11.2026: 2 kayıt onaylanmadı (OF 2). Bugün eklenen 1, bugün onaylanan 1')
    # Aynı UTC saatlerle İstanbul sunucusu (yerel saat = İstanbul) 15:00'te özet göndermez.
    assert uret(a, datetime(2026, 11, 28, 15, 0), yerel_tz=IST)['gun_sonu']['durum'] == 'saati gelmedi'


# =============================================================== Bağlantılar, akış, sayfa
def test_hedef_baglantilar_bildirim_json_ve_sayfa(web):
    from app import panel
    c, a = web
    tek = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)), personel='TEK')
    toplu = [insert(a, proje='GA', ilk_gorulme=ts(SIMDI - timedelta(hours=3, minutes=i))) for i in range(6)]
    uret(a, datetime(2026, 11, 26, 18, 2))
    with panel.app.test_request_context():
        assert panel._bildirim_hedef({'olay': 'gun-sonu:2026-11-26', 'proje': 'GA', 'kayit_id': 1, 'ozet': True}) == '/kayitlar?durum=bekleyen'
        assert panel._bildirim_hedef({'olay': 'hatirlatma-saat-ozet:GA:2026-11-26 15:00', 'proje': 'GA', 'kayit_id': 1, 'ozet': True}) == '/kayitlar?proje=GA&durum=bekleyen'
        assert panel._bildirim_hedef({'olay': 'hatirlatma-saat:%d' % tek, 'proje': 'OF', 'kayit_id': tek}) == '/kayitlar?proje=OF&durum=hepsi&ac=%d' % tek
    login(c)
    d = c.get('/bildirim.json').json
    hat = {x['olay'].split(':')[0]: x for x in d['bildirimler'] if x['tur'] == 'hatirlatma'}
    assert set(hat) == {'hatirlatma-saat', 'hatirlatma-saat-ozet', 'gun-sonu'}
    assert all(x['etiket'] == 'Hatırlatma' for x in hat.values())
    assert hat['hatirlatma-saat']['ozet'] is False and hat['hatirlatma-saat']['url'] == '/kayitlar?proje=OF&durum=hepsi&ac=%d' % tek
    assert hat['hatirlatma-saat']['personel'] == 'TEK' and hat['hatirlatma-saat']['metin'].startswith('Kayıt #%d (TEK) 6 saattir' % tek)
    assert hat['hatirlatma-saat-ozet']['ozet'] is True and hat['hatirlatma-saat-ozet']['url'] == '/kayitlar?proje=GA&durum=bekleyen'
    assert hat['gun-sonu']['ozet'] is True and hat['gun-sonu']['url'] == '/kayitlar?durum=bekleyen' and hat['gun-sonu']['proje'] == 'GA'
    assert hat['gun-sonu']['metin'].startswith('Gün sonu 26.11.2026: 7 kayıt onaylanmadı (GA 6, OF 1).')
    html = c.get('/bildirimler?tur=hatirlatma').data.decode()
    assert html.count('class="bildirim-satir tiklanir') == 3 and 'data-bildirim-hedef="/kayitlar?durum=bekleyen"' in html
    assert 'data-bildirim-hedef="/kayitlar?proje=GA&amp;durum=bekleyen"' in html and html.count('Bekleyenleri aç') == 2 and 'Kaydı aç' in html
    assert 'Gün sonu 26.11.2026' in html
    # Onaylanan kaydın 2 saat satırı akıştan düşer; toplu ve gün sonu satırları kalır.
    assert c.post('/kayit/%d/kt' % tek, data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    kalan = {x['olay'].split(':')[0] for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma'}
    assert kalan == {'hatirlatma-saat-ozet', 'gun-sonu'}
    assert c.post('/kayit/%d/kt' % toplu[5], data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    assert len([x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma']) == 2


# =============================================================== Ayarlar, kapatma, şema, CLI
def test_ayarlar_dogrulama_ve_kapatma(web, capsys):
    c, a = web
    v = hatirlatma.ayarlar({})
    assert (v['kontrol_dk'], v['saat'], v['saat_toplu'], v['gun_sonu'], v['gun_sonu_alicilar']) == (10, 0, 5, dtime(18, 0), None)  # 2.3.8: saat 0
    hatirlatma._LOGLANAN.clear()
    assert hatirlatma.ayarlar({'GUN_SONU_SAAT': '25:00'})['gun_sonu'] == dtime(18, 0)
    assert 'GUN_SONU_SAAT geçersiz' in capsys.readouterr().out
    hatirlatma.ayarlar({'GUN_SONU_SAAT': '25:00'})
    assert capsys.readouterr().out == ''                               # bir kez
    for ham, beklenen in (('abc', dtime(18, 0)), ('18.00', dtime(18, 0)), ('17.30', dtime(17, 30)), ('7.5', dtime(18, 0)), ('', None), ('0', None), (' 07:30 ', dtime(7, 30)), ('9:05', dtime(9, 5)), (None, dtime(18, 0))):
        assert hatirlatma.ayarlar({'GUN_SONU_SAAT': ham})['gun_sonu'] == beklenen, ham
    for ham, beklenen in (('0', 0), (0, 0), (-3, 0), ('x', 0), (None, 0), (2, 2), (5, 5), (10 ** 9, 720)):
        assert hatirlatma.ayarlar({'HATIRLATMA_SAAT': ham})['saat'] == beklenen, ham
    for ham, beklenen in ((0, 5), ('x', 5), (1, 1), (12, 12)):
        assert hatirlatma.ayarlar({'HATIRLATMA_SAAT_TOPLU': ham})['saat_toplu'] == beklenen, ham
    assert hatirlatma.ayarlar({'GUN_SONU_ALICILAR': ' ali, veli ,ali,,'})['gun_sonu_alicilar'] == ['ali', 'veli']
    assert hatirlatma.ayarlar({'GUN_SONU_ALICILAR': ' , '})['gun_sonu_alicilar'] is None
    assert hatirlatma.ayarlar({'HATIRLATMA_KONTROL_DK': 0})['kontrol_dk'] == 0
    # Kapatma: HATIRLATMA_SAAT=0 → 2 saat adımı yok; GUN_SONU_SAAT boş → gün sonu yok (zorla yine çalışır).
    insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=5)))
    r = uret(a, datetime(2026, 11, 26, 19, 0), ayar={'HATIRLATMA_SAAT': 0, 'GUN_SONU_SAAT': ''})
    assert r['saat']['durum'] == 'kapalı' and r['gun_sonu']['durum'] == 'kapalı' and saat_satirlari(a) == [] and gun_sonu_satirlari(a) == []
    r = uret(a, datetime(2026, 11, 26, 9, 0), ayar={'HATIRLATMA_SAAT': 0, 'GUN_SONU_SAAT': ''}, gun_sonu_zorla=True)
    assert r['gun_sonu']['bildirim'] == 1 and gun_sonu_satirlari(a)[0]['metin'].endswith('Bugün eklenen 1, bugün onaylanan 0.')  # 2 saat kapalı: o parça yok
    assert 'Gün sonu özeti (2026-11-26): 1 alıcıya gönderildi' in hatirlatma.rapor_metni(r) and '2 saat kuralı: kapalı' in hatirlatma.rapor_metni(r)


def test_sema_gecisi_eski_veritabani(web):
    c, a = web
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute('DROP TABLE hatirlatma_isaret'); con.execute("DELETE FROM ayarlar WHERE anahtar='core_schema_25'")  # 2.3.2 durumu
    con.close()
    kid = insert(a, ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    con = db.baglan(a['DB'])
    try:
        assert db.ayar_al(con, 'core_schema_25') == '1' and db.ayar_al(con, 'core_schema_24') == '1'
        assert {r['name'] for r in con.execute('PRAGMA table_info(hatirlatma_isaret)')} == {'kayit_id', 'kullanici_adi', 'tur', 'zaman'}
        assert con.execute('SELECT COUNT(*) FROM kayitlar WHERE id=?', (kid,)).fetchone()[0] == 1
    finally:
        con.close()


def test_cli_gun_sonu_zorla_ve_turkce_rapor(tmp_path):
    veri = tmp_path / 'veri'
    ortam = dict(os.environ, PANEL_VERI=str(veri), GYAZO_WORKER='0')
    for k in ('HATIRLATMA_SAAT', 'GUN_SONU_SAAT', 'GUN_SONU_ALICILAR', 'HATIRLATMA_GUN', 'BEKLEYEN_OZET_SAAT', 'BEKLEYEN_OZET_PENCERE'):
        ortam.pop(k, None)
    ortam['HATIRLATMA_SAAT'] = '2'  # 2.3.8: varsayılan kapalı; bu test 2 saat bildirimini de sınar
    kur = subprocess.run([sys.executable, '-m', 'app.cli', 'veritabani-kur'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert kur.returncode == 0, kur.stderr
    ayar = {'DB': str(veri / 'panel.db')}
    kullanicilar.ekle(ayar, 'patron', 'admin', 'Guclu-Parola-77')
    c = db.baglan(ayar['DB'])
    with db.transaction(c):
        c.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,tarih) VALUES('x:1','OF','P1','telegram',?)", (ts(datetime.now() - timedelta(hours=3)),))
    c.close()
    yardim = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--help'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120).stdout
    assert '--gun-sonu-zorla' in yardim
    r = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--gun-sonu-zorla'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    rapor = json.loads(r.stdout)   # stdout saf JSON kalır
    assert rapor['gun_sonu']['bildirim'] == 1 and rapor['saat']['hatirlatma'] == 1 and rapor['hatirlatma'] == 0
    assert '2 saat kuralı: eşiği geçen 1 kayıt; 1 yeni kayıt hatırlatması' in r.stderr and '1 alıcıya gönderildi' in r.stderr
    satir = rows(ayar, "SELECT kullanici_adi,olay,metin FROM mesaj_bildirimleri WHERE olay LIKE 'gun-sonu:%'")
    assert len(satir) == 1 and satir[0]['kullanici_adi'] == 'patron' and 'Gün sonu' in satir[0]['metin'] and '1 kayıt onaylanmadı (OF 1)' in satir[0]['metin']
    # Aynı gün yeniden: yeni satır yok. --tarih ile birlikte de çalışır.
    r2 = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--gun-sonu-zorla', '--tarih', datetime.now().date().isoformat()],
                        cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)['gun_sonu']['bildirim'] == 0 and 'zaten gönderildi' in r2.stderr


def test_arka_plan_isi_varsayilan_ve_dayaniklilik():
    from app import panel, settings
    kaynak = (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')
    assert "hatirlatma.uret(conn,AYAR)" in kaynak and 'except Exception as error' in kaynak
    assert "_tam_sayi('HATIRLATMA_KONTROL_DK', 10)" in (ROOT / 'app' / 'settings.py').read_text(encoding='utf-8')
    for anahtar in ('HATIRLATMA_SAAT', 'HATIRLATMA_SAAT_TOPLU', 'GUN_SONU_SAAT', 'GUN_SONU_ALICILAR'):
        assert anahtar in settings.AYAR
        assert anahtar in (ROOT / '.env.example').read_text(encoding='utf-8')


# =============================================================== 2.3.3 düzeltmeleri
def test_gun_sonu_gizle_modunda_kt_yetkisiz_alici(web):
    """ONAYSIZ_GORUNUM=gizle: kt yetkisi olmayan projelerin onaysız kayıtları alıcıya hiç görünmez; özet onları saymaz.
    Hiç kt projesi olmayan alıcıya özet gitmez (zilde görünmeyecek bir satır yazılmaz)."""
    c, a = web
    account(a, 'mudur', 'OF:oku'); account(a, 'sef', 'OF:oku;PA:oku,kt')
    insert(a, proje='OF', ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    insert(a, proje='PA', ilk_gorulme=ts(SIMDI - timedelta(hours=3)))
    a['ONAYSIZ_GORUNUM'] = 'gizle'
    r = uret(a, datetime(2026, 11, 26, 18, 1), ayar={'GUN_SONU_ALICILAR': 'mudur,sef', 'HATIRLATMA_SAAT': 0})
    assert r['gun_sonu']['bildirim'] == 1 and r['gun_sonu']['bos'] == 1
    satir = gun_sonu_satirlari(a)
    assert [x['kullanici_adi'] for x in satir] == ['sef'] and satir[0]['proje'] == 'PA'
    assert satir[0]['metin'].startswith('Gün sonu 26.11.2026: 1 kayıt onaylanmadı (PA 1).')
    login(c, 'sef')
    assert [x['olay'] for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma'] == ['gun-sonu:2026-11-26']


def test_ortam_negatif_hatirlatma_saat_varsayilana_doner(monkeypatch):
    from app import settings
    monkeypatch.setenv('HATIRLATMA_SAAT', '-3')
    assert hatirlatma.ayarlar(settings.settings())['saat'] == 0   # 2.3.8: varsayılan 0
    monkeypatch.setenv('HATIRLATMA_SAAT', '2')
    assert hatirlatma.ayarlar(settings.settings())['saat'] == 2
    monkeypatch.setenv('HATIRLATMA_SAAT', '0')
    assert hatirlatma.ayarlar(settings.settings())['saat'] == 0
