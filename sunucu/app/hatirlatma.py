"""Onay bekleyen kayıtlar için hatırlatma bildirimleri (2.3.1).

Kurallar (ayarlar .env'den, settings.AYAR):
- Yaş = bugün − date(COALESCE(ilk_gorulme, tarih)); her iki alan da boşsa kayıt hesaba girmez.
- Yaş ≥ HATIRLATMA_GUN olan onaysız (kt=0, silindi=0) kayıt için alıcılar: projede 'kt' yetkisi olan aktif kullanıcılar.
- Kayıt başına: kullanıcıya son HATIRLATMA_TEKRAR_GUN gün içinde (bugün dâhil) hatırlatma yoksa yeni hatırlatma;
  olay anahtarı 'hatirlatma:<kayit_id>:<YYYY-MM-DD>' → günde en çok bir; tekrar çalıştırma idempotent.
- Eski Excel'den aktarılmış kayıtlar (kaynak legacy_excel/excel) kayıt başına değil, proje başına özetle bildirilir:
  'hatirlatma-ozet:<proje>:<YYYY-MM-DD>' (kayit_id = projenin en eski bekleyen kaydı); özet de tekrar aralığına uyar.
- Sel koruması GÜN bazlıdır: kullanıcı başına bugün gönderilmiş kayıt hatırlatması sayılır, kalan kota kadar gönderilir;
  fazlası o günün proje özetine katlanır (özet aynı gün için güncellenir). 30 dakikada bir çalışan iş parçacığı ya da
  art arda CLI çağrıları gün içinde yeni satır üretmez. Sıra adildir: hiç/en uzun süredir hatırlatılmamış kayıt önce.
- İleri tarihli olay anahtarları (yanlış --tarih) gerçek günleri susturmaz: yalnız bugün ve öncesi dikkate alınır.

2.3.3 — iki yeni adım (ayrıntı: _saat_adimi, _gun_sonu_adimi):
- 2 saat kuralı: başlangıcı COALESCE(ilk_gorulme, tarih, guncelleme) olan onaysız (eski Excel dışı) kayıt HATIRLATMA_SAAT saati
  doldurunca projede 'kt' yetkisi olan her kullanıcıya BİR KEZ bildirilir ('hatirlatma-saat:<id>'). Aynı çalıştırmada aynı
  projeden HATIRLATMA_SAAT_TOPLU'dan fazla kayıt eşiği geçerse tek toplu satır ('hatirlatma-saat-ozet:<proje>:<YYYY-AA-GG SS:DD>').
  Hangi kaydın kime bildirildiği hatirlatma_isaret tablosunda tutulur; toplu satıra giren kayıt sonradan tek tek bildirilmez.
  Yaş hesabı sunucunun yerel saatiyle yapılır (db.simdi() ile aynı saat).
- Gün sonu: İstanbul saatiyle GUN_SONU_SAAT (18:00) geçince, İstanbul günü başına bir kez, yöneticilere (ya da GUN_SONU_ALICILAR)
  'gun-sonu:<YYYY-AA-GG>' özeti: kaç kayıt onaylanmadı, proje dağılımı, bugün eklenen/onaylanan, 2 saatten uzun bekleyen.
"""
import re
from datetime import date, datetime, time as dtime, timedelta

from . import db, yetki
from .settings import AYAR

ESKI_KAYNAKLAR = ('legacy_excel', 'excel')
KIM = 'sistem'
EN_COK_KONTROL_DK = 7 * 24 * 60
VARSAYILAN_GUN_SONU = '18:00'
EN_COK_SAAT = 30 * 24
# 2.3.3: kaydın başlangıç zamanı. Telegram kaydında ilk_gorulme boştur; tarih eklenme anıdır (tam zaman damgası).
# guncelleme en sona konur: düzenleme/onay kaldırma her seferinde guncelleme'yi yeniler, 2 saat sayacını sıfırlamasın.
BASLANGIC_SQL = "datetime(COALESCE(NULLIF(ilk_gorulme,''),NULLIF(tarih,''),NULLIF(guncelleme,'')))"
EKLENME_SQL = "datetime(COALESCE(NULLIF(ilk_gorulme,''),NULLIF(tarih,'')))"
_LOGLANAN = set()


def _log_bir_kez(metin):
    """Aynı uyarıyı süreç başına bir kez yazar (10 dakikada bir çalışan iş günlüğü doldurmasın)."""
    if metin in _LOGLANAN:
        return
    _LOGLANAN.add(metin)
    print('Hatırlatma: ' + metin, flush=True)


def istanbul_tz():
    """Europe/Istanbul saat dilimi; sunucuda tzdata yoksa None (çağıran sunucu saatini kullanır, bir kez günlüğe yazılır)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo('Europe/Istanbul')
    except Exception:
        _log_bir_kez('Europe/Istanbul saat dilimi bulunamadı; gün sonu için sunucu saati kullanılıyor.')
        return None


def _gun_sonu_saati(ham):
    """'HH:MM' (ya da 'HH.MM') → datetime.time; boş ya da '0' → None (gün sonu kapalı); geçersiz → 18:00 (bir kez günlüğe yazılır)."""
    if ham is None:
        ham = VARSAYILAN_GUN_SONU
    metin = str(ham).strip()
    if metin in ('', '0'):
        return None
    m = re.fullmatch(r'(\d{1,2})[:.](\d{2})', metin)  # 17:30 ya da Türkçe yazımla 17.30
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        return dtime(int(m.group(1)), int(m.group(2)))
    _log_bir_kez('GUN_SONU_SAAT geçersiz (%r); %s kullanılıyor.' % (metin[:20], VARSAYILAN_GUN_SONU))
    return dtime(18, 0)


def _alici_listesi(ham):
    """GUN_SONU_ALICILAR: virgülle ayrılmış kullanıcı adları; boş = None (tüm aktif yöneticiler)."""
    if ham is None:
        return None
    parcalar = ham if isinstance(ham, (list, tuple)) else str(ham).split(',')
    adlar = []
    for ad in parcalar:
        ad = str(ad).strip()
        if ad and ad not in adlar:
            adlar.append(ad)
    return adlar or None


YAS_SQL = "CAST(julianday(?) - julianday(date(COALESCE(NULLIF(ilk_gorulme,''), tarih))) AS INTEGER)"


def ayarlar(ayar=None):
    """Eşik/tekrar/sınır: 1'den küçük ya da geçersiz değer varsayılana döner; kontrol sıklığı 0 = kapalı, üst sınır 7 gün."""
    ayar = ayar or AYAR
    def oku(ad, varsayilan, en_az=1, en_cok=None):
        try:
            deger = int(ayar.get(ad, varsayilan))
        except (TypeError, ValueError):
            return varsayilan
        if deger < en_az:
            return varsayilan
        return min(deger, en_cok) if en_cok else deger
    # 2.3.3: kontrol sıklığı varsayılanı 10 dk (18:00 özeti 18:00–18:10 arasında, 2 saat bildirimi en geç 10 dk gecikmeyle).
    # HATIRLATMA_SAAT 0 = 2 saat bildirimi kapalı (negatif/geçersiz → 2); GUN_SONU_SAAT boş/0 = gün sonu özeti kapalı.
    return dict(gun=oku('HATIRLATMA_GUN', 3), tekrar=oku('HATIRLATMA_TEKRAR_GUN', 3), sinir=oku('HATIRLATMA_GUNLUK_SINIR', 50),
                kontrol_dk=oku('HATIRLATMA_KONTROL_DK', 10, en_az=0, en_cok=EN_COK_KONTROL_DK),
                saat=oku('HATIRLATMA_SAAT', 2, en_az=0, en_cok=EN_COK_SAAT), saat_toplu=oku('HATIRLATMA_SAAT_TOPLU', 5),
                gun_sonu=_gun_sonu_saati(ayar.get('GUN_SONU_SAAT', VARSAYILAN_GUN_SONU)),
                gun_sonu_alicilar=_alici_listesi(ayar.get('GUN_SONU_ALICILAR')),
                gizle=str(ayar.get('ONAYSIZ_GORUNUM', 'uyar') or '').strip().lower() == 'gizle')


def _ekle(conn, alici, kayit_id, proje, olay, metin, en_cok=300, zaman=None):
    return conn.execute('INSERT OR IGNORE INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                        (alici, kayit_id, proje, olay, 'hatirlatma', KIM, db.metin_temizle(metin, en_cok), zaman or db.simdi())).rowcount


def kayit_metni(yas):
    return "Bu ID'nin kontrolü %d gündür bekliyor." % yas


def ozet_metni(proje, toplam, eski, gun, katlanan=0):
    """Özet sayısı, bağlantının açtığı listeyle aynıdır: projede ≥ gün eşiğidir bekleyen TÜM onaysız kayıtlar."""
    metin = '%s: %d kayıt %d günden uzun süredir onay bekliyor' % (proje, toplam, gun)
    if eski and eski == toplam and not katlanan:
        return metin + " (eski Excel'den)."
    parcalar = []
    if eski:
        parcalar.append("%d eski Excel'den" % eski)
    if katlanan:
        parcalar.append('tek tek bildirilmeyen %d' % katlanan)
    return metin + (' (' + '; '.join(parcalar) + ')' if parcalar else '') + '.'


def uret(conn, ayar=None, bugun=None, simdi=None, yerel_tz=None, tz=None, gun_sonu_zorla=False):
    """Hatırlatmaları üretir; JSON'a yazılabilir rapor döndürür. Yeniden çağrılması yeni satır eklemez (idempotent).

    3 gün kuralı 'bugun' gününe göre çalışır (CLI --tarih). 2.3.3 adımları gerçek saate göre çalışır:
    simdi: sunucu yerel saatini (db.simdi() ile aynı saat) naive datetime olarak döndüren çağrılabilir (test için);
    yerel_tz: sunucu saatinin dilimi (None = işletim sisteminin yerel dilimi); tz: İstanbul dilimi (None = Europe/Istanbul);
    gun_sonu_zorla: GUN_SONU_SAAT beklenmeden bugünün gün sonu özetini üret (yine günde bir)."""
    a = ayarlar(ayar)
    rapor = _uc_gun_adimi(conn, a, bugun)
    an = (simdi or datetime.now)()
    rapor['saat'] = _saat_adimi(conn, a, an)
    rapor['gun_sonu'] = _gun_sonu_adimi(conn, a, an, yerel_tz, tz, gun_sonu_zorla)
    return rapor


def _uc_gun_adimi(conn, a, bugun=None):
    """2.3.1'den beri değişmeyen 3 gün kuralı (rapor anahtarları korunur)."""
    bugun = bugun or date.today()
    bugun_s = bugun.isoformat()
    pencere_s = (bugun - timedelta(days=a['tekrar'])).isoformat()  # bu tarihten SONRAKİ hatırlatma tekrarı engeller
    rapor = dict(tarih=bugun_s, esik_gun=a['gun'], tekrar_gun=a['tekrar'], gunluk_sinir=a['sinir'],
                 bekleyen=0, eski_excel=0, hatirlatma=0, ozet=0, sinira_katlanan=0, alici=0, kullanicilar={})
    rows = conn.execute('SELECT id,proje,kaynak,' + YAS_SQL + ' yas FROM kayitlar WHERE kt=0 AND silindi=0 '
                        "AND date(COALESCE(NULLIF(ilk_gorulme,''),tarih)) IS NOT NULL ORDER BY yas DESC, id", (bugun_s,)).fetchall()
    due = [r for r in rows if r['yas'] is not None and r['yas'] >= a['gun']]
    rapor['bekleyen'] = len(due)
    rapor['eski_excel'] = sum(1 for r in due if (r['kaynak'] or '') in ESKI_KAYNAKLAR)
    if not due:
        return rapor
    proje_toplam, proje_eski, proje_en_eski = {}, {}, {}
    for r in due:
        proje_toplam[r['proje']] = proje_toplam.get(r['proje'], 0) + 1
        if (r['kaynak'] or '') in ESKI_KAYNAKLAR:
            proje_eski[r['proje']] = proje_eski.get(r['proje'], 0) + 1
        proje_en_eski.setdefault(r['proje'], r['id'])

    # Son hatırlatma tarihleri (yalnız bugün ve öncesi): tekrar penceresi içindekiler engellenir, diğerleri adil sıra için kullanılır.
    son_kayit = {(r['kullanici_adi'], r['kayit_id']): r['son'] for r in conn.execute(
        "SELECT kullanici_adi,kayit_id,MAX(substr(olay,-10)) son FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'hatirlatma:%' "
        "AND substr(olay,-10)<=? GROUP BY kullanici_adi,kayit_id", (bugun_s,))}
    son_ozet = {(r['kullanici_adi'], r['proje']): r['son'] for r in conn.execute(
        "SELECT kullanici_adi,proje,MAX(substr(olay,-10)) son FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'hatirlatma-ozet:%' "
        "AND substr(olay,-10)<=? GROUP BY kullanici_adi,proje", (bugun_s,))}
    bugun_sayilari = {r['kullanici_adi']: r['n'] for r in conn.execute(
        "SELECT kullanici_adi,COUNT(*) n FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'hatirlatma:%' AND substr(olay,-10)=? GROUP BY kullanici_adi", (bugun_s,))}
    users = [(u['kullanici_adi'], yetki.coz(u['yetki'])) for u in conn.execute('SELECT kullanici_adi,yetki FROM panel_kullanicilari WHERE aktif=1 ORDER BY kullanici_adi')]

    def engelli(son):
        return bool(son) and son > pencere_s

    with db.transaction(conn):
        for ad, yk in users:
            if ad == KIM:
                continue
            tekil, ozet = [], {}
            for r in due:
                if not yetki.izin(yk, r['proje'], 'kt'):
                    continue
                if (r['kaynak'] or '') in ESKI_KAYNAKLAR:
                    if not engelli(son_ozet.get((ad, r['proje']))):
                        ozet.setdefault(r['proje'], dict(katlanan=0))
                    continue
                if not engelli(son_kayit.get((ad, r['id']))):
                    tekil.append(r)
            if not tekil and not ozet:
                continue
            # Adil sıra: hiç hatırlatılmamış ve en uzun süredir hatırlatılmamış önce; eşitlikte en yaşlı kayıt.
            tekil.sort(key=lambda r: (son_kayit.get((ad, r['id'])) or '', -r['yas'], r['id']))
            kalan = max(0, a['sinir'] - bugun_sayilari.get(ad, 0))
            kullanici_rapor = dict(hatirlatma=0, ozet=0, sinira_katlanan=0)
            for r in tekil[:kalan]:
                kullanici_rapor['hatirlatma'] += _ekle(conn, ad, r['id'], r['proje'], 'hatirlatma:%d:%s' % (r['id'], bugun_s), kayit_metni(r['yas']))
            for r in tekil[kalan:]:
                ozet.setdefault(r['proje'], dict(katlanan=0))['katlanan'] += 1
                kullanici_rapor['sinira_katlanan'] += 1
            for proje, kutu in sorted(ozet.items()):
                metin = ozet_metni(proje, proje_toplam[proje], proje_eski.get(proje, 0), a['gun'], kutu['katlanan'])
                olay = 'hatirlatma-ozet:%s:%s' % (proje, bugun_s)
                if son_ozet.get((ad, proje)) == bugun_s:
                    # Günün özeti zaten var: sayı değiştiyse metni güncelle (yeni satır yok, okundu durumu korunur).
                    conn.execute('UPDATE mesaj_bildirimleri SET metin=? WHERE kullanici_adi=? AND olay=? AND metin<>?', (metin, ad, olay, metin))
                else:
                    kullanici_rapor['ozet'] += _ekle(conn, ad, proje_en_eski[proje], proje, olay, metin)
            if kullanici_rapor['hatirlatma'] or kullanici_rapor['ozet']:
                rapor['alici'] += 1
            for key in kullanici_rapor:
                rapor[key] += kullanici_rapor[key]
            rapor['kullanicilar'][ad] = kullanici_rapor
        if rapor['hatirlatma'] or rapor['ozet']:
            db.denetim_yaz(conn, KIM, 'hatirlatma_uret', yeni={'hatirlatma': rapor['hatirlatma'], 'ozet': rapor['ozet'], 'alici': rapor['alici']},
                           hedef_turu='bildirim', hedef_id=bugun_s)
    return rapor


# =============================================================== 2.3.3 — 2 saat kuralı
def _yas_metni(saniye):
    saat = int(saniye // 3600)
    if saat < 24:
        return '%d saattir' % saat
    return '%d gündür' % (saat // 24)


def saat_metni(kayit_id, personel, saniye):
    kim = ' (%s)' % str(personel).strip()[:60] if personel and str(personel).strip() else ''
    return 'Kayıt #%d%s %s onay bekliyor.' % (kayit_id, kim, _yas_metni(saniye))


def saat_ozet_metni(proje, kayitlar, saat):
    ids = ', '.join('#%d' % r['id'] for r in kayitlar[:3])
    if len(kayitlar) > 3:
        ids += ', …'
    return '%s: %d kayıt en az %d saattir onay bekliyor (%s).' % (proje, len(kayitlar), saat, ids)


def _kullanicilar(conn):
    return [(u['kullanici_adi'], yetki.coz(u['yetki'])) for u in conn.execute(
        'SELECT kullanici_adi,yetki FROM panel_kullanicilari WHERE aktif=1 ORDER BY kullanici_adi') if u['kullanici_adi'] != KIM]


def _saat_adimi(conn, a, an):
    """Eşiği geçen her kayıt, kt yetkili her kullanıcıya bir kez; kalabalık projede tek toplu satır.
    'an' sunucu yerel saatidir (db.simdi() ile aynı saat); kayıt zamanları da bu saatle yazılır."""
    rapor = dict(esik_saat=a['saat'], toplu_esik=a['saat_toplu'], aday=0, hatirlatma=0, ozet=0, toplu_kapsanan=0, durum='')
    if a['saat'] <= 0:
        rapor['durum'] = 'kapalı'
        return rapor
    sinir_s = (an - timedelta(hours=a['saat'])).strftime('%Y-%m-%d %H:%M:%S')
    an_s = an.strftime('%Y-%m-%d %H:%M:%S')
    dakika = an.strftime('%Y-%m-%d %H:%M')
    eski = ','.join('?' for _ in ESKI_KAYNAKLAR)
    with db.transaction(conn):
        adaylar = [dict(r) for r in conn.execute(
            'SELECT id,proje,personel,' + BASLANGIC_SQL + ' bas FROM kayitlar WHERE kt=0 AND silindi=0 '
            "AND COALESCE(kaynak,'') NOT IN (" + eski + ') AND ' + BASLANGIC_SQL + ' <= ? ORDER BY bas,id',
            (*ESKI_KAYNAKLAR, sinir_s))]
        rapor['aday'] = len(adaylar)
        if not adaylar:
            return rapor
        isaretli = {(r['kayit_id'], r['kullanici_adi']) for r in conn.execute(
            "SELECT i.kayit_id,i.kullanici_adi FROM hatirlatma_isaret i JOIN kayitlar k ON k.id=i.kayit_id "
            "WHERE i.tur='saat' AND k.kt=0 AND k.silindi=0")}
        for ad, yk in _kullanicilar(conn):
            projeler = {}
            for r in adaylar:
                if (r['id'], ad) in isaretli or not yetki.izin(yk, r['proje'], 'kt'):
                    continue
                projeler.setdefault(r['proje'], []).append(r)
            for proje, liste in sorted(projeler.items()):
                if len(liste) > a['saat_toplu']:
                    olay = 'hatirlatma-saat-ozet:%s:%s' % (proje, dakika)
                    metin = saat_ozet_metni(proje, liste, a['saat'])
                    eklendi = _ekle(conn, ad, liste[0]['id'], proje, olay, metin, zaman=an_s)
                    if not eklendi:  # aynı dakikada ikinci toplu satır (ör. CLI ile arka plan işi): anahtar ayrışsın
                        eklendi = _ekle(conn, ad, liste[0]['id'], proje, olay + ':' + str(liste[0]['id']), metin, zaman=an_s)
                    rapor['ozet'] += eklendi
                    rapor['toplu_kapsanan'] += len(liste)
                else:
                    for r in liste:
                        saniye = max(0, (an - datetime.strptime(r['bas'], '%Y-%m-%d %H:%M:%S')).total_seconds())
                        rapor['hatirlatma'] += _ekle(conn, ad, r['id'], proje, 'hatirlatma-saat:%d' % r['id'],
                                                     saat_metni(r['id'], r['personel'], saniye), zaman=an_s)
                conn.executemany("INSERT OR IGNORE INTO hatirlatma_isaret(kayit_id,kullanici_adi,tur,zaman) VALUES(?,?,'saat',?)",
                                 [(r['id'], ad, an_s) for r in liste])
        if rapor['hatirlatma'] or rapor['ozet']:
            db.denetim_yaz(conn, KIM, 'hatirlatma_uret', yeni={'saat_hatirlatma': rapor['hatirlatma'], 'saat_ozet': rapor['ozet']},
                           hedef_turu='bildirim', hedef_id=dakika)
    return rapor


# =============================================================== 2.3.3 — Gün sonu özeti (İstanbul saati)
def _yerel(aware, yerel_tz):
    """Aware zamanı sunucu yerel saatine (db.simdi() saatine) çevirip naive döndürür."""
    return (aware.astimezone(yerel_tz) if yerel_tz else aware.astimezone()).replace(tzinfo=None)


def istanbul_gunu(an, yerel_tz=None, tz=None):
    """Sunucu yerel saati 'an' (naive) için: (İstanbul şimdi, İstanbul gününün başı ve sonu sunucu yerel saatiyle).
    Dönüşüm aware datetime + astimezone ile yapılır; saat elle kaydırılmaz. tz None ise sunucu saati kullanılır."""
    if tz is None:
        gun = an.date()
        bas, bit = datetime.combine(gun, dtime(0)), datetime.combine(gun + timedelta(days=1), dtime(0))
        return an, bas.strftime('%Y-%m-%d %H:%M:%S'), bit.strftime('%Y-%m-%d %H:%M:%S')
    yerel_aware = an.replace(tzinfo=yerel_tz) if yerel_tz else an.astimezone()
    ist = yerel_aware.astimezone(tz)
    gun = ist.date()
    bas = datetime.combine(gun, dtime(0), tzinfo=tz)
    bit = datetime.combine(gun + timedelta(days=1), dtime(0), tzinfo=tz)
    return ist, _yerel(bas, yerel_tz).strftime('%Y-%m-%d %H:%M:%S'), _yerel(bit, yerel_tz).strftime('%Y-%m-%d %H:%M:%S')


def gun_sonu_metni(gun, toplam, dagilim, eklenen, onaylanan, uzun, saat, en_cok_proje=8):
    parcalar = ['%s %d' % (p, n) for p, n in dagilim[:en_cok_proje]]
    if len(dagilim) > en_cok_proje:
        parcalar.append('diğer %d proje %d' % (len(dagilim) - en_cok_proje, sum(n for _, n in dagilim[en_cok_proje:])))
    metin = 'Gün sonu %s: %d kayıt onaylanmadı (%s). Bugün eklenen %d, bugün onaylanan %d' % (
        gun.strftime('%d.%m.%Y'), toplam, ', '.join(parcalar), eklenen, onaylanan)
    if saat > 0:
        metin += ', %d saatten uzun bekleyen %d' % (saat, uzun)
    return metin + '.'


def _alicilar(conn, a):
    """Varsayılan: aktif yöneticiler (süperadmin). GUN_SONU_ALICILAR doluysa bu listenin YERİNE o adlar (yok/pasif olan atlanır)."""
    if a['gun_sonu_alicilar'] is None:
        return [(ad, yk) for ad, yk in _kullanicilar(conn) if yk.get('admin')]
    kayitli = {u['kullanici_adi']: u for u in conn.execute('SELECT kullanici_adi,yetki,aktif FROM panel_kullanicilari')}
    sonuc = []
    for ad in a['gun_sonu_alicilar']:
        u = kayitli.get(ad)
        if not u or not u['aktif'] or ad == KIM:
            _log_bir_kez('GUN_SONU_ALICILAR içindeki %r kullanıcısı yok ya da pasif; atlandı.' % ad[:60])
            continue
        sonuc.append((ad, yetki.coz(u['yetki'])))
    return sonuc


def _gun_sonu_adimi(conn, a, an, yerel_tz=None, tz=None, zorla=False):
    rapor = dict(saat=a['gun_sonu'].strftime('%H:%M') if a['gun_sonu'] else None, bildirim=0, bos=0, durum='')
    if a['gun_sonu'] is None and not zorla:
        rapor['durum'] = 'kapalı'
        return rapor
    if tz is None:
        tz = istanbul_tz()
    ist, bas_s, bit_s = istanbul_gunu(an, yerel_tz, tz)
    gun = ist.date()
    rapor.update(tarih=gun.isoformat(), istanbul_saati=ist.strftime('%H:%M'))
    if not zorla and ist.time().replace(second=0, microsecond=0) < a['gun_sonu']:
        rapor['durum'] = 'saati gelmedi'
        return rapor
    olay = 'gun-sonu:%s' % gun.isoformat()
    an_s = an.strftime('%Y-%m-%d %H:%M:%S')
    with db.transaction(conn):
        gonderilmis = {r['kullanici_adi'] for r in conn.execute('SELECT kullanici_adi FROM mesaj_bildirimleri WHERE olay=?', (olay,))}
        alicilar = [(ad, yk) for ad, yk in _alicilar(conn, a) if ad not in gonderilmis]
        if not alicilar:
            rapor['durum'] = 'bugün zaten gönderildi' if gonderilmis else 'alıcı yok'
            return rapor
        bekleyen = {r['proje']: r['n'] for r in conn.execute('SELECT proje,COUNT(*) n FROM kayitlar WHERE kt=0 AND silindi=0 GROUP BY proje')}
        eklenen = {r['proje']: r['n'] for r in conn.execute(
            'SELECT proje,COUNT(*) n FROM kayitlar WHERE silindi=0 AND ' + EKLENME_SQL + ' >= ? AND ' + EKLENME_SQL + ' < ? GROUP BY proje',
            (bas_s, bit_s))}
        onaylanan = {r['proje']: r['n'] for r in conn.execute(
            "SELECT proje,COUNT(*) n FROM kayitlar WHERE kt=1 AND silindi=0 AND datetime(NULLIF(kt_zaman,'')) >= ? "
            "AND datetime(NULLIF(kt_zaman,'')) < ? GROUP BY proje", (bas_s, bit_s))}
        uzun = {}
        if a['saat'] > 0:
            sinir_s = (an - timedelta(hours=a['saat'])).strftime('%Y-%m-%d %H:%M:%S')
            uzun = {r['proje']: r['n'] for r in conn.execute(
                'SELECT proje,COUNT(*) n FROM kayitlar WHERE kt=0 AND silindi=0 AND ' + BASLANGIC_SQL + ' <= ? GROUP BY proje', (sinir_s,))}
        en_eski = {}

        def en_eski_kayit(proje):
            if proje not in en_eski:
                en_eski[proje] = conn.execute(
                    'SELECT id FROM kayitlar WHERE kt=0 AND silindi=0 AND proje=? ORDER BY ' + BASLANGIC_SQL + ' IS NULL,'
                    + BASLANGIC_SQL + ',id LIMIT 1', (proje,)).fetchone()['id']
            return en_eski[proje]

        tum = set(bekleyen) | set(eklenen) | set(onaylanan)
        for ad, yk in alicilar:
            gorur = [p for p in tum if yetki.izin(yk, p, 'oku')]
            if a.get('gizle'):
                # ONAYSIZ_GORUNUM=gizle: kt yetkisi olmayan projelerin onaysız kayıtları bu kişiye hiç gösterilmez;
                # özet de yalnız onay yetkisi olan projeleri sayar (yoksa satır zilde görünmez, yazılmaz).
                gorur = [p for p in gorur if yetki.izin(yk, p, 'kt')]
            dagilim = sorted(((p, bekleyen[p]) for p in gorur if bekleyen.get(p)), key=lambda x: (-x[1], x[0]))
            toplam = sum(n for _, n in dagilim)
            if not toplam:
                rapor['bos'] += 1  # bekleyen yoksa bildirim yok (bildirim satırı bir kayda bağlı olmak zorunda)
                continue
            # Rozet/bağlantı projesi: en kalabalık bekleyen proje (yönetici olmayan alıcıda önce onay yetkisi olduğu projeler);
            # satırın kayıt numarası o projenin en eski bekleyen kaydıdır (mesaj_bildirimleri.kayit_id boş olamaz).
            kt_li = [x for x in dagilim if yetki.izin(yk, x[0], 'kt')]
            proje = (kt_li or dagilim)[0][0]
            metin = gun_sonu_metni(gun, toplam, dagilim, sum(eklenen.get(p, 0) for p in gorur),
                                   sum(onaylanan.get(p, 0) for p in gorur), sum(uzun.get(p, 0) for p in gorur), a['saat'])
            rapor['bildirim'] += _ekle(conn, ad, en_eski_kayit(proje), proje, olay, metin, en_cok=500, zaman=an_s)
        if rapor['bildirim']:
            rapor['durum'] = 'gönderildi'
            db.denetim_yaz(conn, KIM, 'hatirlatma_uret', yeni={'gun_sonu': rapor['bildirim']}, hedef_turu='bildirim', hedef_id=olay)
        else:
            rapor['durum'] = 'bugün zaten gönderildi' if gonderilmis else 'bekleyen kayıt yok'
    return rapor


def rapor_metni(rapor):
    """CLI için kısa Türkçe özet (adım başına sayılar)."""
    s, g = rapor.get('saat') or {}, rapor.get('gun_sonu') or {}
    satirlar = ['3 gün kuralı (%s): %d kayıt hatırlatması, %d proje özeti.' % (rapor.get('tarih'), rapor.get('hatirlatma', 0), rapor.get('ozet', 0))]
    if s.get('durum') == 'kapalı':
        satirlar.append('2 saat kuralı: kapalı (HATIRLATMA_SAAT=0).')
    else:
        satirlar.append('2 saat kuralı: eşiği geçen %d kayıt; %d yeni kayıt hatırlatması, %d toplu bildirim (%d kayıt kapsandı).' % (
            s.get('aday', 0), s.get('hatirlatma', 0), s.get('ozet', 0), s.get('toplu_kapsanan', 0)))
    durum = g.get('durum') or ''
    if durum == 'kapalı':
        satirlar.append('Gün sonu özeti: kapalı (GUN_SONU_SAAT boş).')
    elif durum == 'saati gelmedi':
        satirlar.append('Gün sonu özeti: henüz saati gelmedi (İstanbul saati %s, gönderim %s). Hemen denemek için --gun-sonu-zorla.' % (
            g.get('istanbul_saati'), g.get('saat')))
    else:
        satirlar.append('Gün sonu özeti (%s): %d alıcıya gönderildi; durum: %s.' % (g.get('tarih'), g.get('bildirim', 0), durum))
    return '\n'.join(satirlar)
