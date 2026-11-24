"""Onay bekleyen kayıtlar için hatırlatma bildirimleri (2.3.1).

Kurallar (ayarlar .env'den, settings.AYAR):
- Yaş = bugün − date(COALESCE(ilk_gorulme, tarih)); her iki alan da boşsa kayıt hesaba girmez.
- Yaş ≥ HATIRLATMA_GUN olan onaysız (kt=0, silindi=0) kayıt için alıcılar: projede 'kt' yetkisi olan aktif kullanıcılar.
- Kayıt başına: kullanıcıya son hatırlatma HATIRLATMA_TEKRAR_GUN günden eskiyse (ya da hiç yoksa) yeni hatırlatma;
  olay anahtarı 'hatirlatma:<kayit_id>:<YYYY-MM-DD>' → günde en çok bir, tekrar çalıştırma idempotent.
- Eski Excel'den aktarılmış kayıtlar (kaynak legacy_excel/excel) kayıt başına değil, proje başına özetle bildirilir:
  'hatirlatma-ozet:<proje>:<YYYY-MM-DD>' (kayit_id = projenin en eski bekleyen kaydı); özet de tekrar aralığına uyar.
- Sel koruması: bir çalıştırmada kullanıcı başına en çok HATIRLATMA_GUNLUK_SINIR kayıt hatırlatması; aşan kısım aynı
  günün proje özetine katlanır.
"""
from datetime import date

from . import db, yetki
from .settings import AYAR

ESKI_KAYNAKLAR = ('legacy_excel', 'excel')
KIM = 'sistem'
YAS_SQL = 'CAST(julianday(?) - julianday(date(COALESCE(ilk_gorulme, tarih))) AS INTEGER)'


def ayarlar(ayar=None):
    ayar = ayar or AYAR
    def oku(ad, varsayilan, en_az):
        try:
            return max(en_az, int(ayar.get(ad, varsayilan)))
        except (TypeError, ValueError):
            return varsayilan
    return dict(gun=oku('HATIRLATMA_GUN', 3, 1), tekrar=oku('HATIRLATMA_TEKRAR_GUN', 3, 1),
                sinir=oku('HATIRLATMA_GUNLUK_SINIR', 50, 1), kontrol_dk=oku('HATIRLATMA_KONTROL_DK', 30, 0))


def _gun_farki(bugun, son):
    """son 'YYYY-MM-DD' (olay anahtarının sonu); okunamazsa 'çok eski' sayılır."""
    if not son:
        return None
    try:
        return (bugun - date.fromisoformat(str(son)[:10])).days
    except ValueError:
        return None


def _ekle(conn, alici, kayit_id, proje, olay, metin):
    return conn.execute('INSERT OR IGNORE INTO mesaj_bildirimleri(kullanici_adi,kayit_id,proje,olay,tur,kim,metin,zaman) VALUES(?,?,?,?,?,?,?,?)',
                        (alici, kayit_id, proje, olay, 'hatirlatma', KIM, db.metin_temizle(metin, 300), db.simdi())).rowcount


def kayit_metni(yas):
    return "Bu ID'nin kontrolü %d gündür bekliyor." % yas


def ozet_metni(proje, toplam, eski, gun):
    metin = '%s: %d kayıt %d günden uzun süredir onay bekliyor' % (proje, toplam, gun)
    if eski and eski == toplam:
        metin += ' (eski Excel\'den)'
    elif eski:
        metin += ' (%d eski Excel\'den)' % eski
    return metin + '.'


def uret(conn, ayar=None, bugun=None):
    """Hatırlatmaları üretir; JSON'a yazılabilir rapor döndürür. Aynı gün ikinci çağrı yeni satır eklemez."""
    a = ayarlar(ayar)
    bugun = bugun or date.today()
    bugun_s = bugun.isoformat()
    rapor = dict(tarih=bugun_s, esik_gun=a['gun'], tekrar_gun=a['tekrar'], gunluk_sinir=a['sinir'],
                 bekleyen=0, eski_excel=0, hatirlatma=0, ozet=0, sinira_katlanan=0, alici=0, kullanicilar={})
    rows = conn.execute('SELECT id,proje,kaynak,' + YAS_SQL + ' yas FROM kayitlar WHERE kt=0 AND silindi=0 '
                        'AND date(COALESCE(ilk_gorulme,tarih)) IS NOT NULL ORDER BY yas DESC, id', (bugun_s,)).fetchall()
    due = [r for r in rows if r['yas'] is not None and r['yas'] >= a['gun']]
    rapor['bekleyen'] = len(due)
    rapor['eski_excel'] = sum(1 for r in due if (r['kaynak'] or '') in ESKI_KAYNAKLAR)
    if not due:
        return rapor

    def tekrar_zamani(son):
        fark = _gun_farki(bugun, son)
        return fark is None or fark >= a['tekrar']

    son_kayit = {(r['kullanici_adi'], r['kayit_id']): r['son'] for r in conn.execute(
        "SELECT kullanici_adi,kayit_id,MAX(substr(olay,-10)) son FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'hatirlatma:%' GROUP BY kullanici_adi,kayit_id")}
    son_ozet = {(r['kullanici_adi'], r['proje']): r['son'] for r in conn.execute(
        "SELECT kullanici_adi,proje,MAX(substr(olay,-10)) son FROM mesaj_bildirimleri WHERE tur='hatirlatma' AND olay LIKE 'hatirlatma-ozet:%' GROUP BY kullanici_adi,proje")}
    users = [(u['kullanici_adi'], yetki.coz(u['yetki'])) for u in conn.execute('SELECT kullanici_adi,yetki FROM panel_kullanicilari WHERE aktif=1 ORDER BY kullanici_adi')]
    with db.transaction(conn):
        for ad, yk in users:
            if ad == KIM:
                continue
            tekil, ozet = [], {}
            for r in due:
                if not yetki.izin(yk, r['proje'], 'kt'):
                    continue
                if (r['kaynak'] or '') in ESKI_KAYNAKLAR:
                    if tekrar_zamani(son_ozet.get((ad, r['proje']))):
                        kutu = ozet.setdefault(r['proje'], dict(toplam=0, eski=0, kayit=r['id']))
                        kutu['toplam'] += 1; kutu['eski'] += 1
                    continue
                if tekrar_zamani(son_kayit.get((ad, r['id']))):
                    tekil.append(r)
            if not tekil and not ozet:
                continue
            kullanici_rapor = dict(hatirlatma=0, ozet=0, sinira_katlanan=0)
            for r in tekil[:a['sinir']]:
                kullanici_rapor['hatirlatma'] += _ekle(conn, ad, r['id'], r['proje'], 'hatirlatma:%d:%s' % (r['id'], bugun_s), kayit_metni(r['yas']))
            for r in tekil[a['sinir']:]:
                kutu = ozet.setdefault(r['proje'], dict(toplam=0, eski=0, kayit=r['id']))
                kutu['toplam'] += 1; kullanici_rapor['sinira_katlanan'] += 1
            for proje, kutu in sorted(ozet.items()):
                kullanici_rapor['ozet'] += _ekle(conn, ad, kutu['kayit'], proje, 'hatirlatma-ozet:%s:%s' % (proje, bugun_s),
                                                 ozet_metni(proje, kutu['toplam'], kutu['eski'], a['gun']))
            if kullanici_rapor['hatirlatma'] or kullanici_rapor['ozet']:
                rapor['alici'] += 1
            for key in kullanici_rapor:
                rapor[key] += kullanici_rapor[key]
            rapor['kullanicilar'][ad] = kullanici_rapor
        if rapor['hatirlatma'] or rapor['ozet']:
            db.denetim_yaz(conn, KIM, 'hatirlatma_uret', yeni={'hatirlatma': rapor['hatirlatma'], 'ozet': rapor['ozet'], 'alici': rapor['alici']},
                           hedef_turu='bildirim', hedef_id=bugun_s)
    return rapor
