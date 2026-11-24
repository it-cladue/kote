"""DOSYA_DOGRULAMA.sha256 manifestinin paketle birlikte güncel kalmasını kilitler.

KURULUM_ADIMLARI adım 0'daki `sha256sum -c --quiet DOSYA_DOGRULAMA.sha256` denetimi, manifest
eski kalmışsa teslim edilen paketle deterministik olarak başarısız olur (2.3.0 QA turu bulgusu).
Test yalnız temiz bir git çalışma ağacında (sunucu/ altında commit edilmemiş değişiklik yokken)
koşar: geliştirme sırasında engel olmaz, ama commit edilmiş hâlde manifest eskiyse kırmızı yanar.
Kurulu dizinlerde (/opt/kanit-paneli gibi, git yok) atlanır.

Yenileme komutu (sunucu/ içinde):
  git ls-files | grep -vx DOSYA_DOGRULAMA.sha256 | LC_ALL=C sort | xargs sha256sum -- > DOSYA_DOGRULAMA.sha256
"""
import pathlib
import subprocess

import pytest

KOK = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = KOK / "DOSYA_DOGRULAMA.sha256"
YENILE = "git ls-files | grep -vx DOSYA_DOGRULAMA.sha256 | LC_ALL=C sort | xargs sha256sum -- > DOSYA_DOGRULAMA.sha256"


def _git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=KOK, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return r.returncode == 0, r.stdout


@pytest.fixture(scope="module")
def temiz_git_agaci():
    ok, out = _git("rev-parse", "--is-inside-work-tree")
    if not ok or out.strip() != "true":
        pytest.skip("git çalışma ağacı değil (kurulu dizin); manifest denetimi paket adım 0'da yapılır")
    ok, out = _git("status", "--porcelain", "--", ".")
    if not ok:
        pytest.skip("git status çalışmadı")
    if out.strip():
        pytest.skip("sunucu/ altında commit edilmemiş değişiklik var; manifest denetimi yalnız temiz ağaçta koşar")


def test_manifest_hashleri_guncel(temiz_git_agaci):
    assert MANIFEST.exists(), "DOSYA_DOGRULAMA.sha256 yok"
    r = subprocess.run(["sha256sum", "-c", "--quiet", MANIFEST.name], cwd=KOK, capture_output=True, text=True)
    assert r.returncode == 0, "DOSYA_DOGRULAMA.sha256 eski; yenile: " + YENILE + "\n" + r.stdout + r.stderr


def test_manifest_dosya_kumesi_tam(temiz_git_agaci):
    ok, out = _git("ls-files")
    assert ok
    beklenen = {p for p in out.split("\n") if p and p != MANIFEST.name}
    listelenen = set()
    for satir in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not satir.strip():
            continue
        assert "  " in satir, f"beklenmeyen manifest satırı: {satir!r}"
        listelenen.add(satir.split("  ", 1)[1].lstrip("*"))
    assert listelenen == beklenen, (
        f"manifestte eksik: {sorted(beklenen - listelenen)}; fazla: {sorted(listelenen - beklenen)}; yenile: {YENILE}"
    )
