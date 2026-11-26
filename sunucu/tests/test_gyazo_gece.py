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
    # 12 ayrı kimlik: hepsi 503 → ilk 10'da yeniden deneme (1 sn) var, sonrasında yok; bekleme sürer, arıza ilan edilmez
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
    assert r["acilamayan"] == 17 and r["bitis_nedeni"] == "tamam" and r["hizli_gecis"] == ["Gyazo"] and not r.get("ariza")
    # 10. hatadan sonra yeniden deneme yok; bekleme her denemeden sonra (16 denenen, sonuncusu son aday) = 15
    assert uykular.count(1) == 10 and uykular.count(0.15) == 15
    assert any("art arda 10" in m and "bir kez daha denenmeden" in m for m in loglar)
    assert not any("muhtemelen" in m for m in loglar)
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
    assert r["ariza"] == ["Gyazo"] and r["hizli_gecis"] == ["Gyazo"] and r["ariza_denenmedi"] == {"Gyazo": 9}
    assert r["acilamayan"] == 35 and r["turler"]["gyazo"]["acilamayan"] == 35
    assert any("art arda 10" in m and "son durum: ağ hatası" in m for m in loglar)
    assert any("art arda 25 bağlantının 25'inde hiç yanıt alınamadı" in m and "muhtemelen Gyazo arızası" in m and "denenmeyecek" in m
               for m in loglar)
    assert uykular.count(0.15) == 25  # denenen 25 bağlantının her birinden sonra (hızlı geçişte de); denenmeyenlerde bekleme yok
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
    # 9 hata (k1-k4, k10-k14), k15 iner (arıza penceresi boşalır), sonra 24 hata: 10'da hızlı geçiş, 25'e ulaşmaz
    c._http = _AsiliOturum({kimlik(15): [SahteYanit(200, jpeg())]})
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, bekleme_sn=0)
    assert uykular.count(1) == 9 + 10
    assert len(c._http.istekler) == 9 * 2 + 1 + 10 * 2 + 14
    assert r["indirilen"] == 1 and r["hizli_gecis"] == ["Gyazo"] and not r.get("ariza") and not r.get("ariza_denenmedi")
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
        plan["https://img.snappark.net/s/Ar%02d/raw/" % i] = [requests.exceptions.ReadTimeout("asılı"), requests.exceptions.ReadTimeout("asılı")]
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
    assert r["hizli_gecis"] == ["Snappark"] and r["turler"]["snappark"]["acilamayan"] == 30
    assert any("Snappark art arda 10" in m and "ağ hatası" in m for m in loglar)
    assert any("Snappark arızası da olabilir" in m for m in loglar) and not any("Gyazo arızası da olabilir" in m for m in loglar)


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
                "Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir.")
    assert beklenen in satirlar and satirlar[-1] == "GYAZO_ONBELLEK_TAMAM"
    assert satirlar.index(beklenen) < satirlar.index("GYAZO_ONBELLEK_TAMAM")


def _cli_calistir(tmp_path, sonuc):
    env = {"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)}
    kod = ("import sys\n"
           "from app import gorsel, cli\n"
           "gorsel.gyazo_toplu_indir = lambda *a, **k: %r\n"
           "sys.argv = ['app.cli', 'gyazo-onbellekle', '--on-kontrol-atla']\n"
           "cli.main()\n" % (sonuc,))
    return subprocess.run([sys.executable, "-c", kod], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)


def test_cli_ariza_satiri_coklu_servis_ve_arizasiz(tmp_path):
    r = _cli_calistir(tmp_path, {"bitis_nedeni": "sinir", "kalan": 5, "ariza": ["Gyazo", "Snappark"], "ariza_denenmedi": {"Snappark": 3},
                                 "turler": {"gyazo": {"acilamayan": 12}, "snappark": {"acilamayan": 13}}})
    assert r.returncode == 0, r.stdout + r.stderr
    satirlar = r.stdout.splitlines()
    assert ("ARIZA: Gyazo yanıt vermiyor (muhtemelen Gyazo arızası); 12 bağlantı açılamadı · Snappark yanıt vermiyor "
            "(muhtemelen Snappark arızası); 10 bağlantı açılamadı, 3 bağlantı denenmedi. "
            "Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir.") in satirlar
    assert satirlar[-1].startswith("GYAZO_ONBELLEK_DEVAM")
    r = _cli_calistir(tmp_path, {"bitis_nedeni": "tamam", "kalan": 0, "turler": {"gyazo": {"acilamayan": 4}}})
    assert r.returncode == 0 and not any(s.startswith("ARIZA:") for s in r.stdout.splitlines()) and r.stdout.splitlines()[-1] == "GYAZO_ONBELLEK_TAMAM"


class _SabitOturum(SahteOturum):
    """Planda olmayan kimlikler için sabit sonuç: bir yanıt (ör. 503) ya da yükseltilecek bir istisna."""

    def __init__(self, plan, varsayilan):
        super().__init__(plan)
        self.varsayilan = varsayilan

    def get(self, url, **kw):
        kim = url.rsplit("/", 1)[-1].split(".")[0]
        if self.plan.get(kim):
            return super().get(url, **kw)
        assert kw.get("stream") is True and kw.get("allow_redirects") is False
        self.istekler.append(url)
        if isinstance(self.varsayilan, BaseException):
            raise self.varsayilan
        return SahteYanit(self.varsayilan)


def test_baglanti_kurulamayan_gyazo_da_sayilir_ve_birakilir(ortam):
    # Gyazo yolunda ConnectTimeout da "hata" olarak raporlanır; arıza sayılır, ön kontrolde ise sunucu erişimi sorunu sayılır.
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    c._http = _SabitOturum({}, requests.exceptions.ConnectTimeout("bağlantı zaman aşımı (sahte)"))
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, bekleme_sn=0)
    assert len(c._http.istekler) == 10 * 2 + 15 and uykular.count(1) == 10
    assert r["ariza"] == ["Gyazo"] and r["ariza_denenmedi"] == {"Gyazo": 9} and r["bitis_nedeni"] == "tamam"
    # ön kontrolde bağlantı hiç kurulamıyorsa (sunucunun dış erişimi) eskisi gibi hemen durur
    c._http = _SabitOturum({}, requests.exceptions.ConnectTimeout("bağlantı zaman aşımı (sahte)"))
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, on_kontrol=True, uyku=lambda s: None)
    assert r2["bitis_nedeni"] == "erisim" and len(c._http.istekler) == 2 and "ulaşılamıyor" in r2["durduruldu"]


def test_on_kontrol_asili_kalirsa_durur_ve_iki_ihtimali_soyler(ortam):
    # Ön kontrolde okuma zaman aşımı hem asılı Gyazo hem de TLS'yi kesen bir güvenlik duvarı (dış erişim sorunu) olabilir:
    # komut "tamam" ile bitip sorunu gizlemez; bir kez daha dener, sonra GYAZO_ONBELLEK_YARIM (çıkış 1) ile durur.
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    c._http = _SabitOturum({}, requests.exceptions.ReadTimeout("okuma zaman aşımı (sahte)"))
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, on_kontrol=True, uyku=lambda s: None, log=loglar.append, bekleme_sn=0.15)
    assert r["bitis_nedeni"] == "erisim" and r["denenen"] == 0 and len(c._http.istekler) == 2
    assert not r.get("ariza") and "ulaşılamıyor" in r["durduruldu"] and "curl" in r["durduruldu"]
    assert "Gyazo arızalı" in r["durduruldu"] and "dış HTTPS erişimi" in r["durduruldu"]
    # tek seferlik bir zaman aşımı çalıştırmayı durdurmaz ve Gyazo'yu "arızalı" işaretlemez

    class _Oturum(SahteOturum):
        def get(self, url, **kw):
            kim = url.rsplit("/", 1)[-1].split(".")[0]
            if kim == "0" * 32 and self.plan.get(kim) and isinstance(self.plan[kim][0], BaseException):
                self.istekler.append(url)
                raise self.plan[kim].pop(0)
            return super().get(url, **kw)

    plan = {kimlik(n): [SahteYanit(200, jpeg())] for n in list(range(1, 5)) + list(range(10, 40))}
    plan["0" * 32] = [requests.exceptions.ReadTimeout("geçici"), SahteYanit(404)]
    c._http = _Oturum(plan)
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, on_kontrol=True, uyku=lambda s: None, bekleme_sn=0)
    assert r2["bitis_nedeni"] == "tamam" and r2["indirilen"] == 34 and not r2.get("ariza")


@pytest.mark.parametrize("hizli_yanit", [503, 404])
def test_karisik_arizada_asililar_gyazoyu_birakir(ortam, hizli_yanit):
    # Kaynak arızasında bağlantıların çoğu asılı kalır, bir kısmı hızlı 503/404 alır. Hızlı yanıtlar arıza penceresini
    # boşaltmaz: son 30 denemenin 25'i yanıtsız olunca kalan Gyazo bağlantıları denenmez (%90 asılı / %10 hızlı yanıt).
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 110))
    c._http = _AsiliOturum({kimlik(n): [SahteYanit(hizli_yanit), SahteYanit(hizli_yanit)] for n in range(10, 110, 10)})
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, log=loglar.append, bekleme_sn=0)
    # sıra: k1-k4 asılı (4), k10 hızlı, k11-k19 asılı (13), k20 hızlı, k21-k29 asılı (22), k30 hızlı, k31-k33 asılı (25):
    # 28 denemenin 25'i yanıtsız → k34-k109 (76 bağlantı) hiç istenmez
    assert r["ariza"] == ["Gyazo"] and r["ariza_denenmedi"] == {"Gyazo": 76} and r["bitis_nedeni"] == "tamam" and r["kalan"] == 0
    assert not any(kimlik(n) in u for n in range(34, 110) for u in c._http.istekler)
    assert any("art arda 28 bağlantının 25'inde hiç yanıt alınamadı" in m and "denenmeyecek" in m for m in loglar)


@pytest.mark.parametrize("hizli_yanit", [503, 404])
def test_yari_asili_yari_hizli_yanitta_gyazo_birakilmaz(ortam, hizli_yanit):
    # Bilinçli ödünleşim: bağlantıların yarısı asılı, yarısı hızlı 503/404 alıyorsa son 30 denemenin en çok 15'i yanıtsızdır,
    # Gyazo bırakılmaz (yalnız hızlı geçiş). Bu, sağlam Gyazo'nun silinmiş 503 birikimi + seyrek zaman aşımıyla gece gece
    # bırakılmasını önlemenin bedelidir: yarı asılı bir gecede asılı bağlantı başına ~20 sn harcanır, gece penceresi ve
    # gecelik sınır süreyi yine sınırlar; açılamayanlar sonraki çalıştırmada yeniden denenir.
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 110))
    c._http = _AsiliOturum({kimlik(n): [SahteYanit(hizli_yanit), SahteYanit(hizli_yanit)] for n in range(11, 110, 2)})
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, log=loglar.append, bekleme_sn=0)
    assert not r.get("ariza") and not r.get("ariza_denenmedi") and r["hizli_gecis"] == ["Gyazo"]
    assert r["denenen"] == 104 and r["bitis_nedeni"] == "tamam" and not any("muhtemelen" in m for m in loglar)


def test_ariza_satiri_servis_basina_bir_kez(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    # 14 asılı → hızlı geçiş; k20 iner (sayaç sıfırlanır); 19 asılı → yeniden 10'a varır ama ikinci kez eklenmez
    c._http = _AsiliOturum({kimlik(20): [SahteYanit(200, jpeg())]})
    loglar = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, log=loglar.append, bekleme_sn=0)
    assert r["hizli_gecis"] == ["Gyazo"] and not r.get("ariza") and not r.get("ariza_denenmedi") and r["indirilen"] == 1
    assert sum("art arda 10" in m for m in loglar) == 1


def test_cli_gece_gunlugunde_baglanti_basina_503_satiri_yok(tmp_path):
    # Gece planı (--ayrintili yok) yalnız özet/arıza satırlarını yazar; bağlantı başına 503 satırları günlüğü doldurmaz.
    env = {"PATH": "/usr/bin:/bin", "PANEL_VERI": str(tmp_path), "HOME": str(tmp_path)}
    kod = ("import sys\n"
           "from app import gorsel, cli\n"
           "def sahte(*a, **k):\n"
           "    log = k['log']\n"
           "    log('1/60 00000000… geçici hata (%s); 1 sn sonra bir kez daha' % gorsel._GYAZO_SEBEP[503])\n"
           "    log('2/60 00000000… açılamadı: %s' % gorsel._GYAZO_SEBEP[503])\n"
           "    log('3/60 00000000… açılamadı: %s' % gorsel._GYAZO_SEBEP[403])\n"
           "    log('Gyazo erişimi: ulaşıldı (deneme isteği HTTP 503; var olmayan kimlik için 503/404 normaldir)')\n"
           "    log('Gyazo art arda 10 bağlantıda hata verdi (son durum: HTTP 503); kalan Gyazo bağlantıları bir kez daha denenmeden geçilir.')\n"
           "    log(\"Gyazo art arda 25 bağlantının 25'inde hiç yanıt alınamadı (zaman aşımı / bağlantı hatası); muhtemelen Gyazo arızası.\")\n"
           "    log(\"Snappark'a art arda 3 bağlantıda ulaşılamadı; kalan Snappark bağlantıları bu çalıştırmada denenmeyecek. Sunucunun dış HTTPS erişimini kontrol edin: curl ...\")\n"
           "    log('4/60 00000000… açılamadı: Snappark\\'a ulaşılamadı')\n"
           "    return {'bitis_nedeni': 'tamam', 'kalan': 0, 'ariza': ['Gyazo'], 'turler': {'gyazo': {'acilamayan': 60}}}\n"
           "gorsel.gyazo_toplu_indir = sahte\n"
           "sys.argv = ['app.cli', 'gyazo-onbellekle', '--yeni-en-cok', '900', '--on-kontrol-atla']\n"
           "cli.main()\n")
    r = subprocess.run([sys.executable, "-c", kod], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "açılamadı: Gyazo yanıt" not in r.stdout and "geçici hata" not in r.stdout
    assert "erişimi reddetti (403)" not in r.stdout  # bağlantı başına 403 satırı da gece günlüğüne girmez
    assert "Gyazo erişimi: ulaşıldı" in r.stdout
    assert "Gyazo art arda 10 bağlantıda hata verdi" in r.stdout and "Gyazo art arda 25 bağlantının 25'inde" in r.stdout
    assert "Snappark'a art arda 3 bağlantıda ulaşılamadı; kalan Snappark" in r.stdout  # servis atlama satırı gece günlüğünde
    assert "4/60" not in r.stdout  # bağlantı başına açılamadı satırı girmez


def test_silinmis_503ler_saglam_gyazoyu_birakmaz_gece_gece(ortam):
    conn, c, ayar = ortam
    # 34 ölü kimlik (fikstürdeki 4 + 30; hepsi 503 = silinmiş görsel), aralarda 404, sonra 5 canlı
    _gyazo_kayitlari_ekle(conn, range(10, 45))
    canli = {kimlik(n): [SahteYanit(200, jpeg())] for n in range(40, 45)}
    plan = dict(canli)
    plan.update({kimlik(n): [SahteYanit(404)] for n in range(12, 40, 5)})
    c._http = _SabitOturum(plan, 503)
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)
    assert r["indirilen"] == 5 and not r.get("ariza_denenmedi") and not r.get("ariza") and r["hizli_gecis"] == ["Gyazo"]
    assert r["bitis_nedeni"] == "tamam"
    # ikinci gece: aynı ölüler yine önde, 5 yeni canlı bağlantı sonda → hepsi denenir ve iner
    _gyazo_kayitlari_ekle(conn, range(45, 50))
    c._http = _SabitOturum({kimlik(n): [SahteYanit(200, jpeg())] for n in range(45, 50)}, 503)
    r2 = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)
    assert r2["indirilen"] == 5 and r2["zaten_var"] == 5 and not r2.get("ariza_denenmedi")
    assert not any("denenmedi" in s[4] for s in r2["acilamayan_ornek"])


def test_429_sonrasi_basari_sayaci_sifirlar(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 33))
    # 21 asılı (k1-k4, k10-k26), k27 önce 429 sonra iner, 4 asılı (k28-k31), k32 canlı: sayaç 25'e varmamalı
    c._http = _AsiliOturum({kimlik(27): [SahteYanit(429), SahteYanit(200, jpeg())], kimlik(32): [SahteYanit(200, jpeg())]})
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)
    assert r["indirilen"] == 2 and not r.get("ariza_denenmedi") and any(kimlik(32) in u for u in c._http.istekler)


def test_zaman_asimi_hizli_gecise_sayilir_birakmaya_sayilmaz(ortam, monkeypatch):
    # 'zaman_asimi': yanıt başlığı geldi ama gövde 30 sn'de bitmedi. Hızlı geçiş sayacına girer, ama "hiç yanıt yok" değildir:
    # Gyazo bırakılmaz, her bağlantı denenir; 30 sn'lik deneme yeniden de denenmez.
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    cagrilar = []

    def yavas(k):
        cagrilar.append(k)
        c._gyazo_son_durum = "zaman_asimi"
        return None

    monkeypatch.setattr(c, "gyazo_indir", yavas)
    uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=uykular.append, bekleme_sn=0.15)
    assert len(cagrilar) == 34 and r["hizli_gecis"] == ["Gyazo"] and not r.get("ariza") and not r.get("ariza_denenmedi")
    assert uykular.count(1) == 0 and uykular.count(0.15) == 33  # 34 denenen, sonuncusu son aday


def test_birakildiktan_sonra_onbellektekiler_zaten_var(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    c._http = _SabitOturum({kimlik(39): [SahteYanit(200, jpeg())]}, 404)
    assert gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)["indirilen"] == 1
    c._http = _AsiliOturum({})
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)
    assert r["zaten_var"] == 1 and r["ariza_denenmedi"] == {"Gyazo": 8} and not any(kimlik(39) in u for u in c._http.istekler)


def test_dis_serviste_erisim_de_arizaya_sayilir(tmp_path):
    # Gyazo yolu her istisnayı 'hata' sayar; 'erisim' yalnız dış servislerde görülür. Bağlantı kurulamayan (erisim) ile
    # asılı kalan (hata) bağlantılar sırayla gelince "art arda 3 erisim" atlaması devreye girmez; ikisi de arıza sayılmalı.
    from app import db
    from test_dis_gorsel_232 import URLOturum, ayar_yap
    a = ayar_yap(tmp_path)
    conn = db.baglan(a["DB"])
    plan = {}
    for i in range(30):
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link) VALUES(?,?,?,?)",
                     ("s%d" % i, "OF", str(i), "https://snappark.net/s/Er%02d" % i))
        hata = requests.exceptions.ConnectTimeout if i % 2 == 0 else requests.exceptions.ReadTimeout
        plan["https://img.snappark.net/s/Er%02d/raw/" % i] = [hata("sahte"), hata("sahte")]
    conn.commit()
    c = gorsel.GorselCozucu(a, a["ONBELLEK"])
    c._http = URLOturum(plan)
    r = gorsel.gyazo_toplu_indir(conn, c, a, uyku=lambda s: None, bekleme_sn=0)
    assert not r.get("dis_erisim_yok")
    assert len(c._http.istekler) == 10 * 2 + 15 and r["ariza"] == ["Snappark"] and r["ariza_denenmedi"] == {"Snappark": 5}


# ---- Hızlı geçiş ile arıza (bırakma) ayrıldı: silinmiş 503 birikimi + seyrek zaman aşımı sağlam Gyazo'yu bırakmaz (26 Kasım) ----
class _IstisnaliOturum(SahteOturum):
    """Planda olmayan kimlikler için sabit HTTP yanıtı; plandaki Exception örnekleri yükseltilir."""

    def __init__(self, plan, varsayilan=503):
        super().__init__(plan)
        self.varsayilan = varsayilan

    def get(self, url, **kw):
        assert kw.get("stream") is True and kw.get("allow_redirects") is False
        kim = url.rsplit("/", 1)[-1].split(".")[0]
        if not self.plan.get(kim):
            self.istekler.append(url)
            return SahteYanit(self.varsayilan)
        y = super().get(url, **kw)
        if isinstance(y, BaseException):
            raise y
        return y


def test_silinmis_503_birikimi_ve_seyrek_zaman_asimi_saglam_gyazoyu_birakmaz(ortam):
    # Gece planının olağan hali: önbellekte olmayanların çoğu silinmiş görsel (503); arada tek seferlik okuma zaman aşımları
    # (~%3) olur; canlı bağlantılar sondadır. Gyazo bırakılmamalı, canlılar inmeli, günlükte "muhtemelen ... arızası" olmamalı.
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, list(range(10, 806)) + list(range(900, 920)))  # fikstürdeki 4 + 796 = 800 ölü kimlik, 20 canlı
    plan = {kimlik(n): [requests.exceptions.ReadTimeout("geçici (sahte)"), SahteYanit(503)] for n in range(30, 806, 30)}
    plan.update({kimlik(n): [SahteYanit(200, jpeg())] for n in range(900, 920)})
    c._http = _IstisnaliOturum(plan, 503)
    loglar = []; uykular = []
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, yeni_en_cok=900, uyku=uykular.append, log=loglar.append, bekleme_sn=0.15)
    assert r["indirilen"] == 20 and r["bitis_nedeni"] == "tamam" and r["kalan"] == 0
    assert not r.get("ariza") and not r.get("ariza_denenmedi") and r["hizli_gecis"] == ["Gyazo"]
    assert not any("muhtemelen" in m for m in loglar)
    assert sum("bir kez daha denenmeden" in m for m in loglar) == 1
    assert all(any(kimlik(n) in u for u in c._http.istekler) for n in range(900, 920))
    # 820 ayrı kimlik denendi; son aday (k919) dışında her denemeden sonra bekleme var (hızlı geçişte de)
    assert r["denenen"] == 820 and uykular.count(0.15) == 820 - 1


def test_birakilan_kimligin_tekrar_satiri_ayni_sebebi_tasir_ve_denenmedi_sayilir(ortam):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    for anahtar, n in (("y1", 35), ("y2", 36)):  # bırakıldıktan sonra denenmeyen kimliklerin ikinci satırları
        conn.execute("INSERT INTO kayitlar(anahtar,proje,personel,link,link_turu) VALUES(?,?,?,?,?)",
                     (anahtar, "GA", "2", "https://gyazo.com/%s" % kimlik(n), "gyazo"))
    conn.commit()
    c._http = _AsiliOturum({})
    r = gorsel.gyazo_toplu_indir(conn, c, ayar, uyku=lambda s: None, bekleme_sn=0)
    assert r["ariza"] == ["Gyazo"] and r["ariza_denenmedi"] == {"Gyazo": 9 + 2}
    assert r["baglanti"] == r["kimliksiz"] + r["indirilen"] + r["zaten_var"] + r["acilamayan"] == 37
    satirlar = list(csv.reader(Path(r["rapor"]).read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))[1:]
    assert sum("Gyazo arızası sürüyor" in s[4] for s in satirlar) == 11
    assert [s[4] for s in satirlar].count("aynı bağlantı bu çalıştırmada açılamadı") == 1  # yalnız denenmiş k1'in tekrarı ("b")
    assert all("arızası sürüyor" in s[4] for s in satirlar if s[3].startswith("https://gyazo.com/") and s[1:3] == ["GA", "2"])


def _cli_ici(monkeypatch, capsys, ayar, oturum, argv):
    """cli.main()'i aynı süreçte çalıştırır: ayarlar fikstürden, HTTP sahte oturumdan, uykular kaydedilir (gerçek bekleme yok)."""
    from app import cli
    for anahtar, deger in ayar.items():
        monkeypatch.setitem(cli.AYAR, anahtar, deger)
    monkeypatch.setattr(gorsel.GorselCozucu, "_gyazo_http", lambda self: oturum)
    uykular = []
    monkeypatch.setattr(gorsel.time, "sleep", uykular.append)
    monkeypatch.setattr(sys, "argv", ["app.cli", "gyazo-onbellekle"] + list(argv))
    kod = 0
    try:
        cli.main()
    except SystemExit as e:
        kod = e.code
    return kod, capsys.readouterr().out, uykular


def test_cli_asili_gyazo_birakilir_ariza_satiri_ve_cikis_0(ortam, monkeypatch, capsys):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    oturum = _AsiliOturum({})
    kod, cikti, uykular = _cli_ici(monkeypatch, capsys, ayar, oturum, ["--yeni-en-cok", "900", "--on-kontrol-atla"])
    satirlar = cikti.splitlines()
    assert kod in (0, None) and satirlar[-1] == "GYAZO_ONBELLEK_TAMAM"
    assert len(oturum.istekler) == 10 * 2 + 15 and uykular.count(1) == 10
    assert ("ARIZA: Gyazo yanıt vermiyor (muhtemelen Gyazo arızası); 26 bağlantı açılamadı, 9 bağlantı denenmedi. "
            "Sonraki çalıştırmada (gece planı kuruluysa kendiliğinden) yeniden denenir.") in satirlar
    # gece günlüğü (ayrıntısız): hızlı geçiş ve bırakma satırları birer kez görünür, bağlantı başına satır yok
    assert sum("bir kez daha denenmeden" in s for s in satirlar) == 1
    assert sum("hiç yanıt alınamadı" in s and "muhtemelen Gyazo arızası" in s for s in satirlar) == 1
    assert not any("açılamadı: ağ hatası" in s or "geçici hata" in s for s in satirlar)


def test_cli_silinmis_503lerde_ariza_satiri_yok(ortam, monkeypatch, capsys):
    conn, c, ayar = ortam
    _gyazo_kayitlari_ekle(conn, range(10, 40))
    kod, cikti, _ = _cli_ici(monkeypatch, capsys, ayar, _SabitOturum({kimlik(39): [SahteYanit(200, jpeg())]}, 503),
                             ["--yeni-en-cok", "900", "--on-kontrol-atla"])
    satirlar = cikti.splitlines()
    assert kod in (0, None) and satirlar[-1] == "GYAZO_ONBELLEK_TAMAM"
    assert not any(s.startswith("ARIZA:") or "muhtemelen" in s for s in satirlar)
    assert sum("bir kez daha denenmeden" in s for s in satirlar) == 1


def test_cli_on_kontrol_yanitsizsa_yarim_ve_cikis_1(ortam, monkeypatch, capsys):
    conn, c, ayar = ortam
    oturum = _SabitOturum({}, requests.exceptions.ReadTimeout("okuma zaman aşımı (sahte)"))
    kod, cikti, uykular = _cli_ici(monkeypatch, capsys, ayar, oturum, ["--yeni-en-cok", "900"])
    assert kod == 1 and len(oturum.istekler) == 2 and uykular == [1]
    son = cikti.splitlines()[-1]
    assert son.startswith("GYAZO_ONBELLEK_YARIM: Gyazo'ya ulaşılamıyor (ReadTimeout")
    assert "dış HTTPS erişimi engelli" in son and "Gyazo arızalı" in son and "curl" in son
    assert "çıktı 000 ise" in son and "üç basamaklı başka bir sayı" in son
