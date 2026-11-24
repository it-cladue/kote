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
"""
from datetime import date, timedelta

from . import db, yetki
from .settings import AYAR

ESKI_KAYNAKLAR = ('legacy_excel', 'excel')
KIM = 'sistem'
EN_COK_KONTROL_DK = 7 * 24 * 60
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
    return dict(gun=oku('HATIRLATMA_GUN', 3), tekrar=oku('HATIRLATMA_TEKRAR_GUN', 3), sinir=oku('HATIRLATMA_GUNLUK_SINIR', 50),
                kontrol_dk=oku('HATIRLATMA_KONTROL_DK', 30, en_az=0, en_cok=EN_COK_KONTROL_DK))


def _ekle(conn, alici, kayit_id, proje, olay, metin):
    return conn.execute('INSERT OR IGNORE INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                        (alici, kayit_id, proje, olay, 'hatirlatma', KIM, db.metin_temizle(metin, 300), db.simdi())).rowcount


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


def uret(conn, ayar=None, bugun=None):
    """Hatırlatmaları üretir; JSON'a yazılabilir rapor döndürür. Aynı gün yeniden çağrılması yeni satır eklemez."""
    a = ayarlar(ayar)
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
