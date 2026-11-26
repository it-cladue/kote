"""2.3.4 — Personel bazında kanıt özeti (ana sayfa kartı, /rapor/personel, Excel/CSV çıktısı ve /api/v1/personel-ozet).

Tek veri işlevi: ``personel_ozeti(conn, izinli_projeler, gizli_sql, filtre)``. Panel ve API aynı işlevi kullanır; yetki
kapsamını (izinli projeler, ONAYSIZ_GORUNUM=gizle koşulu, API'de yalniz_onayli) çağıran verir. Yalnız silinmemiş kayıtlar
sayılır. Sayım tek GROUP BY sorgusuyla yapılır (bağlı parametreler); toplam satırı Python'da aynı sonuçtan çıkarılır.

Tarih kuralı Kayıtlar süzgeciyle aynıdır: ``tarih >= 'YYYY-AA-GG'`` ve ``tarih <= 'YYYY-AA-GG 23:59:59'``; böylece hem
Telegram kayıtlarının tam zaman damgası hem eski Excel kayıtlarının yalnız tarih değeri doğru aralığa düşer. "Bugün"
sunucunun yerel takvim günüdür (ana sayfadaki "Bugün eklenen" sayacı ve db.simdi() ile aynı saat dilimi).

2.3.5: tek değerli ``kategori`` süzgeci (boş = tüm kategoriler). Kayıtlar süzgeciyle aynı eşleme kullanılır
(``TRIM(kategori)`` harf duyarsız; ``__bos__`` = kategorisi boş), böylece sayılar ile bağlantıların açtığı liste birebir tutar."""
import re
from datetime import date, datetime, timedelta

from . import katalog

DONEMLER = (('bugun', 'Bugün'), ('hafta', 'Bu hafta'), ('ay', 'Bu ay'), ('son30', 'Son 30 gün'), ('hepsi', 'Tümü'), ('ozel', 'Özel aralık'))
DURUMLAR = (('hepsi', 'Tümü'), ('onayli', 'Onaylı'), ('bekleyen', 'Bekleyen'))
GRUPLAR = (('personel', 'Personel'), ('ekleyen', 'Ekleyen'))
SUTUNLAR = (('kategori', 'Kategori'), ('tip', 'Tip'))
DONEM_ADLARI = dict(DONEMLER); DURUM_ADLARI = dict(DURUMLAR); GRUP_ADLARI = dict(GRUPLAR); SUTUN_ADLARI = dict(SUTUNLAR)
VARSAYILAN = dict(donem='ay', durum='hepsi', grup='personel', sutun='kategori')
BOS = '(boş)'
# Kayıtlar sayfasının personel / ekleyen_ad / tip süzgecinde "boş değer" anlamına gelen işaret.
BOS_DEGER = '__bos__'
# Kategori/tip sütun renkleri (açık ve koyu temada okunur orta tonlar); sıra katalog sırasını izler.
PALET = ('#2457d6', '#15803d', '#c2410c', '#7c3aed', '#0e7490', '#be185d', '#a16207', '#4d7c0f', '#b91c1c', '#0f766e', '#9333ea', '#475569')
ISI_KADEME = 5

# 2.3.5: baş/son kırpılan karakterler (boşluk, sekme, satır sonu, bölünmez boşluk). SQL tarafı ve Python tarafı aynı kümeyi
# kırpar; böylece Excel'den gelen "CVPS<sekme>" gibi eski değerler hem sayımda hem Kayıtlar süzgecinde aynı değere düşer.
KIRP = ' \t\n\r\xa0'


def kirp(deger):
    """Süzgeç değerini SQL tarafıyla aynı karakter kümesiyle kırpar (iç boşluklara dokunmaz)."""
    return str(deger or '').strip(KIRP)


def kirp_sql(kolon):
    """``kirp`` ile aynı kırpmayı yapan SQL ifadesi (NULL → '')."""
    return "TRIM(COALESCE(%s,''),' '||char(9)||char(10)||char(13)||char(160))" % kolon


_GRUP_KOLON = {'personel': kirp_sql('personel'), 'ekleyen': kirp_sql('ekleyen_ad')}
_SUTUN_KOLON = {'kategori': kirp_sql('kategori'), 'tip': kirp_sql('tip')}


def _tarih(deger):
    deger = str(deger or '').strip()
    if not deger:
        return None
    return datetime.strptime(deger, '%Y-%m-%d').date()


def _tr_tarih(d):
    return d.strftime('%d.%m.%Y') if d else ''


def donem_araligi(donem, bugun, t1=None, t2=None):
    """(başlangıç, bitiş) tarihleri; 'hepsi' için (None, None). Hafta pazartesi başlar."""
    if donem == 'bugun':
        return bugun, bugun
    if donem == 'hafta':
        return bugun - timedelta(days=bugun.weekday()), bugun
    if donem == 'ay':
        return bugun.replace(day=1), bugun
    if donem == 'son30':
        return bugun - timedelta(days=29), bugun
    if donem == 'ozel':
        return t1, t2
    return None, None


def filtre_coz(args, izinli, bugun=None):
    """İstek parametrelerini beyaz listeyle doğrular. Dönüş: (filtre, hatalar, uyarilar).
    Geçersiz değerler varsayılana döner ve ``hatalar``a yazılır (panel uyarı gösterir, API 400 verir).
    İzinli olmayan proje ``PermissionError`` fırlatır (panel/API 403)."""
    bugun = bugun or date.today()
    hatalar, uyarilar = [], []

    def tek(ad):
        return str(args.get(ad) or '').strip()

    proje = tek('proje').upper()
    if proje in ('', 'HEPSI', 'TUM', 'TÜM'):
        proje = ''
    elif proje not in izinli:
        raise PermissionError(proje)
    f = dict(proje=proje)
    # 2.3.5: kategori süzgeci (tek değer). '(boş)' ya da '__bos__' = kategorisi boş kayıtlar. Bilinmeyen değer hata değildir: sıfır satır döner.
    # Kayıtlar süzgeciyle aynı: yalnız baş/son kırpılır, iç boşluklar korunur (seçenek değerleri de böyle üretilir).
    kategori = kirp(args.get('kategori'))[:120]
    if kategori in (BOS, BOS_DEGER) or kategori.casefold() == BOS.casefold():
        kategori = BOS_DEGER
    f['kategori'] = kategori
    for ad, liste in (('donem', DONEM_ADLARI), ('durum', DURUM_ADLARI), ('grup', GRUP_ADLARI), ('sutun', SUTUN_ADLARI)):
        deger = tek(ad).lower()
        if ad == 'donem' and not deger and (tek('tarih1') or tek('tarih2')):
            deger = 'ozel'  # yalnız tarih verilmişse özel aralık sayılır
        if not deger:
            deger = VARSAYILAN[ad]
        elif deger not in liste:
            hatalar.append('%s için geçersiz değer: %s (geçerli: %s).' % (ad, deger[:20], ', '.join(liste)))
            deger = VARSAYILAN[ad]
        f[ad] = deger
    t1 = t2 = None
    if f['donem'] == 'ozel':
        try:
            t1, t2 = _tarih(tek('tarih1')), _tarih(tek('tarih2'))
        except ValueError:
            hatalar.append('Tarih YYYY-AA-GG biçiminde olmalı (ör. 2026-11-01).')
            t1 = t2 = None; f['donem'] = VARSAYILAN['donem']
        else:
            if not t1 and not t2:
                hatalar.append('Özel aralık için en az bir tarih seçin.')
                f['donem'] = VARSAYILAN['donem']
            elif t1 and t2 and t1 > t2:
                t1, t2 = t2, t1
                uyarilar.append('Başlangıç tarihi bitişten sonraydı; tarihler yer değiştirildi.')
    bas, son = donem_araligi(f['donem'], bugun, t1, t2)
    f['tarih1'] = bas.isoformat() if bas else ''
    f['tarih2'] = son.isoformat() if son else ''
    return f, hatalar, uyarilar


def donem_etiketi(f):
    ad = DONEM_ADLARI.get(f.get('donem'), '')
    t1, t2 = _tarih(f.get('tarih1')), _tarih(f.get('tarih2'))
    if not t1 and not t2:
        return ad + ' (tüm tarihler)' if f.get('donem') == 'hepsi' else ad
    if t1 == t2:
        return '%s (%s)' % (ad, _tr_tarih(t1))
    return '%s (%s – %s)' % (ad, _tr_tarih(t1) or '…', _tr_tarih(t2) or '…')


def _katalog_sirasi(conn, projeler):
    """Seçili projelerin kategori adları, proje sırası ve proje içi katalog sırasıyla (tekrarsız, harf duyarsız)."""
    sira, gorulen = [], set()
    for p in projeler:
        try:
            kategoriler = katalog.list_categories(conn, project_code=p, active_only=True)
        except Exception:
            kategoriler = []
        for k in kategoriler:
            ad = str(k.get('label') or '').strip()
            if ad and ad.casefold() not in gorulen:
                gorulen.add(ad.casefold()); sira.append(ad)
    return sira


def kategori_adi(deger):
    """Süzgeç değerinin ekranda görünen adı ('__bos__' → '(boş)')."""
    return BOS if deger == BOS_DEGER else (deger or '')


def kategori_secenekleri(conn, projeler, gizli_sql=None):
    """2.3.5: süzgeç çubuğundaki "Kategori" seçenekleri: önce seçili projelerin katalog adları (katalog sırası), sonra bu
    projelerin silinmemiş kayıtlarında geçen diğer adlar (harf duyarsız tekrarsız, alfabetik), en sonda kategorisi boş kayıt
    varsa '(boş)'. Dönüş: [{deger, ad, katalog}] — deger süzgeç parametresine yazılır."""
    if not projeler:
        return []
    katalog_adlari = _katalog_sirasi(conn, projeler)
    gorulen = {a.casefold() for a in katalog_adlari}
    kosul = ['silindi=0', 'proje IN (%s)' % ','.join('?' * len(projeler))]; par = list(projeler)
    if gizli_sql and gizli_sql[0]:
        kosul.append(gizli_sql[0]); par.extend(gizli_sql[1])
    digerleri, bos_var = [], False
    for r in conn.execute("SELECT DISTINCT %s k FROM kayitlar WHERE %s" % (kirp_sql('kategori'), ' AND '.join(kosul)), par):
        ad = r[0] or ''
        if not ad:
            bos_var = True
        elif ad.casefold() not in gorulen:
            gorulen.add(ad.casefold()); digerleri.append(ad)
    digerleri.sort(key=str.casefold)
    out = [dict(deger=a, ad=a, katalog=True) for a in katalog_adlari] + [dict(deger=a, ad=a, katalog=False) for a in digerleri]
    if bos_var:
        out.append(dict(deger=BOS_DEGER, ad=BOS, katalog=False))
    return out


def kategori_kanonik(secenekler, deger):
    """Kullanıcının yazdığı kategoriyi seçeneklerdeki adla (doğru harf biçimiyle) eşler; eşleşme yoksa değer aynen kalır."""
    if not deger or deger == BOS_DEGER:
        return deger
    return next((s['deger'] for s in secenekler if s['deger'].casefold() == deger.casefold()), deger)


_TR_ASCII = str.maketrans('çğıöşüÇĞİÖŞÜâîû', 'cgiosuCGIOSUaiu')


def dosya_parcasi(deger):
    """Dosya adına girecek güvenli parça (ör. 'S.ARK' → 's-ark', '30gün' → '30gun', '(boş)' → 'bos')."""
    if deger == BOS_DEGER:
        return 'bos'
    parca = re.sub(r'[^a-z0-9]+', '-', str(deger or '').translate(_TR_ASCII).lower()).strip('-')[:40].strip('-')
    return parca or 'kategori'


def isi_seviyesi(n, en_buyuk):
    """Hücre ısı kademesi 0..5 (0 = boş hücre)."""
    if not n or not en_buyuk:
        return 0
    return max(1, min(ISI_KADEME, -(-n * ISI_KADEME // en_buyuk)))


def personel_ozeti(conn, izinli_projeler, gizli_sql, filtre):
    """Personel (veya ekleyen) × kategori (veya tip) sayım tablosu.

    filtre: filtre_coz() çıktısı (proje, donem, durum, grup, sutun, tarih1, tarih2, kategori).
    gizli_sql: (sql, parametreler) — ONAYSIZ_GORUNUM=gizle koşulu; uygulanmıyorsa None veya ('', [])."""
    f = dict(filtre)
    projeler = [f['proje']] if f.get('proje') else list(izinli_projeler)
    grup, sutun = f.get('grup', 'personel'), f.get('sutun', 'kategori')
    kategori = f.get('kategori') or ''
    hucre = {}
    if projeler:
        kosul = ['silindi=0', 'proje IN (%s)' % ','.join('?' * len(projeler))]; par = list(projeler)
        if gizli_sql and gizli_sql[0]:
            kosul.append(gizli_sql[0]); par.extend(gizli_sql[1])
        if f.get('durum') == 'onayli':
            kosul.append('kt=1')
        elif f.get('durum') == 'bekleyen':
            kosul.append('kt=0')
        if f.get('tarih1'):
            kosul.append('tarih >= ?'); par.append(f['tarih1'])
        if f.get('tarih2'):
            kosul.append('tarih <= ?'); par.append(f['tarih2'] + ' 23:59:59')
        if kategori == BOS_DEGER:
            kosul.append(kirp_sql('kategori') + "=''")
        elif kategori:
            # Kayıtlar süzgeciyle aynı: baş/son kırpılır (KIRP), harf duyarsız (UNICODE_NOCASE = casefold) eşleşir.
            kosul.append(kirp_sql('kategori') + " COLLATE UNICODE_NOCASE=?"); par.append(kategori)
        sql = ('SELECT %s g,%s s,COUNT(*) n,COALESCE(SUM(kt=1),0) o FROM kayitlar WHERE %s GROUP BY 1,2'
               % (_GRUP_KOLON[grup], _SUTUN_KOLON[sutun], ' AND '.join(kosul)))
        for r in conn.execute(sql, par):
            hucre[(r['g'] or '', r['s'] or '')] = (r['n'], r['o'])
    # Sütun adları: harf duyarsız birleştirilir (Kayıtlar süzgeci de harf duyarsız eşler); katalog adı önceliklidir.
    katalog_adlari = _katalog_sirasi(conn, projeler) if sutun == 'kategori' else []
    ad_haritasi = {a.casefold(): a for a in katalog_adlari}
    sutun_toplam = {}
    for (_, s), (n, _) in hucre.items():
        anahtar = s.casefold()
        if anahtar not in ad_haritasi:
            ad_haritasi[anahtar] = s
        sutun_toplam[ad_haritasi[anahtar]] = sutun_toplam.get(ad_haritasi[anahtar], 0) + n
    digerleri = [a for a in sutun_toplam if a not in katalog_adlari and a != '']
    if sutun == 'kategori':
        digerleri.sort(key=str.casefold)
    else:
        digerleri.sort(key=lambda a: (-sutun_toplam[a], a.casefold()))
    sira = katalog_adlari + digerleri + ([''] if '' in sutun_toplam else [])
    katalogda = {a.casefold() for a in katalog_adlari}
    sutun_bilgi = [dict(ad=a or BOS, deger=a, bos=not a, katalog=a.casefold() in katalogda, renk=PALET[i % len(PALET)] if a else '#94a3b8',
                        toplam=sutun_toplam.get(a, 0)) for i, a in enumerate(sira)]
    kategori_gorunen = ''
    if kategori:
        # 2.3.5: kategori seçiliyken kategori sütunlarında yalnız o kategori kalır (renk tüm listedeki sırasından gelir);
        # kayıt yoksa bile sütun sıfırla gösterilir. Tip sütunlarında yalnız sayılar o kategoriyle sınırlanır.
        hedef = '' if kategori == BOS_DEGER else kategori.casefold()
        kategori_gorunen = BOS if kategori == BOS_DEGER else ad_haritasi.get(hedef, kategori)
        if sutun == 'kategori':
            sutun_bilgi = [b for b in sutun_bilgi if b['deger'].casefold() == hedef]
            if not sutun_bilgi:
                sutun_bilgi = [dict(ad=kategori_gorunen, deger='' if kategori == BOS_DEGER else kategori, bos=kategori == BOS_DEGER, katalog=False,
                                    renk='#94a3b8' if kategori == BOS_DEGER else PALET[len(katalog_adlari) % len(PALET)], toplam=0)]
    satirlar = {}
    for (gk, s), (n, o) in hucre.items():
        sat = satirlar.setdefault(gk, dict(personel=gk or BOS, deger=gk, bos=not gk, toplam=0, onayli=0, bekleyen=0,
                                           sutunlar={b['ad']: 0 for b in sutun_bilgi}))
        sat['toplam'] += n; sat['onayli'] += o; sat['bekleyen'] += n - o
        sat['sutunlar'][(ad_haritasi[s.casefold()] or BOS)] += n
    liste = sorted(satirlar.values(), key=lambda x: (-x['toplam'], x['bos'], x['personel'].casefold()))
    en_buyuk = max([v for x in liste for v in x['sutunlar'].values()] or [0])
    for x in liste:
        x['onay_orani'] = round(x['onayli'] * 100 / x['toplam']) if x['toplam'] else 0
        x['isi'] = {a: isi_seviyesi(v, en_buyuk) for a, v in x['sutunlar'].items()}
    toplam = dict(toplam=sum(x['toplam'] for x in liste), onayli=sum(x['onayli'] for x in liste),
                  bekleyen=sum(x['bekleyen'] for x in liste), sutunlar={b['ad']: b['toplam'] for b in sutun_bilgi})
    toplam['onay_orani'] = round(toplam['onayli'] * 100 / toplam['toplam']) if toplam['toplam'] else 0
    donem = dict(kod=f.get('donem'), ad=DONEM_ADLARI.get(f.get('donem'), ''), tarih1=f.get('tarih1') or '', tarih2=f.get('tarih2') or '',
                 etiket=donem_etiketi(f))
    return dict(satirlar=liste, sutunlar=[b['ad'] for b in sutun_bilgi], sutun_bilgi=sutun_bilgi, toplam=toplam,
                kisi_sayisi=len(liste), kayit_sayisi=toplam['toplam'], donem=donem, projeler=projeler,
                grup_adi=GRUP_ADLARI.get(grup, ''), sutun_adi=SUTUN_ADLARI.get(sutun, ''), en_buyuk_hucre=en_buyuk,
                kategori=kategori, kategori_adi=kategori_gorunen)


def api_gorunumu(ozet, filtre):
    """API yanıtı: P1 yapısı + 'filtre' yankısı (arayüze özgü alanlar çıkarılır)."""
    satirlar = [dict(personel=x['personel'], bos=x['bos'], toplam=x['toplam'], onayli=x['onayli'], bekleyen=x['bekleyen'],
                     onay_orani=x['onay_orani'], sutunlar=dict(x['sutunlar'])) for x in ozet['satirlar']]
    return dict(satirlar=satirlar, sutunlar=list(ozet['sutunlar']), toplam=dict(ozet['toplam']), kisi_sayisi=ozet['kisi_sayisi'],
                kayit_sayisi=ozet['kayit_sayisi'], donem=dict(ozet['donem']),
                filtre=dict(proje=filtre.get('proje') or None, projeler=list(ozet['projeler']), donem=filtre.get('donem'),
                            durum=filtre.get('durum'), grup=filtre.get('grup'), sutun=filtre.get('sutun'),
                            kategori=(ozet.get('kategori_adi') or None),
                            tarih1=filtre.get('tarih1') or None, tarih2=filtre.get('tarih2') or None))


def guvenli_hucre(v):
    """Excel/CSV formül enjeksiyonuna karşı: =, +, -, @, sekme veya satır başı ile başlayan metne kesme işareti eklenir."""
    if isinstance(v, str):
        v = ''.join(ch for ch in v if ch in '\t\n\r' or ord(ch) >= 32)
        if v.startswith(('=', '+', '-', '@', '\t', '\r')):
            v = "'" + v
    return v


def tablo_satirlari(ozet):
    """Çıktı dosyaları için başlık + satırlar + toplam satırı (sayılar sayı olarak)."""
    baslik = [ozet['grup_adi'], 'Toplam', 'Onaylı', 'Bekleyen', 'Onay %'] + list(ozet['sutunlar'])
    satirlar = [[guvenli_hucre(x['personel']), x['toplam'], x['onayli'], x['bekleyen'], x['onay_orani']] +
                [x['sutunlar'][a] for a in ozet['sutunlar']] for x in ozet['satirlar']]
    t = ozet['toplam']
    toplam = ['Toplam', t['toplam'], t['onayli'], t['bekleyen'], t['onay_orani']] + [t['sutunlar'][a] for a in ozet['sutunlar']]
    return [guvenli_hucre(b) for b in baslik], satirlar, toplam
