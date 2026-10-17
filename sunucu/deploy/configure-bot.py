#!/usr/bin/env python3
"""Token ve giriş şifresini yalnız root terminalinden alır; hiçbir değeri yazdırmaz."""
import datetime
import getpass
import grp
import os
from pathlib import Path
import re
import shutil
import tempfile


def main():
    if os.geteuid() != 0:
        raise SystemExit('Bu yardımcı root oturumunda çalıştırılmalı.')
    path = Path('/opt/kanit-paneli/.env')
    if not path.is_file() or path.is_symlink():
        raise SystemExit('Normal .env dosyası bulunamadı; değişiklik yapılmadı.')
    gid = grp.getgrnam('kanit').gr_gid
    print('Değerleri yalnız bu terminale girin. Yazarken karakter görünmemesi normaldir.')
    token = getpass.getpass('Telegram bot anahtarı: ').strip()
    if token.startswith('TELEGRAM_TOKEN='):
        token = token.split('=', 1)[1].strip().strip('\"\'')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
        raise SystemExit('Bot anahtarı biçimi uygun değil; dosya değiştirilmedi.')
    password = getpass.getpass('Bota giriş şifresi: ')
    repeat = getpass.getpass('Bota giriş şifresi tekrar: ')
    if not password.strip() or password != repeat:
        raise SystemExit('Giriş şifreleri boş veya birbirinden farklı; dosya değiştirilmedi.')
    if any(c in password for c in '\r\n\x00') or '${' in password:
        raise SystemExit('Parola tek satırlı olmalı ve ${...} ifadesi içermemeli; dosya değiştirilmedi.')

    def quoted(value):
        return '\"' + value.replace('\\', '\\\\').replace('\"', '\\\"') + '\"'

    text = path.read_text()
    for key, value in [('TELEGRAM_TOKEN', token), ('BOT_PASSWORD', password)]:
        pattern = rf'(?m)^{key}=.*$'
        line = key + '=' + quoted(value)
        if re.search(pattern, text):
            text = re.sub(pattern, lambda match, replacement=line: replacement, text)
        else:
            text = text.rstrip('\n') + '\n' + line + '\n'
    backup = Path('/root/kanit-kurulum') / ('bot-ayar-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(mode=0o700, parents=True)
    shutil.copy2(path, backup / 'env.before')
    os.chmod(backup / 'env.before', 0o600)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.env-bot-', delete=False) as f:
            temporary = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), 0o640)
            os.fchown(f.fileno(), 0, gid)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    print('BOT_AYARLARI_KAYDEDILDI')
    print('Yalnız bot anahtarı ve bota giriş şifresi güncellendi. HTTPS, port ve diğer ayarlar korundu.')


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Giriş iptal edildi.')
