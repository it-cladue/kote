"""Kişisel bildirim geçmişi. Eski bildirimler de kaydın güncel projesine göre korunur."""
from datetime import datetime
from . import db


def _base(username, allowed):
    if not allowed:
        return "SELECT NULL id,NULL key,NULL tur,NULL proje,NULL kayit_id,NULL zaman,0 okundu,NULL kim,NULL metin,NULL personel,NULL kategori,NULL tarih,NULL ekleyen_ad,0 kt WHERE 0", []
    places = ','.join('?' for _ in allowed)
    sql = f'''SELECT b.id,'kayit:'||b.id key,'kanit' tur,k.proje,k.id kayit_id,b.zaman,b.okundu,
              COALESCE(k.ekleyen_ad,'') kim,'Yeni kanıt eklendi' metin,k.personel,k.kategori,k.tarih,k.ekleyen_ad,k.kt
              FROM bildirimler b JOIN kayitlar k ON k.id=b.kayit_id
              WHERE b.kullanici_adi=? AND k.proje IN ({places})
              UNION ALL
              SELECT b.id,'mesaj:'||b.id key,b.tur,k.proje,k.id kayit_id,b.zaman,b.okundu,
              b.kim,COALESCE(b.metin,'') metin,k.personel,k.kategori,k.tarih,k.ekleyen_ad,k.kt
              FROM mesaj_bildirimleri b JOIN kayitlar k ON k.id=b.kayit_id
              WHERE b.kullanici_adi=? AND k.proje IN ({places})'''
    return sql, [username, *allowed, username, *allowed]


def liste(conn, username, allowed, filters=None, page_size=30):
    filters = filters or {}
    sql, params = _base(username, allowed)
    where = ['1=1']
    values = []
    status = filters.get('durum', 'hepsi')
    if status not in ('hepsi', 'okunmamis', 'okundu'):
        raise ValueError('Geçersiz bildirim durumu.')
    if status != 'hepsi':
        where.append('okundu=?')
        values.append(1 if status == 'okundu' else 0)
    project = filters.get('proje', '')
    if project:
        if project not in allowed:
            raise PermissionError('Proje kapsamı dışında.')
        where.append('proje=?'); values.append(project)
    kind = str(filters.get('tur', ''))[:40]
    if kind:
        where.append('tur=?'); values.append(kind)
    dates = {}
    for key, op, tail in (('tarih1', '>=', ' 00:00:00'), ('tarih2', '<=', ' 23:59:59')):
        value = filters.get(key, '')
        if value:
            try:
                datetime.strptime(value, '%Y-%m-%d')
            except ValueError:
                raise ValueError('Geçersiz tarih.') from None
            where.append('zaman ' + op + ' ?'); values.append(value + tail)
        dates[key] = value
    if dates['tarih1'] and dates['tarih2'] and dates['tarih1'] > dates['tarih2']:
        raise ValueError('Başlangıç tarihi bitişten sonra olamaz.')
    try:
        page = max(1, min(1000000, int(filters.get('s', '1'))))
    except (ValueError, TypeError):
        raise ValueError('Geçersiz sayfa.') from None
    clause = ' AND '.join(where)
    total = conn.execute('SELECT COUNT(*) FROM (' + sql + ') WHERE ' + clause, [*params, *values]).fetchone()[0]
    rows = [dict(r) for r in conn.execute('SELECT * FROM (' + sql + ') WHERE ' + clause + ' ORDER BY zaman DESC,key DESC LIMIT ? OFFSET ?',
                                          [*params, *values, page_size, (page - 1) * page_size])]
    count = conn.execute('SELECT COUNT(*) toplam,SUM(okundu=0) okunmamis,SUM(okundu=1) okundu FROM (' + sql + ')', params).fetchone()
    counts = {key: count[key] or 0 for key in count.keys()}
    types = [r[0] for r in conn.execute('SELECT DISTINCT tur FROM (' + sql + ') ORDER BY tur', params)]
    return dict(bildirimler=rows, toplam=total, sayfa=page, sayfa_sayisi=max(1, (total + page_size - 1) // page_size),
                counts=counts, turler=types, filters=dict(durum=status, proje=project, tur=kind, **dates))


def okundu(conn, username, allowed, identifiers=None, all_visible=False):
    if not allowed:
        return 0
    identifiers = identifiers or []
    if len(identifiers) > 200:
        raise ValueError('Çok fazla bildirim seçildi.')
    parsed = {'bildirimler': [], 'mesaj_bildirimleri': []}
    for identifier in identifiers:
        value = str(identifier)
        table = 'bildirimler'
        if ':' in value:
            prefix, value = value.split(':', 1)
            if prefix in ('m', 'mesaj'):
                table = 'mesaj_bildirimleri'
            elif prefix not in ('kayit', 'k'):
                raise ValueError('Geçersiz bildirim.')
        if not value.isdigit() or int(value) < 1:
            raise ValueError('Geçersiz bildirim.')
        parsed[table].append(int(value))
    places = ','.join('?' for _ in allowed)
    changed = 0
    with db.transaction(conn):
        for table, ids in parsed.items():
            if not all_visible and not ids:
                continue
            params = [username, *allowed]
            clause = f'''kullanici_adi=? AND okundu=0 AND EXISTS
                        (SELECT 1 FROM kayitlar k WHERE k.id={table}.kayit_id AND k.proje IN ({places}))'''
            if not all_visible:
                clause += ' AND id IN (' + ','.join('?' for _ in ids) + ')'; params.extend(ids)
            changed += conn.execute('UPDATE ' + table + ' SET okundu=1 WHERE ' + clause, params).rowcount
        if changed:
            db.denetim_yaz(conn, username, 'bildirim_okundu', yeni={'adet': changed}, hedef_turu='bildirim')
    return changed
