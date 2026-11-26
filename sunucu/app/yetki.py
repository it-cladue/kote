"""Kanonik sahip / süperadmin veya açık, sonlu proje izinleri. Hatalı kural fail-closed.

2.4.0: 'sahip' (sistem sahibi) süperadminin üstündedir: admin=True + sahip=True. Süperadminleri, API anahtarlarını ve
erişim (IP) sınırını yalnız sahip yönetir. Saklanan metin tam olarak 'sahip'tir (eş anlamlılar kanonikle()'de çevrilir)."""
import re

EYLEMLER = ('oku', 'gorsel', 'kt', 'duzenle', 'sil')
TAM = set(EYLEMLER)
_CODE = re.compile(r'^[A-Z0-9_]{1,24}$')
_ROL_KODLARI = ('ADMIN', 'SUPERADMIN', 'SAHIP', 'OWNER')
SAHIP_ES_ANLAMLILAR = ('sahip', 'owner', 'sistem sahibi', 'sistem_sahibi')

# Yalnız sahibin açabileceği uç noktalar (Flask endpoint adları). panel.before() her istekte bakar; panel.sahip_gerekli
# süsleyicisi kullanıldığı ucu buraya kendiliğinden ekler. Başka modüller kendi uçlarını bu kümeye ekleyebilir.
SAHIP_GEREKLI_EYLEMLER = set()


def _bos(gecerli=True):
    return {'admin': False, 'sahip': False, 'hepsi': None, 'projeler': {}, 'gecerli': gecerli}


def coz(metin):
    result = _bos()
    raw = str(metin or '')
    if not raw:
        return result
    if raw == 'admin':
        result.update(admin=True, hepsi=set(TAM))
        return result
    if raw == 'sahip':
        result.update(admin=True, sahip=True, hepsi=set(TAM))
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
                if not _CODE.fullmatch(code) or code in _ROL_KODLARI:
                    raise ValueError('Geçersiz proje veya rol.')
                result['projeler'].setdefault(code, set()).update(allowed)
    except (ValueError, TypeError):
        return _bos(False)
    return result


def _sade(metin):
    """Rol adı karşılaştırması: Türkçe büyük harfler, büyük-küçük harf ve fazla boşluk önemsizdir."""
    return ' '.join(str(metin or '').replace('İ', 'i').replace('I', 'i').replace('ı', 'i').casefold().split())


def kanonikle(metin, projeler=None):
    # 'superadmin' / 'süperadmin' (büyük-küçük harf fark etmez) 'admin'in eş anlamlısıdır; arayüz ve CLI yardımı süperadmin der.
    # 2.4.0: 'sahip' / 'owner' / 'sistem sahibi' → 'sahip'.
    sade = _sade(metin)
    if sade in ('superadmin', 'süperadmin'):
        metin = 'admin'
    elif sade in SAHIP_ES_ANLAMLILAR:
        metin = 'sahip'
    parsed = coz(metin)
    if not parsed['gecerli'] or (not parsed['admin'] and not parsed['projeler']):
        raise ValueError('Geçerli rol ve en az bir açık proje izni seçin. * veya admin: biçimi kullanılamaz.')
    if parsed['sahip']:
        return 'sahip'
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


def _yk(yk_veya_metin):
    return coz(yk_veya_metin) if yk_veya_metin is None or isinstance(yk_veya_metin, str) else yk_veya_metin


def sahip_mi(yk_veya_metin):
    return bool(_yk(yk_veya_metin).get('sahip'))


def yonetici_mi(yk_veya_metin):
    """Süperadmin ya da sahip (admin=True)."""
    return bool(_yk(yk_veya_metin).get('admin'))


def rol_kodu(metin):
    """'sahip' | 'superadmin' | 'proje' — Kullanıcılar sayfası ve onay kuralları için."""
    parsed = coz(metin)
    return 'sahip' if parsed['sahip'] else 'superadmin' if parsed['admin'] else 'proje'


ROL_ADLARI = {'sahip': 'Sahip', 'superadmin': 'Süperadmin', 'proje': 'Proje kullanıcısı'}


def rol_etiketi(yk):
    """Başlıktaki rol etiketi; kişinin gerçek yetkisinden türetilir (herkese aynı metin yazılmaz)."""
    yk = yk or {}
    if yk.get('sahip'):
        return 'Sahip'
    if yk.get('admin'):
        return 'Süperadmin'
    projeler = yk.get('projeler') or {}
    if any('kt' in a for a in projeler.values()):
        return 'Takım lideri'
    if any('duzenle' in a for a in projeler.values()):
        return 'Düzenleyici'
    return 'Görüntüleyici'


def ozet(metin):
    parsed = coz(metin)
    if parsed['sahip']:
        return 'Sahip — her şey, süperadminleri ve API anahtarlarını yönetir'
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
    codes = [p for p in codes if _CODE.fullmatch(p) and p not in _ROL_KODLARI]
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
