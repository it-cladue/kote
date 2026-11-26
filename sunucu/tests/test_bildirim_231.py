"""2.3.1 — Hatırlatma bildirimleri, onaysız kayıt görünürlük kuralı (ONAYSIZ_GORUNUM) ve bildirimden hedefe gitme.

Kapsam: hatırlatma üretimi (yaş eşiği, günde bir, tekrar aralığı, eski Excel özeti, günlük sınır, kt alıcı kümesi, CLI raporu),
'uyar' / 'gizle' davranışı (liste, arama uyarısı, ayrıntı 403, profil, çıktı sütunu/etiketleri, kt yetkili etkilenmez),
akışta tür/etiket/bağlantı ve ac+yorum derin bağlantısı için sunucu tarafı alanlar.
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import openpyxl
from werkzeug.datastructures import MultiDict

from app import db, kullanicilar, hatirlatma, yetki
from test_web import web, seed, login, csrf  # noqa: F401  (ortak fixture/yardımcılar)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
TEMPLATES = ROOT / 'app' / 'templates'
XHR = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def gun_once(n):
    return (date.today() - timedelta(days=n)).strftime('%Y-%m-%d 10:00:00')


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'row:' + str(time.time_ns())); cols.setdefault('kaynak', 'telegram')
    cols.setdefault('personel', 'P' + str(time.time_ns())[-5:])
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def rows(a, sql, *params):
    c = db.baglan(a['DB'])
    try: return [dict(r) for r in c.execute(sql, params)]
    finally: c.close()


def conn_uret(a, **kw):
    # 2.3.3 adımları (2 saat, gün sonu) burada kapalı: bu dosya yalnız 3 gün kuralını sınar (test_hatirlatma_233.py ayrı sınar).
    c = db.baglan(a['DB'])
    try: return hatirlatma.uret(c, dict(a, HATIRLATMA_SAAT=0, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=0), **kw)
    finally: c.close()


def logout(c):
    c.post('/cikis', data={'csrf': csrf(c)})


# =============================================================== A. Hatırlatma üretimi
def test_hatirlatma_yas_esigi_gunde_bir_ve_tekrar_araligi(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt')
    taze = insert(a, ilk_gorulme=gun_once(1), tarih=gun_once(1))
    eski = insert(a, ilk_gorulme=gun_once(3), tarih=gun_once(3))
    tarihli = insert(a, tarih=gun_once(5))                     # ilk_gorulme yok → tarih kullanılır
    onayli = insert(a, ilk_gorulme=gun_once(9), tarih=gun_once(9), kt=1)
    silinmis = insert(a, ilk_gorulme=gun_once(9), tarih=gun_once(9), silindi=1)
    tarihsiz = insert(a, ilk_gorulme=None, tarih=None)
    r = conn_uret(a)
    assert r['esik_gun'] == 3 and r['bekleyen'] == 2 and r['hatirlatma'] == 4 and r['ozet'] == 0  # 2 kayıt × (testadmin + lider)
    alinan = rows(a, "SELECT kullanici_adi,kayit_id,olay,tur,kim,metin FROM mesaj_bildirimleri WHERE tur='hatirlatma' ORDER BY kullanici_adi,kayit_id")
    assert {x['kayit_id'] for x in alinan} == {eski, tarihli} and {x['kullanici_adi'] for x in alinan} == {'lider', 'testadmin'}
    assert all(x['kim'] == 'sistem' and x['olay'] == 'hatirlatma:%d:%s' % (x['kayit_id'], date.today().isoformat()) for x in alinan)
    assert next(x for x in alinan if x['kayit_id'] == eski)['metin'] == "Bu ID'nin kontrolü 3 gündür bekliyor."
    assert next(x for x in alinan if x['kayit_id'] == tarihli)['metin'] == "Bu ID'nin kontrolü 5 gündür bekliyor."
    for kid in (taze, onayli, silinmis, tarihsiz):
        assert not any(x['kayit_id'] == kid for x in alinan), kid
    # Aynı gün ikinci çalıştırma yeni satır eklemez (idempotent); rapor 0 der.
    r2 = conn_uret(a); assert r2['hatirlatma'] == 0 and r2['ozet'] == 0 and r2['bekleyen'] == 2
    assert len(rows(a, "SELECT 1 FROM mesaj_bildirimleri WHERE tur='hatirlatma'")) == 4
    # Ertesi gün: 3 günlük tekrar aralığı dolmadı → yok; 3 gün sonra → yeniden (yaş 6 / 8).
    yarin = date.today() + timedelta(days=1)
    assert conn_uret(a, bugun=yarin)['hatirlatma'] == 0
    r3 = conn_uret(a, bugun=date.today() + timedelta(days=3))
    assert r3['hatirlatma'] == 6  # eski/tarihli yeniden (yaş 6 / 8) + o gün eşiği aşan 'taze' (yaş 4) ilk kez; × 2 alıcı
    metinler = [x['metin'] for x in rows(a, "SELECT metin FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND kayit_id=? AND kullanici_adi='lider' ORDER BY id", eski)]
    assert metinler == ["Bu ID'nin kontrolü 3 gündür bekliyor.", "Bu ID'nin kontrolü 6 gündür bekliyor."]
    # Denetim izi sistem adına yazılır ve Türkçe adı vardır.
    from app import panel
    assert rows(a, "SELECT COUNT(*) n FROM denetim WHERE islem='hatirlatma_uret' AND kullanici='sistem'")[0]['n'] == 2
    assert 'hatirlatma_uret' in panel.ISLEM_ADLARI and 'hatirlatma_uret' in panel.DENETIM_ADLARI


def test_hatirlatma_alici_kumesi_kt_yetkisine_gore(web):
    c, a = web
    account(a, 'lider_of', 'OF:oku,kt'); account(a, 'raporcu_of', 'OF:oku'); account(a, 'lider_pa', 'PA:oku,kt')
    account(a, 'pasif', 'OF:oku,kt'); kullanicilar.guncelle(a, 'pasif', aktif=0)
    kid = insert(a, ilk_gorulme=gun_once(4), tarih=gun_once(4))
    r = conn_uret(a)
    alicilar = {x['kullanici_adi'] for x in rows(a, "SELECT kullanici_adi FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND kayit_id=?", kid)}
    assert alicilar == {'testadmin', 'lider_of'} and r['alici'] == 2
    assert 'raporcu_of' not in r['kullanicilar'] and 'lider_pa' not in r['kullanicilar'] and 'pasif' not in r['kullanicilar']


def test_hatirlatma_eski_excel_ozeti_ve_gunluk_sinir(web):
    c, a = web
    for i in range(6):
        insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun_once(10 + i), tarih=gun_once(10 + i), personel='L%d' % i)
    en_eski_ga = insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun_once(40), tarih=gun_once(40), personel='LX')
    insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun_once(1), tarih=gun_once(1))     # yaşı yetmez, özete girmez
    insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun_once(20), tarih=gun_once(20), kt=1)
    tg = [insert(a, proje='OF', ilk_gorulme=gun_once(5 + i), tarih=gun_once(5 + i)) for i in range(4)]
    a['HATIRLATMA_GUNLUK_SINIR'] = 2
    r = conn_uret(a)
    # Eski Excel kayıtları için kayıt başına değil, proje başına tek özet (kayit_id = en eski bekleyen); 7 kayıt sayılır.
    ozet = rows(a, "SELECT * FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma-ozet:GA:%' AND kullanici_adi='testadmin'")
    assert len(ozet) == 1 and ozet[0]['kayit_id'] == en_eski_ga and ozet[0]['tur'] == 'hatirlatma' and ozet[0]['proje'] == 'GA'
    assert ozet[0]['metin'] == "GA: 7 kayıt 3 günden uzun süredir onay bekliyor (eski Excel'den)."
    assert not rows(a, "SELECT 1 FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma:%' AND proje='GA'")
    # Telegram kayıtları: kullanıcı başına en çok 2 kayıt hatırlatması (en eskiler), kalan 2 OF özetine katlanır.
    tekil = rows(a, "SELECT kayit_id FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma:%' AND kullanici_adi='testadmin' ORDER BY kayit_id")
    assert [x['kayit_id'] for x in tekil] == sorted(tg[2:])  # en eski ikisi (yaş 8 ve 7)
    of_ozet = rows(a, "SELECT metin FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma-ozet:OF:%' AND kullanici_adi='testadmin'")
    assert len(of_ozet) == 1 and of_ozet[0]['metin'] == 'OF: 4 kayıt 3 günden uzun süredir onay bekliyor (tek tek bildirilmeyen 2).'  # sayı = bağlantının listelediği küme
    assert r['hatirlatma'] == 2 and r['ozet'] == 2 and r['sinira_katlanan'] == 2 and r['eski_excel'] == 7
    # Aynı gün tekrar → hiçbir şey eklenmez (günlük sınır gün bazlı); özet tekrar aralığına uyar (ertesi gün taşma olmadığı için yok, 3 gün sonra var).
    r2 = conn_uret(a); assert r2['ozet'] == 0 and r2['hatirlatma'] == 0
    assert conn_uret(a, bugun=date.today() + timedelta(days=1))['ozet'] == 0
    r3 = conn_uret(a, bugun=date.today() + timedelta(days=3))
    assert r3['ozet'] >= 1 and any(x['olay'].endswith((date.today() + timedelta(days=3)).isoformat()) for x in rows(a, "SELECT olay FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma-ozet:GA:%'"))
    assert hatirlatma.ozet_metni('PA', 5, 2, 3) == "PA: 5 kayıt 3 günden uzun süredir onay bekliyor (2 eski Excel'den)."


def test_hatirlatma_akista_etiket_baglanti_ve_okundu(web):
    c, a = web; login(c)
    kid = insert(a, ilk_gorulme=gun_once(4), tarih=gun_once(4), personel='HAT-1')
    insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun_once(30), tarih=gun_once(30))
    conn_uret(a)
    d = c.get('/bildirim.json').json
    hat = [x for x in d['bildirimler'] if x['tur'] == 'hatirlatma' and not x['ozet']]
    assert len(hat) == 1 and hat[0]['kayit_id'] == kid and hat[0]['etiket'] == 'Hatırlatma' and hat[0]['personel'] == 'HAT-1'
    assert hat[0]['url'] == '/kayitlar?proje=OF&durum=hepsi&ac=%d' % kid and hat[0]['metin'].startswith("Bu ID'nin kontrolü 4 gündür")
    ozet = [x for x in d['bildirimler'] if x['tur'] == 'hatirlatma' and x['ozet']]
    assert len(ozet) == 1 and ozet[0]['url'] == '/kayitlar?proje=GA&durum=bekleyen&bekleme=3' and ozet[0]['metin'].startswith('GA: 1 kayıt')
    assert 'geciken' in d['sayac']['OF'] and d['sayac']['OF']['geciken'] == 1 and d['sayac']['GA']['geciken'] == 1
    # Bildirimler sayfası: etiket, tür süzgeci, tıklanabilir satır ve hedef
    html = c.get('/bildirimler?tur=hatirlatma').data.decode()
    assert '<option value="hatirlatma" selected>Hatırlatma</option>' in html and html.count('class="bildirim-satir tiklanir') == 2
    assert 'data-bildirim-hedef="/kayitlar?proje=OF&amp;durum=hepsi&amp;ac=%d"' % kid in html and 'Bekleyenleri aç' in html and 'Kaydı aç' in html
    assert 'data-bildirim-hedef="/kayitlar?proje=GA&amp;durum=bekleyen&amp;bekleme=3"' in html
    # Okundu işaretleme korunur (m: öneki)
    assert c.post('/bildirimler/okundu', data={'csrf': csrf(c), 'id': hat[0]['bildirim_id']}).json['degisen'] == 1
    assert not [x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'hatirlatma' and not x['ozet']]
    # Ana sayfa kartı: "3 gündür bekleyen: 1" ve bağlantı; Kayıtlar bekleme filtresi aynı kaydı listeler.
    ana = c.get('/').data.decode()
    assert '3 gündür bekleyen: <b data-sayac="OF:geciken">1</b>' in ana and '/kayitlar?proje=OF&amp;durum=bekleyen&amp;bekleme=3' in ana
    liste = c.get('/kayitlar?proje=OF&durum=bekleyen&bekleme=3').data.decode()
    assert 'data-id="%d"' % kid in liste and 'en az 3 gündür bekleyen' in liste and 'name="bekleme"' in liste
    taze = insert(a, ilk_gorulme=gun_once(0), tarih=gun_once(0))
    assert 'data-id="%d"' % taze not in c.get('/kayitlar?proje=OF&durum=bekleyen&bekleme=3').data.decode()
    assert c.get('/kayitlar?durum=bekleyen&bekleme=abc').status_code == 200 and c.get('/kayitlar?durum=bekleyen&bekleme=99999').status_code == 200


def test_hatirlatma_cli_raporu_ve_kapali_arka_plan(tmp_path):
    veri = tmp_path / 'veri'
    ortam = dict(os.environ, PANEL_VERI=str(veri), GYAZO_WORKER='0', HATIRLATMA_GUN='2', HATIRLATMA_SAAT='0', GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT='0')
    kur = subprocess.run([sys.executable, '-m', 'app.cli', 'veritabani-kur'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert kur.returncode == 0, kur.stderr
    ayar = {'DB': str(veri / 'panel.db')}
    kullanicilar.ekle(ayar, 'lider', 'OF:oku,kt', 'Guclu-Parola-77')
    c = db.baglan(ayar['DB'])
    with db.transaction(c):
        c.execute("INSERT INTO kayitlar(anahtar,proje,personel,kaynak,ilk_gorulme,tarih) VALUES('x:1','OF','P1','telegram',?,?)", (gun_once(2), gun_once(2)))
    c.close()
    r = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    rapor = json.loads(r.stdout)
    assert rapor['esik_gun'] == 2 and rapor['hatirlatma'] == 1 and rapor['alici'] == 1 and rapor['kullanicilar']['lider']['hatirlatma'] == 1
    # Aynı gün yeniden çalıştırma yeni satır eklemez; ileri tarih reddedilir (gerçek günleri susturmasın diye — inceleme bulgusu).
    r2 = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--tarih', date.today().isoformat()], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r2.returncode == 0, r2.stderr
    assert json.loads(r2.stdout)['hatirlatma'] == 0
    ileri = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--tarih', (date.today() + timedelta(days=3)).isoformat()], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert ileri.returncode != 0 and 'ileri' in ileri.stderr
    hata = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--tarih', '31.12.2026'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert hata.returncode != 0 and 'YYYY-AA-GG' in hata.stderr
    assert 'hatirlatma-uret' in subprocess.run([sys.executable, '-m', 'app.cli', '--help'], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120).stdout
    # Ayar okuma: boş/geçersiz değerler varsayılana düşer; HATIRLATMA_KONTROL_DK=0 arka plan işini kapatır.
    from app import panel
    # 2.3.3: kontrol sıklığı varsayılanı 30 → 10 dk; yeni anahtarlar test_hatirlatma_233.py'de sınanır.
    ayar_sonuc = hatirlatma.ayarlar({'HATIRLATMA_GUN': 'x', 'HATIRLATMA_TEKRAR_GUN': 0, 'HATIRLATMA_GUNLUK_SINIR': None})
    assert {k: ayar_sonuc[k] for k in ('gun', 'tekrar', 'sinir', 'kontrol_dk')} == dict(gun=3, tekrar=3, sinir=50, kontrol_dk=10)
    eski = dict(panel.AYAR)
    try:
        panel.AYAR['HATIRLATMA_KONTROL_DK'] = 0; assert panel._start_hatirlatma_isi() is None
    finally:
        panel.AYAR.clear(); panel.AYAR.update(eski)
    assert "_start_web_converter();_start_hatirlatma_isi()" in (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')


# =============================================================== B. ONAYSIZ_GORUNUM
def _raporcu_ortami(a):
    account(a, 'raporcu', 'OF:oku;PA:oku,kt')  # OF'ta yalnız okuma (kural uygulanır), PA'da kt (uygulanmaz)
    onaysiz = insert(a, personel='ARA-1', uye_id='U-ARA')
    onayli = insert(a, personel='ARA-2', uye_id='U-ARA', kt=1, kt_kim='testadmin', kt_zaman=db.simdi())
    pa_onaysiz = insert(a, proje='PA', personel='PA-1')
    return onaysiz, onayli, pa_onaysiz


def test_uyar_modu_rozet_serit_arama_uyarisi_ve_cikti(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'uyar'
    onaysiz, onayli, pa_onaysiz = _raporcu_ortami(a); login(c, 'raporcu')
    for gorunum in ('tablo', 'kart', 'galeri'):
        html = c.get('/kayitlar?durum=hepsi&gorunum=' + gorunum).data.decode()
        assert html.count('ONAY YOK — raporlamada kullanmayın') == 1, gorunum   # yalnız OF'taki onaysız kayıt; PA'da kt yetkisi var
        assert 'Bekliyor</span>' in html                                          # PA kaydı normal "Bekliyor"
    d = c.get('/kayit/%d' % onaysiz, headers=XHR); assert d.status_code == 200 and d.json['onay_uyari'] is True
    assert c.get('/kayit/%d' % onayli, headers=XHR).json['onay_uyari'] is False
    assert c.get('/kayit/%d' % pa_onaysiz, headers=XHR).json['onay_uyari'] is False
    # Arama yalnız onaysız döndürüyorsa uyarı kutusu; onaylı da varsa yok.
    html = c.get('/kayitlar?durum=hepsi&q=ARA-1').data.decode()
    assert 'Aradığınız ID için onaylı kanıt yok; 1 onaysız kayıt listelendi.' in html
    html = c.get('/kayitlar?durum=hepsi&q=U-ARA').data.decode()
    assert 'onaylı kanıt yok' not in html and 'ONAY YOK' in html
    assert 'onaylı kanıt yok' not in c.get('/kayitlar?durum=hepsi&q=PA-1').data.decode()
    # Çıktı: "Takım lideri onayı" sütunu (Onaylı / YOK), özet satırı ve dosya adında onaysız sayısı.
    r = c.get('/disa-aktar.xlsx?durum=hepsi&proje=OF'); assert r.status_code == 200
    assert 'kanit-kayitlari-OF-hepsi-ONAYSIZ-1.xlsx' in r.headers['Content-Disposition']  # 2.4.0: ad süzgeçlerden kurulur
    wb = openpyxl.load_workbook(io.BytesIO(r.data)); ws = wb['Kayıtlar']; hdr = [x.value for x in ws[1]]
    assert hdr.index('Takım lideri onayı') == hdr.index('Durum') + 1
    satirlar = {row[hdr.index('Kayıt ID')]: row[hdr.index('Takım lideri onayı')] for row in ws.iter_rows(min_row=2, values_only=True)}
    assert satirlar[onaysiz] == 'YOK' and satirlar[onayli] == 'Onaylı'
    ozet = list(wb['Proje özeti'].iter_rows(values_only=True))
    assert ozet[0] == ('Proje', 'Kayıt', 'KT onaylı', 'KT bekleyen') and ozet[1] == ('OF', 2, 1, 1) and ozet[-1][0].startswith('Takım lideri onayı YOK') and ozet[-1][1] == 1
    # Yalnız onaylı seçiminde dosya adı normal; etiketler istenen adlarla.
    assert c.get('/disa-aktar.xlsx?durum=onayli&proje=OF').headers['Content-Disposition'].endswith('kanit-kayitlari-OF-onayli.xlsx')
    form = c.get('/disa-aktar').data.decode()
    for etiket in ('>Hepsi<', '>Onaylılar<', '>Onaysızlar (onay bekleyen)<', '>Silinenler<'):
        assert etiket in form, etiket
    assert 'value="bekleyen"' in form and 'Onay bekleyen kayıtlar size gösterilmez' not in form
    # Şablon/JS/CSS kablolaması
    kayit_html = c.get('/kayitlar?durum=hepsi').data.decode()
    assert 'id="m-onay-yok"' in kayit_html and 'Bu kaydın takım lideri onayı yok; raporlamaya alınamaz.' in kayit_html
    js = (STATIC / 'panel.js').read_text(encoding='utf-8'); css = (STATIC / 'kayit.css').read_text(encoding='utf-8')
    assert "classList.toggle('gizli',!k.onay_uyari)" in js and '.durum-rozet.onay-yok' in css and '.onay-yok-serit' in css


def test_uyar_modu_kt_yetkili_kullanici_etkilenmez(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'uyar'; onaysiz, onayli, pa_onaysiz = _raporcu_ortami(a); login(c)
    html = c.get('/kayitlar?durum=hepsi&q=ARA-1').data.decode()
    assert 'ONAY YOK' not in html and 'onaylı kanıt yok' not in html and 'Bekliyor</span>' in html
    assert c.get('/kayit/%d' % onaysiz, headers=XHR).json['onay_uyari'] is False
    r = c.get('/disa-aktar.xlsx?durum=hepsi&proje=OF')
    assert r.headers['Content-Disposition'].endswith('kanit-kayitlari-OF-hepsi.xlsx')
    hdr = [x.value for x in openpyxl.load_workbook(io.BytesIO(r.data))['Kayıtlar'][1]]; assert 'Takım lideri onayı' in hdr and 'KT' not in hdr and len(hdr) == 29  # eski KT sütununun yerini aldı


def test_gizle_modu_liste_arama_ayrinti_gorsel_cikti_profil(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'gizle'
    onaysiz, onayli, pa_onaysiz = _raporcu_ortami(a)
    silinmis = insert(a, personel='SIL-1', kt=1, silindi=1)
    tg_onaysiz = insert(a, personel='TG-1', ekleyen_id='4242', ekleyen_ad='Tg', ekleyen_guven='telegram')
    tg_onayli = insert(a, personel='TG-2', ekleyen_id='4242', ekleyen_ad='Tg', ekleyen_guven='telegram', kt=1)
    login(c, 'raporcu')
    # Liste: OF'ta yalnız onaylı; PA (kt yetkili) onaysızı görünür. Sekmeler karışık seçimde kalır, not gösterilir.
    html = c.get('/kayitlar?durum=hepsi').data.decode()
    assert 'data-id="%d"' % onayli in html and 'data-id="%d"' % pa_onaysiz in html
    for kid in (onaysiz, silinmis, tg_onaysiz): assert 'data-id="%d"' % kid not in html, kid
    assert 'Onay bekleyen kayıtlar size gösterilmez.' in html and 'id="sayac-bekleyen"' in html
    # Yalnız OF seçiliyse durum onaylıya sabitlenir, yalnız Onaylı sekmesi kalır, arama onaysızı bulmaz.
    html = c.get('/kayitlar?proje=OF&durum=bekleyen').data.decode()
    assert 'id="sayac-onayli"' in html and 'id="sayac-bekleyen"' not in html and 'id="sayac-hepsi"' not in html and 'data-id="%d"' % onayli in html
    html = c.get('/kayitlar?proje=OF&durum=hepsi&q=ARA-1').data.decode()
    assert 'data-id="%d"' % onaysiz not in html and 'onaylı kanıt yok' not in html and 'ONAY YOK' not in html
    # Ayrıntı ve görsel: 404 değil 403, açıklayıcı metin; onaylı açılır; PA onaysız (kt var) açılır.
    r = c.get('/kayit/%d' % onaysiz, headers=XHR)
    assert r.status_code == 403 and r.json['hata'] == 'Bu kaydın onayı yok; yalnız onaylı kayıtlar gösterilir.' and r.json['neden'] == 'onay_yok'
    assert c.get('/kucuk/%d' % onaysiz).status_code == 403 and c.get('/gorsel/%d' % onaysiz).status_code == 403
    assert c.get('/kayit/%d' % silinmis, headers=XHR).status_code == 403
    assert c.get('/kayit/%d' % onayli, headers=XHR).status_code == 200 and c.get('/kayit/%d' % pa_onaysiz, headers=XHR).status_code == 200
    assert c.get('/kayit/%d' % onaysiz).status_code == 403  # tarayıcı sayfası da 403 (404 değil)
    # Çıktı: onaysız satır yok, bekleyen seçeneği yok, not var; dosya adı normal.
    r = c.get('/disa-aktar.xlsx?durum=hepsi&proje=OF'); ws = openpyxl.load_workbook(io.BytesIO(r.data))['Kayıtlar']; hdr = [x.value for x in ws[1]]
    ids = [row[hdr.index('Kayıt ID')] for row in ws.iter_rows(min_row=2, values_only=True)]
    assert ids == sorted(ids) and onaysiz not in ids and tg_onaysiz not in ids and onayli in ids and r.headers['Content-Disposition'].endswith('kanit-kayitlari-OF-onayli.xlsx')  # gizle: durum onaylıya sabit
    r = c.get('/disa-aktar.xlsx?durum=bekleyen&proje=OF'); ws = openpyxl.load_workbook(io.BytesIO(r.data))['Kayıtlar']
    assert [row[0] for row in ws.iter_rows(min_row=2, values_only=True)] == sorted([onayli, tg_onayli])  # bekleyen isteği onaylıya sabitlenir
    form = c.get('/disa-aktar').data.decode(); assert 'Onay bekleyen kayıtlar size gösterilmez' in form and 'value="bekleyen"' in form  # PA'da kt var → seçenekler kalır
    # Ekleyen profili: onaysız Telegram kaydı sayılmaz ve listelenmez.
    prof = c.get('/telegram/kullanici/4242/kanitlar').data.decode()
    assert '#%d aç' % tg_onayli in prof and '#%d aç' % tg_onaysiz not in prof
    # Kanıt Kontrolü: onaysız kayıt eşleşme adayı olmaz.
    from app import excel_check
    con = db.baglan(a['DB'])
    try:
        csv = Path(a['BOT_KLASOR']) / 'kontrol.csv'; csv.write_text('personel\nTG-1\nTG-2\n', encoding='utf-8')
        rep = excel_check.check_source(csv, con, ['OF'], {'header_row': 1, 'columns': {'personel': 'A'}, 'match_fields': ['personel'], 'kt': 'hepsi'}, onayli_zorunlu=['OF'])
        durumlar = {row['values']['personel']: row['status'] for row in rep['rows']}
        assert durumlar['TG-2'] == 'bulundu' and durumlar['TG-1'] == 'yok'
    finally: con.close()
    logout(c)
    # kt yetkili kullanıcı (süperadmin) her şeyi görür.
    login(c); html = c.get('/kayitlar?proje=OF&durum=hepsi').data.decode()
    assert 'data-id="%d"' % onaysiz in html and 'size gösterilmez' not in html and c.get('/kayit/%d' % onaysiz, headers=XHR).status_code == 200


def test_gizle_modu_yalniz_okuma_kullanicisi_cikti_formu_ve_yetkisiz_proje(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'gizle'; account(a, 'okur', 'OF:oku'); insert(a, personel='X', kt=1); insert(a, personel='Y')
    login(c, 'okur')
    form = c.get('/disa-aktar').data.decode()
    assert 'value="bekleyen"' not in form and 'value="silinen"' not in form and 'value="onayli"' in form and 'Onay bekleyen kayıtlar size gösterilmez' in form
    html = c.get('/kayitlar').data.decode()
    assert 'id="sayac-onayli"' in html and 'id="sayac-bekleyen"' not in html and html.count('class="kayit ') == 1
    assert c.get('/kayit/%d' % insert(a, proje='PA', personel='Z'), headers=XHR).status_code == 403   # yetkisiz proje önce 403 (yetki)


# =============================================================== C. Bildirimden doğrudan hedefe
def test_yorum_bildirimi_yorum_id_ve_hedef_baglanti(web):
    c, a = web; account(a, 'ofadmin', 'OF:oku,kt'); login(c); kid = seed(a)
    q = c.post('/kayit/%d/yorum' % kid, data={'csrf': csrf(c), 'yorum': 'Soru var', 'alici': 'ofadmin'}).json['yorum_id']
    logout(c); login(c, 'ofadmin')
    d = c.get('/bildirim.json').json
    soru = next(x for x in d['bildirimler'] if x['tur'] == 'soru')
    assert soru['yorum_id'] == q and soru['url'] == '/kayitlar?proje=OF&durum=hepsi&ac=%d&yorum=%d' % (kid, q) and soru['etiket'] == 'Soru'
    kanit = next(x for x in d['bildirimler'] if x['tur'] == 'kanit')
    assert kanit['yorum_id'] is None and kanit['url'] == '/kayitlar?proje=OF&durum=hepsi&ac=%d' % kid and kanit['etiket'] == 'Yeni kanıt'
    html = c.get('/bildirimler').data.decode()
    assert 'data-bildirim-hedef="/kayitlar?proje=OF&amp;durum=hepsi&amp;ac=%d&amp;yorum=%d"' % (kid, q) in html and 'Yorumu aç' in html and 'Yorum #%d' % q in html
    # Kayıtlar sayfası: ac+yorum veri öznitelikleri; sekme/sayfa bağlantıları ac ve yorum taşımaz.
    sayfa = c.get('/kayitlar?proje=OF&durum=hepsi&ac=%d&yorum=%d' % (kid, q)).data.decode()
    assert 'data-acik="%d"' % kid in sayfa and 'data-yorum="%d"' % q in sayfa
    for m in re.finditer(r'href="(/kayitlar\?[^"]*)"', sayfa):
        assert 'ac=' not in m.group(1) and 'yorum=' not in m.group(1), m.group(1)
    assert 'data-yorum=' not in c.get('/kayitlar?durum=hepsi&yorum=%d' % q).data.decode()      # ac olmadan yorum yok sayılır
    assert c.get('/kayitlar?durum=hepsi&ac=%d&yorum=abc' % kid).status_code == 200
    # Yanıt bildirimi de yorum_id taşır; kayıt listede olmasa da (başka durum sekmesi) ac ile modal açılır — JS tarafı.
    assert c.post('/kayit/%d/yorum' % kid, data={'csrf': csrf(c), 'yorum': 'Yanıt', 'yanit_id': q}).json['ok']
    logout(c); login(c)
    yanit = next(x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'yanit')
    assert yanit['yorum_id'] and '&yorum=%d' % yanit['yorum_id'] in yanit['url']
    js = (STATIC / 'panel.js').read_text(encoding='utf-8')
    for parca in ("function yorumVurgula()", "classList.add('vurgu')", "data-notify-hedef", "data-bildirim-hedef", "hatirlatma:'Hatırlatma'", "'Bekleyenleri aç'", "if(bekleyenYorum&&String(k.id)===String(ilkAc))yorumVurgula();"):
        assert parca in js, parca
    assert '.yorum-listesi li.vurgu' in (STATIC / 'kayit.css').read_text(encoding='utf-8')
    assert 'li.tiklanir' in (STATIC / 'stil.css').read_text(encoding='utf-8')


def test_bildirim_gecmisi_filtre_sql_ve_onay_bildirimi_hedefi(web):
    from app import panel, bildirim_gecmisi
    c, a = web; a['BILDIRIM_ONAY'] = '1'  # 2.4.0: onay bildirimi isteğe bağlı (varsayılan kapalı)
    account(a, 'ofadmin', 'OF:oku,kt'); login(c); kid = seed(a)
    assert c.post('/kayit/%d/kt' % kid, data={'csrf': csrf(c)}).json['ok']
    logout(c); login(c, 'ofadmin')
    onay = next(x for x in c.get('/bildirim.json').json['bildirimler'] if x['tur'] == 'onay')
    assert onay['yorum_id'] is None and onay['url'] == '/kayitlar?proje=OF&durum=hepsi&ac=%d' % kid and onay['etiket'] == 'Onay'
    con = db.baglan(a['DB'])
    try:
        veri = bildirim_gecmisi.liste(con, 'ofadmin', ['OF'], {'tur': 'onay'})
        assert veri['bildirimler'][0]['olay'].startswith('onay:%d:' % kid) and veri['bildirimler'][0]['ozet'] is False
        assert bildirim_gecmisi.liste(con, 'ofadmin', [], {})['bildirimler'] == []
    finally: con.close()
    # _filtre_sql: bekleme ve gizle koşulları parametre sırasını bozmaz (proje listesi başta).
    with panel.app.test_request_context('/kayitlar'):
        panel.g.yk = yetki.coz('OF:oku;PA:oku,kt'); panel.g.k = {'kullanici_adi': 'x'}
        a['ONAYSIZ_GORUNUM'] = 'gizle'
        w, p, f = panel._filtre_sql(MultiDict([('durum', 'hepsi'), ('bekleme', '5')]), ['OF', 'PA'])
        assert p[:2] == ['OF', 'PA'] and f['bekleme'] == 5 and f['kt_yok'] == ['OF'] and f['gizli_onaysiz'] and not f['yalniz_onayli']
        assert 'NOT (proje IN (?) AND (kt=0 OR silindi=1))' in w and 'julianday' in w and p[2] == 'OF' and p[3] == 5
        w, p, f = panel._filtre_sql(MultiDict([('proje', 'OF'), ('durum', 'bekleyen')]), ['OF', 'PA'])
        assert f['yalniz_onayli'] and f['durum'] == 'onayli' and 'kt=1 AND silindi=0' in w
        a['ONAYSIZ_GORUNUM'] = 'uyar'
        w, p, f = panel._filtre_sql(MultiDict([('durum', 'bekleyen')]), ['OF', 'PA'])
        assert not f['gizli_onaysiz'] and f['kt_yok'] == ['OF'] and 'NOT IN' not in w and f['durum'] == 'bekleyen'
