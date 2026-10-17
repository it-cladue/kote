from app import db,kullanicilar
from test_web import web,seed,login,csrf


def account(a,name,role):
    kullanicilar.ekle(a,name,role,'Test-Password-123!');kullanicilar.guncelle(a,name,sifre_degistir=0)


def test_question_reply_visible_and_notifications_scoped(web):
    c,a=web;account(a,'ofadmin','OF:oku,kt');account(a,'paadmin','PA:oku,kt');login(c);kid=seed(a)
    r=c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'Bu kanıt neden farklı?\nAyrıntılı açıklar mısın?','alici':'ofadmin'})
    assert r.json['ok'];qid=r.json['yorum_id']
    d=c.get(f'/kayit/{kid}').json;assert d['yorumlar'][0]['alici']=='ofadmin' and d['yorumlar'][0]['tur']=='soru'
    assert any(u['kullanici_adi']=='ofadmin' for u in d['yorum_alicilari']) and not any(u['kullanici_adi']=='paadmin' for u in d['yorum_alicilari'])
    assert c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'x','alici':'paadmin'}).status_code==400
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'ofadmin')
    notifications=c.get('/bildirim.json').json
    questions=[x for x in notifications['bildirimler'] if x.get('tur')=='soru'];assert len(questions)==1 and questions[0]['kim']=='testadmin'
    assert c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'Açıklama budur.','yanit_id':qid}).json['ok']
    c.post('/cikis',data={'csrf':csrf(c)});login(c)
    replies=[x for x in c.get('/bildirim.json').json['bildirimler'] if x.get('tur')=='yanit'];assert len(replies)==1 and replies[0]['kim']=='ofadmin'
    assert c.get(f'/kayit/{kid}').json['yorumlar'][1]['yanit_id']==qid
    assert c.post('/bildirimler/okundu',data={'csrf':csrf(c),'id':replies[0]['bildirim_id']}).json['ok']
    assert not any(x.get('tur')=='yanit' for x in c.get('/bildirim.json').json['bildirimler'])
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'paadmin')
    assert c.get('/bildirim.json').json['okunmamis']==0
    assert c.get(f'/kayit/{kid}').status_code==403


def test_approval_actor_long_comments_cross_record_reply(web):
    c,a=web;account(a,'ofadmin','OF:oku,kt');login(c);kid=seed(a);other=seed(a,'PA','another')
    assert c.post(f'/kayit/{kid}/kt',data={'csrf':csrf(c)}).json['ok']
    d=c.get(f'/kayit/{kid}').json;assert d['kt_kim']=='testadmin' and d['kt_zaman']
    q=c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'A'*4000,'alici':'ofadmin'}).json['yorum_id']
    assert c.post(f'/kayit/{other}/yorum',data={'csrf':csrf(c),'yorum':'yanlış','yanit_id':q}).status_code==400
    assert c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'A'*5001}).status_code==400
    html=c.get('/kayitlar?durum=hepsi').data
    assert b'rows="7"' in html and b'm-onay-ozet' in html and b'yorum-genis' in html
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'ofadmin')
    alerts=c.get('/bildirim.json').json['bildirimler'];assert any(x.get('tur')=='onay' and x['kim']=='testadmin' for x in alerts)


def test_comment_notification_revoked_role_and_foreign_mark(web):
    c,a=web;account(a,'ofadmin','OF:oku,kt');login(c);kid=seed(a)
    c.post(f'/kayit/{kid}/yorum',data={'csrf':csrf(c),'yorum':'Özel soru','alici':'ofadmin'})
    con=db.baglan(a['DB']);bid=con.execute("SELECT id FROM mesaj_bildirimleri WHERE kullanici_adi='ofadmin'").fetchone()[0];con.close()
    c.post('/bildirimler/okundu',data={'csrf':csrf(c),'id':'m:'+str(bid)})
    con=db.baglan(a['DB']);assert con.execute('SELECT okundu FROM mesaj_bildirimleri WHERE id=?',(bid,)).fetchone()[0]==0;con.close()
    kullanicilar.guncelle(a,'ofadmin',yetki='PA:oku,kt')
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'ofadmin')
    assert c.get('/bildirim.json').json['okunmamis']==0
