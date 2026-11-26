"""Gece Gyazo kopyalama: pencere, gecelik sınır, bitiş saati, ön kontrol, kurulum betiği (2.3.1)."""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import gorsel
from test_gyazo_toplu import ortam, SahteOturum, SahteYanit, jpeg, kimlik  # noqa: F401  (fixture ve yardımcılar)

ROOT = Path(__file__).resolve().parents[1]
TR = ZoneInfo("Europe/Istanbul")


def _saat(h, m, gun=25):
    return datetime(2026, 11, gun, h, m, tzinfo=TR)


def test_pencere_gece_yarisini_asar_ve_disinda_kalir():
    icinde, bitis, _ = gorsel.gyazo_pencere("22:30-07:30", simdi=lambda: _saat(23, 0))
    assert icinde and bitis == _saat(7, 30, 26)
    icinde, bitis, _ = gorsel.gyazo_pencere("22:30-07:30", simdi=lambda: _saat(3, 0))
    assert icinde and bitis == _saat(7, 30)
    icinde, sonraki, aciklama = gorsel.gyazo_pencere("22:30-07:30", simdi=lambda: _saat(10, 0))
    assert not icinde and sonraki == _saat(22, 30) and "sonraki başlangıç 22:30" in aciklama
    icinde, bitis, _ = gorsel.gyazo_pencere("09:00-17:00", simdi=lambda: _saat(12, 0))
    assert icinde and bitis == _saat(17, 0)
    icinde, sonraki, _ = gorsel.gyazo_pencere("09:00-17:00", simdi=lambda: _saat(18, 0))
    assert not icinde and sonraki == _saat(9, 0, 26)
    with pytest.raises(ValueError):
        gorsel.gyazo_pencere("22-07")
    with pytest.raises(ValueError):
        gorsel.gyazo_pencere("25:00-07:30")


def test_gecelik_sinir_kaldigi_yerden_surer(ortam):
    conn, c, ayar = ortam
    plan = {kimlik(1): [SahteYanit(200, jpeg())], kimlik(2): [SahteYanit(404)], kimlik(3): [SahteYanit(200, jpeg())], kimlik(4): [SahteYanit(200, jpeg())]}
    c._http = SahteOturum({kimlik(1): list(plan[kimlik(1)]), kimlik(2): list(plan[kimlik(2)])})
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, yeni_en_cok=2, uyku=lambda s: None, log=loglar.append)
    assert (r["denenen"], r["indirilen"], r["acilamayan"], r["bitis_nedeni"]) == (2, 1, 1, "sinir") and r["durduruldu"] is None
    assert r["kalan"] >= 1 and any("sınırı (2) doldu" in m for m in loglar) and any("indirildi" in m for m in loglar)
    # ikinci gece: kalanlar iner, önbellektekiler sayılır
    c._http = SahteOturum({kimlik(2): [SahteYanit(404)], kimlik(3): list(plan[kimlik(3)]), kimlik(4): list(plan[kimlik(4)])})
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, yeni_en_cok=5, uyku=lambda s: None)
    assert (r2["indirilen"], r2["zaten_var"], r2["bitis_nedeni"], r2["kalan"]) == (2, 2, "tamam", 0)


def test_bitis_saati_durdurur(ortam):
    conn, c, ayar = ortam
    c._http = SahteOturum({kimlik(1): [SahteYanit(200, jpeg())]})
    saatler = iter([_saat(23, 0), _saat(7, 31, 26)])
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, bitis=_saat(7, 30, 26), uyku=lambda s: None, simdi=lambda: next(saatler))
    assert (r["denenen"], r["indirilen"], r["bitis_nedeni"]) == (1, 1, "sure") and r["kalan"] >= 1


def test_on_kontrol_erisim_yoksa_hic_denemez(ortam):
    conn, c, ayar = ortam

    class Kopuk:
        def get(self, url, **kw):
            raise OSError("Name or service not known")

    c._http = Kopuk()
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, on_kontrol=True, log=loglar.append, uyku=lambda s: None)
    assert r["bitis_nedeni"] == "erisim" and r["denenen"] == 0 and "ulaşılamıyor" in r["durduruldu"] and "curl" in r["durduruldu"]
    assert r["rapor"] is None and any("ulaşılamıyor" in m for m in loglar)
    # ön kontrol geçerse (404 bile) indirme sürer
    c._http = SahteOturum({"0" * 32: [SahteYanit(404)], kimlik(1): [SahteYanit(200, jpeg())]})
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, on_kontrol=True, en_cok=1, uyku=lambda s: None, log=loglar.append)
    assert r2["indirilen"] == 1 and any("Gyazo erişimi: ulaşıldı" in m for m in loglar)


def test_cli_pencere_disinda_hic_calismaz(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)}
    saat = datetime.now(TR)
    # şu anki saatin 2 saat sonrasından başlayan 1 saatlik pencere → kesinlikle dışarıdayız
    bas = (saat + timedelta(hours=2)).strftime("%H:%M"); bit = (saat + timedelta(hours=3)).strftime("%H:%M")
    r = subprocess.run([sys.executable, "-m", "app.cli", "gyazo-onbellekle", "--pencere", f"{bas}-{bit}", "--on-kontrol-atla"],
                       cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0 and "GYAZO_ONBELLEK_PENCERE_DISI" in r.stdout, r.stdout + r.stderr
    r = subprocess.run([sys.executable, "-m", "app.cli", "gyazo-onbellekle", "--pencere", "abc"], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode != 0 and "SS:DD-SS:DD" in (r.stderr + r.stdout)


def test_setup_gyazo_gece_dry_run_ve_kurulum(tmp_path):
    kok = tmp_path / "kanit"; (kok / ".venv" / "bin").mkdir(parents=True); (kok / "data").mkdir()
    (kok / ".env").write_text("X=1\n")
    py = kok / ".venv" / "bin" / "python"; py.write_text("#!/bin/bash\nexit 0\n"); py.chmod(0o755)
    units = tmp_path / "units"
    log = tmp_path / "systemctl.log"
    fake = tmp_path / "systemctl"; fake.write_text(f"#!/bin/bash\necho \"$*\" >> {log}\nexit 0\n"); fake.chmod(0o755)
    env = {**os.environ, "KANIT_TEST": "1", "KANIT_UNIT_DIR": str(units), "KANIT_SYSTEMCTL": str(fake), "KANIT_DIR": str(kok)}
    betik = str(ROOT / "deploy" / "setup-gyazo-gece.sh")
    r = subprocess.run(["bash", betik, "--dry-run", "--saat", "22:30", "--bitis", "07:30", "--gecelik", "900"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout and not units.exists(), r.stdout + r.stderr
    assert "--yeni-en-cok 900 --pencere 22:30-07:30 --saat-dilimi Europe/Istanbul" in r.stdout and "OnCalendar=*-*-* 22:30:00 Europe/Istanbul" in r.stdout
    r = subprocess.run(["bash", betik, "--saat", "23:00", "--bitis", "06:45", "--gecelik", "500"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "GYAZO_GECE_TAMAM" in r.stdout, r.stdout + r.stderr
    servis = (units / "kanit-gyazo.service").read_text(); timer = (units / "kanit-gyazo.timer").read_text()
    assert f"WorkingDirectory={kok}" in servis and "--yeni-en-cok 500 --pencere 23:00-06:45" in servis and "@" not in servis
    assert "OnCalendar=*-*-* 23:00:00 Europe/Istanbul" in timer and "Persistent=true" in timer
    assert "enable --now kanit-gyazo.timer" in log.read_text()
    r = subprocess.run(["bash", betik, "--saat", "9:5"], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "SS:DD" in r.stderr
    r = subprocess.run(["bash", betik, "--kaldir"], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "GYAZO_GECE_KALDIRILDI" in r.stdout and not (units / "kanit-gyazo.timer").exists()


def test_gyazo_arizasinda_hizli_gecis_ve_t_gyazo_izinli(ortam):
    conn, c, ayar = ortam
    # 12 ayrı kimlik: hepsi 503 → ilk 10'da yeniden deneme (1 sn) var, sonrasında yok; bekleme de yok
    for n in range(10, 22):
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link,link_turu) VALUES(?,?,?,?,?)",
                     (f"z{n}", "GA", "1", "https://i.gyazo.com/%s.jpg" % kimlik(n), "gyazo"))
    conn.commit()
    plan = {kimlik(n): [SahteYanit(503), SahteYanit(503)] for n in range(10, 22)}
    plan.update({kimlik(1): [SahteYanit(503), SahteYanit(503)], kimlik(2): [SahteYanit(503), SahteYanit(503)],
                 kimlik(3): [SahteYanit(503), SahteYanit(503)], kimlik(4): [SahteYanit(503), SahteYanit(503)]})
    c._http = SahteOturum(plan)
    uykular = []; loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, log=loglar.append, bekleme_sn=0.15)
    # 16 ayrı kimlik + "b" (a ile aynı kimlik → "aynı bağlantı bu çalıştırmada açılamadı") = 17
    assert r["acilamayan"] == 17 and r["bitis_nedeni"] == "tamam" and r.get("ariza") == ["Gyazo"]
    assert uykular.count(1) == 10 and uykular.count(0.15) <= 10  # 10. hatadan sonra yeniden deneme ve bekleme yok
    assert any("art arda 10" in m for m in loglar)
    sebepler = [satir[4] for satir in r["acilamayan_ornek"]]
    assert sebepler.count("aynı bağlantı bu çalıştırmada açılamadı") == 1
    assert all("503" in sebep for sebep in sebepler if "aynı bağlantı" not in sebep)
    # t.gyazo.com Gyazo ve Teamzone için izinli
    assert "t.gyazo.com" in gorsel.GYAZO_HOSTLAR and "t.gyazo.com" in gorsel.DIS_GORSEL_HOSTLAR["teamzone"]


# ---- Gyazo arızası: ağ hatası da sayılır, art arda 25'te servis bu çalıştırmada bırakılır (26 Kasım) ----
import csv  # noqa: E402

import requests  # noqa: E402


class _AsiliOturum(SahteOturum):
    """Planda olmayan her kimlik için bağlantı okuma zaman aşımına düşer (asılı kalan Gyazo sunucusu)."""

    def get(self, url, **kw):
        kim = url.rsplit("/", 1)[-1].split(".")[0]
        if self.plan.get(kim):
            return super().get(url, **kw)
        assert kw.get("stream") is True and kw.get("allow_redirects") is False
        self.istekler.append(url)
        raise requests.exceptions.ReadTimeout("okuma zaman aşımı (sahte)")


def _gyazo_kayitlari_ekle(conn, araliklar):
    for n in araliklar:
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link,link_turu) VALUES(?,?,?,?,?)",
                     (f"z{n}", "GA", "1", "https://i.gyazo.com/%s.jpg" % kimlik(n), "gyazo"))
    conn.commit()


def test_gyazo_asili_kalinca_hizli_gecer_ve_25te_birakir(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))  # fikstürdeki 4 kimlik + 30 = 34 ayrı kimlik (+ "b" aynı kimlik)
    c._http = _AsiliOturum({})
    uykular = []; loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, log=loglar.append, bekleme_sn=0.15)
    # ilk 10 bağlantı yeniden denenir (2 istek), sonraki 15 tek istek; 25'ten sonra hiç istek yok
    assert len(c._http.istekler) == 10 * 2 + 15
    assert uykular.count(1) == 10
    assert r["bitis_nedeni"] == "tamam" and r["kalan"] == 0 and r["denenen"] == 25
    assert r["ariza"] == ["Gyazo"] and r["ariza_denenmedi"] == {"Gyazo": 9}
    assert r["acilamayan"] == 35 and r["turler"]["gyazo"]["acilamayan"] == 35
    assert any("art arda 10" in m and "son durum: ağ hatası" in m for m in loglar)
    assert any("art arda 25" in m and "denenmeyecek" in m for m in loglar)
    satirlar = list(csv.reader(Path(r["rapor"]).read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))[1:]
    denenmedi = [s for s in satirlar if "Gyazo arızası sürüyor" in s[4]]
    assert len(denenmedi) == 9 and all("bu çalıştırmada denenmedi" in s[4] and "sonraki çalıştırmada" in s[4] for s in denenmedi)
    assert all(kimlik(n) not in u for n in range(31, 40) for u in c._http.istekler)
    # denenmeyen bağlantılar gecelik yeni indirme sınırını tüketmez
    c._http = _AsiliOturum({})
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, yeni_en_cok=26, uyku=lambda s: None)
    assert r2["bitis_nedeni"] == "tamam" and r2["denenen"] == 25 and r2["kalan"] == 0 and r2["ariza_denenmedi"] == {"Gyazo": 9}


def test_gyazo_arizasinda_basari_sayaci_sifirlar(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    # 9 hata (k1-k4, k10-k14), k15 iner, sonra 24 hata: 10'da hızlı geçiş, sıfırlandığı için 25'e ulaşmaz
    c._http = _AsiliOturum({kimlik(15): [SahteYanit(200, jpeg())]})
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, bekleme_sn=0)
    assert uykular.count(1) == 9 + 10
    assert len(c._http.istekler) == 9 * 2 + 1 + 10 * 2 + 14
    assert r["indirilen"] == 1 and r["ariza"] == ["Gyazo"] and not r.get("ariza_denenmedi")
    assert r["bitis_nedeni"] == "tamam" and r["denenen"] == 34
    assert not any("denenmedi" in s[4] for s in r["acilamayan_ornek"])


def test_snappark_arizasi_gyazoyu_etkilemez(tmp_path):
    from app import db
    from test_dis_gorsel_232 import URLOturum, ayar_yap
    a = ayar_yap(tmp_path)
    conn = db.baglan(a["DB"])
    plan = {}
    for i in range(30):
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)",
                     ("s%d" % i, "OF", str(i), "https://snappark.net/s/Ar%02d" % i))
        plan["https://img.snappark.net/s/Ar%02d/raw/" % i] = [SahteYanit(503), SahteYanit(503)]
        if i % 6 == 5:  # aralara Gyazo bağlantıları
            conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)",
                         ("g%d" % i, "OF", str(i), "https://i.gyazo.com/%s.jpg" % kimlik(100 + i)))
            plan["https://i.gyazo.com/%s.jpg" % kimlik(100 + i)] = [SahteYanit(200, jpeg())]
    conn.commit()
    c = gorsel.GorselCozucu(a, a["ONBELLEK"])
    c._http = URLOturum(plan)
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda s: None, bekleme_sn=0, log=loglar.append)
    sp = [u for u in c._http.istekler if "snappark" in u]
    assert len(sp) == 10 * 2 + 15 and all("Ar%02d" % i not in u for i in range(25, 30) for u in sp)
    assert r["turler"]["gyazo"]["indirilen"] == 5 and r["turler"]["gyazo"]["acilamayan"] == 0
    assert r["ariza"] == ["Snappark"] and r["ariza_denenmedi"] == {"Snappark": 5} and r["bitis_nedeni"] == "tamam"
    assert r["turler"]["snappark"]["acilamayan"] == 30
    assert any("Snappark art arda 10" in m and "HTTP 503" in m for m in loglar)


def test_cli_ariza_satiri(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)}
    kod = ("import sys\n"
           "from app import gorsel, cli\n"
           "gorsel.gyazo_toplu_indir = lambda *a, **k: {'bitis_nedeni': 'tamam', 'kalan': 0, 'ariza': ['Gyazo'],\n"
           "    'ariza_denenmedi': {'Gyazo': 700}, 'turler': {'gyazo': {'baglanti': 900, 'acilamayan': 880}}}\n"
           "sys.argv = ['app.cli', 'gyazo-onbellekle', '--on-kontrol-atla']\n"
           "cli.main()\n")
    r = subprocess.run([sys.executable, "-c", kod], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    satirlar = r.stdout.splitlines()
    beklenen = ("ARIZA: Gyazo yanıt vermiyor (muhtemelen Gyazo arızası); 180 bağlantı açılamadı, 700 bağlantı denenmedi. "
                "Gece planı sonraki çalıştırmada yeniden dener.")
    assert beklenen in satirlar and satirlar[-1] == "GYAZO_ONBELLEK_TAMAM"
    assert satirlar.index(beklenen) < satirlar.index("GYAZO_ONBELLEK_TAMAM")
