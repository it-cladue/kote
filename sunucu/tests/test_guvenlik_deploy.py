"""Altyapı güvenlik turu: deploy/ betikleri, birim dosyaları, nginx şablonları, fail2ban filtresi, yedek, güncelleme.

Çoğu test sandbox araçlarına bağlıdır (nginx, systemd-analyze, fail2ban-regex, root, kanit hesabı); araç yoksa atlanır.
Hiçbir test /opt/kanit-paneli'ne veya gerçek sistem dizinlerine dokunmaz; her şey geçici dizinlerde ve KANIT_* ortam
değişkenleriyle prova edilir.
"""
import importlib.util
import json
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

SUNUCU = Path(__file__).resolve().parents[1]
DEPLOY = SUNUCU / "deploy"
SH_FILES = sorted(DEPLOY.glob("*.sh"))
NGINX = shutil.which("nginx")
ROOT = os.geteuid() == 0


def kanit_var():
    try:
        pwd.getpwnam("kanit")
        return True
    except KeyError:
        return False


def run(cmd, env=None, cwd=None, stdin=None, timeout=180, check=False):
    full_env = dict(os.environ)
    full_env.update(env or {})
    full_env.setdefault("KANIT_TEST", "1")
    return subprocess.run(cmd, env=full_env, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout, check=check)


def bos_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_bekle(port, saniye=10):
    son = time.time() + saniye
    while time.time() < son:
        with socket.socket() as s:
            s.settimeout(0.3)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


FAKE_PANEL = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def _yanit(self):
            if self.path == "/saglik": body = b"OK"
            elif self.path == "/basliklar": body = json.dumps(dict(self.headers.items())).encode()
            else: body = b"PANEL"
            self.send_response(200); self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self): self._yanit()
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0)); self._yanit()
        def log_message(self, *a): pass
    HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
''')


@pytest.fixture
def sahte_panel(tmp_path):
    port = bos_port()
    script = tmp_path / "sahte_panel.py"
    script.write_text(FAKE_PANEL)
    proc = subprocess.Popen([sys.executable, str(script), str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert port_bekle(port), "sahte panel açılmadı"
    try:
        yield port
    finally:
        proc.kill()
        proc.wait(timeout=5)


@pytest.fixture
def kanit_tmp():
    """kanit hesabının da gezebildiği (755) geçici kök; pytest'in tmp_path'i 700 olduğundan ayrı açılır."""
    kok = Path(tempfile.mkdtemp(prefix="kanit-deploy-test.", dir="/tmp"))
    kok.chmod(0o755)
    try:
        yield kok
    finally:
        shutil.rmtree(kok, ignore_errors=True)


def sertifika_uret(dizin, cn, san):
    dizin.mkdir(parents=True, exist_ok=True)
    key, pem = dizin / "privkey.pem", dizin / "fullchain.pem"
    run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3", "-subj", f"/CN={cn}",
         "-addext", f"subjectAltName={san}", "-keyout", str(key), "-out", str(pem)], check=True)
    return pem, key


def curl(*args):
    return run(["curl", "-sk", "--noproxy", "*", "--max-time", "10", *args])


# ---------------------------------------------------------------- betik kalitesi
def test_tum_sh_dosyalari_bash_n():
    assert SH_FILES, "deploy/*.sh bulunamadı"
    for sh in SH_FILES:
        r = run(["bash", "-n", str(sh)])
        assert r.returncode == 0, f"{sh.name}: {r.stderr}"
        assert sh.read_text().startswith("#!/usr/bin/env bash"), sh.name
        assert "set -Eeuo pipefail" in sh.read_text() or "set -euo pipefail" in sh.read_text(), sh.name


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck yok")
def test_shellcheck_temiz():
    r = run(["shellcheck", "-S", "warning", *map(str, SH_FILES)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_yeni_betiklerde_yardim_ve_dry_run():
    for ad in ["setup-cloudflare-https.sh", "setup-backup.sh", "setup-fail2ban.sh", "setup-firewall.sh", "nginx-giris-siniri.sh", "kanit-yedek.sh", "setup-ip-https.sh"]:
        metin = (DEPLOY / ad).read_text()
        assert "--yardim" in metin, ad
        assert "--dry-run" in metin or ad == "setup-firewall.sh", ad
        r = run(["bash", str(DEPLOY / ad), "--yardim"])
        assert r.returncode == 0 and r.stdout.strip(), ad


# ---------------------------------------------------------------- systemd birimleri
def _skor(unit):
    r = run(["systemd-analyze", "security", "--offline=true", str(unit)])
    m = re.search(r"Overall exposure level for [^:]+: ([0-9.]+)", r.stdout)
    assert m, r.stdout + r.stderr
    return float(m.group(1))


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze yok")
def test_birim_guvenlik_skoru_ve_verify():
    for ad in ["kanit-web.service", "kanit-bot.service"]:
        unit = DEPLOY / ad
        assert _skor(unit) <= 3.0, f"{ad} skoru 3.0 üstünde"
        r = run(["systemd-analyze", "verify", str(unit)])
        assert r.returncode == 0, r.stderr
    for ad in ["kanit-yedek.service", "kanit-yedek.timer"]:
        r = run(["systemd-analyze", "verify", str(DEPLOY / ad)])
        # ExecStart yolu sandbox'ta olmayabilir; sözdizimi hatası olmasın yeter.
        assert "Failed to parse" not in r.stderr and "Unknown" not in r.stderr, r.stderr


def test_birim_icerikleri():
    web = (DEPLOY / "kanit-web.service").read_text()
    bot = (DEPLOY / "kanit-bot.service").read_text()
    for metin, ad in ((web, "web"), (bot, "bot")):
        for satir in ["NoNewPrivileges=true", "ProtectSystem=strict", "ReadWritePaths=/opt/kanit-paneli/data", "ProtectHome=true",
                      "PrivateDevices=true", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX", "CapabilityBoundingSet=",
                      "SystemCallFilter=@system-service", "SystemCallArchitectures=native", "UMask=0077",
                      f"SyslogIdentifier=kanit-{ad}", "Environment=PYTHONDONTWRITEBYTECODE=1"]:
            assert satir in metin, f"{ad}: {satir}"
    assert "StartLimitIntervalSec=300" in bot and "StartLimitBurst=10" in bot and "RestartSec=10" in bot
    assert "StartLimit" not in web, "web için StartLimit eklenmemeli (doğrulayıcı notu)"
    timer = (DEPLOY / "kanit-yedek.timer").read_text()
    assert "Persistent=true" in timer and "OnCalendar=*-*-* 03:" in timer


# ---------------------------------------------------------------- fail2ban
ORNEK_SATIRLAR = [
    "Nov 23 19:00:00 sunucu kanit-web[1234]: kanit-web GIRIS_HATA ip=203.0.113.5 kullanici=admin",
    "Nov 23 19:00:01 sunucu python[1234]: WARNING:app.panel:kanit-web GIRIS_SINIR ip=203.0.113.6",
    "Nov 23 19:00:02 sunucu kanit-web[1234]: [2026-11-23 19:00:02,123] WARNING in panel: kanit-web GIRIS_KILIT ip=2001:db8::1 kullanici=x",
    "Nov 23 19:00:03 sunucu kanit-web[1234]: kanit-web GIRIS_OK ip=203.0.113.7 kullanici=admin",
    "Nov 23 19:00:04 sunucu kanit-web[1234]: 203.0.113.8 - - \"POST /giris HTTP/1.1\" 200",
]


@pytest.mark.skipif(shutil.which("fail2ban-regex") is None, reason="fail2ban-regex yok")
def test_fail2ban_filtresi_ornek_satirlar(tmp_path):
    log = tmp_path / "ornek.log"
    log.write_text("\n".join(ORNEK_SATIRLAR) + "\n")
    r = run(["fail2ban-regex", "--print-all-matched", str(log), str(DEPLOY / "fail2ban" / "kanit-web.conf")])
    assert "Lines: 5 lines, 0 ignored, 3 matched, 2 missed" in r.stdout, r.stdout + r.stderr
    for ip in ("203.0.113.5", "203.0.113.6", "2001:db8::1"):
        assert ip in r.stdout
    assert "203.0.113.7" not in r.stdout.split("Addresses found")[1] if "Addresses found" in r.stdout else True


def test_fail2ban_jail_icerigi():
    jail = (DEPLOY / "fail2ban" / "jail-kanit.conf").read_text()
    for satir in ["[kanit-web]", "backend = systemd", "filter = kanit-web", "port = 18443,443", "maxretry = 10", "findtime = 10m", "bantime = 1h"]:
        assert satir in jail
    assert "173.245.48.0/20" in jail and "2606:4700::/32" in jail, "Cloudflare uçları ignoreip'te olmalı"
    filtre = (DEPLOY / "fail2ban" / "kanit-web.conf").read_text()
    assert "journalmatch = _SYSTEMD_UNIT=kanit-web.service" in filtre


def test_setup_fail2ban_sahte_dizin(tmp_path):
    if not ROOT:
        pytest.skip("root gerekir")
    f2bc = tmp_path / "f2bc"
    f2bc.write_text("#!/bin/bash\n[[ $1 == status ]] && echo 'Status for the jail: kanit-web'\nexit 0\n")
    f2bc.chmod(0o755)
    env = {"KANIT_F2B_DIR": str(tmp_path / "f2b"), "KANIT_F2B_CLIENT": str(f2bc), "KANIT_SYSTEMCTL": "true"}
    r = run(["bash", str(DEPLOY / "setup-fail2ban.sh"), "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout, r.stdout + r.stderr
    assert not (tmp_path / "f2b" / "jail.d" / "kanit-web.local").exists()
    r = run(["bash", str(DEPLOY / "setup-fail2ban.sh")], env=env)
    assert r.returncode == 0 and "FAIL2BAN_TAMAM" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "f2b" / "jail.d" / "kanit-web.local").read_text() == (DEPLOY / "fail2ban" / "jail-kanit.conf").read_text()
    assert (tmp_path / "f2b" / "filter.d" / "kanit-web.conf").exists()
    r = run(["bash", str(DEPLOY / "setup-fail2ban.sh")], env=env)
    assert r.returncode == 0 and "Güncel:" in r.stdout


# ---------------------------------------------------------------- update-support.py
def _yardimci():
    spec = importlib.util.spec_from_file_location("update_support", DEPLOY / "update-support.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_requirements_diff_mantigi(tmp_path):
    us = _yardimci()
    eski = tmp_path / "eski.txt"
    yeni = tmp_path / "yeni.txt"
    eski.write_text("Flask==3.1.3\nPillow==12.3.0\n# yorum\nrequests==2.34.2\n")
    yeni.write_text("Flask==3.1.3\nPillow==13.0.0\nrequests==2.34.2\n")
    degisim = us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni))
    assert degisim == [("Pillow", "12.3.0", "13.0.0")]
    assert us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(eski)) == []
    # yeni paket
    yeni.write_text("Flask==3.1.3\nPillow==13.0.0\nrequests==2.34.2\nyenipaket==1.0\n")
    with pytest.raises(us.CheckError, match="yeni paket"):
        us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni))
    # kaldırılan paket
    yeni.write_text("Flask==3.1.3\nPillow==13.0.0\n")
    with pytest.raises(us.CheckError, match="kaldırıyor"):
        us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni))
    # sürüm düşürme
    yeni.write_text("Flask==3.1.3\nPillow==12.2.0\nrequests==2.34.2\n")
    with pytest.raises(us.CheckError, match="düşürme"):
        us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni))
    # serbest sürüm / aralık
    yeni.write_text("Flask>=3.1\nPillow==13.0.0\nrequests==2.34.2\n")
    with pytest.raises(us.CheckError, match="paket==sürüm"):
        us.parse_requirements(yeni)
    # sayısal olmayan sürüm
    yeni.write_text("Flask==3.1.3\nPillow==13.0.0rc1\nrequests==2.34.2\n")
    with pytest.raises(us.CheckError, match="sayısal"):
        us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni))
    # ad normalizasyonu: pillow == Pillow
    yeni.write_text("flask==3.1.3\npillow==13.0.0\nrequests==2.34.2\n")
    assert us.compare_requirements(us.parse_requirements(eski), us.parse_requirements(yeni)) == [("pillow", "12.3.0", "13.0.0")]


def test_requirements_diff_cli(tmp_path):
    eski = tmp_path / "eski.txt"
    yeni = tmp_path / "yeni.txt"
    eski.write_text("Pillow==12.3.0\n")
    yeni.write_text("Pillow==13.0.0\n")
    r = run([sys.executable, str(DEPLOY / "update-support.py"), "requirements-diff", "--old", str(eski), "--new", str(yeni)])
    assert r.returncode == 0 and "SURUM_YUKSELTME Pillow 12.3.0->13.0.0" in r.stdout and "GEREKSINIMLER_YUKSELTME" in r.stdout
    r = run([sys.executable, str(DEPLOY / "update-support.py"), "requirements-diff", "--old", str(eski), "--new", str(eski)])
    assert r.returncode == 0 and "GEREKSINIMLER_AYNI" in r.stdout
    yeni.write_text("Pillow==13.0.0\nbaska==1\n")
    r = run([sys.executable, str(DEPLOY / "update-support.py"), "requirements-diff", "--old", str(eski), "--new", str(yeni)])
    assert r.returncode == 2 and "yeni paket" in r.stderr


def test_env_check_panel_veri_secenegi(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"PANEL_VERI={tmp_path}/veri\nDINLE=127.0.0.1\nPORT=18080\nHTTPS=1\nTRUST_PROXY=1\nSESSION_SECRET=x\n")
    env.chmod(0o600)
    r = run([sys.executable, str(DEPLOY / "update-support.py"), "env-check", "--env", str(env), "--panel-veri", f"{tmp_path}/veri"])
    assert r.returncode == 0 and "ORTAM_UYUMLU" in r.stdout, r.stderr
    r = run([sys.executable, str(DEPLOY / "update-support.py"), "env-check", "--env", str(env)])
    assert r.returncode == 2, "varsayılan /opt/kanit-paneli/data beklentisi korunmalı"


def test_requirements_pillow_13():
    metin = (SUNUCU / "requirements.txt").read_text()
    assert "Pillow==13.0.0" in metin
    assert "Pillow==12." not in metin
    import PIL
    assert tuple(int(x) for x in PIL.__version__.split(".")[:2]) >= (13, 0)


# ---------------------------------------------------------------- nginx şablonları
def _sarmalayici(kok):
    (kok / "logs").mkdir(exist_ok=True)
    (kok / "confd").mkdir(exist_ok=True)
    (kok / "root.conf").write_text(
        f"pid {kok}/nginx.pid;\nerror_log {kok}/logs/error.log warn;\nevents {{ worker_connections 128; }}\n"
        f"http {{ access_log off; include {kok}/confd/*.conf; }}\n")
    return kok / "root.conf"


@pytest.mark.skipif(NGINX is None, reason="nginx yok")
def test_domain_sablonu_limit_req_tls_http2(tmp_path):
    metin = (DEPLOY / "setup-domain-https.sh").read_text()
    fonk = metin[metin.index("nginx_http2_yonergesi_var() {"):]
    fonk = fonk[: fonk.index("\n}\n") + 3]
    sablon = metin[metin.index("http_blogu() {"): metin.index("# 1) Yalnız 80 bloğu")]
    pem, key = sertifika_uret(tmp_path / "live", "panel.ornek.test", "DNS:panel.ornek.test")
    http_port, https_port = bos_port(), bos_port()
    kok = _sarmalayici(tmp_path)
    env = {"NGINX_BIN": NGINX, "IP": "127.0.0.1", "HTTP_PORT": str(http_port), "HTTPS_PORT": str(https_port), "DOMAIN": "panel.ornek.test",
           "WEBROOT": str(tmp_path), "CERT_DIR": str(tmp_path / "live"), "PANEL_URL": "http://127.0.0.1:18080",
           "TLS_CIPHERS": "ECDHE-RSA-AES128-GCM-SHA256"}
    r = run(["bash", "-c", fonk + sablon + "\n{ http_blogu; https_blogu; }"], env=env)
    assert r.returncode == 0, r.stderr
    conf = r.stdout
    (tmp_path / "confd" / "zz020.conf").write_text(conf)
    for satir in ["limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m;", "location = /giris {", "limit_req zone=kanit_giris burst=10 nodelay;",
                  "limit_req_status 429;", "ssl_protocols TLSv1.2 TLSv1.3;", "ssl_prefer_server_ciphers off;", "ssl_ciphers ", "ssl_session_timeout 1d;",
                  "ssl_session_tickets off;", "client_max_body_size 64m;", "proxy_set_header X-Forwarded-For $remote_addr;", "return 301 https://$host$request_uri;"]:
        assert satir in conf, satir
    assert "http2" in conf
    assert "ssl_stapling" not in conf
    r = run([NGINX, "-t", "-c", str(kok), "-p", str(tmp_path) + "/"])
    assert r.returncode == 0, r.stderr


@pytest.fixture
def ip_proxy_ortami(kanit_tmp, sahte_panel):
    """setup-ip-https.sh için: sertifika, .env, sahte systemctl (gerçek nginx'i başlatır)."""
    if not (ROOT and NGINX and kanit_var()):
        pytest.skip("root + nginx + kanit hesabı gerekir")
    kok = kanit_tmp
    ssl = kok / "ssl"
    sertifika_uret(ssl / "config" / "live" / "kanit-ip", "217.156.123.36", "IP:217.156.123.36")
    (kok / "app").mkdir()
    (kok / "app" / ".env").write_text("HTTPS=0\nTRUST_PROXY=0\nPORT=18080\n")
    (kok / "units").mkdir()
    port = bos_port()
    fake = kok / "systemctl"
    fake.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "systemctl $*" >> "{kok}/systemctl.log"
        a=(); for x in "$@"; do case "$x" in --quiet|--now|--no-pager) ;; *) a+=("$x");; esac; done
        cmd=${{a[0]:-}}; unit=${{a[1]:-}}
        basla() {{ nginx -p "{ssl}/" -c "{ssl}/nginx.conf" && sleep 0.3; }}
        dur() {{ [[ -f {kok}/run/nginx.pid ]] && kill -QUIT "$(cat {kok}/run/nginx.pid)" 2>/dev/null; sleep 0.3; return 0; }}
        if [[ $unit == kanit-ip-proxy.service ]]; then
          case "$cmd" in enable) [[ " $* " == *" --now "* ]] && basla;; start) basla;; stop|disable) dur;; restart) dur; basla;; esac
        fi
        exit 0
    '''))
    fake.chmod(0o755)
    env = {"KANIT_SSL_BASE": str(ssl), "KANIT_APP": str(kok / "app"), "KANIT_CACHE": str(kok / "cache"), "KANIT_RUN_DIR": str(kok / "run"),
           "KANIT_UNIT": str(kok / "units" / "kanit-ip-proxy.service"), "KANIT_BACKUP_ROOT": str(kok / "backup"), "KANIT_CURL_EXTRA": "-k",
           "KANIT_PORT": str(port), "KANIT_PANEL_URL": f"http://127.0.0.1:{sahte_panel}", "KANIT_SYSTEMCTL": str(fake)}
    try:
        yield kok, env, port
    finally:
        pid = kok / "run" / "nginx.pid"
        if pid.exists():
            subprocess.run(["kill", "-QUIT", pid.read_text().strip()], capture_output=True)
            time.sleep(0.3)


def test_setup_ip_https_sablon_ve_servis(ip_proxy_ortami):
    kok, env, port = ip_proxy_ortami
    betik = str(DEPLOY / "setup-ip-https.sh")
    r = run(["bash", betik, "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout, r.stdout + r.stderr
    assert not (kok / "ssl" / "nginx.conf").exists()
    r = run(["bash", betik], env=env)
    assert r.returncode == 0 and "HTTPS_SAGLIK_OK" in r.stdout, r.stdout + r.stderr
    conf = (kok / "ssl" / "nginx.conf").read_text()
    for satir in ["limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m;", "limit_req_status 429;", "location = /giris {",
                  "ssl_prefer_server_ciphers off;", "ssl_ciphers ECDHE-", "ssl_session_timeout 1d;", "client_max_body_size 64m;", "X-Forwarded-For $remote_addr"]:
        assert satir in conf, satir
    assert "http2" in conf and "ssl_stapling" not in conf
    assert "HTTPS=1" in (kok / "app" / ".env").read_text()
    # limit_req: 11 istek geçer, sonrakiler 429
    kodlar = [curl("--resolve", f"217.156.123.36:{port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST", "-d", "a=b",
                   f"https://217.156.123.36:{port}/giris").stdout for _ in range(14)]
    assert kodlar[:5] == ["200"] * 5 and "429" in kodlar[11:], kodlar
    # TLS: PFS'siz RSA anahtar değişimi reddedilir, ECDHE kabul edilir, TLS 1.1 kapalı
    r = run(["openssl", "s_client", "-connect", f"127.0.0.1:{port}", "-tls1_2", "-cipher", "AES256-GCM-SHA384"], stdin="")
    assert "Cipher is (NONE)" in r.stdout + r.stderr
    r = run(["openssl", "s_client", "-connect", f"127.0.0.1:{port}", "-tls1_2", "-cipher", "ECDHE-RSA-AES128-GCM-SHA256"], stdin="")
    assert "Cipher is ECDHE-RSA-AES128-GCM-SHA256" in r.stdout
    assert curl("--resolve", f"217.156.123.36:{port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_version}", f"https://217.156.123.36:{port}/saglik").stdout == "2"
    # birim: sertleştirilmiş, skor makul; --servis-guncelle idempotent
    unit = kok / "units" / "kanit-ip-proxy.service"
    metin = unit.read_text()
    for satir in ["CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID CAP_CHOWN CAP_DAC_OVERRIDE CAP_KILL", "PrivateDevices=true",
                  "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX", "ProtectSystem=strict", "NoNewPrivileges=true"]:
        assert satir in metin, satir
    if shutil.which("systemd-analyze"):
        assert _skor(unit) <= 5.0
    r = run(["bash", betik, "--servis-guncelle"], env=env)
    assert r.returncode == 0 and "BIRIM_GUNCEL" in r.stdout, r.stdout + r.stderr
    unit.write_text(metin.replace("CapabilityBoundingSet=CAP_NET_BIND_SERVICE", "CapabilityBoundingSet="))
    r = run(["bash", betik, "--servis-guncelle", "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout and "CAP_NET_BIND_SERVICE" in r.stdout
    assert unit.read_text() != metin, "dry-run birimi değiştirmez"
    r = run(["bash", betik, "--servis-guncelle"], env=env)
    assert r.returncode == 0 and "BIRIM_GUNCELLENDI" in r.stdout, r.stdout + r.stderr
    assert unit.read_text() == metin
    # yeniden kurulum reddi
    r = run(["bash", betik], env=env)
    assert r.returncode == 1 and "zaten mevcut" in r.stderr


ESKI_IP_CONF = """user kanit kanit;
worker_processes 1;
pid {run}/nginx.pid;
error_log {base}/proxy-logs/error.log warn;
events {{ worker_connections 512; }}
http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server_tokens off;
    access_log {base}/proxy-logs/access.log;
    client_body_temp_path {base}/cache/client_body;
    proxy_temp_path {base}/cache/proxy;
    fastcgi_temp_path {base}/cache/fastcgi;
    uwsgi_temp_path {base}/cache/uwsgi;
    scgi_temp_path {base}/cache/scgi;
    server {{
        listen {port} ssl;
        server_name 217.156.123.36;
        ssl_certificate {base}/config/live/kanit-ip/fullchain.pem;
        ssl_certificate_key {base}/config/live/kanit-ip/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_cache shared:KANIT_IP_TLS:10m;
        ssl_session_timeout 1h;
        ssl_session_tickets off;
        client_max_body_size 12m;
        client_body_timeout 60s;
        keepalive_timeout 30s;
        # Her istek panelin kendi giriş ve yetki kontrolünden geçer.
        location / {{
            proxy_pass http://127.0.0.1:18080;
            proxy_http_version 1.1;
            proxy_set_header Host $http_host;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Connection "";
            proxy_read_timeout 120s;
        }}
    }}
}}
"""


@pytest.mark.skipif(not (ROOT and NGINX), reason="root + nginx gerekir")
def test_nginx_giris_siniri_eski_conf_yamasi(tmp_path):
    base = tmp_path
    (base / "proxy-logs").mkdir()
    (base / "cache").mkdir()
    sertifika_uret(base / "config" / "live" / "kanit-ip", "217.156.123.36", "IP:217.156.123.36")
    (base / "nginx.conf").write_text(ESKI_IP_CONF.format(run=base, base=base, port=bos_port()))
    env = {"KANIT_SSL_BASE": str(base), "KANIT_SYSTEMCTL": "true"}
    betik = str(DEPLOY / "nginx-giris-siniri.sh")
    r = run(["bash", betik, "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout, r.stdout + r.stderr
    assert "limit_req" not in (base / "nginx.conf").read_text()
    r = run(["bash", betik], env=env)
    assert r.returncode == 0 and "NGINX_CONF_GUNCELLENDI" in r.stdout, r.stdout + r.stderr
    conf = (base / "nginx.conf").read_text()
    for satir in ["limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m;", "limit_req_status 429;", "location = /giris {",
                  "limit_req zone=kanit_giris burst=10 nodelay;", "ssl_prefer_server_ciphers off;", "ssl_ciphers ECDHE-", "ssl_session_timeout 1d;",
                  "client_max_body_size 64m;", "ssl http2;"]:
        assert satir in conf, satir
    assert conf.index("location = /giris") < conf.index("location / {")
    assert conf.count("proxy_set_header X-Forwarded-For $remote_addr;") == 2
    assert list(base.glob("nginx.conf.before-*")), "eski dosya yedeklenmeli"
    r = run([NGINX, "-t", "-p", str(base) + "/", "-c", str(base / "nginx.conf")])
    assert r.returncode == 0, r.stderr
    r = run(["bash", betik], env=env)
    assert r.returncode == 0 and "NGINX_CONF_GUNCEL" in r.stdout and conf == (base / "nginx.conf").read_text()


@pytest.fixture
def cloudflare_ortami(kanit_tmp, sahte_panel):
    if not (ROOT and NGINX):
        pytest.skip("root + nginx gerekir")
    kok = kanit_tmp
    root_conf = _sarmalayici(kok)
    (kok / "ssl").mkdir()
    fake = kok / "systemctl"
    fake.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "systemctl $*" >> "{kok}/systemctl.log"
        case "$1" in
          is-active) exit 0;;
          reload) if [[ -f {kok}/nginx.pid ]] && kill -0 "$(cat {kok}/nginx.pid)" 2>/dev/null; then kill -HUP "$(cat {kok}/nginx.pid)"; else nginx -c "{root_conf}" -p "{kok}/"; fi; sleep 0.4; exit 0;;
          *) exit 0;;
        esac
    '''))
    fake.chmod(0o755)
    http_port, https_port = bos_port(), bos_port()
    env = {"KANIT_IP": "127.0.0.1", "KANIT_HTTP_PORT": str(http_port), "KANIT_HTTPS_PORT": str(https_port),
           "KANIT_CONF": str(kok / "confd" / "zz020_kanit-panel.conf"), "KANIT_SSL_BASE": str(kok / "ssl"), "KANIT_SYSTEMCTL": str(fake),
           "KANIT_PANEL_URL": f"http://127.0.0.1:{sahte_panel}", "KANIT_NGINX_T_ARGS": f"-c {root_conf} -p {kok}/", "KANIT_COZUM": "104.16.1.1"}
    try:
        yield kok, env, http_port, https_port
    finally:
        pid = kok / "nginx.pid"
        if pid.exists():
            subprocess.run(["kill", "-QUIT", pid.read_text().strip()], capture_output=True)
            time.sleep(0.3)


def test_setup_cloudflare_https_uctan_uca(cloudflare_ortami):
    kok, env, http_port, https_port = cloudflare_ortami
    betik = str(DEPLOY / "setup-cloudflare-https.sh")
    host = "panel.ornek.test"
    conf = kok / "confd" / "zz020_kanit-panel.conf"
    # dry-run: dosya yazılmaz; gri bulut uyarısı
    r = run(["bash", betik, host, "--dry-run"], env=env, stdin="")
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout and "turuncu bulut ✓" in r.stdout, r.stdout + r.stderr
    assert not conf.exists()
    r = run(["bash", betik, host, "--dry-run"], env=dict(env, KANIT_COZUM="127.0.0.1"), stdin="")
    assert r.returncode == 0 and "bulut GRİ" in r.stderr
    # kurulum (stdin kapalı -> öz imzalı)
    r = run(["bash", betik, host], env=env, stdin="")
    assert r.returncode == 0 and "CLOUDFLARE_HTTPS_TAMAM" in r.stdout and "2/3 Yerel origin kontrolü" in r.stdout and "-> OK" in r.stdout, r.stdout + r.stderr
    assert "Full" in r.stdout and "Proxied (TURUNCU bulut)" in r.stdout
    metin = conf.read_text()
    for satir in ["limit_req_zone $binary_remote_addr zone=kanit_giris:1m rate=10r/m;", "geo $realip_remote_addr $kanit_cf_kaynak {", "real_ip_header CF-Connecting-IP;",
                  "real_ip_recursive on;", "if ($kanit_cf_kaynak = 0) { return 403; }", "location = /giris {", "limit_req_status 429;", "ssl_prefer_server_ciphers off;",
                  "ssl_session_timeout 1d;", "client_max_body_size 64m;", f"listen 127.0.0.1:{https_port} ssl", f"listen 127.0.0.1:{http_port};",
                  "proxy_set_header X-Forwarded-For $remote_addr;", "proxy_set_header X-Forwarded-Proto https;", "return 301 https://$host$request_uri;"]:
        assert satir in metin, satir
    for yok in ["add_header", "Strict-Transport-Security", "ssl_stapling"]:
        assert yok not in metin, yok
    pem = kok / "ssl" / "cloudflare" / f"{host}.pem"
    assert pem.exists() and oct(pem.stat().st_mode & 0o777) == "0o600"
    assert (kok / "ssl" / "cloudflare" / "ips.conf").read_text().count("set_real_ip_from") == 22
    # erişim: 127.0.0.1 OK, Cloudflare dışı 127.0.0.3 -> 403, 80 -> 301
    assert curl("--resolve", f"{host}:{https_port}:127.0.0.1", f"https://{host}:{https_port}/saglik").stdout == "OK"
    assert curl("--interface", "127.0.0.3", "--resolve", f"{host}:{https_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}", f"https://{host}:{https_port}/saglik").stdout == "403"
    r = curl("--resolve", f"{host}:{http_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}", f"http://{host}:{http_port}/kayitlar?x=1")
    assert r.stdout == f"301 https://{host}/kayitlar?x=1"
    # --ip-guncelle: dosya kaynağından liste (127.0.0.2 güvenilir uç olur)
    (kok / "v4.txt").write_text("173.245.48.0/20\n103.21.244.0/22\n103.22.200.0/22\n103.31.4.0/22\n141.101.64.0/18\n127.0.0.2/32\n")
    (kok / "v6.txt").write_text("2400:cb00::/32\n2606:4700::/32\n2803:f800::/32\n")
    r = run(["bash", betik, "--ip-guncelle"], env=dict(env, KANIT_CF_URL_V4=f"file://{kok}/v4.txt", KANIT_CF_URL_V6=f"file://{kok}/v6.txt"))
    assert r.returncode == 0 and "IP_LISTESI_GUNCELLENDI" in r.stdout, r.stdout + r.stderr
    assert "set_real_ip_from 127.0.0.2/32;" in (kok / "ssl" / "cloudflare" / "ips.conf").read_text()
    # güvenilir uçtan CF-Connecting-IP -> uygulamaya gerçek IP gider; sahte uçtan yine 403
    r = curl("--interface", "127.0.0.2", "-H", "CF-Connecting-IP: 203.0.113.9", "--resolve", f"{host}:{https_port}:127.0.0.1", f"https://{host}:{https_port}/basliklar")
    basliklar = json.loads(r.stdout)
    assert basliklar["X-Forwarded-For"] == "203.0.113.9" and basliklar["X-Real-IP"] == "203.0.113.9" and basliklar["X-Forwarded-Proto"] == "https"
    assert curl("--interface", "127.0.0.3", "-H", "CF-Connecting-IP: 203.0.113.9", "--resolve", f"{host}:{https_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}", f"https://{host}:{https_port}/saglik").stdout == "403"
    # limit_req gerçek IP'ye göre
    kodlar = [curl("--interface", "127.0.0.2", "-H", "CF-Connecting-IP: 203.0.113.9", "--resolve", f"{host}:{https_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}",
                   "-X", "POST", "-d", "a=b", f"https://{host}:{https_port}/giris").stdout for _ in range(14)]
    assert kodlar[0] == "200" and "429" in kodlar[11:], kodlar
    assert curl("--interface", "127.0.0.2", "-H", "CF-Connecting-IP: 203.0.113.10", "--resolve", f"{host}:{https_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}",
                "-X", "POST", "-d", "a=b", f"https://{host}:{https_port}/giris").stdout == "200"
    # indirme başarısızsa liste korunur
    r = run(["bash", betik, "--ip-guncelle"], env=dict(env, KANIT_CF_URL_V4=f"file://{kok}/yok.txt", KANIT_CF_URL_V6=f"file://{kok}/yok.txt"))
    assert r.returncode == 0 and "IP_LISTESI_KORUNDU" in r.stdout
    # yeniden kurulum reddi, kaldırma (sertifika kalır)
    r = run(["bash", betik, host], env=env, stdin="")
    assert r.returncode == 1 and "zaten var" in r.stderr
    r = run(["bash", betik, "--kaldir"], env=env)
    assert r.returncode == 0 and not conf.exists() and pem.exists()
    # Origin CA dosyalarıyla kurulum -> Full (strict); uyumsuz anahtar reddedilir
    opem, okey = sertifika_uret(kok / "origin", "CloudFlare Origin Certificate", "DNS:*.ornek.test,DNS:ornek.test")
    r = run(["bash", betik, host, "--sertifika", str(opem), "--anahtar", str(okey)], env=env, stdin="")
    assert r.returncode == 0 and "Full (strict)" in r.stdout and "verilen dosyalar" in r.stdout, r.stdout + r.stderr
    r = run(["bash", betik, "--kaldir"], env=env)
    assert r.returncode == 0
    r = run(["bash", betik, host], env=env, stdin="")
    assert r.returncode == 0 and "mevcut" in r.stdout and "Full (strict)" in r.stdout, r.stdout
    r = run(["bash", betik, "--kaldir"], env=env)
    run(["openssl", "genrsa", "-out", str(kok / "baska.key"), "2048"])
    r = run(["bash", betik, host, "--sertifika", str(opem), "--anahtar", str(kok / "baska.key")], env=env, stdin="")
    assert r.returncode == 1 and "eşleşmiyor" in r.stderr and not conf.exists()
    # --herkese-acik: 403 bloğu yok, Cloudflare dışı istek geçer
    r = run(["bash", betik, host, "--herkese-acik"], env=env, stdin="")
    assert r.returncode == 0 and "return 403" not in conf.read_text()
    assert curl("--interface", "127.0.0.3", "--resolve", f"{host}:{https_port}:127.0.0.1", "-o", "/dev/null", "-w", "%{http_code}", f"https://{host}:{https_port}/saglik").stdout == "200"
    assert run(["bash", betik, "--kaldir"], env=env).returncode == 0


# ---------------------------------------------------------------- yedek
@pytest.mark.skipif(not ROOT, reason="root gerekir")
def test_kanit_yedek_ve_setup_backup(kanit_tmp):
    kok = kanit_tmp
    app = kok / "app"
    data = app / "data"
    for d in ["gorseller", "telegram_gorseller/alt", "backups"]:
        (data / d).mkdir(parents=True)
    (app / ".env").write_text("A=1\n")
    (data / "gorseller" / "a.jpg").write_bytes(os.urandom(50 * 1024))
    (data / "telegram_gorseller" / "alt" / "b.jpg").write_bytes(b"x")
    for i in range(7):
        (data / "backups" / f"panel-2026010{i}.sqlite3").write_bytes(b"x")
    import sqlite3
    c = sqlite3.connect(data / "panel.db")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE kayitlar(id INTEGER PRIMARY KEY, x TEXT)")
    c.executemany("INSERT INTO kayitlar(x) VALUES (?)", [("a",)] * 42)
    c.commit()
    c.close()
    if kanit_var():
        subprocess.run(["chown", "-R", "kanit:kanit", str(data)], check=True)
    yedek = kok / "yedek"
    yedek.mkdir()
    (yedek / "20260101T000000Z-1").mkdir()
    os.utime(yedek / "20260101T000000Z-1", (time.time() - 90 * 86400, time.time() - 90 * 86400))
    for i in range(1, 7):
        (yedek / f"20260201T00000{i}Z-1").mkdir()
    env = {"KANIT_APP": str(app), "KANIT_PY": sys.executable, "KANIT_YEDEK_KOK": str(yedek), "KANIT_SBIN_DIR": str(kok / "sbin"),
           "KANIT_UNIT_DIR": str(kok / "units"), "KANIT_SYSTEMCTL": "true"}
    if not kanit_var():
        env["KANIT_USER"] = "kanit-yok"
    r = run(["bash", str(DEPLOY / "setup-backup.sh"), "--dry-run"], env=env)
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout and not list((yedek / "gunluk").glob("panel-*")), r.stdout + r.stderr
    r = run(["bash", str(DEPLOY / "setup-backup.sh")], env=env)
    assert r.returncode == 0 and "YEDEK_ZAMANLAYICI_TAMAM" in r.stdout and "YEDEK_DOGRULANDI" in r.stdout, r.stdout + r.stderr
    gun = time.strftime("%Y%m%d")
    assert (yedek / "gunluk" / f"panel-{gun}.db.gz").exists() and (yedek / "gunluk" / f"env-{gun}").exists()
    assert oct((yedek / "gunluk" / f"panel-{gun}.db.gz").stat().st_mode & 0o777) == "0o600"
    hafta = time.strftime("%G-W%V")
    assert (yedek / "haftalik" / hafta / "gorseller" / "a.jpg").exists() and (yedek / "haftalik" / hafta / "telegram_gorseller" / "alt" / "b.jpg").exists()
    assert not (yedek / "20260101T000000Z-1").exists(), "60 günden eski, ilk 5 dışı güncelleme yedeği silinmeli"
    assert (yedek / "20260201T000002Z-1").exists()
    assert len(list((data / "backups").glob("*.sqlite3"))) == 5
    assert not list(data.glob(".kanit-yedek-*")), "geçici snapshot kalmamalı"
    if kanit_var():
        r = run(["find", str(data), "!", "-user", "kanit"])
        assert r.stdout.strip() == "", r.stdout
    assert (kok / "sbin" / "kanit-yedek.sh").exists() and (kok / "units" / "kanit-yedek.timer").exists()
    # ikinci hafta: hardlink
    (yedek / "haftalik" / hafta).rename(yedek / "haftalik" / "2026-W01")
    r = run(["bash", str(kok / "sbin" / "kanit-yedek.sh"), "--haftalik"], env=env)
    assert r.returncode == 0 and "önceki haftaya hardlink" in r.stdout, r.stdout + r.stderr
    assert (yedek / "haftalik" / "2026-W01" / "gorseller" / "a.jpg").stat().st_nlink == 2
    r = run(["bash", str(kok / "sbin" / "kanit-yedek.sh"), "--dogrula"], env=env)
    assert r.returncode == 0 and "integrity=ok" in r.stdout and "kayit=42" in r.stdout
    assert not list(yedek.glob(".dogrula-*"))
    import gzip
    with gzip.open(yedek / "gunluk" / "panel-29990101.db.gz", "wb") as f:
        f.write(b"bozuk")
    r = run(["bash", str(kok / "sbin" / "kanit-yedek.sh"), "--dogrula"], env=env)
    assert r.returncode == 1 and "YEDEK_BOZUK" in r.stderr


# ---------------------------------------------------------------- güvenlik duvarı
@pytest.mark.skipif(not ROOT, reason="root gerekir")
def test_setup_firewall_plan_ve_uygula(tmp_path):
    (tmp_path / "sshd_config").write_text("# yorum\nPort 2222\n")
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "x.conf").write_text("Port 2200\n")
    ufw_log = tmp_path / "ufw.log"
    ufw = tmp_path / "ufw"
    ufw.write_text(f"#!/bin/bash\necho \"$*\" >> {ufw_log}\n[[ $1 == status ]] && echo 'Status: inactive'\nexit 0\n")
    ufw.chmod(0o755)
    env = {"KANIT_SSHD_CONFIG": str(tmp_path / "sshd_config"), "KANIT_SSHD_CONFIG_D": str(tmp_path / "d"), "KANIT_UFW": str(ufw)}
    r = run(["bash", str(DEPLOY / "setup-firewall.sh")], env=env)
    assert r.returncode == 0 and "PLAN_YAZILDI" in r.stdout, r.stdout + r.stderr
    assert "ufw allow 2200/tcp comment SSH" in r.stdout and "ufw allow 2222/tcp comment SSH" in r.stdout
    assert "ufw allow 25/tcp comment Posta" in r.stdout and "8443" not in [s for s in r.stdout.splitlines() if s.startswith("ufw allow")]
    assert "ufw deny 18080/tcp" in r.stdout and "ufw allow 18443/tcp" in r.stdout
    assert not ufw_log.exists() or "enable" not in ufw_log.read_text()
    r = run(["bash", str(DEPLOY / "setup-firewall.sh"), "--uygula", "--plesk", "--posta-kapat", "--ssh-port", "22,2222"], env=env)
    assert r.returncode == 0 and "GUVENLIK_DUVARI_TAMAM" in r.stdout, r.stdout + r.stderr
    cagrilar = [s for s in ufw_log.read_text().splitlines() if not s.startswith("status")]
    assert cagrilar[:4] == ["default deny incoming", "default allow outgoing", "allow 22/tcp comment SSH", "allow 2222/tcp comment SSH"], cagrilar
    assert "allow 8443/tcp comment Plesk" in cagrilar and not any("Posta" in c for c in cagrilar)
    assert cagrilar[-1] == "--force enable" and "deny 18080/tcp comment Kanit-arka-uc-yalniz-loopback" in cagrilar
    # ufw yokken --uygula durur, plan yine yazılır
    r = run(["bash", str(DEPLOY / "setup-firewall.sh"), "--uygula"], env=dict(env, KANIT_UFW="/yok/ufw"))
    assert r.returncode == 1 and "ufw kurulu değil" in r.stderr


# ---------------------------------------------------------------- logrotate / örnek dosyalar / README
@pytest.mark.skipif(shutil.which("logrotate") is None, reason="logrotate yok")
def test_logrotate_kanit_kuru_calisma(tmp_path):
    (tmp_path / "proxy-logs").mkdir()
    (tmp_path / "proxy-logs" / "access.log").write_text("x\n")
    conf = (DEPLOY / "logrotate-kanit").read_text().replace("/opt/kanit-ssl", str(tmp_path))
    (tmp_path / "lr.conf").write_text(conf)
    r = run(["logrotate", "-d", "-s", str(tmp_path / "state"), str(tmp_path / "lr.conf")])
    cikti = r.stdout + r.stderr
    assert r.returncode == 0 and "error:" not in cikti.lower() and "unknown option" not in cikti.lower(), cikti
    assert "weekly (8 rotations)" in cikti
    # bot_log.txt uygulama içinde döndürülür; logrotate kuralı olmamalı
    kurallar = [l for l in (DEPLOY / "logrotate-kanit").read_text().splitlines() if not l.lstrip().startswith("#")]
    assert not any("bot_log" in l for l in kurallar)


def test_nginx_conf_example_guncel():
    tam = (DEPLOY / "nginx.conf.example").read_text()
    metin = "\n".join(l for l in tam.splitlines() if not l.lstrip().startswith("#"))
    assert "127.0.0.1:18080" in metin and "$proxy_add_x_forwarded_for" not in metin and "X-Forwarded-For $remote_addr" in metin
    assert "8080" not in metin.replace("18080", "")
    assert "KULLANILMAZ" in tam, "örnek dosyanın başında canlı sunucuda kullanılmayacağı yazmalı"
    assert "limit_req" in metin and "ssl_protocols TLSv1.2 TLSv1.3" in metin


def test_readme_isletim_notlari():
    readme = (SUNUCU / "README.md").read_text()
    for parca in ["setup-cloudflare-https.sh", "TURUNCU", "runuser -u kanit", "read -rs KANIT_PW", "setup-backup.sh", "kanit-yedek.sh --dogrula",
                  "setup-fail2ban.sh", "setup-firewall.sh", "logrotate-kanit", "timedatectl", "unattended-upgrades", "pip freeze",
                  "systemctl disable --now kanit-ip-proxy", "nginx-giris-siniri.sh", "--servis-guncelle", "rclone"]:
        assert parca in readme, parca
    assert "otomatik yenilemesi isteğin üzere bu güncellemeye eklenmedi" not in readme


# ---------------------------------------------------------------- apply-update.sh uçtan uca (geçici hedef, sahte systemctl/pip)
@pytest.fixture
def guncelleme_ortami(kanit_tmp):
    if not (ROOT and kanit_var() and Path("/usr/bin/python3").exists() and shutil.which("runuser")):
        pytest.skip("root + kanit hesabı + runuser + /usr/bin/python3 gerekir")
    kok = kanit_tmp
    dest = kok / "opt"
    dest.mkdir()
    shutil.copytree(SUNUCU / "app", dest / "app", ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["chown", "-R", "root:root", str(dest / "app")], check=True)
    for p in (dest / "app").rglob("*"):
        p.chmod(0o755 if p.is_dir() else 0o644)
    (dest / "app").chmod(0o755)
    yeni_req = (SUNUCU / "requirements.txt").read_text()
    eski_req = yeni_req.replace("Pillow==13.0.0", "Pillow==12.3.0")
    assert eski_req != yeni_req
    (dest / "requirements.txt").write_text(eski_req)
    env_dosya = dest / ".env"
    env_dosya.write_text(f"PANEL_VERI={dest}/data\nDINLE=127.0.0.1\nPORT=18080\nHTTPS=1\nTRUST_PROXY=1\nSESSION_SECRET=test-gizli-anahtar-0123456789abcdef0123456789\n")
    subprocess.run(["chown", "root:kanit", str(env_dosya)], check=True)
    env_dosya.chmod(0o640)
    (dest / "data").mkdir(mode=0o700)
    subprocess.run(["chown", "kanit:kanit", str(dest / "data")], check=True)
    runuser = shutil.which("runuser") or "/usr/sbin/runuser"
    r = subprocess.run([runuser, "-u", "kanit", "--", sys.executable, "-c",
                        f"import sys; sys.path.insert(0, '{dest}'); from app import db; db.baglan('{dest}/data/panel.db').close()"],
                       env={"HOME": str(dest), "PATH": "/usr/sbin:/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    # kaynak paket: app + deploy + requirements (yeni)
    kaynak = kok / "kaynak"
    kaynak.mkdir()
    shutil.copytree(SUNUCU / "app", kaynak / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(DEPLOY, kaynak / "deploy", ignore=shutil.ignore_patterns("__pycache__"))
    (kaynak / "requirements.txt").write_text(yeni_req)
    units = kok / "units"
    units.mkdir()
    (units / "kanit-web.service").write_text("[Unit]\nDescription=eski web\n[Service]\nExecStart=/bin/true\n")
    # kanit-bot.service kurulu değil -> yeni dosya kopyalanacak
    port = bos_port()
    panel = kok / "sahte_panel.py"
    panel.write_text(FAKE_PANEL)
    pip_log = kok / "pip.log"
    pip = kok / "pip"
    pip.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "pip $*" >> "{pip_log}"
        if [[ "$1" == install && "${{FAKE_PIP_FAIL:-0}}" == 1 && "$*" != *requirements.before* && "$*" != *--dry-run* ]]; then echo "sahte pip hatasi" >&2; exit 1; fi
        exit 0
    '''))
    pip.chmod(0o755)
    sysctl_log = kok / "systemctl.log"
    fake = kok / "systemctl"
    fake.write_text(textwrap.dedent(f'''#!/usr/bin/env bash
        echo "systemctl $*" >> "{sysctl_log}"
        a=(); for x in "$@"; do case "$x" in --quiet|--now|--no-pager) ;; *) a+=("$x");; esac; done
        cmd=${{a[0]:-}}; unit=${{a[1]:-}}
        pidf="{kok}/panel.pid"
        aktif() {{ [[ -f $pidf ]] && kill -0 "$(cat $pidf)" 2>/dev/null; }}
        case "$cmd" in
          is-active) if [[ $unit == kanit-web.service ]] && aktif; then exit 0; fi; exit 3;;
          start) if [[ $unit == kanit-web.service && "${{FAKE_NO_START:-0}}" != 1 ]]; then aktif || {{ {sys.executable} {panel} {port} >/dev/null 2>&1 & echo $! > "$pidf"; }}; fi; exit 0;;
          stop) if [[ $unit == kanit-web.service ]] && aktif; then kill "$(cat $pidf)"; rm -f "$pidf"; fi; exit 0;;
          *) exit 0;;
        esac
    '''))
    fake.chmod(0o755)
    subprocess.run([str(fake), "start", "kanit-web.service"], check=True)
    assert port_bekle(port)
    env = {"KANIT_DEST": str(dest), "KANIT_VENV_PY": sys.executable, "KANIT_BACKUP_ROOT": str(kok / "yedek"), "KANIT_UNIT_DIR": str(units),
           "KANIT_HEALTH_URL": f"http://127.0.0.1:{port}/saglik", "KANIT_SYSTEMCTL": str(fake), "KANIT_PIP": str(pip)}
    try:
        yield dict(kok=kok, dest=dest, kaynak=kaynak, units=units, env=env, pip_log=pip_log, sysctl_log=sysctl_log, eski_req=eski_req, yeni_req=yeni_req)
    finally:
        pidf = kok / "panel.pid"
        if pidf.exists():
            subprocess.run(["kill", pidf.read_text().strip()], capture_output=True)


def test_apply_update_dry_run_gosterir(guncelleme_ortami):
    o = guncelleme_ortami
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh"), "--dry-run"], env=o["env"])
    assert r.returncode == 0 and "DRY-RUN_TAMAM" in r.stdout, r.stdout + r.stderr
    assert "Pillow 12.3.0->13.0.0" in r.stdout and "pip çözümleme denemesi (--dry-run): TAMAM" in r.stdout
    assert "Servis birim dosyaları güncellenecek" in r.stdout and "kanit-web.service kanit-bot.service" in r.stdout
    assert "Birim farkı (kanit-web.service)" in r.stdout and "+SyslogIdentifier=kanit-web" in r.stdout
    assert "kurulu birim yok" in r.stdout
    assert (o["dest"] / "requirements.txt").read_text() == o["eski_req"], "dry-run dosya değiştirmez"
    assert "pip install --dry-run" in o["pip_log"].read_text()
    assert not (o["kok"] / "yedek").exists()


def test_apply_update_basarili_yukseltme_ve_birimler(guncelleme_ortami):
    o = guncelleme_ortami
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh")], env=o["env"])
    assert r.returncode == 0 and "GÜNCELLEME_TAMAM" in r.stdout, r.stdout + r.stderr
    assert "Bağımlılık yükseltmesi uygulandı" in r.stdout and "Servis birim dosyaları güncellendi" in r.stdout
    assert "UYARI" not in r.stdout, r.stdout
    assert (o["dest"] / "requirements.txt").read_text() == o["yeni_req"]
    assert (o["units"] / "kanit-web.service").read_text() == (DEPLOY / "kanit-web.service").read_text()
    assert (o["units"] / "kanit-bot.service").read_text() == (DEPLOY / "kanit-bot.service").read_text()
    pip_satirlar = o["pip_log"].read_text().splitlines()
    assert any(s.startswith("pip check") for s in pip_satirlar)
    assert any("install --require-virtualenv --no-input" in s and "requirements.txt" in s for s in pip_satirlar)
    sira = o["sysctl_log"].read_text().splitlines()
    dur = next(i for i, s in enumerate(sira) if s == "systemctl stop kanit-web.service")
    reload_i = next(i for i, s in enumerate(sira) if s == "systemctl daemon-reload")
    basla = max(i for i, s in enumerate(sira) if s == "systemctl start kanit-web.service")
    assert dur < reload_i < basla, sira
    assert "systemctl start kanit-bot.service" not in sira, "kapalı bot başlatılmaz"
    yedekler = list((o["kok"] / "yedek").iterdir())
    assert len(yedekler) == 1
    y = yedekler[0]
    for ad in ["sourceapp", ".env.before", "panel.db", "requirements.before", "pip-install.log", "units.before/kanit-web.service", "GERI_DONUS_NOTU.txt"]:
        assert (y / ad).exists(), ad
    assert not (y / "units.before" / "kanit-bot.service").exists()
    assert not list((o["dest"]).glob(".app.before-*")) and not list((o["dest"]).glob(".kanit-update-stage-*"))
    r = run(["find", str(o["dest"] / "data"), "!", "-user", "kanit"])
    assert r.stdout.strip() == "", "ön kontrol data altında root sahipli dizin bırakmamalı: " + r.stdout
    assert not list(Path("/tmp").glob("kanit-update-preflight.*"))
    # ikinci çalıştırma: değişiklik yok
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh"), "--dry-run"], env=o["env"])
    assert "Bağımlılık beyanı aynı" in r.stdout and "Servis birim dosyaları güncel" in r.stdout


def test_apply_update_pip_hatasi_geri_alir(guncelleme_ortami):
    o = guncelleme_ortami
    eski_app = sorted(p.name for p in (o["dest"] / "app").rglob("*"))
    (o["dest"] / "app" / "ISARET.txt").write_text("eski")
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh")], env=dict(o["env"], FAKE_PIP_FAIL="1"))
    assert r.returncode == 37 and "GÜNCELLEME_HATASI [37]" in r.stderr and "uygulama kodu değiştirilmedi" in r.stderr, r.stdout + r.stderr
    assert (o["dest"] / "app" / "ISARET.txt").exists(), "eski app dokunulmamış kalmalı"
    assert (o["dest"] / "requirements.txt").read_text() == o["eski_req"]
    assert (o["units"] / "kanit-web.service").read_text().startswith("[Unit]\nDescription=eski web"), "birimler değiştirilmemeli"
    assert not (o["units"] / "kanit-bot.service").exists()
    pip_satirlar = o["pip_log"].read_text().splitlines()
    assert any("requirements.before" in s for s in pip_satirlar), "eski sürümler geri kurulmalı"
    sira = o["sysctl_log"].read_text().splitlines()
    assert sira[-1] == "systemctl start kanit-web.service", sira
    assert run([str(o["env"]["KANIT_SYSTEMCTL"]), "is-active", "kanit-web.service"]).returncode == 0
    assert (o["dest"] / "app" / "ISARET.txt").read_text() == "eski" and sorted(p.name for p in (o["dest"] / "app").rglob("*")) == sorted(eski_app + ["ISARET.txt"])


def test_apply_update_saglik_hatasi_birimleri_geri_alir(guncelleme_ortami):
    o = guncelleme_ortami
    r = run(["bash", str(o["kaynak"] / "deploy" / "apply-update.sh")], env=dict(o["env"], FAKE_NO_START="1"), timeout=300)
    assert r.returncode == 43 and "GÜNCELLEME_HATASI [43]" in r.stderr, r.stdout + r.stderr
    assert (o["units"] / "kanit-web.service").read_text().startswith("[Unit]\nDescription=eski web"), "eski birim geri gelmeli"
    assert not (o["units"] / "kanit-bot.service").exists(), "yeni kopyalanan birim kaldırılmalı"
    assert (o["dest"] / "requirements.txt").read_text() == o["eski_req"]
    assert any("requirements.before" in s for s in o["pip_log"].read_text().splitlines())
    yedek = next((o["kok"] / "yedek").iterdir())
    assert (yedek / "failed-app").exists() and (o["dest"] / "app" / "panel.py").exists()
    assert "Servis birim dosyaları eski hâline alınıyor" in r.stderr
