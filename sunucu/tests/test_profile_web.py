from app import db,kullanicilar
from test_web import web,seed,login,csrf


def test_profile_route_expected_project_and_scoping(web):
    c,a=web;login(c);of=seed(a);pa=seed(a,'PA','profile-other')
    con=db.baglan(a['DB']);con.execute("UPDATE kayitlar SET ekleyen_id='77',ekleyen_guven='telegram'");con.execute("INSERT INTO tg_kullanicilar(id,username) VALUES('77','tester')");con.close()
    assert c.get('/telegram/kullanici/77/kanitlar').status_code==200
    assert c.post('/telegram/kullanici/77/kanitlar',data={'csrf':csrf(c),'op':'ana_proje','project':'OF'}).status_code==302
    con=db.baglan(a['DB']);assert con.execute("SELECT ana_proje FROM tg_kullanicilar WHERE id='77'").fetchone()[0]=='OF';con.close()
    outside=c.get('/telegram/kullanici/77/kanitlar?outside=1').data
    assert f'ac={pa}"'.encode() in outside and f'ac={of}"'.encode() not in outside
    assert c.post('/telegram/kullanici/77/kanitlar',data={'csrf':csrf(c),'project':'PRIVATE'}).status_code==400
    kullanicilar.ekle(a,'ofadmin','OF:oku,kt','Test-Password-123!');kullanicilar.guncelle(a,'ofadmin',sifre_degistir=0)
    c.post('/cikis',data={'csrf':csrf(c)});login(c,'ofadmin')
    html=c.get('/telegram/kullanici/77/kanitlar').data
    assert f'ac={of}"'.encode() in html and f'ac={pa}"'.encode() not in html
    assert c.post('/telegram/kullanici/77/kanitlar',data={'csrf':csrf(c),'project':'PA'}).status_code==403
    con=db.baglan(a['DB']);con.execute("UPDATE kayitlar SET ekleyen_id='88' WHERE id=?",(pa,));con.close()
    assert c.get('/telegram/kullanici/88/kanitlar').status_code==403
