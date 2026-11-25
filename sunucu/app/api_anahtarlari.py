"""2.3.2 — API anahtarları: üretme, saklama (yalnız sha256 özeti), doğrulama, iptal, istek günlüğü ve hız sınırı.

Anahtar biçimi: ``kp_`` + 40 rastgele harf/rakam. Düz anahtar yalnız oluşturma anında bir kez gösterilir; veritabanında
özet (sha256 hex) ve tanıma için ilk 8 rastgele karakter (``onek``) tutulur."""
import hashlib
import hmac
import json
import math
import re
import secrets
import string
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta

from . import db

ONEK = 'kp_'
_ALFABE = string.ascii_letters + string.digits
ANAHTAR_RX = re.compile(r'^kp_[A-Za-z0-9]{40}$')
PROJE_RX = re.compile(r'^[A-Z0-9_]{1,24}$')
GUNLUK_SAKLAMA_GUN = 90  # api_gunlugu satırları bu kadar gün tutulur
GUNLUK_BUDAMA_ARALIGI_SN = 3600  # budama süreç başına en çok saatte bir (ilk yazmada hemen)
_SON_BUDAMA = -1e9


def uret():
    """(düz anahtar, önek, özet) döndürür."""
    govde = ''.join(secrets.choice(_ALFABE) for _ in range(40))
    anahtar = ONEK + govde
    return anahtar, govde[:8], ozet(anahtar)


def ozet(anahtar):
    return hashlib.sha256(str(anahtar).encode('utf-8')).hexdigest()


def _bugun():
    return date.today().isoformat()


def projeleri_coz(deger):
    """Saklanan kapsam: '*' (tüm projeler, sonradan eklenenler dahil) ya da JSON liste. Bozuk değer → boş liste (fail-closed)."""
    if deger == '*':
        return None
    try:
        liste = json.loads(deger or '[]')
    except (TypeError, ValueError):
        return []
    if not isinstance(liste, list):
        return []
    return [p for p in liste if isinstance(p, str) and PROJE_RX.fullmatch(p)]


def kapsam_projeleri(anahtar, tum_projeler):
    """Anahtarın erişebildiği proje kodları (liste). '*' ise o anki tüm projeler."""
    secili = projeleri_coz(anahtar['projeler'])
    if secili is None:
        return [p for p in tum_projeler if PROJE_RX.fullmatch(p)], True
    return [p for p in secili], False


def durum(anahtar, bugun=None):
    if anahtar['iptal']:
        return 'iptal'
    if anahtar['son_kullanma'] and anahtar['son_kullanma'] < (bugun or _bugun()):
        return 'suresi_doldu'
    return 'etkin'


def olustur(conn, ad, projeler, *, yalniz_onayli=True, sql_izni=False, gorsel_izni=False, son_kullanma=None,
            olusturan, ip=None, tanimli_projeler=None):
    """Yeni anahtar. ``projeler``: '*' ya da kod listesi. (id, düz anahtar) döndürür; geçersiz girdide ValueError."""
    ad = db.metin_temizle(ad or '', 80).replace('\n', ' ').strip()
    if not ad:
        raise ValueError('Anahtar için bir ad yazın (ör. "Rapor sunucusu").')
    if projeler == '*':
        saklanan = '*'
    else:
        liste = list(dict.fromkeys(str(p).strip().upper() for p in (projeler or []) if str(p).strip()))
        if not liste:
            raise ValueError('En az bir proje seçin ya da "Tüm projeler"i işaretleyin.')
        if any(not PROJE_RX.fullmatch(p) for p in liste) or (tanimli_projeler is not None and any(p not in tanimli_projeler for p in liste)):
            raise ValueError('Seçilen projelerden biri tanımlı değil.')
        saklanan = json.dumps(sorted(liste))
    if son_kullanma:
        son_kullanma = str(son_kullanma).strip()[:10]
        try:
            datetime.strptime(son_kullanma, '%Y-%m-%d')
        except ValueError:
            raise ValueError('Son kullanma tarihi YYYY-AA-GG biçiminde olmalı.')
        if son_kullanma < _bugun():
            raise ValueError('Son kullanma tarihi bugünden önce olamaz.')
    else:
        son_kullanma = None
    anahtar, onek, oz = uret()
    with db.transaction(conn):
        kid = conn.execute('INSERT INTO api_anahtarlari(ad,onek,ozet,projeler,yalniz_onayli,sql_izni,gorsel_izni,son_kullanma,olusturan,olusturma) '
                           'VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (ad, onek, oz, saklanan, 1 if yalniz_onayli else 0, 1 if sql_izni else 0, 1 if gorsel_izni else 0,
                            son_kullanma, olusturan, db.simdi())).lastrowid
        db.denetim_yaz(conn, olusturan, 'api_anahtar_olustur', ip=ip, hedef_turu='api_anahtari', hedef_id=kid,
                       yeni={'ad': ad, 'onek': ONEK + onek, 'projeler': saklanan, 'yalniz_onayli': int(bool(yalniz_onayli)),
                             'sql_izni': int(bool(sql_izni)), 'gorsel_izni': int(bool(gorsel_izni)), 'son_kullanma': son_kullanma})
    return kid, anahtar


def iptal(conn, kid, eden, ip=None):
    with db.transaction(conn):
        row = conn.execute('SELECT * FROM api_anahtarlari WHERE id=?', (kid,)).fetchone()
        if not row:
            raise ValueError('Anahtar bulunamadı.')
        if row['iptal']:
            return False
        conn.execute('UPDATE api_anahtarlari SET iptal=1,iptal_eden=?,iptal_zamani=? WHERE id=?', (eden, db.simdi(), kid))
        db.denetim_yaz(conn, eden, 'api_anahtar_iptal', ip=ip, hedef_turu='api_anahtari', hedef_id=kid,
                       eski={'ad': row['ad'], 'onek': ONEK + row['onek']})
    return True


def listele(conn):
    bugun = _bugun()
    sonuc = []
    for row in conn.execute('SELECT * FROM api_anahtarlari ORDER BY iptal, id DESC'):
        d = {k: row[k] for k in row.keys() if k != 'ozet'}
        d['durum'] = durum(row, bugun)
        d['proje_listesi'] = projeleri_coz(row['projeler'])
        sonuc.append(d)
    return sonuc


def son_gunluk(conn, adet=50):
    return [dict(r) for r in conn.execute(
        'SELECT g.*,a.ad AS anahtar_ad,a.onek AS anahtar_onek FROM api_gunlugu g LEFT JOIN api_anahtarlari a ON a.id=g.anahtar_id '
        'ORDER BY g.id DESC LIMIT ?', (adet,))]


def dogrula(conn, ham):
    """Bearer değerini doğrular. (anahtar satırı | None, neden) döndürür; neden: 'yok'|'bicim'|'gecersiz'|'iptal'|'suresi_doldu'|''."""
    if not ham:
        return None, 'yok'
    if not ANAHTAR_RX.fullmatch(ham):
        return None, 'bicim'
    hesap = ozet(ham)
    row = conn.execute('SELECT * FROM api_anahtarlari WHERE ozet=?', (hesap,)).fetchone()
    # Özetler sabit zamanlı karşılaştırılır (indeks araması özet üzerinde; düz anahtar hiçbir yerde karşılaştırılmaz).
    if not row or not hmac.compare_digest(str(row['ozet']), hesap):
        return None, 'gecersiz'
    neden = durum(row)
    if neden != 'etkin':
        return None, neden
    return dict(row), ''


def gunluk_yaz(conn, anahtar_id, uc, ip, durum_kodu, sure_ms, satir):
    with db.transaction(conn):
        conn.execute('INSERT INTO api_gunlugu(anahtar_id,zaman,uc,ip,durum,sure_ms,satir) VALUES(?,?,?,?,?,?,?)',
                     (anahtar_id, db.simdi(), str(uc or '')[:200], str(ip or '')[:45], durum_kodu, sure_ms, satir))
        if anahtar_id:
            conn.execute('UPDATE api_anahtarlari SET son_kullanim=?,son_ip=?,istek_sayisi=istek_sayisi+1 WHERE id=?',
                         (db.simdi(), str(ip or '')[:45], anahtar_id))
    # 2.3.2-inc: budama rastgele değil, süreç başına en çok saatte bir ve 5000 satırlık partilerle (tek istek uzun kilitlenmez).
    global _SON_BUDAMA
    simdi_sn = time.monotonic()
    if simdi_sn - _SON_BUDAMA >= GUNLUK_BUDAMA_ARALIGI_SN:
        _SON_BUDAMA = simdi_sn
        esik = (datetime.now() - timedelta(days=GUNLUK_SAKLAMA_GUN)).strftime('%Y-%m-%d %H:%M:%S')
        try:
            for _ in range(20):
                with db.transaction(conn):
                    n = conn.execute('DELETE FROM api_gunlugu WHERE id IN (SELECT id FROM api_gunlugu WHERE zaman<? ORDER BY zaman LIMIT 5000)',
                                     (esik,)).rowcount
                if n < 5000:
                    break
        except Exception:
            pass


class HizSiniri:
    """Süreç içi kayan 60 sn pencere. Anahtar özeti (ya da IP) başına; iş parçacığı güvenli."""

    def __init__(self, pencere=60.0):
        self.pencere = pencere
        self._kilit = threading.Lock()
        self._kayit = {}

    def dene(self, kimlik, sinir, simdi=None):
        """(izin_var_mi, retry_after_sn)."""
        simdi = time.monotonic() if simdi is None else simdi
        with self._kilit:
            if len(self._kayit) > 5000:
                for k in [k for k, q in self._kayit.items() if not q or simdi - q[-1] >= self.pencere]:
                    del self._kayit[k]
            kuyruk = self._kayit.setdefault(kimlik, deque())
            while kuyruk and simdi - kuyruk[0] >= self.pencere:
                kuyruk.popleft()
            if len(kuyruk) >= sinir:
                return False, max(1, math.ceil(self.pencere - (simdi - kuyruk[0])))
            kuyruk.append(simdi)
            return True, 0

    def sifirla(self):
        with self._kilit:
            self._kayit.clear()
