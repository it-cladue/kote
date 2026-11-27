"""Kanıt Paneli sunucu sürümü. Canlı Excel/OneDrive/Gyazo bağımlılığı yok."""
import io
import json
import os
import re
import secrets
import sys
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, g, request, session, redirect, url_for, render_template, jsonify, abort, send_file, flash
from flask.sessions import SecureCookieSessionInterface
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import SecurityError
from functools import wraps
from PIL import Image, UnidentifiedImageError
from . import db, yetki, kullanicilar, gorsel, bot_yonetim, api, api_anahtarlari, personel_ozeti, erisim, hatirlatma
from . import iki_adim, qr_svg
from .settings import AYAR, ROOT

SURUM = '2.4.1'
secret_path = Path(AYAR['BOT_KLASOR']) / 'session.key'
secret = os.getenv('SESSION_SECRET')
if not secret:
    try:
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    secret = secret_path.read_text().strip()
if len(secret) < 32:
    raise RuntimeError('SESSION_SECRET en az 32 karakter olmalı.')
app = Flask(__name__)
app.json.ensure_ascii=False
app.secret_key = secret
CEREZSIZ_UCLAR=('static','saglik')

class _CerezsizOturum(SecureCookieSessionInterface):
    """Sağlık denetimi ve statik dosyalar oturum çerezi yazmaz (kalıcı oturum tazelemesi dahil)."""
    def save_session(self,app,session,response):
        if request.endpoint in CEREZSIZ_UCLAR and not session.modified:
            return None
        if request.path.startswith('/api/'):
            return None  # 2.3.2: API yanıtları hiçbir koşulda oturum çerezi yazmaz
        return super().save_session(app,session,response)

app.session_interface=_CerezsizOturum()
# SESSION_SECRET döndürme: yeni anahtar SESSION_SECRET'a, eskisi SESSION_SECRET_ESKI'ye (virgülle birden çok) yazılır;
# eski anahtarla imzalı oturumlar doğrulanmaya devam eder, yeni imzalar yeni anahtarla atılır. 1-2 gün sonra eskisi silinir.
_eski_anahtarlar=[x.strip() for x in os.getenv('SESSION_SECRET_ESKI','').split(',') if len(x.strip())>=32]
if _eski_anahtarlar: app.config['SECRET_KEY_FALLBACKS']=_eski_anahtarlar
# Host başlığı sahteciliği (request.url_root ile üretilen bağlantılar): GUVENILEN_HOSTLAR=panel.alan.com,217.156.123.36
# Boşsa denetim yapılmaz (mevcut davranış). Doluysa 127.0.0.1 ve localhost kendiliğinden eklenir ki /saglik kontrolleri kırılmasın.
_hostlar=[h.strip().lower() for h in os.getenv('GUVENILEN_HOSTLAR','').split(',') if h.strip()]
if _hostlar: app.config['TRUSTED_HOSTS']=list(dict.fromkeys(_hostlar+['127.0.0.1','localhost']))
MUTLAK_OTURUM_SN=24*3600  # Kayan 12 saatlik süreye ek mutlak üst sınır: girişten 24 saat sonra yeniden giriş.
secure = str(AYAR['HTTPS']).lower() in ('1','true')
EN_BUYUK_ISTEK=12*1024*1024  # Flask gövde sınırı (12 MB yükleme); waitress sınırı calistir() içinde bunun biraz üstünde tutulur.
# HTTPS'te __Host- ön eki: çerez yalnız bu kaynaktan, Secure ve Path=/ ile yazılabilir; aynı IP'nin 80/443'ündeki başka site yazamaz.
app.config.update(SESSION_COOKIE_NAME='__Host-kanit_session' if secure else 'kanit_session', SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SECURE=secure, SESSION_COOKIE_SAMESITE='Lax',
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
                  MAX_CONTENT_LENGTH=EN_BUYUK_ISTEK)
# 2.4.1: iki adımlı doğrulamanın "bu cihazda sorma" çerezi (oturum çerezinden ayrı; HttpOnly, HTTPS'te Secure + __Host-).
CIHAZ_CEREZI='__Host-kanit_cihaz' if secure else 'kanit_cihaz'
# Kurulumu zorunlu olup bitirmemiş hesabın açabileceği uçlar (kurulum sayfası, çıkış, geçici şifre değişimi, giriş adımları).
IKI_ADIM_SERBEST={'iki_adim','cikis','sifre_degistir','giris','giris_dogrulama','static','saglik'}
# 2.4.0: GYAZO_PROXY / DIS_GORSEL_PROXY panelden değiştirildiyse (veritabanı) açılışta o değer kullanılır (app/ayarlar.py).
from . import ayarlar as _calisma_ayarlari
COZUCU = gorsel.GorselCozucu(_calisma_ayarlari.birlesik(AYAR), AYAR['ONBELLEK'])

def simdi():
    return db.simdi()

def baglanti():
    if 'conn' not in g:
        g.conn = db.baglan(AYAR['DB'])
    return g.conn

@app.teardown_appcontext
def close_connection(error=None):
    c = g.pop('conn',None)
    if c:
        c.close()

def _all_project_info():
    from . import katalog
    if 'project_info' not in g:
        items=katalog.list_projects(baglanti(),active_only=False)
        known={p['code'] for p in items}
        for row in baglanti().execute('SELECT DISTINCT proje FROM kayitlar'):
            # Elle girilmiş küçük harfli/bilinmeyen kodlar ayrı bir çip olmasın: büyük harfe çevrilip tekilleştirilir.
            code=(row['proje'] or '').strip().upper()
            if code and code not in known:
                known.add(code); items.append(dict(code=code,label=code,color='#64748b',aktif=0,revision=0))
        g.project_info=items
    return g.project_info

def renk(proje):
    return next((p['color'] for p in _all_project_info() if p['code']==proje),'#64748b')


def metin_rengi(value):
    try:
        h=value.lstrip('#'); r,gg,b=(int(h[i:i+2],16) for i in (0,2,4))
        return '#111111' if .299*r+.587*gg+.114*b>150 else '#ffffff'
    except (ValueError,AttributeError):
        return '#ffffff'

def projeler():
    return [p['code'] for p in _all_project_info()]

def _allowed():
    return yetki.izinli_projeler(g.yk,projeler())

def _explicit_projects(args,allowed):
    """Kullanicinin acikca sectigi projeler; bos/'hepsi' degerleri yok sayilir (bos = tum yetkili)."""
    selected=[str(p).strip().upper() for p in args.getlist('proje') if str(p).strip() and str(p).strip().lower()!='hepsi']
    if any(p not in allowed for p in selected):abort(403)
    return list(dict.fromkeys(selected))

def _selected_projects(args,allowed):
    selected=_explicit_projects(args,allowed)
    return selected or list(allowed)

def _gizli_kayit_sql(alias='',projeler_listesi=None,sol_birlesim=False):
    """2.3.1 ONAYSIZ_GORUNUM=gizle: kullanıcının kt yetkisi olmayan projelerde onaysız/silinmiş kayıtları dışlayan ortak koşul.
    (sql, params) döndürür; kural uygulanmıyorsa ('', []). Liste, sayaçlar, kategori, denetim/son işlemler ve bildirim akışı aynı yardımcıyı kullanır.
    sol_birlesim=True: LEFT JOIN'de kayıt satırı olmayan (k NULL) satırlar korunur."""
    if _onaysiz_modu()!='gizle':return '',[]
    kt_yok=_kt_yok(projeler_listesi if projeler_listesi is not None else _allowed())
    if not kt_yok:return '',[]
    a=(alias+'.') if alias else ''
    sql='NOT (%sproje IN (%s) AND (%skt=0 OR %ssilindi=1))' % (a,','.join('?'*len(kt_yok)),a,a)
    if sol_birlesim:sql='(%sid IS NULL OR %s)' % (a,sql)
    return sql,list(kt_yok)

def _scoped_categories(codes):
    from . import katalog
    if not codes:return []
    names=set()
    for code in codes:
        names.update(r['label'] for r in katalog.list_categories(baglanti(),project_code=code,active_only=True))
    places=','.join('?' for _ in codes)
    gizli_sql,gizli_par=_gizli_kayit_sql('',codes)
    names.update(r[0] for r in baglanti().execute("SELECT DISTINCT kategori FROM kayitlar WHERE proje IN ("+places+") AND kategori IS NOT NULL AND kategori<>''"+(' AND '+gizli_sql if gizli_sql else ''),[*codes,*gizli_par]))
    return sorted(names,key=str.casefold)

def url_filtre(endpoint,**ek):
    args=request.args.to_dict(flat=False)
    for k,v in ek.items(): args[k]=[str(v)]
    return url_for(endpoint,**args)


def url_degistir(**kw):
    args=request.args.to_dict(flat=False); args.pop('s',None)
    for k,v in kw.items():
        if v is None or v=='': args.pop(k,None)
        else: args[k]=list(v) if isinstance(v,(list,tuple)) else [str(v)]
    if 'ac' not in args: args.pop('yorum',None)  # derin bağlantının yorum vurgusu sekme/sayfa bağlantılarına taşınmaz
    return url_for(request.endpoint or 'kayitlar',**args)

def ip():
    return request.remote_addr

def _gunluk_ip(value):
    return re.sub(r'[^0-9a-fA-F.:]','',str(value or ''))[:45] or '-'

def guvenlik_gunlugu(olay,kullanici=None,ip_adresi=None):
    """fail2ban'ın okuyabileceği sabit biçimde tek satır (stderr → journald):
    kanit-web GIRIS_HATA ip=1.2.3.4 kullanici=ad | GIRIS_SINIR ip=... | GIRIS_KILIT ip=... kullanici=... | CSRF_HATA ip=... kullanici=...
    Kullanıcı adı yalnız süzgeci geçiyorsa yazılır; aksi hâlde '-' (satır sonu/boşluk enjeksiyonu olmaz)."""
    satir='kanit-web '+re.sub(r'[^A-Z_]','',str(olay))+' ip='+_gunluk_ip(ip_adresi if ip_adresi is not None else ip())
    if kullanici is not None:
        satir+=' kullanici='+(kullanici if kullanici_adi_gecerli(kullanici) else '-')
    try:print(satir,file=sys.stderr,flush=True)
    except Exception:pass

def _guvenli_yol(hedef):
    """Yalnız site içi mutlak yol. Tarayıcılar ve urlsplit sekme/satır sonu karakterlerini SİLER ('/\\t/evil' → '//evil'),
    bu yüzden kontrol karakteri ve ters bölü reddedilir; şema veya host içeren hedef kabul edilmez."""
    hedef=str(hedef or '')
    if not hedef or len(hedef)>2000 or re.search(r'[\x00-\x1f\x7f\\]',hedef):return '/'
    p=urlsplit(hedef)
    if p.scheme or p.netloc or not p.path.startswith('/') or p.path.startswith('//'):return '/'
    return hedef

OTURUM_MESAJI='Oturumunuz sona erdi; başka bir cihazdan çıkış yapıldı, yetkileriniz güncellendi veya şifreniz değişti. Lütfen yeniden giriş yapın.'
SURE_MESAJI='Oturum süreniz doldu; güvenlik için girişten 24 saat sonra yeniden giriş istenir. Lütfen yeniden giriş yapın.'

def _sonraki_hedef():
    """Giriş sonrası dönülecek adres: sorgu dizesi korunur, yalnız site içi yol kabul edilir."""
    if request.method not in ('GET','HEAD'):return '/'
    target=(request.full_path if request.query_string else request.path).rstrip('?')
    return _guvenli_yol(target)

def _oturum_dustu_yaniti():
    """Yetki/şifre değişince düşen oturum: XHR'a JSON 401, sayfaya açıklamalı giriş yönlendirmesi."""
    if _json_bekleniyor():
        return jsonify(ok=False,hata='Oturumunuz sona erdi, sayfayı yenileyin.',kod=401,oturum=False,giris=url_for('giris',neden='oturum')),401
    return redirect(url_for('giris',neden='oturum',sonraki=_sonraki_hedef()))

def _host_hatasi(error=None):
    """GUVENILEN_HOSTLAR dışındaki Host başlığı: URL kurucu yok, şablon (url_for) kullanılamaz; sade Türkçe 400."""
    from flask import make_response
    resp=make_response('<!doctype html><html lang="tr"><meta charset="utf-8"><title>Geçersiz istek</title>'
                       '<p>Bu adres (Host başlığı) panel için tanımlı değil. Paneli tanımlı adresinden açın; sorun sürerse yöneticinize bildirin.</p>',400)
    resp.headers['Content-Type']='text/html; charset=utf-8'
    return resp

app.register_error_handler(SecurityError,_host_hatasi)
app.register_blueprint(api.bp)  # 2.3.2: /api/v1/* (Bearer anahtar; oturum/CSRF yok)

@app.before_request
def before():
    g.k=None;g.oturum_dustu=False;g.csp_nonce=secrets.token_urlsafe(16)
    if isinstance(getattr(request,'routing_exception',None),SecurityError):
        # Güvenilmeyen Host: oturum/CSRF akışına girmeden sade 400 (url_for çağrıları 500 üretirdi).
        g.yk=yetki.coz('');return _host_hatasi(request.routing_exception)
    if not request.path.startswith('/api/'):
        # 2.4.0: erişim sınırı (IP izin listesi) — /giris dahil her panel adresi; statik dosyalar ve sunucunun kendisinden
        # gelen doğrudan istekler muaf (ayrıntı: app/erisim.py). API kendi listesini api.py'de uygular.
        red=_erisim_denetimi()
        if red is not None:
            g.yk=yetki.coz('');return red
    if request.endpoint in CEREZSIZ_UCLAR:
        # Sağlık denetimi ve statik dosyalar oturum çerezi üretmez.
        g.yk=yetki.coz('');return None
    if request.path.startswith('/api/'):
        # 2.3.2: API oturum çerezini okumaz/yazmaz, CSRF uygulanmaz; kimlik api.py'de Bearer anahtarla. Eşleşmeyen yol → JSON 404/405.
        g.yk=yetki.coz('');return api.yol_hatasi()
    if session.get('kad'):
        row=baglanti().execute('SELECT * FROM panel_kullanicilari WHERE kullanici_adi=?',(session['kad'],)).fetchone();u=dict(row) if row else None
        gz=session.get('gz')
        suresi_gecerli=isinstance(gz,int) and 0<=time.time()-gz<MUTLAK_OTURUM_SN
        if u and u['aktif'] and session.get('sv')==u['session_version'] and suresi_gecerli:
            g.k=u
        else:
            # Yetki/şifre değişti, hesap kapandı ya da 24 saatlik mutlak süre doldu: işaret, zil yoklaması ya da ikinci sekme
            # tarafından tüketilmesin diye yeni bir giriş yapılana kadar oturumda kalır (giriş sayfası görülmesi işareti silmez).
            # 'sure' yalnız gz alanı okunabildiğinde: gz olmayan (2.3 öncesi) çerez '24 saat doldu' değil genel açıklamayı alır.
            neden='sure' if (u and u['aktif'] and session.get('sv')==u['session_version'] and isinstance(gz,int) and not suresi_gecerli) else 'degisti'
            session.clear();session['dustu']=1;session['dustu_zaman']=simdi();session['dustu_neden']=neden;g.oturum_dustu=True
    elif session.get('dustu'):
        g.oturum_dustu=True
    g.yk=yetki.coz(g.k['yetki'] if g.k else '')
    session.setdefault('csrf',secrets.token_hex(24))
    # 2.4.1: politika iki adımlı doğrulamayı zorunlu kılıyor ve hesap henüz kurmadıysa yalnız kurulum sayfası açılır
    # (geçici şifre önce değiştirilir). Sahip kendi kurulum sayfasına her zaman ulaşır; acil durumda sunucuda 2fa-sifirla.
    # 2.4.2: zorunlu_mu önce hesabın kendi ayarına (iki_adim_zorunlu 1/0) bakar; g.k her istekte veritabanından okunur.
    g.iki_adim_kilit=bool(g.k and not g.k['sifre_degistir'] and not iki_adim.acik_mi(g.k) and iki_adim.zorunlu_mu(g.k,conn=baglanti()))
    # /sifre yalnız geçici şifre değişimi için serbest; o durumda bu kilit zaten devrede değil, kurulum bekleyen hesap /sifre'yi açamaz.
    if g.iki_adim_kilit and (request.endpoint not in IKI_ADIM_SERBEST or request.endpoint=='sifre_degistir'):
        if _json_bekleniyor():
            return jsonify(ok=False,hata='Önce iki adımlı doğrulamayı kurun.',kod=403,iki_adim=url_for('iki_adim')),403
        return redirect(url_for('iki_adim'))
    if g.k and request.endpoint in yetki.SAHIP_GEREKLI_EYLEMLER and not g.yk.get('sahip') and not g.k['sifre_degistir']:
        # 2.4.0: yalnız sahibe açık uçlar (sahip_gerekli süsleyicisi ve başka modüllerin eklediği uç adları).
        abort(403)
    if request.method in ('POST','PUT','PATCH','DELETE'):
        if not g.k and request.endpoint not in ('giris','giris_dogrulama'):
            # Oturumu olmayan her gönderim CSRF kontrolünden ÖNCE açıklamalı yanıt alır:
            # XHR'a JSON 401, sayfa gönderimine /giris?neden=oturum (çıkış isteği doğrudan giriş sayfasına).
            if request.endpoint=='cikis':return redirect(url_for('giris'))
            return _oturum_dustu_yaniti()
        token=request.form.get('csrf') or request.headers.get('X-CSRF','')
        if not secrets.compare_digest(token,session.get('csrf','')):
            if g.k:_csrf_hatasi_kaydet()
            abort(400,'Geçersiz CSRF. Sayfayı yenileyin.')

def _erisim_denetimi():
    """İzin listesi dışındaki adrese sade 403 sayfası; dakikada IP başına bir 'erisim_red' satırı. Liste boşsa hiçbir şey yapmaz."""
    try:
        c=baglanti();izinli,adres=erisim.panel_izinli(c,request)
    except Exception as hata:
        # Ayar okunamazsa (ör. veritabanı kilidi) panel kapanmaz; durum stderr'e yazılır.
        print('Erişim sınırı okunamadı: '+type(hata).__name__,file=sys.stderr,flush=True);return None
    if izinli:return None
    erisim.red_kaydet(c,adres,request.method+' '+request.path)
    guvenlik_gunlugu('ERISIM_RED')
    from flask import make_response
    if _json_bekleniyor():
        resp=jsonify(ok=False,hata='Bu adresten erişim izinli değil (IP: '+str(adres or '?')+').',kod=403,neden='ip_izinsiz');resp.status_code=403
    else:
        resp=make_response(erisim.red_sayfasi(adres),403);resp.headers['Content-Type']='text/html; charset=utf-8'
    return resp

def _csrf_hatasi_kaydet():
    """Oturumlu kullanıcıdan geçersiz CSRF: denetime 'csrf_hata' (IP+kullanıcı başına dakikada en çok 1) ve stderr satırı."""
    try:
        c=baglanti();esik=(datetime.now()-timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
        son=c.execute("SELECT 1 FROM denetim WHERE islem='csrf_hata' AND ip=? AND kullanici=? AND zaman>? LIMIT 1",(ip(),g.k['kullanici_adi'],esik)).fetchone()
        if not son:
            db.denetim_yaz(c,g.k['kullanici_adi'],'csrf_hata',ip=ip(),sonuc='uyari',hedef_turu='hesap',hedef_id=g.k['kullanici_adi'],aciklama=(request.method+' '+request.path)[:200])
            guvenlik_gunlugu('CSRF_HATA',g.k['kullanici_adi'])
    except Exception:
        pass

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='private, no-store' if request.endpoint!='static' else 'public, max-age=3600'
    # Satır içi <script> etiketleri şablonlarda nonce taşır; style= öznitelikleri için 'unsafe-inline' zorunlu.
    # Görseller yerel vekilden (/gorsel, /kucuk, /arsiv/gorsel) ve data: ikonlarından gelir; dış görsel doğrudan gösterilmez.
    # Bozuk görsel yer tutucusu kendi CSP'sini taşır (setdefault onu korur).
    response.headers.setdefault('Content-Security-Policy',"default-src 'self'; script-src 'self' 'nonce-"+g.get('csp_nonce','')+"'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'; object-src 'none'")
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=(), payment=(), usb=()'
    response.headers['Cross-Origin-Opener-Policy']='same-origin'
    if secure:
        # includeSubDomains bilinçli olarak YOK: aynı IP/alan altında Plesk'te başka site var.
        response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

@app.context_processor
def context():
    allowed=_allowed() if g.get('k') else []
    info=[p for p in _all_project_info() if p['code'] in allowed] if allowed else []
    safe_user={a:b for a,b in (g.get('k') or {}).items() if a not in ('sifre_hash','iki_adim_sir')}
    return dict(k=safe_user if g.get('k') else None,yk=g.get('yk'),renk=renk,metin_rengi=metin_rengi,
                url_degistir=url_degistir,url_filtre=url_filtre,csrf=session.get('csrf',''),projeler=lambda:allowed,
                proje_renkleri={p['code']:p['color'] for p in info},proje_bilgileri=info,
                izin=lambda p,e:yetki.izin(g.yk,p,e),simdi=simdi,SURUM=SURUM,csp_nonce=g.get('csp_nonce',''),
                rol_adi=yetki.rol_etiketi(g.get('yk')) if g.get('k') else '',
                kanit_ekle_olur=bool(_ekleme_projeleri()) if g.get('k') else False,
                iki_adim_kilit=bool(g.get('iki_adim_kilit')),iki_adim_acik=iki_adim.acik_mi(g.get('k')))


def giris_gerekli(f):
    @wraps(f)
    def wrapper(*a,**kw):
        if not g.k:
            if g.get('oturum_dustu'):return _oturum_dustu_yaniti()
            if _json_bekleniyor():return jsonify(ok=False,hata='Giriş gerekli; sayfayı yenileyip yeniden giriş yapın.',kod=401,giris=url_for('giris',neden='oturum')),401
            return redirect(url_for('giris',sonraki=_sonraki_hedef()))
        if g.k['sifre_degistir'] and request.endpoint not in ('sifre_degistir','cikis'):
            return redirect(url_for('sifre_degistir'))
        return f(*a,**kw)
    return wrapper

def admin_gerekli(f):
    @giris_gerekli
    @wraps(f)
    def wrapper(*a,**kw):
        if not g.yk['admin']: abort(403)
        return f(*a,**kw)
    return wrapper

def sahip_gerekli(f):
    """2.4.0: yalnız sahip (süperadminin üstü). Ucu yetki.SAHIP_GEREKLI_EYLEMLER kümesine de ekler; before() orada da denetler."""
    @admin_gerekli
    @wraps(f)
    def wrapper(*a,**kw):
        if not g.yk.get('sahip'): abort(403)
        return f(*a,**kw)
    yetki.SAHIP_GEREKLI_EYLEMLER.add(f.__name__)
    return wrapper

def kullanici_adi_gecerli(ad):
    return bool(re.fullmatch(r'[a-z0-9_.]{1,40}',ad or ''))

@app.route('/giris',methods=['GET','POST'])
def giris():
    hata=None
    if request.method=='POST':
        ad=request.form.get('kullanici','').strip().lower()
        c=baglanti()
        # IP bazlı kalıcı sınır; bilinmeyen kullanıcı adlarıyla da aşılmaz.
        count=_ip_hata_sayisi(c)
        if count>=20:
            guvenlik_gunlugu('GIRIS_SINIR')
            return render_template('giris.html',hata='Çok fazla giriş denemesi. 15 dakika bekleyin.'),429
        u,hata=kullanicilar.dogrula(AYAR,ad,request.form.get('sifre',''),ip=ip())
        if u:
            hedef=_guvenli_yol(request.args.get('sonraki','/'))
            if iki_adim.acik_mi(u):
                # 2.4.1: güvenilen cihaz (ayrı çerez) kodu atlar; değilse kısa ömürlü, tek kullanımlık ön işaretle kod adımına.
                if iki_adim.cihaz_gecerli(c,u['kullanici_adi'],request.cookies.get(CIHAZ_CEREZI),ip()):
                    _oturum_ac(c,u,'güvenilen cihaz: doğrulama kodu sorulmadı');return redirect(hedef)
                numara=iki_adim.on_giris_olustur(c,u['kullanici_adi'],u['session_version'],hedef)
                session.clear();session['ia']=numara;session['csrf']=secrets.token_hex(24)
                return redirect(url_for('giris_dogrulama'))
            _oturum_ac(c,u)
            return redirect(hedef)
        # Denetime yazılan ad süzgeci geçmeli: yanlış kutuya yazılan parola ya da rastgele metin İşlem Geçmişi'ne düşmez.
        gunluk_ad=ad if kullanici_adi_gecerli(ad) else '[geçersiz ad]'
        db.denetim_yaz(c,gunluk_ad,'giris_hata',ip=ip())
        if count+1>=20: db.denetim_yaz(c,gunluk_ad,'giris_sinir',ip=ip(),sonuc='uyari',hedef_turu='hesap',hedef_id=ip(),aciklama='IP 15 dakikada 20 hatalı denemeye ulaştı')
        hesap=kullanicilar.bul(AYAR,ad) if kullanici_adi_gecerli(ad) else None
        guvenlik_gunlugu('GIRIS_KILIT' if kullanicilar.kilitli_mi(hesap) else 'GIRIS_HATA',ad)
        time.sleep(.3)
    if not kullanicilar.var_mi(AYAR):
        hata='Henüz panel hesabı oluşturulmadı. Sunucuda python -m app.cli admin-ekle komutunu çalıştırın.'
    # Düşme işareti burada silinmez; başarılı giriş session.clear() ile temizler. Böylece ikinci sekme de açıklamayı görür.
    dustu=bool(session.get('dustu'))
    bilgi=None
    if request.method=='GET' and not g.k:
        if dustu:bilgi=SURE_MESAJI if session.get('dustu_neden')=='sure' else OTURUM_MESAJI
        elif request.args.get('neden')=='oturum':bilgi='Oturumunuz sona erdi. Lütfen yeniden giriş yapın.'
    return render_template('giris.html',hata=hata,bilgi=bilgi)

def _ip_hata_sayisi(c):
    """IP başına 15 dakikalık hatalı deneme sayısı (parola + 2.4.1 doğrulama kodu); bilinmeyen adlarla da aşılmaz."""
    return c.execute("SELECT COUNT(*) FROM denetim WHERE islem IN ('giris_hata','2fa_hata') AND ip=? AND zaman>?",
                     (ip(),(datetime.now()-timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S'))).fetchone()[0]

def _oturum_ac(c,u,aciklama=None):
    """Tam oturum: eski oturum (ve varsa iki adımlı ön işaret) silinir, yeni CSRF ve giriş zamanı yazılır."""
    session.clear(); session.permanent=True
    session.update(kad=u['kullanici_adi'],sv=u['session_version'],csrf=secrets.token_hex(24),gz=int(time.time()))
    db.denetim_yaz(c,u['kullanici_adi'],'giris',ip=ip(),aciklama=aciklama)

IKI_ADIM_SURE_MESAJI='Doğrulama adımının süresi doldu (5 dakika). Güvenlik için kullanıcı adı ve şifreyle yeniden başlayın.'

@app.route('/giris/dogrulama',methods=['GET','POST'])
def giris_dogrulama():
    """2.4.1: parola doğru → 6 haneli kod ya da kurtarma kodu. Ön işaret tam oturum değildir (bkz. app/iki_adim.py)."""
    c=baglanti();numara=session.get('ia');veri=iki_adim.on_giris_al(c,numara)
    if g.k and not veri:return redirect(url_for('ana'))
    if not veri:
        session.pop('ia',None)
        flash(IKI_ADIM_SURE_MESAJI if numara else 'Önce kullanıcı adı ve şifrenizle giriş yapın.')
        return redirect(url_for('giris'))
    ad=veri['ad'];u=kullanicilar.bul(AYAR,ad)
    if not u or not u['aktif'] or u['session_version']!=veri.get('sv') or not iki_adim.acik_mi(u):
        iki_adim.on_giris_sil(c,numara);session.clear();flash(OTURUM_MESAJI);return redirect(url_for('giris'))
    guven=iki_adim.guven_gun(c);hata=None;durum=200
    kalan_sn=max(0,int(iki_adim.ON_GIRIS_SN-(time.time()-float(veri.get('zaman',0)))))
    if request.method=='POST':
        if _ip_hata_sayisi(c)>=20:
            guvenlik_gunlugu('GIRIS_SINIR');iki_adim.on_giris_sil(c,numara);session.clear()
            return render_template('giris.html',hata='Çok fazla giriş denemesi. 15 dakika bekleyin.'),429
        if kullanicilar.kilitli_mi(u):
            iki_adim.on_giris_sil(c,numara);session.clear()
            return render_template('giris.html',hata='Çok fazla hatalı doğrulama kodu; hesap geçici olarak kilitlendi. %d dakika sonra yeniden deneyin ya da yöneticinize başvurun.' % kullanicilar.KILIT_DAKIKA),429
        # Kilit + sayım + kod denetimi tek işlemde (paralel isteklerle sınır aşılamaz); yukarıdaki iki denetim yalnız hızlı yol.
        tur=iki_adim.kod_dene(c,ad,request.form.get('kod',''),ip(),kullanicilar.KILIT_DAKIKA,ip_sinir=20)
        if tur=='ip_sinir':
            guvenlik_gunlugu('GIRIS_SINIR');iki_adim.on_giris_sil(c,numara);session.clear()
            return render_template('giris.html',hata='Çok fazla giriş denemesi. 15 dakika bekleyin.'),429
        if tur=='kilitli':
            iki_adim.on_giris_sil(c,numara);session.clear()
            return render_template('giris.html',hata='Çok fazla hatalı doğrulama kodu; hesap geçici olarak kilitlendi. %d dakika sonra yeniden deneyin ya da yöneticinize başvurun.' % kullanicilar.KILIT_DAKIKA),429
        if tur in ('totp','kurtarma'):
            iki_adim.on_giris_sil(c,numara)
            _oturum_ac(c,u,'iki adımlı doğrulama: '+('kurtarma kodu' if tur=='kurtarma' else 'uygulama kodu'))
            yanit=redirect(_guvenli_yol(veri.get('sonraki') or '/'))
            if request.form.get('guven')=='1' and guven>0:
                belirtec=iki_adim.cihaz_ekle(c,ad,guven,ip(),request.headers.get('User-Agent'))
                yanit.set_cookie(CIHAZ_CEREZI,belirtec,max_age=guven*86400,path='/',secure=secure,httponly=True,samesite='Lax')
            if tur=='kurtarma':
                kalan=iki_adim.kalan_kurtarma(c,ad)
                flash('Kurtarma koduyla girdiniz; %d kod kaldı.%s' % (kalan,' Kodlarınız azaldı: "İki adımlı doğrulama" sayfasından yeni kurtarma kodları üretin.' if kalan<=iki_adim.KURTARMA_UYARI_ESIGI else ''))
            return yanit
        kilit=tur=='kilit'
        guvenlik_gunlugu('GIRIS_KILIT' if kilit else 'IKI_ADIM_HATA',ad)
        time.sleep(.3)
        if kilit:
            iki_adim.on_giris_sil(c,numara);session.clear()
            return render_template('giris.html',hata='Çok fazla hatalı doğrulama kodu; hesap %d dakika kilitlendi.' % kullanicilar.KILIT_DAKIKA),429
        hata='Kod doğrulanamadı. Uygulamadaki güncel 6 haneli kodu ya da bir kurtarma kodunu girin. Kalan deneme: %d.' % max(0,iki_adim.KOD_DENEME-iki_adim.son_hatalar(c,ad))
    return render_template('giris_kod.html',hata=hata,guven_gun=guven,kalan_sn=kalan_sn,kullanici_adi=ad),durum

@app.route('/cikis',methods=['POST'])
def cikis():
    if g.k:
        # İmzalı çerez sunucuda tutulmaz; sürüm artırılmadan eski çerez 12 saat daha geçerli kalır.
        c=baglanti()
        with db.transaction(c):
            c.execute('UPDATE panel_kullanicilari SET session_version=session_version+1 WHERE id=?',(g.k['id'],))
            db.denetim_yaz(c,g.k['kullanici_adi'],'cikis',ip=ip(),hedef_turu='hesap',hedef_id=g.k['kullanici_adi'])
    session.clear()
    return redirect(url_for('giris'))

SIFRE_HATA_SINIRI=5;SIFRE_BEKLEME_DK=10

@app.route('/sifre',methods=['GET','POST'])
@giris_gerekli
def sifre_degistir():
    hata=None
    if request.method=='POST':
        ad=g.k['kullanici_adi'];eski=request.form.get('eski','');s=request.form.get('yeni','');c=baglanti()
        # Mevcut parola denemeleri giriş kilidini ETKİLEMEZ (oturum zaten açık); ayrı küçük sayaç: 10 dakikada 5 hata → bekleme.
        esik=(datetime.now()-timedelta(minutes=SIFRE_BEKLEME_DK)).strftime('%Y-%m-%d %H:%M:%S')
        hatalar=c.execute("SELECT COUNT(*) FROM denetim WHERE islem='sifre_hata' AND kullanici=? AND zaman>?",(ad,esik)).fetchone()[0]
        if hatalar>=SIFRE_HATA_SINIRI:
            hata='Çok fazla hatalı deneme; %d dakika sonra tekrar deneyin. Giriş hesabınız kilitlenmedi.' % SIFRE_BEKLEME_DK
        elif not kullanicilar.parola_dogru(AYAR,ad,eski):
            hata='Mevcut parolanız yanlış.'
            db.denetim_yaz(c,ad,'sifre_hata',ip=ip(),hedef_turu='hesap',hedef_id=ad)
            time.sleep(.3)
        elif kullanicilar.parola_politikasi(ad,s,eski): hata=kullanicilar.parola_politikasi(ad,s,eski)
        elif s!=request.form.get('yeni2'): hata='Yeni parolalar aynı değil.'
        else:
            u=kullanicilar.guncelle(AYAR,g.k['kullanici_adi'],sifre=s,sifre_degistir=0)
            session['sv']=u['session_version']
            db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'sifre_degisti',ip=ip())
            flash('Parola değiştirildi.'); return redirect(url_for('ana'))
    return render_template('sifre.html',hata=hata)

def _iki_adim_parola(ad,sifre):
    """İki adımlı doğrulama sayfasında mevcut parola denetimi (/sifre ile aynı küçük sayaç; giriş kilidine dokunmaz)."""
    c=baglanti();esik=(datetime.now()-timedelta(minutes=SIFRE_BEKLEME_DK)).strftime('%Y-%m-%d %H:%M:%S')
    if c.execute("SELECT COUNT(*) FROM denetim WHERE islem='sifre_hata' AND kullanici=? AND zaman>?",(ad,esik)).fetchone()[0]>=SIFRE_HATA_SINIRI:
        raise ValueError('Çok fazla hatalı parola denemesi; %d dakika sonra tekrar deneyin.' % SIFRE_BEKLEME_DK)
    if not kullanicilar.parola_dogru(AYAR,ad,sifre):
        db.denetim_yaz(c,ad,'sifre_hata',ip=ip(),hedef_turu='hesap',hedef_id=ad);time.sleep(.3)
        raise ValueError('Mevcut parolanız yanlış.')

IKI_ADIM_KAPAT_KILIT='Çok fazla hatalı doğrulama kodu; hesap geçici olarak kilitlendi. %d dakika sonra yeniden deneyin. İki adımlı doğrulama açık kaldı.' % kullanicilar.KILIT_DAKIKA

@app.route('/profil/iki-adim',methods=['GET','POST'],endpoint='iki_adim')
@giris_gerekli
def iki_adim_sayfasi():
    """2.4.1: iki adımlı doğrulama (Google Authenticator vb.) kurulumu, kurtarma kodları, güvenilen cihazlar, kapatma."""
    c=baglanti();ad=g.k['kullanici_adi'];hata=None;kurtarma=None;durum=200
    u=kullanicilar.bul(AYAR,ad);acik=iki_adim.acik_mi(u);zorunlu=iki_adim.zorunlu_mu(u,conn=c)
    if request.method=='POST':
        op=request.form.get('islem','')
        try:
            if op=='baslat':
                if acik:_iki_adim_parola(ad,request.form.get('sifre',''))  # yeniden kurulum: oturum çalınmışsa anahtar değiştirilemesin
                iki_adim.bekleyen_sil(c,ad);iki_adim.bekleyen_al(c,ad,olustur=True)
                return redirect(url_for('iki_adim')+'#kurulum')
            elif op=='iptal':
                iki_adim.bekleyen_sil(c,ad);flash('Kurulum iptal edildi; hesabınızda değişiklik olmadı.');return redirect(url_for('iki_adim'))
            elif op=='etkinlestir':
                sir=iki_adim.bekleyen_al(c,ad)
                if not sir and acik:
                    # Kurtarma kodları sayfası yenilendi (form yeniden gönderildi): kurulum zaten tamam, yanıltıcı hata verme.
                    flash('İki adımlı doğrulama zaten açık; kurtarma kodları yalnız bir kez gösterilir (gerekirse yenilerini üretin).')
                    return redirect(url_for('iki_adim'))
                if not sir:raise ValueError('Kurulum süresi doldu (15 dakika). "İki adımlı doğrulamayı aç" düğmesine yeniden basın; uygulamaya yeni anahtarı ekleyin.')
                kurtarma=[iki_adim.kurtarma_goster(k) for k in iki_adim.etkinlestir(c,ad,sir,request.form.get('kod',''),ad,ip())]
            elif op=='kapat':
                if not acik:raise ValueError('İki adımlı doğrulama zaten kapalı.')
                if zorunlu:raise ValueError('Yönetici kararıyla iki adımlı doğrulama hesabınız için zorunlu; kapatılamaz. Telefon değiştirdiyseniz "Yeniden kur"u kullanın.')
                if kullanicilar.kilitli_mi(u) or iki_adim.son_hatalar(c,ad)>=iki_adim.KOD_DENEME:
                    raise ValueError(IKI_ADIM_KAPAT_KILIT)
                _iki_adim_parola(ad,request.form.get('sifre',''))
                # Giriş adımıyla aynı sınır: 5 dakikada 5 hatalı kod → hesap kilidi; kilitliyken kod hiç denenmez.
                tur=iki_adim.kod_dene(c,ad,request.form.get('kod',''),ip(),kullanicilar.KILIT_DAKIKA)
                if tur=='kilitli':raise ValueError(IKI_ADIM_KAPAT_KILIT)
                if tur not in ('totp','kurtarma'):
                    guvenlik_gunlugu('GIRIS_KILIT' if tur=='kilit' else 'IKI_ADIM_HATA',ad);time.sleep(.3)
                    raise ValueError(IKI_ADIM_KAPAT_KILIT if tur=='kilit' else 'Doğrulama kodu ya da kurtarma kodu hatalı. Kalan deneme: %d.' % max(0,iki_adim.KOD_DENEME-iki_adim.son_hatalar(c,ad)))
                iki_adim.kapat(c,ad,ad,ip());flash('İki adımlı doğrulama kapatıldı; güvenilen cihazlar ve kurtarma kodları silindi.')
                return redirect(url_for('iki_adim'))
            elif op=='kurtarma_yenile':
                _iki_adim_parola(ad,request.form.get('sifre',''))
                kurtarma=[iki_adim.kurtarma_goster(k) for k in iki_adim.kurtarma_yenile(c,ad,ad,ip())]
            elif op=='cihaz_kaldir':
                try:cid=int(request.form.get('id',''))
                except ValueError:raise ValueError('Cihaz bulunamadı.')
                flash('Cihaz kaldırıldı; o tarayıcıda bir sonraki girişte kod sorulur.' if iki_adim.cihaz_kaldir(c,ad,cid,ad,ip()) else 'Cihaz zaten kaldırılmıştı.')
                return redirect(url_for('iki_adim')+'#cihazlar')
            elif op=='cihazlar_kaldir':
                n=iki_adim.cihazlari_kaldir(c,ad,ad,ip());flash('%d güvenilen cihaz kaldırıldı.' % n);return redirect(url_for('iki_adim')+'#cihazlar')
            else:abort(400)
        except ValueError as e:
            hata=str(e);durum=400
        u=kullanicilar.bul(AYAR,ad);acik=iki_adim.acik_mi(u)
    sir=iki_adim.bekleyen_al(c,ad)
    kurulum=None
    if sir and not kurtarma:
        uri=iki_adim.otpauth_uri(ad,sir)
        kurulum=dict(sir=sir,gruplu=iki_adim.sir_grupla(sir),uri=uri,qr=qr_svg.svg(uri,baslik='İki adımlı doğrulama QR kodu'))
    return render_template('iki_adim.html',acik=acik,zorunlu=zorunlu,kurulum=kurulum,kurtarma=kurtarma,hata=hata,
                           kalan=iki_adim.kalan_kurtarma(c,ad) if acik else 0,esik=iki_adim.KURTARMA_UYARI_ESIGI,
                           cihazlar=iki_adim.cihazlar(c,ad) if acik else [],guven_gun=iki_adim.guven_gun(c),
                           kurulum_tarihi=(u or {}).get('iki_adim_tarih'),sunucu_epoch=int(time.time()),
                           sunucu_saati=datetime.now().strftime('%H:%M:%S'),politika=iki_adim.politika(c)),durum

def durum_bilgisi():
    c=baglanti(); raw=db.ayar_al(c,'son_ice_aktarim')
    return {'son_ice_aktarim':json.loads(raw) if raw else None,'bot':bot_yonetim.bot_calisiyor_mu(AYAR),
            'log_son':db.ayar_al(c,'son_degisiklik'),'kuyruk_bekleyen':0,'bekleyen_islem':0,
            'surum':SURUM,'veritabani':'SQLite WAL','gorsel_klasor':'Özel yerel arşiv','paylasim_modu':False}

def _acik_sorular(allowed):
    """Bana yöneltilmiş ve henüz yanıtlanmamış soru sayısı (yalnız izinli projeler)."""
    if not allowed:return 0
    places=','.join('?' for _ in allowed)
    return baglanti().execute('''SELECT COUNT(*) FROM yorumlar y JOIN kayitlar k ON k.id=y.kayit_id
        WHERE y.tur='soru' AND y.alici=? AND k.proje IN ('''+places+''')
        AND NOT EXISTS (SELECT 1 FROM yorumlar r WHERE r.yanit_id=y.id)''',(g.k['kullanici_adi'],*allowed)).fetchone()[0]

def _son_islemler(allowed,limit=10):
    """İşlem Geçmişi ile aynı kapsam kuralı: süperadmin her şeyi, admin yalnız izinli kayıt hareketlerini görür."""
    from .guvenli_log import log_row
    if g.yk['admin']:where,params='1=1',[]
    elif allowed:where,params='k.proje IN ('+','.join('?' for _ in allowed)+')',list(allowed)
    else:return []
    gizli_sql,gizli_par=_gizli_kayit_sql('k',allowed,sol_birlesim=True)
    if gizli_sql:where+=' AND '+gizli_sql;params=[*params,*gizli_par]
    rows=[]
    # Kullanıcının kendi "okundu" hareketleri akışı doldurmasın; İşlem Geçmişi'nde görünmeye devam eder.
    for row in baglanti().execute("SELECT d.*,k.id record_id FROM denetim d LEFT JOIN kayitlar k ON k.anahtar=d.anahtar WHERE "+where+" AND d.islem<>'bildirim_okundu' ORDER BY d.id DESC LIMIT ?",[*params,limit]):
        item=log_row(row)
        if item.get('proje') and item['proje'] not in allowed and not g.yk['admin']:continue
        rows.append(item)
    return rows

# Ana sayfa "Son işlemler" cümle biçimi. Kodlar: panel.py, bot.py, bot_yonetim.py, katalog.py, kullanicilar.py, yetki.py,
# discussion.py, donusum_isleri.py, bildirim_gecmisi.py içindeki denetim_yaz çağrıları.
ISLEM_ADLARI={'giris':'Giriş yaptı','giris_hata':'Hatalı giriş denemesi','onayla':'Kaydı onayladı','onay_kaldir':'Onayı kaldırdı','duzenle':'Kaydı düzenledi','sil':'Kaydı sildi','geri_al':'Kaydı geri aldı','yorum_ekle':'Yorum yazdı','soru_yonelt':'Soru yöneltti','yanit_ekle':'Yanıt verdi','gyazo_istek':'Gyazo dönüşümü istedi','disa_aktar':'Excel çıktısı aldı','dosya_kontrol':'Dosya kontrolü yaptı','kullanici_ekle':'Kullanıcı ekledi','kullanici_guncelle':'Kullanıcıyı güncelledi','kilit_ac':'Hesap kilidini açtı','sifre_degisti':'Parolasını değiştirdi','cikis':'Çıkış yaptı','giris_kilit':'Hesap kilitlendi','giris_sinir':'IP giriş sınırına ulaştı','sifre_hata':'Hatalı mevcut parola','csrf_hata':'Geçersiz CSRF gönderimi','arsiv_esle':'Arşiv görseli eşledi','beklenen_proje':'Beklenen projeyi atadı','yeni_kayit':'Yeni kanıt ekledi','sunucu_hata':'Sunucu hatası',
 'bildirim_okundu':'Bildirimleri okudu','ice_aktar':'İçe aktarım yaptı','yetki_kanonik':'Yetki tanımı düzeltildi',
 'telegram_kayit':'Telegram ile kanıt ekledi','bot_kayit':'Telegram ile kanıt ekledi','panel_kanit_ekle':'Panelden kanıt ekledi','telegram_onay':'Telegram botuna şifreyle giriş yaptı','telegram_admin_giris':'Telegram botuna yönetici olarak giriş yaptı','telegram_admin_giris_hata':'Telegram botunda yönetici parolasını yanlış girdi','telegram_engel':'Telegram botunda engellendi','telegram_eski_buton':'Telegram botunda eski düğmeye bastı','telegram_yanlis_adim_butonu':'Telegram botunda yanlış adımda düğmeye bastı',
 'bot_bakim_ac':'Bakım modunu açtı','bot_bakim_kapat':'Bakım modunu kapattı','bot_bakim':'Bakım modunu değiştirdi','bot_onayla':'Telegram kullanıcısını onayladı','bot_onay_kaldir':'Telegram onayını kaldırdı','bot_engelle':'Telegram kullanıcısını engelledi','bot_engel_kaldir':'Telegram engelini kaldırdı','bot_tam_sifirla':'Telegram kullanıcısını tam sıfırladı','bot_oturum_temizle':'Bot oturumunu temizledi','bot_kontrol':'Botu duraklattı / sürdürdü','bot_yedek':'Veritabanı yedeği aldı','bot_inbox_tekrar':'Bekleyen bot mesajlarını yeniden denedi','bot_kategori_kaydet':'Bot kategorisini kaydetti','bot_kategori_sil':'Bot kategorisini pasife aldı','bot_kategori_yayinla':'Bot kategorilerini yayınladı',
 'katalog_proje_kaydet':'Proje tanımını kaydetti','katalog_kategori_kaydet':'Kategori tanımını kaydetti',
 'gyazo_link_guncelle':'Gyazo bağlantısını güncelledi','gyazo_link_yerel_korundu':'Gyazo bağlantısı eklenmedi, yerel görsel korundu',
 'hatirlatma_uret':'Onay bekleyenler için hatırlatma bildirimi üretti',
 'api_anahtar_olustur':'API anahtarı oluşturdu','api_anahtar_iptal':'API anahtarını iptal etti','rapor_aktar':'Personel raporunu indirdi'}
# İşlem Geçmişi tablosu için kısa ad biçimi.
DENETIM_ADLARI={'giris':'Giriş','giris_hata':'Hatalı giriş','onayla':'Onay','onay_kaldir':'Onay kaldırma','duzenle':'Düzenleme','sil':'Silme','geri_al':'Geri alma','yorum_ekle':'Yorum','soru_yonelt':'Soru','yanit_ekle':'Yanıt','gyazo_istek':'Gyazo isteği','disa_aktar':'Excel çıktısı','dosya_kontrol':'Dosya kontrolü','kullanici_ekle':'Kullanıcı ekleme','kullanici_guncelle':'Kullanıcı güncelleme','kilit_ac':'Kilit açma','sifre_degisti':'Şifre değişimi','cikis':'Çıkış','giris_kilit':'Hesap kilidi','giris_sinir':'IP giriş sınırı','sifre_hata':'Hatalı mevcut parola','csrf_hata':'Geçersiz CSRF gönderimi','arsiv_esle':'Arşiv eşleme','beklenen_proje':'Beklenen proje','yeni_kayit':'Yeni kanıt','bildirim_okundu':'Bildirim okundu','sunucu_hata':'Sunucu hatası','ice_aktar':'İçe aktarım','yetki_kanonik':'Yetki düzeltme',
 'katalog_proje_kaydet':'Proje kaydı','katalog_kategori_kaydet':'Kategori kaydı',
 'telegram_kayit':'Telegram ile kanıt','bot_kayit':'Telegram ile kanıt','panel_kanit_ekle':'Panelden kanıt','telegram_onay':'Telegram: şifreyle giriş','telegram_admin_giris':'Telegram: yönetici girişi','telegram_admin_giris_hata':'Telegram: yönetici parolası hatası','telegram_engel':'Telegram: engellendi','telegram_eski_buton':'Telegram: eski düğme','telegram_yanlis_adim_butonu':'Telegram: yanlış adım düğmesi',
 'bot_onayla':'Bot: kullanıcı onayı','bot_onay_kaldir':'Bot: onay kaldırma','bot_engelle':'Bot: engelleme','bot_engel_kaldir':'Bot: engel kaldırma','bot_tam_sifirla':'Bot: tam sıfırlama','bot_oturum_temizle':'Bot: oturum temizleme','bot_bakim':'Bot: bakım modu','bot_bakim_ac':'Bot: bakım modu açıldı','bot_bakim_kapat':'Bot: bakım modu kapatıldı','bot_kontrol':'Bot: duraklat/sürdür','bot_yedek':'Bot: veritabanı yedeği','bot_inbox_tekrar':'Bot: tekrar deneme','bot_kategori_kaydet':'Bot: kategori kaydı','bot_kategori_sil':'Bot: kategori pasife','bot_kategori_yayinla':'Bot: kategori yayını',
 'gyazo_link_guncelle':'Gyazo bağlantısı','gyazo_link_yerel_korundu':'Gyazo: yerel görsel korundu','hatirlatma_uret':'Hatırlatma bildirimi',
 'api_anahtar_olustur':'API anahtarı oluşturma','api_anahtar_iptal':'API anahtarı iptali','rapor_aktar':'Personel raporu çıktısı'}

ISLEM_ADLARI['tg_duzeltme']='Telegram kaydını düzeltti';DENETIM_ADLARI['tg_duzeltme']='Telegram: kayıt düzeltme'  # 2.4.0 (Takım C)
ISLEM_ADLARI.update(iki_adim.ISLEM_ADLARI);DENETIM_ADLARI.update(iki_adim.DENETIM_ADLARI)  # 2.4.1: iki adımlı doğrulama
def islem_adi(code,adlar=None):
    """Sözlükte olmayan kod ham yazılmaz; alt çizgiler boşluğa çevrilir (kod ikinci kez basılmaz)."""
    code=str(code or '')
    return (adlar or ISLEM_ADLARI).get(code) or code.replace('_',' ')

def _onay_metni(value):
    return 'onaylı' if str(value or '').strip().lower() in ('1','true','onayli','onaylı') else 'bekliyor'

def _denetim_ayrinti(item):
    """İşlem Geçmişi "Ayrıntı" sütunu: kt/silindi gibi 0/1 değerleri okunur metne çevrilir.
    Dönüş: (satırlar, açılır-kapanır mı). Serbest eski/yeni değerleri "Önceki / yeni" olarak katlanır."""
    code=str(item.get('islem') or '');eski=item.get('eski');yeni=item.get('yeni')
    if code in ('onayla','onay_kaldir'):return ['Onay: '+_onay_metni(eski)+' → '+_onay_metni(yeni)],False
    if code in ('sil','geri_al'):return ['Silindi' if code=='sil' else 'Geri alındı'],False
    if code=='bildirim_okundu':
        try:adet=int(json.loads(yeni or '{}').get('adet') or 0)
        except (ValueError,TypeError,AttributeError):adet=0
        return [str(adet)+' bildirim okundu' if adet else 'Bildirimler okundu'],False
    lines=[]
    if eski:lines.append('Önceki: '+str(eski))
    if yeni:lines.append('Yeni: '+str(yeni))
    return lines,True

@app.route('/')
@giris_gerekli
def ana():
    cards=[];allowed=_allowed();kpi=dict(bekleyen=0,bugun=0,bugun_onay=0,toplam=0,onayli=0,geciken=0);gun=_hatirlatma_gun()
    gizli_sql,gizli_par=_gizli_kayit_sql('',allowed);gizli_projeler=set(gizli_par)  # gizle: kt'siz projelerde yalnız onaylılar sayılır
    kt_var=bool(_kt_projeleri(allowed))
    for p in allowed:
        row=baglanti().execute('''SELECT SUM(kt=0 AND silindi=0) bekleyen,
            SUM(kt=1 AND silindi=0) onayli,SUM(silindi=1) silinen,
            SUM(date(tarih)=date('now','localtime') AND silindi=0) bugun,
            SUM(kt=1 AND silindi=0 AND date(kt_zaman)=date('now','localtime')) bugun_onay,COUNT(*) toplam,
            SUM(kt=0 AND silindi=0 AND '''+_GECIKEN_SQL+''') geciken
            FROM kayitlar WHERE proje=?'''+(' AND '+gizli_sql if gizli_sql else ''),(gun,p,*gizli_par)).fetchone()
        card={'proje':p,**{k:row[k] or 0 for k in row.keys()}}
        card['etiket']=next((x['label'] for x in _all_project_info() if x['code']==p),p)
        card['gizli']=p in gizli_projeler  # onay bekleyen/silinen bağlantıları üretilmez, sayaçlar 0
        cards.append(card)
        card['kt']=yetki.izin(g.yk,p,'kt')
        for key in list(kpi):
            # 2.4.0: "Onay bekleyen" (ve gecikenler) yalnız onay yetkisi olan projeleri sayar; diğerleri ayrı notta.
            # Hiçbir projede onay yetkisi olmayan kullanıcıda eskisi gibi tüm görebildiği bekleyenler sayılır (Kayıtlar sekmesiyle aynı).
            if key.endswith('_oku'): continue
            if key in ('bekleyen','geciken') and not card['kt'] and kt_var: kpi[key+'_oku']=kpi.get(key+'_oku',0)+card[key]; continue
            kpi[key]+=card[key]
    kpi.setdefault('bekleyen_oku',0); kpi.setdefault('geciken_oku',0)
    kpi['acik_soru']=_acik_sorular(allowed)
    bekleyen_baglanti=any(p not in gizli_projeler for p in allowed)
    po=_personel_ozet_hazirla(allowed,ana_sayfa=True) if allowed else None
    return render_template('ana.html',kartlar=cards,durum=durum_bilgisi(),kpi=kpi,son_islemler=_son_islemler(allowed),islem_adlari=ISLEM_ADLARI,hatirlatma_gun=gun,bekleyen_baglanti=bekleyen_baglanti,gizli_proje_var=bool(gizli_projeler),po=po)

# ---------- 2.3.4: personel bazında kanıt özeti (ana sayfa kartı + /rapor/personel + Excel/CSV) ----------
ANA_OZET_SATIR=10

def _personel_ozet_filtre(allowed):
    """İstek parametreleri → doğrulanmış filtre. İzinsiz proje 403; diğer geçersiz değerler varsayılana döner (uyarı).
    Kayıtlar sayfasıyla aynı kural: seçili projelerin hepsinde kt yetkisi yoksa ve ONAYSIZ_GORUNUM=gizle ise durum onaylıya sabitlenir."""
    try: f,hatalar,uyarilar=personel_ozeti.filtre_coz(request.args,allowed,bugun=datetime.now().date())
    except PermissionError: abort(403)
    secili=[f['proje']] if f['proje'] else list(allowed)
    kt_yok=_kt_yok(secili); gizle=_onaysiz_modu()=='gizle'
    f['yalniz_onayli']=bool(secili) and gizle and len(kt_yok)==len(secili)
    if f['yalniz_onayli']: f['durum']='onayli'
    f['gizli_onaysiz']=gizle and bool(kt_yok)
    gizli=_gizli_kayit_sql('',secili)
    # 2.3.5: kategori seçenekleri seçili kapsamdan (proje seçiliyse yalnız o proje) gelir; yazılan değer katalogdaki harf biçimine eşlenir.
    f['kategori_secenekleri']=personel_ozeti.kategori_secenekleri(baglanti(),secili,gizli)
    f['kategori']=personel_ozeti.kategori_kanonik(f['kategori_secenekleri'],f.get('kategori') or '')
    return f,hatalar+uyarilar,gizli

PO_SUZGEC_ADLARI=('proje','donem','durum','grup','sutun','kategori','tarih1','tarih2')

def _personel_ozet_url(endpoint,f,**ek):
    a={k:f[k] for k in ('proje','donem','durum','grup','sutun','kategori') if f.get(k)}
    if f.get('donem')=='ozel': a.update(tarih1=f.get('tarih1') or None,tarih2=f.get('tarih2') or None)
    if f.get('esik') and f['esik']!=personel_ozeti.VARSAYILAN_ESIK: a['esik']=f['esik']  # 2.3.7: Durumlar eşiği (varsayılan %50 adrese yazılmaz)
    a.update(ek)
    return url_for(endpoint,**{k:v for k,v in a.items() if v not in (None,'')})

def _personel_ozet_kayit_url(f,satir=None,sutun=None):
    """Kayıtlar listesine bağlantı: aynı proje + dönem + durum (+ kategori süzgeci + personel/ekleyen + kategori/tip). Silinenler hariç tutulur.
    2.3.5: kategorisi boş kayıtlar '__bos__' ile açılır; kişi kartlarındaki kutular da bu yardımcıyı kullanır."""
    a=dict(durum=f['durum'],silinmemis='1')
    if f.get('proje'): a['proje']=f['proje']
    if f.get('kategori'): a['kategori']=f['kategori']
    if f.get('tarih1'): a['tarih1']=f['tarih1']
    if f.get('tarih2'): a['tarih2']=f['tarih2']
    if satir is not None:
        a['ekleyen_ad' if f['grup']=='ekleyen' else 'personel']=satir['deger'] or personel_ozeti.BOS_DEGER
    if sutun is not None:
        if f['sutun']=='kategori':
            a['kategori']=personel_ozeti.BOS_DEGER if sutun['bos'] else sutun['deger']
        else: a['tip']=sutun['deger'] or personel_ozeti.BOS_DEGER
    return url_for('kayitlar',**a)

def _po_durum_baglantilari(f,onceki_f,d):
    """2.3.7: Durumlar satırlarının bağlantıları; kart kutularıyla aynı yardımcı (sayı ile açılan liste birebir tutar).
    hucre → o kişinin o sütundaki kayıtları; kisi → kişinin dönemdeki tüm kayıtları; bekleyen → kişinin onay bekleyenleri;
    onceki → kişinin önceki dönemdeki kayıtları (bu dönem hiç kaydı olmayanlar)."""
    for grup in d['tum_gruplar']:
        for o in grup['ogeler']:
            satir=dict(deger=o['kisi_deger'])
            if o['baglanti']=='hucre': o['url']=_personel_ozet_kayit_url(f,satir=satir,sutun=dict(deger=o['sutun_deger'],bos=o['sutun_bos']))
            elif o['baglanti']=='bekleyen': o['url']=_personel_ozet_kayit_url(dict(f,durum='bekleyen'),satir=satir)
            elif o['baglanti']=='onceki' and onceki_f: o['url']=_personel_ozet_kayit_url(onceki_f,satir=satir)
            else: o['url']=_personel_ozet_kayit_url(f,satir=satir)

PO_KART_ILK=6   # 2.3.5: kişi kartları — ilk 6 görünür, "Daha fazla göster" her basışta 12 kart daha açar
PO_KART_ADIM=12

def _personel_ozet_hazirla(allowed,ana_sayfa=False):
    f,uyarilar,gizli=_personel_ozet_filtre(allowed)
    o=personel_ozeti.personel_ozeti(baglanti(),allowed,gizli,f)
    bilgi=o['sutun_bilgi']
    if ana_sayfa:
        # Ana sayfa kartı: sıfır toplamlı sütunlar gizlenir, ilk 10 satır gösterilir.
        bilgi=[b for b in bilgi if b['toplam']] or bilgi[:6]
    for b in bilgi:b['url']=_personel_ozet_kayit_url(f,sutun=b) if b['toplam'] else None
    satirlar=o['satirlar'][:ANA_OZET_SATIR] if ana_sayfa else o['satirlar']
    renkler={b['ad']:b['renk'] for b in o['sutun_bilgi']}
    # 2.3.5: kişi kartları tüm satırlar için hazırlanır (tablo ana sayfada ilk 10 ile sınırlı kalır).
    # Kart kutuları ("CVPS 68"): yalnız sıfırdan büyük sütunlar, sayıya göre azalan; bağlantılar hücre bağlantısıyla aynıdır.
    for x in o['satirlar']:
        x['url']=_personel_ozet_kayit_url(f,satir=x)
        x['url_sutun']={b['ad']:(_personel_ozet_kayit_url(f,satir=x,sutun=b) if x['sutunlar'].get(b['ad']) else None) for b in o['sutun_bilgi']}
        x['paylar']=[dict(ad=b['ad'],renk=b['renk'],n=x['sutunlar'].get(b['ad'],0),oran=round(x['sutunlar'].get(b['ad'],0)*100/x['toplam'],1)) for b in o['sutun_bilgi'] if x['toplam'] and x['sutunlar'].get(b['ad'])]
        x['cipler']=sorted((dict(ad=ad,n=n,renk=renkler.get(ad,'#94a3b8'),url=x['url_sutun'].get(ad)) for ad,n in x['sutunlar'].items() if n),
                           key=lambda c:(-c['n'],c['ad']==personel_ozeti.BOS,c['ad'].casefold()))
    # 2.3.7: Durumlar — aynı süzgeçlerle önceki dönem de sayılır (hepsi / başlangıçsız özel aralıkta karşılaştırma yok).
    onceki_f=personel_ozeti.onceki_filtre(f,datetime.now().date())
    onceki_o=personel_ozeti.personel_ozeti(baglanti(),allowed,gizli,onceki_f) if onceki_f else None
    durum_ozeti=personel_ozeti.durumlar(o,onceki_o,f.get('esik',personel_ozeti.VARSAYILAN_ESIK),f)
    _po_durum_baglantilari(f,onceki_f,durum_ozeti)
    kart_endpoint='ana' if ana_sayfa else 'rapor_personel'
    # Ana sayfadaki "Tüm tablo ve rapor": süzgeç seçilmediyse yalın adres (rapor sayfası kişinin son süzgeçlerini uygulayabilsin).
    suzgecli=any(request.args.get(k) for k in PO_SUZGEC_ADLARI)
    o.update(f=f,uyarilar=uyarilar,gosterilen_sutunlar=bilgi,gosterilen_satirlar=satirlar,toplam_url=_personel_ozet_kayit_url(f),
             kartlar=o['satirlar'],kart_ilk=PO_KART_ILK,kart_adim=PO_KART_ADIM,kartlar_hepsi=request.args.get('kartlar') in ('hepsi','1'),
             kartlar_baski=request.args.get('yazdir')=='1' and request.args.get('kartlar')=='1',
             kartlar_hepsi_url=_personel_ozet_url(kart_endpoint,f,kartlar='hepsi')+'#po-kartlar',
             kategori_secenekleri=f['kategori_secenekleri'],
             kategori_secenekte=not f.get('kategori') or any(s['deger']==f['kategori'] for s in f['kategori_secenekleri']),
             kalan=max(0,len(o['satirlar'])-len(satirlar)),
             durum_ozeti=durum_ozeti,ana_sayfa=ana_sayfa,esikler=personel_ozeti.ESIKLER,
             durumlar_url=_personel_ozet_url('rapor_personel',f)+'#durumlar',
             proje_secenekleri=[p for p in _all_project_info() if p['code'] in allowed],
             donemler=personel_ozeti.DONEMLER,durumlar=personel_ozeti.DURUMLAR,gruplar=personel_ozeti.GRUPLAR,sutun_secenekleri=personel_ozeti.SUTUNLAR,
             rapor_url=(_personel_ozet_url('rapor_personel',f) if suzgecli or not ana_sayfa else url_for('rapor_personel')),xlsx_url=_personel_ozet_url('rapor_personel_xlsx',f),
             csv_url=_personel_ozet_url('rapor_personel_csv',f),yazdir_url=_personel_ozet_url('rapor_personel',f,yazdir='1'),
             olusturma=datetime.now().strftime('%d.%m.%Y %H:%M'),durum_adi=personel_ozeti.DURUM_ADLARI.get(f['durum'],''),
             proje_etiketi=(next((p['label'] for p in _all_project_info() if p['code']==f['proje']),f['proje']) if f['proje'] else 'Tüm yetkili projeler'))
    return o

def _personel_ozet_dosya_adi(f,uzanti):
    kat=('-'+personel_ozeti.dosya_parcasi(f['kategori'])) if f.get('kategori') else ''
    return 'rapor-personel-%s-%s%s-%s.%s' % ((f['proje'] or 'tum').lower(),f['donem'],kat,datetime.now().strftime('%Y-%m-%d'),uzanti)

@app.route('/rapor/personel')
@giris_gerekli
def rapor_personel():
    allowed=_allowed()
    po=_personel_ozet_hazirla(allowed) if allowed else None
    # 2.3.5: "hatirlanan=1" sayfanın tarayıcıda hatırlanan süzgeçlerle açıldığını, "sifirla=1" hatırlananların silinmesini bildirir (rapor.js).
    return render_template('rapor_personel.html',po=po,yazdir=request.args.get('yazdir')=='1',
                           hatirlanan=request.args.get('hatirlanan')=='1',sifirla=request.args.get('sifirla')=='1')

@app.route('/rapor/personel.xlsx')
@giris_gerekli
def rapor_personel_xlsx():
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    allowed=_allowed()
    if not allowed: abort(403)
    po=_personel_ozet_hazirla(allowed); f=po['f']
    baslik,satirlar,toplam=personel_ozeti.tablo_satirlari(po)
    wb=openpyxl.Workbook(); ws=wb.active; ws.title='Özet'
    ws.append(baslik)
    for r in satirlar: ws.append(r)
    ws.append(toplam)
    koyu=PatternFill('solid',fgColor='1F2937'); acik=PatternFill('solid',fgColor='E8EFFF'); cizgi=Side(style='thin',color='9CA3AF')
    for cell in ws[1]:
        cell.font=Font(bold=True,color='FFFFFF'); cell.fill=koyu; cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    # 2.3.7: ikinci sayfa "Durumlar" — rapor sayfasındaki Durumlar bölümüyle aynı hesap (tüm satırlar, eşik Bilgi sayfasında).
    d=po['durum_ozeti']
    dbaslik,dsatirlar=personel_ozeti.durum_tablo_satirlari(d,po['sutun_adi'])
    wd=wb.create_sheet('Durumlar')
    wd.append(dbaslik)
    for r in dsatirlar: wd.append(r)
    if not dsatirlar: wd.append(['—','','','','','',d['kiyas_notu'] or 'Bu dönemde dikkat çeken bir durum yok.'])
    for cell in wd[1]:
        cell.font=Font(bold=True,color='FFFFFF'); cell.fill=koyu; cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    for satir in wd.iter_rows(min_row=2):
        satir[4].number_format='0.0'; satir[5].number_format='0%'
    for harf,gen in zip('ABCDEFG',(26,24,18,8,10,14,70)): wd.column_dimensions[harf].width=gen
    wd.freeze_panes='A2'
    if dsatirlar: wd.auto_filter.ref='A1:G%d' % wd.max_row
    son=ws.max_row
    for cell in ws[son]:
        cell.font=Font(bold=True); cell.fill=acik; cell.border=Border(top=cizgi)
    for i,b in enumerate(baslik,1):
        uzun=max([len(str(b))]+[len(str(r[i-1])) for r in satirlar]+[len(str(toplam[i-1]))])
        ws.column_dimensions[get_column_letter(i)].width=min(40,max(9,uzun+3))
    ws.freeze_panes='B2'
    ws.auto_filter.ref='A1:%s%d' % (get_column_letter(len(baslik)),max(1,son-1))
    bilgi=wb.create_sheet('Bilgi')
    for satir in (('Rapor','Personel bazında kanıtlar'),('Proje',po['proje_etiketi']),('Dönem',po['donem']['etiket']),
                  ('Durum',personel_ozeti.DURUM_ADLARI[f['durum']]),('Kategori',po['kategori_adi'] or 'Tüm kategoriler'),('Gruplama',po['grup_adi']),('Sütunlar',po['sutun_adi']),
                  ('Kişi',po['kisi_sayisi']),('Kanıt',po['kayit_sayisi']),
                  ('Durumlar eşiği','%%%d (%s)' % (d['esik'],d['esik_aciklama'])),
                  ('Ortalama','Kişi başına kayıt: %s' % d['genel_ortalama_tr']+(' · '+d['kiyas_notu'] if d['kiyas_notu'] else '')),
                  ('Önceki dönem',d['onceki']['etiket'] if d['onceki'] else 'Karşılaştırma yok (Tümü ya da başlangıçsız aralık)'),('Oluşturma',po['olusturma']),('Oluşturan',g.k['kullanici_adi']),
                  ('Not','Yalnız silinmemiş kayıtlar sayılır.'+(' Onay yetkiniz olmayan projelerde onay bekleyenler sayılmaz.' if f['gizli_onaysiz'] else ''))):
        bilgi.append([personel_ozeti.guvenli_hucre(v) for v in satir])
    bilgi.column_dimensions['A'].width=14; bilgi.column_dimensions['B'].width=60
    for cell in bilgi['A']: cell.font=Font(bold=True)
    stream=io.BytesIO(); wb.save(stream); stream.seek(0)
    db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'rapor_aktar',proje=f['proje'] or None,yeni='xlsx:%d' % po['kisi_sayisi'],ip=ip())
    return send_file(stream,as_attachment=True,download_name=_personel_ozet_dosya_adi(f,'xlsx'),mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/rapor/personel.csv')
@giris_gerekli
def rapor_personel_csv():
    import csv
    allowed=_allowed()
    if not allowed: abort(403)
    po=_personel_ozet_hazirla(allowed); f=po['f']
    baslik,satirlar,toplam=personel_ozeti.tablo_satirlari(po)
    out=io.StringIO()
    # Türkçe Excel'in beklediği biçim: UTF-8 BOM + noktalı virgül ayırıcı + CRLF.
    w=csv.writer(out,delimiter=';',lineterminator='\r\n',quoting=csv.QUOTE_MINIMAL)
    w.writerow(baslik)
    for r in satirlar: w.writerow(r)
    w.writerow(toplam)
    db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'rapor_aktar',proje=f['proje'] or None,yeni='csv:%d' % po['kisi_sayisi'],ip=ip())
    from flask import Response
    resp=Response(('\ufeff'+out.getvalue()).encode('utf-8'),mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition']='attachment; filename="%s"' % _personel_ozet_dosya_adi(f,'csv')
    return resp

SAYFA_BOYLARI=(24,48,96)

def _json_hata(code,message,**ek):
    """Kayit uclarinda hata: fetch/XHR ve POST isteklerine JSON (arayuz Turkce toast gosterir);
    tarayicida dogrudan acilan /kayit, /gorsel, /kucuk adresleri ise mevcut Turkce HTML hata sayfasini alir."""
    from flask import make_response
    if _json_bekleniyor() or request.method not in ('GET','HEAD'):
        abort(make_response(jsonify(ok=False,hata=message,kod=code,**ek),code))
    abort(code,message)

def _degisiklik_damgasi():
    """Kendi işleminden sonra arayüzün 'Yeni değişiklik var' şeridini kendi değişikliği için göstermemesi
    amacıyla zil yoklamasıyla aynı değişiklik damgası döndürülür (hesaplanamazsa None)."""
    try: return _scoped_counts()[1]
    except Exception: return None

def _tr_kucuk(value):
    """Türkçe'ye uygun büyük/küçük harf duyarsız karşılaştırma anahtarı (İ→i, I→ı)."""
    return str(value or '').replace('İ','i').replace('I','ı').casefold()

def _kategori_kanonik(cat,codes):
    """Kullanıcının yazdığı/seçtiği kategoriyi projelerdeki tanımlı adla (doğru harf biçimiyle) eşler."""
    if not cat: return cat
    try:
        kapsam=_scoped_categories(codes)
        # 2.3.5: değer kapsamdaki bir adla zaten harf duyarsız (casefold, SQL'deki UNICODE_NOCASE) eşleşiyorsa olduğu gibi kalır;
        # böylece personel raporundaki 'İPTAL' kutusu 'iptal' kayıtlarına değil kendi kayıtlarına gider. Türkçe eşleme yalnız elle yazılan değere uygulanır.
        if any(personel_ozeti.kirp(k).casefold()==cat.casefold() for k in kapsam): return cat
        return next((k for k in kapsam if _tr_kucuk(k)==_tr_kucuk(cat)),cat)
    except Exception: return cat

# 2.3.1 — Onaysız kayıt görünürlüğü ve bekleme süresi. Yaş = bugün − date(COALESCE(ilk_gorulme,tarih)); ? = gün eşiği.
_GECIKEN_SQL="julianday(date('now','localtime')) - julianday(date(COALESCE(NULLIF(ilk_gorulme,''),tarih))) >= ?"

def _hatirlatma_gun():
    # 2.4.0: panelden değiştirilen değer (veritabanı) önce; yoksa açılıştaki .env değeri (AYAR). Ayrıntı: app/ayarlar.py
    from . import ayarlar as calisma_ayarlari
    try: return max(1,int(calisma_ayarlari.ust('HATIRLATMA_GUN',AYAR.get('HATIRLATMA_GUN',3))))
    except (TypeError,ValueError): return 3

def _onaysiz_modu():
    """'gizle' ya da 'uyar' (varsayılan). Kural yalnız kullanıcının kt yetkisi OLMAYAN projelerde uygulanır.
    2.4.0: panelden değiştirilen değer (veritabanı) önce; yoksa .env (AYAR)."""
    from . import ayarlar as calisma_ayarlari
    return 'gizle' if str(calisma_ayarlari.ust('ONAYSIZ_GORUNUM',AYAR.get('ONAYSIZ_GORUNUM','uyar')) or '').strip().lower()=='gizle' else 'uyar'

def _kt_yok(projeler_listesi):
    """Verilen projelerden kullanıcının onay (kt) yetkisi olmayanları döndürür."""
    yk=g.get('yk') or yetki.coz('')
    return [p for p in projeler_listesi if not yetki.izin(yk,p,'kt')]

def _bekleme_gun(args):
    """'bekleme' parametresi: en az N gündür bekleyen; geçersizse yok sayılır."""
    try: n=int(str(args.get('bekleme','') or '').strip() or 0)
    except (TypeError,ValueError): return 0
    return n if 1<=n<=3650 else 0

def _tarih_alani(args):
    """2.4.0 'tarih_alani': eklenme (varsayılan; kaydın tarihi) ya da onay (onay zamanı; yalnız onaylı kayıtlar)."""
    return 'onay' if str(args.get('tarih_alani','') or '').strip().lower()=='onay' else 'eklenme'

def _kt_projeleri(projeler_listesi):
    """Verilen projelerden kullanıcının onay (kt) yetkisi olanlar (süperadmin: hepsi)."""
    yk=g.get('yk') or yetki.coz('')
    return [p for p in projeler_listesi if yetki.izin(yk,p,'kt')]

def _filtre_sql(args,izinli,bekleyen_kapsam=False):
    """bekleyen_kapsam=True (2.4.0, Kayıtlar listesi/sekme sayacı ve 'bu görünüm' Excel'i): proje seçilmemişken "Onay bekleyen"
    yalnız kullanıcının onay yetkisi olan projeleri kapsar (en az bir onay projesi varsa); diğerleri f['bekleyen_disi']'na yazılır."""
    explicit=_explicit_projects(args,izinli)
    selected=explicit or list(izinli)
    if not selected: return '1=0',[],dict(proje=[],proje_etkin=[],durum=args.get('durum','bekleyen'),kategori='',q='',ekleyen='',tarih1='',tarih2='',tarihsiz=False,bekleme=0,kt_yok=[],gizli_onaysiz=False,yalniz_onayli=False,personel='',ekleyen_ad='',tip='',silinmemis=False,tarih_alani=_tarih_alani(args),bekleyen_disi=[])
    where=['proje IN (%s)' % ','.join('?'*len(selected))]; par=list(selected)
    gizle=_onaysiz_modu()=='gizle'; kt_yok=_kt_yok(selected); yalniz_onayli=gizle and len(kt_yok)==len(selected)
    state=args.get('durum','bekleyen')
    if yalniz_onayli: state='onayli'  # onaysızlar bu kullanıcıya hiç gösterilmez; sekme seçimi onaylıya sabitlenir
    if state=='bekleyen': where.append('kt=0 AND silindi=0')
    elif state=='onayli': where.append('kt=1 AND silindi=0')
    elif state=='silinen': where.append('silindi=1')
    elif state!='hepsi': state='bekleyen'; where.append('kt=0 AND silindi=0')
    bekleyen_disi=[]
    if bekleyen_kapsam and state=='bekleyen' and not explicit:
        kt_li=_kt_projeleri(selected)
        if kt_li and len(kt_li)<len(selected):
            bekleyen_disi=[p for p in selected if p not in kt_li]
            where.append('proje IN (%s)' % ','.join('?'*len(kt_li))); par.extend(kt_li)
    if gizle and kt_yok and not yalniz_onayli:
        gizli_sql,gizli_par=_gizli_kayit_sql('',selected); where.append(gizli_sql); par.extend(gizli_par)
    bekleme=0 if yalniz_onayli else _bekleme_gun(args)  # onaylıya sabitlenen listede 'gündür bekleyen' süzgeci anlamsız: yok sayılır
    if bekleme: where.append(_GECIKEN_SQL); par.append(bekleme)
    # 2.3.5: personel raporuyla aynı kırpma (boşluk, sekme, satır sonu, bölünmez boşluk; iç boşluklar korunur).
    cat=_kategori_kanonik(personel_ozeti.kirp(args.get('kategori',''))[:120],selected)
    if cat==personel_ozeti.BOS_DEGER: where.append(personel_ozeti.kirp_sql('kategori')+"=''")  # 2.3.5: rapordaki "(boş)" kategori kutusu/hücresi
    elif cat: where.append(personel_ozeti.kirp_sql('kategori')+" COLLATE UNICODE_NOCASE=?"); par.append(cat)  # 2.3.4: baş/son boşluklu eski kategoriler de eşleşir
    q=args.get('q','').strip()[:200]
    if q:
        where.append('(personel LIKE ? OR uye_id LIKE ? OR ana_uye_id LIKE ? OR lead_id LIKE ? OR link LIKE ? OR aciklama LIKE ? OR ekleyen_ad LIKE ? OR kategori LIKE ?)'); par += ['%'+q+'%']*8
    by=args.get('ekleyen','').strip()[:100]
    if by: where.append('(ekleyen_ad LIKE ? OR ekleyen_id=?)'); par += ['%'+by+'%',by]
    # 2.3.4: personel raporundaki hücre bağlantıları için tam eşleşen süzgeçler ('__bos__' = boş değer) ve "silinenler hariç".
    tam={}
    for name,kolon in (('personel',personel_ozeti.kirp_sql('personel')),('ekleyen_ad',personel_ozeti.kirp_sql('ekleyen_ad')),('tip',personel_ozeti.kirp_sql('tip')+" COLLATE UNICODE_NOCASE")):
        v=personel_ozeti.kirp(args.get(name,''))[:200]
        if v: where.append(kolon+'=?'); par.append('' if v==personel_ozeti.BOS_DEGER else v)
        tam[name]=v
    silinmemis=args.get('silinmemis')=='1' and state in ('hepsi','onayli','bekleyen')
    if silinmemis: where.append('silindi=0')
    dates={}
    undated=args.get('tarihsiz')=='1'
    if undated:
        if args.get('tarih1') or args.get('tarih2'): abort(400,'Tarihsiz filtre tarih aralığıyla birleştirilemez.')
        where.append("(tarih IS NULL OR tarih='')")
    # 2.3.4: başlangıç 'YYYY-AA-GG' ile karşılaştırılır; eski Excel kayıtlarının saatsiz tarihi de başlangıç gününe dahil olur.
    # 2.4.0: tarih_alani=onay → aynı kural onay zamanına (kt_zaman) uygulanır; onayı kaldırılmış kayıt sayılmaz (kt=1).
    tarih_alani=_tarih_alani(args); kolon='kt_zaman' if tarih_alani=='onay' else 'tarih'
    for name,op,suffix in [('tarih1','>=',''),('tarih2','<=',' 23:59:59')]:
        v=args.get(name,'').strip()
        if v:
            try: datetime.strptime(v,'%Y-%m-%d')
            except ValueError: abort(400,'Geçersiz tarih.')
            where.append(f'{kolon} {op} ?'); par.append(v+suffix)
        dates[name]=v
    if kolon=='kt_zaman' and (dates.get('tarih1') or dates.get('tarih2')): where.append('kt=1')
    if dates.get('tarih1') and dates.get('tarih2') and dates['tarih1']>dates['tarih2']:abort(400)
    return ' AND '.join(where),par,dict(proje=explicit,proje_etkin=selected,durum=state,kategori=cat,q=q,ekleyen=by,tarihsiz=undated,bekleme=bekleme,
                                      kt_yok=kt_yok,gizli_onaysiz=gizle and bool(kt_yok),yalniz_onayli=yalniz_onayli,silinmemis=silinmemis,
                                      tarih_alani=tarih_alani,bekleyen_disi=bekleyen_disi,**tam,**dates)

def _su_an():
    """Bekleme süresi hesabının 'şimdi'si: sunucu yerel saati (db.simdi() ve hatırlatmalarla aynı saat). Testler değiştirebilir."""
    return datetime.now()

def _bekleme_esikleri():
    """(turuncu eşik saat, kırmızı eşik gün): BEKLEME_UYARI_SAAT (2) ve HATIRLATMA_GUN (3); istek başına bir kez okunur."""
    if 'bekleme_esik' not in g:
        a=hatirlatma.ayarlar(AYAR); g.bekleme_esik=(a['bekleme_uyari_saat'],a['gun'])
    return g.bekleme_esik

def _baslangic_zamani(d):
    """hatirlatma.BASLANGIC_SQL ile aynı: COALESCE(ilk_gorulme, tarih, guncelleme) içinden ilk dolu değer; okunamazsa None."""
    for ad in ('ilk_gorulme','tarih','guncelleme'):
        v=str(d.get(ad) or '').strip()
        if not v: continue
        try: z=datetime.fromisoformat(v.replace('/','-'))
        except ValueError: return None
        return z.astimezone().replace(tzinfo=None) if z.tzinfo else z
    return None

def bekleme_etiketi(saniye):
    """'45 dk' (1 saatten az), '5 sa' (1 günden az), '3 gün'."""
    saniye=max(0,int(saniye))
    if saniye<3600: return '%d dk' % max(1,saniye//60)
    if saniye<86400: return '%d sa' % (saniye//3600)
    return '%d gün' % (saniye//86400)

def bekleme_bilgisi(d,an=None):
    """2.4.0: onay bekleyen (kt=0, silindi=0) kayıt için {'etiket','seviye','sn','baslangic'}; diğerleri için None.
    seviye: 'kirmizi' (≥ HATIRLATMA_GUN gün), 'turuncu' (≥ BEKLEME_UYARI_SAAT saat) ya da 'normal'."""
    if d.get('kt') or d.get('silindi'): return None
    bas=_baslangic_zamani(d)
    if not bas: return None
    sn=max(0,int(((an or _su_an())-bas).total_seconds()))
    uyari_saat,kirmizi_gun=_bekleme_esikleri()
    seviye='kirmizi' if sn>=kirmizi_gun*86400 else 'turuncu' if sn>=uyari_saat*3600 else 'normal'
    return dict(etiket=bekleme_etiketi(sn),seviye=seviye,sn=sn,baslangic=bas.strftime('%d.%m.%Y %H:%M'))

def kayit_izin(r,eylem):
    return yetki.izin(g.yk,r['proje'],eylem)

def _metin(value):
    """Her satir degerini JSON'a guvenle tasir (bytes/None/sayi)."""
    if isinstance(value,bytes):
        try: return value.decode('utf-8')
        except UnicodeDecodeError: return value.decode('latin-1','replace')
    return value

def kayit_sozluk(row):
    d={k:_metin(v) for k,v in dict(row).items()}
    d.setdefault('anahtar',None); d['anahtar']=d['anahtar'] if isinstance(d['anahtar'],str) and d['anahtar'] else 'id:'+str(d.get('id'))
    for name in ('link','gorsel2','gorsel_dosya','gorsel2_dosya','proje','kategori'):
        if d.get(name) is not None and not isinstance(d[name],str): d[name]=str(d[name])
    d['silindi']=1 if d.get('silindi') else 0; d['kt']=1 if d.get('kt') else 0
    try: path,source=COZUCU.yerel_dosya(d)
    except Exception: path,source=None,'yok'
    # 2.3.2: gorsel_kaynak = yerel | gyazo | snappark | teamzone (sunucu üzerinden getirilir) | onedrive (kopyası yok) | kayip | yok
    try: link_kaynak=gorsel.link_turu_ve_kimlik(d.get('link') or '')[0]
    except Exception: link_kaynak='bos'
    if not path and COZUCU.gyazo_mumkun(d): source='gyazo'
    elif not path:
        try: source=COZUCU.dis_mumkun(d) or source
        except Exception: pass
    dosya=d.get('gorsel_dosya') or ''
    kayip=bool(str(dosya).strip()) and not path
    uzak=source in ('gyazo','snappark','teamzone')
    if kayip and not uzak: source='kayip'
    elif source=='yok' and link_kaynak=='onedrive': source='onedrive'
    try: ikinci=COZUCU.ikinci_dosya(d)[0] or COZUCU.gyazo_mumkun(dict(d,_gorsel2=True)) or COZUCU.dis_mumkun(dict(d,_gorsel2=True))
    except Exception: ikinci=None
    d.update(gorsel_var=bool(path) or uzak,gorsel_yerel=bool(path),gorsel_kaynak=source,link_kaynak=link_kaynak,gorsel2_var=bool(ikinci),renk=renk(d['proje']),
             gorsel_kayip=kayip,gorsel_dosya_adi=(os.path.basename(str(dosya).replace('\\','/').rstrip('/')) or None) if kayip else None,
             izin_gyazo=kayit_izin(d,'kt') and kayit_izin(d,'gorsel') and bool(path) and not d['silindi'],izin_kt=kayit_izin(d,'kt'),izin_yorum=kayit_izin(d,'kt'),izin_duzenle=kayit_izin(d,'duzenle'),izin_sil=kayit_izin(d,'sil'),geri_al_olur=bool(d['silindi']))
    # 2.3.1: kt yetkisi olmayan kullanıcı için onaysız kayıt 'uyar' modunda kırmızı rozet/şeritle işaretlenir.
    d['onay_uyari']=bool(_onaysiz_modu()=='uyar' and not d['izin_kt'] and not d['kt'] and not d['silindi'])
    link=d.get('link') or ''; d['dis_link']=link if re.match(r'^https?://',link) else None
    link2=d.get('gorsel2') or ''; d['dis_link2']=link2 if re.match(r'^https?://',link2) else None
    d['bekleme']=bekleme_bilgisi(d)  # 2.4.0: "Bekleme" rozeti (liste ve ayrıntı penceresi)
    d['giris_tipi_metni']=GIRIS_TIPI_ADLARI.get(d.get('giris_tipi') or '',d.get('giris_tipi') or '')
    d['kaynak_metni']=KAYNAK_ADLARI.get(d.get('kaynak') or '',d.get('kaynak') or '')
    d.setdefault('gorsel_dosya_adi',os.path.basename(str(d['gorsel_dosya'])) if d.get('gorsel_dosya') else None)
    d['gorsel2_dosya_adi']=os.path.basename(str(d['gorsel2_dosya'])) if d.get('gorsel2_dosya') else None
    for name in ('file_id','file_unique_id','chat_id','gorsel_dosya','gorsel2_dosya'):
        d.pop(name,None)
    return d

def _sayfa_boyu(args):
    try: size=int(args.get('boy',AYAR.get('SAYFA_BOYU',48)))
    except (TypeError,ValueError): size=AYAR.get('SAYFA_BOYU',48)
    return size if size in SAYFA_BOYLARI else AYAR.get('SAYFA_BOYU',48)

def _kayit_args():
    """Kayıt listesi sorgusunu okunur hale getirir: ters tarih aralığı 400 yerine düzeltilip uyarıyla gösterilir."""
    args=MultiDict(request.args.to_dict(flat=False)); uyari=None
    t1=(args.get('tarih1') or '').strip(); t2=(args.get('tarih2') or '').strip()
    if t1 and t2 and t1>t2:
        try: datetime.strptime(t1,'%Y-%m-%d'); datetime.strptime(t2,'%Y-%m-%d'); gecerli=True
        except ValueError: gecerli=False
        if gecerli:
            args.setlist('tarih1',[t2]); args.setlist('tarih2',[t1])
            uyari='Başlangıç tarihi bitişten sonraydı; tarihler yer değiştirildi ('+t2+' → '+t1+').'
    if args.get('tarihsiz')=='1' and (t1 or t2):
        args.setlist('tarihsiz',['']); uyari='Tarih aralığı girildiği için "yalnız tarihsiz kayıtlar" seçimi kaldırıldı.'
    return args,uyari

# 2.4.0: liste sırası. eski = en uzun bekleyen önce (başlangıç zamanı hatırlatmalarla aynı ifade), yeni = en yeni tarih önce.
SIRALAMALAR={'eski':"COALESCE("+hatirlatma.BASLANGIC_SQL+",'9999') ASC,id ASC",'yeni':"COALESCE(tarih,'0000') DESC,id DESC"}

# 2.4.0: Kayıtlar gelişmiş süzgeçleri ve Çıktı sayfasındaki hızlı tarih düğmeleri (tarihleri panel.js İstanbul takvimiyle doldurur;
# hafta pazartesi başlar). Kod adları panel.js HIZLI_DONEM ile aynıdır.
HIZLI_DONEMLER=(('bugun','Bugün'),('bu_hafta','Bu hafta'),('gecen_hafta','Geçen hafta'),('bu_ay','Bu ay'),('gecen_ay','Geçen ay'))
app.jinja_env.globals['hizli_donemler']=HIZLI_DONEMLER

def _siralama(args,durum):
    """'sirala' parametresi (eski|yeni); verilmemişse Onay bekleyen sekmesinde eski, diğerlerinde yeni."""
    v=str(args.get('sirala','') or '').strip().lower()
    if v in SIRALAMALAR: return v
    return 'eski' if durum=='bekleyen' else 'yeni'

def _etkin_suzgec_sayisi(f):
    """Telefonda kapalı süzgeç düğmesindeki "N etkin" sayısı (proje seçimi, kategori, arama, tarih aralığı vb. birer sayılır)."""
    adlar=('proje','kategori','q','ekleyen','tarihsiz','bekleme','personel','ekleyen_ad','tip','silinmemis')
    n=sum(1 for ad in adlar if f.get(ad))
    if f.get('tarih1') or f.get('tarih2'): n+=1
    return n

def _gyazo_hazir():
    """Sunucuda Gyazo anahtarı tanımlı mı (yalnız evet/hayır; anahtarın kendisi sayfaya hiç yazılmaz)."""
    return bool(os.environ.get('GYAZO_TOKEN','').strip())

@app.route('/kayitlar')
@giris_gerekli
def kayitlar():
    c=baglanti(); allowed=yetki.izinli_projeler(g.yk,projeler()); args,uyari=_kayit_args(); where,par,f=_filtre_sql(args,allowed,bekleyen_kapsam=True)
    try: page=max(1,int(args.get('s','1')))
    except ValueError: abort(400,'Geçersiz sayfa.')
    size=_sayfa_boyu(args); total=c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {where}',par).fetchone()[0]
    pages=max(1,(total+size-1)//size); page=min(page,pages)
    sirala=_siralama(args,f['durum'])
    rows=c.execute(f"SELECT * FROM kayitlar WHERE {where} ORDER BY {SIRALAMALAR[sirala]} LIMIT ? OFFSET ?",(*par,size,(page-1)*size)).fetchall()
    cats=_scoped_categories(f.get('proje_etkin') or allowed)
    counts={}
    for s in ('bekleyen','onayli','silinen','hepsi'):
        a=args.to_dict(flat=False); a['durum']=[s]; w,p,_=_filtre_sql(MultiDict(a),allowed,bekleyen_kapsam=True)
        counts[s]=c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {w}',p).fetchone()[0]
    # 2.4.0: "Onay bekleyen" sayısı yalnız onay yetkisi olan projeleri sayar; yalnız görüntüleyebildiği projelerdeki bekleyenler ayrı notta.
    bekleyen_disi=None
    a=args.to_dict(flat=False); a['durum']=['bekleyen']; _,_,fb=_filtre_sql(MultiDict(a),allowed,bekleyen_kapsam=True)
    if fb.get('bekleyen_disi'):
        a['proje']=list(fb['bekleyen_disi']); w,p,_=_filtre_sql(MultiDict(a),allowed)
        n=c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {w}',p).fetchone()[0]
        if n: bekleyen_disi=dict(adet=n,url=url_degistir(proje=list(fb['bekleyen_disi']),durum='bekleyen',s='',ac='',sirala=''),projeler=fb['bekleyen_disi'])
    records=[kayit_sozluk(r) for r in rows]
    toplu_kt=any(yetki.izin(g.yk,p,'kt') for p in (f.get('proje_etkin') or allowed))
    view=args.get('gorunum','tablo')
    if view not in ('tablo','kart','galeri'): view='tablo'
    try: acik=int(args.get('ac','') or 0)
    except ValueError: acik=0
    try: yorum=int(args.get('yorum','') or 0)
    except ValueError: yorum=0
    if acik<=0: acik=0
    if not (0<yorum<2**31): yorum=0
    # 'uyar' modu: arama sonucu yalnız onaysız (kt yetkisi olmayan projelerdeki, silinmemiş) kayıt içeriyor ve aynı arama için
    # HİÇBİR sekmede onaylı kanıt yoksa uyarı; onaylı kanıt başka sekmedeyse yalnız yönlendirici bilgi notu.
    onaysiz_uyari=None;onayli_notu=None
    if f.get('q') and f.get('kt_yok') and _onaysiz_modu()=='uyar':
        places=','.join('?'*len(f['kt_yok']))
        listelenen=c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {where} AND kt=0 AND silindi=0 AND proje IN ({places})',(*par,*f['kt_yok'])).fetchone()[0]
        tum=args.to_dict(flat=False);tum['durum']=['hepsi'];w_tum,p_tum,_=_filtre_sql(MultiDict(tum),allowed)
        onayli_tum=c.execute(f'SELECT COUNT(*) FROM kayitlar WHERE {w_tum} AND kt=1 AND silindi=0',p_tum).fetchone()[0]
        if listelenen and not onayli_tum: onaysiz_uyari='Aradığınız ID için onaylı kanıt yok; %d onaysız kayıt listelendi.' % listelenen
        elif onayli_tum and f['durum'] in ('bekleyen','silinen'): onayli_notu=onayli_tum
    ekle=_ekleme_baglami() if _ekleme_projeleri() else None  # 2.3.6: 'Kanıt ekle' düğmesi ve penceresi (jeton pencere açılınca alınır)
    etkin=_etkin_suzgec_sayisi(f)
    return render_template('kayitlar.html',bekleyen_disi=bekleyen_disi,sirala=sirala,sirala_varsayilan=_siralama(MultiDict(),f['durum']),etkin_suzgec=etkin,
                           gyazo_hazir=_gyazo_hazir(),bekleme_uyari_saat=_bekleme_esikleri()[0],ekle=ekle,kayitlar=records,toplam=total,sayfa=page,sayfa_sayisi=pages,f=f,izinli=allowed,kategoriler=cats,gorunum=view,sayac=counts,sayfa_boyu=size,sayfa_boylari=SAYFA_BOYLARI,toplu_kt=toplu_kt,uyari=uyari,acik_kayit=acik or None,acik_yorum=(yorum if acik and yorum else None),onaysiz_uyari=onaysiz_uyari,onayli_notu=onayli_notu,hatirlatma_gun=_hatirlatma_gun(),damga=_degisiklik_damgasi() or '',filtre_aktif=bool(f.get('q') or f.get('kategori') or f.get('ekleyen') or f.get('tarih1') or f.get('tarih2') or f.get('tarihsiz') or f.get('proje') or f.get('bekleme') or f.get('personel') or f.get('ekleyen_ad') or f.get('tip') or f.get('silinmemis')),bos_deger=personel_ozeti.BOS_DEGER)

@app.route('/kayit/<int:kid>')
@giris_gerekli
def kayit_json(kid):
    r=_kayit_al(kid,'oku')
    try:
        d=kayit_sozluk(r)
        can_view=kayit_izin(r,'gorsel')
        d['gorsel_url']=url_for('gorsel_goster',kid=kid) if can_view and d['gorsel_var'] else None
        d['kucuk_url']=url_for('kucuk_goster',kid=kid) if can_view and d['gorsel_var'] else None
        d['indir_url']=url_for('gorsel_goster',kid=kid,indir=1) if can_view and d['gorsel_var'] else None
        d['gorsel2_url']=url_for('gorsel_goster',kid=kid,ikinci=1) if can_view and d['gorsel2_var'] else None
        d['kucuk2_url']=url_for('kucuk_goster',kid=kid,ikinci=1) if can_view and d['gorsel2_var'] else None
        from . import discussion
        d['yorumlar']=[{k:_metin(v) for k,v in dict(x).items()} for x in baglanti().execute('SELECT id,kullanici,metin,zaman,yanit_id,alici,tur FROM yorumlar WHERE kayit_id=? ORDER BY id',(kid,))]
        try: d['yorum_alicilari']=discussion.recipients(baglanti(),r['proje'],g.k['kullanici_adi']) if d['izin_yorum'] else []
        except Exception: d['yorum_alicilari']=[]
        from . import bot_bildirim; d['tg_ekleyen']=bool(d['izin_yorum'] and bot_bildirim.tg_hedef(r) and bot_bildirim.soru_acik())  # 2.4.0: "Ekleyene sor (Telegram)"
        from .guvenli_log import log_row
        d['soru_cevaplar']=_question_answers(r)
        d['gyazo_hazir']=_gyazo_hazir()
        try:
            job=baglanti().execute('SELECT * FROM donusum_isleri WHERE record_id=? ORDER BY id DESC LIMIT 1',(kid,)).fetchone()
            d['gyazo_bekliyor']=bool(job and job['durum'] not in ('tamam','hata','belirsiz','iptal') and job['expected_gorsel']==r['gorsel_dosya'])
            d['gyazo_is']=_gyazo_result(job,r) if job else None
        except Exception: d['gyazo_bekliyor']=False; d['gyazo_is']=None
        d['gorsel_bozuk']=False
        try:
            if d['gorsel_yerel']:
                yol,_=COZUCU.yerel_dosya(dict(r)); d['gorsel_bozuk']=bool(yol) and not COZUCU.gecerli(yol)
        except Exception: d['gorsel_bozuk']=False
        try: d['gecmis']=[log_row(x) for x in baglanti().execute('SELECT zaman,kullanici,islem,eski,yeni,aciklama FROM denetim WHERE anahtar=? ORDER BY id DESC LIMIT 30',(r['anahtar'],))] if r['anahtar'] else []
        except Exception: d['gecmis']=[]
        return jsonify(d)
    except Exception as error:
        app.logger.exception('kayit_json %s: %s',kid,type(error).__name__)
        return jsonify(ok=False,hata='Kayıt ayrıntısı okunamadı; sunucu kaydı hazırlarken hata oluştu. Yöneticinize bildirin.',kod=500),500

def _kayit_al(kid,action):
    r=baglanti().execute('SELECT * FROM kayitlar WHERE id=?',(kid,)).fetchone()
    if not r: _json_hata(404,'Kayıt bulunamadı; silinmiş veya taşınmış olabilir.')
    if not kayit_izin(r,action): _json_hata(403,'Bu kayıt için yetkiniz yok; kayıt '+str(r['proje'] or '?')+' projesine ait.',proje=r['proje'])
    # 2.3.1 'gizle': kt yetkisi olmayan kullanıcıya onaysız (ya da silinmiş) kayıt ayrıntı/görsel olarak da verilmez (404 değil 403).
    if _onaysiz_modu()=='gizle' and not kayit_izin(r,'kt') and (not r['kt'] or r['silindi']):
        if r['silindi']: _json_hata(403,'Bu kayıt silinmiş; size gösterilmez.',neden='silindi')
        _json_hata(403,'Bu kaydın onayı yok; yalnız onaylı kayıtlar gösterilir.',neden='onay_yok')
    return r

def _hatirlatmalari_kapat(c,kid):
    """2.3.1: onaylanan ya da silinen kaydın açık hatırlatmaları okundu olur (zil sayacı düşer); akış da bunları süzer."""
    # 2.3.3: 2 saat hatırlatması ('hatirlatma-saat:<id>') da kapanır; toplu ve gün sonu satırları listeye bağlı olduğu için kalır.
    c.execute("UPDATE mesaj_bildirimleri SET okundu=1 WHERE kayit_id=? AND tur='hatirlatma' AND (olay LIKE 'hatirlatma:%' OR olay LIKE 'hatirlatma-saat:%') AND okundu=0",(kid,))

def _kayit_bildirimlerini_kapat(c,kid):
    """2.4.0: kayıt onaylanınca, onayı kaldırılınca, silinince ya da geri alınınca o kayda ait 'Yeni kanıt' satırları ve kayda özel
    hatırlatmalar HERKES için okundu olur (zil bir daha bu kaydı göstermez). Soru / yanıt / yorum satırlarına dokunulmaz;
    proje özeti, gün sonu ve bekleyen özeti gibi listeye bağlı satırlar da kalır (_hatirlatmalari_kapat ile aynı kural)."""
    c.execute('UPDATE bildirimler SET okundu=1 WHERE kayit_id=? AND okundu=0',(kid,))
    c.execute("UPDATE mesaj_bildirimleri SET okundu=1 WHERE kayit_id=? AND tur='kanit' AND okundu=0",(kid,))
    _hatirlatmalari_kapat(c,kid)

def _bildirim_onay_acik():
    """2.4.0 BILDIRIM_ONAY (varsayılan 0): 1 ise onay / onay kaldırma diğer proje sorumlularına bildirim olarak da gider.
    İşlem geçmişi (denetim) bu ayardan etkilenmez."""
    return hatirlatma.ayarlar(AYAR)['bildirim_onay']

def version_check(r):
    v=request.form.get('surum')
    if v is not None and str(r['surum'])!=v:
        _json_hata(409,'Bu kayıt az önce başka bir kullanıcı tarafından değiştirildi. Yenileyip tekrar deneyin.')

def _kt_uygula(c,r,v):
    """Tek kayit icin onay/onay kaldirma; kayit_kt ve toplu-kt ayni kurali kullanir."""
    from . import discussion
    c.execute('UPDATE kayitlar SET kt=?,kt_kaynak=\'panel\',kt_kim=?,kt_zaman=?,surum=surum+1,guncelleme=? WHERE id=?',(v,g.k['kullanici_adi'],simdi(),simdi(),r['id']))
    _kayit_bildirimlerini_kapat(c,r['id'])  # 2.4.0: onayda da onay kaldırmada da kaydın "Yeni kanıt" / hatırlatma satırları okundu
    if _bildirim_onay_acik(): discussion.approval_notice(c,r,g.k['kullanici_adi'],v,r['surum']+1)
    from . import bot_bildirim; bot_bildirim.onay_kuyruga(c,r,v)  # 2.4.0 (Takım C): Telegram ekleyene onay bildirimi
    db.denetim_yaz(c,g.k['kullanici_adi'],'onayla' if v else 'onay_kaldir',r['proje'],r['anahtar'],r['kt'],v,ip())

@app.route('/kayit/<int:kid>/kt',methods=['POST'])
@giris_gerekli
def kayit_kt(kid):
    c=baglanti()
    with db.transaction(c):
        r=_kayit_al(kid,'kt'); version_check(r)
        if r['silindi']: _json_hata(400,'Silinen kayıt onaylanamaz; önce geri alın.')
        v=1 if request.form.get('deger','1')=='1' else 0
        _kt_uygula(c,r,v); db.degisti(c)
    return jsonify(ok=True,kt=v,damga=_degisiklik_damgasi())

@app.route('/kayitlar/toplu-kt',methods=['POST'])
@giris_gerekli
def kayitlar_toplu_kt():
    payload=request.get_json(silent=True) if request.is_json else None
    raw=(payload or {}).get('ids') if payload else request.form.getlist('ids')
    if isinstance(raw,str): raw=raw.split(',')
    if not isinstance(raw,list): _json_hata(400,'Geçersiz kayıt listesi.')
    try: ids=list(dict.fromkeys(int(x) for x in raw if str(x).strip()))
    except (TypeError,ValueError): _json_hata(400,'Geçersiz kayıt listesi.')
    if not ids: _json_hata(400,'Önce en az bir kayıt seçin.')
    if len(ids)>300: _json_hata(400,'Tek seferde en çok 300 kayıt işlenebilir.')
    deger=(payload or {}).get('deger') if payload else request.form.get('deger','1')
    v=1 if str(deger if deger is not None else '1')=='1' else 0
    c=baglanti(); result=dict(ok=True,kt=v,degisen=0,atlanan=0,yetkisiz=0,silinen=0,bulunamadi=0,zaten=0,ids=[])
    with db.transaction(c):
        for kid in ids:
            r=c.execute('SELECT * FROM kayitlar WHERE id=?',(kid,)).fetchone()
            if not r: result['bulunamadi']+=1; continue
            if not kayit_izin(r,'kt'): result['yetkisiz']+=1; continue
            if r['silindi']: result['silinen']+=1; continue
            if (1 if r['kt'] else 0)==v: result['zaten']+=1; continue
            _kt_uygula(c,r,v); result['degisen']+=1; result['ids'].append(kid)
        if result['degisen']: db.degisti(c)
    result['atlanan']=result['yetkisiz']+result['silinen']+result['bulunamadi']+result['zaten']
    parts=[('%d kayıt onaylandı' if v else '%d kaydın onayı kaldırıldı') % result['degisen']]
    if result['zaten']: parts.append('%d kayıt zaten bu durumdaydı' % result['zaten'])
    if result['silinen']: parts.append('%d silinmiş kayıt atlandı' % result['silinen'])
    if result['yetkisiz']: parts.append('%d kayıt için yetki yok' % result['yetkisiz'])
    if result['bulunamadi']: parts.append('%d kayıt bulunamadı' % result['bulunamadi'])
    result['mesaj']='; '.join(parts)+'.'
    result['damga']=_degisiklik_damgasi()
    return jsonify(result)

GYAZO_DURUM_ADLARI={'bekliyor':'Sırada bekliyor','tekrar':'Yeniden denenecek','calisiyor':'Gönderiliyor','verify':'Bağlantı doğrulanıyor','tamam':'Tamamlandı','hata':'Başarısız','belirsiz':'Sonuç belirsiz','iptal':'İptal edildi'}

def _gyazo_result(job,record):
    """Dönüşüm işinin kullanıcıya gösterilecek özeti: durum adı, deneme sayısı, hata metni, tekrar denenebilir mi."""
    from .guvenli_log import text
    if not job:return dict(ok=True,pending=False,converted=False,durum=None,durum_adi='Başlatılmadı',deneme=0,hata=None,tekrar_olur=False,mesaj='Bu kayıt için dönüşüm başlatılmadı.')
    job=dict(job)
    pending=job['durum'] not in ('tamam','hata','belirsiz','iptal')
    converted=bool(job['durum']=='tamam' and job['url'] and record['link']==job['url'] and record['link_turu']=='gyazo' and job['expected_gorsel']==record['gorsel_dosya'])
    hata=text(job.get('hata') or '') or None
    deneme=int(job.get('deneme') or 0)+int(job.get('verify_deneme') or 0)
    if pending:message='Dönüşüm arka planda sürüyor ('+GYAZO_DURUM_ADLARI.get(job['durum'],job['durum'])+(', %d. deneme' % deneme if deneme else '')+'). Yerel kanıt korunuyor.'+(' Son hata: '+hata if hata else '')
    elif converted:message='Gyazo bağlantısı oluşturuldu ve kayda eklendi.'
    elif job['durum']=='tamam':message='Görsel dönüştü ancak kayıt görseli değişti; mevcut kanıt değiştirilmedi.'
    elif job['durum']=='iptal':message='Dönüşüm iptal edildi. Yerel kanıt korunuyor.'
    else:message=(hata or 'Dönüşüm tamamlanamadı.')+(' (%d deneme)' % deneme if deneme else '')+' Yerel kanıt korunuyor.'
    return dict(ok=True,pending=pending,converted=converted,url=job['url'] if converted else None,mesaj=message,durum=job['durum'],durum_adi=GYAZO_DURUM_ADLARI.get(job['durum'],job['durum']),deneme=deneme,hata=hata,
                tekrar_olur=job['durum'] in ('hata','belirsiz','iptal') or (job['durum']=='tamam' and not converted),is_id=job.get('id'),guncelleme=job.get('guncelleme'))

@app.route('/kayit/<int:kid>/gyazo',methods=['POST'])
@giris_gerekli
def kayit_gyazo(kid):
    import hashlib
    from . import donusum_isleri
    c=baglanti();record=_kayit_al(kid,'kt');version_check(record)
    if not kayit_izin(record,'gorsel') or record['silindi']:_json_hata(403,'Bu kayıt için görsel dönüştürme yetkiniz yok.')
    if not os.environ.get('GYAZO_TOKEN','').strip():return jsonify(ok=False,hata='Gyazo anahtarı yapılandırılmadı. Süperadmin sunucudaki gizli ayardan eklemeli.'),400
    path,_=COZUCU.yerel_dosya(dict(record))
    if not path:return jsonify(ok=False,hata='Bu kaydın eşleşmiş yerel görseli yok.'),400
    fingerprint=hashlib.sha256()
    with open(path,'rb') as image:
        for part in iter(lambda:image.read(1048576),b''):fingerprint.update(part)
    key='web:'+str(kid)+':'+fingerprint.hexdigest()
    with db.transaction(c):
        current=_kayit_al(kid,'kt');version_check(current)
        last=c.execute('SELECT * FROM donusum_isleri WHERE record_id=? ORDER BY id DESC LIMIT 1',(kid,)).fetchone()
        if last:
            son=_gyazo_result(last,current)
            if son['pending']:
                return jsonify(dict(son,mesaj='Bu kayıt için dönüşüm zaten sürüyor; tamamlanınca burada görünecek.'))
            if son['converted']:
                return jsonify(dict(son,mesaj='Bu kaydın Gyazo bağlantısı zaten oluşturulmuş; yeniden dönüştürme gerekmez.'))
            if son['tekrar_olur'] and request.form.get('tekrar')!='1':
                return jsonify(dict(son,mesaj='Önceki dönüşüm tamamlanamadı. Yeniden başlatmak için "Tekrar dene" düğmesini kullanın.'))
        existing=c.execute('SELECT durum FROM donusum_isleri WHERE job_key=?',(key,)).fetchone()
        if existing and existing['durum'] in ('tamam','hata','belirsiz','iptal'):
            # Biten işler asla canlandırılmaz; yeniden deneme yeni bir iş kaydıdır.
            key=key+':tekrar'+str(last['id'] if last else 0)
        job=donusum_isleri.enqueue(c,kid,g.k['kullanici_adi'],local_path=path,job_key=key)
        db.denetim_yaz(c,g.k['kullanici_adi'],'gyazo_istek',current['proje'],current['anahtar'],yeni={'is':job['id'],'durum':job['durum'],'tekrar':request.form.get('tekrar')=='1'},ip=ip(),hedef_turu='kayit',hedef_id=kid)
    return jsonify(_gyazo_result(job,current))

@app.route('/kayit/<int:kid>/gyazo-durum')
@giris_gerekli
def kayit_gyazo_durum(kid):
    record=_kayit_al(kid,'kt')
    job=baglanti().execute('SELECT * FROM donusum_isleri WHERE record_id=? ORDER BY id DESC LIMIT 1',(kid,)).fetchone()
    return jsonify(_gyazo_result(job,record))

DUZENLE_ALANLARI=('personel','uye_id','ana_uye_id','lead_id','tip','kategori','aciklama')

@app.route('/kayit/<int:kid>/duzenle',methods=['POST'])
@giris_gerekli
def kayit_duzenle(kid):
    c=baglanti()
    with db.transaction(c):
        r=_kayit_al(kid,'duzenle'); version_check(r)
        if r['silindi']: _json_hata(400,'Silinen kayıt düzenlenemez; önce geri alın.')
        vals={k:request.form[k].strip()[:500] for k in DUZENLE_ALANLARI if k in request.form}
        for k,v in vals.items():
            if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',v): _json_hata(400,'Alanlarda kontrol karakteri kullanılamaz.')
        if 'kategori' in vals and vals['kategori'] and vals['kategori']!=(r['kategori'] or ''):
            tanimli=_scoped_categories([r['proje']]); eslesen=next((k for k in tanimli if _tr_kucuk(k)==_tr_kucuk(vals['kategori'])),None)
            if eslesen is None:_json_hata(403 if not g.yk['admin'] else 400,'"'+vals['kategori']+'" kategorisi '+r['proje']+' projesinde tanımlı değil; yalnız listeden seçin. Yeni kategori gerekiyorsa Yönetim → Katalog bölümünden eklenir.')
            vals['kategori']=eslesen
        if r['cevaplar_json']:
            try:answers=json.loads(r['cevaplar_json'])
            except (ValueError,TypeError):answers={}
            if not isinstance(answers,dict):answers={}
            previous_answers=dict(answers)
            questions=_snapshot_questions(r['soru_anlik_json'])
            for question in questions:
                if question.get('preset') in vals:answers[question['key']]=vals[question['preset']]
            if answers!=previous_answers:vals['cevaplar_json']=json.dumps(answers,ensure_ascii=False)
        vals={k:v for k,v in vals.items() if (r[k] or '')!=v}
        if vals:
            c.execute('UPDATE kayitlar SET '+','.join(f'{k}=?' for k in vals)+',surum=surum+1,guncelleme=? WHERE id=?',(*vals.values(),simdi(),kid))
            db.denetim_yaz(c,g.k['kullanici_adi'],'duzenle',r['proje'],r['anahtar'],json.dumps({k:r[k] for k in vals},ensure_ascii=False),json.dumps(vals,ensure_ascii=False),ip()); db.degisti(c)
    return jsonify(ok=True,degisiklik=bool(vals),damga=_degisiklik_damgasi())

# ---------- 2.3.6: panelden kanıt ekleme (kategori SMS) ----------
# Kim: süperadmin ya da etkin bir projede onay (kt) veya düzenleme yetkisi olan kullanıcı; yalnız o projelere ekler.
# Görsel dosyası yüklenmez; Gyazo / Snappark / Teamzone bağlantısı (gorsel.py izin listesi, host tam eşleşme) yapıştırılır.
# Çift gönderim: her form açılışında oturuma bir jeton yazılır; kayıt anahtarı 'panel:<jeton>' olduğu için aynı form iki kayıt üretemez.
EKLEME_HOSTLARI=tuple(dict.fromkeys(tuple(gorsel.GYAZO_HOSTLAR)+tuple(h for v in gorsel.DIS_GORSEL_HOSTLAR.values() for h in v)))
EKLEME_TIPLERI=(('sessiz','Sessiz'),('telesekreter','Telesekreter'))  # bot ile aynı değerler (t:sessiz / t:telesekreter)
EKLEME_ALANLARI=(('personel','Personel',100,True),('uye_id','Üye ID',500,False),('ana_uye_id','Ana üye ID',500,False),('lead_id','Lead ID',500,False))
EKLEME_ACIKLAMA_SINIRI=500
EKLEME_JETON_SAYISI=20
_EKLEME_JETON_RX=re.compile(r'[0-9a-f]{32}')
_EKLEME_KONTROL_RX=re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def _ekleme_projeleri():
    """Kullanıcının panelden kanıt ekleyebileceği etkin projeler (proje sırasıyla)."""
    if not g.get('k'):return []
    aktif={p['code'] for p in _all_project_info() if p.get('aktif')}
    return [p for p in _allowed() if p in aktif and (g.yk['admin'] or yetki.izin(g.yk,p,'kt') or yetki.izin(g.yk,p,'duzenle'))]

def _ekleme_jetonu():
    jeton=uuid.uuid4().hex
    liste=[x for x in (session.get('ekle_jeton') or []) if isinstance(x,str)][-(EKLEME_JETON_SAYISI-1):]
    session['ekle_jeton']=liste+[jeton]
    return jeton

def _ekleme_jetonu_dus(jeton):
    session['ekle_jeton']=[x for x in (session.get('ekle_jeton') or []) if isinstance(x,str) and x!=jeton]

def _ekleme_secili_proje(uygun,istenen=None):
    istenen=[str(p).strip().upper() for p in (istenen or []) if str(p).strip()]
    istenen=[p for p in dict.fromkeys(istenen) if p in uygun]
    if len(istenen)==1:return istenen[0]
    return uygun[0] if len(uygun)==1 else ''

def _ekleme_kategori_adi():
    from . import katalog
    try:
        kat=katalog.panel_kategori(baglanti())
        return kat['label'] if kat else katalog.panel_kategori_etiketi()
    except Exception:
        return katalog.panel_kategori_etiketi()

def _ekleme_baglami(degerler=None,hatalar=None,jeton=None,genel_hata=None):
    uygun=_ekleme_projeleri()
    degerler=dict(degerler or {})
    if 'proje' not in degerler:degerler['proje']=_ekleme_secili_proje(uygun,request.args.getlist('proje'))
    if 'onayli' not in degerler:degerler['onayli']='1'
    etiketler={p['code']:p['label'] for p in _all_project_info()}
    return dict(ekleme_projeleri=[dict(code=p,label=etiketler.get(p,p),kt=yetki.izin(g.yk,p,'kt')) for p in uygun],
                ekleme_kategori=_ekleme_kategori_adi(),ekleme_hostlari=EKLEME_HOSTLARI,ekleme_tipleri=EKLEME_TIPLERI,
                ekleme_alanlari=EKLEME_ALANLARI,ekleme_aciklama_siniri=EKLEME_ACIKLAMA_SINIRI,
                degerler=degerler,hatalar=hatalar or {},jeton=jeton or '',genel_hata=genel_hata)

def _ekleme_linki(ham,zorunlu):
    """Görsel bağlantısını doğrular. Dönüş: ((link, link_turu) | None, hata | None)."""
    v=(ham if isinstance(ham,str) else '').strip()
    if not v:
        return None,('Görsel bağlantısı zorunludur; Gyazo, Snappark veya Teamzone bağlantısını yapıştırın.' if zorunlu else None)
    if len(v)>2048:return None,'Bağlantı en çok 2048 karakter olabilir.'
    if not v.lower().startswith('https://'):return None,'Bağlantı https:// ile başlamalıdır (http:// ve diğer biçimler kabul edilmez).'
    if not gorsel._guvenli_url(v,EKLEME_HOSTLARI):
        return None,'Yalnız şu adreslerin bağlantıları kabul edilir: '+', '.join(EKLEME_HOSTLARI)+'. Bağlantıda boşluk, @ işareti veya Türkçe karakter olmamalıdır.'
    tur,kimlik=gorsel.link_turu_ve_kimlik(v)
    if tur=='gyazo' and gorsel.KIMLIK_RX.fullmatch(kimlik or ''):return (v,'gyazo'),None
    if tur in ('snappark','teamzone') and gorsel.dis_gorsel_cozumle(v):return (v,tur),None
    return None,'Bağlantıda görsel kimliği bulunamadı. Gyazo için https://gyazo.com/… (32 karakterlik kimlik), Snappark için https://img.snappark.net/s/…/raw/ biçimini kullanın.'

def _ekleme_dogrula(form,uygun):
    """Form → (değerler, hatalar, yetkisiz proje mi). İstemci kuralları birebir: zorunlu alanlar, uzunluk, kontrol karakteri, tip listesi."""
    def al(ad):
        v=form.get(ad,'')
        # Görünmez biçim karakterleri (U+200B, U+202E yön değiştirme vb., Unicode Cf) sessizce atılır.
        return ''.join(ch for ch in v if unicodedata.category(ch)!='Cf') if isinstance(v,str) else ''
    degerler={};hatalar={};yasak=False
    proje=al('proje').strip().upper()
    degerler['proje']=proje
    if not proje:hatalar['proje']='Proje seçin.'
    elif proje not in uygun:hatalar['proje']='Bu projeye kanıt ekleme yetkiniz yok.';yasak=True
    for ad,zorunlu in (('link',True),('gorsel2',False)):
        degerler[ad]=al(ad).strip()
        sonuc,hata=_ekleme_linki(al(ad),zorunlu)
        if hata:hatalar[ad]=hata
        elif sonuc:degerler[ad+'_tur']=sonuc[1]
    if 'link' not in hatalar and 'gorsel2' not in hatalar and degerler.get('gorsel2') and degerler['gorsel2']==degerler['link']:
        hatalar['gorsel2']='İkinci görsel bağlantısı birinciyle aynı; boş bırakın ya da başka bir bağlantı girin.'
    for ad,etiket,sinir,zorunlu in EKLEME_ALANLARI:
        ham=al(ad)
        v=re.sub(r'\s+',' ',db.metin_temizle(ham)).strip()
        degerler[ad]=v
        if _EKLEME_KONTROL_RX.search(ham):hatalar[ad]=etiket+' alanında kontrol karakteri kullanılamaz.'
        elif zorunlu and not v:hatalar[ad]=etiket+' zorunludur.'
        elif len(v)>sinir:hatalar[ad]='%s en çok %d karakter olabilir.' % (etiket,sinir)
    tip=al('tip').strip().lower()
    degerler['tip']=tip
    if tip and tip not in dict(EKLEME_TIPLERI):hatalar['tip']='Sessiz / Telesekreter alanında yalnız listedeki seçenekler kullanılabilir.'
    ham=al('aciklama')
    aciklama=db.metin_temizle(ham).strip()
    degerler['aciklama']=aciklama
    if _EKLEME_KONTROL_RX.search(ham):hatalar['aciklama']='Açıklamada kontrol karakteri kullanılamaz.'
    elif len(aciklama)>EKLEME_ACIKLAMA_SINIRI:hatalar['aciklama']='Açıklama en çok %d karakter olabilir.' % EKLEME_ACIKLAMA_SINIRI
    degerler['onayli']='1' if al('onayli')=='1' else ''
    return degerler,hatalar,yasak

def _ekleme_hata(kod,mesaj,degerler=None,hatalar=None,yeni_jeton=False):
    if _json_bekleniyor():
        ek={'hatalar':hatalar or {}}
        if yeni_jeton:ek['jeton']=_ekleme_jetonu()
        return jsonify(ok=False,hata=mesaj,kod=kod,**ek),kod
    return render_template('kayit_yeni.html',e=_ekleme_baglami(degerler,hatalar,jeton=_ekleme_jetonu(),genel_hata=mesaj)),kod

def _ekleme_tekrar_yaniti(row):
    """Aynı jetonla ikinci gönderim (çift tıklama, sayfa yenileme): yeni kayıt açılmaz, ilk kayıt döner."""
    if row['ekleyen_id']!='panel:'+g.k['kullanici_adi']:
        return _ekleme_hata(409,'Bu form başka bir gönderimde kullanılmış; formu kapatıp yeniden açın.',yeni_jeton=True)
    mesaj='Bu form zaten gönderildi; Kayıt #%d yeniden oluşturulmadı.' % row['id']
    if _json_bekleniyor():
        return jsonify(ok=True,id=row['id'],tekrar=True,mesaj=mesaj,proje=row['proje'],damga=_degisiklik_damgasi())
    flash(mesaj);return redirect(url_for('kayitlar',durum='hepsi',proje=row['proje'],ac=row['id']))

@app.route('/kayit/yeni.json')
@giris_gerekli
def kayit_yeni_json():
    """Ekleme penceresi her açılışta buradan yeni bir form jetonu ve güncel proje listesini alır."""
    if not _ekleme_projeleri():_json_hata(403,'Kanıt eklemek için bir projede onay ya da düzenleme yetkiniz olmalı.')
    b=_ekleme_baglami()
    return jsonify(ok=True,jeton=_ekleme_jetonu(),projeler=b['ekleme_projeleri'],kategori=b['ekleme_kategori'],hostlar=list(EKLEME_HOSTLARI),secili=b['degerler']['proje'])

@app.route('/kayit/yeni',methods=['GET','POST'])
@giris_gerekli
def kayit_yeni():
    from . import katalog
    uygun=_ekleme_projeleri()
    if not uygun:_json_hata(403,'Kanıt eklemek için bir projede onay (takım lideri) ya da düzenleme yetkiniz olmalı. Gerekirse süperadminden yetki isteyin.')
    if request.method=='GET':
        return render_template('kayit_yeni.html',e=_ekleme_baglami(jeton=_ekleme_jetonu()))
    jeton=str(request.form.get('jeton') or '').strip().lower()
    if not _EKLEME_JETON_RX.fullmatch(jeton):
        return _ekleme_hata(400,'Form kimliği eksik ya da bozuk; formu kapatıp yeniden açın.',yeni_jeton=True)
    c=baglanti();kad=g.k['kullanici_adi'];anahtar='panel:'+jeton
    var=c.execute('SELECT id,proje,ekleyen_id FROM kayitlar WHERE anahtar=?',(anahtar,)).fetchone()
    if var:return _ekleme_tekrar_yaniti(var)
    degerler,hatalar,yasak=_ekleme_dogrula(request.form,uygun)
    if yasak:
        _json_hata(403,'Bu projeye kanıt ekleme yetkiniz yok; kayıt '+degerler['proje']+' projesine eklenemez.',proje=degerler['proje'])
    if jeton not in (session.get('ekle_jeton') or []):
        return _ekleme_hata(400,'Form süresi doldu ya da başka bir oturumda açıldı; bilgileriniz korunarak form yenilendi, yeniden gönderin.',degerler,yeni_jeton=True)
    if hatalar:
        return _ekleme_hata(400,'Formda düzeltilmesi gereken alanlar var.',degerler,hatalar)
    proje=degerler['proje'];onayli=bool(degerler['onayli']) and yetki.izin(g.yk,proje,'kt')
    kat=katalog.panel_kategori(c)
    if not kat:
        return _ekleme_hata(400,'Panel ekleme kategorisi katalogda bulunamadı; süperadmine bildirin.',degerler)
    if not kat.get('aktif'):
        return _ekleme_hata(400,'Panel ekleme kategorisi (%s) katalogda pasif; panelden kanıt ekleme kapalı. Süperadmin katalogdan kategoriyi yeniden etkinleştirebilir.' % kat['label'],degerler)
    tanim=katalog.get_category(c,kat['code']) or {}
    sorular=[dict(q) for q in tanim.get('questions') or []]
    # Anlık görüntü panel formunun kuralını yansıtır: panelde yalnız Personel zorunlu, diğer hazır sorular isteğe bağlıdır.
    for q in sorular:
        if q.get('required') and q.get('preset')!='personel':q['required']=False
    cevaplar={q['key']:degerler[q['preset']] for q in sorular if q.get('preset') in degerler and degerler.get(q['preset'])}
    from . import bot_bildirim; uyari=None if request.form.get('yine_de')=='1' else bot_bildirim.panel_mukerrer(c,proje,kat['code'],degerler)  # 2.4.0 (Takım C)
    if uyari:return _ekleme_hata(409,uyari,dict(degerler,yine_de='1'),{'mukerrer':uyari})
    an=simdi()
    with db.transaction(c):
        var=c.execute('SELECT id,proje,ekleyen_id FROM kayitlar WHERE anahtar=?',(anahtar,)).fetchone()
        if var:return _ekleme_tekrar_yaniti(var)
        alanlar=dict(anahtar=anahtar,proje=proje,kategori=kat['label'],kategori_code=kat['code'],kategori_mode=kat.get('mode'),
                     personel=degerler['personel'],uye_id=degerler['uye_id'] or None,ana_uye_id=degerler['ana_uye_id'] or None,
                     lead_id=degerler['lead_id'] or None,tip=degerler['tip'] or None,link=degerler['link'],link_turu=degerler['link_tur'],
                     gorsel2=degerler['gorsel2'] or None,aciklama=degerler['aciklama'] or None,tarih=an,tarih_ham=an,guncelleme=an,
                     kt=1 if onayli else 0,excel_durum='var',ekleyen_id='panel:'+kad,ekleyen_ad=kad,ekleyen_guven='panel',
                     kaynak='panel',giris_tipi='panel',silindi=0,surum=1)
        if onayli:alanlar.update(kt_kaynak='panel',kt_kim=kad,kt_zaman=an)
        mevcut={row['name'] for row in c.execute('PRAGMA table_info(kayitlar)')}
        ekler={'kategori_soru_surumu':tanim.get('revision'),
               'soru_anlik_json':json.dumps({'questions':sorular,'category_code':kat['code'],'project':proje},ensure_ascii=False,separators=(',',':')),
               'cevaplar_json':json.dumps(cevaplar,ensure_ascii=False,separators=(',',':'))}
        alanlar.update({k:v for k,v in ekler.items() if k in mevcut})
        kid=c.execute('INSERT INTO kayitlar('+','.join(alanlar)+') VALUES('+','.join('?'*len(alanlar))+')',list(alanlar.values())).lastrowid
        if not onayli:db.bildirim_uret(c,kid,haric=kad)  # onaylı eklenen kayıt için onay bildirimi gerekmez
        db.denetim_yaz(c,kad,'panel_kanit_ekle',proje,anahtar,
                       yeni=json.dumps({'kayit':kid,'kategori':kat['label'],'personel':degerler['personel'],'onayli':onayli,'link_turu':degerler['link_tur']},ensure_ascii=False),
                       ip=ip(),hedef_turu='kayit',hedef_id=kid)
        db.degisti(c)
    _ekleme_jetonu_dus(jeton)
    mesaj='Kayıt #%d eklendi%s.' % (kid,' (onaylı)' if onayli else '; onay bekliyor')
    # ONAYSIZ_GORUNUM=gizle ve onay yetkisi yok: kullanıcı kendi eklediği onaysız kaydı da göremez; ayrıntı açılmaz, ileti bunu söyler.
    acilabilir=onayli or _onaysiz_modu()!='gizle' or yetki.izin(g.yk,proje,'kt')
    if not acilabilir:mesaj+=' Onaylanınca listede görünür.'
    if _json_bekleniyor():
        return jsonify(ok=True,id=kid,mesaj=mesaj,kt=1 if onayli else 0,proje=proje,kategori=kat['label'],acilabilir=acilabilir,damga=_degisiklik_damgasi(),jeton=_ekleme_jetonu())
    flash(mesaj)
    return redirect(url_for('kayitlar',durum='hepsi',proje=proje,ac=kid) if acilabilir else url_for('kayitlar',proje=proje))

@app.route('/kayit/<int:kid>/sil',methods=['POST'])
@giris_gerekli
def kayit_sil(kid):
    return _delete_state(kid,1)

@app.route('/kayit/<int:kid>/geri-al',methods=['POST'])
@giris_gerekli
def kayit_geri_al(kid):
    return _delete_state(kid,0)

def _delete_state(kid,value):
    c=baglanti()
    with db.transaction(c):
        r=_kayit_al(kid,'sil'); version_check(r)
        if bool(r['silindi'])==bool(value): return jsonify(ok=True,degisiklik=False)
        reason=db.metin_temizle(request.form.get('sebep') or '',300).strip()
        c.execute('UPDATE kayitlar SET silindi=?,silen=?,silme_zamani=?,surum=surum+1,guncelleme=? WHERE id=?',(value,g.k['kullanici_adi'] if value else None,simdi() if value else None,simdi(),kid))
        _kayit_bildirimlerini_kapat(c,kid)  # 2.4.0: silmede de geri almada da
        if value: from . import bot_bildirim; bot_bildirim.silme_kuyruga(c,r,reason)  # 2.4.0 (Takım C)
        db.denetim_yaz(c,g.k['kullanici_adi'],'sil' if value else 'geri_al',r['proje'],r['anahtar'],r['silindi'],value,ip(),aciklama=reason or None); db.degisti(c)
    return jsonify(ok=True,degisiklik=True,damga=_degisiklik_damgasi())

def _yer_tutucu_yaniti(kucuk,baslik,aciklama,durum):
    """Ham baytlar/500 yerine açıklayıcı yer tutucu görsel (200, X-Gorsel-Durum: bozuk|yok)."""
    from flask import make_response
    body=gorsel.yer_tutucu_svg(baslik,aciklama,400 if kucuk else 1200,300 if kucuk else 900)
    resp=make_response(body); resp.headers['Content-Type']='image/svg+xml; charset=utf-8'; resp.headers['X-Gorsel-Durum']=durum; resp.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'"
    resp.headers['Cache-Control']='no-store'
    return resp

def _bozuk_gorsel_yaniti(kucuk=False):
    """Bozuk/okunamayan dosya için ham baytlar yerine açıklayıcı yer tutucu görsel (200, X-Gorsel-Durum: bozuk)."""
    return _yer_tutucu_yaniti(kucuk,'Görsel açılamadı','Dosya sunucuda var ama bozuk ya da okunamıyor','bozuk')

def _dosya_gonder(yol,yeniden_coz,yoksa,**secenekler):
    """send_file yarış koruması: önbellek budaması yol çözümlendikten sonra dosyayı silmiş olabilir (FileNotFoundError → 500 ve
    'sunucu_hata' kaydı yerine) bir kez yeniden çözümlenir; yine yoksa `yoksa()` yanıtı (yer tutucu / 404) verilir."""
    try:return send_file(yol,**secenekler)
    except FileNotFoundError:pass
    try:
        yeni=yeniden_coz()
        if yeni:return send_file(yeni,**secenekler)
    except FileNotFoundError:pass
    return yoksa()

def _gorsel_yolu(kid,kucuk=False):
    """(yol, bozuk_mu) döndürür; yol yoksa 404. Bozuk dosyada yol yine verilir, çağıran yer tutucu gösterir."""
    r=_kayit_al(kid,'gorsel'); d={k:_metin(v) for k,v in dict(r).items()}
    if request.args.get('ikinci')=='1':
        d.update(gorsel_dosya=r['gorsel2_dosya'],link=r['gorsel2'],anahtar=str(r['anahtar'] or r['id'])+':2')
    # 2.3.2-inc: liste/galeri küçük resmi dış indirmeyi beklemez (arka planda başlatılır, yer tutucu döner);
    # ayrıntı görseli indirme yuvası için en çok GORSEL_ISTEK_BEKLEME_SN bekler.
    try: path,kaynak=COZUCU.gorsel_yolu(d,arka_plan=True) if kucuk else COZUCU.gorsel_yolu(d,bekle=gorsel.GORSEL_ISTEK_BEKLEME_SN)
    except Exception: path,kaynak=None,'yok'
    if not path and kaynak=='hazirlaniyor': return None,'hazirlaniyor'
    if not path: abort(404,'Bu kaydın yerel görseli eşleşmemiş.')
    if not kucuk: return path,not COZUCU.gecerli(path)
    thumb=COZUCU.kucuk(d,path)
    if thumb: return thumb,False
    return path,not COZUCU.gecerli(path)

@app.route('/gorsel/<int:kid>')
@giris_gerekli
def gorsel_goster(kid):
    path,bozuk=_gorsel_yolu(kid)
    if not path: abort(404)
    indir=request.args.get('indir')=='1'
    if bozuk and not indir: return _bozuk_gorsel_yaniti()
    name='kayit-%d%s%s' % (kid,'-2' if request.args.get('ikinci')=='1' else '',Path(path).suffix.lower() or '.jpg')
    return _dosya_gonder(path,lambda:_gorsel_yolu(kid)[0],lambda:_yer_tutucu_yaniti(False,'Görsel şu an okunamadı','Dosya yenileniyor; sayfayı yenileyin','yok'),
                         conditional=True,as_attachment=indir,download_name=name if indir else None)

@app.route('/kucuk/<int:kid>')
@giris_gerekli
def kucuk_goster(kid):
    path,bozuk=_gorsel_yolu(kid,True)
    if bozuk=='hazirlaniyor': return _yer_tutucu_yaniti(True,'Görsel hazırlanıyor','Dış siteden alınıyor; birkaç saniye sonra sayfayı yenileyin','hazirlaniyor')
    if not path: abort(404)
    if bozuk: return _bozuk_gorsel_yaniti(True)
    def yeniden():
        yol,bozuk=_gorsel_yolu(kid,True)  # küçük resim yeniden üretilir; olmazsa orijinal
        return None if bozuk else yol
    return _dosya_gonder(path,yeniden,lambda:_yer_tutucu_yaniti(True,'Görsel şu an okunamadı','Dosya yenileniyor; sayfayı yenileyin','yok'),conditional=True)

def _role_from_form():
    if 'rol' not in request.form and request.form.get('yetki'):
        return yetki.kanonikle(request.form['yetki'],projeler())
    if request.form.get('rol','admin')=='superadmin':return 'admin'
    if request.form.get('rol','admin')=='sahip':return 'sahip'
    if request.form.get('rol','admin')!='admin':raise ValueError('Geçersiz rol.')
    selected=request.form.getlist('projeler')
    if not selected or any(p not in projeler() for p in selected):raise ValueError('Admin için en az bir tanımlı proje seçin.')
    rules=[]
    for code in dict.fromkeys(selected):
        actions=set(request.form.getlist('eylemler_'+code))
        if not actions.issubset({'kt','duzenle','sil'}):raise ValueError('Geçersiz eylem.')
        actions.update(('oku','gorsel'))
        rules.append(code+':'+','.join(a for a in yetki.EYLEMLER if a in actions))
    return yetki.kanonikle(';'.join(rules),projeler())

GECICI_SIFRE_OMRU_DK=10        # üretilen geçici parola sunucuda en çok bu kadar kalır (admin görmese de)
GECICI_SIFRE_TEMIZLIK_SN=600   # dönüşüm işçisi döngüsünde süresi geçen kayıtların periyodik temizliği

def gecici_sifreleri_temizle(c=None):
    """Süresi geçen gecici_sifre:* satırlarını siler (düz metin parola panel.db'de ve günlük yedeklerde kalmasın).
    Çağrılma yerleri: geçici parola üretimi, Kullanıcılar sayfası GET'i (oturumda token olmasa da), süreç başı ve
    dönüşüm işçisinde 10 dakikada bir. Bağlantı verilmezse kendi bağlantısını açar; hata yutar, silinen sayısını döndürür."""
    kapat=c is None;silinen=0
    try:
        if c is None:c=db.baglan(AYAR['DB'])
        esik=(datetime.now()-timedelta(minutes=GECICI_SIFRE_OMRU_DK)).strftime('%Y-%m-%d %H:%M:%S')
        with db.transaction(c):
            for row in c.execute("SELECT anahtar,deger FROM ayarlar WHERE anahtar LIKE 'gecici_sifre:%'").fetchall():
                try:zaman=json.loads(row['deger']).get('zaman','')
                except (ValueError,TypeError,AttributeError):zaman=''
                if not zaman or zaman<esik:c.execute('DELETE FROM ayarlar WHERE anahtar=?',(row['anahtar'],));silinen+=1
    except Exception as hata:
        print('Geçici parola temizliği: '+type(hata).__name__,flush=True)
    finally:
        if kapat and c is not None:c.close()
    return silinen

def _gecici_sifre_sakla(ad,sifre,uretildi):
    """Geçici parola imzalı (şifrelenmemiş) oturum çerezine değil, sunucuda tek kullanımlık anahtara yazılır."""
    token=secrets.token_hex(16);c=baglanti()
    with db.transaction(c):
        gecici_sifreleri_temizle(c)
        db.ayar_yaz(c,'gecici_sifre:'+token,json.dumps({'ad':ad,'sifre':sifre,'uretildi':bool(uretildi),'zaman':simdi()},ensure_ascii=False))
    session['gecici_sifre']=token

def _gecici_sifre_al():
    c=baglanti();gecici_sifreleri_temizle(c)  # token olmasa da: sayfa her açıldığında süresi geçenler gider
    token=session.pop('gecici_sifre',None)
    if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token):return None
    with db.transaction(c):
        raw=db.ayar_al(c,'gecici_sifre:'+token)
        c.execute('DELETE FROM ayarlar WHERE anahtar=?',('gecici_sifre:'+token,))
    try:data=json.loads(raw) if raw else None
    except ValueError:return None
    return data if isinstance(data,dict) and data.get('zaman','')>=(datetime.now()-timedelta(minutes=GECICI_SIFRE_OMRU_DK)).strftime('%Y-%m-%d %H:%M:%S') else None

def _onay_kontrol(gerekce,beklenen):
    """2.4.0: tehlikeli değişiklikte yazılı onay (sunucuda doğrulanır). Onay alanı boş ya da farklıysa ValueError."""
    if gerekce and not kullanicilar.onay_dogru(beklenen,request.form.get('onay','')):
        raise ValueError(gerekce+' yazılı onay ister: onay kutusuna "'+str(beklenen)+'" yazın.')

@app.route('/yonetim/kullanicilar',methods=['GET','POST'])
@admin_gerekli
def yonetim_kullanicilar():
    mesaj=None;durum=200
    if request.method=='POST':
        try:
            op=request.form.get('islem')
            ad=(request.form.get('kullanici_adi') or request.form.get('kullanici') or request.form.get('ad','')).strip().lower()
            expected=request.form.get('expected_version',request.form.get('sv','-1'))
            actor=g.k['kullanici_adi']
            gorunen=db.metin_temizle(request.form.get('gorunen_ad') or '',120).strip()
            hedef=kullanicilar.bul(AYAR,ad) if op in ('guncelle','yetki','sifre','pasif','sahip_ata','iki_adim_sifirla','iki_adim_cihazlar','iki_adim_zorunlu') else None
            if op in ('guncelle','yetki','sifre','pasif','iki_adim_sifirla','iki_adim_cihazlar','iki_adim_zorunlu') and not hedef:raise ValueError('Hesap bulunamadı.')
            if op=='ekle':
                rol=_role_from_form()
                # 2.4.0: süperadmin/sahip hesabı yalnız sahip açar ve yazılı onay ister (yeni kullanıcı adını yazma).
                kullanicilar.yonetim_denetimi(g.yk,None,rol)
                _onay_kontrol(kullanicilar.onay_gerekli({'yetki':'','aktif':1},rol),ad)
                uretildi=not request.form.get('sifre')
                password=request.form.get('sifre') or secrets.token_urlsafe(15)
                if not uretildi and kullanicilar.parola_politikasi(ad,password):raise ValueError(kullanicilar.parola_politikasi(ad,password))
                # Hesap ilk girişte şifre değiştirmek zorunda açılır (kullanicilar.ekle → sifre_degistir=1).
                # 2.4.2: formdan açılan hesap varsayılan olarak 2FA zorunludur (kutu işaretli → 1, genel politika ne olursa olsun).
                # Kutu kaldırılırsa 0 = zorunlu değil; bu sayfa zaten yalnız süperadmin/sahibe açık. Alan işareti (iki_adim_alan)
                # olmayan eski/önbellekteki form da 1 kaydeder.
                zorunlu=0 if request.form.get('iki_adim_alan')=='1' and request.form.get('iki_adim_zorunlu')!='1' else 1
                kullanicilar.ekle(AYAR,ad,rol,password,gorunen or ad,actor,ip=ip(),iki_adim_zorunlu=zorunlu)
                _gecici_sifre_sakla(ad,password,uretildi)
                mesaj='Hesap açıldı: '+ad+'. İlk girişte değiştirilecek şifre aşağıdaki kutuda.'
            elif op=='guncelle':
                fields=dict(yetki=_role_from_form(),aktif=1 if request.form.get('aktif')=='1' else 0,
                            sifre_degistir=1 if request.form.get('sifredegistir')=='1' else 0,
                            gorunen_ad=gorunen or ad)
                kullanicilar.yonetim_denetimi(g.yk,hedef,fields['yetki'])
                if ad==actor and not fields['aktif']:raise ValueError('Kendi hesabınızı kapatamazsınız.')
                _onay_kontrol(kullanicilar.onay_gerekli(hedef,fields['yetki'],fields['aktif']),ad)
                if request.form.get('sifre'):
                    if kullanicilar.parola_politikasi(ad,request.form['sifre']):raise ValueError(kullanicilar.parola_politikasi(ad,request.form['sifre']))
                    fields['sifre']=request.form['sifre']
                    if ad!=actor:fields['sifre_degistir']=1  # Admin'in bildiği parola kalıcı olamaz: ilk girişte değiştirilir.
                kullanicilar.guncelle(AYAR,ad,expected_version=expected,islem_yapan=actor,ip=ip(),**fields)
                mesaj='Hesap ve açık proje kapsamı kaydedildi.'
            elif op=='yetki':
                rol=_role_from_form();kullanicilar.yonetim_denetimi(g.yk,hedef,rol)
                _onay_kontrol(kullanicilar.onay_gerekli(hedef,rol),ad)
                kullanicilar.guncelle(AYAR,ad,expected_version=expected,islem_yapan=actor,ip=ip(),yetki=rol);mesaj='Yetki güncellendi.'
            elif op=='sifre':
                kullanicilar.yonetim_denetimi(g.yk,hedef)
                password=secrets.token_urlsafe(15)
                kullanicilar.guncelle(AYAR,ad,expected_version=expected,islem_yapan=actor,ip=ip(),sifre=password,sifre_degistir=1)
                _gecici_sifre_sakla(ad,password,True)
                mesaj=ad+' için geçici şifre üretildi; aşağıdaki kutudan kopyalayın.'
            elif op=='pasif':
                if ad==actor:raise ValueError('Kendi hesabınızı kapatamazsınız.')
                kullanicilar.yonetim_denetimi(g.yk,hedef)
                _onay_kontrol(kullanicilar.onay_gerekli(hedef,None,0 if hedef['aktif'] else 1),ad)
                kullanicilar.guncelle(AYAR,ad,expected_version=expected,islem_yapan=actor,ip=ip(),aktif=0 if hedef['aktif'] else 1);mesaj='Hesap durumu değişti.'
            elif op=='sahip_ata':
                # İlk sahip ataması: etkin sahip yokken süperadmin tek bir hesabı (kendisi dahil) sahip yapar; sonrası yalnız sahipte.
                if kullanicilar.aktif_sahip_var(AYAR):raise kullanicilar.Yasak('Zaten etkin bir sahip var; yeni sahip atamasını yalnız sahip, hesabın Düzenle formundan yapar.')
                if not hedef:raise ValueError('Sahip yapılacak hesabı seçin.')
                _onay_kontrol('Sahip ataması',ad)
                u=kullanicilar.sahip_ata(AYAR,ad,actor,ip())
                if ad==actor:session['sv']=u['session_version']  # kendini atayan oturumda kalır
                mesaj=ad+' artık sahip. API anahtarları ve Erişim sınırı sayfaları yalnız sahibe açıktır.'
            elif op=='iki_adim_zorunlu':
                # 2.4.2: hesap başına 2FA zorunluluğu (Zorunlu / Zorunlu değil / Politikaya göre). Yalnız süperadmin ve sahip
                # değiştirir; bunlar HER hesap için değiştirebilir (diğer süperadminler, sahip, kendi hesapları dahil).
                # Satırın diğer düzenleme kısıtları burada uygulanmaz. Açık oturum düşmez.
                if not (g.yk.get('admin') or g.yk.get('sahip')):raise kullanicilar.Yasak('İki adımlı doğrulama zorunluluğunu yalnız süperadmin ve sahip değiştirebilir.')
                deger=iki_adim.hesap_ayari_degeri(request.form.get('iki_adim_zorunlu'))
                u=kullanicilar.guncelle(AYAR,ad,expected_version=expected if expected not in (None,'','-1') else None,islem_yapan=actor,ip=ip(),iki_adim_zorunlu=deger)
                mesaj='%s: iki adımlı doğrulama zorunluluğu → %s (şu an %s).' % (ad,iki_adim.HESAP_AYAR_ADLARI[iki_adim.hesap_ayari(u)],
                      'zorunlu' if iki_adim.zorunlu_mu(u,conn=baglanti()) else 'zorunlu değil')
            elif op in ('iki_adim_sifirla','iki_adim_cihazlar'):
                # 2.4.1: iki adımlı doğrulamayı sıfırlama / güvenilen cihazları iptal yalnız sahipte (telefon kaybı vb.).
                if not g.yk.get('sahip'):raise kullanicilar.Yasak('İki adımlı doğrulamayı sıfırlamayı ve güvenilen cihazları iptal etmeyi yalnız sahip yapabilir.')
                if op=='iki_adim_sifirla':
                    _onay_kontrol('İki adımlı doğrulamayı sıfırlama',ad)
                    onceki,cihaz=iki_adim.sifirla(baglanti(),ad,actor,ip())
                    if ad==actor:session['sv']=kullanicilar.bul(AYAR,ad)['session_version']  # kendini sıfırlayan oturumda kalır
                    mesaj=(ad+' için iki adımlı doğrulama sıfırlandı'+(' (%d güvenilen cihaz kaldırıldı)' % cihaz if cihaz else '')+
                           '; açık oturumları kapandı. Zorunluysa bir sonraki girişte yeniden kurar.') if onceki else ad+' hesabında iki adımlı doğrulama zaten kapalıydı; kalan kayıtlar temizlendi.'
                else:
                    n=iki_adim.cihazlari_kaldir(baglanti(),ad,actor,ip(),'sahip iptal etti')
                    mesaj='%s: %d güvenilen cihaz iptal edildi; bir sonraki girişte kod sorulur.' % (ad,n)
            else:raise ValueError('Bilinmeyen işlem.')
            flash(mesaj);return redirect(url_for('yonetim_kullanicilar'))
        except kullanicilar.Yasak as e:mesaj='Hata: '+str(e);durum=403
        except ValueError as e:mesaj='Hata: '+str(e);durum=200  # eski davranış: hata mesajıyla aynı sayfa (200)
    users=[]
    ben_sahip=bool(g.yk.get('sahip'))
    c_ia=baglanti();pol=iki_adim.politika(c_ia)
    cihaz_sayilari={r[0]:r[1] for r in c_ia.execute('SELECT kullanici_adi,COUNT(*) FROM iki_adim_cihazlar WHERE bitis>? GROUP BY kullanici_adi',(simdi(),))}
    for user in kullanicilar.hepsi(AYAR):
        parsed=yetki.coz(user['yetki']);rol=yetki.rol_kodu(user['yetki'])
        safe={k:v for k,v in user.items() if k not in ('sifre_hash','iki_adim_sir')}
        safe.update(iki_adim=iki_adim.durum_etiketi(user,pol),iki_adim_cihaz=cihaz_sayilari.get(user['kullanici_adi'],0),
                    iki_adim_hesap=iki_adim.hesap_ayari(user))
        safe.update(ozet=yetki.ozet(user['yetki']),rol=rol,rol_adi=yetki.ROL_ADLARI[rol],
                    duzenlenebilir=ben_sahip or rol=='proje',
                    parsed_yetkiler=dict(rol={'sahip':'sahip','superadmin':'superadmin'}.get(rol,'admin'),
                    projeler=list(parsed['projeler']),eylemler={p:list(a) for p,a in parsed['projeler'].items()}))
        users.append(safe)
    gecici=_gecici_sifre_al() if request.method=='GET' else None
    sahip_var=kullanicilar.aktif_sahip_var(AYAR)
    return render_template('kullanicilar.html',kullanicilar=users,mesaj=mesaj,tum_projeler=projeler(),gecici_sifre=gecici,
                           ben_sahip=ben_sahip,sahip_var=sahip_var,sahip_adaylari=[u for u in users if u['aktif']],
                           iki_adim_politika=pol,iki_adim_politika_adi=iki_adim.POLITIKA_ADLARI[pol],iki_adim_bekleyen=[u['kullanici_adi'] for u in users if u['aktif'] and u['iki_adim']=='zorunlu_bekliyor']),durum


@app.route('/yonetim/api-anahtarlari',methods=['GET','POST'])
@sahip_gerekli
def yonetim_api_anahtarlari():
    """2.3.2: dış sistemler için salt okunur API anahtarları. Yeni anahtar yalnız oluşturma yanıtında bir kez gösterilir (saklanmaz)."""
    c=baglanti();mesaj=None;yeni=None;durum=200
    if request.method=='POST':
        try:
            op=request.form.get('islem');kim=g.k['kullanici_adi']
            if op=='olustur':
                kapsam='*' if request.form.get('kapsam','secili')=='hepsi' else request.form.getlist('projeler')
                kid,anahtar=api_anahtarlari.olustur(c,request.form.get('ad',''),kapsam,yalniz_onayli=request.form.get('yalniz_onayli')=='1',
                    sql_izni=request.form.get('sql_izni')=='1',gorsel_izni=request.form.get('gorsel_izni')=='1',
                    son_kullanma=request.form.get('son_kullanma') or None,olusturan=kim,ip=ip(),tanimli_projeler=projeler(),
                    izinli_ipler=request.form.get('izinli_ipler',''))
                yeni=dict(id=kid,anahtar=anahtar,ad=db.metin_temizle(request.form.get('ad',''),80).strip())
                mesaj='Anahtar oluşturuldu. Aşağıdaki değeri şimdi kopyalayın; bir daha gösterilmez.'
            elif op in ('iptal','ip'):
                try:kid=int(request.form.get('id',''))
                except ValueError:raise ValueError('Anahtar bulunamadı.')
                row=c.execute('SELECT ad,iptal FROM api_anahtarlari WHERE id=?',(kid,)).fetchone()
                if not row:raise ValueError('Anahtar bulunamadı.')
                if op=='iptal':
                    # 2.4.0: iptal geri alınamaz; anahtarın adı yazılarak onaylanır (sunucuda doğrulanır).
                    if not row['iptal'] and not kullanicilar.onay_dogru(row['ad'],request.form.get('onay','')):
                        raise ValueError('İptal için onay kutusuna anahtarın adını ("'+row['ad']+'") yazın.')
                    mesaj='Anahtar iptal edildi; bu anahtarla gelen istekler artık reddedilir.' if api_anahtarlari.iptal(c,kid,kim,ip()) else 'Anahtar zaten iptal edilmişti.'
                else:
                    yeni_liste=api_anahtarlari.ip_guncelle(c,kid,request.form.get('izinli_ipler',''),kim,ip())
                    mesaj=('"'+row['ad']+'" anahtarı artık yalnız şu adreslerden kullanılabilir: '+yeni_liste.replace('\n',', ')) if yeni_liste else ('"'+row['ad']+'" anahtarı için ek IP sınırı kaldırıldı.')
                flash(mesaj);return redirect(url_for('yonetim_api_anahtarlari'))
            else:raise ValueError('Bilinmeyen işlem.')
        except ValueError as e:mesaj='Hata: '+str(e);durum=400
    # Oluşturma hatasında girilenler forma geri yazılır (ad, kapsam, projeler, izinler, tarih, IP listesi).
    giris=request.form if (request.method=='POST' and durum==400 and request.form.get('islem')=='olustur') else None
    return render_template('api_anahtarlari.html',anahtarlar=api_anahtarlari.listele(c),gunluk=api_anahtarlari.son_gunluk(c,50),
                           tum_projeler=projeler(),yeni=yeni,mesaj=mesaj,giris=giris,api_acik=api.acik_mi(),dakika_siniri=api.dakika_siniri(),
                           bugun=datetime.now().strftime('%Y-%m-%d'),kilavuz=_api_kilavuz(),erisim_durum=erisim.durum_ozeti(c,request)),durum


# 2.4.0 — Erişim sınırı (IP izin listesi; yalnız sahip). Kayıt/okuma erisim.ayar_oku / erisim.ayar_yaz üzerinden
# (genel Ayarlar sayfası da aynı işlevleri çağırabilir). Ayrıntı: app/erisim.py ve DEGISIKLIKLER_v2.4.0-B1.md.
@app.route('/yonetim/erisim',methods=['GET','POST'])
@sahip_gerekli
def yonetim_erisim():
    c=baglanti();mesaj=None;durum=200;form={}
    if request.method=='POST':
        form={k:request.form.get(k,'') for k in ('panel','api')}
        try:
            op=request.form.get('islem','kaydet');kim=g.k['kullanici_adi']
            if op=='temizle':
                tur=request.form.get('tur','panel')
                if tur not in erisim.TURLER:raise ValueError('Bilinmeyen liste.')
                if not kullanicilar.onay_dogru(kim,request.form.get('onay','')):
                    raise ValueError('Listeyi temizlemek için onay kutusuna kendi kullanıcı adınızı ("'+kim+'") yazın.')
                erisim.ayar_yaz(c,tur,'',kim,ip())
                mesaj=erisim.TURLER[tur][2]+' erişim listesi temizlendi; artık her adresten erişilebilir.'
            elif op=='kaydet':
                panel_yeni=erisim.normalle(form['panel']);api_yeni=erisim.normalle(form['api'])
                bilgi=erisim.istemci(request)
                if panel_yeni:
                    if bilgi['vekil_suphesi']:
                        raise ValueError('Sunucu ziyaretçi adresini göremiyor (TRUST_PROXY=1 gerekli). Bu durumda liste herkesi engeller; '
                                         'önce .env içinde TRUST_PROXY=1 yapıp kanit-web hizmetini yeniden başlatın.')
                    if not erisim.muaf_mi(request) and not erisim.izinli_mi(bilgi['ip'],erisim.liste_coz(panel_yeni)) and request.form.get('kendimi_disarida')!='1':
                        raise ValueError('Şu anki adresiniz ('+str(bilgi['ip'])+') panel listesinde yok; kaydederseniz panele bir daha giremezsiniz. '
                                         'Adresinizi ekleyin ya da "Kendi adresimi dışarıda bırakmayı anlıyorum" kutusunu işaretleyin.')
                eski_panel=erisim.ayar_oku(c,'panel')['metin'];eski_api=erisim.ayar_oku(c,'api')['metin']
                if eski_panel and not panel_yeni or eski_api and not api_yeni:
                    if not kullanicilar.onay_dogru(kim,request.form.get('onay','')):
                        raise ValueError('Dolu bir listeyi boşaltmak sınırı kaldırır; onay kutusuna kendi kullanıcı adınızı ("'+kim+'") yazın.')
                erisim.ayar_yaz(c,'panel',panel_yeni,kim,ip());erisim.ayar_yaz(c,'api',api_yeni,kim,ip())
                mesaj='Erişim sınırı kaydedildi. '+('Panel: '+str(len(panel_yeni.split())) +' adres/blok.' if panel_yeni else 'Panel: sınır yok.')+' '+('API: '+str(len(api_yeni.split()))+' adres/blok.' if api_yeni else 'API: genel sınır yok.')
            else:raise ValueError('Bilinmeyen işlem.')
            flash(mesaj);return redirect(url_for('yonetim_erisim'))
        except ValueError as e:mesaj='Hata: '+str(e);durum=400
    d=erisim.durum_ozeti(c,request)
    anahtar_listeleri=[a for a in api_anahtarlari.listele(c) if a.get('izinli_ipler') and a['durum']=='etkin']
    return render_template('erisim.html',d=d,mesaj=mesaj,form=form,anahtar_listeleri=anahtar_listeleri,
                           trust_proxy=str(AYAR.get('TRUST_PROXY','0')).lower() in ('1','true')),durum

def _api_kilavuz():
    """2.3.5: Kullanım kılavuzu kartı (örnekler panelin dış adresiyle: request.url_root; TRUST_PROXY ile X-Forwarded-* dikkate alınır)."""
    from . import api_kilavuz
    return api_kilavuz.kilavuz(request.url_root,api.dakika_siniri())

@app.route('/bot',methods=['GET','POST'])
@admin_gerekli
def bot_sayfasi():
    c=baglanti(); mesaj=None
    if request.method=='POST':
        op=request.form.get('islem'); tg=request.form.get('tg_id','').strip(); ad=request.form.get('ad','').strip(); kim=g.k['kullanici_adi']
        try:
            # Ad boşsa kullanıcının Telegram'dan gelen adı korunur; sayısal ID ada yazılmaz.
            if op=='onayla': bot_yonetim.onayla(AYAR,c,tg,ad,kim)
            elif op=='onay_kaldir': bot_yonetim.onay_kaldir(AYAR,c,tg,kim)
            elif op=='engelle': bot_yonetim.engelle(AYAR,c,tg,ad,request.form.get('sebep') or 'panel',kim)
            elif op=='engel_kaldir': bot_yonetim.engel_kaldir(AYAR,c,tg,kim)
            elif op in ('bakim_ac','bakim_kapat'): bot_yonetim.bakim_modu_ayarla(AYAR,c,op=='bakim_ac',kim)
            elif op=='oturum_temizle': bot_yonetim.oturum_temizle(AYAR,c,tg or None,kim)
            elif op=='kategori_ekle':
                from . import katalog
                katalog.save_category(c,request.form.get('code',''),request.form.get('label',''),mode=request.form.get('mode','tek_uye'),projects=projeler(),questions=None,actor=kim)
            elif op=='kategori_sil': bot_yonetim.kategori_sil(AYAR,c,request.form.get('code',''),kim)
            elif op=='yedek': mesaj=bot_yonetim.geri_yuklenebilir_yedek_al(AYAR,c,kim,ip())  # 2.4.0: --geri-yukle ile açılır (.db.gz)
            elif op=='tam_sifirla': bot_yonetim.tam_sifirla(AYAR,c,tg,kim)
            elif op in ('bot_duraklat','bot_surdur'): bot_yonetim.bot_kontrol(AYAR,c,op=='bot_duraklat',kim)
            elif op=='kategori_yayinla': mesaj='Kategori değişiklikleri kaydedildiği anda geçerlidir.'
            elif op=='inbox_tekrar': bot_yonetim.tekrar_dene(AYAR,c,request.form.get('update_id') or None,kim)
            elif op=='yenile': pass
            else: raise ValueError('Bilinmeyen işlem.')
            mesaj=mesaj or 'İşlem sunucuya uygulandı.'
        except (ValueError,OSError) as e: mesaj='Hata: '+str(e)
    sure=bot_yonetim.sure_normalle(request.args.get('sure',''))
    if request.args.get('sure','') and not sure and not mesaj: mesaj='Son görülme filtresi tanınmadı; tüm zamanlar gösteriliyor.'
    tg_durum=request.args.get('tg_durum','hepsi') if request.args.get('tg_durum','hepsi') in ('hepsi','onayli','engelli','onaysiz') else 'hepsi'
    return render_template('bot.html',mesaj=mesaj,durum=durum_bilgisi(),istatistik=bot_yonetim.istatistik(c),kullanici_q=request.args.get('q','')[:100],kullanici_durum=tg_durum,kullanici_sure=sure,tg_kullanicilar=bot_yonetim.kullanicilari_ara(c,request.args.get('q',''),tg_durum,sure,limit=500),olu_mektuplar=[dict(r) for r in c.execute("SELECT bot_id,update_id,deneme,hata,guncelleme FROM tg_gelen WHERE durum='olu' ORDER BY guncelleme DESC LIMIT 50")],kategoriler=bot_yonetim.kategoriler(AYAR),bakim=bot_yonetim.bakim_modu(AYAR),oturumlar=bot_yonetim.oturumlar(AYAR),log=bot_yonetim.son_log(AYAR,150),hatalar=bot_yonetim.son_log(AYAR,40,True),cfg=bot_yonetim.config(AYAR),islemler=bot_yonetim.son_islemler(c))

@app.route('/bot/islemler.json')
@admin_gerekli
def bot_islemler_json():
    return jsonify(islemler=bot_yonetim.son_islemler(baglanti()),bekleyen=0)

# 2.4.0 — İşlem Geçmişi: serbest arama (kayıt no/anahtar, personel, kullanıcı, açıklama, IP), IP sütunu (yalnız yönetici),
# okunur ayrıntı (rol, onay, ayar, alan değişiklikleri; "Ham" düğmesiyle özgün değer), CSV ve hızlı tarih düğmeleri.
ISLEM_ADLARI.update({'sahip_atama':'Sahip atadı','erisim_ayar':'Erişim sınırını değiştirdi','erisim_red':'İzinsiz adresten erişim engellendi',
                     'api_anahtar_ip':'API anahtarının IP listesini değiştirdi','denetim_aktar':'İşlem Geçmişi CSV indirdi'})
DENETIM_ADLARI.update({'sahip_atama':'Sahip ataması','erisim_ayar':'Erişim sınırı ayarı','erisim_red':'Erişim engeli (IP)',
                       'api_anahtar_ip':'API anahtarı IP listesi','denetim_aktar':'İşlem Geçmişi CSV'})
DENETIM_ALAN_ADLARI={'yetki':'Rol','aktif':'Durum','ad':'Görünen ad','sifre_degistir':'İlk girişte şifre değiştirme','parola_degisti':'Parola',
                     'personel':'Personel','kategori':'Kategori','aciklama':'Açıklama','tarih':'Tarih','uye_id':'Üye no','ana_uye_id':'Ana üye no',
                     'lead_id':'Lead','link':'Link','proje':'Proje','izinli_ipler':'İzinli adresler','adresler':'Adresler','projeler':'Projeler',
                     'yalniz_onayli':'Yalnız onaylı','sql_izni':'SQL izni','gorsel_izni':'Görsel izni','son_kullanma':'Son kullanma','onek':'Önek',
                     'hatali_giris':'Hatalı deneme','kilit_bitis':'Kilit bitişi','liste':'Liste','kaynak':'Kaynak'}
CSV_EN_COK_SATIR=50000

def _json_sozluk(value):
    try:data=json.loads(value) if isinstance(value,str) else value
    except (ValueError,TypeError):return None
    return data if isinstance(data,dict) else None

def _denetim_deger(alan,value):
    if alan=='yetki':return yetki.ozet(value) if value is not None else '—'
    if alan=='aktif':return 'Aktif' if value in (1,True,'1') else 'Pasif'
    if alan in ('sifre_degistir','yalniz_onayli','sql_izni','gorsel_izni'):return 'evet' if value in (1,True,'1') else 'hayır'
    if alan=='parola_degisti':return 'değiştirildi'
    if isinstance(value,list):return ', '.join(str(x) for x in value) if value else '(boş — sınır yok)' if alan in ('adresler','izinli_ipler') else '(boş)'
    if value is None or value=='':return '—'
    return str(value)

def _denetim_okunur(item):
    """İşlem Geçmişi okunur satırları (ham JSON yerine). Liste ya da None (özel biçim yok → eski 'Önceki / yeni' gösterimi)."""
    code=str(item.get('islem') or '');eski=_json_sozluk(item.get('eski'));yeni=_json_sozluk(item.get('yeni'))
    if code in ('onayla','onay_kaldir','sil','geri_al','bildirim_okundu'):return None
    if code=='erisim_ayar' and (eski or yeni):
        liste=(yeni or eski or {}).get('liste','')
        return [liste+' listesi: '+_denetim_deger('adresler',(eski or {}).get('adresler',[]))+' → '+_denetim_deger('adresler',(yeni or {}).get('adresler',[]))]
    if eski is None and yeni is None:return None
    eski=eski or {};yeni=yeni or {};lines=[]
    for alan in list(dict.fromkeys([*eski.keys(),*yeni.keys()])):
        ad=DENETIM_ALAN_ADLARI.get(alan,alan.replace('_',' '))
        if alan in eski and alan in yeni:
            if eski[alan]==yeni[alan]:lines.append(ad+': değiştirildi');continue  # gizlenen değerler ([GİZLİ]) aynı görünür
            lines.append(ad+': '+_denetim_deger(alan,eski[alan])+' → '+_denetim_deger(alan,yeni[alan]))
        elif alan in yeni:lines.append(ad+': '+_denetim_deger(alan,yeni[alan]))
        else:lines.append(ad+' (önceki): '+_denetim_deger(alan,eski[alan]))
    return lines or None

def _denetim_sorgu(args):
    """(where listesi, parametreler, filtreler, uyarı). Kapsam kuralları: süperadmin hepsini, diğerleri yalnız yetkili projelerin kayıtlarını görür."""
    allowed=_allowed();where=['1=1'];params=[]
    if not g.yk['admin']:
        if not allowed:abort(403)
        where.append('k.proje IN ('+','.join('?' for _ in allowed)+')');params.extend(allowed)
        gizli_sql,gizli_par=_gizli_kayit_sql('k',allowed,sol_birlesim=True)
        if gizli_sql:where.append(gizli_sql);params.extend(gizli_par)
    filters={key:args.get(key,'')[:100] for key in ('q','kullanici','islem','proje','tarih1','tarih2')}
    if filters['proje']:
        if filters['proje'] not in allowed:abort(403)
        where.append('d.proje=?');params.append(filters['proje'])
    for key in ('kullanici','islem'):
        if filters[key]:where.append('d.'+key+' LIKE ?');params.append('%'+filters[key]+'%')
    q=filters['q'].strip()
    if q:
        # LIKE joker karakterleri (% _ \) kaçışlanır: 'tg:1_2' araması 'tg:1x2' ile eşleşmesin.
        like='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        kosul=["d.kullanici LIKE ? ESCAPE '\\'","d.islem LIKE ? ESCAPE '\\'","d.anahtar LIKE ? ESCAPE '\\'","d.hedef_id LIKE ? ESCAPE '\\'","k.personel LIKE ? ESCAPE '\\'","d.aciklama LIKE ? ESCAPE '\\'"]
        par=[like]*6
        if g.yk['admin']:kosul.append("d.ip LIKE ? ESCAPE '\\'");par.append(like)
        no=q.lstrip('#').strip()
        # 19+ haneli sayı SQLite INTEGER'a sığmaz (OverflowError → 500); o zaman yalnız LIKE aramaları kullanılır.
        if no.isascii() and no.isdigit() and len(no)<=18:kosul.append('k.id=?');par.append(int(no))
        where.append('('+' OR '.join(kosul)+')');params.extend(par)
    uyari=None
    for key,op,tail in (('tarih1','>=',' 00:00:00'),('tarih2','<=',' 23:59:59')):
        if filters[key]:
            try:datetime.strptime(filters[key],'%Y-%m-%d')
            except ValueError:uyari='Geçersiz tarih.';continue
            where.append('d.zaman '+op+' ?');params.append(filters[key]+tail)
    if filters['tarih1'] and filters['tarih2'] and filters['tarih1']>filters['tarih2']:
        # Bildirimler sayfasıyla aynı kural: tam sayfa 400 yerine formda uyarı; form değerleri korunur.
        uyari='Başlangıç tarihi bitişten sonra olamaz.'
    return where,params,filters,uyari

def _denetim_satiri(row):
    from .guvenli_log import log_row
    item=log_row(row)
    if item['record_id']:item.update(hedef_turu='kayit',hedef_id=str(item['record_id']))
    elif item.get('hedef_turu')=='kayit':
        # Kayıt tablosunda karşılığı olmayan hedef: proje kaydı ya da artık bulunmayan kayıt anahtarı.
        item['hedef_turu']='proje' if str(item.get('islem') or '').startswith('katalog_proje') else 'anahtar'
    if 'hata' in item['islem']:item['sonuc']='hata'
    item['sonuc']={'ok':'Başarılı','hata':'Hata','uyari':'Uyarı'}.get(item.get('sonuc'),item.get('sonuc') or 'Tamamlandı')
    item['islem_adi']=islem_adi(item['islem'],DENETIM_ADLARI);item['islem_bilinen']=item['islem'] in DENETIM_ADLARI
    item['ayrinti'],item['ayrinti_katla']=_denetim_ayrinti(item)
    item['okunur']=_denetim_okunur(item)
    item['sebep_etiketi']='Sebep' if item['islem'] in ('sil','geri_al') else 'Açıklama'
    if not g.yk['admin']:item['ip']=None  # IP adresleri yalnız yöneticiye görünür
    return item

DENETIM_SORGU_KAYNAK=' FROM denetim d LEFT JOIN kayitlar k ON k.anahtar=d.anahtar WHERE '

@app.route('/denetim')
@giris_gerekli
def denetim():
    where,params,filters,uyari=_denetim_sorgu(request.args)
    try:page=max(1,min(1000000,int(request.args.get('s','1'))))
    except ValueError:abort(400)
    source=DENETIM_SORGU_KAYNAK+' AND '.join(where)
    total=0 if uyari else baglanti().execute('SELECT COUNT(*)'+source,params).fetchone()[0]
    rows=[_denetim_satiri(row) for row in ([] if uyari else baglanti().execute('SELECT d.*,k.id record_id,k.personel kayit_personel'+source+' ORDER BY d.id DESC LIMIT 50 OFFSET ?',[*params,(page-1)*50]))]
    bugun=datetime.now().date()
    hizli=[('Bugün',bugun,bugun),('Son 7 gün',bugun-timedelta(days=6),bugun),('Son 30 gün',bugun-timedelta(days=29),bugun),('Bu ay',bugun.replace(day=1),bugun)]
    hizli_tarih=[dict(ad=ad,tarih1=t1.isoformat(),tarih2=t2.isoformat(),secili=filters['tarih1']==t1.isoformat() and filters['tarih2']==t2.isoformat()) for ad,t1,t2 in hizli]
    csv_args={k:v for k,v in filters.items() if v}
    return render_template('denetim.html',logs=rows,kayitlar=rows,toplam=total,sayfa=page,sayfa_sayisi=max(1,(total+49)//50),filters=filters,q=filters['q'],
                           islem_adlari=DENETIM_ADLARI,uyari=uyari,ip_goster=bool(g.yk['admin']),hizli_tarih=hizli_tarih,csv_url=url_for('denetim_csv',**csv_args))

@app.route('/denetim.csv')
@giris_gerekli
def denetim_csv():
    """Süzülmüş İşlem Geçmişi: UTF-8 BOM + ';' + CRLF (Türkçe Excel), formül enjeksiyonuna karşı güvenli hücreler, en çok 50.000 satır."""
    import csv
    from flask import Response
    where,params,filters,uyari=_denetim_sorgu(request.args)
    if uyari:abort(400,uyari)
    source=DENETIM_SORGU_KAYNAK+' AND '.join(where)
    ip_goster=bool(g.yk['admin'])
    out=io.StringIO();w=csv.writer(out,delimiter=';',lineterminator='\r\n',quoting=csv.QUOTE_MINIMAL)
    w.writerow(['Zaman','Kullanıcı','İşlem','İşlem kodu','Hedef','Proje','Personel','Sonuç','Ayrıntı','Açıklama']+(['IP'] if ip_goster else []))
    adet=0
    for row in baglanti().execute('SELECT d.*,k.id record_id,k.personel kayit_personel'+source+' ORDER BY d.id DESC LIMIT ?',[*params,CSV_EN_COK_SATIR]):
        r=_denetim_satiri(row);adet+=1
        hedef=('Kayıt #'+str(r['hedef_id'])) if r.get('hedef_turu')=='kayit' and r.get('hedef_id') else (r.get('hedef_id') or r.get('anahtar') or '')
        ayrinti=' | '.join(r['okunur'] or r['ayrinti'] or [])
        hucreler=[r.get('zaman'),r.get('kullanici'),r.get('islem_adi'),r.get('islem'),hedef,r.get('proje'),r.get('kayit_personel'),r.get('sonuc'),ayrinti,r.get('aciklama')]+([r.get('ip')] if ip_goster else [])
        w.writerow([personel_ozeti.guvenli_hucre('' if v is None else str(v)) for v in hucreler])
    db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'denetim_aktar',yeni='csv:%d' % adet,ip=ip(),hedef_turu='sistem',aciklama='İşlem Geçmişi CSV')
    resp=Response(('\ufeff'+out.getvalue()).encode('utf-8'),mimetype='text/csv; charset=utf-8')
    resp.headers['Content-Disposition']='attachment; filename="islem-gecmisi-%s.csv"' % datetime.now().strftime('%Y%m%d-%H%M')
    return resp


@app.route('/durum.json')
@admin_gerekli
def durum_json():
    return jsonify(durum_bilgisi())

def _scoped_counts():
    allowed=_allowed()
    if not allowed:return {},'0'
    places=','.join('?' for _ in allowed)
    gizli_sql,gizli_par=_gizli_kayit_sql('',allowed)
    rows=baglanti().execute('SELECT proje,SUM(kt=0 AND silindi=0) bekleyen,SUM(kt=1 AND silindi=0) onayli,SUM(silindi=1) silinen,COUNT(*) toplam,SUM(surum) version_sum,SUM(kt=0 AND silindi=0 AND '+_GECIKEN_SQL+') geciken FROM kayitlar WHERE proje IN ('+places+')'+(' AND '+gizli_sql if gizli_sql else '')+' GROUP BY proje',[_hatirlatma_gun(),*allowed,*gizli_par]).fetchall()
    counts={p:dict(bekleyen=0,onayli=0,silinen=0,toplam=0,geciken=0) for p in allowed}
    stamp=[]
    for row in rows:
        counts[row['proje']]={key:row[key] or 0 for key in ('bekleyen','onayli','silinen','toplam','geciken')}
        stamp.append([row['proje'],row['toplam'],row['version_sum'],row['onayli'],row['silinen']])
    comments=baglanti().execute('SELECT COUNT(*),MAX(y.id) FROM yorumlar y JOIN kayitlar k ON k.id=y.kayit_id WHERE k.proje IN ('+places+')',allowed).fetchone()
    stamp.append(list(comments))
    return counts,json.dumps(stamp,separators=(',',':'))

BILDIRIM_TUR_ADLARI={'soru':'Soru','yanit':'Yanıt','yorum':'Yorum','onay':'Onay','kanit':'Yeni kanıt','kayit':'Yeni kayıt','onay_kaldir':'Onay kaldırıldı','hatirlatma':'Hatırlatma'}

def _bildirim_hedef(row):
    """2.3.1: bildirime tıklanınca açılacak adres. Kayıt → kayıt modalı (durum=hepsi, liste dışı olsa da açılır);
    yorum/soru/yanıt → aynı modalda ilgili yorum vurgulanır (&yorum=); hatırlatma özeti → projenin bekleyen listesi.
    2.3.3: gün sonu özeti → tüm projelerin bekleyen listesi; 2 saat toplu bildirimi → projenin bekleyen listesi (gün süzgeci yok);
    2 saat kayıt hatırlatması → kayıt modalı (aşağıdaki genel yol).
    2.3.8: bekleyen özeti → kullanıcının onay yetkisi olan projelerinin bekleyen listesi (yönetici ya da tüm projelerinde
    onay yetkisi olan kullanıcı: proje süzgeci yok)."""
    olay=str(row.get('olay') or '')
    if olay.startswith('bekleyen-ozet:'):
        yk=g.get('yk') or yetki.coz('')
        izinli=yetki.izinli_projeler(yk,projeler()) if g.get('yk') else []
        kt=[p for p in izinli if yetki.izin(yk,p,'kt')]
        if yk.get('admin') or not kt or len(kt)==len(izinli):
            return url_for('kayitlar',durum='bekleyen')
        return url_for('kayitlar',proje=kt,durum='bekleyen')
    if olay.startswith('gun-sonu:'):
        return url_for('kayitlar',durum='bekleyen')
    if olay.startswith('sistem:'):  # 2.4.0: Sistem durumu uyarısı → ana sayfadaki kart
        return url_for('ana',_anchor='sistem-durumu')
    if olay.startswith('hatirlatma-saat-ozet:'):
        return url_for('kayitlar',proje=row.get('proje'),durum='bekleyen')
    if row.get('ozet') or olay.startswith('hatirlatma-ozet:'):
        return url_for('kayitlar',proje=row.get('proje'),durum='bekleyen',bekleme=_hatirlatma_gun())
    args=dict(proje=row.get('proje'),durum='hepsi',ac=row.get('kayit_id'))
    if row.get('yorum_id'): args['yorum']=row['yorum_id']
    return url_for('kayitlar',**args)

@app.route('/bildirim.json')
@giris_gerekli
def bildirim_json():
    from . import bildirim_gecmisi
    data=bildirim_gecmisi.liste(baglanti(),g.k['kullanici_adi'],_allowed(),{'durum':'okunmamis'},20,gizli=_gizli_kayit_sql('k'))
    counts,stamp=_scoped_counts()
    alerts=[]
    for row in data['bildirimler']:
        item=dict(row);item['bildirim_id']='m:'+str(row['id']) if row['key'].startswith('mesaj:') else str(row['id']);item['id']=row['kayit_id']
        item['kayit_id']=row['kayit_id'];item['personel']=row.get('personel') or '';item['kategori']=row.get('kategori') or ''
        item['url']=_bildirim_hedef(row);item['etiket']=BILDIRIM_TUR_ADLARI.get(row.get('tur'),row.get('tur') or 'Bildirim');item['ozet']=bool(row.get('ozet'))
        alerts.append(item)
    return jsonify(bildirimler=alerts,okunmamis=data['counts']['okunmamis'],sayac=counts,degisiklik=stamp,kuyruk_bekleyen=0)

@app.route('/bildirimler')
@giris_gerekli
def bildirim_sayfasi():
    from . import bildirim_gecmisi
    filters=request.args.to_dict()
    if filters.get('okundu') in ('0','1'):filters['durum']='okunmamis' if filters['okundu']=='0' else 'okundu'
    elif filters.get('okundu'):abort(400)
    if filters.get('tur')=='kayit':filters['tur']='kanit'
    if 'sayfa' in filters and 's' not in filters:filters['s']=filters['sayfa']
    try:data=bildirim_gecmisi.liste(baglanti(),g.k['kullanici_adi'],_allowed(),filters,gizli=_gizli_kayit_sql('k'))
    except PermissionError:abort(403)
    except ValueError as error:
        # Ters tarih aralığı gibi girdi hataları: tam sayfa 400 yerine formun içinde uyarı; seçimler korunur.
        kept={key:str(filters.get(key,''))[:40] for key in ('tur','proje','tarih1','tarih2')}
        kept['okundu']=filters.get('okundu','') if filters.get('okundu') in ('0','1') else ''
        return render_template('bildirimler.html',bildirimler=[],toplam=0,sayfa=1,sayfa_sayisi=1,counts={},turler=[],filters=kept,uyari=str(error))
    data['filters']['okundu']='0' if data['filters']['durum']=='okunmamis' else '1' if data['filters']['durum']=='okundu' else ''
    for row in data['bildirimler']:row['url']=_bildirim_hedef(row)
    return render_template('bildirimler.html',tur_adlari=BILDIRIM_TUR_ADLARI,**data)

@app.route('/bildirimler/okundu',methods=['POST'])
@giris_gerekli
def bildirim_okundu():
    from . import bildirim_gecmisi
    payload=request.get_json(silent=True) if request.is_json else None
    payload=payload or {}
    all_visible=payload.get('hepsi') in (True,1,'1') or request.form.get('hepsi')=='1'
    ids=payload.get('ids') if request.is_json else request.form.getlist('ids')
    if not ids and request.form.get('id'):ids=[request.form['id']]
    if ids is None:ids=[]
    if not isinstance(ids,list) or (not all_visible and not ids):abort(400)
    try:changed=bildirim_gecmisi.okundu(baglanti(),g.k['kullanici_adi'],_allowed(),ids,all_visible)
    except ValueError:abort(400)
    return jsonify(ok=True,degisen=changed)


@app.route('/kayit/<int:kid>/yorum',methods=['POST'])
@giris_gerekli
def kayit_yorum(kid):
    from . import discussion
    c=baglanti();_kayit_al(kid,'kt')
    try:
        cid=discussion.add(c,kid,g.k['kullanici_adi'],request.form.get('yorum',''),request.form.get('alici',''),request.form.get('yanit_id') or None)
    except PermissionError:abort(403)
    except ValueError as e:return jsonify(ok=False,hata=str(e)),400
    return jsonify(ok=True,yorum_id=cid,damga=_degisiklik_damgasi())

@app.route('/arsiv',methods=['GET','POST'])
@admin_gerekli
def arsiv():
    c=baglanti()
    if request.method=='POST':
        if request.form.get('islem')=='tara':
            report=gorsel.arsiv_tara(AYAR,c,COZUCU); flash(_arsiv_rapor_metni(report),'hata' if report.get('hata') else 'message')
        elif request.form.get('islem')=='esle':
            try: aid=int(request.form.get('arsiv_id',0)); kid=int(request.form.get('kayit_id',0))
            except ValueError: abort(400)
            with db.transaction(c):
                a=c.execute('SELECT * FROM arsiv_dosyalar WHERE id=?',(aid,)).fetchone(); r=c.execute('SELECT * FROM kayitlar WHERE id=?',(kid,)).fetchone()
                if not r: flash('Kayıt bulunamadı: #%d numaralı kayıt yok. Kayıt numarasını Kayıtlar sayfasından kontrol edin.' % kid,'hata'); return redirect(url_for('arsiv'))
                if not kayit_izin(r,'duzenle'): flash('#%d numaralı kayıt %s projesinde; bu projede düzenleme yetkiniz yok.' % (kid,r['proje']),'hata'); return redirect(url_for('arsiv'))
                if not a: flash('Arşiv dosyası bulunamadı; arşivi yeniden tarayın.','hata'); return redirect(url_for('arsiv'))
                path=Path(a['yol']).resolve(); root=Path(AYAR['ARSIV_KLASOR']).resolve()
                if not path.is_relative_to(root) or not path.is_file(): flash('Arşiv dosyası diskte yok ya da arşiv klasörünün dışında; arşivi yeniden tarayın.','hata'); return redirect(url_for('arsiv'))
                column='gorsel2_dosya' if request.form.get('ikinci')=='1' else 'gorsel_dosya'
                if r[column] and request.form.get('degistir')!='1':
                    flash('#%d numaralı kayıtta zaten bir görsel bağı var (%s). Değiştirmek istiyorsanız "Varsa mevcut görsel bağını değiştir" kutusunu işaretleyip tekrar "İlişkilendir" deyin.' % (kid,Path(str(r[column])).name),'hata'); return redirect(url_for('arsiv'))
                c.execute(f'UPDATE kayitlar SET {column}=?,surum=surum+1,guncelleme=? WHERE id=?',(str(path),simdi(),kid))
                c.execute('UPDATE arsiv_dosyalar SET kayit_id=?,guncelleme=? WHERE id=?',(kid,simdi(),aid))
                db.denetim_yaz(c,g.k['kullanici_adi'],'arsiv_esle',r['proje'],r['anahtar'],r[column],a['ad'],ip()); db.degisti(c)
            flash('Görsel kayıtla ilişkilendirildi.')
        return redirect(url_for('arsiv'))
    try: page=max(1,int(request.args.get('s',1)))
    except ValueError: page=1
    q=request.args.get('q','')[:100]; state=request.args.get('durum','eslesmeyen')
    where='ad LIKE ?'+(' AND kayit_id IS NULL' if state=='eslesmeyen' else '')
    total=c.execute(f'SELECT COUNT(*) FROM arsiv_dosyalar WHERE {where}',('%'+q+'%',)).fetchone()[0]
    rows=c.execute(f'SELECT * FROM arsiv_dosyalar WHERE {where} ORDER BY id LIMIT 48 OFFSET ?',('%'+q+'%',(page-1)*48))
    return render_template('arsiv.html',dosyalar=[dict(r) for r in rows],toplam=total,sayfa=page,sayfa_sayisi=max(1,(total+47)//48),q=q,durum=state)

def _arsiv_rapor_metni(report):
    """Tarama sonucunu ham JSON yerine okunur Türkçe cümleye çevirir."""
    r=report or {}
    if r.get('hata'):return 'Arşiv taranamadı: '+str(r['hata'])+'.'
    parts=['%d dosya tarandı' % (r.get('tarandi') or 0),'%d dosya indekslendi' % (r.get('indekslendi') or 0),'%d görsel kayıtla eşleşti' % (r.get('eslesti') or 0)]
    if r.get('eslesmeyen'):parts.append('%d görsel eşleşmedi' % r['eslesmeyen'])
    if r.get('belirsiz'):parts.append('%d görsel belirsiz kaldı' % r['belirsiz'])
    return 'Arşiv tarandı: '+', '.join(parts)+'.'

@app.route('/arsiv/gorsel/<int:aid>')
@admin_gerekli
def arsiv_gorsel(aid):
    r=baglanti().execute('SELECT yol FROM arsiv_dosyalar WHERE id=?',(aid,)).fetchone()
    if not r: abort(404)
    path=Path(r['yol']).resolve(); root=Path(AYAR['ARSIV_KLASOR']).resolve()
    if not path.is_relative_to(root) or not path.is_file(): abort(404)
    if request.args.get('kucuk')=='1':
        thumb=COZUCU.kucuk({'anahtar':'archive:'+str(aid)},str(path))
        if not thumb:abort(404)
        # Budama küçük resmi sildiyse bir kez yeniden üret; o da yoksa orijinal arşiv dosyası (az önce is_file ile doğrulandı).
        return _dosya_gonder(thumb,lambda:COZUCU.kucuk({'anahtar':'archive:'+str(aid)},str(path)),lambda:send_file(str(path),conditional=True),conditional=True)
    return send_file(path,conditional=True)

def _cikti_secimi(args):
    """Çıktı formunun gönderilen değerleri; hata/uyarı halinde form aynı değerlerle yeniden gösterilir."""
    today=datetime.now().date()
    if args is None:
        return dict(proje=[],tarih1=(today-timedelta(days=30)).isoformat(),tarih2=today.isoformat(),durum='hepsi',kategori='',q='',ekleyen='',tarihsiz=False,tarih_alani='eklenme')
    return dict(proje=[str(x).strip().upper() for x in args.getlist('proje') if str(x).strip()],tarih1=args.get('tarih1','').strip()[:10],tarih2=args.get('tarih2','').strip()[:10],
                durum=args.get('durum','hepsi'),kategori=args.get('kategori','').strip()[:120],q=args.get('q','').strip()[:200],ekleyen=args.get('ekleyen','').strip()[:100],tarihsiz=args.get('tarihsiz')=='1',tarih_alani=_tarih_alani(args))

def _cikti_tarih_hatasi(args):
    if args.get('tarihsiz')=='1':
        return 'Tarihsiz kayıt seçeneği tarih aralığıyla birlikte kullanılamaz.' if (args.get('tarih1') or args.get('tarih2')) else None
    t1,t2=args.get('tarih1','').strip(),args.get('tarih2','').strip()
    for v in (t1,t2):
        if v:
            try:datetime.strptime(v,'%Y-%m-%d')
            except ValueError:return 'Tarih biçimi geçersiz; takvimden seçin.'
    if t1 and t2 and t1>t2:return 'Başlangıç tarihi bitiş tarihinden sonra olamaz.'
    return None

# Tek istekte yazılacak en çok kayıt; aşılırsa tarih aralığı/filtre daraltma istenir (bellek ve iş parçacığı koruması).
# Varsayılan 30.000 (eskiden 100.000: tek istek ~22 s bir iş parçacığını tutup süreci +200 MB büyütüyordu); .env CIKTI_SATIR_SINIRI ile değişir.
try:CIKTI_SATIR_SINIRI=max(1000,int(os.getenv('CIKTI_SATIR_SINIRI','30000')))
except ValueError:CIKTI_SATIR_SINIRI=30000

def _cikti_sinir_mesaji(adet):
    return ('Seçime %s kayıt uyuyor; tek dosyada en çok %s kayıt yazılabilir. Tarih aralığını daraltın ya da proje/durum '
            'filtresiyle birkaç parça hâlinde indirin.') % (format(adet,',').replace(',','.'),format(CIKTI_SATIR_SINIRI,',').replace(',','.'))

def _cikti_sayfasi(secim=None,hata=None,status=200):
    cats=_scoped_categories(_allowed());izinli=yetki.izinli_projeler(g.yk,projeler());kt_yok=_kt_yok(izinli)
    yalniz_onayli=bool(izinli) and _onaysiz_modu()=='gizle' and len(kt_yok)==len(izinli)
    return render_template('disa_aktar.html',izinli=izinli,kategoriler=cats,f=_cikti_secimi(secim),hata=hata,yalniz_onayli=yalniz_onayli,gizli_onaysiz=_onaysiz_modu()=='gizle' and bool(kt_yok)),status

@app.route('/disa-aktar')
@giris_gerekli
def disa_aktar_sayfasi():
    # 2.3.1: başka sayfadan (ör. ekleyen profili "Bu görünümü Excel'e aktar") gelen koşullar formu önceden doldurur.
    on_dolu=any(request.args.get(k) for k in ('ekleyen','tarih1','tarih2','proje','durum','kategori','q','tarihsiz','tarih_alani'))
    return _cikti_sayfasi(request.args if on_dolu else None)

def _yorum_ozetleri(ids):
    """Kayıt başına yorum sayısı ve son yorum (çıktı için)."""
    out={}
    if not ids:return out
    c=baglanti()
    for i in range(0,len(ids),900):
        parca=ids[i:i+900];yer=','.join('?'*len(parca))
        for r in c.execute(f'SELECT kayit_id,COUNT(*) adet,MAX(id) son FROM yorumlar WHERE kayit_id IN ({yer}) GROUP BY kayit_id',parca):
            out[r['kayit_id']]={'adet':r['adet'],'son':r['son']}
    if out:
        sonlar=[v['son'] for v in out.values()]
        for i in range(0,len(sonlar),900):
            parca=sonlar[i:i+900];yer=','.join('?'*len(parca))
            for r in c.execute(f'SELECT id,kayit_id,kullanici,zaman,metin FROM yorumlar WHERE id IN ({yer})',parca):
                out[r['kayit_id']]['metin']=f"{r['kullanici']} ({r['zaman']}): {r['metin']}"
    return out

GIRIS_TIPI_ADLARI={'resim':'Görsel','lead':'Lead ID','metin':'Metin','link':'Bağlantı','panel':'Panel (bağlantı)'}
KAYNAK_ADLARI={'telegram':'Telegram','excel':'Eski Excel','legacy_excel':'Eski Excel','panel':'Panel'}

def _cikti_degeri(r,name,yorumlar):
    """Çıktı hücresi: türetilmiş alanlar okunur metin, diğerleri olduğu gibi."""
    if name=='soru_ozet':return '\n'.join(x['label']+': '+str(x['value']) for x in _question_answers(r))
    if name=='durum_metni':return 'Silindi' if r['silindi'] else ('Onaylı' if r['kt'] else 'Bekliyor')
    if name=='tl_onay':return 'Silindi' if r['silindi'] else ('Onaylı' if r['kt'] else 'YOK')
    if name=='giris_tipi_metni':return GIRIS_TIPI_ADLARI.get(r['giris_tipi'] or '',r['giris_tipi'] or '')
    if name=='kaynak_metni':return KAYNAK_ADLARI.get(r['kaynak'] or '',r['kaynak'] or '')
    if name=='gorsel_dosya_adi':return os.path.basename(str(r['gorsel_dosya'])) if r['gorsel_dosya'] else ''
    if name=='yorum_sayisi':return (yorumlar.get(r['id']) or {}).get('adet',0)
    if name=='son_yorum':return (yorumlar.get(r['id']) or {}).get('metin','')
    if name=='panel_link':return request.url_root.rstrip('/')+'/kayitlar?durum=hepsi&ac='+str(r['id'])
    v=r[name]
    return v if v is not None else ''


CIKTI_ZAMAN_SUTUNLARI=('tarih','kt_zaman','silme_zamani')
CIKTI_DURUM_ADLARI={'hepsi':'Hepsi','onayli':'Onaylı','bekleyen':'Onay bekleyen','silinen':'Silinen'}

def _excel_zamani(v):
    """'YYYY-AA-GG SS:DD:SS' → datetime, 'YYYY-AA-GG' → date (Excel'de gerçek tarih); boş ya da okunamayan değer olduğu gibi."""
    if not isinstance(v,str) or not v.strip(): return v
    t=v.strip()
    try:
        if len(t)==10: return datetime.strptime(t,'%Y-%m-%d').date()
        z=datetime.fromisoformat(t)
        return (z.astimezone().replace(tzinfo=None) if z.tzinfo else z).replace(microsecond=0)
    except ValueError: return v

def cikti_dosya_adi(f,onaysiz=0):
    """kanit-kayitlari[-PROJE+PROJE]-<durum>[-<başlangıç>_<bitiş> | -onay-<…> | -tarihsiz][-ONAYSIZ-N].xlsx (yalnız ASCII)."""
    parca=['kanit-kayitlari']
    pr=list(f.get('proje') or [])
    if pr: parca.append('+'.join(pr[:4])+('+%d-proje' % (len(pr)-4) if len(pr)>4 else ''))
    parca.append(f.get('durum') or 'hepsi')
    if f.get('tarihsiz'): parca.append('tarihsiz')
    elif f.get('tarih1') or f.get('tarih2'):
        parca.append(('onay-' if f.get('tarih_alani')=='onay' else '')+(f.get('tarih1') or 'baslangic')+'_'+(f.get('tarih2') or 'bugun'))
    if onaysiz: parca.append('ONAYSIZ-%d' % onaysiz)
    return re.sub(r'[^A-Za-z0-9_.+-]','',('-'.join(parca)))+'.xlsx'

def _cikti_bilgi_satirlari(f,adet,olusturma):
    """Excel "Bilgi" sayfası: hangi süzgeçlerle, kim tarafından, ne zaman, kaç kayıt."""
    tarih_adi='Onay zamanı' if f.get('tarih_alani')=='onay' else 'Eklenme tarihi'
    if f.get('tarihsiz'): aralik='Yalnız tarihsiz kayıtlar'
    elif f.get('tarih1') or f.get('tarih2'):
        def tr(x): return datetime.strptime(x,'%Y-%m-%d').strftime('%d.%m.%Y') if x else '…'
        aralik='%s – %s' % (tr(f.get('tarih1')),tr(f.get('tarih2')))
    else: aralik='Tüm tarihler'
    satirlar=[('Rapor','Kanıt kayıtları (Excel çıktısı)'),
              ('Proje',', '.join(f.get('proje') or []) or 'Tüm yetkili projeler (%s)' % ', '.join(x for x in (f.get('proje_etkin') or []) if x not in (f.get('bekleyen_disi') or []))),
              ('Durum',CIKTI_DURUM_ADLARI.get(f.get('durum'),f.get('durum') or '')),
              ('Tarih ölçütü',tarih_adi),('Tarih aralığı',aralik),
              ('Kategori',('(boş)' if f.get('kategori')==personel_ozeti.BOS_DEGER else f.get('kategori')) or 'Tüm kategoriler')]
    for ad,etiket in (('q','Arama'),('ekleyen','Ekleyen'),('personel','Personel'),('ekleyen_ad','Ekleyen (rapordan)'),('tip','Tip')):
        if f.get(ad): satirlar.append((etiket,'(boş)' if f[ad]==personel_ozeti.BOS_DEGER else f[ad]))
    if f.get('bekleme'): satirlar.append(('Bekleme','En az %d gündür bekleyen' % f['bekleme']))
    if f.get('silinmemis'): satirlar.append(('Silinenler','Hariç'))
    notlar=[]
    if f.get('bekleyen_disi'): notlar.append('Onay bekleyenler yalnız onay yetkiniz olan projelerden alındı (%s hariç).' % ', '.join(f['bekleyen_disi']))
    if f.get('tarih_alani')=='onay' and (f.get('tarih1') or f.get('tarih2')): notlar.append('Onay zamanına göre süzüldüğü için yalnız onaylı kayıtlar var.')
    if f.get('gizli_onaysiz'): notlar.append('Onay yetkiniz olmayan projelerde onay bekleyen kayıtlar dosyaya girmez.')
    satirlar += [('Kayıt sayısı',adet),('Oluşturan',g.k['kullanici_adi']),('Oluşturma zamanı',olusturma.strftime('%d.%m.%Y %H:%M')),
                 ('Not',' '.join(notlar) or 'Tarih, Onay zamanı ve Silme zamanı sütunları Excel tarih biçimindedir.')]
    return satirlar

@app.route('/disa-aktar.xlsx')
@giris_gerekli
def disa_aktar_xlsx():
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    sayim=request.args.get('sayim')=='1'
    hata=_cikti_tarih_hatasi(request.args)
    if hata:
        # Ters tarih aralığı: tam sayfa 400 yerine form aynı değerlerle ve satır içi uyarıyla döner (XHR'a JSON).
        if sayim or _json_bekleniyor():return jsonify(ok=False,hata=hata,kod=400),400
        return _cikti_sayfasi(request.args,hata=hata,status=400)
    a=request.args.to_dict(flat=False); a.setdefault('durum',['hepsi'])
    # 2.4.0: "Onay bekleyen"in onay projeleriyle sınırlanması yalnız Kayıtlar'daki "Excel (bu görünüm)" bağlantısında (kapsam=kayitlar)
    # uygulanır; Çıktı sayfası eskisi gibi görüntüleyebildiğiniz tüm projelerin bekleyenlerini verir.
    kapsam_kayitlar=a.pop('kapsam',[''])[0]=='kayitlar'
    w,p,f=_filtre_sql(MultiDict(a),yetki.izinli_projeler(g.yk,projeler()),bekleyen_kapsam=kapsam_kayitlar)
    if sayim:
        # Çıktı formu indirmeden önce sayımı sorar; 0 kayıtta boş dosya yerine sayfada uyarı gösterir.
        # Yalnız sayım istendiğinden satırlar çekilmez (eşzamanlı kullanıcılarda hız).
        adet=baglanti().execute(f'SELECT COUNT(*) FROM kayitlar WHERE {w}',p).fetchone()[0]
        if adet>CIKTI_SATIR_SINIRI:return jsonify(ok=False,adet=adet,hata=_cikti_sinir_mesaji(adet),kod=400),400
        return jsonify(ok=True,adet=adet,mesaj=('Seçime uyan kayıt yok; dosya indirilmedi. Tarih aralığını veya diğer koşulları genişletin.' if not adet else '%d kayıt dosyaya yazılıyor.' % adet))
    adet=baglanti().execute(f'SELECT COUNT(*) FROM kayitlar WHERE {w}',p).fetchone()[0]
    if adet>CIKTI_SATIR_SINIRI:
        hata=_cikti_sinir_mesaji(adet)
        if _json_bekleniyor():return jsonify(ok=False,hata=hata,kod=400,adet=adet),400
        return _cikti_sayfasi(request.args,hata=hata,status=400)
    rows=baglanti().execute(f'SELECT * FROM kayitlar WHERE {w} ORDER BY proje,tarih,id',p).fetchall()
    olusturma=datetime.now()
    # write_only: hücreler belleğe değil doğrudan akışa yazılır (100 bin satıra kadar bellek dostu); sütun genişliği önce hesaplanır.
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.utils import get_column_letter
    wb=openpyxl.Workbook(write_only=True)
    # 2.4.0: ilk sayfa "Bilgi" (uygulanan süzgeçler, oluşturan, zaman, kayıt sayısı); dosya "Kayıtlar" sayfasında açılır.
    bilgi=wb.create_sheet('Bilgi'); ws=wb.create_sheet('Kayıtlar'); wb.active=1
    bilgi.column_dimensions['A'].width=22; bilgi.column_dimensions['B'].width=70  # write_only: genişlik ilk satırdan önce verilmeli
    # Girilen her alan çıktıda: eski Excel düzeni + panelde eklenen bilgiler (durum, onay, ekleyen, yorum, bağlantı).
    # 2.3.1: eski sayısal 'KT' (0/1) sütunu 'Takım lideri onayı' (Onaylı / YOK) oldu; sütun sayısı değişmedi.
    columns=[('Kayıt ID','id'),('Proje','proje'),('Kategori','kategori'),('Personel','personel'),('Üye ID','uye_id'),('Ana üye ID','ana_uye_id'),('Sessiz / Telesekreter','tip'),('Lead ID','lead_id'),('Tarih','tarih'),('Durum','durum_metni'),('Takım lideri onayı','tl_onay'),('Onaylayan','kt_kim'),('Onay zamanı','kt_zaman'),('Ekleyen','ekleyen_ad'),('Ekleyen Telegram ID','ekleyen_id'),('Giriş tipi','giris_tipi_metni'),('Kaynak','kaynak_metni'),('Görsel bağlantısı','link'),('2. görsel bağlantısı','gorsel2'),('Görsel dosyası','gorsel_dosya_adi'),('Açıklama','aciklama'),('Ek not','ek_not'),('Ek sorular','soru_ozet'),('Yorum sayısı','yorum_sayisi'),('Son yorum','son_yorum'),('Silen','silen'),('Silme zamanı','silme_zamani'),('Eski Excel satırı','excel_satir'),('Panel bağlantısı','panel_link')]
    yorumlar=_yorum_ozetleri([r['id'] for r in rows])
    def satir(r):
        vals=[]
        for _,name in columns:
            v=_cikti_degeri(r,name,yorumlar)
            if name in CIKTI_ZAMAN_SUTUNLARI: v=_excel_zamani(v)  # 2.4.0: gerçek Excel tarih/saat hücresi (okunamazsa metin kalır)
            if isinstance(v,str): v=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',v)
            if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')): v="'"+v
            vals.append(v)
        return vals
    def hucreler(r):
        out=[]
        for v in satir(r):
            if isinstance(v,(datetime,date)):
                cell=WriteOnlyCell(ws,value=v);cell.number_format='dd.mm.yyyy hh:mm' if isinstance(v,datetime) else 'dd.mm.yyyy';out.append(cell)
            else: out.append(v)
        return out
    # Sütun genişlikleri ilk satır yazılmadan önce verilmeli (write_only); içerik uzunluğu bir ön geçişle ölçülür.
    genislik=[len(a) for a,_ in columns]
    ozet={}
    for r in rows:
        for i,v in enumerate(satir(r)):
            n=16 if isinstance(v,(datetime,date)) else len(str(v if v is not None else ''))
            if n>genislik[i]:genislik[i]=n
        proje_ozet=ozet.setdefault(r['proje'],[0,0,0,0]);proje_ozet[0]+=1;proje_ozet[1 if r['kt'] else 2]+=1
        if not r['kt'] and r['silindi']:proje_ozet[3]+=1  # silinmiş onaysız: 'Takım lideri onayı YOK' toplamına ve dosya adına girmez
    for i,n in enumerate(genislik,1):ws.column_dimensions[get_column_letter(i)].width=min(45,max(12,n+2))
    ws.freeze_panes='A2'
    baslik=[]
    for a,_ in columns:
        cell=WriteOnlyCell(ws,value=a);cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='1F2937');baslik.append(cell)
    ws.append(baslik)
    for r in rows:ws.append(hucreler(r))
    ws.auto_filter.ref='A1:'+get_column_letter(len(columns))+str(len(rows)+1)
    summary=wb.create_sheet('Proje özeti');summary.append(['Proje','Kayıt','KT onaylı','KT bekleyen'])
    for project in sorted(ozet):
        summary.append([project,ozet[project][0],ozet[project][1],ozet[project][2]])
    onaysiz=sum(v[2]-v[3] for v in ozet.values())
    summary.append([]);summary.append(['Takım lideri onayı YOK (raporlamada kullanılmaz)',onaysiz])
    for satir_ in _cikti_bilgi_satirlari(f,len(rows),olusturma):
        bilgi.append([personel_ozeti.guvenli_hucre(v) for v in satir_])
    stream=io.BytesIO(); wb.save(stream); stream.seek(0)
    db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'disa_aktar',yeni=str(len(rows)),ip=ip())
    # 2.3.1 'uyar': kt yetkisi olmayan kullanıcının dosyasında onaysız satır varsa dosya adı bunu söyler.
    # 2.4.0: dosya adı süzgeçlerden kurulur (ör. kanit-kayitlari-OF-onayli-2026-11-17_2026-11-23.xlsx).
    onaysiz_ktsiz=sum(ozet[p][2]-ozet[p][3] for p in _kt_yok(sorted(ozet)))
    ad=cikti_dosya_adi(f,onaysiz_ktsiz)
    return send_file(stream,as_attachment=True,download_name=ad,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/bot/kullanici/<tg_id>')
@admin_gerekli
def bot_kullanici_detay(tg_id):
    try: data=bot_yonetim.kullanici_durum(baglanti(),tg_id)
    except ValueError: abort(404)
    return render_template('bot_kullanici.html',u=data)

def _check_folder():
    identifier=session.get('excel_check_id','')
    if not re.fullmatch('[a-f0-9]{32}',identifier): return None
    folder=Path(AYAR['BOT_KLASOR'])/'checks'/identifier
    metadata=folder/'owner.json'
    if not metadata.exists(): return None
    if json.loads(metadata.read_text()).get('user')!=g.k['kullanici_adi']: abort(403)
    return folder

def _source_path(folder):
    if not folder:return None
    info=folder/'source.json'
    if info.exists():
        name=json.loads(info.read_text()).get('file','')
        if name not in ('source.xlsx','source.csv','source.tsv','source.txt','source.ods'):abort(400)
        return folder/name
    return folder/'source.xlsx' if (folder/'source.xlsx').exists() else None

def _parse_options(form, previous=None):
    options=dict(previous or {})
    for key in ('encoding','delimiter','text_mode','header_row','sheet'):
        if key in form:options[key]=form.get(key)
    return options

@app.route('/excel-kontrol',methods=['GET','POST'])
@giris_gerekli
def excel_kontrol():
    from . import excel_check,file_sources
    allowed=_allowed()
    if not allowed:abort(403)
    folder=_check_folder();workbook=None;report=None;options={};hata=None
    if folder and (folder/'source.json').exists():options=json.loads((folder/'source.json').read_text()).get('options',{})
    if request.method=='POST':
        try:
            operation=request.form.get('islem')
            if operation=='yukle':
                uploaded=request.files.get('excel')
                suffix=Path(uploaded.filename or '').suffix.lower() if uploaded else ''
                if not uploaded or suffix not in ('.xlsx','.ods','.csv','.tsv','.txt'):raise ValueError('XLSX, ODS, CSV, TSV veya TXT dosyası seçin.')
                parent=Path(AYAR['BOT_KLASOR'])/'checks';parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                import shutil
                eski_kontrolleri_temizle()
                candidate=parent/uuid.uuid4().hex;candidate.mkdir(mode=0o700)
                path=candidate/('source'+suffix)
                try:
                    total=0
                    with path.open('wb') as target:
                        for chunk in iter(lambda:uploaded.stream.read(65536),b''):
                            total+=len(chunk)
                            if total>file_sources.MAX_UPLOAD_BYTES:raise ValueError('Dosya en çok 12 MB olabilir.')
                            target.write(chunk)
                    options={'text_mode':'ids','header_row':0} if suffix=='.txt' else {'header_row':1}
                    excel_check.validate_source(path,options);workbook=excel_check.inspect_source(path,options)
                    if workbook['sheets']:options['sheet']=workbook['sheets'][0]['name']
                    (candidate/'owner.json').write_text(json.dumps({'user':g.k['kullanici_adi'],'name':Path(uploaded.filename).name},ensure_ascii=False))
                    (candidate/'source.json').write_text(json.dumps({'file':path.name,'options':options},ensure_ascii=False))
                    folder=candidate;session['excel_check_id']=candidate.name
                except BaseException:
                    shutil.rmtree(candidate,ignore_errors=True);raise
            elif operation in ('incele','kontrol'):
                path=_source_path(folder)
                if not path or not path.exists():raise ValueError('Önce bir kontrol dosyası yükleyin.')
                options=_parse_options(request.form,options)
                workbook=excel_check.inspect_source(path,options)
                names=[sheet['name'] for sheet in workbook['sheets']]
                if names and (not options.get('sheet') or (operation=='incele' and options.get('sheet') not in names)):
                    options['sheet']=names[0]
                if operation=='kontrol':
                    options.update(columns={field:request.form.get('kolon_'+field,'') for field in excel_check.FIELDS},
                                   match_fields=request.form.getlist('alan'),project=request.form.get('project',''),kt=request.form.get('kt','hepsi'))
                    if workbook['format']=='id_list':
                        options.update(id_field=request.form.get('id_field') or (options['match_fields'][0] if options['match_fields'] else 'personel'))
                        options.update(match_fields=[options['id_field']],columns={})
                    report=excel_check.check_source(path,baglanti(),allowed,options,onayli_zorunlu=_kt_yok(allowed) if _onaysiz_modu()=='gizle' else None)
                    (folder/'result.json').write_text(json.dumps({'report':report,'options':options},ensure_ascii=False))
                    db.denetim_yaz(baglanti(),g.k['kullanici_adi'],'dosya_kontrol',yeni={'format':workbook['format'],'satir':report['total'],'alanlar':options['match_fields']},ip=ip(),hedef_turu='kontrol')
                else:
                    (folder/'result.json').unlink(missing_ok=True)
                (folder/'source.json').write_text(json.dumps({'file':path.name,'options':options},ensure_ascii=False))
            else:raise ValueError('Bilinmeyen işlem.')
        except (ValueError,OSError) as error:hata=str(error)
    path=_source_path(folder)
    if workbook is None and path and path.exists():
        try:workbook=excel_check.inspect_source(path,options)
        except (ValueError,OSError) as error:hata=hata or str(error)
    if request.method=='GET' and folder and (folder/'result.json').exists():
        saved=json.loads((folder/'result.json').read_text());report=saved['report'];options=saved['options']
    report_page=1;report_pages=1;report_status=request.args.get('rapor_durum','')
    if report:
        rows=report['rows']
        if report_status:rows=[row for row in rows if row['status']==report_status]
        try:report_page=max(1,min(1000000,int(request.args.get('r_s','1'))))
        except ValueError:abort(400)
        report_pages=max(1,(len(rows)+99)//100)
        report_page=min(report_page,report_pages)
        report=dict(report,rows=[dict(row,ids=row['ids'][:20],display_remaining=max(0,len(row['ids'])-20)) for row in rows[(report_page-1)*100:report_page*100]])
    if workbook and path:workbook['extension']=path.suffix
    kontrol_zamani=excel_check.yerel_zaman_metni((report or {}).get('metadata',{}).get('checked_at','')) if report else ''
    return render_template('excel_check.html',workbook=workbook,report=report,options=options,hata=hata,izinli=allowed,upload_ready=bool(path),report_page=report_page,report_pages=report_pages,report_status=report_status,kontrol_zamani=kontrol_zamani)

def eski_kontrolleri_temizle(yas_sn=86400):
    """data/checks altındaki 24 saatten eski kontrol klasörlerini siler (yüklemede ve uygulama başlangıcında; hata yutar)."""
    silinen=0
    try:
        import shutil
        parent=Path(AYAR['BOT_KLASOR'])/'checks'
        if not parent.is_dir():return 0
        for old in parent.iterdir():
            try:
                if old.is_dir() and old.stat().st_mtime<time.time()-yas_sn:shutil.rmtree(old,ignore_errors=True);silinen+=1
            except OSError:continue
    except Exception:
        pass
    return silinen

def _safe_excel(value):
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',str('' if value is None else value))
    return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text

@app.route('/excel-kontrol/sonuc.xlsx')
@giris_gerekli
def excel_kontrol_indir():
    folder=_check_folder()
    if not folder or not (folder/'result.json').exists():abort(404)
    saved=json.loads((folder/'result.json').read_text());report=saved['report'];options=saved['options']
    allowed=_allowed()
    if not allowed:abort(403)
    snapshot=set(report.get('metadata',{}).get('scope',{}).get('allowed_projects',[]))
    if snapshot and not snapshot.issubset(set(allowed)):abort(403)
    ids=list({int(kid) for row in report['rows'] for kid in row['ids']})
    for offset in range(0,len(ids),500):
        batch=ids[offset:offset+500]
        for record in baglanti().execute('SELECT proje FROM kayitlar WHERE id IN ('+','.join('?' for _ in batch)+')',batch):
            if record['proje'] not in allowed:abort(403)
    from openpyxl import Workbook
    from openpyxl.styles import Font,PatternFill
    wb=Workbook();ws=wb.active;ws.title='Eksik kanıtlar' if request.args.get('eksik')=='1' else 'Kontrol sonucu'
    fields=options.get('match_fields',[]);ws.append(['Kaynak satırı','Durum',*fields,'Kanıt kayıt IDleri','Açıklama'])
    for row in report['rows']:
        if request.args.get('eksik')=='1' and row['status']!='yok':continue
        ws.append([_safe_excel(row.get('source',row['row'])),row['status'],*[_safe_excel(row['values'].get(field,'')) for field in fields],', '.join(str(x) for x in row['ids']),_safe_excel(row.get('reason',''))])
    for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='1F2937')
    ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
    for column in ws.columns:ws.column_dimensions[column[0].column_letter].width=min(50,max(15,max(len(str(cell.value or '')) for cell in column)+2))
    metadata=wb.create_sheet('Kontrol bilgisi');metadata.append(['Alan','Değer'])
    meta=report.get('metadata',{})
    from . import excel_check
    for key,value in [('Kontrol zamanı',excel_check.yerel_zaman_metni(meta.get('checked_at',''))),('Kapsam',meta.get('scope',{})),('Seçenekler',meta.get('options',options)),('Limitler',meta.get('limits',{})),('Kaynak adı',json.loads((folder/'owner.json').read_text()).get('name',''))]:
        metadata.append([key,_safe_excel(json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else value)])
    metadata.column_dimensions['A'].width=25;metadata.column_dimensions['B'].width=90
    stream=io.BytesIO();wb.save(stream);stream.seek(0)
    return send_file(stream,as_attachment=True,download_name='eksik-kanitlar.xlsx' if request.args.get('eksik')=='1' else 'kanit-kontrol.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/telegram/kullanici/<tg_id>/kanitlar',methods=['GET','POST'])
@giris_gerekli
def telegram_kayitlari(tg_id):
    from . import user_evidence
    if not re.fullmatch('[0-9]{1,20}',tg_id):abort(404)
    allowed=yetki.izinli_projeler(g.yk,projeler())
    if not allowed:abort(403)
    c=baglanti()
    if request.method=='POST':
        if not g.yk['admin']:abort(403)
        project=request.form.get('project',request.form.get('ana_proje','')).strip()
        if project and project not in allowed:abort(400)
        with db.transaction(c):
            c.execute('INSERT INTO tg_kullanicilar(id,ana_proje) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET ana_proje=excluded.ana_proje',(tg_id,project or None))
            db.denetim_yaz(c,g.k['kullanici_adi'],'beklenen_proje',yeni=tg_id+':'+project,ip=ip());db.degisti(c)
        return redirect(url_for('telegram_kayitlari',tg_id=tg_id))
    onayli_zorunlu=_kt_yok(allowed) if _onaysiz_modu()=='gizle' else []
    try:data=user_evidence.get_profile(c,tg_id,allowed,request.args.to_dict(),superadmin=g.yk['admin'],onayli_zorunlu=onayli_zorunlu)
    except PermissionError:abort(403)
    except ValueError as e:return render_template('hata.html',kod=400,baslik='Geçersiz istek',mesaj=str(e)),400
    return render_template('telegram_kayitlari.html',profile=data,allowed=allowed,kisayollar=_profil_kisayollari(tg_id,data),
                           excel_url=_profil_excel_url(tg_id,data),ozet_etiketi=_profil_aralik_etiketi(data['filters']),
                           uyar_kt_yok=set(_kt_yok(allowed)) if _onaysiz_modu()=='uyar' else set())

def _profil_kisayollari(tg_id,data):
    """2.3.1 ekleyen profili: tarih aralığı kısayolları (Son 7 gün, Son 30 gün, Bu ay, Tümü); diğer süzgeçler korunur."""
    bugun=datetime.now().date();f=data['filters']
    secenekler=[('Son 7 gün',(bugun-timedelta(days=6)).isoformat(),bugun.isoformat()),('Son 30 gün',(bugun-timedelta(days=29)).isoformat(),bugun.isoformat()),
                ('Bu ay',bugun.replace(day=1).isoformat(),bugun.isoformat()),('Tümü','','')]
    sabit={k:v for k,v in data['link_args'].items() if k not in ('tarih1','tarih2')}
    return [dict(etiket=ad,url=url_for('telegram_kayitlari',tg_id=tg_id,**sabit,**({'tarih1':t1,'tarih2':t2} if t1 else {})),
                 aktif=(f['tarih1']==t1 and f['tarih2']==t2)) for ad,t1,t2 in secenekler]

def _profil_excel_url(tg_id,data):
    """'Bu görünümü Excel'e aktar': mevcut Çıktı formu ekleyen + tarih + proje + durum ile önceden doldurulmuş açılır."""
    f=data['filters']
    return url_for('disa_aktar_sayfasi',ekleyen=tg_id,tarih1=f['tarih1'] or None,tarih2=f['tarih2'] or None,proje=f['project'] or None,durum=f['kt'])

def _profil_aralik_etiketi(f):
    def tr(v):return '.'.join(reversed(v.split('-'))) if v else ''
    if f['tarih1'] and f['tarih2']:return tr(f['tarih1'])+' – '+tr(f['tarih2'])
    if f['tarih1']:return tr(f['tarih1'])+' ve sonrası'
    if f['tarih2']:return tr(f['tarih2'])+' ve öncesi'
    return 'Tüm zamanlar'

@app.route('/saglik')
def saglik():
    # Sürüm başlığı yalnız sunucunun kendisinden (127.0.0.1, vekil başlığı olmadan) gelen isteklere; dışarıya sürüm açıklanmaz.
    yerel=request.remote_addr in ('127.0.0.1','::1') and not request.headers.get('X-Forwarded-For')
    return 'OK',200,({'X-Kanit-Paneli':SURUM} if yerel else {})

@app.route('/manus-routes.json')
@admin_gerekli
def route_manifest():
    return jsonify(routes=[{'path':p,'title':t} for p,t in [('/','Ana sayfa'),('/giris','Giriş'),('/sifre','Parola'),('/kayitlar','Kayıtlar'),('/arsiv','Arşiv'),('/excel-kontrol','Excel kontrol'),('/bot','Bot'),('/yonetim/kullanicilar','Kullanıcılar'),('/denetim','Denetim'),('/disa-aktar','Çıktı'),('/telegram/kullanici/:tg_id/kanitlar','Ekleyen kanıt profili'),('/bot/kullanici/:tg_id','Telegram kullanıcı durumu')]])

def _json_bekleniyor():
    """fetch() ile çağrılan uç noktalar hata sayfası yerine JSON hata gövdesi alır."""
    if request.is_json or request.headers.get('X-CSRF') or request.headers.get('X-Requested-With')=='XMLHttpRequest':return True
    return request.accept_mimetypes.best_match(['application/json','text/html'])=='application/json'

HATA_BASLIKLARI={400:'Geçersiz istek',403:'Yetkiniz yok',404:'Sayfa bulunamadı',405:'Bu yöntem desteklenmiyor',409:'Kayıt değişti',413:'Dosya çok büyük',429:'Çok fazla deneme',500:'Beklenmeyen hata'}

@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(405)
@app.errorhandler(409)
@app.errorhandler(413)
@app.errorhandler(429)
def handle_error(error):
    messages={400:'Gönderilen bilgi geçersiz veya eksik. Sayfayı yenileyip tekrar deneyin.',403:'Bu sayfa veya işlem için hesabınızın yetkisi yok. Gerekirse süperadminden proje yetkisi isteyin.',404:'Aradığınız sayfa ya da kayıt bulunamadı; bağlantı eski olabilir.',405:'Bu adres bu şekilde çağrılamaz.',409:'Kayıt bu arada başka bir kullanıcı tarafından değiştirildi. Sayfayı yenileyip tekrar deneyin.',413:'Dosya boyutu sınırı (12 MB) aşıldı.',429:'Çok fazla istek gönderildi. Birkaç dakika bekleyip tekrar deneyin.'}
    ozel=error.description if isinstance(getattr(error,'description',None),str) and error.code in (400,409) and error.description and not error.description.startswith('The ') else None
    if _json_bekleniyor():
        return jsonify(ok=False,hata=ozel or messages[error.code]),error.code
    return render_template('hata.html',kod=error.code,baslik=HATA_BASLIKLARI.get(error.code,'Hata'),mesaj=ozel or messages[error.code]),error.code

@app.errorhandler(500)
def handle_server_error(error):
    ref=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3).upper()
    original=getattr(error,'original_exception',None) or error
    app.logger.error('Beklenmeyen hata [kayit no %s] %s %s',ref,request.method,request.path,exc_info=(type(original),original,original.__traceback__))
    try:
        c=db.baglan(AYAR['DB'])
        try:
            db.denetim_yaz(c,(g.get('k') or {}).get('kullanici_adi') or 'anonim','sunucu_hata',yeni={'kayit_no':ref,'yol':request.path,'tur':type(original).__name__},ip=ip(),hedef_turu='sistem',hedef_id=ref,sonuc='hata')
        finally:c.close()
    except Exception:
        pass
    mesaj='Beklenmeyen hata, kayıt no '+ref+'. Ayrıntı sunucu günlüğüne yazıldı; sorun sürerse bu numarayı yöneticinize iletin.'
    if _json_bekleniyor():
        return jsonify(ok=False,hata=mesaj,kayit_no=ref),500
    try:
        return render_template('hata.html',kod=500,baslik=HATA_BASLIKLARI[500],mesaj=mesaj,kayit_no=ref),500
    except Exception:
        # Şablon da kurulamıyorsa (ör. URL kurucu yok) ham ama Türkçe yanıt; Flask'ın İngilizce varsayılan sayfası görünmez.
        return mesaj,500,{'Content-Type':'text/plain; charset=utf-8'}


def _start_web_converter():
    if os.environ.get('GYAZO_WORKER','1')=='0':return
    import threading
    from . import donusum_isleri
    def loop():
        son_temizlik=time.time()
        while True:
            conn=None;processed=False
            try:
                conn=db.baglan(AYAR['DB'])
                processed=bool(donusum_isleri.worker_step(conn,'web-'+str(os.getpid())))
                if time.time()-son_temizlik>=GECICI_SIFRE_TEMIZLIK_SN:
                    son_temizlik=time.time();gecici_sifreleri_temizle(conn)
            except Exception as error:
                # Ham HTTP hata metni anahtar içeriyor olabilir; yalnız sınıf adı.
                print('Dönüşüm işçisi kontrolü: '+type(error).__name__,flush=True)
            finally:
                if conn:conn.close()
            time.sleep(0.5 if processed else 2)
    threading.Thread(target=loop,name='kanit-web-gyazo',daemon=True).start()

def _start_hatirlatma_isi():
    """2.3.1: onay bekleyen kayıtlar için hatırlatma bildirimlerini HATIRLATMA_KONTROL_DK dakikada bir üretir (0 = kapalı).
    Üretim idempotent olduğu için sık çalışması yeni satır eklemez; ilk çalışma açılıştan ~20 sn sonra.
    2.3.3: varsayılan 10 dk; 2 saat bildirimi eşikten en geç ~10 dk sonra, gün sonu özeti İstanbul 18:00–18:10 arasında gider."""
    import sqlite3,threading
    from . import hatirlatma
    # 2.4.0: aralık her turda yeniden okunur (panelden değiştirilebilir; app/ayarlar.py). Açılışta 0 ise iş hiç başlamaz.
    # Her turdan sonra Sistem durumu kırmızıysa süperadminlere günde bir 'Sistem' bildirimi yazılır (durum.uyari_uret).
    try:
        _c=db.baglan(AYAR['DB'])
        try:dk=hatirlatma.ayarlar(AYAR,_c)['kontrol_dk']
        finally:_c.close()
    except Exception:
        dk=hatirlatma.ayarlar(AYAR)['kontrol_dk']
    if dk<=0:return None
    def loop():
        nonlocal dk
        time.sleep(20)
        while True:
            conn=None
            try:
                conn=db.baglan(AYAR['DB'])
                dk=hatirlatma.ayarlar(AYAR,conn)['kontrol_dk']
                if dk>0:hatirlatma.uret(conn,AYAR)
                try:
                    from . import durum as _durum
                    _durum.uyari_uret(conn,_durum.satirlar(conn,AYAR,SURUM))
                except Exception as error:
                    print('Sistem durumu uyarısı: '+type(error).__name__,flush=True)
            except sqlite3.Error as error:
                # SQLite metni gizli veri içermez ve teşhis için gerekir ('database is locked' / 'disk I/O error').
                print('Hatırlatma işi: %s: %s' % (type(error).__name__,str(error)[:160]),flush=True)
            except Exception as error:
                print('Hatırlatma işi: '+type(error).__name__,flush=True)
            finally:
                if conn:conn.close()
            try:time.sleep(dk*60 if dk>0 else 60)  # 0 = panelden durduruldu: dakikada bir yeniden bakılır
            except (OverflowError,ValueError):time.sleep(600)
    t=threading.Thread(target=loop,name='kanit-web-hatirlatma',daemon=True);t.start();return t

def sunucu_ayarlari():
    """waitress serve() parametreleri (test edilebilir): gövde üst sınırı ve yalnız tek güvenilen vekil."""
    ayar=dict(threads=8,max_request_body_size=EN_BUYUK_ISTEK+1024*1024)  # 12 MB dosya + çok parçalı form payı; Türkçe 413'ü Flask verir
    if str(AYAR.get('TRUST_PROXY','0')).lower() in ('1','true'):
        # Nginx arkasındaki sunucu: X-Forwarded-* başlıklarına yalnız GUVENILEN_PROXY (varsayılan 127.0.0.1) adresinden gelen
        # bağlantıda güvenilir; aynı makinedeki başka bir süreç ('*' iken mümkündü) IP sahteleyemez.
        ayar.update(trusted_proxy=(os.getenv('GUVENILEN_PROXY','').strip() or '127.0.0.1'),trusted_proxy_count=1,
                    trusted_proxy_headers={'x-forwarded-for','x-forwarded-proto','x-forwarded-host'})
    else:
        # 2.4.0: TRUST_PROXY=0 iken waitress X-Forwarded-For'u silmesin (adres yine bağlantıdan alınır, başlık uygulanmaz);
        # böylece erişim sınırı 'döngü + X-Forwarded-For' durumunu görüp muafiyet vermez ve "TRUST_PROXY=1 gerekli" uyarır.
        ayar.update(clear_untrusted_proxy_headers=False)
    return ayar

def calistir():
    from waitress import serve
    _start_web_converter();_start_hatirlatma_isi()
    eski_kontrolleri_temizle();gecici_sifreleri_temizle()
    # 2.3.6: panel ekleme kategorisi (SMS) ilk istek beklenmeden açılışta hazır olsun; hata panelin açılmasını engellemez.
    try:
        from . import katalog as _kat
        _k=db.baglan(AYAR['DB'])
        try: _kat.panel_kategori(_k)
        finally: _k.close()
    except Exception as hata: print('Panel ekleme kategorisi hazırlanamadı: '+type(hata).__name__,flush=True)
    print(f'Kanıt Paneli {SURUM} — {AYAR["DINLE"]}:{AYAR["PORT"]}',flush=True)
    serve(app,host=AYAR['DINLE'],port=AYAR['PORT'],**sunucu_ayarlari())


def _snapshot_questions(raw):
    try:questions=json.loads(raw) if isinstance(raw,str) else (raw or [])
    except (ValueError,TypeError):return []
    if isinstance(questions,dict):questions=questions.get('questions',[])
    if not isinstance(questions,list):return []
    return [question for question in questions if isinstance(question,dict) and isinstance(question.get('key'),str) and isinstance(question.get('label'),str)]

def _question_answers(row):
    try:
        questions=_snapshot_questions(row['soru_anlik_json']);answers=json.loads(row['cevaplar_json'] or '{}')
        if not isinstance(answers,dict):return []
        return [dict(key=q['key'],label=q['label'],preset=q.get('preset'),value=answers.get(q['key'],'')) for q in questions]
    except (ValueError,KeyError,TypeError):return []

@app.route('/kategoriler.json')
@giris_gerekli
def kategori_secenekleri():
    selected=_selected_projects(request.args,_allowed())
    return jsonify(kategoriler=_scoped_categories(selected))

@app.route('/yonetim/katalog',methods=['GET','POST'])
@admin_gerekli
def katalog_yonetim():
    from . import katalog
    c=baglanti();message=None;status=200
    if request.method=='POST':
        try:
            revision=request.form.get('revision')
            revision=int(revision) if revision else None
            active=request.form.get('active')=='1'
            if request.form.get('islem')=='proje_kaydet':
                if katalog.get_project(c,request.form.get('code','')) and revision is None:raise katalog.RevisionConflict('Bu kod var; mevcut proje formundan düzenleyin.')
                katalog.save_project(c,request.form.get('code',''),request.form.get('label',''),request.form.get('color',''),active=active,actor=g.k['kullanici_adi'],expected_revision=revision)
            elif request.form.get('islem')=='kategori_kaydet':
                if katalog.get_category(c,request.form.get('code','')) and revision is None:raise katalog.RevisionConflict('Bu kod var; mevcut kategori formundan düzenleyin.')
                questions=json.loads(request.form.get('questions_json','[]'))
                katalog.save_category(c,request.form.get('code',''),request.form.get('label',''),mode=request.form.get('mode','custom'),projects=request.form.getlist('projects'),questions=questions,active=active,actor=g.k['kullanici_adi'],expected_revision=revision)
            else:raise ValueError('Bilinmeyen işlem.')
            flash('Kaydedildi. Yeni seçimlerde anında geçerli.');return redirect(url_for('katalog_yonetim'))
        except katalog.RevisionConflict as error:message=str(error);status=409
        except (ValueError,TypeError) as error:message=str(error);status=400
    from . import kategori_temizlik
    return render_template('katalog.html',proje_bilgileri=katalog.list_projects(c,False),kategoriler=katalog.list_categories(c,active_only=False),mesaj=message,
                           kayit_sayilari=kategori_temizlik.katalog_sayilari(c)),status

# 2.3.5 — Kategori temizliği (yalnız süperadmin): kayıtlardaki kategori yazımlarını katalog adlarında birleştirir.
# Önizleme yazmaz; Uygula önizleme damgasını transaction içinde yeniden doğrular. Ayrıntı: app/kategori_temizlik.py
ISLEM_ADLARI['kategori_birlestir']='Kayıt kategorilerini birleştirdi'
DENETIM_ADLARI['kategori_birlestir']='Kategori birleştirme'

def _temizlik_secimleri():
    anahtarlar=request.form.getlist('g');hedefler_=request.form.getlist('h')
    if len(anahtarlar)!=len(hedefler_) or len(anahtarlar)>2000:raise ValueError('Form eksik gönderildi; sayfayı yenileyip yeniden deneyin.')
    secim={}
    for a,h in zip(anahtarlar,hedefler_):
        h=str(h or '').strip()
        if h:secim[str(a)]=h
    return secim

@app.route('/yonetim/katalog/kategori-temizligi',methods=['GET','POST'])
@admin_gerekli
def kategori_temizligi():
    from . import kategori_temizlik as kt
    c=baglanti();mesaj=None;durum=200;onizleme=None;sonuc=None;secim=None
    if request.method=='POST':
        try:
            secim=_temizlik_secimleri();op=request.form.get('islem')
            if op not in ('onizle','uygula'):raise ValueError('Bilinmeyen işlem.')
            if not secim:raise ValueError('Hiçbir grup için "Şuna dönüştür" seçilmedi; değiştirilecek bir şey yok.')
            if op=='onizle':onizleme=kt.plan(c,secim)
            else:
                damga=request.form.get('damga','')
                if not damga:raise ValueError('Önce Önizle düğmesine basın.')
                sonuc=kt.uygula(c,secim,g.k['kullanici_adi'],ip=ip(),damga=damga)
                secim=None
        except kt.Cakisma as error:
            mesaj='Hata: '+str(error);durum=409
            try:onizleme=kt.plan(c,secim or {})
            except ValueError:onizleme=None
        except ValueError as error:mesaj='Hata: '+str(error);durum=400
    gruplar=kt.gruplar(c)
    if secim is not None:
        for grp in gruplar:grp['secili']=secim.get(grp['anahtar'],'')
    else:
        for grp in gruplar:grp['secili']=grp['varsayilan']
    return render_template('kategori_temizligi.html',gruplar=gruplar,hedefler=kt.hedefler(c),onizleme=onizleme,sonuc=sonuc,mesaj=mesaj,
                           BOS_HEDEF=kt.BOS_HEDEF,BOS_AD=kt.BOS_AD,toplam_kayit=sum(x['hepsi'] for x in gruplar)),durum

# 2.4.0 (B2): Sistem durumu, Yedekler ve Çalışma ayarları (/yonetim/...); ayrıntı app/isletim.py
from . import isletim as _isletim
import sys as _sys
_isletim.kaydet(app,_sys.modules.get(__name__) or _sys.modules.get('app.panel'))  # __main__ olarak çalışırken de panel modülü isletim'e tanıtılır

if __name__=='__main__':
    calistir()
