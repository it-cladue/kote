"""QA düzeltme turu (2.3.0): deploy betikleri — güvenlik duvarı hata yolu, dolmuş IP sertifikasıyla birim güncellemesi,
SQLite geri yükleme (--geri-yukle), rsync 23/24 toleransı, snapshot yan dosyaları, bot açılış uyarısı, configure-bot --yonetici.

Hiçbir test /opt/kanit-paneli'ne, gerçek systemctl/ufw/rsync'e veya sistem dizinlerine dokunmaz; sahte komutlar ve
KANIT_* geçersiz kılmalarıyla geçici dizinlerde prova edilir. Araç/yetki yoksa ilgili test atlanır.
"""
import gzip
import os
import pwd
import shutil
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from test_guvenlik_deploy import (DEPLOY, NGINX, ROOT, SUNUCU, guncelleme_ortami, ip_proxy_ortami,  # noqa: F401 (fixture'lar)
                                  kanit_tmp, kanit_var, run, sahte_panel)


def _yardimci():
    import importlib.util
    spec = importlib.util.spec_from_file_location("update_support", DEPLOY / "update-support.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- setup-firewall.sh: kural hatası -> enable yok
@pytest.mark.skipif(not ROOT, reason="root gerekir")
def test_setup_firewall_kural_hatasi_ufw_etkinlestirmez(tmp_path):
    (tmp_path / "sshd_config").write_text("Port 22\n")
    (tmp_path / "d").mkdir()
    ufw_log = tmp_path / "ufw.log"
    ufw = tmp_path / "ufw"
    # 443 kuralı başarısız olsun (gerçek ufw'nin sözdizimi hatası gibi).
    ufw.write_text(f"#!/bin/bash\nprintf '%d %s\\n' \"$#\" \"$*\" >> {ufw_log}\n[[ $1 == status ]] && echo 'Status: inactive'\n"
                   "if [[ $2 == 443/tcp ]]; then echo 'ERROR: Invalid syntax' >&2; exit 1; fi\nexit 0\n")
    ufw.chmod(0o755)
    env = {"KANIT_SSHD_CONFIG": str(tmp_path / "sshd_config"), "KANIT_SSHD_CONFIG_D": str(tmp_path / "d"), "KANIT_UFW": str(ufw)}
    r = run(["bash", str(DEPLOY / "setup-firewall.sh"), "--uygula"], env=env)
    assert r.returncode == 1 and "GUVENLIK_DUVARI_TAMAM" not in r.stdout, r.stdout + r.stderr
    assert "ufw ETKİNLEŞTİRİLMEDİ" in r.stderr and "'ufw enable' YAPMAYIN" in r.stderr and "allow 443/tcp comment HTTPS" in r.stderr, r.stderr
    cagrilar = [s for s in ufw_log.read_text().splitlines() if not s.split(" ", 1)[1].startswith("status")]
    assert cagrilar == ["4 allow 22/tcp comment SSH", "4 allow 80/tcp comment HTTP", "4 allow 443/tcp comment HTTPS"], cagrilar
    assert not any("enable" in c or "default" in c for c in cagrilar), "hatadan sonra enable/default politika çağrılmamalı"
    # Plan modu (bayraksız) ufw'ye yalnız status ile dokunur ve sıra: kurallar -> default -> enable
    r = run(["bash", str(DEPLOY / "setup-firewall.sh")], env=env)
    assert r.returncode == 0 and "PLAN_YAZILDI" in r.stdout
    plan = [s for s in r.stdout.splitlines() if s.startswith("ufw ")]
    assert plan[0] == "ufw allow 22/tcp comment SSH" and plan[-3:] == ["ufw default deny incoming", "ufw default allow outgoing", "ufw --force enable"], plan


# ---------------------------------------------------------------- setup-ip-https.sh --servis-guncelle: dolmuş sertifika
def dolmus_sertifika_uret(dizin, san):
    """openssl ca ile geçmiş tarihli (dolmuş) öz imzalı sertifika: canlıdaki dolmuş Let's Encrypt IP sertifikasının karşılığı."""
    dizin.mkdir(parents=True, exist_ok=True)
    cfg = dizin / "ca.cnf"
    cfg.write_text(textwrap.dedent(f"""
        [ ca ]
        default_ca = k
        [ k ]
        dir = {dizin}
        database = $dir/index.txt
        new_certs_dir = $dir
        serial = $dir/serial
        default_md = sha256
        policy = p
        x509_extensions = ext
        unique_subject = no
        [ p ]
        commonName = supplied
        [ ext ]
        subjectAltName = {san}
        basicConstraints = CA:FALSE
        [ req ]
        distinguished_name = dn
        prompt = no
        [ dn ]
        CN = 217.156.123.36
    """))
    (dizin / "index.txt").write_text("")
    (dizin / "serial").write_text("01\n")
    key, csr, pem = dizin / "privkey.pem", dizin / "req.csr", dizin / "fullchain.pem"
    run(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-config", str(cfg)], check=True)
    run(["openssl", "ca", "-batch", "-config", str(cfg), "-selfsign", "-keyfile", str(key), "-in", str(csr), "-out", str(pem), "-notext",
         "-startdate", "20261018000000Z", "-enddate", "20261024000000Z"], check=True)
    assert run(["openssl", "x509", "-in", str(pem), "-checkend", "0", "-noout"]).returncode == 1, "sertifika dolmuş olmalı"
    return pem, key


def test_setup_ip_https_servis_guncelle_dolmus_sertifikayla_calisir(ip_proxy_ortami):
    kok, env, port = ip_proxy_ortami
    betik = str(DEPLOY / "setup-ip-https.sh")
    r = run(["bash", betik], env=env)
    assert r.returncode == 0 and "HTTPS_SAGLIK_OK" in r.stdout, r.stdout + r.stderr
    unit = kok / "units" / "kanit-ip-proxy.service"
    metin = unit.read_text()
    # Canlı durum: IP sertifikası dolmuş (yenilenmiyor), birim eski/sertleştirilmemiş.
    live = kok / "ssl" / "config" / "live" / "kanit-ip"
    pem, key = dolmus_sertifika_uret(kok / "dolmus", "IP:217.156.123.36")
    shutil.copy(pem, live / "fullchain.pem")
    shutil.copy(key, live / "privkey.pem")
    unit.write_text(metin.replace("CapabilityBoundingSet=CAP_NET_BIND_SERVICE", "CapabilityBoundingSet="))
    log = kok / "systemctl.log"
    log.write_text("")
    # Üretimde CURL_EXTRA boştur; betik bu yolda doğrulamayı kendisi kapatır (-k), gövde 'OK' şartı sürer.
    r = run(["bash", betik, "--servis-guncelle"], env=dict(env, KANIT_CURL_EXTRA=""))
    assert r.returncode == 0 and "BIRIM_GUNCELLENDI" in r.stdout and "sağlık OK" in r.stdout, r.stdout + r.stderr
    assert "IP sertifikası dolmuş" in r.stdout and "Oct 24 00:00:00 2026" in r.stdout, r.stdout
    assert unit.read_text() == metin, "sertleştirilmiş birim kalmalı (geri alma olmamalı)"
    assert "geri yükleniyor" not in r.stderr
    sira = [s for s in log.read_text().splitlines() if "restart" in s]
    assert len(sira) == 1, "tek restart (geri alma restart'ı olmamalı): " + log.read_text()
    assert run(["curl", "-sk", "--noproxy", "*", "--max-time", "5", "--resolve", f"217.156.123.36:{port}:127.0.0.1",
                f"https://217.156.123.36:{port}/saglik"]).stdout == "OK"
    # Geçerli sertifikayla not satırı yazılmaz, idempotent
    r = run(["bash", betik, "--servis-guncelle"], env=dict(env, KANIT_CURL_EXTRA=""))
    assert r.returncode == 0 and "BIRIM_GUNCEL:" in r.stdout


# ---------------------------------------------------------------- kanit-yedek.sh --geri-yukle
def _yedek_ortami(kok):
    app = kok / "app"
    data = app / "data"
    data.mkdir(parents=True)
    (app / ".env").write_text("A=1\n")
    c = sqlite3.connect(data / "panel.db")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE kayitlar(id INTEGER PRIMARY KEY, x TEXT)")
    c.executemany("INSERT INTO kayitlar(x) VALUES (?)", [("eski",)] * 42)
    c.commit()
    c.close()
    yedek = kok / "yedek"
    (yedek / "gunluk").mkdir(parents=True)
    # "dünkü" yedek: backup API + DELETE modu (kanit-yedek.sh'ın yaptığı gibi), gzip
    duz = kok / "panel-dun.db"
    s = sqlite3.connect(data / "panel.db")
    d = sqlite3.connect(duz)
    s.backup(d)
    d.execute("PRAGMA journal_mode=DELETE")
    d.close()
    s.close()
    gz = yedek / "gunluk" / "panel-20260101.db.gz"
    with gzip.open(gz, "wb") as f:
        f.write(duz.read_bytes())
    # canlı DB ilerler (52 kayıt) ve servis kapanışında WAL/SHM yan dosyaları kalmış olsun
    c = sqlite3.connect(data / "panel.db")
    c.executemany("INSERT INTO kayitlar(x) VALUES (?)", [("yeni",)] * 10)
    c.commit()
    c.close()
    (data / "panel.db-wal").write_bytes(b"bayat wal")
    (data / "panel.db-shm").write_bytes(b"bayat shm")
    if kanit_var():
        subprocess.run(["chown", "-R", "kanit:kanit", str(data)], check=True)
    log = kok / "systemctl.log"
    fake = kok / "systemctl"
    fake.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "systemctl $*" >> "{log}"
        a=(); for x in "$@"; do case "$x" in --quiet|--now|--no-pager) ;; *) a+=("$x");; esac; done
        case "${{a[0]:-}}" in
          is-active|is-enabled) [[ ${{a[1]:-}} == kanit-web ]] && exit 0; exit 3;;
          *) exit 0;;
        esac
    '''))
    fake.chmod(0o755)
    env = {"KANIT_APP": str(app), "KANIT_PY": sys.executable, "KANIT_YEDEK_KOK": str(yedek), "KANIT_SYSTEMCTL": str(fake),
           "KANIT_ONCEKI_KOK": str(kok / "onceki")}
    if not kanit_var():
        env["KANIT_USER"] = "kanit-yok"
    return app, data, yedek, gz, log, env


def _sayi(db, deger=None):
    c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        if deger is None:
            return c.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM kayitlar WHERE x=?", (deger,)).fetchone()[0]
    finally:
        c.close()


@pytest.mark.skipif(not ROOT, reason="root gerekir")
def test_kanit_yedek_geri_yukle(kanit_tmp):
    kok = kanit_tmp
    app, data, yedek, gz, log, env = _yedek_ortami(kok)
    betik = str(DEPLOY / "kanit-yedek.sh")
    assert _sayi(data / "panel.db") == 52
    # dosya yok / argüman yok / dry-run: hiçbir şeye dokunulmaz
    r = run(["bash", betik, "--geri-yukle", str(yedek / "gunluk" / "panel-yok.db.gz")], env=env)
    assert r.returncode == 1 and "bulunamadı" in r.stderr and not log.exists()
    r = run(["bash", betik, "--geri-yukle"], env=env)
    assert r.returncode == 2 and "yedek dosyası" in r.stderr
    r = run(["bash", betik, "--geri-yukle", str(gz), "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout and "Plan:" in r.stdout and not log.exists(), r.stdout + r.stderr
    assert (data / "panel.db-wal").exists() and _sayi(data / "panel.db") == 52
    # bozuk gzip / sqlite olmayan içerik / kayitlar tablosu olmayan DB: YEDEK_BOZUK, servislere ve DB'ye dokunulmaz
    bozuk = yedek / "gunluk" / "panel-29990101.db.gz"
    bozuk.write_bytes(b"bozuk gzip degil")
    r = run(["bash", betik, "--geri-yukle", str(bozuk)], env=env)
    assert r.returncode == 1 and "YEDEK_BOZUK" in r.stderr and "dokunulmadı" in r.stderr, r.stderr
    with gzip.open(bozuk, "wb") as f:
        f.write(b"bu bir sqlite dosyasi degil" * 100)
    r = run(["bash", betik, "--geri-yukle", str(bozuk)], env=env)
    assert r.returncode == 1 and "YEDEK_BOZUK" in r.stderr, r.stderr
    bos = kok / "bos.db"
    c = sqlite3.connect(bos)
    c.execute("CREATE TABLE baska(id)")
    c.commit()
    c.close()
    with gzip.open(bozuk, "wb") as f:
        f.write(bos.read_bytes())
    r = run(["bash", betik, "--geri-yukle", str(bozuk)], env=env)
    assert r.returncode == 1 and "YEDEK_BOZUK" in r.stderr and "kayitlar" in r.stderr, r.stderr
    assert not log.exists(), "doğrulama başarısızken servislere dokunulmamalı: " + (log.read_text() if log.exists() else "")
    assert _sayi(data / "panel.db") == 52 and (data / "panel.db-wal").exists() and not list(data.glob(".kanit-geri-yukle-*"))
    assert not (kok / "onceki").exists()
    # gerçek geri yükleme
    r = run(["bash", betik, "--geri-yukle", str(gz)], env=env)
    assert r.returncode == 0 and "GERI_YUKLEME_TAMAM" in r.stdout and "Yedek doğrulandı" in r.stdout, r.stdout + r.stderr
    sira = log.read_text().splitlines()
    assert sira == ["systemctl is-active --quiet kanit-web", "systemctl stop kanit-web", "systemctl is-active --quiet kanit-bot",
                    "systemctl is-enabled --quiet kanit-bot", "systemctl stop kanit-bot", "systemctl start kanit-web"], sira
    assert "kanit-bot" not in r.stdout.split("Başlatılan:")[1], "kapalı ve devre dışı bot başlatılmaz"
    assert _sayi(data / "panel.db") == 42 and _sayi(data / "panel.db", "yeni") == 0
    assert not (data / "panel.db-wal").exists() and not (data / "panel.db-shm").exists(), "eski WAL/SHM silinmeli"
    assert sorted(p.name for p in data.iterdir()) == ["panel.db"]
    st = (data / "panel.db").stat()
    assert oct(st.st_mode & 0o777) == "0o600"
    if kanit_var():
        assert pwd.getpwuid(st.st_uid).pw_name == "kanit"
    onceki = list((kok / "onceki").iterdir())
    assert len(onceki) == 1 and sorted(p.name for p in onceki[0].iterdir()) == ["panel.db", "panel.db-shm", "panel.db-wal"]
    assert _sayi(onceki[0] / "panel.db") == 52 and (onceki[0] / "panel.db-wal").read_bytes() == b"bayat wal"
    assert oct((kok / "onceki").stat().st_mode & 0o777) == "0o700"
    # geri yüklenen DB uygulama gibi açılıp yazılabilir (WAL'a geçer)
    c = sqlite3.connect(data / "panel.db")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("INSERT INTO kayitlar(x) VALUES ('sonra')")
    c.commit()
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and c.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] == 43
    c.close()
    # normal yedek akışı bu değişiklikten etkilenmez
    r = run(["bash", betik, "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout


# ---------------------------------------------------------------- kanit-yedek.sh: rsync 23/24 uyarı, diğer kodlar hata
@pytest.mark.skipif(not ROOT or shutil.which("rsync") is None, reason="root + rsync gerekir")
def test_kanit_yedek_rsync_24_uyari_diger_kod_hata(kanit_tmp):
    kok = kanit_tmp
    app, data, yedek, gz, log, env = _yedek_ortami(kok)
    for d in ["gorseller", "telegram_gorseller"]:
        (data / d).mkdir()
        (data / d / "a.jpg").write_bytes(b"x" * 1024)
    if kanit_var():
        subprocess.run(["chown", "-R", "kanit:kanit", str(data)], check=True)
    sahte = kok / "bin"
    sahte.mkdir()
    gercek = shutil.which("rsync")
    (sahte / "rsync").write_text(f"#!/usr/bin/env bash\n{gercek} \"$@\"; rc=$?\n[[ -n ${{FAKE_RSYNC_RC:-}} ]] && exit \"$FAKE_RSYNC_RC\"\nexit $rc\n")
    (sahte / "rsync").chmod(0o755)
    env = dict(env, PATH=f"{sahte}:{os.environ['PATH']}")
    betik = str(DEPLOY / "kanit-yedek.sh")
    r = run(["bash", betik, "--haftalik"], env=dict(env, FAKE_RSYNC_RC="24"))
    assert r.returncode == 0 and "YEDEK_TAMAM" in r.stdout and "Görsel aynası" in r.stdout, r.stdout + r.stderr
    assert "UYARI: rsync 24" in r.stderr and "ayna yine geçerli" in r.stderr, r.stderr
    hafta = time.strftime("%G-W%V")
    assert (yedek / "haftalik" / hafta / "gorseller" / "a.jpg").exists()
    r = run(["bash", betik, "--haftalik"], env=dict(env, FAKE_RSYNC_RC="23"))
    assert r.returncode == 0 and "UYARI: rsync 23" in r.stderr and "YEDEK_TAMAM" in r.stdout
    r = run(["bash", betik, "--haftalik"], env=dict(env, FAKE_RSYNC_RC="12"))
    assert r.returncode == 1 and "rsync hatası (çıkış 12)" in r.stderr and "YEDEK_TAMAM" not in r.stdout, r.stdout + r.stderr
    r = run(["bash", betik, "--haftalik"], env=env)
    assert r.returncode == 0 and "UYARI" not in r.stderr and "YEDEK_TAMAM" in r.stdout


# ---------------------------------------------------------------- update-support.py sqlite-backup: yan dosya yok
def test_update_support_snapshot_tek_dosya(tmp_path):
    src = tmp_path / "panel.db"
    c = sqlite3.connect(src)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE kayitlar(id INTEGER PRIMARY KEY, x TEXT)")
    c.executemany("INSERT INTO kayitlar(x) VALUES (?)", [("a",)] * 10)
    c.commit()
    # canlı panel gibi açık yazar bağlantı dururken (-wal/-shm mevcut) snapshot alınır
    assert (tmp_path / "panel.db-wal").exists()
    hedef = tmp_path / ".kanit-update-snapshot-x.db"
    r = run([sys.executable, "-I", str(DEPLOY / "update-support.py"), "sqlite-backup", "--source", str(src), "--destination", str(hedef)])
    assert r.returncode == 0 and "SQLITE_SNAPSHOT_HAZIR" in r.stdout, r.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == [".kanit-update-snapshot-x.db", "panel.db", "panel.db-shm", "panel.db-wal"]
    d = sqlite3.connect(f"file:{hedef}?mode=ro", uri=True)
    assert d.execute("PRAGMA journal_mode").fetchone()[0] == "delete" and d.execute("SELECT COUNT(*) FROM kayitlar").fetchone()[0] == 10
    d.close()
    assert not (tmp_path / ".kanit-update-snapshot-x.db-wal").exists() and not (tmp_path / ".kanit-update-snapshot-x.db-shm").exists()
    c.close()
    us = _yardimci()
    with pytest.raises(us.CheckError, match="zaten var"):
        us.online_backup(src, hedef)


# ---------------------------------------------------------------- apply-update.sh: bot açılamazsa görünür uyarı, geri alma yok
def test_apply_update_bot_acilamazsa_uyari_yazar(guncelleme_ortami):
    o = guncelleme_ortami
    kok = o["kok"]
    bayrak = kok / "bot.aktif"
    bot_log = kok / "bot-systemctl.log"
    sarma = kok / "systemctl-bot"
    sarma.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        a=(); for x in "$@"; do case "$x" in --quiet|--now|--no-pager) ;; *) a+=("$x");; esac; done
        if [[ ${{a[1]:-}} == kanit-bot.service ]]; then
          echo "systemctl $*" >> "{bot_log}"
          case "${{a[0]:-}}" in
            is-active) [[ -f "{bayrak}" ]] && exit 0; exit 3;;
            stop) rm -f "{bayrak}"; exit 0;;
            start) [[ "${{FAKE_BOT_CRASH:-0}}" == 1 ]] || touch "{bayrak}"; exit 0;;
            *) exit 0;;
          esac
        fi
        exec "{o["env"]["KANIT_SYSTEMCTL"]}" "$@"
    '''))
    sarma.chmod(0o755)
    env = dict(o["env"], KANIT_SYSTEMCTL=str(sarma), KANIT_BOT_BEKLE="0")
    # 1) bot aktif, yeni birimle açılamıyor (saniyeler sonra düşüyor): güncelleme tamamlanır, uyarı görünür, çıkış 0
    bayrak.touch()
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh")], env=dict(env, FAKE_BOT_CRASH="1"), timeout=300)
    assert r.returncode == 0 and "GÜNCELLEME_TAMAM" in r.stdout, r.stdout + r.stderr
    assert "UYARI: kanit-bot açılamadı" in r.stdout and "journalctl -u kanit-bot -n 50" in r.stdout, r.stdout
    assert r.stdout.index("GÜNCELLEME_TAMAM") < r.stdout.index("UYARI: kanit-bot"), "uyarı sonuç satırından sonra, görünür yerde"
    assert "GÜNCELLEME_HATASI" not in r.stderr and (o["dest"] / "requirements.txt").read_text() == o["yeni_req"], "geri alma olmamalı"
    satirlar = bot_log.read_text().splitlines()
    assert "systemctl stop kanit-bot.service" in satirlar and "systemctl start kanit-bot.service" in satirlar
    assert satirlar[-1] == "systemctl is-active --quiet kanit-bot.service", satirlar
    # 2) bot sağlıklı açılıyorsa uyarı yok
    bayrak.touch()
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh")], env=env, timeout=300)
    assert r.returncode == 0 and "GÜNCELLEME_TAMAM" in r.stdout and "UYARI: kanit-bot" not in r.stdout, r.stdout + r.stderr
    assert bayrak.exists()


# ---------------------------------------------------------------- configure-bot.py --yonetici
def _configure_bot(env_dosya, kurulum, stdin):
    # getpass tty varsa /dev/tty'den okur; yeni oturumda (setsid) tty yoktur ve stdin'e düşer.
    full_env = dict(os.environ, KANIT_ENV=str(env_dosya), KANIT_BACKUP_ROOT=str(kurulum))
    return subprocess.run([sys.executable, "-I", str(DEPLOY / "configure-bot.py"), "--yonetici"], input=stdin, env=full_env,
                          capture_output=True, text=True, timeout=60, start_new_session=True)


@pytest.mark.skipif(not ROOT, reason="root gerekir (betik root ister)")
def test_configure_bot_yonetici_env_guvenli_gunceller(tmp_path):
    env_dosya = tmp_path / ".env"
    icerik = ('PANEL_VERI=/opt/kanit-paneli/data\nHTTPS=1\nADMIN_IDS=1\n# yorum satırı\nBOT_PASSWORD="bot-sifre"\n'
              'ADMIN_PASSWORD="eski"\nMAX_DENEME=3\n')
    env_dosya.write_text(icerik)
    gid = pwd.getpwnam("kanit").pw_gid if kanit_var() else 0
    os.chown(env_dosya, 0, gid)
    env_dosya.chmod(0o640)
    kurulum = tmp_path / "kurulum"
    parola = 'par/ola&"ters\\bölü$x'
    r = _configure_bot(env_dosya, kurulum, f"5, 7,5\n{parola}\n{parola}\n")
    assert r.returncode == 0 and "YONETICI_AYARLARI_KAYDEDILDI" in r.stdout and "systemctl restart kanit-bot" in r.stdout, r.stdout + r.stderr
    assert parola not in r.stdout + r.stderr and "5,7" not in r.stdout + r.stderr, "değerler yazdırılmaz"
    yeni = env_dosya.read_text()
    assert yeni.splitlines()[0:2] == ["PANEL_VERI=/opt/kanit-paneli/data", "HTTPS=1"] and "# yorum satırı" in yeni
    assert 'BOT_PASSWORD="bot-sifre"' in yeni and "MAX_DENEME=3" in yeni and "ADMIN_IDS=5,7\n" in yeni and 'ADMIN_PASSWORD="eski"' not in yeni
    assert yeni.count("ADMIN_IDS=") == 1 and yeni.count("ADMIN_PASSWORD=") == 1
    st = env_dosya.stat()
    assert oct(st.st_mode & 0o777) == "0o640" and st.st_uid == 0 and st.st_gid == gid, "izin ve sahip korunur"
    assert not env_dosya.is_symlink() and not list(tmp_path.glob(".env-bot-*")), "geçici dosya kalmaz"
    yedekler = list(kurulum.glob("bot-ayar-*/env.before"))
    assert len(yedekler) == 1 and yedekler[0].read_text() == icerik and oct(yedekler[0].stat().st_mode & 0o777) == "0o600"
    # uygulamanın okuduğu biçimde (python-dotenv) parola birebir geri gelir
    from dotenv import dotenv_values
    degerler = dotenv_values(env_dosya)
    assert degerler["ADMIN_PASSWORD"] == parola and degerler["ADMIN_IDS"] == "5,7" and degerler["BOT_PASSWORD"] == "bot-sifre"
    us = _yardimci()
    assert us.parse_dotenv(env_dosya)["ADMIN_IDS"] == "5,7", "güncelleme ön kontrolü (env-check) dosyayı yine ayrıştırır"
    # satır yoksa eklenir; farklı izin (600, root:root) korunur
    env2 = tmp_path / "env2"
    env2.write_text("HTTPS=1\n")
    env2.chmod(0o600)
    r = _configure_bot(env2, kurulum, "42\nabc\nabc\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert env2.read_text() == 'HTTPS=1\nADMIN_IDS=42\nADMIN_PASSWORD="abc"\n' and oct(env2.stat().st_mode & 0o777) == "0o600"
    # hatalı girdiler: dosya değişmez, yedek alınmaz
    once = yeni
    for stdin, beklenen in [("5\nbir\niki\n", "farklı"), ("5\n\n\n", "boş"), ("abc\nx\nx\n", "rakam"), ("\nx\nx\n", "En az bir"),
                            ("5\nsatir${HOME}\nsatir${HOME}\n", "${...}")]:
        r = _configure_bot(env_dosya, kurulum, stdin)
        assert r.returncode == 1 and beklenen in r.stderr and "değiştirilmedi" in r.stderr, (stdin, r.stdout + r.stderr)
        assert env_dosya.read_text() == once
    assert len(list(kurulum.glob("bot-ayar-*"))) == 2
    # .env yoksa / sembolik bağlantıysa reddedilir
    (tmp_path / "link").symlink_to(env_dosya)
    r = _configure_bot(tmp_path / "link", kurulum, "5\nx\nx\n")
    assert r.returncode == 1 and "Normal .env" in r.stderr and env_dosya.read_text() == once
    # varsayılan mod korunur (--yonetici olmadan bot anahtarı sorar; biçim hatası dosyaya dokunmaz)
    full_env = dict(os.environ, KANIT_ENV=str(env_dosya), KANIT_BACKUP_ROOT=str(kurulum))
    r = subprocess.run([sys.executable, "-I", str(DEPLOY / "configure-bot.py")], input="gecersiz-token\n", env=full_env,
                       capture_output=True, text=True, timeout=60, start_new_session=True)
    assert r.returncode == 1 and "Bot anahtarı biçimi" in r.stderr and env_dosya.read_text() == once


def test_configure_bot_yardim_ve_python_I_uyumu():
    r = run([sys.executable, "-I", str(DEPLOY / "configure-bot.py"), "--help"])
    assert r.returncode == 0 and "--yonetici" in r.stdout, r.stdout + r.stderr
    r = run([sys.executable, "-I", str(DEPLOY / "configure-bot.py"), "--bilinmeyen"])
    assert r.returncode == 2
