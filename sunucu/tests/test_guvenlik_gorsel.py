# -*- coding: utf-8 -*-
"""Güvenlik turu v2.3.0 — görsel önbelleği: boyut/yaş sınırları, temizlik, indirme boyutu.

Kapsanan bulgular: girdi_veri #2 (Gyazo ve küçük resim önbellekleri sınırsız büyüyor),
altyapi #12 (data/tmp/gyazo disk doluluğu). Ağ yok; requests sahte nesneyle taklit edilir.
"""
import io
import os
import shutil
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from app import gorsel, settings
from test_web import web, seed, login  # noqa: F401  (web fixture'ı bu modülde kullanılır)

MB = 1024 * 1024
HEX = '0123456789abcdef'


def kimlik(n):
    """n sayısından 32 hex Gyazo kimliği üretir."""
    return '%032x' % n


def png_bytes(color=(200, 10, 10), size=(16, 16)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, 'PNG')
    return buf.getvalue()


def sahte(dizin, ad, boyut, yas_sn):
    """Önbellek klasörüne verilen boyutta ve yaşta (mtime geçmişe alınmış) sahte dosya yazar."""
    yol = Path(dizin) / ad
    yol.write_bytes(b'x' * boyut)
    eski = time.time() - yas_sn
    os.utime(yol, (eski, eski))
    return yol


def gorsel_dosyalari(dizin):
    return [p for p in Path(dizin).iterdir() if p.is_file() and not p.is_symlink() and gorsel._ONBELLEK_GORSEL_RX.match(p.name)]


@pytest.fixture
def cozucu(tmp_path):
    media = tmp_path / 'gorseller'; media.mkdir()
    arsiv = tmp_path / 'telegram_gorseller'; arsiv.mkdir()
    ayar = {'BOT_KLASOR': str(tmp_path), 'GORSEL_KLASOR': str(media), 'ARSIV_KLASOR': str(arsiv),
            'EK_GORSEL_KLASORLERI': [str(arsiv)], 'ONBELLEK': str(tmp_path / 'tmp'), 'GYAZO_PROXY': '1',
            'GYAZO_ONBELLEK_MB': 1, 'GYAZO_ONBELLEK_GUN': 30, 'KUCUK_ONBELLEK_MB': 1}
    return gorsel.GorselCozucu(ayar, ayar['ONBELLEK']), ayar


# ------------------------------------------------------------------ ayarlar
def test_ayarlar_gecersiz_degerde_varsayilan_kullanir(monkeypatch):
    for ad, kotu in (('GYAZO_ONBELLEK_MB', 'abc'), ('GYAZO_ONBELLEK_GUN', ''), ('KUCUK_ONBELLEK_MB', '12abc')):
        monkeypatch.setenv(ad, kotu)
    a = settings.settings()
    assert (a['GYAZO_ONBELLEK_MB'], a['GYAZO_ONBELLEK_GUN'], a['KUCUK_ONBELLEK_MB']) == (500, 30, 300)
    monkeypatch.setenv('GYAZO_ONBELLEK_MB', ' 250 '); monkeypatch.setenv('GYAZO_ONBELLEK_GUN', '-7'); monkeypatch.setenv('KUCUK_ONBELLEK_MB', '1e400')
    a = settings.settings()
    assert (a['GYAZO_ONBELLEK_MB'], a['GYAZO_ONBELLEK_GUN'], a['KUCUK_ONBELLEK_MB']) == (250, 0, 300)
    # Mevcut anahtarlar ve değerleri yerinde.
    assert a['MAX_GORSEL_BYTES'] == 10 * MB and a['SAYFA_BOYU'] == 48 and 'PROJELER' in a and 'ONBELLEK' in a
    assert settings._tam_sayi('OLMAYAN_ANAHTAR_X', 7) == 7
    # GorselCozucu da AYAR'daki bozuk/eksik değere dayanıklı; 0 = sınır yok.
    assert gorsel._onbellek_siniri({'GYAZO_ONBELLEK_MB': 'bozuk'}, 'GYAZO_ONBELLEK_MB', MB) == 500 * MB
    assert gorsel._onbellek_siniri({}, 'KUCUK_ONBELLEK_MB', MB) == 300 * MB
    assert gorsel._onbellek_siniri({'GYAZO_ONBELLEK_GUN': 0}, 'GYAZO_ONBELLEK_GUN', 86400) == 0
    assert gorsel._onbellek_siniri({'GYAZO_ONBELLEK_GUN': -3}, 'GYAZO_ONBELLEK_GUN', 86400) == 0
    c = gorsel.GorselCozucu({'BOT_KLASOR': str(settings.DATA), 'GYAZO_ONBELLEK_MB': '2', 'KUCUK_ONBELLEK_MB': None}, str(settings.DATA / 'tmp'))
    assert c.gyazo_sinir_bayt == 2 * MB and c.kucuk_sinir_bayt == 300 * MB and c.gyazo_yas_sn == 30 * 86400


# ------------------------------------------------------------------ boyut sınırı
def test_boyut_siniri_asilinca_en_eskiler_silinir_ve_sinir_altina_inilir(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor)
    # 12 x 100 KB = 1,2 MB > 1 MB sınırı; 0 numaralı en eski, 11 numaralı en yeni (hepsi 1 saatten eski)
    yollar = [sahte(g, kimlik(i) + ('.jpg' if i % 2 else '.png'), 100 * 1024, 7200 + (12 - i) * 60) for i in range(12)]
    yabanci = sahte(g, 'tanimsiz.bin', 100 * 1024, 99999)             # bu modülün üretmediği ad: dokunulmaz
    taze = g / (kimlik(99) + '.jpg'); taze.write_bytes(b'y' * 100 * 1024)  # az önce yazıldı: silinmez
    rapor = c.onbellek_temizle(zorla=True)['gyazo']
    # 1,3 MB görsel → %90 hedefi 0,9 MB: en eski 4 dosya gider, 0,9 MB kalır
    assert rapor['silinen'] == 4 and rapor['silinen_bayt'] == 400 * 1024
    assert [p.exists() for p in yollar] == [False] * 4 + [True] * 8
    assert yabanci.exists() and taze.exists()
    assert sum(p.stat().st_size for p in gorsel_dosyalari(g)) <= int(0.9 * MB)
    assert rapor['dosya'] == 14 and rapor['kalan_dosya'] == 10 and rapor['kalan_bayt'] == 10 * 100 * 1024
    # Sınır altındayken hiçbir şey silinmez; 0 = sınır yok
    assert c.onbellek_temizle(zorla=True)['gyazo']['silinen'] == 0
    c.gyazo_sinir_bayt = 0
    for i in range(20, 40):
        sahte(g, kimlik(i) + '.jpg', 100 * 1024, 7200)
    assert c.onbellek_temizle(zorla=True)['gyazo']['silinen'] == 0 and len(gorsel_dosyalari(g)) == 29
    # Küçük resim önbelleği de aynı kuralla (AYAR: KUCUK_ONBELLEK_MB=1)
    t = Path(c.thumbs)
    for i in range(15):
        sahte(t, kimlik(i) + '.jpg', 100 * 1024, 7200 + i)
    rapor = c.onbellek_temizle(zorla=True)['thumbs']
    assert rapor['silinen'] == 6 and sum(p.stat().st_size for p in gorsel_dosyalari(t)) <= int(0.9 * MB)
    assert not (t / (kimlik(14) + '.jpg')).exists() and (t / (kimlik(0) + '.jpg')).exists()


# ------------------------------------------------------------------ yaş sınırı, .yok ve yarım dosyalar
def test_yas_siniri_yok_isaretleri_ve_yarim_kalan_dosyalar(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor); t = Path(c.thumbs)
    eski = sahte(g, kimlik(1) + '.jpg', 10, 31 * 86400)
    yeni = sahte(g, kimlik(2) + '.jpg', 10, 29 * 86400)
    yok_eski = sahte(g, kimlik(3) + '.yok', 5, gorsel.GYAZO_OLUMSUZ_SN + 5)
    yok_yeni = sahte(g, kimlik(4) + '.yok', 5, 10)
    part_eski = sahte(g, 'gyazo-abc123.part', 1000, 2 * 3600)
    tmp_eski = sahte(g, 'gyazo-def456.tmp', 1000, 2 * 3600)
    part_yeni = sahte(g, 'gyazo-ghi789.part', 1000, 60)
    thumb_tmp = sahte(t, 'thumb-xyz.tmp', 1000, 2 * 3600)
    thumb_eski = sahte(t, kimlik(5) + '.jpg', 10, 400 * 86400)  # küçük resimde yaş sınırı yok
    rapor = c.onbellek_temizle(zorla=True)
    assert not eski.exists() and yeni.exists()
    assert not yok_eski.exists() and yok_yeni.exists()
    assert not part_eski.exists() and not tmp_eski.exists() and part_yeni.exists()
    assert not thumb_tmp.exists() and thumb_eski.exists()
    assert rapor['gyazo']['silinen'] == 4 and rapor['thumbs']['silinen'] == 1
    # Yaş sınırı 0 = kapalı
    c.gyazo_yas_sn = 0
    cok_eski = sahte(g, kimlik(6) + '.jpg', 10, 900 * 86400)
    c.onbellek_temizle(zorla=True)
    assert cok_eski.exists()


# ------------------------------------------------------------------ LRU: okunan dosya korunur
def test_okunan_dosya_lru_ile_korunur(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor)
    c.gyazo_sinir_bayt = 1500
    a_yol = sahte(g, kimlik(0xa) + '.jpg', 1000, 5 * 3600)  # en eski ama okunacak
    b_yol = sahte(g, kimlik(0xb) + '.jpg', 1000, 4 * 3600)
    assert c._gyazo_onbellek(kimlik(0xa)) == str(a_yol)  # okuma mtime'ı günceller (saatte en fazla bir kez)
    assert time.time() - a_yol.stat().st_mtime < 60
    rapor = c.onbellek_temizle(zorla=True)['gyazo']
    assert a_yol.exists() and not b_yol.exists() and rapor['silinen'] == 1
    # Son bir saat içinde zaten dokunulmuş dosyaya tekrar utime yapılmaz (ucuz).
    m = a_yol.stat().st_mtime
    os.utime(a_yol, (m - 100, m - 100))
    c._gyazo_onbellek(kimlik(0xa))
    assert abs(a_yol.stat().st_mtime - (m - 100)) < 1
    # utime hatası yutulur
    gorsel._dokun(str(g / 'olmayan.jpg'))
    assert c._gyazo_onbellek(kimlik(0xb)) is None
    # Boş (0 bayt) dosya önbellek vuruşu sayılmaz
    (g / (kimlik(0xc) + '.jpg')).write_bytes(b'')
    assert c._gyazo_onbellek(kimlik(0xc)) is None


# ------------------------------------------------------------------ sembolik bağ: önbellek dışına çıkılmaz
def test_sembolik_bag_ile_onbellek_disina_cikilmaz_ve_kullanici_verisine_dokunulmaz(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor); arsiv = Path(a['ARSIV_KLASOR']); kok = Path(a['BOT_KLASOR'])
    c.gyazo_sinir_bayt = 10
    kullanici = arsiv / 'kanit.jpg'; kullanici.write_bytes(b'k' * 5000)
    cok_eski = time.time() - 400 * 86400; os.utime(kullanici, (cok_eski, cok_eski))
    (g / (kimlik(1) + '.jpg')).symlink_to(kullanici)   # önbellek içinde dışa işaret eden bağ
    (g / (kimlik(2) + '.png')).symlink_to(arsiv)       # klasöre bağ
    gercek = sahte(g, kimlik(3) + '.jpg', 5000, 7200)
    rapor = c.onbellek_temizle(zorla=True)['gyazo']
    assert kullanici.exists() and kullanici.stat().st_size == 5000      # kullanıcı verisi yerinde
    assert (g / (kimlik(1) + '.jpg')).is_symlink() and (g / (kimlik(2) + '.png')).is_symlink()  # bağlara dokunulmadı
    assert not gercek.exists() and rapor['silinen'] == 1 and rapor['dosya'] == 1
    # thumbs klasörünün kendisi kullanıcı arşivine bağlanmışsa temizlik atlanır
    shutil.rmtree(c.thumbs); os.symlink(arsiv, c.thumbs)
    hedef = sahte(arsiv, kimlik(4) + '.jpg', 5000, 7200); c.kucuk_sinir_bayt = 10
    rapor = c.onbellek_temizle(zorla=True)
    assert 'atlandi' in rapor['thumbs'] and hedef.exists()
    # Önbellek kökü dışındaki herhangi bir klasöre bağ da atlanır
    disari = kok / 'baska'; disari.mkdir()
    dis_dosya = sahte(disari, kimlik(5) + '.jpg', 5000, 7200)
    os.unlink(c.thumbs); os.symlink(disari, c.thumbs)
    rapor = c.onbellek_temizle(zorla=True)
    assert 'atlandi' in rapor['thumbs'] and dis_dosya.exists()
    assert c.onbellek_durumu()['thumbs']['dosya'] == 1  # durum yine okunur, silmez
    # Doğrudan kontrol: kökün kendisi ve görsel kökleri asla temizlenecek dizin değildir
    assert gorsel._onbellek_dizini_guvenli(c.gyazo_klasor, c.onbellek, c.kokler)
    assert not gorsel._onbellek_dizini_guvenli(c.onbellek, c.onbellek, c.kokler)
    assert not gorsel._onbellek_dizini_guvenli(a['GORSEL_KLASOR'], c.onbellek, c.kokler)
    assert not gorsel._onbellek_dizini_guvenli(str(arsiv), c.onbellek, c.kokler)
    assert not gorsel._onbellek_dizini_guvenli(str(kok / 'tmp' / 'olmayan'), c.onbellek, c.kokler)
    # tmp kökünün TAMAMI başka diske bağlanmışsa (ikisi birlikte çözülür) temizlik çalışır
    disk2 = kok / 'disk2'; disk2.mkdir()
    os.symlink(disk2, kok / 'tmp2')
    c2 = gorsel.GorselCozucu(dict(a, ONBELLEK=str(kok / 'tmp2')), str(kok / 'tmp2'))
    c2.gyazo_sinir_bayt = 10
    buyuk = sahte(c2.gyazo_klasor, kimlik(6) + '.jpg', 5000, 7200)
    assert c2.onbellek_temizle(zorla=True)['gyazo']['silinen'] == 1 and not buyuk.exists()
    # Önbellek görsel kökünün İÇİNE kurulmuşsa (yanlış yapılandırma) hiç silinmez
    c3 = gorsel.GorselCozucu(dict(a, ONBELLEK=str(arsiv / 'tmp')), str(arsiv / 'tmp'))
    c3.gyazo_sinir_bayt = 10
    icerde = sahte(c3.gyazo_klasor, kimlik(7) + '.jpg', 5000, 7200)
    rapor = c3.onbellek_temizle(zorla=True)
    assert 'atlandi' in rapor['gyazo'] and 'atlandi' in rapor['thumbs'] and icerde.exists()


# ------------------------------------------------------------------ eşzamanlılık
def test_eszamanli_temizlik_ve_yarisan_silmeler_hata_vermez(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor); c.gyazo_sinir_bayt = 20 * 1024
    for i in range(300):
        sahte(g, kimlik(i) + '.jpg', 1024, 7200 + i)
    hatalar = []

    def temizle():
        try:
            for _ in range(5):
                c.onbellek_temizle(zorla=True)
                c._temizlik_zaman = 0; c._temizlik_gerekirse()
        except Exception as e:  # pragma: no cover - başarısızlık yolu
            hatalar.append(e)

    def karistir(n):
        try:
            for k in range(150):
                yol = g / (kimlik(1000 + n * 1000 + k) + '.jpg'); yol.write_bytes(b'z' * 1024)
                eski = time.time() - 7200; os.utime(yol, (eski, eski))
                try:
                    os.unlink(g / (kimlik(k) + '.jpg'))
                except FileNotFoundError:
                    pass
                c._gyazo_onbellek(kimlik(1000 + n * 1000 + k))
        except Exception as e:  # pragma: no cover
            hatalar.append(e)

    isler = [threading.Thread(target=temizle) for _ in range(4)] + [threading.Thread(target=karistir, args=(n,)) for n in range(3)]
    for t in isler:
        t.start()
    for t in isler:
        t.join(60)
    assert not hatalar and not any(t.is_alive() for t in isler)
    # Okunan (dokunulan) dosyalar taze sayılır ve korunur; hepsini eskitince tek tarama sınırın altına iner.
    for p in gorsel_dosyalari(g):
        eski = time.time() - 7200; os.utime(p, (eski, eski))
    c.onbellek_temizle(zorla=True)
    assert sum(p.stat().st_size for p in gorsel_dosyalari(g)) <= int(20 * 1024 * 0.9)
    # Kilit başkasındayken zorlanmayan çağrı beklemez, None döner
    with c._temizlik_kilit:
        assert c.onbellek_temizle() is None


def test_silme_ve_tarama_hatalari_yutulur(cozucu, monkeypatch):
    c, a = cozucu
    g = Path(c.gyazo_klasor); c.gyazo_sinir_bayt = 10
    sahte(g, kimlik(0xa) + '.jpg', 1000, 7200); sahte(g, kimlik(0xb) + '.jpg', 1000, 7200)

    def unlink(yol, *k, **kw):
        if str(yol).endswith(kimlik(0xa) + '.jpg'):
            raise FileNotFoundError(yol)   # yarışta başka iş parçacığı sildi
        raise PermissionError(yol)

    monkeypatch.setattr(gorsel.os, 'unlink', unlink)
    rapor = c.onbellek_temizle(zorla=True)['gyazo']
    assert rapor['silinen'] == 0 and 'hata' not in rapor and rapor['dosya'] == 2
    monkeypatch.undo()
    # Beklenmedik hata temizlikte kalır, isteği düşürmez; rapor hatayı adlandırır
    monkeypatch.setattr(gorsel, '_onbellek_buda', lambda *k, **kw: (_ for _ in ()).throw(RuntimeError('disk')))
    rapor = c.onbellek_temizle(zorla=True)
    assert rapor['gyazo'] == {'hata': 'RuntimeError'} and rapor['thumbs'] == {'hata': 'RuntimeError'}
    kaynak = Path(a['GORSEL_KLASOR']) / 'k.png'; kaynak.write_bytes(png_bytes())
    c._temizlik_zaman = 0
    assert c.kucuk({'anahtar': 'k'}, str(kaynak))  # küçük resim yine üretilir
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xa)}) == str(g / (kimlik(0xa) + '.jpg'))  # önbellek vuruşu
    c._http = SahteOturum([]); c._temizlik_zaman = 0
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0x1)}) is None and (g / (kimlik(0x1) + '.yok')).is_file()


# ------------------------------------------------------------------ durum
def test_onbellek_durumu_dosya_sayisi_ve_boyut(cozucu):
    c, a = cozucu
    d = c.onbellek_durumu()
    assert d['gyazo']['dosya'] == 0 and d['thumbs']['bayt'] == 0 and d['toplam_bayt'] == 0 and d['son_temizlik'] is None
    assert d['gyazo']['sinir_mb'] == 1 and d['gyazo']['yas_gun'] == 30 and d['thumbs']['sinir_mb'] == 1 and d['thumbs']['yas_gun'] == 0
    assert d['gyazo']['dizin'] == c.gyazo_klasor and d['thumbs']['dizin'] == c.thumbs
    sahte(c.gyazo_klasor, kimlik(1) + '.jpg', 3000, 10); sahte(c.gyazo_klasor, kimlik(2) + '.yok', 5, 10); sahte(c.thumbs, kimlik(3) + '.jpg', 2000, 10)
    d = c.onbellek_durumu()
    assert d['gyazo']['dosya'] == 2 and d['gyazo']['bayt'] == 3005 and d['gyazo']['mb'] == round(3005 / MB, 2)
    assert d['gyazo']['doluluk_yuzde'] == round(100.0 * 3005 / MB, 1)
    assert d['thumbs']['dosya'] == 1 and d['thumbs']['bayt'] == 2000
    assert d['toplam_bayt'] == 5005 and d['toplam_mb'] == round(5005 / MB, 2)
    c.onbellek_temizle(zorla=True)
    d = c.onbellek_durumu()
    assert d['son_temizlik'] and d['son_temizlik_raporu']['gyazo']['dosya'] == 2 and d['son_temizlik_raporu']['gyazo']['silinen'] == 0
    # Modül düzeyi kısayol (panel/CLI için) ve sınırsız (0) klasörde doluluk yüzdesi yok
    m = gorsel.onbellek_durumu(dict(a, KUCUK_ONBELLEK_MB=0))
    assert m['thumbs']['doluluk_yuzde'] is None and m['thumbs']['sinir_mb'] == 0 and m['gyazo']['dosya'] == 2
    # Klasör silinmişse hata yerine sıfır
    shutil.rmtree(c.thumbs)
    assert c.onbellek_durumu()['thumbs']['dosya'] == 0


# ------------------------------------------------------------------ indirme boyutu sınırı (requests sahte)
class SahteYanit:
    def __init__(self, status=200, headers=None, govde=b'', parca_sayisi=None):
        self.status_code = status; self.headers = headers or {}; self._govde = govde; self._parca = parca_sayisi; self.okunan = 0

    def iter_content(self, n):
        if self._parca is not None:  # Content-Length olmayan uzun akış
            for _ in range(self._parca):
                self.okunan += 1
                yield b'\xff' * n
            return
        for i in range(0, len(self._govde), n):
            self.okunan += 1
            yield self._govde[i:i + n]

    def close(self):
        pass


class SahteOturum:
    def __init__(self, yanitlar):
        self.yanitlar = list(yanitlar); self.istekler = []

    def get(self, url, **kw):
        self.istekler.append(url)
        assert kw.get('stream') is True and kw.get('allow_redirects') is False
        return self.yanitlar.pop(0)


def test_indirme_boyut_siniri_ve_yarim_dosya_kalmaz(cozucu, monkeypatch):
    c, a = cozucu
    g = Path(c.gyazo_klasor)
    monkeypatch.setattr(gorsel, 'GYAZO_MAX_BYTES', 256 * 1024)
    gecici = lambda: [p for p in g.iterdir() if p.suffix in ('.jpg', '.png', '.part', '.tmp')]
    # 1) Content-Length sınırın üstünde: gövde hiç okunmaz, önbelleğe yazılmaz, olumsuz işaret konur
    buyuk = SahteYanit(headers={'Content-Length': str(300 * 1024), 'Content-Type': 'image/jpeg'}, parca_sayisi=100)
    c._http = SahteOturum([buyuk])
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xa)}) is None
    assert buyuk.okunan == 0 and (g / (kimlik(0xa) + '.yok')).is_file() and not gecici()
    assert c._http.istekler == ['https://i.gyazo.com/' + kimlik(0xa) + '.jpg']
    # 2) Content-Length yok, akış sınırı aşıyor: sınırdan hemen sonra kesilir, yazılmaz
    sonsuz = SahteYanit(headers={'Content-Type': 'image/jpeg'}, parca_sayisi=10000)
    c._http = SahteOturum([sonsuz])
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xb)}) is None
    assert sonsuz.okunan <= 256 * 1024 // 65536 + 1 and (g / (kimlik(0xb) + '.yok')).is_file() and not gecici()
    # 3) Yanıltıcı küçük Content-Length ile uzun gövde de akış sayacına takılır
    yalanci = SahteYanit(headers={'Content-Length': '100', 'Content-Type': 'image/jpeg'}, parca_sayisi=10000)
    c._http = SahteOturum([yalanci])
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xc)}) is None and yalanci.okunan <= 5 and not gecici()
    # 4) Sınır içinde geçerli PNG: önbelleğe yazılır, .part kalmaz, süreç başı temizliği bir kez çalışmış olur
    veri = png_bytes()
    c._http = SahteOturum([SahteYanit(headers={'Content-Length': str(len(veri)), 'Content-Type': 'image/png'}, govde=veri)])
    yol = c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xd)})
    assert yol == str(g / (kimlik(0xd) + '.png')) and Path(yol).read_bytes() == veri
    assert not list(g.glob('gyazo-*')) and c._son_temizlik is not None
    # 5) İkinci çağrı ağa gitmez; ağ hatası da yutulur
    c._http = SahteOturum([])
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xd)}) == yol and c._http.istekler == []
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xe)}) is None  # pop boş listeden → yutulur, .yok yazılır
    assert (g / (kimlik(0xe) + '.yok')).is_file()
    # 6) Yazım hatasında geçici dosya kalmaz (klasör yazılamaz)
    sahte_mkstemp = lambda **kw: (_ for _ in ()).throw(OSError('disk dolu'))
    monkeypatch.setattr(gorsel.tempfile, 'mkstemp', sahte_mkstemp)
    c._http = SahteOturum([SahteYanit(headers={'Content-Length': str(len(veri)), 'Content-Type': 'image/png'}, govde=veri)])
    assert c.gyazo_indir({'link': 'https://gyazo.com/' + kimlik(0xf)}) is None and not list(g.glob('gyazo-*'))


# ------------------------------------------------------------------ zaman eşiği ve küçük resim tetiği
def test_temizlik_zaman_esigi_ve_kucuk_resim_tetigi(cozucu):
    c, a = cozucu
    t = Path(c.thumbs); c.kucuk_sinir_bayt = 50 * 1024
    for i in range(10):
        sahte(t, kimlik(i) + '.jpg', 10 * 1024, 7200 + i)   # 100 KB > 50 KB
    kaynak = Path(a['GORSEL_KLASOR']) / 'k.png'; kaynak.write_bytes(png_bytes())
    assert c._temizlik_zaman == 0
    thumb = c.kucuk({'anahtar': 'k1'}, str(kaynak))   # ilk kullanım: süreç başı temizliği
    assert thumb and Path(thumb).is_file() and c._temizlik_zaman > 0
    kalan = [p for p in t.iterdir() if p.name != Path(thumb).name]
    assert len(kalan) == 4 and sum(p.stat().st_size for p in kalan) <= int(50 * 1024 * 0.9)
    # 10 dakika dolmadan tekrar tarama yapılmaz (ucuz)
    buyuk = sahte(t, kimlik(50) + '.jpg', 60 * 1024, 7200)
    assert c.onbellek_temizle() is None and buyuk.exists()
    c.kucuk({'anahtar': 'k1'}, str(kaynak)); assert buyuk.exists()
    c._temizlik_zaman -= gorsel.ONBELLEK_TEMIZLIK_ARALIGI_SN
    assert c.onbellek_temizle() is not None and not buyuk.exists() and Path(thumb).is_file()


def test_gyazo_kaynakli_kucuk_resim_yeniden_uretilmez_ve_okunan_dokunulur(cozucu):
    c, a = cozucu
    g = Path(c.gyazo_klasor)
    kaynak = g / (kimlik(0xd) + '.png'); kaynak.write_bytes(png_bytes())
    eski = time.time() - 5 * 3600; os.utime(kaynak, (eski, eski))
    thumb = c.kucuk({'anahtar': 'x'}, str(kaynak)); assert thumb
    ino = os.stat(thumb).st_ino
    os.utime(thumb, (eski, eski))              # küçük resim eski görünsün
    c._gyazo_onbellek(kimlik(0xd))             # kaynağa LRU dokunuşu: mtime şimdi
    assert os.stat(kaynak).st_mtime > eski + 3000
    assert c.kucuk({'anahtar': 'x'}, str(kaynak)) == thumb
    assert os.stat(thumb).st_ino == ino                    # yeniden üretilmedi (aynı inode)
    assert time.time() - os.stat(thumb).st_mtime < 60      # okunan küçük resme dokunuldu
    # Yerel (değişebilir) kaynakta eski davranış korunur: kaynak yenilenirse küçük resim yeniden üretilir
    yerel = Path(a['GORSEL_KLASOR']) / 'y.png'; yerel.write_bytes(png_bytes((1, 2, 3)))
    t2 = c.kucuk({'anahtar': 'y'}, str(yerel)); ino2 = os.stat(t2).st_ino
    os.utime(t2, (eski, eski)); yerel.write_bytes(png_bytes((4, 5, 6)))
    assert c.kucuk({'anahtar': 'y'}, str(yerel)) == t2 and os.stat(t2).st_ino != ino2


# ------------------------------------------------------------------ web katmanı: istek temizliği tetikler
def test_web_kucuk_istegi_temizligi_tetikler_ve_yanit_bozulmaz(web):
    from app import panel
    c, a = web; login(c); kid = seed(a)
    t = Path(a['ONBELLEK']) / 'thumbs'; coz = panel.COZUCU
    coz.kucuk_sinir_bayt = 30 * 1024
    for i in range(6):
        sahte(t, kimlik(i) + '.jpg', 10 * 1024, 7200 + i)   # 60 KB > 30 KB
    r = c.get(f'/kucuk/{kid}')
    assert r.status_code == 200 and r.headers['Content-Type'].startswith('image/jpeg')
    sahteler = [p for p in t.iterdir() if p.name in {kimlik(i) + '.jpg' for i in range(6)}]
    assert len(sahteler) == 2 and {p.name for p in sahteler} == {kimlik(0) + '.jpg', kimlik(1) + '.jpg'}
    d = coz.onbellek_durumu()
    assert d['thumbs']['dosya'] == 3 and d['son_temizlik'] and d['toplam_bayt'] > 0
    assert c.get(f'/kucuk/{kid}').status_code == 200 and c.get(f'/gorsel/{kid}').status_code == 200
