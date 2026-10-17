#!/usr/bin/env python3
"""Özel ayar dosyasını sabit sunucu .env dosyasına birleştirir; sır yazdırmaz."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import os
import pwd
import re
import shutil
import stat
import tempfile
from dotenv import dotenv_values

FIELDS={'TELEGRAM_TOKEN','GYAZO_TOKEN','BOT_PASSWORD','ADMIN_PASSWORD','ADMIN_IDS','MAX_DENEME','GYAZO_BAKIM'}
TARGET=Path('/opt/kanit-paneli/.env')
BACKUPS=Path('/var/backups/kanit-paneli')

def parse_patch(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError('Özel dosya normal ve yalnız sahibine açık olmalı; chmod 600 uygulayın.')
    if info.st_size>8192:raise ValueError('Özel ayar dosyası beklenenden büyük.')
    values=dotenv_values(path,interpolate=False)
    if set(values)!=FIELDS or any(value is None for value in values.values()):
        raise ValueError('Özel dosyadaki ayar adları eksik veya beklenenden farklı.')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',values['TELEGRAM_TOKEN']):raise ValueError('Telegram anahtarı biçimi geçersiz.')
    if not values['GYAZO_TOKEN'].strip():raise ValueError('Gyazo anahtarı boş.')
    if not values['BOT_PASSWORD'] or not values['ADMIN_PASSWORD']:raise ValueError('Bot parolası boş olamaz.')
    ids=values['ADMIN_IDS'].split(',')
    if not all(re.fullmatch(r'[1-9][0-9]*',item.strip()) for item in ids):raise ValueError('Telegram yönetici ID biçimi geçersiz.')
    values['ADMIN_IDS']=','.join(dict.fromkeys(item.strip() for item in ids))
    if not values['MAX_DENEME'].isdigit() or not 1<=int(values['MAX_DENEME'])<=10:raise ValueError('Deneme sayısı geçersiz.')
    if values['GYAZO_BAKIM'] not in {'0','1'}:raise ValueError('Eski bakım alanı 0 veya 1 olmalı.')
    if any('\n' in value or '\r' in value or '\x00' in value for value in values.values()):raise ValueError('Çok satırlı ayar kabul edilmez.')
    return values

def merge(text,values):
    pattern=re.compile(r'^\s*(?:export\s+)?('+'|'.join(sorted(FIELDS))+r')\s*=')
    lines=[line for line in text.splitlines() if not pattern.match(line)]
    lines.extend(name+'='+json.dumps(values[name],ensure_ascii=False) for name in sorted(FIELDS))
    return '\n'.join(lines)+'\n'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ozel_dosya',type=Path)
    args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Root olarak çalıştırın.')
    values=parse_patch(args.ozel_dosya)
    info=TARGET.lstat();gid=pwd.getpwnam('kanit').pw_gid
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_gid!=gid or info.st_mode & 0o007:
        raise ValueError('Mevcut .env özel sahiplik/izin kontrolünü sağlamıyor.')
    text=TARGET.read_text();old=dotenv_values(TARGET,interpolate=False);result=merge(text,values)
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=TARGET.parent,prefix='.private-settings-',delete=False) as handle:
        temp=Path(handle.name)
        try:
            os.fchmod(handle.fileno(),0o640);os.fchown(handle.fileno(),0,gid)
            handle.write(result);handle.flush();os.fsync(handle.fileno())
            actual=dotenv_values(temp,interpolate=False)
            if any(actual.get(key)!=value for key,value in old.items() if key not in FIELDS):raise ValueError('Mevcut diğer ayarlar korunamadı.')
            if any(actual.get(key)!=value for key,value in values.items()):raise ValueError('Özel ayar doğrulaması başarısız.')
            BACKUPS.mkdir(mode=0o700,parents=True,exist_ok=True)
            backup=BACKUPS/('private-env-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            backup.mkdir(mode=0o700)
            shutil.copyfile(TARGET,backup/'env.before');os.chmod(backup/'env.before',0o600)
            os.replace(temp,TARGET)
        finally:
            if temp.exists():temp.unlink()
    print('OZEL_AYAR_KAYDEDILDI: Anahtar/parola/ID alanları güncellendi; HTTPS, port, veri yolu ve oturum anahtarı korundu.')
    print('Web veya bot servisi bu yardımcı tarafından yeniden başlatılmadı.')
    print('GYAZO_BAKIM eski uyumluluk alanıdır; 2.1 dönüşümünü açıp kapatmaz.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError):
        print('HATA: Özel dosya, sahiplik, izin veya ayar doğrulaması başarısız; anahtarlar gösterilmedi.')
        raise SystemExit(1)
