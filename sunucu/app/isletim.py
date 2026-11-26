"""2.4.0 (B2 — işletim): Sistem durumu kartı/JSON, Yedekler sayfası, Çalışma ayarları sayfası.

Adresler: /yonetim/sistem-durumu.json, /yonetim/yedekler, /yonetim/ayarlar. panel.py dosyanın sonunda bu blueprint'i kaydeder.
Yetki: sayfaları süperadmin (admin) görür; Çalışma ayarlarını yalnız 'sahip' değiştirir (süperadmin salt okunur görür).
"""
import sys
from functools import wraps

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from . import ayarlar as calisma_ayarlari
from . import durum, yedek

bp = Blueprint('isletim', __name__)


def _panel():
    return sys.modules['app.panel']


def _sahip_mi():
    """Sahip (süperadminin üstü) mi? B1'in sahip_mi()/g.yk['sahip'] alanı varsa o; yoksa süperadmin sahip sayılır.
    TODO B1: sahip_gerekli — B1 'sahip' rolünü birleştirince bu geri dönüş kaldırılabilir."""
    panel = _panel()
    islev = getattr(panel, 'sahip_mi', None)
    if callable(islev):
        try:
            return bool(islev())
        except TypeError:
            pass
    yk = g.get('yk') or {}
    if 'sahip' in yk:
        return bool(yk.get('sahip'))
    return bool(yk.get('admin'))


def _admin_gerekli(f):
    @wraps(f)
    def sarmal(*a, **kw):
        return _panel().admin_gerekli(f)(*a, **kw)
    return sarmal


def sahip_gerekli(f):
    """B1'in panel.sahip_gerekli'si varsa o kullanılır; yoksa admin_gerekli + _sahip_mi() denetimi.
    TODO B1: sahip_gerekli (koordinatör: B1 birleşince bu geri dönüşü panel.sahip_gerekli'ye bağlayın)."""
    @wraps(f)
    def sarmal(*a, **kw):
        panel = _panel()
        b1 = getattr(panel, 'sahip_gerekli', None)
        if callable(b1):
            return b1(f)(*a, **kw)

        def ic(*a2, **kw2):
            if not _sahip_mi():
                abort(403)
            return f(*a2, **kw2)
        return panel.admin_gerekli(ic)(*a, **kw)
    return sarmal


def _ayar():
    return _panel().AYAR


def _baglanti():
    return _panel().baglanti()


def durum_verisi():
    rows = durum.satirlar(_baglanti(), _ayar(), _panel().SURUM)
    return {'satirlar': rows, 'ozet': durum.ozet(rows)}


@bp.app_context_processor
def _sablon_yardimcilari():
    def sistem_durumu():
        try:
            return durum_verisi()
        except Exception as hata:  # kart ana sayfayı asla düşürmesin
            return {'satirlar': [], 'ozet': {'genel': 'sari', 'kirmizi': 0, 'sari': 1, 'metin': 'Durum okunamadı: ' + type(hata).__name__}}

    def yedek_listesi(en_cok=20):
        try:
            return yedek.liste(_ayar())[:en_cok]
        except Exception:
            return []
    return dict(sistem_durumu=sistem_durumu, yedek_listesi=yedek_listesi, sahip_mi=_sahip_mi,
                yedek_kurulum_komutu=yedek.kurulum_komutu(), yedek_betik=yedek.BETIK)


# ---------------------------------------------------------------- sistem durumu

@bp.route('/yonetim/sistem-durumu.json')
@_admin_gerekli
def sistem_durumu_json():
    return jsonify(durum_verisi())


# ---------------------------------------------------------------- yedekler

def _guvenli_sonraki(hedef):
    hedef = str(hedef or '')
    return hedef if hedef.startswith('/') and not hedef.startswith('//') and '\\' not in hedef and len(hedef) < 500 else url_for('isletim.yedekler')


@bp.route('/yonetim/yedekler', methods=['GET', 'POST'])
@_admin_gerekli
def yedekler():
    panel = _panel()
    if request.method == 'POST':
        if request.form.get('islem') != 'yedek_al':
            abort(400)
        try:
            mesaj = panel.bot_yonetim.geri_yuklenebilir_yedek_al(_ayar(), _baglanti(), g.k['kullanici_adi'], panel.ip())
            flash(mesaj)
        except (OSError, ValueError) as hata:
            flash('Hata: ' + str(hata), 'hata')
        return redirect(_guvenli_sonraki(request.form.get('sonraki')))
    son = yedek.son_yedek(_ayar())
    return render_template('yedekler.html', yedekler=yedek.liste(_ayar()), son=son, kok=str(yedek.kok(_ayar())),
                           panel_dizini=str(yedek.panel_dizini(_ayar())))


# ---------------------------------------------------------------- çalışma ayarları

@bp.route('/yonetim/ayarlar', methods=['GET', 'POST'])
@_admin_gerekli
def ayarlar():
    panel = _panel()
    c = _baglanti()
    hatalar, girilen = {}, {}
    duzenleyebilir = _sahip_mi()
    if request.method == 'POST':
        if not duzenleyebilir:
            abort(403)
        ad = request.form.get('ad', '')
        islem = request.form.get('islem', 'kaydet')
        try:
            if islem == 'sil':
                if calisma_ayarlari.sil(c, ad, g.k['kullanici_adi'], panel.ip()):
                    flash('%s varsayılana döndü (.env ya da varsayılan değer geçerli).' % calisma_ayarlari.SOZLUK[ad].etiket)
                else:
                    flash('%s zaten panelden değiştirilmemişti.' % calisma_ayarlari.SOZLUK[ad].etiket)
            elif islem == 'kaydet':
                deger = calisma_ayarlari.yaz(c, ad, request.form.get('deger', ''), g.k['kullanici_adi'], panel.ip())
                a = calisma_ayarlari.SOZLUK[ad]
                metin = calisma_ayarlari.gosterim(dict(tur=a.tur, gecerli=deger, secenekler=a.secenekler, sifir=a.sifir))
                flash('Kaydedildi: %s = %s. Yeniden başlatma gerekmez; bir sonraki istekte / iş turunda geçerli.'
                      % (a.etiket, metin if metin != '' else '(boş)'))
            else:
                abort(400)
            return redirect(url_for('isletim.ayarlar') + '#ayar-' + ad)
        except ValueError as hata:
            hatalar[ad] = str(hata)
            girilen[ad] = request.form.get('deger', '')[:200]
    satirlar = calisma_ayarlari.tablo(c)
    for s in satirlar:
        s['gosterim'] = calisma_ayarlari.gosterim(s)
    gruplar = [(grup, [s for s in satirlar if s['grup'] == grup]) for grup in calisma_ayarlari.GRUPLAR]
    return render_template('ayarlar.html', gruplar=gruplar, hatalar=hatalar, girilen=girilen, duzenleyebilir=duzenleyebilir), (400 if hatalar else 200)


def kaydet(app):
    """panel.py'den çağrılır: blueprint + İşlem Geçmişi adları + bildirim türü/hedefi."""
    panel = _panel()
    app.register_blueprint(bp)
    for sozluk, adlar in ((panel.ISLEM_ADLARI, {'ayar_degistir': 'Çalışma ayarını değiştirdi', 'ayar_varsayilan': 'Çalışma ayarını varsayılana döndürdü'}),
                          (panel.DENETIM_ADLARI, {'ayar_degistir': 'Ayar değişikliği', 'ayar_varsayilan': 'Ayar varsayılana döndü'})):
        for k, v in adlar.items():
            sozluk.setdefault(k, v)
    panel.BILDIRIM_TUR_ADLARI.setdefault('sistem', 'Sistem')
