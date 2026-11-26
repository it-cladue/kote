"""2.3.5 — Kategori temizliği: kayıtlardaki serbest ``kategori`` yazımlarını katalogdaki kategori adlarında birleştirir.

Kural (sistemin geri kalanıyla aynı):
- Bot yeni kayda ``kategori`` = katalogdaki *görünen ad* (label), ``kategori_code`` = katalog kodu yazar (bot.py). Kayıtlar süzgeci,
  personel raporu ve API ``kategori`` metnini harf duyarsız (``casefold``) ve baş/son boşluksuz karşılaştırır; kod sütununu okumaz.
  Bu yüzden birleştirme ``kategori``'yi hedef kategorinin görünen adına, ``kategori_code``'u da kategorinin koduna çeker (bot
  kayıtlarıyla aynı biçim). ``kategori_mode`` ve soru/cevap anlık görüntüsü tarihî bilgi olduğu için değişmez.
- Gruplama anahtarı: ``TRIM(kategori)`` (yalnız boşluk; SQL TRIM ile aynı) + ``casefold``. NULL ve '' aynı "(boş)" grubudur.
- Silinmiş kayıtlar da dönüştürülür (geri alınınca tutarlı kalsınlar) ama ayrı sayılır.
- Önizleme hiçbir şey yazmaz. Uygulama tek transaction (BEGIN IMMEDIATE) içinde planı yeniden hesaplar; önizlemedeki ``damga``
  (etkilenecek kayıt kimliklerinin özeti) değiştiyse hiçbir şey yazmadan reddeder. Değişen her grup için İşlem Geçmişi'ne bir
  ``kategori_birlestir`` satırı yazılır. Aynı dönüşümü ikinci kez uygulamak hiçbir satırı değiştirmez (idempotent).
- Geri alma: yalnız yedekten (``deploy/kanit-yedek.sh --geri-yukle``). Uygulamadan önce yedek alın."""
import hashlib
import json

from . import db, katalog

BOS_HEDEF = '__bos__'      # "(boş) yap"
BOS_AD = '(boş)'
ISLEM = 'kategori_birlestir'
PARCA = 400                # UPDATE ... WHERE id IN (...) parça boyu


class Cakisma(Exception):
    """Önizlemeden sonra etkilenecek kayıtlar değişti; uygulama yapılmadı."""


def anahtar(deger):
    """Gruplama anahtarı: baş/son boşluk (yalnız ' ', SQL TRIM gibi) atılır, harf duyarsız (casefold)."""
    return str(deger or '').strip(' ').casefold()


def _ham(deger):
    if deger is None:
        return ''
    if isinstance(deger, bytes):
        return deger.decode('utf-8', 'replace')
    return deger if isinstance(deger, str) else str(deger)


def _katalog_haritasi(conn):
    """anahtar(görünen ad) → kategori. Aynı adlı birden çok kategori varsa etkin olan önceliklidir."""
    harita = {}
    for k in sorted(katalog.list_categories(conn, active_only=False), key=lambda x: (not x['aktif'], x['code'])):
        harita.setdefault(anahtar(k['label']), k)
    return harita


def hedefler(conn):
    """'Şuna dönüştür' seçenekleri: etkin katalog kategorileri (görünen ada göre sıralı)."""
    return sorted(({'code': k['code'], 'label': k['label']} for k in katalog.list_categories(conn, active_only=True)),
                  key=lambda x: (x['label'].casefold(), x['code']))


def gruplar(conn):
    """Kayıtlardaki her farklı kategori değeri, normalleştirilmiş anahtar altında gruplanmış olarak.

    Her grup: anahtar, gorunen, bos, yazimlar [{deger, adet, silinen}], toplam/onayli/bekleyen (silinmemiş), silinen, hepsi
    (silinmişler dahil), projeler [{proje, adet}] (silinmemiş), katalog (eşleşen kategori ya da None), kod_onerisi,
    varsayilan (önerilen hedef kodu; '' = değiştirme), duzgun (bütün yazımlar katalog adıyla birebir aynı)."""
    harita = _katalog_haritasi(conn)
    kod_harita = {k['code'].casefold(): k for k in katalog.list_categories(conn, active_only=True)}
    out = {}
    for r in conn.execute('SELECT kategori,proje,kt,silindi,COUNT(*) n FROM kayitlar GROUP BY kategori,proje,kt,silindi'):
        ham = _ham(r['kategori'])
        a = anahtar(ham)
        grp = out.setdefault(a, dict(anahtar=a, bos=not a, yazimlar={}, toplam=0, onayli=0, bekleyen=0, silinen=0, hepsi=0, projeler={}))
        y = grp['yazimlar'].setdefault(ham, dict(deger=ham, adet=0, silinen=0))
        n = r['n']
        y['adet'] += n; grp['hepsi'] += n
        if r['silindi']:
            y['silinen'] += n; grp['silinen'] += n
        else:
            grp['toplam'] += n
            if r['kt']:
                grp['onayli'] += n
            else:
                grp['bekleyen'] += n
            grp['projeler'][r['proje']] = grp['projeler'].get(r['proje'], 0) + n
    liste = []
    for a, grp in out.items():
        yazimlar = sorted(grp['yazimlar'].values(), key=lambda y: (-y['adet'], y['deger']))
        grp['yazimlar'] = yazimlar
        grp['gorunen'] = yazimlar[0]['deger'].strip(' ') if a else BOS_AD
        grp['projeler'] = [dict(proje=p, adet=n) for p, n in sorted(grp['projeler'].items(), key=lambda x: (-x[1], str(x[0])))]
        k = harita.get(a) if a else None
        grp['katalog'] = dict(code=k['code'], label=k['label'], aktif=bool(k['aktif'])) if k else None
        oneri = kod_harita.get(a) if a and not k else None
        grp['kod_onerisi'] = dict(code=oneri['code'], label=oneri['label']) if oneri else None
        grp['varsayilan'] = k['code'] if k and k['aktif'] else ''
        grp['duzgun'] = bool(k) and all(y['deger'] == k['label'] for y in yazimlar)
        liste.append(grp)
    liste.sort(key=lambda x: (x['bos'], -x['hepsi'], x['anahtar']))
    return liste


def donusum_coz(ciftler):
    """[(eski, yeni)] → {anahtar: hedef}. ``yeni``: kategori kodu ya da görünen adı, BOS_HEDEF / '(boş)' = boş yap,
    '' = değiştirme (atlanır). ``eski`` '(boş)' ise boş grup. Aynı gruba iki farklı hedef verilirse ValueError."""
    out = {}
    for eski, yeni in ciftler:
        yeni = str(yeni or '').strip()
        if not yeni:
            continue
        eski = '' if str(eski or '').strip() in (BOS_AD, BOS_HEDEF) else eski
        a = anahtar(eski)
        if a in out and out[a] != yeni:
            raise ValueError('Aynı değer için iki farklı hedef verildi: ' + (str(eski) or BOS_AD)[:60] + '.')
        out[a] = yeni
    return out


def _hedef(etkin, yeni):
    """Hedef metni → (görünen ad, kod). BOS_HEDEF → ('', None). Yalnız etkin katalog kategorisi kabul edilir."""
    if yeni in (BOS_HEDEF, BOS_AD):
        return '', None
    for k in etkin:
        if k['code'] == yeni:
            return k['label'], k['code']
    for k in etkin:
        if anahtar(k['label']) == anahtar(yeni):
            return k['label'], k['code']
    raise ValueError('Hedef kategori katalogda etkin değil: ' + str(yeni)[:60] + '. Önce katalogda ekleyin ya da etkinleştirin.')


def plan(conn, donusumler):
    """Kuru çalıştırma: hiçbir şey yazmaz. donusumler: {anahtar: hedef}.

    Dönüş: dict(kalemler=[...], toplam_degisecek, toplam_silinen, damga). Her kalem: anahtar, gorunen, hedef_ad, hedef_kod,
    hedef_gorunen, grup_adet, degisecek, degisecek_silinen, degisecek_onayli, degisecek_bekleyen, yazimlar {ham: adet}
    (yalnız değişecekler) ve iç kullanım için _idler."""
    etkin = katalog.list_categories(conn, active_only=True)
    kalemler = {}
    for a, yeni in donusumler.items():
        ad, kod = _hedef(etkin, yeni)
        kalemler[a] = dict(anahtar=a, gorunen=BOS_AD if not a else None, hedef_ad=ad, hedef_kod=kod, hedef_gorunen=ad or BOS_AD,
                           grup_adet=0, degisecek=0, degisecek_silinen=0, degisecek_onayli=0, degisecek_bekleyen=0, yazimlar={}, _idler=[])
    if kalemler:
        for r in conn.execute('SELECT id,kategori,kt,silindi FROM kayitlar ORDER BY id'):
            ham = _ham(r['kategori'])
            k = kalemler.get(anahtar(ham))
            if k is None:
                continue
            k['grup_adet'] += 1
            if k['gorunen'] is None:
                k['gorunen'] = ham.strip(' ')
            if ham == k['hedef_ad']:
                continue  # zaten hedef yazımında (boş grupta NULL ile '' aynı sayılır); kategori_code'una dokunulmaz
            k['degisecek'] += 1; k['_idler'].append(r['id'])
            k['yazimlar'][ham] = k['yazimlar'].get(ham, 0) + 1
            if r['silindi']:
                k['degisecek_silinen'] += 1
            elif r['kt']:
                k['degisecek_onayli'] += 1
            else:
                k['degisecek_bekleyen'] += 1
    liste = sorted(kalemler.values(), key=lambda k: (-k['degisecek'], k['anahtar']))
    for k in liste:
        if k['gorunen'] is None:
            k['gorunen'] = k['anahtar']  # kayıtlarda artık bu değer yok
    # Damga: değişecek kayıtların kimlikleri ve onaylı/bekleyen/silinmiş dağılımı; önizlemeden sonra biri onaylanır, silinir
    # ya da geri alınırsa da Uygula reddedilir (önizlemede görülen sayılar uygulananla aynı kalsın).
    ozet = [(k['anahtar'], k['hedef_kod'] or '', k['hedef_ad'], k['_idler'],
             k['degisecek_onayli'], k['degisecek_bekleyen'], k['degisecek_silinen']) for k in liste]
    damga = hashlib.sha256(json.dumps(ozet, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()[:20]
    return dict(kalemler=liste, toplam_degisecek=sum(k['degisecek'] for k in liste),
                toplam_silinen=sum(k['degisecek_silinen'] for k in liste), damga=damga)


def disa(p):
    """JSON çıktısı için iç alanları (_idler) atar."""
    return dict(p, kalemler=[{a: b for a, b in k.items() if not a.startswith('_')} for k in p['kalemler']])


def uygula(conn, donusumler, kim, ip=None, damga=None):
    """Planı tek transaction içinde yeniden hesaplar ve uygular. ``damga`` verildiyse ve değiştiyse Cakisma (hiçbir şey yazılmaz).
    Değişen her grup için bir İşlem Geçmişi satırı yazar. Dönüş: plan + 'uygulanan' (değişen kayıt sayısı)."""
    with db.transaction(conn):
        p = plan(conn, donusumler)
        if damga is not None and str(damga) != p['damga']:
            raise Cakisma('Önizlemeden sonra kayıtlar değişti (yeni kayıt, düzenleme ya da başka bir temizlik). '
                          'Hiçbir şey değiştirilmedi; yeniden önizleyin.')
        zaman = db.simdi(); uygulanan = 0
        for k in p['kalemler']:
            idler = k['_idler']
            if not idler:
                continue
            for i in range(0, len(idler), PARCA):
                parca = idler[i:i + PARCA]
                conn.execute('UPDATE kayitlar SET kategori=?,kategori_code=?,surum=COALESCE(surum,1)+1,guncelleme=? WHERE id IN (%s)'
                             % ','.join('?' * len(parca)), (k['hedef_ad'], k['hedef_kod'], zaman, *parca))
            uygulanan += len(idler)
            eski = ' | '.join('"%s" (%d)' % (ham, n) for ham, n in sorted(k['yazimlar'].items(), key=lambda x: (-x[1], x[0])))
            db.denetim_yaz(conn, kim, ISLEM, eski=eski[:900] or BOS_AD,
                           yeni='%s · %d kayıt (%d silinmiş)' % (k['hedef_gorunen'], k['degisecek'], k['degisecek_silinen']), ip=ip,
                           hedef_turu='kategori', hedef_id=k['hedef_kod'] or BOS_HEDEF,
                           aciklama=json.dumps(dict(eski=k['gorunen'], yazimlar=k['yazimlar'], hedef=k['hedef_ad'], kod=k['hedef_kod'],
                                                    adet=k['degisecek'], silinen=k['degisecek_silinen']), ensure_ascii=False)[:1000])
        if uygulanan:
            db.degisti(conn)
    p['uygulanan'] = uygulanan
    return p


def katalog_sayilari(conn):
    """Katalog sayfası için: kategori kodu → {toplam (silinmemiş), hepsi (silinmişler dahil)}.
    Sayılan kayıtlar: kategori metni bu kategorinin görünen adıyla harf duyarsız (baş/son boşluksuz) eşleşenler."""
    harita = _katalog_haritasi(conn)
    out = {}
    for grp in gruplar(conn):
        k = harita.get(grp['anahtar']) if grp['anahtar'] else None
        if k:
            out[k['code']] = dict(toplam=grp['toplam'], hepsi=grp['hepsi'])
    return out


def tablo_metni(liste):
    """CLI için düz Türkçe tablo."""
    satirlar = ['%-34s %7s %7s %8s %7s  %s' % ('Değer (yazımlar)', 'Toplam', 'Onaylı', 'Bekleyen', 'Silinen', 'Katalog')]
    for g in liste:
        yaz = BOS_AD if g['bos'] else ', '.join('"%s"×%d' % (y['deger'], y['adet']) for y in g['yazimlar'])
        if g['katalog']:
            kat = 'Katalogda var: ' + g['katalog']['label'] + ('' if g['katalog']['aktif'] else ' (pasif)')
        elif g.get('kod_onerisi'):
            kat = 'Kod eşleşmesi: ' + g['kod_onerisi']['label']
        else:
            kat = '—'
        satirlar.append('%-34s %7d %7d %8d %7d  %s' % (yaz[:34], g['toplam'], g['onayli'], g['bekleyen'], g['silinen'], kat))
        if len(yaz) > 34:
            satirlar.append('    ' + yaz)
    return '\n'.join(satirlar)
