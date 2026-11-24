#!/usr/bin/env python3
"""Bot sırlarını yalnız root terminalinden alır ve .env'i atomik günceller; hiçbir değeri yazdırmaz.

    python3 deploy/configure-bot.py              # TELEGRAM_TOKEN + BOT_PASSWORD (bot anahtarı ve bota giriş şifresi)
    python3 deploy/configure-bot.py --yonetici   # yalnız ADMIN_IDS + ADMIN_PASSWORD (Telegram yönetici kimlikleri ve
                                                 # yönetici parolası); diğer satırlara dokunulmaz, dosya izni/sahibi korunur.
                                                 # KURULUM §4'teki sed satırının yerine geçer ('/', '&', '\\' içeren parola sorun değil).

Her iki modda eski .env, /root/kanit-kurulum/bot-ayar-<zaman>/env.before (root 600) olarak yedeklenir ve
sonunda ayarın etkin olması için servisin yeniden başlatılması gerekir: systemctl restart kanit-bot
Test/prova için ezilebilir değerler (canlı sunucuda değiştirmeyin): KANIT_ENV (.env yolu), KANIT_BACKUP_ROOT (yedek kökü).
"""
import argparse
import datetime
import getpass
import grp
import os
from pathlib import Path
import re
import shutil
import tempfile

ENV_PATH = Path(os.environ.get('KANIT_ENV') or '/opt/kanit-paneli/.env')
BACKUP_ROOT = Path(os.environ.get('KANIT_BACKUP_ROOT') or '/root/kanit-kurulum')


def quoted(value):
    return '\"' + value.replace('\\', '\\\\').replace('\"', '\\\"') + '\"'


def parola_kontrol(password, repeat, etiket):
    if not password.strip() or password != repeat:
        raise SystemExit(f'{etiket} boş veya tekrarıyla farklı; dosya değiştirilmedi.')
    if any(c in password for c in '\r\n\x00') or '${' in password:
        raise SystemExit('Parola tek satırlı olmalı ve ${...} ifadesi içermemeli; dosya değiştirilmedi.')


def satirlari_guncelle(text, pairs):
    """Her (anahtar, hazır satır) için: satır varsa yerine koy (ilk eşleşme), yoksa sona ekle. Diğer satırlar aynen kalır."""
    for key, line in pairs:
        pattern = rf'(?m)^{key}=.*$'
        if re.search(pattern, text):
            text = re.sub(pattern, lambda match, replacement=line: replacement, text, count=1)
        else:
            text = text.rstrip('\n') + '\n' + line + '\n'
    return text


def yedekle(path):
    backup = BACKUP_ROOT / ('bot-ayar-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    backup.mkdir(mode=0o700, parents=True)
    shutil.copy2(path, backup / 'env.before')
    os.chmod(backup / 'env.before', 0o600)
    return backup


def atomik_yaz(path, text, mode, uid, gid):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.env-bot-', delete=False) as f:
            temporary = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
            os.fchown(f.fileno(), uid, gid)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def env_dosyasi():
    path = ENV_PATH
    if not path.is_file() or path.is_symlink():
        raise SystemExit('Normal .env dosyası bulunamadı; değişiklik yapılmadı.')
    return path


def bot_ayarla():
    path = env_dosyasi()
    gid = grp.getgrnam('kanit').gr_gid
    print('Değerleri yalnız bu terminale girin. Yazarken karakter görünmemesi normaldir.')
    token = getpass.getpass('Telegram bot anahtarı: ').strip()
    if token.startswith('TELEGRAM_TOKEN='):
        token = token.split('=', 1)[1].strip().strip('\"\'')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}', token):
        raise SystemExit('Bot anahtarı biçimi uygun değil; dosya değiştirilmedi.')
    password = getpass.getpass('Bota giriş şifresi: ')
    repeat = getpass.getpass('Bota giriş şifresi tekrar: ')
    parola_kontrol(password, repeat, 'Giriş şifreleri')
    text = satirlari_guncelle(path.read_text(), [('TELEGRAM_TOKEN', 'TELEGRAM_TOKEN=' + quoted(token)),
                                                 ('BOT_PASSWORD', 'BOT_PASSWORD=' + quoted(password))])
    yedekle(path)
    atomik_yaz(path, text, 0o640, 0, gid)
    print('BOT_AYARLARI_KAYDEDILDI')
    print('Yalnız bot anahtarı ve bota giriş şifresi güncellendi. HTTPS, port ve diğer ayarlar korundu.')
    print('Etkinleşmesi için: systemctl restart kanit-bot')


def yonetici_ayarla():
    path = env_dosyasi()
    print('Değerleri yalnız bu terminale girin. Parola yazılırken karakter görünmemesi normaldir.')
    raw_ids = input('Yönetici Telegram kullanıcı kimlikleri (sayı; birden çoksa virgülle, örn. 123456,987654): ').strip()
    ids = []
    for item in raw_ids.split(','):
        item = item.strip()
        if not item:
            continue
        if not re.fullmatch(r'[0-9]{1,20}', item):
            raise SystemExit('Yönetici kimliği yalnız rakamlardan oluşmalı (virgülle ayrılmış); dosya değiştirilmedi.')
        if item not in ids:
            ids.append(item)
    if not ids:
        raise SystemExit('En az bir yönetici kimliği gerekli; dosya değiştirilmedi.')
    password = getpass.getpass('Yönetici parolası: ')
    repeat = getpass.getpass('Yönetici parolası tekrar: ')
    parola_kontrol(password, repeat, 'Yönetici parolaları')
    text = satirlari_guncelle(path.read_text(), [('ADMIN_IDS', 'ADMIN_IDS=' + ','.join(ids)),
                                                 ('ADMIN_PASSWORD', 'ADMIN_PASSWORD=' + quoted(password))])
    info = path.stat()
    yedekle(path)
    atomik_yaz(path, text, info.st_mode & 0o7777, info.st_uid, info.st_gid)
    print('YONETICI_AYARLARI_KAYDEDILDI')
    print(f'Yalnız ADMIN_IDS ({len(ids)} kimlik) ve ADMIN_PASSWORD güncellendi; diğer satırlar, dosya izni ve sahibi korundu.')
    print('Etkinleşmesi için: systemctl restart kanit-bot')


def main():
    parser = argparse.ArgumentParser(description='Kanıt Paneli bot ayarları (.env, yalnız root)')
    parser.add_argument('--yonetici', action='store_true', help='yalnız ADMIN_IDS ve ADMIN_PASSWORD sor ve güncelle')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Bu yardımcı root oturumunda çalıştırılmalı.')
    if args.yonetici:
        yonetici_ayarla()
    else:
        bot_ayarla()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit('Giriş iptal edildi.')
