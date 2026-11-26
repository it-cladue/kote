"""2.3.1 bağımsız inceleme sonrası regresyonlar (inc231: hatirlatma/guvenlik/arayuz/uyum bulguları).
Düzeltmeden önce çalıştırıldığında başarısız olan testler = bulguların yeniden üretimi (notlar: 'İnceleme sonrası düzeltmeler')."""
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from app import db, kullanicilar, hatirlatma
from test_web import web, seed, login, csrf  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
XHR = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def gun(n):
    return (date.today() - timedelta(days=n)).strftime('%Y-%m-%d 10:00:00')


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'inc:' + str(time.time_ns())); cols.setdefault('kaynak', 'telegram')
    cols.setdefault('personel', 'P' + str(time.time_ns())[-5:])
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def rows(a, sql, *params):
    c = db.baglan(a['DB'])
    try: return [dict(r) for r in c.execute(sql, params)]
    finally: c.close()


def uret(a, **kw):
    # 2.3.3 adımları (2 saat, gün sonu) burada kapalı: bu dosya yalnız 3 gün kuralını sınar (test_hatirlatma_233.py ayrı sınar).
    c = db.baglan(a['DB'])
    try: return hatirlatma.uret(c, dict(a, HATIRLATMA_SAAT=0, GUN_SONU_SAAT='', BEKLEYEN_OZET_SAAT=0), **kw)
    finally: c.close()


def bugunku(a, ad, gun_s=None):
    gun_s = gun_s or date.today().isoformat()
    return rows(a, "SELECT COUNT(*) n FROM mesaj_bildirimleri WHERE kullanici_adi=? AND tur='hatirlatma' AND olay LIKE 'hatirlatma:%' AND substr(olay,-10)=?", ad, gun_s)[0]['n']


def logout(c):
    c.post('/cikis', data={'csrf': csrf(c)})


# ---- 1. [YÜKSEK] HATIRLATMA_GUNLUK_SINIR gün bazlı: aynı gün tekrar 0 satır, 48 çağrı ≤ sınır, ertesi gün yeniden ≤ sınır
def test_gunluk_sinir_gun_bazli_ve_sel_benzetimi(web):
    c, a = web; account(a, 'lider', 'OF:oku,kt'); a['HATIRLATMA_GUNLUK_SINIR'] = 2
    ids = [insert(a, ilk_gorulme=gun(5 + i), tarih=gun(5 + i), personel='T%d' % i) for i in range(4)]
    r1 = uret(a)
    assert r1['hatirlatma'] == 4 and r1['sinira_katlanan'] == 4 and r1['ozet'] == 2  # 2 kayıt × 2 alıcı; kalan 2'şer kayıt proje özetine
    assert bugunku(a, 'lider') == 2 and bugunku(a, 'testadmin') == 2
    ozet = rows(a, "SELECT metin FROM mesaj_bildirimleri WHERE kullanici_adi='lider' AND olay LIKE 'hatirlatma-ozet:OF:%'")
    assert len(ozet) == 1 and ozet[0]['metin'] == 'OF: 4 kayıt 3 günden uzun süredir onay bekliyor (tek tek bildirilmeyen 2).'
    # Aynı gün ikinci çalıştırma (sınırı aşan kayıt varken de) hiç satır eklemez.
    once = rows(a, 'SELECT COUNT(*) n FROM mesaj_bildirimleri')[0]['n']
    r2 = uret(a)
    assert r2['hatirlatma'] == 0 and r2['ozet'] == 0 and rows(a, 'SELECT COUNT(*) n FROM mesaj_bildirimleri')[0]['n'] == once
    # Sel benzetimi: 48 çağrı (30 dk'lık iş parçacığının bir günü) → kullanıcı başına bugün en çok sınır kadar.
    for _ in range(48):
        uret(a)
    assert bugunku(a, 'lider') == 2 and bugunku(a, 'testadmin') == 2 and rows(a, 'SELECT COUNT(*) n FROM mesaj_bildirimleri')[0]['n'] == once
    # Ertesi gün: henüz hatırlatılmamış 2 kayıt sırada (adil sıra), yine en çok 2; özet o gün yeniden (günde en çok bir).
    yarin = date.today() + timedelta(days=1)
    r3 = uret(a, bugun=yarin)
    assert r3['hatirlatma'] == 4 and bugunku(a, 'lider', yarin.isoformat()) == 2
    yarin_kayitlar = {x['kayit_id'] for x in rows(a, "SELECT kayit_id FROM mesaj_bildirimleri WHERE kullanici_adi='lider' AND olay LIKE 'hatirlatma:%:'||?", yarin.isoformat())}
    bugun_kayitlar = {x['kayit_id'] for x in rows(a, "SELECT kayit_id FROM mesaj_bildirimleri WHERE kullanici_adi='lider' AND olay LIKE 'hatirlatma:%:'||?", date.today().isoformat())}
    assert yarin_kayitlar.isdisjoint(bugun_kayitlar) and yarin_kayitlar | bugun_kayitlar == set(ids)
    for _ in range(10):
        uret(a, bugun=yarin)
    assert bugunku(a, 'lider', yarin.isoformat()) == 2
    # Sınır günlük olduğu için ayarlar raporda 'gunluk_sinir' adıyla; CLI yardımı 'günlük' der.
    assert r1['gunluk_sinir'] == 2
    assert 'gün' in subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--help'], cwd=str(ROOT), env=dict(os.environ, PANEL_VERI=str(Path(a['BOT_KLASOR']) / 'cli'), GYAZO_WORKER='0'), capture_output=True, text=True, timeout=120).stdout


def test_adil_sira_ve_ozet_sayisi_baglantiyla_ayni(web):
    c, a = web; a['HATIRLATMA_GUNLUK_SINIR'] = 50
    for i in range(120):
        insert(a, ilk_gorulme=gun(4 + (i % 7)), tarih=gun(4 + (i % 7)), personel='F%03d' % i)
    for i in range(3):
        insert(a, kaynak='legacy_excel', ilk_gorulme=gun(30), tarih=gun(30), personel='L%d' % i)
    gunler = [date.today() + timedelta(days=n) for n in range(0, 3)]
    for g in gunler:
        uret(a, bugun=g)
    hatirlatilan = {x['kayit_id'] for x in rows(a, "SELECT DISTINCT kayit_id FROM mesaj_bildirimleri WHERE kullanici_adi='testadmin' AND olay LIKE 'hatirlatma:%'")}
    assert len(hatirlatilan) == 120  # 3 günde 3×50 kota → her Telegram kaydı en az bir kez tek tek hatırlatıldı
    ozetler = rows(a, "SELECT olay,metin FROM mesaj_bildirimleri WHERE kullanici_adi='testadmin' AND olay LIKE 'hatirlatma-ozet:OF:%' ORDER BY olay")
    # 1. ve 2. gün taşma var → günde bir özet; 3. gün kalan 20 kayıt kotaya sığar, eski Excel özeti de tekrar aralığında → özet yok.
    assert len(ozetler) == 2
    assert ozetler[0]['metin'] == 'OF: 123 kayıt 3 günden uzun süredir onay bekliyor (3 eski Excel\'den; tek tek bildirilmeyen 70).'
    assert ozetler[1]['metin'] == 'OF: 123 kayıt 3 günden uzun süredir onay bekliyor (3 eski Excel\'den; tek tek bildirilmeyen 20).'
    # 4. gün: ilk günün 50'si yeniden sıraya girer (3 günlük tekrar), kota 50 → taşma yok; son özet (eski Excel sayısını da veren)
    # 2. gündeydi → tekrar aralığı dolmadı, özet yok. 5. gün: özet tekrar aralığı doldu → eski Excel özeti yeniden üretilir.
    r4 = uret(a, bugun=date.today() + timedelta(days=3)); assert r4['hatirlatma'] == 50 and r4['ozet'] == 0 and r4['sinira_katlanan'] == 0
    r5 = uret(a, bugun=date.today() + timedelta(days=4)); assert r5['hatirlatma'] == 50 and r5['ozet'] == 1 and r5['sinira_katlanan'] == 0
    # Özet sayısı, bağlantının listelediği kümeyle (projede ≥3 gündür bekleyen tüm onaysızlar) aynı.
    login(c); html = c.get('/kayitlar?proje=OF&durum=bekleyen&bekleme=3').data.decode()
    assert '<b>123</b> kayıt' in html


# ---- 2. [ORTA] gizle: İşlem Geçmişi, Son işlemler, bildirim akışı ve kategori listesi onaysız kaydı göstermez
def test_gizle_denetim_son_islemler_akis_ve_kategori(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'gizle'; a['BILDIRIM_ONAY'] = '1'; account(a, 'raporcu', 'OF:oku'); account(a, 'eskilider', 'OF:oku,kt')
    gizli = seed(a, 'OF', 'gz:1'); acik = insert(a, personel='ACIK', kt=1, kategori='HGST')
    gizli_kat = insert(a, personel='GIZLIKAT', kategori='YALNIZGIZLIKAT')
    login(c)
    assert c.post('/kayit/%d/yorum' % gizli, data={'csrf': csrf(c), 'yorum': 'GIZLI YORUM METNI', 'alici': 'eskilider'}).json['ok']
    assert c.post('/kayit/%d/kt' % acik, data={'csrf': csrf(c), 'deger': '0'}).status_code in (200, 400)  # acik için denetim satırı
    assert c.post('/kayit/%d/kt' % acik, data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    logout(c); login(c, 'raporcu')
    for url in ('/', '/denetim', '/denetim?q=gz'):
        html = c.get(url).data.decode()
        assert 'Kayıt #%d' % gizli not in html and 'GIZLI YORUM METNI' not in html and 'ac=%d' % gizli not in html, url
        assert 'Kayıt #%d' % gizli_kat not in html, url
    assert 'Kayıt #%d' % acik in c.get('/denetim').data.decode()
    assert 'YALNIZGIZLIKAT' not in c.get('/kategoriler.json?proje=OF').json['kategoriler'] and 'HGST' in c.get('/kategoriler.json?proje=OF').json['kategoriler']
    assert 'YALNIZGIZLIKAT' not in c.get('/kayitlar?durum=hepsi').data.decode()
    logout(c)
    # kt→oku düşürülen kullanıcı: onaysız kaydın eski bildirimleri (yeni kanıt, yorum) akışta görünmez ve okunmamışa sayılmaz;
    # onaylı kaydın (acik) onay bildirimleri görünür kalır.
    kullanicilar.guncelle(a, 'eskilider', yetki='OF:oku'); login(c, 'eskilider')
    d = c.get('/bildirim.json').json
    assert {x['kayit_id'] for x in d['bildirimler']} == {acik} and d['okunmamis'] == len(d['bildirimler'])
    assert 'GIZLI YORUM METNI' not in c.get('/bildirimler').data.decode() and 'Kayıt #%d' % gizli not in c.get('/bildirimler').data.decode()
    logout(c); login(c)  # süperadmin her şeyi görür
    assert 'GIZLI YORUM METNI' in c.get('/denetim').data.decode() and 'YALNIZGIZLIKAT' in c.get('/kategoriler.json?proje=OF').json['kategoriler']


# ---- 3. [ORTA] gizle: ana sayfa / zil sayaçları gizlenen sayıları sızdırmaz, bağlantılar Onaylı listesine düşmez
def test_gizle_ana_sayfa_ve_zil_sayaclari(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'gizle'; account(a, 'raporcu', 'OF:oku'); account(a, 'karma', 'OF:oku;PA:oku,kt')
    for i in range(2): insert(a, ilk_gorulme=gun(5), tarih=gun(5), personel='B%d' % i)
    onayli = insert(a, personel='ON', kt=1, ilk_gorulme=gun(9), tarih=gun(9)); insert(a, personel='SIL', silindi=1)
    insert(a, proje='PA', personel='PB', ilk_gorulme=gun(5), tarih=gun(5))
    login(c, 'raporcu'); html = c.get('/').data.decode()
    assert 'data-sayac="OF:geciken" hidden>0<' in html and 'data-sayac="OF:bekleyen">0<' in html and 'data-sayac="OF:silinen">0<' in html and 'data-sayac="OF:toplam">1<' in html
    assert 'data-kpi="bekleyen">0<' in html and 'Onay bekleyenleri aç' not in html and 'durum=bekleyen' not in html and 'bekleme=3' not in html
    assert 'Onay bekleyen kayıtlar size gösterilmez' in html
    sayac = c.get('/bildirim.json').json['sayac']['OF']
    assert sayac == {'bekleyen': 0, 'onayli': 1, 'silinen': 0, 'toplam': 1, 'geciken': 0}
    # Onaylıya sabitlenen listede bekleme yok sayılır (onaylı kayıt 'bekleyen' diye süzülmez), 'en az N gündür bekleyen' metni yok.
    html = c.get('/kayitlar?proje=OF&durum=bekleyen&bekleme=3').data.decode()
    assert 'data-id="%d"' % onayli in html and 'en az 3 gündür bekleyen' not in html
    logout(c); login(c, 'karma'); html = c.get('/').data.decode()
    assert 'data-sayac="OF:bekleyen">0<' in html and 'data-sayac="PA:bekleyen">1<' in html and 'data-sayac="PA:geciken">1<' in html and 'data-kpi="bekleyen">1<' in html
    assert 'proje=PA&amp;durum=bekleyen&amp;bekleme=3' in html and 'proje=OF&amp;durum=bekleyen' not in html and 'Onay bekleyenleri aç' in html
    logout(c); a['ONAYSIZ_GORUNUM'] = 'uyar'; login(c, 'raporcu'); html = c.get('/').data.decode()
    assert 'data-sayac="OF:bekleyen">2<' in html and 'data-sayac="OF:geciken">2<' in html  # uyar modunda sayılar görünür


# ---- 4. [ORTA] onaylanan / silinen kaydın hatırlatması akıştan düşer ve okundu olur
def test_onaylanan_ve_silinen_kaydin_hatirlatmasi_duser(web):
    c, a = web; login(c)
    k1 = insert(a, ilk_gorulme=gun(5), tarih=gun(5), personel='H1'); k2 = insert(a, ilk_gorulme=gun(6), tarih=gun(6), personel='H2'); k3 = insert(a, ilk_gorulme=gun(7), tarih=gun(7), personel='H3')
    insert(a, proje='GA', kaynak='legacy_excel', ilk_gorulme=gun(40), tarih=gun(40))
    uret(a)
    d = c.get('/bildirim.json').json; once = d['okunmamis']
    assert {x['kayit_id'] for x in d['bildirimler'] if x['tur'] == 'hatirlatma' and not x['ozet']} == {k1, k2, k3}
    assert c.post('/kayit/%d/kt' % k1, data={'csrf': csrf(c), 'deger': '1'}).json['ok']
    assert c.post('/kayit/%d/sil' % k2, data={'csrf': csrf(c)}).json['ok']
    d = c.get('/bildirim.json').json
    assert {x['kayit_id'] for x in d['bildirimler'] if x['tur'] == 'hatirlatma' and not x['ozet']} == {k3} and d['okunmamis'] == once - 2
    assert all(x['okundu'] == 1 for x in rows(a, "SELECT okundu FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma:%' AND kayit_id IN (?,?)", k1, k2))
    assert any(x['ozet'] for x in d['bildirimler'])  # özet satırı etkilenmez
    html = c.get('/bildirimler?tur=hatirlatma').data.decode()
    assert 'Kayıt #%d' % k1 not in html and 'Kayıt #%d' % k3 in html
    # Onay kaldırılınca kayıt yeniden bekler: 3 gün sonra tekrar hatırlatılır.
    assert c.post('/kayit/%d/kt' % k1, data={'csrf': csrf(c), 'deger': '0'}).json['ok']
    assert any(x['kayit_id'] == k1 for x in rows(a, "SELECT kayit_id FROM mesaj_bildirimleri WHERE olay LIKE 'hatirlatma:%:'||?", (date.today() + timedelta(days=3)).isoformat())) is False
    uret(a, bugun=date.today() + timedelta(days=3))
    assert rows(a, "SELECT COUNT(*) n FROM mesaj_bildirimleri WHERE kayit_id=? AND olay LIKE 'hatirlatma:%:'||?", k1, (date.today() + timedelta(days=3)).isoformat())[0]['n'] == 1


# ---- 5. [ORTA] --tarih ileri tarih reddedilir; ileri tarihli anahtar gerçek günleri susturmaz
def test_ileri_tarih_reddi_ve_susturmama(web, tmp_path):
    c, a = web; kid = insert(a, ilk_gorulme=gun(5), tarih=gun(5))
    yarin = (date.today() + timedelta(days=1)).isoformat()
    ortam = dict(os.environ, PANEL_VERI=str(tmp_path / 'veri'), GYAZO_WORKER='0')
    r = subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--tarih', yarin], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and 'ileri' in r.stderr
    assert subprocess.run([sys.executable, '-m', 'app.cli', 'hatirlatma-uret', '--tarih', date.today().isoformat()], cwd=str(ROOT), env=ortam, capture_output=True, text=True, timeout=120).returncode == 0
    # Yanlışlıkla yazılmış ileri tarihli anahtar (ör. eski sürüm) bugünkü üretimi engellemez.
    con = db.baglan(a['DB'])
    with db.transaction(con):
        con.execute("INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES('testadmin',?,'OF',?,'hatirlatma','sistem','x',?)", (kid, 'hatirlatma:%d:%s' % (kid, (date.today() + timedelta(days=10)).isoformat()), db.simdi()))
    con.close()
    assert uret(a)['hatirlatma'] == 1 and bugunku(a, 'testadmin') == 1


# ---- 6. [ORTA] uyar: 'Onay bekleyen' sekmesindeki arama, onaylı kanıt başka sekmede varken 'onaylı kanıt yok' demez
def test_uyar_arama_uyarisi_sekmeden_bagimsiz(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'uyar'; account(a, 'raporcu', 'OF:oku')
    insert(a, personel='A1', uye_id='U-77', kt=1); insert(a, personel='A2', uye_id='U-77'); insert(a, personel='A3', uye_id='U-99'); insert(a, personel='A4', uye_id='U-55', silindi=1)
    login(c, 'raporcu')
    html = c.get('/kayitlar?durum=bekleyen&q=U-77').data.decode()
    assert 'Aradığınız ID için onaylı kanıt yok' not in html and 'Onaylı sekmesinde 1 onaylı kayıt var' in html
    assert 'Aradığınız ID için onaylı kanıt yok; 1 onaysız kayıt listelendi.' in c.get('/kayitlar?durum=hepsi&q=U-99').data.decode()
    assert 'Aradığınız ID için onaylı kanıt yok; 1 onaysız kayıt listelendi.' in c.get('/kayitlar?durum=bekleyen&q=U-99').data.decode()
    assert 'onaylı kanıt yok' not in c.get('/kayitlar?durum=hepsi&q=U-77').data.decode()
    # Silinmiş kayıt 'onaysız' sayılmaz: rozet yok, uyarı yok, Excel'de 'Silindi', özet/dosya adı silinmişi saymaz.
    html = c.get('/kayitlar?durum=hepsi&q=U-55').data.decode()
    assert 'ONAY YOK' not in html and 'onaylı kanıt yok' not in html
    import io, openpyxl
    r = c.get('/disa-aktar.xlsx?durum=hepsi&proje=OF'); assert 'kanit-kayitlari-OF-hepsi-ONAYSIZ-2.xlsx' in r.headers['Content-Disposition']
    wb = openpyxl.load_workbook(io.BytesIO(r.data)); ws = wb['Kayıtlar']; hdr = [x.value for x in ws[1]]
    assert {row[hdr.index('Personel')]: row[hdr.index('Takım lideri onayı')] for row in ws.iter_rows(min_row=2, values_only=True)}['A4'] == 'Silindi'
    assert list(wb['Proje özeti'].iter_rows(values_only=True))[-1][1] == 2


# ---- 7. [ORTA, uyum] SURUM 2.3.1 ve statik dosya sürümü şablonlarda SURUM'dan
def test_surum_ve_statik_surum_parametresi(web):
    # 2.3.2-inc: sabit '2.3.1' yerine panel.SURUM (tek kaynak); sürüm atlatmalarında test kendiliğinden güncel kalır.
    from app import panel
    c, a = web; login(c)
    S = panel.SURUM
    assert re.fullmatch(r'2\.\d+\.\d+', S) and S != '2.3.1' and c.get('/saglik').headers['X-Kanit-Paneli'] == S
    for url, beklenen in (('/', (f'stil.css?v={S}', f'panel.js?v={S}', f'tema.js?v={S}')), ('/kayitlar?durum=hepsi', (f'kayit.css?v={S}',)), ('/yonetim/katalog', (f'katalog.js?v={S}',))):
        html = c.get(url).data.decode()
        for b in beklenen: assert b in html and 'v=2.3.0' not in html, (url, b)
    logout(c); giris = c.get('/giris').data.decode(); assert f'stil.css?v={S}' in giris and f'tema.js?v={S}' in giris
    for name in ('base.html', 'giris.html', 'katalog.html', 'kayitlar.html'):
        metin = (ROOT / 'app' / 'templates' / name).read_text(encoding='utf-8')
        assert "v='2.3" not in metin and 'v=SURUM' in metin, name


# ---- düşük/bilgi: ayar değerleri, boş ilk_gorulme, negatif ac, silinmiş 403 metni, bildirim satırı ayırıcı
def test_dusuk_bulgular(web):
    from app import panel, settings
    c, a = web; login(c)
    ayar_sonuc = hatirlatma.ayarlar({'HATIRLATMA_GUN': 0, 'HATIRLATMA_TEKRAR_GUN': -5, 'HATIRLATMA_GUNLUK_SINIR': 0, 'HATIRLATMA_KONTROL_DK': 10 ** 12})
    assert {k: ayar_sonuc[k] for k in ('gun', 'tekrar', 'sinir', 'kontrol_dk')} == dict(gun=3, tekrar=3, sinir=50, kontrol_dk=7 * 24 * 60)
    kid = insert(a, ilk_gorulme='', tarih=gun(5))  # boş dize NULL sayılır → tarih kullanılır
    assert uret(a)['bekleyen'] == 1 and c.get('/bildirim.json').json['sayac']['OF']['geciken'] == 1
    html = c.get('/kayitlar?durum=hepsi&ac=-1&yorum=99999999999999999999').data.decode()
    assert 'data-acik=' not in html and 'data-yorum=' not in html
    a['ONAYSIZ_GORUNUM'] = 'gizle'; account(a, 'raporcu', 'OF:oku'); silinmis = insert(a, kt=1, silindi=1)
    logout(c); login(c, 'raporcu')
    r = c.get('/kayit/%d' % silinmis, headers=XHR); assert r.status_code == 403 and r.json['neden'] == 'silindi' and 'silinmiş' in r.json['hata'] and 'proje' not in r.json
    r = c.get('/kayit/%d' % kid, headers=XHR); assert r.status_code == 403 and r.json['neden'] == 'onay_yok' and 'proje' not in r.json
    logout(c); login(c)
    html = c.get('/bildirimler?tur=hatirlatma').data.decode()
    assert '> · Personel' not in html and '<span class="kucukyazi">Personel' in html
    css = (ROOT / 'app' / 'static' / 'stil.css').read_text(encoding='utf-8')
    assert '#m-gorsel-yok { color: #cbd5e1; padding: 30px; text-align: center; line-height: 1.6; word-break: normal; overflow-wrap: anywhere; }' in css
    js = (ROOT / 'app' / 'static' / 'panel.js').read_text(encoding='utf-8')
    assert 'yeni bildirim' in js and "sqlite3" in (ROOT / 'app' / 'panel.py').read_text(encoding='utf-8')
