import io
from pathlib import Path
import pytest
import requests
from PIL import Image
from app import gyazo,db
from test_web import web,seed,login,csrf


class Reply:
    def __init__(self,status=200,result=None,content='image/png'):
        self.status_code=status;self.result=result;self.headers={'Content-Type':content}
    def json(self):return self.result
    def close(self):pass


class HTTP:
    def __init__(self,status=200,image_status=200,raw_url=None,timeout=False):
        self.status=status;self.image_status=image_status;self.raw_url=raw_url;self.timeout=timeout;self.uploads=0;self.last=None
    def post(self,url,**kwargs):
        self.uploads+=1;self.last=(url,kwargs)
        if self.timeout:raise requests.Timeout()
        return Reply(self.status,{'image_id':'a'*32,'url':self.raw_url or 'https://i.gyazo.com/'+('a'*32)+'.png'})
    def get(self,url,**kwargs):return Reply(self.image_status)
    def close(self):pass


@pytest.fixture
def photo(tmp_path,monkeypatch):
    p=tmp_path/'photo.png';Image.new('RGB',(4,4),'red').save(p)
    monkeypatch.setattr(gyazo,'AYAR',{'DB':str(tmp_path/'panel.db')})
    return p


def test_gyazo_optional_and_success_cached(photo,monkeypatch):
    h=HTTP();monkeypatch.setattr(gyazo.requests,'Session',lambda:h)
    assert gyazo.convert(photo,token='')['ok'] is False and h.uploads==0
    r=gyazo.convert(photo,token='test-key');assert r['ok'] and r['url']=='https://gyazo.com/'+('a'*32)
    assert h.last[0]=='https://upload.gyazo.com/api/upload'
    assert h.last[1]['files']['imagedata'][0]=='kanit.png'
    assert gyazo.convert(photo,token='test-key')['ok'] and h.uploads==1
    assert photo.is_file()


@pytest.mark.parametrize('http,part',[(HTTP(status=503),'sunucusunda hata'),(HTTP(status=401),'yetkilendirmesi'),(HTTP(image_status=404),'bağlantısı erişilemiyor'),(HTTP(raw_url='http://127.0.0.1/private'),'bağlantısı erişilemiyor'),(HTTP(timeout=True),'süresi')])
def test_gyazo_failure_keeps_source(photo,monkeypatch,http,part):
    monkeypatch.setattr(gyazo.requests,'Session',lambda:http)
    original=photo.read_bytes();r=gyazo.convert(photo,token='test-key')
    assert r['ok'] is False and r['url'] is None and part in r['error']
    assert photo.read_bytes()==original


def test_existing_evidence_conversion_is_not_new_evidence(web,monkeypatch):
    c,a=web;login(c);kid=seed(a)
    from app import donusum_isleri
    monkeypatch.setenv('GYAZO_TOKEN','test-private-key')
    d=c.get(f'/kayit/{kid}').json;assert d['izin_gyazo']
    r=c.post(f'/kayit/{kid}/gyazo',data={'csrf':csrf(c),'surum':d['surum']})
    assert r.status_code==200 and r.json['pending'] and not r.json['converted']
    conn=db.baglan(a['DB']);assert conn.execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0]==1
    upload=lambda path:{'ok':True,'image_id':'b'*32,'image_url':'https://i.gyazo.com/'+('b'*32)+'.png','http_status':200}
    verify=lambda image_id,image_url:{'ok':True,'url':'https://gyazo.com/'+('b'*32),'http_status':200}
    donusum_isleri.worker_step(conn,'test-web',upload=upload,verify=verify)
    donusum_isleri.worker_step(conn,'test-web',upload=upload,verify=verify)
    row=conn.execute('SELECT * FROM kayitlar WHERE id=?',(kid,)).fetchone();assert row['gorsel_dosya'] and row['link_turu']=='gyazo';conn.close()
    assert c.get(f'/kayit/{kid}/gyazo-durum').json['converted']
    r=c.post(f'/kayit/{kid}/gyazo',data={'csrf':csrf(c)})
    assert r.json['converted'] and not r.json['pending']
    conn=db.baglan(a['DB']);assert conn.execute('SELECT COUNT(*) FROM donusum_isleri').fetchone()[0]==1;conn.close()
    # Aynı menüde tema düğmesi ve yükleme öncesi tema modülü bulunur.
    assert b'data-tema-toggle' in c.get('/').data and b'tema.js' in c.get('/giris').data
