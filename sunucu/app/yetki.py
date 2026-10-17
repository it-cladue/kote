"""Kanonik süperadmin veya açık, sonlu proje izinleri. Hatalı kural fail-closed."""
import re

EYLEMLER = ('oku', 'gorsel', 'kt', 'duzenle', 'sil')
TAM = set(EYLEMLER)
_CODE = re.compile(r'^[A-Z0-9_]{1,24}$')


def coz(metin):
    result = {'admin': False, 'hepsi': None, 'projeler': {}, 'gecerli': True}
    raw = str(metin or '')
    if not raw:
        return result
    if raw == 'admin':
        result.update(admin=True, hepsi=set(TAM))
        return result
    try:
        if raw.strip() != raw or len(raw) > 5000:
            raise ValueError('Kanonik olmayan yetki.')
        for group in re.split(r'[;\s]+', raw):
            if not group:
                continue
            if ':' in group:
                codes, actions = group.split(':', 1)
                actions = actions.split(',')
                if not actions or any(a not in TAM for a in actions):
                    raise ValueError('Geçersiz eylem.')
                allowed = set(actions)
                if 'oku' in allowed:
                    allowed.add('gorsel')
            else:
                codes, allowed = group, set(TAM)
            for code in codes.split(','):
                code = code.upper()
                if not _CODE.fullmatch(code) or code in ('ADMIN', 'SUPERADMIN'):
                    raise ValueError('Geçersiz proje veya rol.')
                result['projeler'].setdefault(code, set()).update(allowed)
    except (ValueError, TypeError):
        return {'admin': False, 'hepsi': None, 'projeler': {}, 'gecerli': False}
    return result


def kanonikle(metin, projeler=None):
    parsed = coz(metin)
    if not parsed['gecerli'] or (not parsed['admin'] and not parsed['projeler']):
        raise ValueError('Geçerli rol ve en az bir açık proje izni seçin. * veya admin: biçimi kullanılamaz.')
    if parsed['admin']:
        return 'admin'
    if projeler is not None and any(p not in projeler for p in parsed['projeler']):
        raise ValueError('Seçilen projelerden biri tanımlı değil.')
    return ';'.join(p + ':' + ','.join(a for a in EYLEMLER if a in actions)
                    for p, actions in sorted(parsed['projeler'].items()))


def izin(yk, proje, eylem):
    if yk.get('admin'):
        return True
    actions = yk.get('projeler', {}).get(str(proje or '').upper(), set())
    return bool('oku' in actions and eylem in actions)


def izinli_projeler(yk, tum_projeler):
    return [p for p in tum_projeler if izin(yk, p, 'oku')]


def ozet(metin):
    parsed = coz(metin)
    if parsed['admin']:
        return 'Süperadmin — tüm projeler ve yönetim'
    if not parsed['gecerli']:
        return 'Geçersiz eski yetki; projeleri yeniden seçin'
    return '; '.join(p + ': ' + ('tam' if a == TAM else ', '.join(x for x in EYLEMLER if x in a))
                     for p, a in sorted(parsed['projeler'].items())) or 'Proje yetkisi yok'


def eski_wildcardlari_sabitle(conn, codes):
    """Eski açık '*' niyetini yalnız geçiş anındaki projelere çevirir; yeni proje açılmaz."""
    from . import db
    if db.ayar_al(conn, 'rol_gecis_21') == '1':
        return
    codes = [p for p in codes if _CODE.fullmatch(p) and p not in ('ADMIN', 'SUPERADMIN')]
    for user in conn.execute('SELECT kullanici_adi,yetki FROM panel_kullanicilari').fetchall():
        match = re.fullmatch(r'\*(?::([a-z_,]+))?', user['yetki'] or '')
        if not match:
            continue
        actions = set((match.group(1) or ','.join(EYLEMLER)).split(','))
        if not actions.issubset(TAM):
            continue
        if 'oku' in actions:
            actions.add('gorsel')
        explicit = ';'.join(p + ':' + ','.join(a for a in EYLEMLER if a in actions) for p in codes)
        conn.execute('UPDATE panel_kullanicilari SET yetki=?,session_version=session_version+1 WHERE kullanici_adi=?',
                     (explicit, user['kullanici_adi']))
        db.denetim_yaz(conn, 'sunucu-gecis', 'yetki_kanonik', anahtar=user['kullanici_adi'], eski='*', yeni=explicit,
                       hedef_turu='hesap', hedef_id=user['kullanici_adi'])
    db.ayar_yaz(conn, 'rol_gecis_21', '1')
