"""2.4.0 (B2 — işletim): yedek adlandırma/liste/işaret/geri yükleme, panel yedeği, sistem durumu, Sistem bildirimi,
çalışma ayarları (öncelik, doğrulama, denetim, yeniden başlatmasız okuma), rol kapıları ve CLI.

Bash testleri geçici dizinde, sahte systemctl ile çalışır (root gerekir; değilse atlanır). Saatler/işaretler enjekte edilir.
"""
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from collections import namedtuple
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import ayarlar as ca
from app import db, durum, hatirlatma, yedek
from test_web import web, login, csrf  # noqa: F401
from test_bildirim_231 import account, insert, rows

SUNUCU = Path(__file__).resolve().parents[1]
DEPLOY = SUNUCU / 'deploy'
ROOT = os.geteuid() == 0
SIMDI = datetime(2026, 11, 26, 15, 0, 0)


def ts(dt):
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def cikis(c, ad='testadmin'):
    c.post('/cikis', data={'csrf': csrf(c)})
    return login(c, ad)


def sayi(gz_yolu, tmp):
    duz = Path(tmp) / ('ac-%d.db' % time.time_ns())
    with gzip.open(gz_yolu, 'rb') as f:
        duz.write_bytes(f.read())
    c = sqlite3.connect('file:%s?mode=ro&immutable=1' % duz, uri=True)
    try:
        return (c.execute('PRAGMA integrity_check').fetchone()[0], c.execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0],
                c.execute('PRAGMA journal_mode').fetchone()[0])
    finally:
        c.close()


# =============================================================== O1 — panel (Python) yedeği
def test_panel_yedegi_geri_yuklenebilir_bicim_manifest_isaret_saklama(web, tmp_path, monkeypatch):
    c, a = web
    for _ in range(3):
        insert(a)
    bilgi = yedek.yedek_al(a, 'testadmin', simdi=SIMDI)
    yol = Path(bilgi['yol'])
    assert yol.parent == Path(a['BOT_KLASOR']) / 'yedekler' and yol.name == 'panel-20261126-150000.db.gz'
    assert oct(yol.stat().st_mode & 0o777) == '0o600' and bilgi['kayit'] == 3 and bilgi['integrity'] == 'ok'
    assert sayi(yol, tmp_path) == ('ok', 3, 'delete'), 'kanit-yedek.sh ile aynı biçim: tek dosya, bütünlük ok'
    man = (yol.parent / 'MANIFEST.tsv').read_text().splitlines()
    assert man == ['panel-20261126-150000.db.gz\t2026-11-26 15:00:00\t%d\tok\t3\tpanel' % yol.stat().st_size]
    isaret = json.loads((yol.parent / 'son_yedek.json').read_text())
    assert isaret['ad'] == yol.name and isaret['kayit'] == 3 and yedek.son_yedek(a)['ad'] == yol.name
    # yalnız panel yedeği varken 'Son yedek' kırmızı kalır (gece yedeği yok); gece işareti / yedekler.json gelince yeşil
    an = SIMDI + timedelta(minutes=1)
    assert durum.yedek_satiri(a, an)['renk'] == 'kirmizi' and yol.name in durum.yedek_satiri(a, an)['aciklama']
    veri = Path(a['BOT_KLASOR'])
    (veri / 'yedekler.json').write_text(json.dumps({'yedekler': [{'ad': 'panel-20261126.db.gz', 'yol': '/x/panel-20261126.db.gz', 'boyut': 9,
                                                                   'zaman': '2026-11-26 03:17:05', 'kayit': 3, 'integrity': 'ok', 'tur': 'gece'}]}))
    assert durum.yedek_satiri(a, an)['renk'] == 'yesil' and yedek.son_gece_yedegi(a)['ad'] == 'panel-20261126.db.gz'
    (veri / 'son_gece_yedegi.json').write_text(json.dumps({'zaman': '2026-11-24 03:17:00', 'ad': 'panel-20261124.db.gz', 'integrity': 'ok', 'tur': 'gece'}))
    assert yedek.son_gece_yedegi(a)['ad'] == 'panel-20261126.db.gz', 'en yeni gece kaydı'
    (veri / 'yedekler.json').unlink()
    assert durum.yedek_satiri(a, an)['renk'] == 'kirmizi', '2 günden eski gece yedeği: panel yedeği yeşile çevirmez'
    (veri / 'son_gece_yedegi.json').unlink()
    with pytest.raises(yedek.YedekHatasi, match='Bu saniyede'):
        yedek.yedek_al(a, simdi=SIMDI)
    for i in range(1, 12):
        yedek.yedek_al(a, simdi=SIMDI + timedelta(minutes=i))
    kalan = sorted(p.name for p in yol.parent.glob('panel-*.db.gz'))
    assert len(kalan) == yedek.PANEL_SAKLA and kalan[-1] == 'panel-20261126-151100.db.gz' and yol.name not in kalan
    assert len((yol.parent / 'MANIFEST.tsv').read_text().splitlines()) == yedek.PANEL_SAKLA
    assert not list(yol.parent.glob('.panel-yedek-*')), 'geçici dosya kalmamalı'
    liste = yedek.liste(a)
    assert liste[0]['ad'] == 'panel-20261126-151100.db.gz' and liste[0]['tur_adi'] == 'Panelden' and liste[0]['kayit'] == 3
    assert liste[0]['komut']['uygula'] == 'sudo /usr/local/sbin/kanit-yedek.sh --geri-yukle ' + liste[0]['yol']
    # yazılamayan klasör: Türkçe hata + sunucu komutu
    monkeypatch.setattr(yedek.os, 'access', lambda *x, **k: False)
    with pytest.raises(yedek.YedekHatasi, match='sudo install -d -m 700 -o kanit -g kanit'):
        yedek.yedek_al(a)


def test_bot_sayfasi_yedek_dugmesi_yedekler_sayfasi_ve_temizlik_kancasi(web):
    c, a = web
    login(c)
    insert(a)
    html = c.get('/bot').get_data(as_text=True)
    assert 'Yedek al (geri yüklenebilir)' in html and 'SQLite yedeği al' not in html and 'id="yedekler"' in html
    r = c.post('/bot', data={'csrf': csrf(c), 'islem': 'yedek'})
    html = r.get_data(as_text=True)
    assert 'Yedek alındı:' in html and 'kanit-yedek.sh --geri-yukle' in html and '1 kayıt' in html
    assert len(list((Path(a['BOT_KLASOR']) / 'yedekler').glob('panel-*.db.gz'))) == 1
    assert rows(a, "SELECT islem FROM denetim WHERE islem='bot_yedek'"), 'denetim satırı'
    sayfa = c.get('/yonetim/yedekler').get_data(as_text=True)
    assert 'Geri yükleme — adım adım' in sayfa and '--dry-run' in sayfa and 'Panelden' in sayfa
    # "Önce yedek al": temizlik sayfasında düğme; yedekten sonra aynı sayfaya dönülür, mesaj üstte
    temizlik = c.get('/yonetim/katalog/kategori-temizligi').get_data(as_text=True)
    assert 'Önce yedek al' in temizlik and 'name="sonraki" value="/yonetim/katalog/kategori-temizligi"' in temizlik
    time.sleep(1.05)
    r = c.post('/yonetim/yedekler', data={'csrf': csrf(c), 'islem': 'yedek_al', 'sonraki': '/yonetim/katalog/kategori-temizligi'})
    assert r.status_code == 302 and r.headers['Location'].endswith('/yonetim/katalog/kategori-temizligi')
    assert 'Yedek alındı:' in c.get(r.headers['Location']).get_data(as_text=True)
    r = c.post('/yonetim/yedekler', data={'csrf': csrf(c), 'islem': 'yedek_al', 'sonraki': '//kotu.example/x'})
    assert r.headers['Location'].endswith('/yonetim/yedekler'), 'dış adrese yönlendirme yok'
    # betiğin yazdığı özet (gece yedekleri) de listede görünür
    (Path(a['BOT_KLASOR']) / 'yedekler.json').write_text(json.dumps({'yedekler': [
        {'ad': 'panel-20261125.db.gz', 'yol': '/var/backups/kanit-paneli/gunluk/panel-20261125.db.gz', 'boyut': 2048,
         'zaman': '2026-11-25 03:20:01', 'kayit': 77, 'integrity': 'ok', 'tur': 'gece'}]}))
    sayfa = c.get('/yonetim/yedekler').get_data(as_text=True)
    assert 'panel-20261125.db.gz' in sayfa and 'Gece (otomatik)' in sayfa and '>77<' in sayfa


# =============================================================== O1 — kanit-yedek.sh (bash)
def _betik_ortami(kok):
    app = kok / 'app'
    data = app / 'data'
    data.mkdir(parents=True)
    (app / '.env').write_text('A=1\n')
    c = sqlite3.connect(data / 'panel.db')
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE kayitlar(id INTEGER PRIMARY KEY, x TEXT)')
    c.executemany('INSERT INTO kayitlar(x) VALUES (?)', [('a',)] * 42)
    c.commit()
    c.close()
    log = kok / 'systemctl.log'
    fake = kok / 'systemctl'
    fake.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "systemctl $*" >> "{log}"
        exit 0
    '''))
    fake.chmod(0o755)
    env = dict(os.environ, KANIT_TEST='1', KANIT_APP=str(app), KANIT_PY=sys.executable, KANIT_YEDEK_KOK=str(kok / 'yedek'),
               KANIT_SYSTEMCTL=str(fake), KANIT_ONCEKI_KOK=str(kok / 'onceki'), KANIT_USER='kanit-yok', KANIT_HAFTALIK_GUN='9')
    return app, data, env


def _calistir(env, *arg):
    return subprocess.run(['bash', str(DEPLOY / 'kanit-yedek.sh'), *arg], env=env, capture_output=True, text=True, timeout=180)


@pytest.mark.skipif(not ROOT, reason='root gerekir')
def test_betik_adlandirma_ezmeme_liste_json_isaret_ve_geri_yukleme(tmp_path):
    kok = Path(tempfile.mkdtemp(prefix='kanit-b2.', dir='/tmp'))
    try:
        app, data, env = _betik_ortami(kok)
        gunluk = kok / 'yedek' / 'gunluk'
        gun = time.strftime('%Y%m%d')
        r = _calistir(env, '--zamanlayici')
        assert r.returncode == 0 and 'YEDEK_TAMAM' in r.stdout and 'YEDEK_DOGRULANDI: panel-%s.db.gz (integrity=ok kayit=42)' % gun in r.stdout, r.stdout + r.stderr
        gece = gunluk / ('panel-%s.db.gz' % gun)
        assert gece.exists() and (gunluk / ('env-%s' % gun)).exists()
        gece_icerik = gece.read_bytes()
        assert json.loads((data / 'son_gece_yedegi.json').read_text())['ad'] == gece.name
        # elle çalıştırma: saatli ad, gece dosyası değişmez
        c = sqlite3.connect(data / 'panel.db'); c.executemany('INSERT INTO kayitlar(x) VALUES (?)', [('b',)] * 8); c.commit(); c.close()
        r = _calistir(env)
        assert r.returncode == 0, r.stdout + r.stderr
        el = [p for p in gunluk.glob('panel-%s-*.db.gz' % gun)]
        assert len(el) == 1 and gece.read_bytes() == gece_icerik, 'elle yedek gece dosyasının üzerine yazmamalı'
        assert len(list(gunluk.glob('env-%s-*' % gun))) == 1
        isaret = json.loads((data / 'son_yedek.json').read_text())
        assert isaret['ad'] == el[0].name and isaret['kayit'] == 50 and isaret['tur'] == 'el' and isaret['integrity'] == 'ok'
        assert oct((data / 'son_yedek.json').stat().st_mode & 0o777) == '0o600'
        gece_isr = json.loads((data / 'son_gece_yedegi.json').read_text())
        assert gece_isr['ad'] == gece.name and gece_isr['tur'] == 'gece', 'elle yedek gece işaretini değiştirmemeli'
        man = (gunluk / 'MANIFEST.tsv').read_text()
        assert '\t42\tgece' in man and '\t50\tel' in man
        # panel (Python) yedeği de aynı listede
        ayar = {'BOT_KLASOR': str(data), 'DB': str(data / 'panel.db'), 'YEDEK_KOK': str(kok / 'yedek')}
        p = yedek.yedek_al(ayar, simdi=datetime.now() - timedelta(minutes=5))
        r = _calistir(env, '--liste')
        assert r.returncode == 0 and gece.name in r.stdout and el[0].name in r.stdout and p['ad'] in r.stdout and 'Toplam 3 yedek' in r.stdout, r.stdout + r.stderr
        r = _calistir(env, '--liste', '--json')
        veri = json.loads(r.stdout)
        turler = {o['ad']: (o['tur'], o['kayit']) for o in veri['yedekler']}
        assert turler == {gece.name: ('gece', 42), el[0].name: ('el', 50), p['ad']: ('panel', 50)}, turler
        ozet = json.loads((data / 'yedekler.json').read_text())
        assert {o['ad'] for o in ozet['yedekler']} == {gece.name, el[0].name}, 'betiğin son çalışmasındaki özet'
        # --dogrula en yeni dosyayı (panel yedeği dahil, değişme zamanına göre) açar
        r = _calistir(env, '--dogrula')
        assert r.returncode == 0 and 'YEDEK_DOGRULANDI' in r.stdout
        # geri yükleme: tam yol (gece biçimi) ve yalnız ad (panel biçimi)
        r = _calistir(env, '--geri-yukle', str(gece))
        assert r.returncode == 0 and 'GERI_YUKLEME_TAMAM' in r.stdout, r.stdout + r.stderr
        assert sqlite3.connect(data / 'panel.db').execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0] == 42
        r = _calistir(env, '--geri-yukle', p['ad'], '--dry-run')
        assert r.returncode == 0 and 'DRY-RUN_TAMAM' in r.stdout and str(data / 'yedekler' / p['ad']) in r.stdout, r.stdout + r.stderr
        r = _calistir(env, '--geri-yukle', p['ad'])
        assert r.returncode == 0 and 'GERI_YUKLEME_TAMAM' in r.stdout, r.stdout + r.stderr
        assert sqlite3.connect(data / 'panel.db').execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0] == 50
        r = _calistir(env, '--geri-yukle', 'panel-19990101.db.gz')
        assert r.returncode == 1 and 'bulunamadı' in r.stderr
        # saklama: elle yedekler ayrı sayılır; 12 elle yedek → 10 kalır, gece dosyası durur
        for i in range(12):
            (gunluk / ('panel-20200101-0000%02d.db.gz' % i)).write_bytes(b'x')
        r = _calistir(env)
        assert r.returncode == 0, r.stderr
        assert gece.exists() and len(list(gunluk.glob('panel-????????-??????.db.gz'))) == 10
        r = _calistir(env, '--yardim')
        assert '--zamanlayici' in r.stdout and '--liste' in r.stdout
    finally:
        shutil.rmtree(kok, ignore_errors=True)


def test_birim_zamanlayici_bayragi_ve_kurulum_ilk_yedek():
    assert 'ExecStart=/usr/local/sbin/kanit-yedek.sh --zamanlayici' in (DEPLOY / 'kanit-yedek.service').read_text()
    assert '"$HEDEF_SH" --zamanlayici' in (DEPLOY / 'setup-backup.sh').read_text()
    for ad in ('kanit-yedek.sh', 'setup-backup.sh'):
        assert subprocess.run(['bash', '-n', str(DEPLOY / ad)]).returncode == 0
    gerekli = (DEPLOY / 'update-support.py').read_text()
    for ad in ('ayarlar.py', 'durum.py', 'yedek.py', 'isletim.py'):
        assert '"%s"' % ad in gerekli


# =============================================================== O2 — sistem durumu
def _satir(rows_, kod):
    return next(r for r in rows_ if r['kod'] == kod)


def test_durum_esikleri_bot_yedek_gece_hatirlatma_disk_kuyruk(web):
    c, a = web
    con = db.baglan(a['DB'])
    try:
        def tum(**kw):
            return durum.satirlar(con, dict(a, HATIRLATMA_KONTROL_DK=10), '2.4.0', simdi=SIMDI, **kw)
        assert _satir(tum(), 'bot')['renk'] == 'kirmizi'
        for yas, renk in ((60, 'yesil'), (300, 'sari'), (900, 'kirmizi')):
            con.execute("INSERT OR REPLACE INTO tg_durum(bot_id,offset,heartbeat) VALUES('b',0,?)", (ts(SIMDI - timedelta(seconds=yas)),))
            assert _satir(tum(), 'bot')['renk'] == renk, yas
        assert 'kanit-bot' in _satir(tum(), 'bot')['komut']
        db.ayar_yaz(con, 'bot_durdur', '1')
        assert _satir(tum(), 'bot')['renk'] == 'sari'
        db.ayar_yaz(con, 'bot_durdur', '0')
        # son yedek
        assert _satir(tum(), 'yedek')['renk'] == 'kirmizi'
        for saat, renk in ((10, 'yesil'), (30, 'sari'), (60, 'kirmizi')):
            isr = {'zaman': ts(SIMDI - timedelta(hours=saat)), 'ad': 'panel-x.db.gz', 'kayit': 5, 'integrity': 'ok', 'boyut': 10}
            assert _satir(tum(isaretler={'yedek': isr}), 'yedek')['renk'] == renk, saat
        # panel/elle yedek rengi değiştirmez (yalnız ek bilgi); gece yedeği yoksa kırmızı
        panel_isr = {'zaman': ts(SIMDI - timedelta(hours=1)), 'ad': 'panel-20261126-140000.db.gz', 'kayit': 5, 'integrity': 'ok', 'boyut': 10, 'tur': 'panel'}
        y = _satir(tum(isaretler={'yedek_diger': panel_isr}), 'yedek')
        assert y['renk'] == 'kirmizi' and 'panelden alınan' in y['aciklama'] and 'setup-backup.sh' in y['aciklama'], y
        eski_gece = {'zaman': ts(SIMDI - timedelta(hours=60)), 'ad': 'panel-20261124.db.gz', 'kayit': 5, 'integrity': 'ok', 'boyut': 10, 'tur': 'gece'}
        y = _satir(tum(isaretler={'yedek': eski_gece, 'yedek_diger': panel_isr}), 'yedek')
        assert y['renk'] == 'kirmizi' and 'panel-20261124.db.gz' in y['deger'] and 'panel-20261126-140000' in y['aciklama'], y
        bozuk = {'zaman': ts(SIMDI), 'ad': 'p', 'integrity': 'bozuk'}
        assert _satir(tum(isaretler={'yedek': bozuk}), 'yedek')['renk'] == 'kirmizi'
        # gece görsel işi
        assert _satir(tum(), 'gece_gorsel')['renk'] == 'gri'
        for isr, renk in (({'zaman': ts(SIMDI - timedelta(hours=10)), 'bitis_nedeni': 'tamam'}, 'yesil'),
                          ({'zaman': ts(SIMDI - timedelta(hours=40)), 'bitis_nedeni': 'tamam'}, 'sari'),
                          ({'zaman': ts(SIMDI - timedelta(hours=2)), 'bitis_nedeni': 'tamam', 'ariza': ['Gyazo']}, 'sari'),
                          ({'zaman': ts(SIMDI - timedelta(hours=2)), 'bitis_nedeni': 'erisim', 'durduruldu': 'yok'}, 'kirmizi'),
                          ({'zaman': ts(SIMDI - timedelta(days=8)), 'bitis_nedeni': 'tamam'}, 'kirmizi')):
            assert _satir(tum(isaretler={'gece_gorsel': isr}), 'gece_gorsel')['renk'] == renk, isr
        # hatırlatma işi (aralık 10 dk → yeşil < 20 dk, sarı < 60 dk)
        for dk, renk in ((5, 'yesil'), (30, 'sari'), (120, 'kirmizi')):
            assert _satir(tum(isaretler={'hatirlatma': {'zaman': ts(SIMDI - timedelta(minutes=dk))}}), 'hatirlatma')['renk'] == renk, dk
        kapali = durum.satirlar(con, dict(a, HATIRLATMA_KONTROL_DK=0), '2.4.0', simdi=SIMDI)
        assert _satir(kapali, 'hatirlatma')['renk'] == 'gri'
        # disk
        K = namedtuple('K', 'total used free')
        for dolu, renk in ((50, 'yesil'), (85, 'sari'), (95, 'kirmizi')):
            assert _satir(tum(disk=K(100, dolu, 100 - dolu)), 'disk')['renk'] == renk
        # kuyruk
        assert _satir(tum(), 'kuyruk')['renk'] == 'yesil'
        con.execute("INSERT INTO tg_gelen(bot_id,update_id,veri,durum) VALUES('b',1,'{}','olu')")
        assert _satir(tum(), 'kuyruk')['renk'] == 'sari'
        con.executemany("INSERT INTO tg_gelen(bot_id,update_id,veri,durum) VALUES('b',?,'{}','bekliyor')", [(i,) for i in range(2, 205)])
        assert _satir(tum(), 'kuyruk')['renk'] == 'kirmizi'
        assert [r['kod'] for r in tum()] == ['web', 'bot', 'yedek', 'gece_gorsel', 'hatirlatma', 'disk', 'veritabani', 'kuyruk']
        assert durum.ozet(tum())['genel'] == 'kirmizi'
    finally:
        con.close()


def test_is_isaretleri_gece_gorsel_ve_hatirlatma(web):
    c, a = web
    from app import gorsel
    con = db.baglan(a['DB'])
    try:
        with pytest.raises(ValueError):
            gorsel.gyazo_toplu_indir(con, SimpleNamespace(gyazo_acik=False, dis_acik=False), a)
        isr = json.loads(db.ayar_al(con, gorsel.GECE_IS_ISARETI))
        assert isr['bitis_nedeni'] == 'hata' and 'GYAZO_PROXY' in isr['durduruldu'] and isr['zaman']
        assert _satir(durum.satirlar(con, a, ''), 'gece_gorsel')['renk'] == 'kirmizi'
        r = gorsel.gyazo_toplu_indir(con, SimpleNamespace(gyazo_acik=True, dis_acik=True), a, rapor_yolu=str(Path(a['BOT_KLASOR']) / 'r.csv'))
        isr = json.loads(db.ayar_al(con, gorsel.GECE_IS_ISARETI))
        assert r['bitis_nedeni'] == 'tamam' and isr['bitis_nedeni'] == 'tamam' and isr['indirilen'] == 0
        assert _satir(durum.satirlar(con, a, ''), 'gece_gorsel')['renk'] == 'yesil'
        assert db.ayar_al(con, hatirlatma.IS_ISARETI) is None
        hatirlatma.uret(con, dict(a, BEKLEYEN_OZET_SAAT=0, GUN_SONU_SAAT=''))
        assert json.loads(db.ayar_al(con, hatirlatma.IS_ISARETI))['zaman']
        assert _satir(durum.satirlar(con, dict(a, HATIRLATMA_KONTROL_DK=10), ''), 'hatirlatma')['renk'] == 'yesil'
    finally:
        con.close()


def test_sistem_bildirimi_gunde_bir_satir_basina_ve_zilde(web):
    c, a = web
    account(a, 'ikinciadmin', 'admin'); account(a, 'lider', 'OF:oku,kt')
    con = db.baglan(a['DB'])
    try:
        kirmizi = durum.satirlar(con, a, '', simdi=SIMDI)
        assert sum(r['renk'] == 'kirmizi' for r in kirmizi) >= 2  # bot sinyalsiz + yedek yok
        assert durum.uyari_uret(con, kirmizi, SIMDI) == 0, 'hiç kayıt yokken bildirim yazılmaz (çapa yok)'
        insert(a)
        n_kirmizi = sum(r['renk'] == 'kirmizi' for r in kirmizi)
        assert durum.uyari_uret(con, kirmizi, SIMDI) == 2 * n_kirmizi
        assert durum.uyari_uret(con, kirmizi, SIMDI + timedelta(hours=3)) == 0, 'aynı gün yeniden yazılmaz'
        assert durum.uyari_uret(con, kirmizi, SIMDI + timedelta(days=1)) == 2 * n_kirmizi, 'ertesi gün yeniden'
        assert not rows(a, "SELECT 1 FROM mesaj_bildirimleri WHERE tur='sistem' AND kullanici_adi='lider'"), 'yalnız süperadminler'
        yesil = [dict(r, renk='yesil') for r in kirmizi]
        assert durum.uyari_uret(con, yesil, SIMDI + timedelta(days=2)) == 0
    finally:
        con.close()
    login(c)
    j = c.get('/bildirim.json').get_json()
    sistem = [b for b in j['bildirimler'] if b['tur'] == 'sistem']
    assert sistem and sistem[0]['etiket'] == 'Sistem' and sistem[0]['url'].endswith('/#sistem-durumu') and sistem[0]['ozet']
    sayfa = c.get('/bildirimler?tur=sistem').get_data(as_text=True)
    assert "value=\"sistem\" selected" in sayfa and 'Sistem:' in sayfa
    assert all(b['proje'] == '' for b in sistem), 'sistem bildirimi bir projeye ait değildir (rozet yok)'
    assert 'Sistem durumunu aç' in sayfa and 'Bekleyenleri aç' not in sayfa
    assert not rows(a, "SELECT 1 FROM mesaj_bildirimleri WHERE tur='sistem' AND proje<>''")


def test_ana_sayfa_karti_json_ve_rol_kapilari(web):
    c, a = web
    login(c)
    html = c.get('/').get_data(as_text=True)
    assert 'id="sistem-durumu"' in html and 'data-sd-kod="yedek"' in html and 'Komutu kopyala' in html
    j = c.get('/yonetim/sistem-durumu.json').get_json()
    assert [r['kod'] for r in j['satirlar']][:3] == ['web', 'bot', 'yedek'] and j['ozet']['genel'] in ('sari', 'kirmizi')
    account(a, 'okur', 'OF:oku')
    cikis(c, 'okur')
    assert 'id="sistem-durumu"' not in c.get('/').get_data(as_text=True)
    for url in ('/yonetim/sistem-durumu.json', '/yonetim/yedekler', '/yonetim/ayarlar'):
        assert c.get(url).status_code == 403, url
    assert c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'HATIRLATMA_GUN', 'deger': '5'}).status_code == 403
    assert c.post('/yonetim/yedekler', data={'csrf': csrf(c), 'islem': 'yedek_al'}).status_code == 403


# =============================================================== O3 — çalışma ayarları
def test_ayar_onceligi_db_env_varsayilan_ve_dogrulama(web, monkeypatch):
    c, a = web
    con = db.baglan(a['DB'])
    try:
        monkeypatch.delenv('API_DAKIKA_SINIRI', raising=False)
        assert ca.deger('API_DAKIKA_SINIRI', conn=con) == '120'
        monkeypatch.setenv('API_DAKIKA_SINIRI', '300')
        assert ca.deger('API_DAKIKA_SINIRI', conn=con) == '300'
        assert ca.yaz(con, 'API_DAKIKA_SINIRI', ' 45 ', 'testadmin', '127.0.0.1') == '45'
        assert ca.deger('API_DAKIKA_SINIRI', conn=con) == '45'
        satir = next(s for s in ca.tablo(con) if s['ad'] == 'API_DAKIKA_SINIRI')
        assert satir['kaynak'] == 'DB' and satir['ortam'] == '300'
        assert ca.sil(con, 'API_DAKIKA_SINIRI', 'testadmin') and ca.deger('API_DAKIKA_SINIRI', conn=con) == '300'
        assert not ca.sil(con, 'API_DAKIKA_SINIRI', 'testadmin')
        monkeypatch.setenv('API_DAKIKA_SINIRI', 'abc')
        satir = next(s for s in ca.tablo(con) if s['ad'] == 'API_DAKIKA_SINIRI')
        assert satir['kaynak'] == 'varsayılan' and 'geçersiz' in satir['ortam_uyari']
        hatali = {'HATIRLATMA_GUN': ['0', '366', 'üç'], 'BEKLEYEN_OZET_PENCERE': ['20:00-08:00', '25:00-26:00', 'sabah'],
                  'GUN_SONU_SAAT': ['24:00', '18'], 'ONAYSIZ_GORUNUM': ['sakla'], 'API_ACIK': ['belki'],
                  'GUN_SONU_ALICILAR': ['Ali Veli', 'yok_boyle'], 'PANEL_EKLEME_KATEGORI': ['  ', 'x' * 121]}
        for ad, degerler in hatali.items():
            for d in degerler:
                with pytest.raises(ValueError):
                    ca.yaz(con, ad, d, 'testadmin')
        for sir in ('TELEGRAM_TOKEN', 'GYAZO_TOKEN', 'SESSION_SECRET', 'PANEL_VERI', 'ADMIN_PASSWORD'):
            with pytest.raises(ValueError, match='değiştirilemez'):
                ca.yaz(con, sir, 'x', 'testadmin')
        assert ca.yaz(con, 'BEKLEYEN_OZET_PENCERE', '8.30 - 19', 'testadmin') == '08:30-19:00'
        assert ca.yaz(con, 'GUN_SONU_SAAT', '17.5'.replace('.5', '.05'), 'testadmin') == '17:05'
        assert ca.yaz(con, 'GUN_SONU_SAAT', '0', 'testadmin') == '0'
        assert ca.yaz(con, 'API_ACIK', 'Kapalı', 'testadmin') == '0'
        assert ca.yaz(con, 'GUN_SONU_ALICILAR', 'testadmin, testadmin', 'testadmin') == 'testadmin'
        d = rows(a, "SELECT * FROM denetim WHERE islem IN ('ayar_degistir','ayar_varsayilan') ORDER BY id")
        ilk = d[0]
        assert json.loads(ilk['eski']) == {'ad': 'API_DAKIKA_SINIRI', 'deger': None, 'kaynak': '.env'}
        assert json.loads(ilk['yeni']) == {'ad': 'API_DAKIKA_SINIRI', 'deger': '45'} and ilk['hedef_turu'] == 'ayar' and ilk['ip'] == '127.0.0.1'
        assert d[1]['islem'] == 'ayar_varsayilan'
    finally:
        con.close()


def test_okuyucular_yeniden_baslatmasiz_gorur(web, monkeypatch):
    c, a = web
    con = db.baglan(a['DB'])
    try:
        assert hatirlatma.ayarlar(dict(a, BEKLEYEN_OZET_SAAT=2), con)['ozet_saat'] == 2
        ca.yaz(con, 'BEKLEYEN_OZET_SAAT', '4', 'testadmin')
        ca.yaz(con, 'BEKLEYEN_OZET_PENCERE', '', 'testadmin')
        ca.yaz(con, 'BEKLEYEN_OZET_YONETICI', '0', 'testadmin')
        ca.yaz(con, 'HATIRLATMA_KONTROL_DK', '0', 'testadmin')
        h = hatirlatma.ayarlar(dict(a, BEKLEYEN_OZET_SAAT=2), con)
        assert h['ozet_saat'] == 4 and h['ozet_pencere'] == (0, 1440) and h['ozet_yonetici'] is False and h['kontrol_dk'] == 0
        assert hatirlatma.ayarlar(dict(a), None)['ozet_saat'] in (2, 4)  # conn'suz: settings veritabanı (test dışı)
        r = hatirlatma.uret(con, dict(a, GUN_SONU_SAAT=''), simdi=lambda: SIMDI)
        assert r['bekleyen_ozet'].get('aralik_saat', 4) == 4
    finally:
        con.close()
    from app import api, katalog
    login(c)
    # ONAYSIZ_GORUNUM: okuyucu (kt yok) onaysız kaydı görür → gizle sonrası görmez
    account(a, 'okur', 'OF:oku')
    kid = insert(a, kt=0)
    cikis(c, 'okur')
    assert c.get('/kayit/%d' % kid).status_code == 200
    con = db.baglan(a['DB'])
    ca.yaz(con, 'ONAYSIZ_GORUNUM', 'gizle', 'testadmin')
    assert c.get('/kayit/%d' % kid).status_code in (403, 404), 'yeniden başlatmadan gizlenmeli'
    ca.yaz(con, 'ONAYSIZ_GORUNUM', 'uyar', 'testadmin')
    assert c.get('/kayit/%d' % kid).status_code == 200
    # API_ACIK / API_DAKIKA_SINIRI / PANEL_EKLEME_KATEGORI
    monkeypatch.delenv('API_ACIK', raising=False)
    ca.yaz(con, 'API_ACIK', '0', 'testadmin')
    assert c.get('/api/v1/ozet', headers={'Authorization': 'Bearer x'}).status_code == 404
    ca.sil(con, 'API_ACIK', 'testadmin')
    assert c.get('/api/v1/ozet', headers={'Authorization': 'Bearer x'}).status_code == 401
    ca.yaz(con, 'API_DAKIKA_SINIRI', '7', 'testadmin')
    with panel_istek(c):
        assert api.dakika_siniri() == 7
    ca.yaz(con, 'PANEL_EKLEME_KATEGORI', 'Kısa Mesaj', 'testadmin')
    assert katalog.panel_kategori_etiketi(con) == 'Kısa Mesaj'
    ca.yaz(con, 'HATIRLATMA_GUN', '9', 'testadmin')
    con.close()
    cikis(c)
    assert 'Kısa Mesaj' in c.get('/kayit/yeni').get_data(as_text=True)


class panel_istek:
    def __init__(self, c):
        from app import panel
        self.ctx = panel.app.test_request_context('/')

    def __enter__(self):
        self.ctx.__enter__()

    def __exit__(self, *e):
        self.ctx.__exit__(*e)


def test_ayarlar_sayfasi_sahip_duzenler_superadmin_salt_okur(web, monkeypatch):
    c, a = web
    from app import kullanicilar
    kullanicilar.guncelle(a, 'testadmin', yetki='sahip')  # 2.4.0 (B1): ayarları yalnız sahip değiştirir
    login(c)
    html = c.get('/yonetim/ayarlar').get_data(as_text=True)
    for grup in ('Hatırlatmalar', 'Bildirimler', 'Görünürlük', 'API', 'Görseller'):
        assert '>%s</h2>' % grup in html
    assert 'Şu an geçerli değer' in html and 'TELEGRAM_TOKEN' not in html and 'name="deger"' in html
    r = c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'HATIRLATMA_GUN', 'deger': '0'})
    assert r.status_code == 400 and '1 ile 365 arasında' in r.get_data(as_text=True) and 'aria-invalid="true"' in r.get_data(as_text=True)
    r = c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'HATIRLATMA_GUN', 'deger': '5'})
    assert r.status_code == 302 and r.headers['Location'].endswith('#ayar-HATIRLATMA_GUN')
    html = c.get('/yonetim/ayarlar').get_data(as_text=True)
    assert 'Kaydedildi' in html and 'data-ayar="HATIRLATMA_GUN" data-kaynak="DB"' in html and 'Varsayılana dön' in html
    assert 'Çalışma ayarını değiştirdi' in c.get('/').get_data(as_text=True)
    r = c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'HATIRLATMA_GUN', 'islem': 'sil'})
    assert r.status_code == 302 and 'data-ayar="HATIRLATMA_GUN" data-kaynak="DB"' not in c.get('/yonetim/ayarlar').get_data(as_text=True)
    assert c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'TELEGRAM_TOKEN', 'deger': 'x'}).status_code == 400
    # süperadmin ama sahip değil: görür, değiştiremez (B1 'sahip' rolü gelince g.yk['sahip'] ile)
    from app import isletim
    monkeypatch.setattr(isletim, '_sahip_mi', lambda: False)
    html = c.get('/yonetim/ayarlar').get_data(as_text=True)
    assert 'salt okunur' in html and 'name="deger"' not in html and 'python -m app.cli ayar' in html
    assert c.post('/yonetim/ayarlar', data={'csrf': csrf(c), 'ad': 'HATIRLATMA_GUN', 'deger': '5'}).status_code == 403


def test_sahip_kapisi_g_yk_sahip_alanini_dikkate_alir(web):
    c, a = web
    from app import isletim, panel
    with panel.app.test_request_context('/'):
        from flask import g
        g.yk = {'admin': True}
        assert isletim._sahip_mi() is True
        g.yk = {'admin': True, 'sahip': False}
        assert isletim._sahip_mi() is False
        g.yk = {'admin': False, 'sahip': True}
        assert isletim._sahip_mi() is True


# =============================================================== CLI
def test_cli_ayar_ve_durum(tmp_path):
    veri = tmp_path / 'veri'
    veri.mkdir()
    ortam = dict(os.environ, PANEL_VERI=str(veri), GYAZO_WORKER='0')
    for k in [k for k in ortam if k in ca.SOZLUK]:
        ortam.pop(k)

    def cli(*arg):
        return subprocess.run([sys.executable, '-m', 'app.cli', *arg], cwd=str(SUNUCU), env=ortam, capture_output=True, text=True, timeout=120)
    assert cli('veritabani-kur').returncode == 0
    r = cli('ayar', '--listele')
    assert r.returncode == 0 and '== Hatırlatmalar' in r.stdout and 'BEKLEYEN_OZET_SAAT' in r.stdout and '[varsayılan]' in r.stdout, r.stdout + r.stderr
    r = cli('ayar', 'bekleyen_ozet_saat', '3')
    assert r.returncode == 0 and 'BEKLEYEN_OZET_SAAT = 3' in r.stdout, r.stdout + r.stderr
    assert '[DB]' in [l for l in cli('ayar', '--listele').stdout.splitlines() if 'BEKLEYEN_OZET_SAAT' in l][0]
    r = cli('ayar', 'BEKLEYEN_OZET_SAAT', '99')
    assert r.returncode == 1 and 'Hata:' in r.stderr and '0 ile 24' in r.stderr
    r = cli('ayar', 'TELEGRAM_TOKEN', 'x')
    assert r.returncode == 1 and 'değiştirilemez' in r.stderr
    r = cli('ayar', 'BEKLEYEN_OZET_SAAT', '--sil')
    assert r.returncode == 0 and 'silindi' in r.stdout
    c = sqlite3.connect(veri / 'panel.db')
    assert c.execute("SELECT kullanici FROM denetim WHERE islem='ayar_degistir'").fetchone()[0] == 'sunucu-cli'
    c.close()
    r = cli('durum', '--json')
    j = json.loads(r.stdout)
    assert r.returncode == 1 and [x['kod'] for x in j['satirlar']][:2] == ['web', 'bot'] and j['ozet']['genel'] == 'kirmizi'
    r = cli('durum')
    assert r.returncode == 1 and 'Sistem durumu:' in r.stdout and '[KIRMIZI]' in r.stdout and 'Kayıt:' in r.stdout


# =============================================================== Tarayıcı (Node + Playwright yoksa atlanır)
def _playwright_var():
    if not shutil.which('node'):
        return False
    try:
        return subprocess.run(['node', '-e', "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.mark.skipif(not _playwright_var(), reason='Node + Playwright yok; tarayıcı testi atlandı')
def test_tarayicida_sistem_durumu_ayarlar_yedekler(web, tmp_path):
    import threading
    from waitress.server import create_server
    from app import panel
    c, a = web
    from app import kullanicilar
    kullanicilar.guncelle(a, 'testadmin', yetki='sahip')  # 2.4.0 (B1): ayarlar sayfasını yalnız sahip düzenler
    insert(a)
    yedek.yedek_al(a, 'testadmin')
    con = db.baglan(a['DB'])
    try:
        assert durum.uyari_uret(con, durum.satirlar(con, a, '')) > 0
    finally:
        con.close()
    sunucu = create_server(panel.app, host='127.0.0.1', port=0, threads=6)
    threading.Thread(target=sunucu.run, daemon=True).start()
    try:
        ortam = dict(os.environ, PANEL_URL='http://127.0.0.1:%s' % sunucu.effective_port,
                     EKRAN_KLASORU=os.environ.get('KANIT_EKRAN_KLASORU', ''))
        r = subprocess.run(['node', str(Path(__file__).with_name('isletim_tarayici.js'))], capture_output=True, text=True, timeout=150,
                           env=ortam, cwd=str(tmp_path))
        cikti = r.stdout + r.stderr
        print(cikti[-3000:])
        assert r.returncode == 0 and 'TAMAM' in r.stdout, cikti[-4000:]
    finally:
        try:
            sunucu.close()
        except Exception:
            pass


def test_ayar_tablosu_env_degerini_okuyucunun_kullandigi_gibi_gosterir(web, monkeypatch):
    """.env'deki sınır dışı / geçersiz değer: sayfa okuyucunun gerçekte uyguladığı değeri ve kaynağı yazar."""
    c, a = web
    from app import api
    for ad, d in (('HATIRLATMA_GUN', '500'), ('API_DAKIKA_SINIRI', '200000'), ('BEKLEYEN_OZET_SAAT', '30'), ('GYAZO_PROXY', '0'),
                  ('HATIRLATMA_TEKRAR_GUN', 'abc'), ('GUN_SONU_SAAT', 'kapalı'), ('API_ACIK', 'belki')):
        monkeypatch.setenv(ad, d)
    monkeypatch.delenv('DIS_GORSEL_PROXY', raising=False)
    con = db.baglan(a['DB'])
    try:
        t = {s['ad']: s for s in ca.tablo(con)}
        h = hatirlatma.ayarlar(dict(a, HATIRLATMA_GUN=500, BEKLEYEN_OZET_SAAT=30, HATIRLATMA_TEKRAR_GUN=3), con)
        assert (t['HATIRLATMA_GUN']['gecerli'], t['HATIRLATMA_GUN']['kaynak']) == (str(h['gun']), '.env') == ('500', '.env')
        assert 'yine de 500' in t['HATIRLATMA_GUN']['ortam_uyari']
        assert t['BEKLEYEN_OZET_SAAT']['gecerli'] == str(h['ozet_saat']) == '24' and 'sınırlıyor' in t['BEKLEYEN_OZET_SAAT']['ortam_uyari']
        assert t['API_DAKIKA_SINIRI']['gecerli'] == str(api.dakika_siniri()) == '200000'
        assert (t['HATIRLATMA_TEKRAR_GUN']['gecerli'], t['HATIRLATMA_TEKRAR_GUN']['kaynak']) == ('3', 'varsayılan')
        assert 'geçersiz' in t['HATIRLATMA_TEKRAR_GUN']['ortam_uyari']
        assert t['GUN_SONU_SAAT']['gecerli'] == '18:00', 'okuyucu "kapalı" yazımını tanımaz, 18:00 kullanır'
        assert t['API_ACIK']['gecerli'] == '0' and api.acik_mi() is False
        assert (t['DIS_GORSEL_PROXY']['gecerli'], t['DIS_GORSEL_PROXY']['kaynak']) == ('0', '.env')
        assert 'GYAZO_PROXY' in t['DIS_GORSEL_PROXY']['ortam_uyari'] and ca.deger('DIS_GORSEL_PROXY', conn=con) == '0'
    finally:
        con.close()
