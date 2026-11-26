"""2.4.0 — Geri yüklenebilir veritabanı yedeği (panel içinden) ve yedek listesi.

Biçim, sunucu betiği (deploy/kanit-yedek.sh) ile aynıdır: SQLite backup API ile alınmış, tek dosyalık (journal_mode=DELETE),
bütünlük denetiminden geçmiş veritabanı, gzip ile sıkıştırılmış: panel-YYYYAAGG-SSDDSS.db.gz. Bu dosya
'sudo /usr/local/sbin/kanit-yedek.sh --geri-yukle <dosya>' ile geri yüklenir.

Konumlar:
  /var/backups/kanit-paneli/gunluk/  — gece ve sunucuda elle alınan yedekler (root 700; panel bu klasörü okuyamaz)
  data/yedekler/                     — panelden alınan yedekler (kanit 700; panel son PANEL_SAKLA tanesini tutar)
  data/son_yedek.json, data/yedekler.json — betiğin her yedekte yazdığı, panelin okuduğu özet (kanit 600)
  data/son_gece_yedegi.json               — yalnız gece (zamanlayıcı) yedeği; durum kartı 'Son yedek' rengini buna göre verir
Panel yedekleri veri klasöründedir çünkü kanit-web birimi (ProtectSystem=strict) yalnız data/ altına yazabilir; gece yedekleri
root klasöründe kalır (panel ele geçirilse bile onları silemez).
Her yedek klasöründe MANIFEST.tsv: ad, zaman, boyut, integrity, kayit, tür (sekmeyle ayrılmış, satır başına bir yedek).
"""
import gzip
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

VARSAYILAN_KOK = '/var/backups/kanit-paneli'
BETIK = '/usr/local/sbin/kanit-yedek.sh'
PANEL_SAKLA = 10
AD_RX = re.compile(r'^panel-(\d{8})(?:-(\d{6}))?\.db\.gz$')
ISARET = 'son_yedek.json'
GECE_ISARET = 'son_gece_yedegi.json'  # yalnız betik --zamanlayici ile yazar
LISTE = 'yedekler.json'
MANIFEST = 'MANIFEST.tsv'


class YedekHatasi(OSError):
    """Kullanıcıya gösterilecek Türkçe açıklama + sunucuda çalıştırılacak komut."""


def kok(ayar):
    """Gece yedeklerinin kökü (yalnız gösterim için; panel bu klasörü okumaz)."""
    return Path(str((ayar or {}).get('YEDEK_KOK') or os.getenv('KANIT_YEDEK_KOK') or VARSAYILAN_KOK))


def veri_dizini(ayar):
    return Path(ayar['BOT_KLASOR'])


def panel_dizini(ayar):
    return veri_dizini(ayar) / 'yedekler'


def kurulum_komutu():
    return 'cd /opt/kanit-paneli && sudo bash deploy/setup-backup.sh'


def geri_yukleme_komutlari(yol):
    yol = str(yol)
    return {'dene': 'sudo %s --geri-yukle %s --dry-run' % (BETIK, yol), 'uygula': 'sudo %s --geri-yukle %s' % (BETIK, yol)}


def _zaman_addan(ad):
    m = AD_RX.match(ad)
    if not m:
        return None
    try:
        if m.group(2):
            return datetime.strptime(m.group(1) + m.group(2), '%Y%m%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S')
        return datetime.strptime(m.group(1), '%Y%m%d').strftime('%Y-%m-%d')
    except ValueError:
        return None


def _manifest_oku(dizin):
    satirlar = {}
    try:
        with open(dizin / MANIFEST, encoding='utf-8') as f:
            for satir in f:
                p = satir.rstrip('\n').split('\t')
                if len(p) >= 6 and AD_RX.match(p[0]):
                    try:
                        kayit = int(p[4])
                    except ValueError:
                        kayit = None
                    satirlar[p[0]] = {'zaman': p[1], 'integrity': p[3], 'kayit': kayit, 'tur': p[5]}
    except OSError:
        pass
    return satirlar


def _manifest_yaz(dizin, kalanlar, yeni=None):
    """Silinmiş dosyaların satırlarını atar, yeniyi ekler (geçici dosya + rename)."""
    eski = _manifest_oku(dizin)
    satirlar = []
    for ad, v in sorted(eski.items()):
        if ad in kalanlar and (not yeni or ad != yeni['ad']):
            boyut = (dizin / ad).stat().st_size if (dizin / ad).exists() else 0
            satirlar.append('\t'.join([ad, v['zaman'], str(boyut), v['integrity'], '' if v['kayit'] is None else str(v['kayit']), v['tur']]))
    if yeni:
        satirlar.append('\t'.join([yeni['ad'], yeni['zaman'], str(yeni['boyut']), yeni['integrity'], str(yeni['kayit']), yeni['tur']]))
    gecici = dizin / ('.' + MANIFEST + '.%d' % os.getpid())
    gecici.write_text(''.join(s + '\n' for s in satirlar), encoding='utf-8')
    os.replace(gecici, dizin / MANIFEST)


def _json_yaz(yol, veri, mod=0o600):
    gecici = yol.with_name('.' + yol.name + '.%d' % os.getpid())
    with open(gecici, 'w', encoding='utf-8') as f:
        json.dump(veri, f, ensure_ascii=False)
    os.chmod(gecici, mod)
    os.replace(gecici, yol)


def yedek_al(ayar, kim='panel', simdi=None):
    """Panelden geri yüklenebilir yedek. Dönüş: {ad, yol, boyut, zaman, integrity, kayit, tur}.
    Dizin yoksa / yazılamıyorsa YedekHatasi (sunucuda çalıştırılacak komutla)."""
    dizin = panel_dizini(ayar)
    try:
        dizin.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        pass
    if not dizin.is_dir() or not os.access(dizin, os.W_OK | os.X_OK):
        raise YedekHatasi('Yedek klasörü %s yok ya da panel hesabı (kanit) yazamıyor. Sunucuda düzeltin: '
                          'sudo install -d -m 700 -o kanit -g kanit %s — ya da yedeği doğrudan sunucuda alın: sudo %s' % (dizin, dizin, BETIK))
    an = simdi or datetime.now()
    ad = 'panel-' + an.strftime('%Y%m%d-%H%M%S') + '.db.gz'
    hedef = dizin / ad
    if hedef.exists():
        raise YedekHatasi('Bu saniyede zaten bir yedek alındı; birkaç saniye sonra yeniden deneyin.')
    bos = shutil.disk_usage(dizin).free
    kaynak_yol = Path(ayar['DB'])
    if bos < kaynak_yol.stat().st_size * 1.2 + 50 * 1024 * 1024:
        raise YedekHatasi('Diskte yer yetersiz (%d MB boş); yedek alınmadı. Sunucuda: df -h %s' % (bos // 1048576, dizin))
    gecici_db = dizin / ('.panel-yedek-%d-%d.db' % (os.getpid(), time.monotonic_ns()))
    gecici_gz = gecici_db.with_suffix('.gz.tmp')
    fd = os.open(gecici_db, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        kaynak = sqlite3.connect('file:' + quote(str(kaynak_yol.resolve())) + '?mode=ro', uri=True, timeout=30)
        hedef_db = sqlite3.connect(str(gecici_db), timeout=30)
        try:
            kaynak.backup(hedef_db)
            hedef_db.execute('PRAGMA journal_mode=DELETE')  # tek dosya (-wal/-shm yok), betikle aynı
            ic = str(hedef_db.execute('PRAGMA integrity_check').fetchone()[0])
            tablolar = {r[0] for r in hedef_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            kayit = hedef_db.execute('SELECT COUNT(*) FROM kayitlar').fetchone()[0] if 'kayitlar' in tablolar else -1
        finally:
            hedef_db.close()
            kaynak.close()
        if ic.lower() != 'ok':
            raise YedekHatasi('Yedek bütünlük denetiminden geçmedi (%s); dosya yazılmadı. Sunucuda: sudo %s --dogrula' % (ic[:120], BETIK))
        fd = os.open(gecici_gz, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as ham, gzip.GzipFile(filename='', mode='wb', fileobj=ham, mtime=0) as gz, open(gecici_db, 'rb') as f:
            shutil.copyfileobj(f, gz, 1024 * 1024)
        os.replace(gecici_gz, hedef)
    finally:
        for y in (gecici_db, gecici_gz):
            try:
                y.unlink()
            except FileNotFoundError:
                pass
    bilgi = {'ad': ad, 'yol': str(hedef), 'boyut': hedef.stat().st_size, 'zaman': an.strftime('%Y-%m-%d %H:%M:%S'),
             'integrity': 'ok', 'kayit': kayit, 'tur': 'panel', 'kim': str(kim)[:80]}
    # Saklama: en yeni PANEL_SAKLA kalır.
    dosyalar = sorted(p.name for p in dizin.iterdir() if AD_RX.match(p.name))
    for eski in dosyalar[:-PANEL_SAKLA]:
        try:
            (dizin / eski).unlink()
        except OSError:
            pass
    kalanlar = {p.name for p in dizin.iterdir() if AD_RX.match(p.name)}
    try:
        _manifest_yaz(dizin, kalanlar, bilgi)
        _json_yaz(dizin / ISARET, bilgi)
    except OSError:
        pass
    return bilgi


def _isaret_oku(yol):
    try:
        with open(yol, encoding='utf-8') as f:
            veri = json.load(f)
        return veri if isinstance(veri, dict) and veri.get('zaman') else None
    except (OSError, ValueError):
        return None


def son_yedek(ayar):
    """Gece/el (betik) ve panel işaretlerinden en yenisi; hiçbiri yoksa None."""
    adaylar = [x for x in (_isaret_oku(veri_dizini(ayar) / ISARET), _isaret_oku(panel_dizini(ayar) / ISARET)) if x]
    return max(adaylar, key=lambda x: str(x.get('zaman'))) if adaylar else None


def son_gece_yedegi(ayar):
    """En yeni GECE (kanit-yedek.timer) yedeği: data/son_gece_yedegi.json; yoksa son_yedek.json / yedekler.json içindeki
    tür 'gece' olan en yeni öğe. Panelden ya da elle alınan yedekler sayılmaz (gece işinin bozulduğunu gizlemesinler)."""
    adaylar = []
    for yol in (veri_dizini(ayar) / GECE_ISARET, veri_dizini(ayar) / ISARET):
        x = _isaret_oku(yol)
        if x and (yol.name == GECE_ISARET or x.get('tur') == 'gece'):
            adaylar.append(x)
    try:
        with open(veri_dizini(ayar) / LISTE, encoding='utf-8') as f:
            veri = json.load(f)
        for o in (veri.get('yedekler') if isinstance(veri, dict) else []) or []:
            if isinstance(o, dict) and o.get('tur') == 'gece' and o.get('zaman'):
                adaylar.append(o)
    except (OSError, ValueError, AttributeError):
        pass
    return max(adaylar, key=lambda x: str(x.get('zaman'))) if adaylar else None


def _tara(dizin, tur_varsayilan):
    sonuc = []
    try:
        adlar = [p for p in dizin.iterdir() if AD_RX.match(p.name) and p.is_file()]
    except OSError:
        return sonuc
    manifest = _manifest_oku(dizin)
    for p in adlar:
        m = manifest.get(p.name, {})
        try:
            boyut = p.stat().st_size
        except OSError:
            continue
        sonuc.append({'ad': p.name, 'yol': str(p), 'boyut': boyut, 'zaman': m.get('zaman') or _zaman_addan(p.name) or '',
                      'kayit': m.get('kayit'), 'integrity': m.get('integrity') or '', 'tur': m.get('tur') or tur_varsayilan})
    return sonuc


def liste(ayar):
    """Panelin görebildiği bütün yedekler (yeniden eskiye). Gece yedekleri betiğin yazdığı yedekler.json'dan,
    panel yedekleri doğrudan klasörden okunur."""
    ogeler = {}
    try:
        with open(veri_dizini(ayar) / LISTE, encoding='utf-8') as f:
            veri = json.load(f)
        for o in (veri.get('yedekler') if isinstance(veri, dict) else []) or []:
            if isinstance(o, dict) and AD_RX.match(str(o.get('ad', ''))) and o.get('yol'):
                ogeler[str(o['yol'])] = {k: o.get(k) for k in ('ad', 'yol', 'boyut', 'zaman', 'kayit', 'integrity', 'tur')}
    except (OSError, ValueError, AttributeError):
        pass
    panel_yolu = str(panel_dizini(ayar))
    ogeler = {k: v for k, v in ogeler.items() if not k.startswith(panel_yolu + '/')}  # panel klasörü taze okunur
    for o in _tara(panel_dizini(ayar), 'panel'):
        ogeler[o['yol']] = o
    for o in ogeler.values():
        o['komut'] = geri_yukleme_komutlari(o['yol'])
        o['boyut_metin'] = boyut_metni(o.get('boyut') or 0)
        o['tur_adi'] = {'gece': 'Gece (otomatik)', 'el': 'Sunucuda elle', 'panel': 'Panelden'}.get(o.get('tur'), o.get('tur') or '')
    return sorted(ogeler.values(), key=lambda o: str(o.get('zaman') or ''), reverse=True)


def boyut_metni(bayt):
    bayt = int(bayt or 0)
    for birim in ('B', 'KB', 'MB', 'GB'):
        if bayt < 1024 or birim == 'GB':
            return ('%d %s' % (bayt, birim)) if birim == 'B' else ('%.1f %s' % (bayt, birim)).replace('.', ',')
        bayt /= 1024.0
    return ''  # pragma: no cover
