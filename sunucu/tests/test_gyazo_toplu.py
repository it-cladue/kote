"""gyazo-onbellekle: kayıtlardaki Gyazo bağlantılarının toplu ön-indirilmesi (2.3.0 son tur)."""
import io
import csv
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from app import db, gorsel

ROOT = Path(__file__).resolve().parents[1]


def kimlik(n):
    return f"{n:032x}"


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


class SahteYanit:
    def __init__(self, status=200, govde=b"", headers=None):
        self.status_code = status
        self.headers = headers or ({"Content-Type": "image/jpeg", "Content-Length": str(len(govde))} if status == 200 else {})
        self._govde = govde

    def iter_content(self, n):
        for i in range(0, len(self._govde), n):
            yield self._govde[i:i + n]

    def close(self):
        pass


class SahteOturum:
    """URL'ye göre sıralı yanıtlar: {kimlik: [yanit, yanit, ...]}; tükenince assert."""

    def __init__(self, plan):
        self.plan = {k: list(v) for k, v in plan.items()}
        self.istekler = []

    def get(self, url, **kw):
        assert kw.get("stream") is True and kw.get("allow_redirects") is False
        self.istekler.append(url)
        kim = url.rsplit("/", 1)[-1].split(".")[0]
        assert self.plan.get(kim), f"beklenmeyen istek: {url}"
        return self.plan[kim].pop(0)


@pytest.fixture
def ortam(tmp_path):
    media = tmp_path / "gorseller"; media.mkdir()
    arsiv = tmp_path / "telegram_gorseller"; arsiv.mkdir()
    ayar = {"BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(media), "ARSIV_KLASOR": str(arsiv),
            "EK_GORSEL_KLASORLERI": [str(arsiv)], "ONBELLEK": str(tmp_path / "tmp"), "GYAZO_PROXY": "1",
            "GYAZO_ONBELLEK_MB": 1, "GYAZO_ONBELLEK_GUN": 0, "KUCUK_ONBELLEK_MB": 1, "DB": str(tmp_path / "data" / "panel.db")}
    (tmp_path / "data").mkdir()
    conn = db.baglan(ayar["DB"])
    satirlar = [
        ("a", "GA", "280", "https://i.gyazo.com/%s.png" % kimlik(1), "gyazo", ""),            # indirilir
        ("b", "GA", "281", "https://gyazo.com/%s" % kimlik(1), "gyazo", ""),                   # aynı kimlik → zaten var
        ("c", "OF", "282", "https://i.gyazo.com/%s.jpg" % kimlik(2), "gyazo", ""),            # 404
        ("d", "OF", "283", "https://i.gyazo.com/%s.jpg" % kimlik(3), "gyazo", ""),            # 429 sonra 200
        ("e", "PA", "284", "https://onedrive.example/x", "onedrive", "https://i.gyazo.com/%s.jpg" % kimlik(4)),  # ikinci görsel gyazo
        ("f", "PA", "285", "https://teamzone.gyazo.com/x/abc", "teamzone", ""),               # aday değil
        ("g", "PP", "286", "https://i.gyazo.com/%s.jpg" % kimlik(5), "gyazo", ""),            # silinmiş → aday değil
    ]
    for anahtar, proje, personel, link, tur, g2 in satirlar:
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link,link_turu,gorsel2,silindi) VALUES(?,?,?,?,?,?,?)",
                     (anahtar, proje, personel, link, tur, g2, 1 if anahtar == "g" else 0))
    conn.commit()
    cozucu = gorsel.GorselCozucu(ayar, ayar["ONBELLEK"])
    return conn, cozucu, ayar


def test_toplu_indirme_indirir_tekrarlari_atlar_ve_raporlar(ortam):
    conn, c, ayar = ortam
    c._http = SahteOturum({kimlik(1): [SahteYanit(200, jpeg())], kimlik(2): [SahteYanit(404)],
                           kimlik(3): [SahteYanit(429), SahteYanit(200, jpeg())], kimlik(4): [SahteYanit(200, jpeg())]})
    uykular = []
    ilerlemeler = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, ilerleme=lambda i, n, s: ilerlemeler.append((i, n)))
    assert (r["baglanti"], r["kimlik"], r["indirilen"], r["zaten_var"], r["acilamayan"], r["kimliksiz"]) == (5, 4, 3, 1, 1, 0)
    assert r["durduruldu"] is None and r["hiz_siniri_bekleme_sn"] == 30 and 30 in uykular
    assert ilerlemeler == [(5, 5)]
    g = Path(c.gyazo_klasor)
    assert (g / (kimlik(1) + ".jpg")).is_file() and (g / (kimlik(3) + ".jpg")).is_file() and (g / (kimlik(4) + ".jpg")).is_file()
    assert not (g / (kimlik(2) + ".jpg")).exists() and (g / (kimlik(2) + ".yok")).is_file()
    # silinmiş kayıt ve teamzone bağlantısı hiç istenmedi
    assert not any(kimlik(5) in u for u in c._http.istekler) and len(c._http.istekler) == 5
    # rapor: yalnız açılamayan, Türkçe sebep, noktalı virgül ayraç
    rapor = Path(r["rapor"])
    assert rapor == Path(ayar["DB"]).parent / "gyazo-acilamayan.csv"
    satirlar = list(csv.reader(rapor.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert satirlar[0] == ["kayit_id", "proje", "personel", "link", "sebep"]
    assert len(satirlar) == 2 and satirlar[1][1:3] == ["OF", "282"] and "404" in satirlar[1][4]
    assert r["onbellek_sinir_mb"] == 1 and r["onbellek_gyazo_mb"] is not None
    # kayıt satırları değişmedi
    assert conn.execute("SELECT COUNT(*) FROM kayitlar WHERE guncelleme IS NOT NULL").fetchone()[0] == 0


def test_ikinci_calistirma_onbellegi_kullanir_ve_olumsuz_isareti_bir_kez_daha_dener(ortam):
    conn, c, ayar = ortam
    c._http = SahteOturum({kimlik(1): [SahteYanit(200, jpeg())], kimlik(2): [SahteYanit(404)],
                           kimlik(3): [SahteYanit(200, jpeg())], kimlik(4): [SahteYanit(200, jpeg())]})
    gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None)
    # ikinci tur: yalnız 404'lü kimlik yeniden istenir (olumsuz işaret taze olsa bile), diğerleri önbellekten
    c._http = SahteOturum({kimlik(2): [SahteYanit(404)]})
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None)
    assert (r["indirilen"], r["zaten_var"], r["acilamayan"]) == (0, 4, 1) and len(c._http.istekler) == 1


def test_surekli_429_durdurur_ve_kaldigi_yeri_soyler(ortam):
    conn, c, ayar = ortam
    c._http = SahteOturum({kimlik(1): [SahteYanit(429)] * 5})
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append)
    assert r["durduruldu"] and "1/5" in r["durduruldu"] and uykular == [30, 60, 120, 300]
    assert r["acilamayan"] == 1 and "429" in r["acilamayan_ornek"][0][4]
    # bir sonraki çalıştırma kaldığı yerden: kimlik 1 bu kez iner
    c._http = SahteOturum({kimlik(1): [SahteYanit(200, jpeg())], kimlik(2): [SahteYanit(404)],
                           kimlik(3): [SahteYanit(200, jpeg())], kimlik(4): [SahteYanit(200, jpeg())]})
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None)
    assert r2["durduruldu"] is None and r2["indirilen"] == 3


def test_gecici_hata_bir_kez_daha_denenir_ve_en_cok_sinirlar(ortam):
    conn, c, ayar = ortam

    class Kopuk(SahteOturum):
        def get(self, url, **kw):
            if len(self.istekler) == 0:
                self.istekler.append(url)
                raise OSError("bağlantı koptu")
            return super().get(url, **kw)

    c._http = Kopuk({kimlik(1): [SahteYanit(200, jpeg())]})
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, en_cok=1, uyku=uykular.append)
    assert (r["baglanti"], r["indirilen"], r["acilamayan"]) == (1, 1, 0) and uykular == [5]
    assert (Path(c.gyazo_klasor) / (kimlik(1) + ".jpg")).is_file()


def test_vekil_kapaliysa_acik_hata(ortam):
    conn, c, ayar = ortam
    c.gyazo_acik = False
    with pytest.raises(ValueError):
        gorsel.gyazo_toplu_indir(conn, c, ayar)


def test_cli_komutu_yardimda_ve_ayristirmada(tmp_path):
    r = subprocess.run([sys.executable, "-m", "app.cli", "gyazo-onbellekle", "--help"], cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)})
    assert r.returncode == 0 and "--en-cok" in r.stdout and "gyazo-acilamayan.csv" in r.stdout
