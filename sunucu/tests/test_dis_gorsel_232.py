"""2.3.2 — Dış görsel servisleri (Snappark, Teamzone): normalizasyon, güvenli indirme, önbellek, panel, toplu kopyalama."""
import csv
import hashlib
import io
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests
from PIL import Image

from app import db, gorsel
from app.excel_oku import link_turu_ve_kimlik
from test_web import web, login  # noqa: F401
from test_kayitlar_v22 import insert
from test_gyazo_toplu import SahteYanit, jpeg, kimlik

ROOT = Path(__file__).resolve().parents[1]
SP_ID = "MduBQ4TiGc"
SP_RAW = "https://img.snappark.net/s/%s/raw/" % SP_ID
TZ_ID = "0123456789abcdef0123456789abcdef"
TZ = "https://teamzone.gyazo.com/" + TZ_ID


def png(renk=(10, 120, 200), boyut=(20, 14)):
    b = io.BytesIO(); Image.new("RGB", boyut, renk).save(b, "PNG"); return b.getvalue()


def sha1(s):
    return hashlib.sha1(s.encode()).hexdigest()


class SahteDis:
    """Yerel sahte Snappark/Gyazo sunucusu: yol = /<host><path> (DIS_GORSEL_TEST_HOST biçimi)."""

    def __init__(self):
        self.hits = []
        self.yollar = {}  # yol -> (durum, başlıklar, gövde)
        dis = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self):
                dis.hits.append(self.path)
                durum, basliklar, govde = dis.yollar.get(self.path, (404, {}, b""))
                self.send_response(durum)
                for k, v in basliklar.items():
                    self.send_header(k, v)
                if "Content-Length" not in basliklar:
                    self.send_header("Content-Length", str(len(govde)))
                self.end_headers()
                if govde:
                    try:
                        self.wfile.write(govde)
                    except OSError:
                        pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def gorsel(self, yol, govde, tur="image/png"):
        self.yollar[yol] = (200, {"Content-Type": tur}, govde)

    def close(self):
        self.server.shutdown(); self.server.server_close()


def ayar_yap(tmp_path, **ek):
    media = tmp_path / "gorseller"; media.mkdir(exist_ok=True)
    arsiv = tmp_path / "telegram_gorseller"; arsiv.mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    a = {"BOT_KLASOR": str(tmp_path), "GORSEL_KLASOR": str(media), "ARSIV_KLASOR": str(arsiv), "EK_GORSEL_KLASORLERI": [str(arsiv)],
         "ONBELLEK": str(tmp_path / "tmp"), "GYAZO_PROXY": "1", "GYAZO_ONBELLEK_MB": 2000, "GYAZO_ONBELLEK_GUN": 0,
         "KUCUK_ONBELLEK_MB": 300, "DB": str(tmp_path / "data" / "panel.db")}
    a.update(ek)
    return a


@pytest.fixture
def sahte():
    s = SahteDis()
    yield s
    s.close()


def _cozucu(sahte, ayar):
    c = gorsel.GorselCozucu(ayar, ayar["ONBELLEK"])
    c.dis_test_host = "127.0.0.1:%d" % sahte.port
    oturum = requests.Session(); oturum.trust_env = False; c._http = oturum
    return c


@pytest.fixture
def coz(sahte, tmp_path):
    a = ayar_yap(tmp_path)
    return _cozucu(sahte, a), a


# ---------------------------------------------------------------- excel_oku.link_turu_ve_kimlik
def test_link_turu_snappark_kimligi_s_parcasi():
    assert link_turu_ve_kimlik(SP_RAW) == ("snappark", SP_ID)
    assert link_turu_ve_kimlik("https://snappark.net/s/%s" % SP_ID) == ("snappark", SP_ID)
    assert link_turu_ve_kimlik("https://www.snappark.net/s/%s/" % SP_ID) == ("snappark", SP_ID)
    assert link_turu_ve_kimlik("https://snappark.net/baska/abc") == ("snappark", "abc")  # /s/ yoksa eski davranış
    # diğer türler değişmedi
    assert link_turu_ve_kimlik(TZ) == ("teamzone", TZ_ID)
    assert link_turu_ve_kimlik("https://gyazo.com/" + TZ_ID) == ("gyazo", TZ_ID)
    assert link_turu_ve_kimlik("") == ("bos", "")


# ---------------------------------------------------------------- normalizasyon
def test_normalizasyon_snappark_ve_teamzone():
    for link in (SP_RAW, "https://img.snappark.net/s/%s/raw" % SP_ID, "https://snappark.net/s/%s" % SP_ID,
                 "http://www.snappark.net/s/%s/" % SP_ID, "  https://IMG.SNAPPARK.NET/s/%s/raw/  " % SP_ID):
        r = gorsel.dis_gorsel_cozumle(link)
        assert r and r["tur"] == "snappark" and r["url"] == SP_RAW and r["anahtar"] == sha1(SP_RAW) and r["adaylar"] == [SP_RAW], link
    for kotu in ("https://snappark.net/x/abc", "https://evilsnappark.net/s/abc", "https://snappark.net.evil.example/s/abc",
                 "ftp://snappark.net/s/abc", "https://snappark.net/s/a/b/c", "https://snappark.net/s/" + "x" * 100, "", None):
        assert gorsel.dis_gorsel_cozumle(kotu) is None, kotu
    r = gorsel.dis_gorsel_cozumle(TZ.upper().replace("HTTPS://TEAMZONE.GYAZO.COM", "https://teamzone.gyazo.com"))
    assert r["tur"] == "teamzone" and r["url"] == TZ and r["anahtar"] == sha1(TZ)
    assert r["adaylar"] == ["https://i.gyazo.com/%s.png" % TZ_ID, "https://i.gyazo.com/%s.jpg" % TZ_ID, TZ]
    assert gorsel.dis_gorsel_cozumle("https://teamzone.gyazo.com/x/abc") is None
    assert gorsel.dis_gorsel_cozumle("https://teamzone.gyazo.com.evil.example/" + TZ_ID) is None


def test_test_hostu_yalniz_loopback(tmp_path):
    for deger, beklenen in (("127.0.0.1:18701", "127.0.0.1:18701"), ("localhost:18702", "localhost:18702"),
                            ("10.0.0.5:80", None), ("evil.example:80", None), ("", None), ("127.0.0.1", None)):
        c = gorsel.GorselCozucu(ayar_yap(tmp_path, DIS_GORSEL_TEST_HOST=deger), str(tmp_path / "tmp"))
        assert c.dis_test_host == beklenen, deger
    c = gorsel.GorselCozucu(ayar_yap(tmp_path), str(tmp_path / "tmp"))
    assert c.dis_test_host is None and not c._dis_izinli("snappark")("http://127.0.0.1:1/x")
    assert c._dis_izinli("snappark")(SP_RAW) and c._dis_izinli("teamzone")("https://i.gyazo.com/a.png")
    assert not c._dis_izinli("snappark")("https://i.gyazo.com/a.png")  # host listeleri türe özel


# ---------------------------------------------------------------- indirme
def test_snappark_indirir_onbellekler_ve_tekrar_istemez(coz, sahte):
    c, a = coz
    govde = png()
    sahte.gorsel("/img.snappark.net/s/%s/raw/" % SP_ID, govde)
    kayit = {"link": "https://snappark.net/s/%s" % SP_ID, "anahtar": "k1"}
    assert c.dis_mumkun(kayit) == "snappark"
    yol = c.dis_indir(kayit)
    assert yol == os.path.join(a["ONBELLEK"], "dis", sha1(SP_RAW) + ".png") and Path(yol).read_bytes() == govde
    assert sahte.hits == ["/img.snappark.net/s/%s/raw/" % SP_ID]
    assert c.gorsel_yolu({"link": SP_RAW, "anahtar": "k2"}) == (yol, "snappark") and len(sahte.hits) == 1
    assert not list(Path(c.dis_klasor).glob("*.part"))
    # ikinci görsel alanı da çözülür
    assert c.dis_mumkun({"link": "", "gorsel2": SP_RAW, "_gorsel2": True}) == "snappark"
    # küçük resim dış önbellekten üretilir
    k = c.kucuk({"anahtar": "k1"}, yol)
    assert k and Path(k).is_file() and Path(k).parent == Path(c.thumbs)


def test_teamzone_yedek_sirasi_png_404_sonra_jpg(coz, sahte):
    c, a = coz
    sahte.gorsel("/i.gyazo.com/%s.jpg" % TZ_ID, jpeg(), "image/jpeg")
    yol = c.dis_indir({"link": TZ})
    assert yol and yol.endswith(sha1(TZ) + ".jpg")
    assert sahte.hits == ["/i.gyazo.com/%s.png" % TZ_ID, "/i.gyazo.com/%s.jpg" % TZ_ID]


def test_teamzone_sayfasi_html_ise_reddedilir_ve_olumsuz_isaret(coz, sahte):
    c, a = coz
    sahte.yollar["/teamzone.gyazo.com/" + TZ_ID] = (200, {"Content-Type": "text/html; charset=utf-8"}, b"<html>giris</html>")
    assert c.dis_indir({"link": TZ}) is None and c._dis_son_durum == "gorsel_degil"
    assert len(sahte.hits) == 3
    isaret = Path(c.dis_klasor) / (sha1(TZ) + ".yok")
    assert isaret.is_file() and c.dis_mumkun({"link": TZ}) is None
    assert c.dis_indir({"link": TZ}) is None and len(sahte.hits) == 3  # 10 dk içinde yeniden denenmez
    eski = time.time() - 700; os.utime(isaret, (eski, eski))
    sahte.gorsel("/teamzone.gyazo.com/" + TZ_ID, png())  # sayfa artık görsel döndürüyor (son aday)
    assert c.dis_mumkun({"link": TZ}) == "teamzone"
    assert c.dis_indir({"link": TZ}) and not isaret.exists() and len(sahte.hits) == 6


def test_izinsiz_host_ve_yonlendirme_reddi(coz, sahte):
    c, a = coz
    yol = "/img.snappark.net/s/%s/raw/" % SP_ID
    sahte.yollar[yol] = (302, {"Location": "http://evil.example/x.png"}, b"")
    assert c.dis_indir({"link": SP_RAW}) is None and sahte.hits == [yol]
    # izinli olmayan host taşıyan bağlantı hiç çözülmez, istek atılmaz
    for link in ("https://snappark.evil.example/s/abc/raw/", "https://example.com/s/abc/raw/", "https://i.gyazo.com/" + TZ_ID + ".png"):
        assert c.dis_cozum({"link": link}) is None and c.dis_indir({"link": link}) is None
    assert sahte.hits == [yol]
    # test hostu yokken loopback'e yönlenen bağlantı reddedilir
    c2 = gorsel.GorselCozucu(a, a["ONBELLEK"]); c2._http = c._http
    assert not c2._dis_izinli("snappark")("http://127.0.0.1:%d/x" % sahte.port)


def test_yonlendirme_siniri_ve_goreli_yonlendirme(coz, sahte):
    c, a = coz
    yol = "/img.snappark.net/s/%s/raw/" % SP_ID
    sahte.yollar[yol] = (302, {"Location": yol}, b"")  # kendine sonsuz yönlendirme
    assert c.dis_indir({"link": SP_RAW}) is None and c._dis_son_durum == "yonlendirme" and len(sahte.hits) == 5
    sid = "Baska123"
    y2 = "/img.snappark.net/s/%s/raw/" % sid
    sahte.yollar[y2] = (301, {"Location": "dosya.png"}, b"")  # göreli yönlendirme aynı hosta
    sahte.gorsel("/img.snappark.net/s/%s/raw/dosya.png" % sid, png())
    assert c.dis_indir({"link": "https://snappark.net/s/" + sid})


def test_boyut_siniri_ve_bozuk_gorsel(coz, sahte, monkeypatch):
    c, a = coz
    sahte.yollar["/img.snappark.net/s/Buyuk1/raw/"] = (200, {"Content-Type": "image/png", "Content-Length": str(50 * 1024 * 1024)}, b"")
    assert c.dis_indir({"link": "https://snappark.net/s/Buyuk1"}) is None and c._dis_son_durum == "buyuk"
    monkeypatch.setattr(gorsel, "DIS_MAX_BYTES", 1000)
    sahte.yollar["/img.snappark.net/s/Akis1/raw/"] = (200, {"Content-Type": "image/png"}, png(boyut=(400, 400)) + b"\0" * 5000)
    assert c.dis_indir({"link": "https://snappark.net/s/Akis1"}) is None and c._dis_son_durum == "buyuk"
    monkeypatch.setattr(gorsel, "DIS_MAX_BYTES", 20 * 1024 * 1024)
    sahte.gorsel("/img.snappark.net/s/Bozuk1/raw/", b"\x89PNG\r\n\x1a\nbozuk")
    assert c.dis_indir({"link": "https://snappark.net/s/Bozuk1"}) is None and c._dis_son_durum == "bozuk"
    assert not [p for p in Path(c.dis_klasor).iterdir() if p.suffix in (".png", ".jpg", ".part")]


def test_kapaliysa_hic_istek_yok(sahte, tmp_path):
    a = ayar_yap(tmp_path, DIS_GORSEL_PROXY="0")
    c = _cozucu(sahte, a)
    sahte.gorsel("/img.snappark.net/s/%s/raw/" % SP_ID, png())
    assert not c.dis_acik and c.dis_mumkun({"link": SP_RAW}) is None and c.dis_indir({"link": SP_RAW}) is None
    assert c.gorsel_yolu({"link": SP_RAW}) == (None, "yok") and sahte.hits == []
    # ayrı anahtar yoksa GYAZO_PROXY izlenir
    assert not gorsel.GorselCozucu(ayar_yap(tmp_path, GYAZO_PROXY="0"), a["ONBELLEK"]).dis_acik
    assert gorsel.GorselCozucu(ayar_yap(tmp_path, GYAZO_PROXY="0", DIS_GORSEL_PROXY="1"), a["ONBELLEK"]).dis_acik


# ---------------------------------------------------------------- önbellek budama / durum
def test_dis_onbellek_budama_ve_durum_kapsami(tmp_path):
    a = ayar_yap(tmp_path, GYAZO_ONBELLEK_MB=1)
    c = gorsel.GorselCozucu(a, a["ONBELLEK"])
    adlar = [x[0] for x in c._onbellek_dizinleri()]
    assert adlar == ["gyazo", "dis", "thumbs"]
    dis = dict((x[0], x) for x in c._onbellek_dizinleri())["dis"]
    assert dis[1] == c.dis_klasor and dis[2] == c.gyazo_sinir_bayt and dis[3] == c.gyazo_yas_sn
    d = Path(c.dis_klasor)
    eski = time.time() - 4000
    for i in range(6):
        p = d / (sha1("u%d" % i) + ".jpg"); p.write_bytes(b"x" * 300 * 1024); os.utime(p, (eski + i, eski + i))
    yok = d / (sha1("y") + ".yok"); yok.write_text("1"); os.utime(yok, (eski, eski))
    yarim = d / "dis-abc.part"; yarim.write_bytes(b"1"); os.utime(yarim, (eski, eski))
    yabanci = d / "benim-dosyam.jpg"; yabanci.write_bytes(b"x" * 1024); os.utime(yabanci, (eski, eski))
    rapor = c.onbellek_temizle(zorla=True)
    assert set(rapor) == {"gyazo", "dis", "thumbs"}
    r = rapor["dis"]
    assert not yok.exists() and not yarim.exists() and yabanci.exists()
    kalan = sorted(p.name for p in d.iterdir() if p.suffix == ".jpg" and p.name != yabanci.name)
    assert r["silinen"] >= 4 and sum((d / n).stat().st_size for n in kalan) <= 1024 * 1024
    assert (d / (sha1("u5") + ".jpg")).exists()  # en yeni kalır
    durum = c.onbellek_durumu()
    assert durum["dis"]["sinir_mb"] == 1 and durum["dis"]["dizin"] == c.dis_klasor


# ---------------------------------------------------------------- panel
def test_panel_json_gorsel_kaynak_ve_rotalar_onbellekten(web, sahte):
    cl, a = web; login(cl)
    from app import panel
    c = panel.COZUCU
    c.dis_test_host = "127.0.0.1:%d" % sahte.port
    oturum = requests.Session(); oturum.trust_env = False; c._http = oturum
    govde = png((1, 2, 3))
    Path(c.dis_klasor, sha1(SP_RAW) + ".png").write_bytes(govde)  # önceden kopyalanmış (gece işi)
    sp = insert(a, link=SP_RAW, link_turu="snappark", personel="SP")
    d = cl.get("/kayit/%d" % sp).json
    assert d["gorsel_kaynak"] == "snappark" and d["link_kaynak"] == "snappark" and d["gorsel_var"] and d["gorsel_url"] and d["kucuk_url"]
    r = cl.get("/gorsel/%d" % sp); assert r.status_code == 200 and r.data == govde
    r = cl.get("/gorsel/%d?indir=1" % sp); assert r.status_code == 200 and "kayit-%d.png" % sp in r.headers["Content-Disposition"]
    r = cl.get("/kucuk/%d" % sp); assert r.status_code == 200 and r.data[:2] == b"\xff\xd8"
    assert sahte.hits == []  # hepsi önbellekten
    # önbellekte yok: ilk görüntülemede indirilir
    sahte.gorsel("/i.gyazo.com/%s.png" % TZ_ID, png((9, 9, 9)))
    tz = insert(a, link=TZ, link_turu="teamzone", personel="TZ")
    assert cl.get("/kayit/%d" % tz).json["gorsel_kaynak"] == "teamzone"
    assert cl.get("/gorsel/%d" % tz).status_code == 200 and sahte.hits == ["/i.gyazo.com/%s.png" % TZ_ID]
    # açılamayan teamzone: kaynak 'yok' ama link_kaynak söyler; rota 404
    tz2_id = "f" * 32
    tz2 = insert(a, link="https://teamzone.gyazo.com/" + tz2_id, link_turu="teamzone")
    assert cl.get("/gorsel/%d" % tz2).status_code == 404
    d = cl.get("/kayit/%d" % tz2).json
    assert d["gorsel_kaynak"] == "yok" and d["link_kaynak"] == "teamzone" and not d["gorsel_var"] and d["dis_link"]
    od = insert(a, link="https://x.sharepoint.com/personal/onedrive.aspx?id=/a/b/kanit.png", link_turu="onedrive")
    d = cl.get("/kayit/%d" % od).json
    assert d["gorsel_kaynak"] == "onedrive" and d["link_kaynak"] == "onedrive" and not d["gorsel_var"]
    gy = insert(a, link="https://gyazo.com/" + "a" * 32, link_turu="gyazo")
    assert cl.get("/kayit/%d" % gy).json["link_kaynak"] == "gyazo"
    # ikinci görsel Snappark
    iki = insert(a, link="", gorsel2=SP_RAW)
    d = cl.get("/kayit/%d" % iki).json
    assert d["gorsel2_var"] and d["gorsel2_url"] and cl.get("/gorsel/%d?ikinci=1" % iki).data == govde


def test_panel_js_yer_tutucu_kaynagi_soyler():
    js = (ROOT / "app" / "static" / "panel.js").read_text(encoding="utf-8")
    assert "Görsel dış sitede ('+DIS_SITE[lk]+'); açılamadı" in js and "snappark:'Snappark',teamzone:'Teamzone'" in js
    assert "Görsel dış sitede (OneDrive)" in js and "lk!=='dosya'" in js
    assert "disHataMetni(k)||'Görsel şu an açılamadı.'" in js


# ---------------------------------------------------------------- toplu / gece kopyalama
class URLOturum:
    """Tam URL -> sıralı yanıt listesi; Exception örneği yükseltilir."""

    def __init__(self, plan):
        self.plan = {k: list(v) for k, v in plan.items()}
        self.istekler = []

    def get(self, url, **kw):
        assert kw.get("stream") is True and kw.get("allow_redirects") is False
        self.istekler.append(url)
        assert self.plan.get(url), "beklenmeyen istek: " + url
        y = self.plan[url].pop(0)
        if isinstance(y, Exception):
            raise y
        return y


def _png_yanit():
    g = png()
    return SahteYanit(200, g, {"Content-Type": "image/png", "Content-Length": str(len(g))})


@pytest.fixture
def toplu(tmp_path):
    a = ayar_yap(tmp_path)
    conn = db.baglan(a["DB"])
    satirlar = [
        ("a", "GA", "1", "https://i.gyazo.com/%s.jpg" % kimlik(1), ""),
        ("b", "OF", "2", SP_RAW, ""),
        ("c", "OF", "3", "https://snappark.net/s/%s" % SP_ID, ""),       # aynı normalize URL → zaten var
        ("d", "PA", "4", TZ, ""),
        ("e", "PA", "5", "https://snappark.net/baska/abc", ""),           # tanınmayan
        ("f", "HI", "6", "https://onedrive.example/x", "https://img.snappark.net/s/Iki2/raw/"),  # ikinci görsel snappark → 404
    ]
    for anahtar, proje, personel, link, g2 in satirlar:
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link,gorsel2) VALUES(?,?,?,?,?)", (anahtar, proje, personel, link, g2))
    conn.commit()
    c = gorsel.GorselCozucu(a, a["ONBELLEK"])
    yield conn, c, a
    conn.close()


def test_toplu_indirme_tur_sayaclari_ve_rapor(toplu):
    conn, c, a = toplu
    c._http = URLOturum({
        "https://i.gyazo.com/%s.jpg" % kimlik(1): [SahteYanit(200, jpeg())],
        SP_RAW: [_png_yanit()],
        "https://i.gyazo.com/%s.png" % TZ_ID: [SahteYanit(404)],
        "https://i.gyazo.com/%s.jpg" % TZ_ID: [SahteYanit(200, jpeg())],
        "https://img.snappark.net/s/Iki2/raw/": [SahteYanit(404)],
    })
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda s: None, log=loglar.append)
    assert (r["baglanti"], r["indirilen"], r["zaten_var"], r["acilamayan"]) == (5, 3, 1, 1)
    t = r["turler"]
    assert t["gyazo"] == {"baglanti": 1, "indirilen": 1, "zaten_var": 0, "acilamayan": 0, "taninmayan": 0}
    assert t["snappark"] == {"baglanti": 3, "indirilen": 1, "zaten_var": 1, "acilamayan": 1, "taninmayan": 1}
    assert t["teamzone"] == {"baglanti": 1, "indirilen": 1, "zaten_var": 0, "acilamayan": 0, "taninmayan": 0}
    assert any("5 bağlantı taranıyor (Gyazo 1, Snappark 3, Teamzone 1)" in m for m in loglar)
    assert (Path(c.dis_klasor) / (sha1(SP_RAW) + ".png")).is_file() and (Path(c.dis_klasor) / (sha1(TZ) + ".jpg")).is_file()
    satirlar = list(csv.reader(Path(r["rapor"]).read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert satirlar[0] == ["kayit_id", "proje", "personel", "link", "sebep"]
    assert len(satirlar) == 2 and satirlar[1][1] == "HI" and "Snappark'ta görsel yok (404)" == satirlar[1][4]
    # ikinci çalıştırma: önbellektekiler istenmez, 404 bir kez daha denenir
    c._http = URLOturum({"https://img.snappark.net/s/Iki2/raw/": [SahteYanit(404)]})
    r2 = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda s: None)
    assert (r2["indirilen"], r2["zaten_var"], r2["acilamayan"]) == (0, 4, 1) and len(c._http.istekler) == 1
    assert conn.execute("SELECT COUNT(*) FROM kayitlar WHERE guncelleme IS NOT NULL").fetchone()[0] == 0


def test_toplu_dis_servis_erisim_yoksa_kalanlari_denemez(toplu):
    conn, c, a = toplu
    c._http = URLOturum({
        "https://i.gyazo.com/%s.jpg" % kimlik(1): [SahteYanit(200, jpeg())],
        SP_RAW: [OSError("Name or service not known"), OSError("Name or service not known")],
        "https://i.gyazo.com/%s.png" % TZ_ID: [SahteYanit(200, png(), {"Content-Type": "image/png"})],
    })
    uykular, loglar = [], []
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=uykular.append, log=loglar.append)
    assert uykular.count(5) == 1  # geçici hata bir kez yeniden denendi
    assert r["dis_erisim_yok"] == ["Snappark"] and any("Snappark'a ulaşılamıyor" in m for m in loglar)
    assert r["turler"]["snappark"]["acilamayan"] == 3 and r["turler"]["teamzone"]["indirilen"] == 1
    assert "https://img.snappark.net/s/Iki2/raw/" not in c._http.istekler and c._http.istekler.count(SP_RAW) == 2
    assert r["bitis_nedeni"] == "tamam"


def test_toplu_on_kontrol_yalniz_gyazo(toplu):
    conn, c, a = toplu
    c._http = URLOturum({"https://i.gyazo.com/%s.jpg" % ("0" * 32): [SahteYanit(404)],
                         "https://i.gyazo.com/%s.jpg" % kimlik(1): [SahteYanit(200, jpeg())]})
    r = gorsel.gyazo_toplu_indir(conn, c, a, on_kontrol=True, en_cok=1, uyku=lambda s: None)
    assert r["indirilen"] == 1 and c._http.istekler[0].endswith("0" * 32 + ".jpg") and len(c._http.istekler) == 2


def test_toplu_dis_kapaliysa_yalniz_gyazo(toplu):
    conn, c, a = toplu
    c.dis_acik = False
    c._http = URLOturum({"https://i.gyazo.com/%s.jpg" % kimlik(1): [SahteYanit(200, jpeg())]})
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda s: None)
    assert r["baglanti"] == 1 and r["turler"]["snappark"]["baglanti"] == 0 and r["turler"]["snappark"]["taninmayan"] == 4


def test_cli_yardim_dis_servisleri_anar(tmp_path):
    r = subprocess.run([sys.executable, "-m", "app.cli", "--help"], cwd=ROOT, capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)})
    assert r.returncode == 0 and "Gyazo/Snappark/Teamzone" in r.stdout
