# -*- coding: utf-8 -*-
"""Dagitim (deploy/): betik sozdizimi, kuru calisma (KANIT_KUR_DRY=1), systemd birimleri, env.ornek,
yedekle.sh + geri-yukle.sh gercek tur (gecici klasorde, sahte systemctl ile), kontrol.sh, belgeler.
Calistirma: cd kanit && python3 tests/test_deploy.py   (ya da python3 -m pytest -q tests/test_deploy.py)
Sunucuya ozgu adimlar (apt, useradd, gercek systemd, Plesk guvenlik duvari) burada DENENMEZ; yalnizca kuru ciktisi okunur."""
import os, sys, re, stat, shutil, sqlite3, subprocess, tempfile, datetime, gzip, tarfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from kanit import ayar, db

KANIT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEPO = os.path.abspath(os.path.join(KANIT_DIR, ".."))
DEPLOY = os.path.join(DEPO, "deploy")
BETIKLER = ["kur.sh", "guncelle.sh", "yedekle.sh", "geri-yukle.sh", "kontrol.sh"]
BIRIMLER = ["kanit-web.service", "kanit-bot.service"]
BELGELER = ["env.ornek", "ISLETME.md", "nginx-plesk.md"]

ok = 0


def check(cond, msg):
    global ok
    if cond:
        ok += 1
        print("  OK ", msg)
    else:
        print("  FAIL", msg)
        raise SystemExit(1)


def oku(ad):
    with open(os.path.join(DEPLOY, ad), encoding="utf-8") as f:
        return f.read()


def kos(args, env=None, cwd=None, girdi=""):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run(args, input=girdi, capture_output=True, text=True, env=e, cwd=cwd or DEPLOY, timeout=300)
    return p.returncode, p.stdout + p.stderr


def birim_coz(metin):
    """[Bolum] -> {anahtar: [degerler]} (Environment gibi tekrar eden anahtarlar icin liste)."""
    d, bolum = {}, None
    for ln in metin.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            bolum = ln.strip("[]"); d.setdefault(bolum, {}); continue
        k, v = ln.split("=", 1)
        d[bolum].setdefault(k.strip(), []).append(v.strip())
    return d


def sahte_bin(td):
    """PATH'in basina konacak sahte systemctl (gercek systemd yok)."""
    b = os.path.join(td, "bin"); os.makedirs(b, exist_ok=True)
    yol = os.path.join(b, "systemctl")
    with open(yol, "w") as f:
        f.write('#!/usr/bin/env bash\necho "systemctl $*" >> "$SAHTE_LOG"\n'
                'case "$1" in\n  is-active) echo inactive; exit 3 ;;\n  is-enabled) echo disabled; exit 1 ;;\n'
                '  show) echo ""; exit 0 ;;\n  *) exit 0 ;;\nesac\n')
    os.chmod(yol, 0o755)
    return b


def kok_kur(td):
    """Gecici /opt/kanit benzeri: src -> depo (symlink), venv/bin/python -> bu python, .env, veri."""
    kok = os.path.join(td, "kok")
    os.makedirs(os.path.join(kok, "src"), exist_ok=True)
    os.symlink(KANIT_DIR, os.path.join(kok, "src", "kanit"))
    os.symlink(DEPLOY, os.path.join(kok, "src", "deploy"))
    os.makedirs(os.path.join(kok, "venv", "bin"))
    os.symlink(sys.executable, os.path.join(kok, "venv", "bin", "python"))
    veri = os.path.join(kok, "veri")
    for alt in ("", "gorseller/OF", "onbellek/thumbs", "yedek", "log", "gecici"):
        os.makedirs(os.path.join(veri, alt), exist_ok=True)
    with open(os.path.join(kok, ".env"), "w") as f:
        f.write(f"VERI={veri}\nPORT=8080\nDINLE=127.0.0.1\nTELEGRAM_TOKEN=123:abc\nBOT_PASSWORD=gizli\nTZ=Europe/Istanbul\n")
    os.chmod(os.path.join(kok, ".env"), 0o600)
    with open(os.path.join(kok, "kaynak.txt"), "w") as f:
        f.write(f"kopya {DEPO}\n")
    return kok, veri


def calistir():
    import pwd
    ben = pwd.getpwuid(os.getuid()).pw_name
    td = tempfile.mkdtemp(prefix="kanit-deploy-")
    sahte = sahte_bin(td)
    ortak_env = {"KANIT_KULLANICI": ben, "PATH": sahte + os.pathsep + os.environ.get("PATH", ""), "SAHTE_LOG": os.path.join(td, "systemctl.log")}

    print("-- dosyalar, ASCII, sozdizimi")
    for ad in BETIKLER + BIRIMLER + BELGELER:
        yol = os.path.join(DEPLOY, ad)
        check(os.path.isfile(yol), f"var: deploy/{ad}")
        with open(yol, "rb") as f:
            ham = f.read()
        check(all(b < 128 for b in ham), f"ASCII: {ad}")
        check(b"\r" not in ham, f"LF satir sonu: {ad}")
    for ad in BETIKLER:
        yol = os.path.join(DEPLOY, ad)
        check(os.stat(yol).st_mode & stat.S_IXUSR, f"calistirilabilir: {ad}")
        check(oku(ad).startswith("#!/usr/bin/env bash\n"), f"shebang: {ad}")
        rc, out = kos(["bash", "-n", yol]); check(rc == 0, f"bash -n: {ad} {out.strip()}")
        rc, out = kos(["bash", yol, "--help"], env=ortak_env); check(rc == 0 and "Kanit" in out, f"--help: {ad}")
        rc, out = kos(["bash", yol, "--boyle-bir-secenek-yok"], env=ortak_env); check(rc == 2, f"bilinmeyen secenek -> 2: {ad}")
    if shutil.which("shellcheck"):
        rc, out = kos(["shellcheck", "-S", "style"] + [os.path.join(DEPLOY, b) for b in BETIKLER])
        check(rc == 0, "shellcheck temiz" + ("" if rc == 0 else "\n" + out))
    else:
        print("  (shellcheck yok, atlandi)")

    print("-- systemd birimleri")
    for ad in BIRIMLER:
        u = birim_coz(oku(ad)); s = u["Service"]
        kisa = ad.split(".")[0].split("-")[1]   # web | bot
        check(s["ExecStart"] == [f"/opt/kanit/venv/bin/python -m kanit {kisa}"], f"{ad} ExecStart")
        check(s["User"] == ["kanit"] and s["WorkingDirectory"] == ["/opt/kanit/src/kanit"] and s["EnvironmentFile"] == ["/opt/kanit/.env"], f"{ad} User/WorkingDirectory/EnvironmentFile")
        check(s["Restart"] == ["always"] and s["RestartSec"] == ["5"], f"{ad} Restart=always RestartSec=5")
        check(s["StandardOutput"] == [f"append:/opt/kanit/veri/log/{kisa}.log"] and s["StandardError"] == s["StandardOutput"], f"{ad} log append")
        check("/opt/kanit/veri" in s.get("ReadWritePaths", []) and s.get("NoNewPrivileges") == ["true"], f"{ad} sertlestirme")
        check(u["Install"]["WantedBy"] == ["multi-user.target"] and "network-online.target" in u["Unit"]["After"][0], f"{ad} Install/After")
    check("kanit-web.service" in birim_coz(oku("kanit-bot.service"))["Unit"]["After"][0], "bot, web'den sonra")
    if shutil.which("systemd-analyze"):
        rc, out = kos(["systemd-analyze", "verify", "--man=no"] + ["./" + b for b in BIRIMLER])
        kalan = [ln for ln in out.splitlines() if ln.strip() and "/opt/kanit/venv/bin/python" not in ln]
        check(not kalan, "systemd-analyze verify (venv yolu disinda uyari yok)" + ("" if not kalan else "\n" + "\n".join(kalan)))
    else:
        print("  (systemd-analyze yok, atlandi)")

    print("-- env.ornek")
    ornek = ayar._dosya_oku(os.path.join(DEPLOY, "env.ornek"))
    check(set(ornek) <= set(ayar.VARSAYILAN), f"env.ornek anahtarlari ayar.VARSAYILAN icinde ({sorted(set(ornek) - set(ayar.VARSAYILAN))})")
    for k in ("VERI", "PORT", "DINLE", "TELEGRAM_TOKEN", "GYAZO_TOKEN", "BOT_PASSWORD", "ADMIN_IDS", "GUVENILIR_PROXY", "HTTPS", "TZ"):
        check(k in ornek, f"env.ornek {k}")
    eski = dict(os.environ)
    os.environ["KANIT_ENV"] = os.path.join(DEPLOY, "env.ornek"); os.environ["KANIT_VERI"] = os.path.join(td, "veri-ornek")
    for k in ("PORT", "TELEGRAM_TOKEN", "VERI"):
        os.environ.pop(k, None)
    a = ayar.yukle()
    os.environ.clear(); os.environ.update(eski)
    check(a["PORT"] == 8080 and a["DINLE"] == "0.0.0.0" and a["ADMIN_IDS"] == [] and a["TZ"] == "Europe/Istanbul" and a["VERI"] == os.path.join(td, "veri-ornek"), "env.ornek ayar.yukle ile okunuyor")

    print("-- kur.sh kuru calisma (kopya ve git modu)")
    kuru_kok = os.path.join(td, "kuru-kok")
    rc, out = kos(["bash", "kur.sh", "--sessiz"], env=dict(ortak_env, KANIT_KUR_DRY="1", KANIT_KOK=kuru_kok, KANIT_KULLANICI="kanit"))
    check(rc == 0, f"kur.sh --sessiz kuru -> 0 (rc={rc})")
    check(not os.path.exists(kuru_kok) and not os.path.exists("/etc/cron.d/kanit-yedek-test"), "kuru calisma hicbir sey olusturmadi")
    for bekle in ("KURU CALISMA", "useradd --system", f"rsync -a --delete", f"{kuru_kok}/src/kanit/", "-m venv", "pip install --quiet -r",
                  f"dosya yazilacak: {kuru_kok}/.env (kanit:kanit, 0600", "/etc/systemd/system/kanit-web.service", "/etc/systemd/system/kanit-bot.service",
                  "systemctl daemon-reload", "systemctl enable --quiet kanit-web.service", "systemctl start kanit-web.service", "systemctl disable --quiet kanit-bot.service",
                  "/etc/cron.d/kanit-yedek", "/etc/logrotate.d/kanit", "TCP 8080", "kullanici-ekle admin admin", "-m kanit saglik",
                  "KURULUM TAMAM", ":8080", "KONTROL LISTESI", "ice-aktar --kuru", "ice-aktar --uygula", "systemctl enable --now kanit-bot"):
        check(bekle in out, f"kuru cikti: {bekle!r}")
    check("[KURU] systemctl enable --quiet --now kanit-bot.service" not in out, "bot ilk kurulumda baslatilmiyor")
    rc, out = kos(["bash", "kur.sh", "--sessiz", "--bot-baslat", "--admin", "patron", "--port", "8090", "--repo", "https://ornek.invalid/kote.git", "--dal", "main"],
                  env=dict(ortak_env, KANIT_KUR_DRY="1", KANIT_KOK=kuru_kok))
    check(rc == 0 and f"git clone --quiet --branch main https://ornek.invalid/kote.git {kuru_kok}/src" in out, "git modu: clone --branch")
    check("rsync -a" not in out and "kullanici-ekle patron admin" in out and "TCP 8090" in out and ":8090" in out and "enable --quiet --now kanit-bot.service" in out and "su an ACIK" in out, "git modu: --admin/--port/--bot-baslat")
    rc, out = kos(["bash", os.path.join(DEPLOY, "kur.sh"), "--sessiz"], env=dict(ortak_env, KANIT_KUR_DRY="1", KANIT_KOK=kuru_kok), cwd=td)
    check(rc == 0, "kur.sh baska klasorden cagrilsa da kaynagi kendi yanindan bulur")
    rc, out = kos(["bash", "kur.sh", "--sessiz"], env=dict(ortak_env, KANIT_KUR_DRY="1", KANIT_KOK=kuru_kok), girdi="")
    check(rc == 0, "stdin tty degilken soru sormuyor")

    print("-- yedekle.sh / geri-yukle.sh gercek tur (gecici kok)")
    kok, veri = kok_kur(td)
    env = dict(ortak_env, KANIT_KOK=kok)
    conn = db.baglan(os.path.join(veri, "kanit.db"))
    db.ayar_yaz(conn, "deneme", "ilk")
    k = db.kayit_ekle(conn, {"proje": "OF", "kategori": "ARK", "personel": "215", "uye_id": "4956", "link": "https://gyazo.com/" + "a" * 32, "ekleyen_tg_id": "1", "ekleyen_ad": "ali"}, kim="bot")
    with open(os.path.join(veri, "gorseller", "OF", "a.png"), "wb") as f:
        f.write(b"\x89PNG" + b"0" * 50)
    eski_yedek = os.path.join(veri, "yedek", "2020-01-01"); os.makedirs(eski_yedek)
    eskizaman = time.time() - 40 * 86400; os.utime(eski_yedek, (eskizaman, eskizaman))
    rc, out = kos(["bash", "yedekle.sh"], env=env)
    bugun = datetime.date.today().isoformat(); hedef = os.path.join(veri, "yedek", bugun)
    check(rc == 0, f"yedekle.sh -> 0\n{out}" if rc else "yedekle.sh -> 0")
    check(os.path.isfile(os.path.join(hedef, "kanit.db.gz")) and os.path.isfile(os.path.join(hedef, "gorseller.tar.gz")) and os.path.isfile(os.path.join(hedef, "SHA256SUMS")), f"yedek klasoru {bugun}: db.gz + gorseller.tar.gz + SHA256SUMS")
    check(stat.S_IMODE(os.stat(os.path.join(hedef, "env.600")).st_mode) == 0o600, "env.600 izni 600")
    with open(os.path.join(veri, "yedek", "SON")) as f:
        check(f.read().strip() == bugun, "SON dosyasi bugunu gosteriyor")
    check(not os.path.exists(eski_yedek), "40 gunluk yedek silindi")
    with gzip.open(os.path.join(hedef, "kanit.db.gz"), "rb") as g, open(os.path.join(td, "acik.db"), "wb") as f:
        f.write(g.read())
    c2 = sqlite3.connect(os.path.join(td, "acik.db"))
    check(c2.execute("SELECT deger FROM ayarlar WHERE anahtar='deneme'").fetchone()[0] == "ilk" and c2.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] == 1, "yedekteki db tutarli")
    c2.close()
    with tarfile.open(os.path.join(hedef, "gorseller.tar.gz")) as t:
        check("gorseller/OF/a.png" in t.getnames(), "gorseller.tar.gz goreli yol gorseller/OF/...")
    rc, out = kos(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=hedef); check(rc == 0, "SHA256SUMS dogru")
    rc, out = kos(["bash", "yedekle.sh", "--sadece-db"], env=env)
    check(rc == 0 and "--sadece-db" in out and os.path.isfile(os.path.join(hedef, "kanit.db.gz")), "yedekle.sh --sadece-db")
    check("yedek basliyor" in out and re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", out), "yedek logu zaman damgali")
    rc, out = kos(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=hedef); check(rc == 0, "ayni gun ikinci yedekte SHA256SUMS yine dogru (kendini listelemiyor)")
    with open(os.path.join(hedef, "SHA256SUMS")) as f:
        sums = f.read()
    check("SHA256SUMS" not in sums and "gorseller.tar.gz" in sums and "kanit.db.gz" in sums, "SHA256SUMS icinde kendisi yok, dosyalar var")
    # degisiklik -> geri yukle
    db.ayar_yaz(conn, "deneme", "sonra")
    with open(os.path.join(veri, "gorseller", "OF", "b.png"), "wb") as f:
        f.write(b"\x89PNG" + b"1" * 50)
    conn.close()
    rc, out = kos(["bash", "geri-yukle.sh"], env=env)
    check(rc == 2 and bugun in out and "Kullanim" in out, "geri-yukle.sh parametresiz: liste + 2")
    rc, out = kos(["bash", "geri-yukle.sh", bugun], env=env, girdi="hayir\n")
    check(rc == 1 and "vazgecildi" in out, "onay verilmeyince vazgeciyor")
    rc, out = kos(["bash", "geri-yukle.sh", bugun, "--evet"], env=env)
    check(rc == 0, f"geri-yukle.sh --evet -> 0\n{out}" if rc else "geri-yukle.sh --evet -> 0")
    c3 = sqlite3.connect(os.path.join(veri, "kanit.db"))
    check(c3.execute("SELECT deger FROM ayarlar WHERE anahtar='deneme'").fetchone()[0] == "ilk", "veritabani yedekteki haline dondu")
    c3.close()
    check(os.path.isfile(os.path.join(veri, "gorseller", "OF", "a.png")) and not os.path.exists(os.path.join(veri, "gorseller", "OF", "b.png")), "gorseller yedekteki haline dondu")
    oncesi = [d for d in os.listdir(os.path.join(veri, "yedek")) if d.startswith("geri-yukleme-oncesi-")]
    check(len(oncesi) == 1 and os.path.isfile(os.path.join(veri, "yedek", oncesi[0], "kanit.db")) and os.path.isfile(os.path.join(veri, "yedek", oncesi[0], "gorseller", "OF", "b.png")), "eski veri kenara alindi")
    with open(os.path.join(td, "systemctl.log")) as f:
        sl = f.read()
    check("systemctl stop kanit-bot.service kanit-web.service" in sl and "systemctl start kanit-web.service" in sl, "servisler durduruldu / baslatildi")
    check("systemctl start kanit-bot.service" not in sl, "bot kapaliysa kapali kaliyor")
    rc, out = kos(["bash", "geri-yukle.sh", bugun, "--evet", "--sadece-db"], env=env)
    check(rc == 0 and len([d for d in os.listdir(os.path.join(veri, "yedek")) if d.startswith("geri-yukleme-oncesi-")]) >= 1, "geri-yukle --sadece-db")
    rc, out = kos(["bash", "geri-yukle.sh", "2019-01-01", "--evet"], env=env)
    check(rc == 1 and "yok" in out, "olmayan yedek -> hata")

    print("-- kontrol.sh ve guncelle.sh (kuru)")
    rc, out = kos(["bash", "kontrol.sh", "--hata", "3"], env=env)
    for bekle in ("KANIT MERKEZI KONTROL", "Servisler", "kanit-web", "Disk", "Yedek", f"son yedek {bugun}", "Ayar dosyasi", ".env izni 600", "TELEGRAM_TOKEN yazili", "Son hatalar", "Sonuc"):
        check(bekle in out, f"kontrol.sh: {bekle!r}")
    check(rc == 1 and "SORUN" in out, "kontrol.sh servis yokken 1 ile cikiyor")
    rc, out = kos(["bash", "guncelle.sh"], env=dict(env, KANIT_KUR_DRY="1"))
    check(rc == 0 and "rsync -a --delete" in out and "pip install --quiet -r" in out and "systemctl restart kanit-web.service" in out and "-m kanit saglik" in out, "guncelle.sh kuru (kopya modu)")
    with open(os.path.join(kok, "kaynak.txt"), "w") as f:
        f.write("git https://ornek.invalid/kote.git main\n")
    rc, out = kos(["bash", "guncelle.sh"], env=dict(env, KANIT_KUR_DRY="1"))
    check(rc == 0 and "git -C" in out and "checkout --quiet main" in out and "pull --ff-only" in out, "guncelle.sh kuru (git modu)")

    print("-- belgeler")
    i = oku("ISLETME.md")
    for bekle in ("/opt/kanit/gelen", "scp", "unzip", "ice-aktar --kuru", "ice-aktar --uygula", "/bakim_ac", "excel-ekle", "Revoke", "TELEGRAM_TOKEN", "systemctl restart kanit-bot",
                  "03:15", "30 gun", "rclone", "geri-yukle.sh", "kullanici-ekle", "sifre-sifirla", "Bot yanit vermiyor", "409", "Disk doldu", "Token sizdi", "Port ya da alan adi",
                  "VERI SAKLAMA", "silinmez", "nginx-plesk.md", "kontrol.sh", "guncelle.sh"):
        check(bekle in i, f"ISLETME.md: {bekle!r}")
    n = oku("nginx-plesk.md")
    for bekle in ("proxy_pass         http://127.0.0.1:8080", "X-Forwarded-For", "X-Forwarded-Proto", "client_max_body_size 25m", "Proxy mode", "Ek nginx yonergeleri",
                  "DINLE=127.0.0.1", "GUVENILIR_PROXY=1", "HTTPS=1", "Let's Encrypt", "Cloudflare", "plesk.page", "DOKUNULMAZ"):
        check(bekle in n, f"nginx-plesk.md: {bekle!r}")
    for b in ("kur.sh", "yedekle.sh", "geri-yukle.sh", "guncelle.sh"):
        check("KANIT_KUR_DRY" in oku(b) and "--kuru" in oku(b), f"{b} kuru calisma anahtari (KANIT_KUR_DRY / --kuru)")
    check("KANIT_KUR_DRY" not in oku("kontrol.sh") and "systemctl restart" not in oku("kontrol.sh"), "kontrol.sh salt okunur")
    check("plesk ext firewall --add" in oku("kur.sh") and "ufw allow" in oku("kur.sh"), "kur.sh: Plesk firewall + ufw yedegi")
    check("15 3 * * * root" in oku("kur.sh") and "yedekle.sh" in oku("kur.sh"), "kur.sh: cron 03:15")

    shutil.rmtree(td, ignore_errors=True)
    print(f"\nDAGITIM TESTLERI GECTI ({ok})")


if __name__ == "__main__":
    calistir()
else:
    def test_deploy():
        calistir()
