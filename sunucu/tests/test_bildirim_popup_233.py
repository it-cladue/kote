# -*- coding: utf-8 -*-
"""2.3.3: bildirimler pop-up kart + ses + hatırlatma penceresi.
1) Şablon / statik dosya denetimleri (kapsayıcılar, Ses anahtarı, tost kullanılmaması, CSS sınıfları ve koyu tema).
2) Uçtan uca tarayıcı testi: gerçek waitress sunucusu + geçici veritabanı + Playwright (Node). Node veya Playwright
   yoksa temiz biçimde atlanır (üretim sunucusu test çalıştırmaz)."""
import json
import os
import shutil
import subprocess
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app import db, hatirlatma, panel
from tests.test_web import web, login, seed  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
TEMPLATES = ROOT / 'app' / 'templates'
TARAYICI_BETIK = Path(__file__).with_name('bildirim_popup_tarayici.js')


def _js():
    return (STATIC / 'panel.js').read_text(encoding='utf-8')


def _blok():
    js = _js()
    bas = js.index('/* ===== 2.3.3: bildirim pop-up kartları')
    son = js.index('/* ===== 2.3.3: bildirim pop-up bloğu (son) ===== */')
    return js[bas:son]


# ---------------------------------------------------------------- 1. şablon ve statik dosyalar

def test_base_sablonu_kapsayicilar_ve_ses_anahtari(web):
    c, a = web
    login(c)
    html = c.get('/').get_data(as_text=True)
    for parca in ('id="bildirim-popuplar"', 'aria-live="polite"', 'id="hatirlatma-popup"', 'role="dialog" aria-modal="true" aria-labelledby="hp-baslik"',
                  'Bekleyen kontroller hatırlatması', 'data-hp-sonra', 'Daha sonra', 'data-hp-okundu', 'data-hp-kapat', 'id="bildirim-ses"',
                  'role="switch"', '> Ses</label>', 'id="bildirim-izin-btn"', 'Masaüstü bildirimlerini aç', 'okundu=0&amp;tur=hatirlatma'):
        assert parca in html, parca
    # Pop-up kapsayıcısı açılır listeden sonra gelir (CSS kardeş seçicisi buna dayanır); liste artık ayrıca canlı bölge değil.
    assert html.index('id="bildirim-kutu"') < html.index('id="bildirim-popuplar"')
    assert '<ul id="bildirim-liste">' in html
    # Girişsiz sayfada pop-up iskeleti yok.
    from app import panel as p
    anon = p.app.test_client().get('/giris').get_data(as_text=True)
    assert 'bildirim-popuplar' not in anon and 'hatirlatma-popup' not in anon


def test_panel_js_sozdizimi_ve_tost_kullanmaz():
    if shutil.which('node'):
        r = subprocess.run(['node', '--check', str(STATIC / 'panel.js')], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
    js = _js()
    bildirim = js.split('  function bildirimler(){', 1)[1].split('  function menu(){', 1)[0]
    # Yeni bildirimler artık alttaki tostla gösterilmez (tost yalnız işlem geri bildirimi için kalır).
    assert "toast((n.tur==='hatirlatma'?'Hatırlatma: ':'Yeni bildirim: ')" not in js and 'toast(ozetMetin)' not in js
    assert 'popup.yoklama(items,yeniler,initial)' in bildirim
    blok = _blok()
    assert 'toast(' not in blok.replace("toast(ids.length+' hatırlatma okundu sayıldı.')", '').replace('toast(err.message,true)', '')
    for parca in ('AudioContext', 'webkitAudioContext', "state!=='running'", '.resume()', "'pointerdown','keydown','touchstart'",
                  "localStorage.getItem(SES_ANAHTAR)!=='0'", 'EN_COK=4', 'SURE=15000', 'kanit-hatirlatma-sonra:', 'bugunTarih()',
                  'acikPencereVar()', 'yaziyor(document.activeElement)', 'bn.onclick', 'window.focus()', 'MutationObserver',
                  "' yeni bildirim'", "' hatırlatma'", 'Bildirimleri aç', 'Tümünü gör', '/bildirimler?okundu=0', 'data-bp-ac', 'data-bp-okundu'):
        assert parca in blok, parca
    # Kazanç ≤ 0,15; normal iki ton, hatırlatma üç ton.
    assert 'exponentialRampToValueAtTime(.12' in blok
    assert '[[880,0,.14],[1318.5,.12,.18]]' in blok and '[[659.25,0,.2],[783.99,.15,.2],[1046.5,.3,.28]]' in blok
    # Arka planda da yoklama (30 sn), test kancası.
    assert 'window.KP_YOKLAMA_MS' in bildirim and 'document.hidden?ARALIK*3:ARALIK' in bildirim
    assert 'if(document.hidden&&!force){schedule();return;}' not in js
    # Önceki sürümlerin bildirim davranışı korunur (2.3.1 testleri de bunlara bakar).
    for parca in ('var LIMIT=15', 'data-notify-hedef', "hatirlatma:'Hatırlatma'", "'Bekleyenleri aç'"):
        assert parca in js, parca


def test_stil_css_kart_pencere_koyu_tema_ve_telefon():
    css = (STATIC / 'stil.css').read_text(encoding='utf-8')
    for parca in ('.bildirim-popuplar {', '.bp-kart {', '.bp-kart.hatirlatma {', '.bp-kart.ozet {', '.bp-kapat {', '.hp-perde {', '.hp-pencere {',
                  '.hp-liste li {', '.ses-anahtar {', '@keyframes bp-gir', '[data-theme="dark"] .bp-kart {', '[data-theme="dark"] .hp-perde {',
                  '[data-theme="dark"] .hp-pencere {', 'body:has(#modal:not(.gizli)) .bildirim-popuplar'):
        assert parca in css, parca
    son = css.split('2.3.3: bildirim pop-up kartları', 1)[1]
    assert '@media (prefers-reduced-motion: reduce) { .bp-kart, .hp-pencere { animation: none; }' in son
    tel = son.split('@media (max-width: 900px) {', 1)[1]
    assert '.bildirim-popuplar { left: 8px; right: 8px; width: auto;' in tel
    # Katman sırası: açılır liste 55 < kartlar 56 < hatırlatma penceresi 60 < görsel büyütme 90; kayıt penceresi açıkken kartlar 45.
    assert 'z-index: 56' in son.split('.bildirim-popuplar {', 1)[1].split('}', 1)[0]
    assert 'z-index: 60' in son.split('.hp-perde {', 1)[1].split('}', 1)[0]


# ---------------------------------------------------------------- 2. uçtan uca tarayıcı testi

def _playwright_var():
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _yeni_kayit(con, sira, bildir):
    kid = con.execute('INSERT INTO kayitlar(anahtar,proje,personel,uye_id,kategori,kaynak,giris_tipi,ekleyen_ad,aciklama,tarih,guncelleme) '
                      'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                      ('e2e:%d' % sira, 'OF', '00%03d' % sira, '00099', 'HGST', 'telegram', 'yazili', 'tgtester', 'Uçtan uca', db.simdi(), db.simdi())).lastrowid
    if bildir:
        db.bildirim_uret(con, kid)
    db.degisti(con)
    return kid


class _Yardimci:
    """Tarayıcı betiğinin çağırdığı küçük yerel HTTP yardımcısı: geçici veritabanına bildirim ekler / okunmamışları sayar."""

    def __init__(self, ayar):
        self.ayar = ayar; self.sira = 100; self.kilit = threading.Lock()
        yardimci = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                uzunluk = int(self.headers.get('Content-Length') or 0)
                veri = json.loads(self.rfile.read(uzunluk) or b'{}')
                try:
                    with yardimci.kilit:
                        cevap = yardimci.islem(self.path.strip('/'), veri)
                    govde, durum = json.dumps(cevap).encode(), 200
                except Exception as e:  # betik hatayı görsün
                    govde, durum = json.dumps({'hata': repr(e)}).encode(), 500
                self.send_response(durum); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(govde)))
                self.end_headers(); self.wfile.write(govde)

        self.sunucu = ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.sunucu.daemon_threads = True
        threading.Thread(target=self.sunucu.serve_forever, daemon=True).start()
        self.url = 'http://127.0.0.1:%d' % self.sunucu.server_address[1]

    def islem(self, ad, veri):
        con = db.baglan(self.ayar['DB'])
        try:
            if ad == 'kanit':
                sonuc = []
                with db.transaction(con):
                    for _ in range(int(veri.get('adet', 1))):
                        self.sira += 1; kid = _yeni_kayit(con, self.sira, True)
                        bid = con.execute('SELECT id FROM bildirimler WHERE kullanici_adi=? AND kayit_id=?', ('testadmin', kid)).fetchone()[0]
                        sonuc.append({'kayit_id': kid, 'bildirim_id': bid})
                return sonuc[0] if len(sonuc) == 1 else {'liste': sonuc}
            if ad == 'hatirlatma':
                bugun = date.today().isoformat(); idler = []; kayitlar = []
                with db.transaction(con):
                    for _ in range(int(veri.get('adet', 1))):
                        self.sira += 1; kid = _yeni_kayit(con, self.sira, False); kayitlar.append(kid)
                        idler.append(con.execute('INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                                                 ('testadmin', kid, 'OF', 'hatirlatma:%d:%s' % (kid, bugun), 'hatirlatma', hatirlatma.KIM,
                                                  hatirlatma.kayit_metni(4), db.simdi())).lastrowid)
                    if veri.get('ozet'):
                        idler.append(con.execute('INSERT INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                                                 ('testadmin', kayitlar[0], 'OF', 'hatirlatma-ozet:OF:%s' % bugun, 'hatirlatma', hatirlatma.KIM,
                                                  hatirlatma.ozet_metni('OF', 6, 2, 3), db.simdi())).lastrowid)
                return {'idler': idler, 'kayit_idler': kayitlar}
            if ad == 'okunmamis':
                if veri.get('tur'):
                    n = con.execute("SELECT COUNT(*) FROM mesaj_bildirimleri WHERE kullanici_adi='testadmin' AND okundu=0 AND tur=?", (veri['tur'],)).fetchone()[0]
                else:
                    tablo, sayi = veri['key'].split(':', 1)
                    tablo = 'bildirimler' if tablo == 'kayit' else 'mesaj_bildirimleri'
                    n = con.execute('SELECT COUNT(*) FROM ' + tablo + ' WHERE id=? AND okundu=0', (int(sayi),)).fetchone()[0]
                return {'okunmamis': n}
            raise ValueError(ad)
        finally:
            con.close()

    def kapat(self):
        self.sunucu.shutdown(); self.sunucu.server_close()


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_kart_ses_ve_hatirlatma_penceresi(web, tmp_path):
    from waitress.server import create_server
    c, a = web
    seed(a, key='tg:e2e:ilk', picture=False)  # ilk yüklemede zaten okunmamış bir bildirim var: kart/ses çıkmamalı
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    yardimci = _Yardimci(a)
    try:
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port, YARDIMCI_URL=yardimci.url,
                     EKRAN_KLASOR=os.environ.get('KP_EKRAN_KLASOR', ''))
        r = subprocess.run(['node', str(TARAYICI_BETIK)], capture_output=True, text=True, timeout=150, env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        yardimci.kapat()
        try:
            sunucu.close()
        except Exception:
            pass
