import io
from pathlib import Path
import pytest
from PIL import Image
from app import db,kullanicilar

@pytest.fixture
def web(tmp_path,monkeypatch):
    from app import panel,gorsel
    config=dict(panel.AYAR)
    config.update(DB=str(tmp_path/'panel.db'),BOT_KLASOR=str(tmp_path),GORSEL_KLASOR=str(tmp_path/'gorseller'),ARSIV_KLASOR=str(tmp_path/'telegram_gorseller'),EK_GORSEL_KLASORLERI=[str(tmp_path/'telegram_gorseller')],ONBELLEK=str(tmp_path/'tmp'),LOG_DOSYA=str(tmp_path/'bot_log.txt'))
    Path(config['GORSEL_KLASOR']).mkdir();Path(config['ARSIV_KLASOR']).mkdir()
    monkeypatch.setattr(panel,'AYAR',config);monkeypatch.setattr(panel,'COZUCU',gorsel.GorselCozucu(config,config['ONBELLEK']))
    panel.app.config.update(TESTING=True,SESSION_COOKIE_SECURE=False)
    kullanicilar.ekle(config,'testadmin','admin','Test-Password-123!');kullanicilar.guncelle(config,'testadmin',sifre_degistir=0)
    return panel.app.test_client(),config

def token(client):
    client.get('/giris')
    with client.session_transaction() as s:return s['csrf']

def login(client,ad='testadmin'):
    return client.post('/giris',data={'csrf':token(client),'kullanici':ad,'sifre':'Test-Password-123!'})

def csrf(client):
    with client.session_transaction() as s:return s['csrf']

def seed(a,project='OF',key='tg:1:2:3',picture=True):
    path=None
    if picture:
        path=Path(a['GORSEL_KLASOR'])/'test.png';Image.new('RGB',(10,10),(255,0,0)).save(path,'PNG')
    c=db.baglan(a['DB'])
    with db.transaction(c):
        kid=c.execute('INSERT INTO kayitlar(anahtar,proje,personel,uye_id,kategori,gorsel_dosya,kaynak,giris_tipi,ekleyen_ad,aciklama,tarih,guncelleme) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                      (key,project,'00123','00099','HGST',str(path) if path else None,'telegram','resim' if path else 'yazili','tgtester','Özgün açıklama',db.simdi(),db.simdi())).lastrowid
        db.bildirim_uret(c,kid);db.degisti(c)
    c.close();return kid

def test_health_login_and_no_site_submission(web):
    c,a=web
    assert c.get('/saglik').status_code==200
    assert c.get('/').status_code==302
    assert c.post('/giris',data={'kullanici':'testadmin','sifre':'Test-Password-123!'}).status_code==400
    assert login(c).status_code==302
    for url in ['/','/kayitlar?gorunum=tablo','/kayitlar?gorunum=galeri','/kayitlar?gorunum=kart','/arsiv','/yonetim/kullanicilar','/denetim','/disa-aktar','/bot']:
        assert c.get(url).status_code==200,url
    assert c.get('/ekle').status_code==404
    assert c.post('/ekle',data={'csrf':csrf(c)}).status_code==404
    assert b'Kan\xc4\xb1t ekle' not in c.get('/').data
    assert not list(Path(a['BOT_KLASOR']).glob('*.xlsx'))

def test_crud_comments_and_no_excel_queue(web):
    c,a=web;login(c);kid=seed(a)
    assert c.get(f'/gorsel/{kid}').status_code==200
    assert c.get(f'/kucuk/{kid}').status_code==200
    d=c.get(f'/kayit/{kid}').json
    assert 'gorsel_dosya' not in d and 'file_id' not in d
    assert c.post(f'/kayit/{kid}/kt',data={'csrf':csrf(c),'deger':'1','surum':d['surum']}).json['kt']==1
    assert c.post(f'/kayit/{kid}/duzenle',data={'csrf':csrf(c),'personel':'new','surum':d['surum']}).status_code==409
    assert c.post(f'/kayit/{kid}/duzenle',data={'csrf':csrf(c),'personel':'new'}).json['ok']
    assert c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'Kontrol edildi <b>OK</b>'}).json['ok']
    d=c.get(f'/kayit/{kid}').json
    assert d['yorumlar'][0]['kullanici']=='testadmin' and d['aciklama']=='Özgün açıklama'
    assert c.post(f'/kayit/{kid}/sil',data={'csrf':csrf(c)}).json['ok']
    assert c.post(f'/kayit/{kid}/geri-al',data={'csrf':csrf(c)}).json['ok']
    con=db.baglan(a['DB']);assert con.execute('SELECT COUNT(*) FROM denetim').fetchone()[0]>=6
    assert con.execute('SELECT COUNT(*) FROM islem_sonuclari').fetchone()[0]==0;con.close()
    assert not (Path(a['BOT_KLASOR'])/'panel_kuyruk').exists()

def test_roles_csrf_and_session_invalidation(web):
    c,a=web;login(c);of=seed(a);pa=seed(a,'PA','tg:1:2:4')
    kullanicilar.ekle(a,'reader','OF:oku','Test-Password-123!');kullanicilar.guncelle(a,'reader',sifre_degistir=0)
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'reader')
    assert c.get('/bot').status_code==403 and c.get('/arsiv').status_code==403
    assert c.get(f'/kayit/{pa}').status_code==403
    assert c.post(f'/kayit/{of}/kt',data={'csrf':csrf(c)}).status_code==403
    assert c.post(f'/kayit/{of}/yorum',data={'csrf':csrf(c),'yorum':'x'}).status_code==403
    assert c.post(f'/kayit/{of}/kt',data={}).status_code==400
    kullanicilar.guncelle(a,'reader',sifre='Replacement-Password-123!')
    assert c.get('/').status_code==302

def test_project_notifications_persist_and_scoped(web):
    c,a=web
    for name,role in [('ofadmin','OF:oku,kt'),('paadmin','PA:oku,kt'),('reader','OF:oku')]:
        kullanicilar.ekle(a,name,role,'Test-Password-123!');kullanicilar.guncelle(a,name,sifre_degistir=0)
    of=seed(a);pa=seed(a,'PA','tg:1:2:4')
    con=db.baglan(a['DB']);db.bildirim_uret(con,of)
    assert con.execute('SELECT COUNT(*) FROM bildirimler WHERE kayit_id=?',(of,)).fetchone()[0]==2
    assert con.execute("SELECT COUNT(*) FROM bildirimler WHERE kullanici_adi='reader'").fetchone()[0]==0
    other_id=con.execute("SELECT id FROM bildirimler WHERE kullanici_adi='paadmin'").fetchone()[0];con.close()
    login(c,'ofadmin');d=c.get('/bildirim.json').json
    assert d['okunmamis']==1 and len(d['bildirimler'])==1 and d['bildirimler'][0]['proje']=='OF'
    c.post('/bildirimler/okundu',data={'csrf':csrf(c),'id':other_id})
    assert c.get('/bildirim.json').json['okunmamis']==1
    own_id=d['bildirimler'][0]['bildirim_id'];c.post('/bildirimler/okundu',data={'csrf':csrf(c),'id':own_id})
    assert c.get('/bildirim.json').json['okunmamis']==0
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'paadmin')
    assert c.get('/bildirim.json').json['okunmamis']==1

def test_report_formulas_and_redirect(web):
    c,a=web
    assert c.post('/giris?sonraki=//evil.example',data={'csrf':token(c),'kullanici':'testadmin','sifre':'Test-Password-123!'}).location=='/'
    kid=seed(a,picture=False);con=db.baglan(a['DB']);con.execute('UPDATE kayitlar SET personel=?,lead_id=? WHERE id=?',('=1+1','LEAD-5',kid));con.close()
    x=c.get('/disa-aktar.xlsx?durum=hepsi');assert x.status_code==200
    from openpyxl import load_workbook
    w=load_workbook(io.BytesIO(x.data));assert w.active['D2'].data_type=='s' and w.active['D2'].value.startswith("'");w.close()

def test_login_lock_and_last_admin(web):
    c,a=web
    for _ in range(5):c.post('/giris',data={'csrf':token(c),'kullanici':'testadmin','sifre':'bad'})
    assert kullanicilar.dogrula(a,'testadmin','Test-Password-123!')[0] is None
    with pytest.raises(ValueError):kullanicilar.guncelle(a,'testadmin',aktif=0)
