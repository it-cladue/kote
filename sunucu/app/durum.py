"""2.4.0 — Sistem durumu: web, bot, son yedek, gece görsel işi, hatırlatma işi, disk, veritabanı, bot kuyruğu.

Her satır: {kod, ad, renk ('yesil'|'sari'|'kirmizi'|'gri'), deger, aciklama, komut}. Eşikler:
  bot           son sinyal < 2 dk yeşil, < 10 dk sarı, değilse kırmızı (duraklatılmış bot sarı)
  yedek         son GECE yedeği (panel/elle yedekler renge katılmaz, yalnız ek bilgi) < 26 saat yeşil, < 50 saat sarı, değilse / hiç yoksa / bütünlük bozuksa kırmızı
  gece_gorsel   son çalışma < 36 saat ve başarılı yeşil; daha eski (< 7 gün) ya da hız sınırı/arıza sarı;
                hata/erişim sorunu ya da 7 günden eski kırmızı; hiç çalışmadıysa gri
  hatirlatma    son çalışma < max(20 dk, 2×aralık) yeşil, < max(60 dk, 6×aralık) sarı, değilse kırmızı; aralık 0 ise gri
  disk          veri klasörünün diski < %80 yeşil, < %90 sarı, değilse kırmızı
  kuyruk        ölü (işlenemeyen) mesaj yok ve bekleyen < 20 yeşil; ölü > 0 ya da bekleyen ≥ 20 sarı; bekleyen ≥ 200 kırmızı
Kırmızı satır için günde bir, satır başına bir 'Sistem' bildirimi süperadminlere yazılır (uyari_uret; idempotent).
Saat (simdi) ve işaretler test için dışarıdan verilebilir.
"""
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime

from . import db, yedek

BASLANGIC = time.time()
RENK_ADLARI = {'yesil': 'Normal', 'sari': 'Dikkat', 'kirmizi': 'Sorun', 'gri': 'Bilgi yok'}
UYARI_ONEK = 'sistem:'


def _zaman(metin):
    if not metin:
        return None
    for bicim in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(metin)[:19], bicim)
        except ValueError:
            continue
    return None


def sure_metni(saniye):
    saniye = max(0, int(saniye))
    if saniye < 90:
        return '%d sn' % saniye
    dk = saniye // 60
    if dk < 90:
        return '%d dk' % dk
    saat = dk // 60
    if saat < 48:
        return '%d saat %d dk' % (saat, dk % 60) if dk % 60 else '%d saat' % saat
    return '%d gün %d saat' % (saat // 24, saat % 24) if saat % 24 else '%d gün' % (saat // 24)


def _satir(kod, ad, renk, deger, aciklama, komut=''):
    return {'kod': kod, 'ad': ad, 'renk': renk, 'renk_adi': RENK_ADLARI[renk], 'deger': deger, 'aciklama': aciklama, 'komut': komut}


def _isaret(conn, anahtar):
    try:
        ham = db.ayar_al(conn, anahtar)
        veri = json.loads(ham) if ham else None
        return veri if isinstance(veri, dict) else None
    except (sqlite3.Error, ValueError, TypeError):
        return None


def web_satiri(surum, simdi_ts):
    return _satir('web', 'Web sunucusu', 'yesil', 'Sürüm %s · çalışma süresi %s' % (surum, sure_metni(simdi_ts - BASLANGIC)),
                  'Panel açık ve istekleri yanıtlıyor.')


def bot_satiri(conn, an):
    komut = 'sudo systemctl status kanit-bot --no-pager; sudo journalctl -u kanit-bot -n 50 --no-pager'
    try:
        r = conn.execute('SELECT heartbeat,hata FROM tg_durum WHERE heartbeat IS NOT NULL ORDER BY heartbeat DESC LIMIT 1').fetchone()
        duraklatildi = db.ayar_al(conn, 'bot_durdur', '0') == '1'
    except sqlite3.Error:
        r, duraklatildi = None, False
    if not r:
        return _satir('bot', 'Telegram botu', 'kirmizi', 'Hiç sinyal yok', 'Bot hiç çalışmamış ya da veritabanına ulaşamıyor.',
                      'sudo systemctl enable --now kanit-bot; ' + komut)
    zaman = _zaman(r['heartbeat'])
    yas = (an - zaman).total_seconds() if zaman else None
    if yas is None:
        return _satir('bot', 'Telegram botu', 'kirmizi', 'Sinyal okunamadı', 'Son sinyal zamanı geçersiz.', komut)
    deger = 'Son sinyal %s önce (%s)' % (sure_metni(yas), r['heartbeat'])
    if duraklatildi:
        return _satir('bot', 'Telegram botu', 'sari', deger, 'Bot yönetici tarafından duraklatıldı; mesajlar işlenmiyor. Bot sayfasından "Botu sürdür".')
    if yas < 120:
        if r['hata']:
            return _satir('bot', 'Telegram botu', 'sari', deger, 'Bot çalışıyor ama son hata: ' + str(r['hata'])[:160], komut)
        return _satir('bot', 'Telegram botu', 'yesil', deger, 'Bot çalışıyor.')
    if yas < 600:
        return _satir('bot', 'Telegram botu', 'sari', deger, 'Bot birkaç dakikadır sinyal vermiyor; Telegram bağlantısı yavaş olabilir.', komut)
    return _satir('bot', 'Telegram botu', 'kirmizi', deger, 'Bot çalışmıyor: Telegram\'dan gelen kanıtlar işlenmiyor.',
                  'sudo systemctl restart kanit-bot; ' + komut)


def _yedek_ozeti(son, an):
    zaman = _zaman(son.get('zaman'))
    yas = (an - zaman).total_seconds() if zaman else 10 ** 9
    return yas, '%s önce · %s · %s kayıt · %s' % (
        sure_metni(yas), son.get('ad') or os.path.basename(str(son.get('dosya') or son.get('yol') or '')),
        son.get('kayit') if son.get('kayit') is not None else '?', yedek.boyut_metni(son.get('boyut') or 0))


def yedek_satiri(ayar, an, isaret=None, diger=None):
    """Renk YALNIZ gece (kanit-yedek.timer) yedeğine göre verilir: panelden/elle alınan yedek gece işinin bozulduğunu
    gizlemesin (panel yedekleri ayrıca panelin silebileceği veri diskindedir). En yeni panel/elle yedek ek bilgi olarak yazılır.
    isaret: gece yedeği işareti (test); diger: en yeni yedek işareti, türü ne olursa olsun (test)."""
    gece = isaret if isaret is not None else yedek.son_gece_yedegi(ayar)
    diger = diger if diger is not None else yedek.son_yedek(ayar)
    komut = 'sudo systemctl status kanit-yedek.timer --no-pager; sudo journalctl -t kanit-yedek -n 30 --no-pager; sudo ' + yedek.BETIK
    ek = ''
    if diger and diger.get('tur') in ('panel', 'el') and (not gece or str(diger.get('zaman')) > str(gece.get('zaman'))):
        ek = ' Ayrıca %s yedek: %s.' % ('panelden alınan' if diger.get('tur') == 'panel' else 'sunucuda elle alınan', _yedek_ozeti(diger, an)[1])
    if not gece:
        return _satir('yedek', 'Son yedek', 'kirmizi', 'Gece yedeği bilgisi yok',
                      'Gece (otomatik) yedeği hiç alınmamış ya da kurulu değil; panelden alınan yedek bunun yerini tutmaz. '
                      'Bir kez kurun: ' + yedek.kurulum_komutu() + '.' + ek, komut)
    yas, deger = _yedek_ozeti(gece, an)
    if str(gece.get('integrity') or 'ok').lower() != 'ok':
        return _satir('yedek', 'Son yedek', 'kirmizi', deger, 'Son gece yedeği bütünlük denetiminden geçmedi.' + ek, 'sudo %s --dogrula' % yedek.BETIK)
    if yas < 26 * 3600:
        return _satir('yedek', 'Son yedek', 'yesil', deger, 'Son 26 saat içinde doğrulanmış gece yedeği var.' + ek)
    if yas < 50 * 3600:
        return _satir('yedek', 'Son yedek', 'sari', deger, 'Dünkü gece yedeği alınmamış görünüyor.' + ek, komut)
    return _satir('yedek', 'Son yedek', 'kirmizi', deger, '2 günden uzun süredir gece yedeği alınmadı.' + ek, komut)


def gece_gorsel_satiri(conn, an, isaret=None):
    from .gorsel import GECE_IS_ISARETI
    son = isaret if isaret is not None else _isaret(conn, GECE_IS_ISARETI)
    komut = 'sudo systemctl status kanit-gyazo.timer --no-pager; sudo journalctl -u kanit-gyazo -n 40 --no-pager'
    if not son:
        return _satir('gece_gorsel', 'Gece görsel işi', 'gri', 'Henüz çalışmadı',
                      'Gyazo/Snappark görsellerini sunucuya kopyalayan gece işi hiç çalışmamış (kurulu değil ya da ilk gece gelmedi).',
                      'cd /opt/kanit-paneli && sudo bash deploy/setup-gyazo-gece.sh')
    zaman = _zaman(son.get('zaman'))
    yas = (an - zaman).total_seconds() if zaman else 10 ** 9
    neden = str(son.get('bitis_nedeni') or '')
    deger = '%s önce · indirilen %s · açılamayan %s · %s' % (sure_metni(yas), son.get('indirilen', 0) or 0, son.get('acilamayan', 0) or 0,
                                                            {'tamam': 'tamamlandı', 'sinir': 'gece sınırı doldu, sürecek', 'sure': 'pencere bitti, sürecek',
                                                             'hiz_siniri': 'hız sınırı', 'erisim': 'erişim yok', 'hata': 'hata'}.get(neden, neden or '?'))
    if neden in ('erisim', 'hata'):
        return _satir('gece_gorsel', 'Gece görsel işi', 'kirmizi', deger, 'Son çalışma başarısız: ' + str(son.get('durduruldu') or '')[:200], komut)
    if yas >= 7 * 86400:
        return _satir('gece_gorsel', 'Gece görsel işi', 'kirmizi', deger, 'Bir haftadır çalışmamış.', komut)
    if yas >= 36 * 3600:
        return _satir('gece_gorsel', 'Gece görsel işi', 'sari', deger, 'Dün gece çalışmamış görünüyor.', komut)
    if neden == 'hiz_siniri' or son.get('ariza'):
        return _satir('gece_gorsel', 'Gece görsel işi', 'sari', deger, 'Servis yavaş ya da arızalı (%s); sonraki gece yeniden denenir.'
                      % ', '.join(son.get('ariza') or []) if son.get('ariza') else 'Hız sınırına takıldı; sonraki gece kaldığı yerden sürer.')
    return _satir('gece_gorsel', 'Gece görsel işi', 'yesil', deger, 'Son gece çalıştı. Açılamayanlar: veri klasöründe gyazo-acilamayan.csv.')


def hatirlatma_satiri(conn, ayar, an, isaret=None):
    from . import hatirlatma
    dk = hatirlatma.ayarlar(ayar, conn)['kontrol_dk']
    if dk <= 0:
        return _satir('hatirlatma', 'Hatırlatma işi', 'gri', 'Kapalı (HATIRLATMA_KONTROL_DK=0)', 'Hatırlatma ve özet bildirimleri üretilmiyor. Açmak için Çalışma ayarları.')
    son = isaret if isaret is not None else _isaret(conn, hatirlatma.IS_ISARETI)
    komut = 'sudo systemctl restart kanit-web; sudo journalctl -u kanit-web -n 50 --no-pager | grep -i hatırlatma'
    if not son:
        return _satir('hatirlatma', 'Hatırlatma işi', 'sari', 'Henüz çalışmadı', 'Sunucu açıldıktan ~20 sn sonra ilk kez çalışır.', komut)
    zaman = _zaman(son.get('zaman'))
    yas = (an - zaman).total_seconds() if zaman else 10 ** 9
    deger = 'Son çalışma %s önce (%d dk\'da bir)' % (sure_metni(yas), dk)
    if yas < max(20, 2 * dk) * 60:
        return _satir('hatirlatma', 'Hatırlatma işi', 'yesil', deger, 'Bildirimler düzenli üretiliyor.')
    if yas < max(60, 6 * dk) * 60:
        return _satir('hatirlatma', 'Hatırlatma işi', 'sari', deger, 'İş gecikiyor.', komut)
    return _satir('hatirlatma', 'Hatırlatma işi', 'kirmizi', deger, 'Hatırlatma işi durmuş; bildirimler üretilmiyor.', komut)


def disk_satiri(ayar, kullanim=None):
    yol = ayar.get('BOT_KLASOR') or os.path.dirname(ayar.get('DB') or '.')
    try:
        k = kullanim or shutil.disk_usage(yol)
    except OSError:
        return _satir('disk', 'Disk', 'gri', 'Okunamadı', 'Veri klasörünün diski okunamadı.')
    oran = 100.0 * (k.total - k.free) / k.total if k.total else 0
    deger = '%%%d dolu · %s boş / %s' % (round(oran), yedek.boyut_metni(k.free), yedek.boyut_metni(k.total))
    komut = 'df -h; sudo du -xsh /opt/kanit-paneli/data/* /var/backups/kanit-paneli/* 2>/dev/null | sort -h | tail'
    if oran < 80:
        return _satir('disk', 'Disk', 'yesil', deger, 'Yeterli boş alan var.')
    if oran < 90:
        return _satir('disk', 'Disk', 'sari', deger, 'Disk dolmaya yaklaşıyor; eski dosyaları temizleyin.', komut)
    return _satir('disk', 'Disk', 'kirmizi', deger, 'Disk neredeyse dolu: yedek ve yeni kanıt yazılamayabilir.', komut)


def veritabani_satiri(ayar):
    yol = ayar.get('DB') or ''
    toplam = 0
    for ek in ('', '-wal'):
        try:
            toplam += os.path.getsize(yol + ek)
        except OSError:
            pass
    return _satir('veritabani', 'Veritabanı boyutu', 'yesil', yedek.boyut_metni(toplam), 'SQLite (WAL) dosyasının boyutu.')


def kuyruk_satiri(conn):
    bekleyen = olu = 0
    for tablo in ('tg_gelen', 'tg_giden'):
        try:
            for r in conn.execute('SELECT durum,COUNT(*) adet FROM ' + tablo + ' GROUP BY durum'):
                if r['durum'] in ('bekliyor', 'tekrar'):
                    bekleyen += r['adet']
                elif r['durum'] == 'olu':
                    olu += r['adet']
        except sqlite3.Error:
            continue
    deger = '%d bekleyen · %d işlenemeyen' % (bekleyen, olu)
    if bekleyen >= 200:
        return _satir('kuyruk', 'Bot kuyruğu', 'kirmizi', deger, 'Bot mesajları birikiyor; bot çalışmıyor olabilir.', 'sudo systemctl restart kanit-bot')
    if olu or bekleyen >= 20:
        return _satir('kuyruk', 'Bot kuyruğu', 'sari', deger, 'İşlenemeyen mesajlar Bot sayfası → Hatalar bölümünde; "Yeniden dene" ile tekrar denenir.' if olu
                      else 'Bekleyen mesaj çok; bot yavaş işliyor olabilir.')
    return _satir('kuyruk', 'Bot kuyruğu', 'yesil', deger, 'Kuyruk normal.')


def satirlar(conn, ayar, surum='', simdi=None, isaretler=None, disk=None, komut_satiri=False):
    """Bütün satırlar (sıra sabittir). simdi: naive yerel datetime (test); isaretler: {'yedek' (gece yedeği):…, 'yedek_diger':…, 'gece_gorsel':…, 'hatirlatma':…}.
    komut_satiri: CLI'dan çağrı (web sürecinin çalışma süresi bilinmez; satır gri ve yönlendirici)."""
    an = simdi or datetime.now()
    isaretler = isaretler or {}
    ts = time.time() if simdi is None else an.timestamp()
    web = (_satir('web', 'Web sunucusu', 'gri', 'Sürüm %s' % surum, 'Komut satırından web sürecinin durumu görünmez.',
                  'sudo systemctl status kanit-web --no-pager; curl -s http://127.0.0.1:18080/saglik') if komut_satiri else web_satiri(surum, ts))
    return [web, bot_satiri(conn, an), yedek_satiri(ayar, an, isaretler.get('yedek'), isaretler.get('yedek_diger')),
            gece_gorsel_satiri(conn, an, isaretler.get('gece_gorsel')), hatirlatma_satiri(conn, ayar, an, isaretler.get('hatirlatma')),
            disk_satiri(ayar, disk), veritabani_satiri(ayar), kuyruk_satiri(conn)]


def ozet(rows):
    renkler = [r['renk'] for r in rows]
    genel = 'kirmizi' if 'kirmizi' in renkler else 'sari' if 'sari' in renkler else 'yesil'
    return {'genel': genel, 'kirmizi': renkler.count('kirmizi'), 'sari': renkler.count('sari'),
            'metin': {'yesil': 'Her şey normal', 'sari': 'Dikkat gerektiren satır var', 'kirmizi': 'Sorun var: kırmızı satırlara bakın'}[genel]}


def _alicilar(conn):
    """Sahip / süperadminler (etkin). B1 'sahip' rolünü eklerse yetki metni 'admin' olmayan sahipler de buraya eklenmeli."""
    return [r[0] for r in conn.execute("SELECT kullanici_adi FROM panel_kullanicilari WHERE aktif=1 AND yetki='admin' ORDER BY kullanici_adi")]


def uyari_uret(conn, rows, simdi=None):
    """Kırmızı satır başına, günde bir 'sistem' bildirimi (olay 'sistem:<kod>:<YYYY-AA-GG>'). Dönüş: eklenen satır sayısı.
    Bildirim bir kayda bağlı olmak zorunda olduğundan (tablo kısıtı) en yeni kayıt 'çapa' olarak kullanılır; hiç kayıt yoksa
    bildirim yazılmaz (kart yine kırmızı gösterir). Proje boş yazılır: uyarı bir projeye ait değildir. Bildirime tıklayınca ana sayfadaki Sistem durumu kartı açılır."""
    kirmizi = [r for r in rows if r['renk'] == 'kirmizi']
    if not kirmizi:
        return 0
    gun = (simdi or datetime.now()).strftime('%Y-%m-%d')
    try:
        capa = conn.execute('SELECT id FROM kayitlar ORDER BY id DESC LIMIT 1').fetchone()
    except sqlite3.Error:
        return 0
    if not capa:
        return 0
    eklenen = 0
    with db.transaction(conn):
        alicilar = _alicilar(conn)
        for r in kirmizi:
            metin = 'Sistem: %s — %s %s' % (r['ad'], r['aciklama'], ('Komut: ' + r['komut']) if r['komut'] else '')
            for ad in alicilar:
                eklenen += conn.execute('INSERT OR IGNORE INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) '
                                        'VALUES(?,?,?,?,?,?,?,?)', (ad, capa['id'], '', '%s%s:%s' % (UYARI_ONEK, r['kod'], gun),
                                                                   'sistem', 'sistem', db.metin_temizle(metin.strip(), 300), db.simdi())).rowcount
    return eklenen
