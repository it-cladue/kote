"""2.3.1 ek — Ekleyen profili (/telegram/kullanici/<id>/kanitlar): tarih aralığı süzgeci, özet bloğu ve kategori × tip çapraz tablosu."""
import re
import time
from datetime import date, timedelta

from app import db, kullanicilar, user_evidence
from test_web import web, login, csrf  # noqa: F401  (ortak fixture/yardımcılar)

TG = '5550001'


def account(a, name, role):
    kullanicilar.ekle(a, name, role, 'Test-Password-123!'); kullanicilar.guncelle(a, name, sifre_degistir=0)


def gun(n, saat='10:00:00'):
    return (date.today() - timedelta(days=n)).strftime('%Y-%m-%d ') + saat


def insert(a, **cols):
    cols.setdefault('proje', 'OF'); cols.setdefault('anahtar', 'pr:' + str(time.time_ns())); cols.setdefault('kaynak', 'telegram')
    cols.setdefault('ekleyen_id', TG); cols.setdefault('ekleyen_ad', 'Ekleyen'); cols.setdefault('ekleyen_guven', 'telegram')
    cols.setdefault('personel', 'P' + str(time.time_ns())[-5:])
    c = db.baglan(a['DB'])
    with db.transaction(c):
        kid = c.execute('INSERT INTO kayitlar(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', list(cols.values())).lastrowid
    c.close(); return kid


def ornek_veri(a):
    """Bugün: ARK sessiz, CVPS telesekreter, ARK (tip boş, onaylı); 3 gün önce: DDS silinmiş; 10 gün önce: CVPS Sessiz (büyük harf, PA); 40 gün önce: ARK onaylı."""
    ids = dict(
        ark_bugun=insert(a, kategori='ARK', tip='sessiz', tarih=gun(0)),
        cvps_bugun=insert(a, kategori='CVPS', tip='telesekreter', tarih=gun(0)),
        ark_onayli=insert(a, kategori='ARK', tip=None, tarih=gun(0), kt=1),
        dds_silinmis=insert(a, kategori='DDS', tip='sessiz', tarih=gun(3), silindi=1),
        cvps_pa=insert(a, proje='PA', kategori='CVPS', tip='Sessiz', tarih=gun(10)),
        ark_eski=insert(a, kategori='ARK', tip='telesekreter', tarih=gun(40), kt=1),
    )
    insert(a, ekleyen_id='9999', kategori='ARK', tip='sessiz', tarih=gun(0))  # başka ekleyen: hiçbir sayıma girmez
    return ids


def profil(a, **filters):
    c = db.baglan(a['DB'])
    try: return user_evidence.get_profile(c, TG, ['OF', 'PA'], filters, superadmin=True)
    finally: c.close()


def test_tarih_araligi_sayimlari_listeyi_ve_sekmeleri_kapsar(web):
    c, a = web; login(c); ids = ornek_veri(a)
    # Aralıksız: tüm geçmiş (6 kayıt)
    p = profil(a)
    assert p['counts'] == {'total': 6, 'outside': 1, 'pending': 3, 'approved': 2, 'deleted': 1, 'estimated': 0} and p['filters']['tarih1'] == '' and p['link_args'] == {}
    # Son 7 gün: bugünkü 3 + 3 gün önceki silinmiş = 4; liste ve proje listesi de aralığa göre.
    t1, t2 = (date.today() - timedelta(days=6)).isoformat(), date.today().isoformat()
    p = profil(a, tarih1=t1, tarih2=t2)
    assert p['counts'] == {'total': 4, 'outside': 0, 'pending': 2, 'approved': 1, 'deleted': 1, 'estimated': 0}
    assert {r['id'] for r in p['rows']} == {ids['ark_bugun'], ids['cvps_bugun'], ids['ark_onayli'], ids['dds_silinmis']} and p['projects'] == [{'proje': 'OF', 'adet': 4}]
    assert p['link_args'] == {'tarih1': t1, 'tarih2': t2}
    # Durum sekmesi + aralık birlikte: onaylı yalnız bugünkü onaylı.
    p = profil(a, tarih1=t1, tarih2=t2, kt='onayli')
    assert [r['id'] for r in p['rows']] == [ids['ark_onayli']] and p['link_args']['kt'] == 'onayli'
    # Yalnız başlangıç / yalnız bitiş
    assert profil(a, tarih1=(date.today() - timedelta(days=15)).isoformat())['counts']['total'] == 5
    assert profil(a, tarih2=(date.today() - timedelta(days=5)).isoformat())['counts']['total'] == 2
    # Sayfa: kısayollar, tarih alanları, sekme/sayfa bağlantıları aralığı taşır, özet etiketi ve sayaçlar.
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar?tarih1={t1}&tarih2={t2}').data.decode()
    for etiket in ('Son 7 gün', 'Son 30 gün', 'Bu ay', 'Tümü'):
        assert etiket in html, etiket
    assert f'value="{t1}"' in html and f'value="{t2}"' in html and 'Bu aralıkta ne eklemiş?' in html
    assert re.search(r'<b data-ozet="total">4</b>', html) and re.search(r'<b data-ozet="deleted">1</b>', html)
    sekmeler = re.findall(r'class="sekme[^"]*" href="([^"]+)"', html)
    assert len(sekmeler) == 4 and all(f'tarih1={t1}' in s and f'tarih2={t2}' in s for s in sekmeler) and any('kt=onayli' in s for s in sekmeler)
    assert '.'.join(reversed(t1.split('-'))) + ' – ' + '.'.join(reversed(t2.split('-'))) in html
    # "Son 7 gün" kısayolu aktif işaretli; "Tümü" tarihsiz bağlantı.
    assert re.search(r'class="btn kucuk birincil" href="[^"]*tarih1=' + t1 + r'[^"]*" aria-current="true">Son 7 gün', html)
    assert re.search(r'class="btn kucuk hayalet" href="/telegram/kullanici/' + TG + r'/kanitlar"[^>]*>Tümü', html)
    # Excel bağlantısı Çıktı formuna ekleyen + tarih + durum ile gider ve form önceden dolu açılır.
    m = re.search(r'id="profil-excel" href="([^"]+)"', html); assert m
    excel = m.group(1).replace('&amp;', '&')
    assert excel.startswith('/disa-aktar?') and f'ekleyen={TG}' in excel and f'tarih1={t1}' in excel and f'tarih2={t2}' in excel and 'durum=hepsi' in excel and 'proje=' not in excel
    form = c.get(excel).data.decode()
    assert f'value="{TG}"' in form and f'value="{t1}"' in form and 'value="hepsi" selected' in form
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar?project=PA&kt=bekleyen&tarih1={(date.today() - timedelta(days=15)).isoformat()}').data.decode()
    m = re.search(r'id="profil-excel" href="([^"]+)"', html); excel = m.group(1).replace('&amp;', '&')
    assert 'proje=PA' in excel and 'durum=bekleyen' in excel and 'tarih2=' not in excel
    assert c.get('/disa-aktar').status_code == 200  # parametresiz çıktı formu eskisi gibi (varsayılan 30 gün)


def test_capraz_tablo_kategori_x_tip_toplamlar_ve_proje_alt_toplamlari(web):
    c, a = web; login(c); ids = ornek_veri(a)
    cz = profil(a)['capraz']
    assert [s['kod'] for s in cz['sutunlar']] == ['sessiz', 'telesekreter', 'diger']
    satir = {r['kategori']: r for r in cz['satirlar']}
    # "Tümü" sekmesinde silinen (DDS) tabloya girmez; büyük harf 'Sessiz' sessiz sayılır; tip boş → diğer.
    assert 'DDS' not in satir and cz['silinen_haric'] is True
    assert satir['ARK'] == {'kategori': 'ARK', 'sessiz': 1, 'telesekreter': 1, 'diger': 1, 'toplam': 3}
    assert satir['CVPS'] == {'kategori': 'CVPS', 'sessiz': 1, 'telesekreter': 1, 'diger': 0, 'toplam': 2}
    assert [r['kategori'] for r in cz['satirlar']] == ['ARK', 'CVPS']  # toplamı büyük olan üstte
    assert cz['toplam'] == {'sessiz': 2, 'telesekreter': 2, 'diger': 1, 'toplam': 5}
    assert [(p['proje'], p['toplam']) for p in cz['projeler']] == [('OF', 4), ('PA', 1)]  # proje birden fazla → alt toplamlar
    # Proje süzgeci: tek proje → alt toplam satırı yok; durum sekmesi "silinen" → yalnız DDS.
    cz = profil(a, project='OF')['capraz']; assert cz['projeler'] == [] and cz['toplam']['toplam'] == 4
    cz = profil(a, kt='silinen')['capraz']
    assert [(r['kategori'], r['sessiz']) for r in cz['satirlar']] == [('DDS', 1)] and cz['silinen_haric'] is False
    # Aralık + onaylı: yalnız bugünkü ARK (tip boş)
    t1 = (date.today() - timedelta(days=6)).isoformat(); t2 = date.today().isoformat()
    cz = profil(a, tarih1=t1, tarih2=t2, kt='onayli')['capraz']
    assert cz['satirlar'] == [{'kategori': 'ARK', 'sessiz': 0, 'telesekreter': 0, 'diger': 1, 'toplam': 1}]
    # Kategorisi boş kayıt "— (kategori yok)" satırında; boş sonuçta satır yok ve toplam sıfır.
    insert(a, kategori=None, tip='sessiz', tarih=gun(0))
    cz = profil(a, tarih1=t2, tarih2=t2)['capraz']
    assert any(r['kategori'] == '— (kategori yok)' and r['sessiz'] == 1 for r in cz['satirlar'])
    assert profil(a, tarih1='2000-01-01', tarih2='2000-01-02')['capraz'] == {'satirlar': [], 'toplam': {'sessiz': 0, 'telesekreter': 0, 'diger': 0, 'toplam': 0}, 'projeler': [], 'sutunlar': cz['sutunlar'], 'silinen_haric': True}
    # HTML: tablo başlıkları, satırlar, toplam satırı ve proje alt toplamı.
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar').data.decode()
    assert 'id="profil-capraz"' in html and '<th class="sayi">Sessiz</th>' in html and '<th class="sayi">Telesekreter</th>' in html and '<th class="sayi">Diğer / boş</th>' in html
    assert '<b data-capraz-toplam="toplam">6</b>' in html and html.count('class="alt-toplam"') == 2 and 'proje toplamı' in html


def test_gizle_modunda_ozet_ve_tablo_yalniz_onayli_kt_yetkili_etkilenmez(web):
    c, a = web; a['ONAYSIZ_GORUNUM'] = 'gizle'; ids = ornek_veri(a)
    account(a, 'raporcu', 'OF:oku;PA:oku'); account(a, 'lider', 'OF:oku,kt;PA:oku,kt')
    login(c, 'raporcu')
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar').data.decode()
    assert re.search(r'<b data-ozet="total">2</b>', html) and re.search(r'<b data-ozet="pending">0</b>', html) and re.search(r'<b data-ozet="deleted">0</b>', html)
    assert '<b data-capraz-toplam="toplam">2</b>' in html and f'#{ids["ark_bugun"]} aç' not in html and f'#{ids["ark_onayli"]} aç' in html
    t1 = (date.today() - timedelta(days=6)).isoformat(); t2 = date.today().isoformat()
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar?tarih1={t1}&tarih2={t2}').data.decode()
    assert re.search(r'<b data-ozet="total">1</b>', html) and '<b data-capraz-toplam="diger">1</b>' in html and '<b data-capraz-toplam="toplam">1</b>' in html
    c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'lider')
    html = c.get(f'/telegram/kullanici/{TG}/kanitlar').data.decode()
    assert re.search(r'<b data-ozet="total">6</b>', html) and '<b data-capraz-toplam="toplam">5</b>' in html and f'#{ids["ark_bugun"]} aç' in html
    # uyar modunda raporcu her şeyi sayar (kural yalnız gizle'de daraltır)
    a['ONAYSIZ_GORUNUM'] = 'uyar'; c.post('/cikis', data={'csrf': csrf(c)}); login(c, 'raporcu')
    assert re.search(r'<b data-ozet="total">6</b>', c.get(f'/telegram/kullanici/{TG}/kanitlar').data.decode())


def test_gecersiz_ve_ters_tarih(web):
    c, a = web; login(c); ornek_veri(a)
    r = c.get(f'/telegram/kullanici/{TG}/kanitlar?tarih1=2026-13-01')
    assert r.status_code == 400 and 'Tarih biçimi geçersiz; takvimden seçin' in r.data.decode() and 'Geçersiz istek' in r.data.decode()
    assert c.get(f'/telegram/kullanici/{TG}/kanitlar?tarih2=bugun').status_code == 400
    t1 = (date.today() - timedelta(days=6)).isoformat(); t2 = date.today().isoformat()
    r = c.get(f'/telegram/kullanici/{TG}/kanitlar?tarih1={t2}&tarih2={t1}')   # ters aralık: düzeltilir, uyarı gösterilir, sayım doğru
    html = r.data.decode()
    assert r.status_code == 200 and 'tarihler yer değiştirildi' in html and f'id="profil-tarih1" type="date" name="tarih1" value="{t1}"' in html
    assert re.search(r'<b data-ozet="total">4</b>', html) and 'aria-invalid="true"' in html
    p = profil(a, tarih1=t2, tarih2=t1)
    assert p['filters']['tarih1'] == t1 and p['filters']['tarih2'] == t2 and p['filters']['uyari'].startswith('Başlangıç tarihi bitişten sonraydı')
    # Boş/boşluklu değer yok sayılır
    assert profil(a, tarih1='  ', tarih2='')['filters']['uyari'] == '' and profil(a, tarih1='  ')['counts']['total'] == 6
