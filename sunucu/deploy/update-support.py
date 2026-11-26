#!/usr/bin/env python3
"""Kanit Paneli güncelleme yardımcıları.

Bu dosya yalnızca yerel doğrulama ve SQLite backup API işlemleri yapar. Ortam
anahtarlarının değerlerini hiçbir zaman stdout/stderr'e yazmaz. ``sqlite-backup``
komutu kaynak veritabanını SQLite URI ``mode=ro`` ile açar; hedefi ise çağıranın
sağladığı geçici konumda oluşturur. ``requirements-diff`` iki requirements.txt
dosyasını karşılaştırır ve yalnız sabitlenmiş sürüm yükseltmelerini kabul eder
(yeni paket adı, kaldırılan paket, sürüm düşürme veya serbest sürüm reddedilir).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import Iterable
from urllib.parse import quote


class CheckError(RuntimeError):
    """Kullanıcıya gösterilebilecek, sır taşımayan doğrulama hatası."""


_EXPECTED_ENV = {
    "PANEL_VERI": "/opt/kanit-paneli/data",
    "DINLE": "127.0.0.1",
    "PORT": "18080",
    "HTTPS": "1",
    "TRUST_PROXY": "1",
}
_REQUIRED_APP_FILES = ("__init__.py", "db.py", "settings.py", "panel.py", "bot.py", "bildirim_gecmisi.py", "hatirlatma.py", "api.py", "api_anahtarlari.py", "personel_ozeti.py", "api_kilavuz.py", "kategori_temizlik.py")


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CheckError(f"{label} bulunamadı.") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CheckError(f"{label} normal dosya olmalı; sembolik bağlantı veya özel dosya kabul edilmez.")
    return info


def _regular_directory(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CheckError(f"{label} bulunamadı.") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CheckError(f"{label} normal dizin olmalı; sembolik bağlantı kabul edilmez.")
    return info


def _unquote_env_value(raw: str, line_no: int) -> str:
    """Basit dotenv literalini, kabuk değerlendirmesi yapmadan çöz."""
    value = raw.strip()
    if not value:
        return ""
    if value[0] in ("'", '"'):
        quote_char = value[0]
        if len(value) < 2 or value[-1] != quote_char:
            raise CheckError(f".env satır {line_no}: kapatılmamış tırnak var.")
        return value[1:-1]
    # Tırnaksız değerde yalnız boşluk öncesindeki yorum kısmını ayırır. Kabuk
    # genişletmesi, komut ikamesi veya değişken çözümü kesinlikle yapılmaz.
    return value.split(" #", 1)[0].rstrip()


def parse_dotenv(path: Path) -> dict[str, str]:
    _regular_file(path, ".env")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CheckError(".env UTF-8 metin dosyası olmalı.") from exc
    values: dict[str, str] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        if "=" not in stripped:
            # Diğer uygulama anahtarları için dotenv'in kabul ettiği boş satır/
            # açıklama dışındaki belirsiz sözdizimini sessizce çalıştırmayız.
            raise CheckError(f".env satır {line_no}: NAME=DEGER biçiminde değil.")
        key, raw = stripped.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise CheckError(f".env satır {line_no}: geçersiz anahtar adı var.")
        values[key] = _unquote_env_value(raw, line_no)
    return values


def command_env_check(args: argparse.Namespace) -> None:
    path = Path(args.env)
    info = _regular_file(path, ".env")
    mode = stat.S_IMODE(info.st_mode)
    # root:kanit 0640 veya root-only 0600 uygundur. Dünya erişimi ve grup yazma
    # özel yapılandırma dosyası için kabul edilmez.
    if mode & 0o007 or mode & 0o020 or mode & 0o010:
        raise CheckError(".env özel olmalı; dünya erişimi veya grup yazma/çalıştırma izni var.")
    if args.owner is not None and info.st_uid != args.owner:
        raise CheckError(".env beklenen kullanıcı sahibine ait değil.")
    if args.group is not None and info.st_gid != args.group:
        raise CheckError(".env beklenen grup sahibine ait değil.")
    values = parse_dotenv(path)
    expected_env = dict(_EXPECTED_ENV)
    if getattr(args, "panel_veri", None):
        # Yalnız test/prova ortamı için: beklenen veri dizini farklı bir kökte olabilir.
        expected_env["PANEL_VERI"] = args.panel_veri
    for key, expected in expected_env.items():
        if values.get(key) != expected:
            raise CheckError(f".env içindeki {key} güncelleme uyumluluğu için beklenen yapılandırmada değil.")
    # Değer/özet/hash yazılmaz; yalnız başarı işareti yazılır.
    print("ORTAM_UYUMLU")


def _walk_without_links(app_dir: Path) -> Iterable[Path]:
    """Düzenli dosyaları döndür; kaynak paketinde symlink/special file kabul etme."""
    for current, dirs, files in os.walk(app_dir, topdown=True, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            item = current_path / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise CheckError("Kaynak app içinde sembolik bağlantı veya özel dizin var.")
        for name in files:
            item = current_path / name
            info = item.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise CheckError("Kaynak app içinde sembolik bağlantı veya özel dosya var.")
            yield item


def compile_source_tree(root: Path) -> None:
    _regular_directory(root, "Kaynak kök")
    app_dir = root / "app"
    _regular_directory(app_dir, "Kaynak app dizini")
    _regular_file(root / "requirements.txt", "Kaynak requirements.txt")
    for required in _REQUIRED_APP_FILES:
        _regular_file(app_dir / required, f"Kaynak app/{required}")
    python_files: list[Path] = []
    for item in _walk_without_links(app_dir):
        if item.suffix == ".py":
            python_files.append(item)
    if not python_files:
        raise CheckError("Kaynak app içinde Python dosyası yok.")
    for item in sorted(python_files):
        try:
            source = item.read_text(encoding="utf-8")
            compile(source, str(item), "exec", dont_inherit=True)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            # Kod satırı/ortam sırrı taşımayan kısa hata; traceback döndürülmez.
            raise CheckError("Kaynak Python derleme doğrulaması başarısız.") from exc


def command_source_check(args: argparse.Namespace) -> None:
    compile_source_tree(Path(args.root))
    print("KAYNAK_DOGRULANDI")


def _ro_uri(path: Path) -> str:
    # Path.as_uri() boşlukları kaçışlar; quote Windows olmayan mutlak POSIX yolu
    # için ayrıca güvenlidir. Ubuntu hedefinde bu URI biçimi desteklenir.
    absolute = path.resolve(strict=True)
    return "file:" + quote(str(absolute)) + "?mode=ro"


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    return len(rows) == 1 and str(rows[0][0]).lower() == "ok"


def online_backup(source_path: Path, destination_path: Path) -> None:
    _regular_file(source_path, "Kaynak SQLite veritabanı")
    parent = destination_path.parent
    _regular_directory(parent, "Geçici snapshot dizini")
    if destination_path.exists() or destination_path.is_symlink():
        raise CheckError("Geçici snapshot hedefi zaten var.")
    if source_path.resolve() == destination_path.resolve(strict=False):
        raise CheckError("SQLite snapshot hedefi kaynakla aynı olamaz.")

    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    created = False
    try:
        # Önce güvenli izinli boş dosyayı yalnız çağıranın dizininde oluştururuz.
        fd = os.open(destination_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        created = True
        source = sqlite3.connect(_ro_uri(source_path), uri=True, isolation_level=None, timeout=30)
        source.execute("PRAGMA query_only=ON")
        destination = sqlite3.connect(str(destination_path), isolation_level=None, timeout=30)
        source.backup(destination)
        # Kaynak WAL modundaysa backup API hedef başlığını da WAL olarak kopyalar; snapshot tek dosya olsun
        # (-wal/-shm yan dosyası kalmasın) diye hedef DELETE moduna alınır (kanit-yedek.sh ile aynı).
        destination.execute("PRAGMA journal_mode=DELETE")
        if not _integrity_ok(destination):
            raise CheckError("SQLite snapshot bütünlük denetiminden geçmedi.")
        destination.close()
        destination = None
        source.close()
        source = None
        os.chmod(destination_path, 0o600)
    except (OSError, sqlite3.Error) as exc:
        raise CheckError("SQLite çevrimiçi snapshot oluşturulamadı.") from exc
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        if created and not destination_path.exists():
            created = False
        # Hata halinde eksik/bozuk geçici dosya bırakılmaz.
        if created:
            try:
                # sqlite3 bağlantısında ``with`` kapatmaz; closing ile kesin kapanır (yan dosya kalmaz).
                with contextlib.closing(sqlite3.connect(_ro_uri(destination_path), uri=True, timeout=5)) as verify:
                    valid = _integrity_ok(verify)
            except (OSError, sqlite3.Error):
                valid = False
            if not valid:
                destination_path.unlink(missing_ok=True)


def command_sqlite_backup(args: argparse.Namespace) -> None:
    online_backup(Path(args.source), Path(args.destination))
    print("SQLITE_SNAPSHOT_HAZIR")


def command_schema_check(args: argparse.Namespace) -> None:
    database = Path(args.database)
    _regular_file(database, "SQLite veritabanı")
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(_ro_uri(database), uri=True, timeout=30)
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        found = {str(row[0]) for row in rows}
        required = set(args.table or [])
        if not required.issubset(found):
            raise CheckError("SQLite şema denetiminde gerekli tablo eksik.")
        if not _integrity_ok(conn):
            raise CheckError("SQLite şema denetiminde bütünlük hatası var.")
    except sqlite3.Error as exc:
        raise CheckError("SQLite şema denetimi çalıştırılamadı.") from exc
    finally:
        if conn is not None:
            conn.close()
    print("SQLITE_SEMA_UYUMLU")


_REQ_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([0-9][0-9A-Za-z.]*)$")


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements(path: Path) -> dict[str, tuple[str, str]]:
    """``paket==sürüm`` satırlarını {normalize_ad: (görünen_ad, sürüm)} olarak döndür.

    Boş satır ve ``#`` yorumları atlanır. Başka her sözdizimi (aralık, URL, ek
    seçenek, -r dahil etme) reddedilir; güncelleme betiği bilinçli olarak yalnız
    tam sabitlenmiş beyanlarla çalışır.
    """
    _regular_file(path, "requirements.txt")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise CheckError("requirements.txt UTF-8 metin dosyası olmalı.") from exc
    result: dict[str, tuple[str, str]] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        match = _REQ_LINE.match(stripped)
        if not match:
            raise CheckError(f"requirements.txt satır {line_no}: yalnız 'paket==sürüm' biçimi kabul edilir.")
        name, version = match.group(1), match.group(2)
        key = _normalize_name(name)
        if key in result:
            raise CheckError(f"requirements.txt satır {line_no}: {name} birden çok kez sabitlenmiş.")
        result[key] = (name, version)
    if not result:
        raise CheckError("requirements.txt hiç paket sabitlemiyor.")
    return result


def _version_key(version: str, name: str) -> tuple[int, ...]:
    parts = version.split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise CheckError(
            f"{name} için sürüm '{version}' sayısal (örn. 13.0.0) değil; otomatik yükseltme kabul edilmez."
        ) from exc


def compare_requirements(old: dict[str, tuple[str, str]], new: dict[str, tuple[str, str]]) -> list[tuple[str, str, str]]:
    """Yalnız sürüm yükseltmelerini (ad, eski, yeni) listesi olarak döndür.

    Yeni paket adı, kaldırılan paket veya sürüm düşürme CheckError verir.
    """
    added = sorted(new[key][0] for key in new.keys() - old.keys())
    if added:
        raise CheckError("requirements.txt yeni paket ekliyor: " + ", ".join(added) + ". Bu betik yeni paket kurmaz.")
    removed = sorted(old[key][0] for key in old.keys() - new.keys())
    if removed:
        raise CheckError("requirements.txt paket kaldırıyor: " + ", ".join(removed) + ". Beyan değişikliği elle incelenmeli.")
    changes: list[tuple[str, str, str]] = []
    for key in sorted(new):
        name, new_version = new[key]
        old_version = old[key][1]
        if new_version == old_version:
            continue
        if _version_key(new_version, name) <= _version_key(old_version, name):
            raise CheckError(f"{name} için sürüm düşürme ({old_version} -> {new_version}) kabul edilmez.")
        changes.append((name, old_version, new_version))
    return changes


def command_requirements_diff(args: argparse.Namespace) -> None:
    changes = compare_requirements(parse_requirements(Path(args.old)), parse_requirements(Path(args.new)))
    if not changes:
        print("GEREKSINIMLER_AYNI")
        return
    for name, old_version, new_version in changes:
        print(f"SURUM_YUKSELTME {name} {old_version}->{new_version}")
    print("GEREKSINIMLER_YUKSELTME")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Kanit güncelleme yardımcıları")
    sub = parser.add_subparsers(dest="command", required=True)

    env_check = sub.add_parser("env-check", help="Sır göstermeden .env uyumluluğunu denetle")
    env_check.add_argument("--env", required=True)
    env_check.add_argument("--owner", type=int)
    env_check.add_argument("--group", type=int)
    env_check.add_argument("--panel-veri", help="Beklenen PANEL_VERI (varsayılan /opt/kanit-paneli/data; yalnız prova ortamı için)")
    env_check.set_defaults(func=command_env_check)

    source_check = sub.add_parser("source-check", help="Kaynak app ve Python derlemesini denetle")
    source_check.add_argument("--root", required=True)
    source_check.set_defaults(func=command_source_check)

    backup = sub.add_parser("sqlite-backup", help="Salt-okunur kaynaktan SQLite backup API snapshot al")
    backup.add_argument("--source", required=True)
    backup.add_argument("--destination", required=True)
    backup.set_defaults(func=command_sqlite_backup)

    schema = sub.add_parser("schema-check", help="Salt-okunur SQLite şema/bütünlük denetimi")
    schema.add_argument("--database", required=True)
    schema.add_argument("--table", action="append", default=[])
    schema.set_defaults(func=command_schema_check)

    req_diff = sub.add_parser("requirements-diff", help="İki requirements.txt arasındaki sürüm yükseltmelerini listele; başka değişikliği reddet")
    req_diff.add_argument("--old", required=True)
    req_diff.add_argument("--new", required=True)
    req_diff.set_defaults(func=command_requirements_diff)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except CheckError as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("HATA: Yardımcı beklenmeyen bir yerel dosya hatasıyla durdu.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
