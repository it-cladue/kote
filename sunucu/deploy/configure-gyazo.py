#!/usr/bin/env python3
"""Yalnız GYAZO_TOKEN alanını güvenli biçimde güncelle.

Canlı .env bu geliştirme görevi sırasında okunmaz; bu yardımcı üretimde root
terminalinden çalıştırılmak içindir. Diğer tüm satırlar (HTTPS dahil) korunur.
"""
from __future__ import annotations

import getpass
import grp
import os
from pathlib import Path
import re
import sys
import tempfile

DEFAULT_ENV = Path('/opt/kanit-paneli/.env')


def _quoted(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def update_gyazo_token(path: Path, token: str, *, gid: int | None = None) -> None:
    """Atomically replace only GYAZO_TOKEN and retain root:kanit 0640 policy."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Normal .env dosyası bulunamadı; değişiklik yapılmadı.')
    token = str(token).strip()
    if not token or any(c in token for c in '\r\n\x00') or '${' in token:
        raise ValueError('Gyazo anahtarı tek satırlı ve boş olmayan bir değer olmalı; dosya değiştirilmedi.')
    original = path.read_text(encoding='utf-8')
    line = 'GYAZO_TOKEN=' + _quoted(token)
    if re.search(r'(?m)^GYAZO_TOKEN=.*$', original):
        changed = re.sub(r'(?m)^GYAZO_TOKEN=.*$', lambda _: line, original)
    else:
        changed = original.rstrip('\n') + '\n' + line + '\n'
    if gid is None:
        gid = grp.getgrnam('kanit').gr_gid
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.env-gyazo-', delete=False) as f:
            temporary = f.name
            f.write(changed)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), 0o640)
            os.fchown(f.fileno(), 0, int(gid))
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit('Bu yardımcı root oturumunda çalıştırılmalı.')
    if not sys.stdin.isatty():
        raise SystemExit('Anahtar yalnız özel bir TTY terminalinden girilebilir.')
    print('Gyazo anahtarını yalnız bu özel terminale girin; yazarken karakter görünmez.')
    token = getpass.getpass('Gyazo erişim anahtarı: ')
    try:
        update_gyazo_token(DEFAULT_ENV, token)
    except (KeyError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print('GYAZO_TOKEN_KAYDEDILDI')
    print('Yalnız GYAZO_TOKEN güncellendi; HTTPS, port ve diğer .env ayarları korunmuştur.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Giriş iptal edildi.')
