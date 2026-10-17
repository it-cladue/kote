"""Dinamik proje, kategori ve soru kataloğu.

Bu modül taban ``db.py`` şemasını değiştirmez. Parent, ``db.baglan``
sonrasında :func:`ensure_schema` çağırır. Migration eklemeli ve tekrar
çalıştırılabilir; legacy seed yalnızca ilk katalog migration'ında yapılır.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Any, Iterable

from . import db


MIGRATION_NAME = "katalog_2_1"
PROJECT_CODE_RE = re.compile(r"^[A-Z0-9_]{1,24}$")
CATEGORY_CODE_RE = re.compile(r"^[a-z0-9_]{1,48}$")
QUESTION_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Eski settings.py paleti, migration'da yalnız eksik satırları doldurmak için
# kullanılır. Görünen ad başlangıçta kodun kendisidir ve sonra panelden
# serbestçe değiştirilebilir.
LEGACY_PROJECTS = (
    ("PP", "PP", "#A6A6A6"),
    ("PA", "PA", "#4472C4"),
    ("OF", "OF", "#FFFF00"),
    ("HI", "HI", "#FF0000"),
    ("VI", "VI", "#7030A0"),
    ("GA", "GA", "#00B050"),
)
# 2.2: BETA projesi mevcut kurulumlara bir kez, eksikse eklenir. Admin sonradan
# pasife alır veya yeniden adlandırırsa seed tekrar çalışmaz.
BETA_MIGRATION_NAME = "katalog_2_2_beta"
BETA_PROJECT = ("BETA", "BETA", "#FFA500")
LEGACY_MODES = frozenset({"tek_uye", "ark_ana", "ana_only", "sessiz_tip"})
ALLOWED_PRESETS = frozenset({"", "personel", "uye_id", "ana_uye_id", "lead_id", "tip"})


class RevisionConflict(ValueError):
    """Bir katalog satırı form açıldıktan sonra değiştiğinde yükseltilir."""


def _now() -> str:
    return db.simdi()


@contextmanager
def _transaction(conn):
    """db.transaction ile aynı nested-transaction davranışını korur."""
    with db.transaction(conn):
        yield conn


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn, table: str) -> set[str]:
    # Tablo adları bu modülün sabitleri olduğundan interpolation kullanıcı girdisi
    # taşımaz.
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(conn, table: str, column: str, declaration: str) -> None:
    if _table_exists(conn, table) and column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _legacy_questions(mode: str) -> list[dict[str, Any]]:
    """Dört eski wizard mode'unu sürümlü soru tanımlarına çevirir."""
    specs: dict[str, list[dict[str, Any]]] = {
        "tek_uye": [
            {"key": "personel", "label": "Personel", "preset": "personel", "type": "text", "required": True, "options": []},
            {"key": "uye_id", "label": "Üye ID", "preset": "uye_id", "type": "text", "required": True, "options": []},
        ],
        "ark_ana": [
            {"key": "personel", "label": "Personel", "preset": "personel", "type": "text", "required": True, "options": []},
            # Arkadaş/alt üye değeri eski uye_id kolonuna eşlenir; etiket
            # değişik olabilir, preset sabit kalır.
            {"key": "uye_id", "label": "Arkadaş Üye ID", "preset": "uye_id", "type": "text", "required": True, "options": []},
            {"key": "ana_uye_id", "label": "Ana Üye ID", "preset": "ana_uye_id", "type": "text", "required": True, "options": []},
        ],
        "ana_only": [
            {"key": "personel", "label": "Personel", "preset": "personel", "type": "text", "required": True, "options": []},
            {"key": "ana_uye_id", "label": "Ana Üye ID", "preset": "ana_uye_id", "type": "text", "required": True, "options": []},
        ],
        "sessiz_tip": [
            {"key": "personel", "label": "Personel", "preset": "personel", "type": "text", "required": True, "options": []},
            {"key": "uye_id", "label": "Üye ID", "preset": "uye_id", "type": "text", "required": True, "options": []},
            {"key": "tip", "label": "Tip", "preset": "tip", "type": "select", "required": True, "options": ["sessiz", "telesekreter"]},
        ],
    }
    # Yeni dict'ler üret; çağıranın listede yaptığı değişiklik sabit şablona
    # sızmasın.
    return [dict(item, options=list(item["options"])) for item in specs.get(mode, [])]


def ensure_schema(conn) -> None:
    """Katalog DDL'sini kurar ve ilk geçişte legacy veriyi seed eder.

    Bu fonksiyon mevcut kayıtları, kategori etiketlerini, proje aktifliklerini
    veya mevcut ilişki tercihlerinin hiçbirini güncellemez. Migration kaydı
    yerleştiğinde legacy ilişki/question seed'i tekrar çalışmaz.
    """
    with _transaction(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS projeler ("
            "code TEXT PRIMARY KEY, label TEXT NOT NULL, color TEXT NOT NULL, "
            "sort_order INTEGER NOT NULL DEFAULT 0, aktif INTEGER NOT NULL DEFAULT 1, "
            "revision INTEGER NOT NULL DEFAULT 1)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kategoriler ("
            "code TEXT PRIMARY KEY, label TEXT NOT NULL, "
            "mode TEXT NOT NULL DEFAULT 'tek_uye', aktif INTEGER NOT NULL DEFAULT 1, "
            "revision INTEGER NOT NULL DEFAULT 1)"
        )
        _add_column_if_missing(conn, "kategoriler", "mode", "TEXT NOT NULL DEFAULT 'tek_uye'")
        _add_column_if_missing(conn, "kategoriler", "aktif", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "kategoriler", "revision", "INTEGER NOT NULL DEFAULT 1")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS proje_kategorileri ("
            "proje_code TEXT NOT NULL, kategori_code TEXT NOT NULL, "
            "aktif INTEGER NOT NULL DEFAULT 1, sort_order INTEGER NOT NULL DEFAULT 0, "
            "PRIMARY KEY(proje_code,kategori_code), "
            "FOREIGN KEY(proje_code) REFERENCES projeler(code), "
            "FOREIGN KEY(kategori_code) REFERENCES kategoriler(code))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kategori_sorular ("
            "kategori_code TEXT NOT NULL, soru_key TEXT NOT NULL, source TEXT NOT NULL, "
            "preset_key TEXT, label TEXT NOT NULL, type TEXT NOT NULL, "
            "required INTEGER NOT NULL DEFAULT 1, options_json TEXT, "
            "sort_order INTEGER NOT NULL DEFAULT 0, aktif INTEGER NOT NULL DEFAULT 1, "
            "PRIMARY KEY(kategori_code,soru_key), "
            "FOREIGN KEY(kategori_code) REFERENCES kategoriler(code))"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_proje_kategorileri_kategori "
            "ON proje_kategorileri(kategori_code,aktif,sort_order)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_kategori_sorular_sira "
            "ON kategori_sorular(kategori_code,aktif,sort_order)"
        )

        # kayitlar tablosu base db.py tarafından kurulur. Tablo bu bağlantıda
        # henüz yoksa yaratmayız: eksik temel şemalı bir tablo oluşturmak, parent
        # db.py'nin CREATE TABLE IF NOT EXISTS çağrısını yanıltır.
        if _table_exists(conn, "kayitlar"):
            _add_column_if_missing(conn, "kayitlar", "kategori_soru_surumu", "INTEGER")
            _add_column_if_missing(conn, "kayitlar", "soru_anlik_json", "TEXT")
            _add_column_if_missing(conn, "kayitlar", "cevaplar_json", "TEXT")

        first = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name=?", (MIGRATION_NAME,)
        ).fetchone() is None
        if not first:
            _seed_beta_project(conn)
            return

        # Seed INSERT OR IGNORE'dur: yarım kalmış bir ilk migration tekrar
        # çalışsa dahi mevcut admin düzenini/aktiflikleri ezmez.
        for order, (code, label, color) in enumerate(LEGACY_PROJECTS, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO projeler(code,label,color,sort_order,aktif,revision) "
                "VALUES(?,?,?,?,1,1)",
                (code, label, color, order),
            )

        # Eski kayıtlarda sabit palet dışında kalan kodlar salt tarihsel/pasif
        # proje satırı olur. Kayıt satırları kesinlikle güncellenmez.
        if _table_exists(conn, "kayitlar") and "proje" in _columns(conn, "kayitlar"):
            historical = conn.execute(
                "SELECT DISTINCT proje FROM kayitlar "
                "WHERE proje IS NOT NULL AND TRIM(proje)<>'' ORDER BY proje"
            ).fetchall()
            for index, row in enumerate(historical, start=1):
                code = str(row[0])
                if code in {item[0] for item in LEGACY_PROJECTS}:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO projeler(code,label,color,sort_order,aktif,revision) "
                    "VALUES(?,?,?,?,0,1)",
                    (code, ("Legacy " + code)[:120], "#999999", 1000 + index),
                )

        # Migration anındaki etkin kategoriler, eski davranıştaki gibi her seed
        # projede görünür. Daha sonraki bağlantılarda hiçbir ilişki eklenmez.
        categories = conn.execute(
            "SELECT code,mode FROM kategoriler WHERE aktif=1 ORDER BY rowid"
        ).fetchall()
        for project_code, _, _ in LEGACY_PROJECTS:
            for order, row in enumerate(categories, start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO proje_kategorileri"
                    "(proje_code,kategori_code,aktif,sort_order) VALUES(?,?,1,?)",
                    (project_code, row[0], order),
                )
        for row in categories:
            for order, question in enumerate(_legacy_questions(str(row[1])), start=1):
                conn.execute(
                    "INSERT OR IGNORE INTO kategori_sorular"
                    "(kategori_code,soru_key,source,preset_key,label,type,required,options_json,sort_order,aktif) "
                    "VALUES(?,?,?,?,?,?,?,?,?,1)",
                    (
                        row[0], question["key"], "preset", question["preset"],
                        question["label"], question["type"], int(question["required"]),
                        json.dumps(question["options"], ensure_ascii=False), order,
                    ),
                )
        conn.execute(
            "INSERT INTO schema_migrations(name,applied_at) VALUES(?,?)",
            (MIGRATION_NAME, _now()),
        )
        _seed_beta_project(conn)


def _seed_beta_project(conn) -> None:
    """2.2 geçişi: BETA projesi yoksa aktif olarak ekler; varsa dokunmaz.

    Tek seferliktir (schema_migrations kaydı). Seed anındaki aktif kategoriler
    legacy seed ile aynı mantıkla BETA'ya bağlanır ki Telegram akışında proje
    hemen kullanılabilsin. Mevcut proje/kategori satırları değiştirilmez.
    """
    if conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name=?", (BETA_MIGRATION_NAME,)
    ).fetchone():
        return
    code, label, color = BETA_PROJECT
    if conn.execute("SELECT 1 FROM projeler WHERE code=?", (code,)).fetchone() is None:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0)+1 FROM projeler WHERE sort_order<1000"
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO projeler(code,label,color,sort_order,aktif,revision) "
            "VALUES(?,?,?,?,1,1)",
            (code, label, color, next_order),
        )
        categories = conn.execute(
            "SELECT code FROM kategoriler WHERE aktif=1 ORDER BY rowid"
        ).fetchall()
        for order, row in enumerate(categories, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO proje_kategorileri"
                "(proje_code,kategori_code,aktif,sort_order) VALUES(?,?,1,?)",
                (code, row[0], order),
            )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations(name,applied_at) VALUES(?,?)",
        (BETA_MIGRATION_NAME, _now()),
    )


def _normalise_project_code(code: Any) -> str:
    value = str(code or "").strip().upper()
    if not PROJECT_CODE_RE.fullmatch(value):
        raise ValueError("Proje kodu yalnız büyük harf, rakam ve _ içerebilir (1-24 karakter).")
    if value in {"ADMIN", "SUPERADMIN"}:
        raise ValueError("ADMIN ve SUPERADMIN ayrılmış rol adlarıdır; proje kodu olamaz.")
    return value


def _normalise_category_code(code: Any) -> str:
    value = str(code or "").strip().lower()
    if not CATEGORY_CODE_RE.fullmatch(value):
        raise ValueError("Kategori kodu yalnız küçük harf, rakam ve _ içerebilir (1-48 karakter).")
    return value


def _normalise_label(label: Any, kind: str, limit: int = 120) -> str:
    value = str(label or "").strip()
    if not value:
        raise ValueError(f"{kind} etiketi zorunludur.")
    if len(value) > limit:
        raise ValueError(f"{kind} etiketi en fazla {limit} karakter olabilir.")
    return value


def _as_bool(value: Any, field: str = "Aktiflik") -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"1", "true", "on", "evet"}:
            return True
        if lower in {"0", "false", "off", "hayir", "hayır", ""}:
            return False
    raise ValueError(f"{field} true/false olmalıdır.")


def _expected_revision(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Revision sayısal olmalıdır.") from exc
    if revision < 0:
        raise ValueError("Revision negatif olamaz.")
    return revision


def _row_dict(row) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def list_projects(conn, active_only: bool = False) -> list[dict[str, Any]]:
    """Projeleri sıralı, halka açık sözleşme alanlarıyla döndürür."""
    ensure_schema(conn)
    sql = "SELECT code,label,color,sort_order,aktif,revision FROM projeler"
    if active_only:
        sql += " WHERE aktif=1"
    sql += " ORDER BY sort_order,code"
    return [dict(row) for row in conn.execute(sql)]


def get_project(conn, code: str) -> dict[str, Any] | None:
    ensure_schema(conn)
    # Geçmiş kodeksi okuyabilmek için get çağrısında yeni-kod validasyonu yerine
    # yalnız normalizasyon yapılır; save_project yeni değerleri sıkı doğrular.
    value = str(code or "").strip().upper()
    row = conn.execute(
        "SELECT code,label,color,sort_order,aktif,revision FROM projeler WHERE code=?", (value,)
    ).fetchone()
    return _row_dict(row)


def _project_from_row(row) -> dict[str, Any]:
    return {
        "code": row["code"], "label": row["label"], "color": row["color"],
        "sort_order": row["sort_order"], "aktif": row["aktif"], "revision": row["revision"],
    }


def save_project(
    conn,
    code: str,
    label: str,
    color: str,
    active: bool = True,
    actor: str = "panel",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Proje ekler/günceller/pasifleştirir; kod birincil ve değişmez kimliktir."""
    ensure_schema(conn)
    code = _normalise_project_code(code)
    label = _normalise_label(label, "Proje")
    color = str(color or "").strip().upper()
    if not COLOR_RE.fullmatch(color):
        raise ValueError("Proje rengi #RRGGBB biçiminde olmalıdır.")
    active = _as_bool(active)
    expected = _expected_revision(expected_revision)

    with _transaction(conn):
        current = conn.execute("SELECT * FROM projeler WHERE code=?", (code,)).fetchone()
        if current is None:
            if expected not in (None, 0):
                raise RevisionConflict("Proje henüz bu revision ile mevcut değil; sayfayı yenileyin.")
            next_order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM projeler").fetchone()[0]
            conn.execute(
                "INSERT INTO projeler(code,label,color,sort_order,aktif,revision) VALUES(?,?,?,?,?,1)",
                (code, label, color, next_order, int(active)),
            )
            old = None
        else:
            if expected is not None and expected != int(current["revision"]):
                raise RevisionConflict("Proje başka kullanıcı tarafından değiştirildi; sayfayı yenileyin.")
            old = _project_from_row(current)
            conn.execute(
                "UPDATE projeler SET label=?,color=?,aktif=?,revision=revision+1 WHERE code=?",
                (label, color, int(active), code),
            )
        saved = get_project(conn, code)
        db.denetim_yaz(
            conn, actor or "panel", "katalog_proje_kaydet", proje=code, anahtar=code,
            eski=json.dumps(old, ensure_ascii=False) if old is not None else None,
            yeni=json.dumps(saved, ensure_ascii=False),
            hedef_turu="proje", hedef_id=code,
        )
        db.degisti(conn)
    return saved  # type: ignore[return-value]


def _questions_for_category(conn, category_code: str, active_only: bool = True) -> list[dict[str, Any]]:
    sql = (
        "SELECT soru_key,preset_key,label,type,required,options_json,sort_order "
        "FROM kategori_sorular WHERE kategori_code=?"
    )
    if active_only:
        sql += " AND aktif=1"
    sql += " ORDER BY sort_order,soru_key"
    result: list[dict[str, Any]] = []
    for row in conn.execute(sql, (category_code,)):
        try:
            options = json.loads(row["options_json"] or "[]")
        except (TypeError, ValueError):
            options = []
        if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
            options = []
        result.append(
            {
                "key": row["soru_key"], "label": row["label"],
                "preset": row["preset_key"] or "", "type": row["type"],
                "required": bool(row["required"]), "options": options,
            }
        )
    return result


def questions(conn, category_code: str) -> list[dict[str, Any]]:
    """Bir kategorinin aktif sorularını tanım sırasıyla verir."""
    ensure_schema(conn)
    return _questions_for_category(conn, _normalise_category_code(category_code))


def _category_projects(conn, category_code: str) -> list[str]:
    # Yönetim ekranı aktif ilişki tercihlerini gösterebilmelidir. Pasif proje
    # seçili olsa da ilişki saklanır; wizard zaten proje aktifliğini ayrıca sınar.
    return [
        row[0] for row in conn.execute(
            "SELECT proje_code FROM proje_kategorileri "
            "WHERE kategori_code=? AND aktif=1 ORDER BY sort_order,proje_code",
            (category_code,),
        )
    ]


def _category_from_row(conn, row) -> dict[str, Any]:
    return {
        "code": row["code"], "label": row["label"], "mode": row["mode"],
        "aktif": row["aktif"], "revision": row["revision"],
        "projects": _category_projects(conn, row["code"]),
        "questions": _questions_for_category(conn, row["code"]),
    }


def list_categories(
    conn, project_code: str | None = None, active_only: bool = True
) -> list[dict[str, Any]]:
    """Kategori listesini, isteğe bağlı aktif proje üyeliği filtresiyle döndürür."""
    ensure_schema(conn)
    params: list[Any] = []
    if project_code is None:
        sql = "SELECT c.code,c.label,c.mode,c.aktif,c.revision FROM kategoriler c"
        where: list[str] = []
        if active_only:
            where.append("c.aktif=1")
    else:
        code = str(project_code or "").strip().upper()
        sql = (
            "SELECT c.code,c.label,c.mode,c.aktif,c.revision FROM kategoriler c "
            "JOIN proje_kategorileri pk ON pk.kategori_code=c.code "
            "JOIN projeler p ON p.code=pk.proje_code"
        )
        where = ["pk.proje_code=?"]
        params.append(code)
        if active_only:
            where.extend(("c.aktif=1", "pk.aktif=1", "p.aktif=1"))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + ("pk.sort_order,c.code" if project_code is not None else "c.code")
    return [_category_from_row(conn, row) for row in conn.execute(sql, params)]


def get_category(
    conn, code: str, project_code: str | None = None
) -> dict[str, Any] | None:
    """Kategori alır; proje verildiyse aktif proje-kategori üyeliğini doğrular."""
    ensure_schema(conn)
    category_code = _normalise_category_code(code)
    if project_code is None:
        row = conn.execute(
            "SELECT code,label,mode,aktif,revision FROM kategoriler WHERE code=?", (category_code,)
        ).fetchone()
    else:
        project = str(project_code or "").strip().upper()
        row = conn.execute(
            "SELECT c.code,c.label,c.mode,c.aktif,c.revision FROM kategoriler c "
            "JOIN proje_kategorileri pk ON pk.kategori_code=c.code "
            "JOIN projeler p ON p.code=pk.proje_code "
            "WHERE c.code=? AND pk.proje_code=? AND c.aktif=1 AND pk.aktif=1 AND p.aktif=1",
            (category_code, project),
        ).fetchone()
    return _category_from_row(conn, row) if row is not None else None


def _validate_projects(conn, projects: Iterable[Any]) -> list[str]:
    if isinstance(projects, (str, bytes)):
        raise ValueError("projects açık bir liste olmalıdır.")
    try:
        values = list(projects)
    except TypeError as exc:
        raise ValueError("projects açık bir liste olmalıdır.") from exc
    result = [_normalise_project_code(value) for value in values]
    if len(set(result)) != len(result):
        raise ValueError("Aynı proje kategoriye birden fazla bağlanamaz.")
    if result:
        placeholders = ",".join("?" for _ in result)
        existing = {
            row[0] for row in conn.execute(
                f"SELECT code FROM projeler WHERE code IN ({placeholders})", result
            )
        }
        missing = [code for code in result if code not in existing]
        if missing:
            raise ValueError("Bilinmeyen proje: " + ", ".join(missing))
    return result


def _validate_questions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("Sorular JSON listesi olmalıdır.")
    if not 1 <= len(value) <= 20:
        raise ValueError("Kategori 1 ile 20 arasında açık soru içermelidir.")
    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    presets: set[str] = set()
    for index, raw in enumerate(value, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{index}. soru nesne olmalıdır.")
        key = str(raw.get("key") or "").strip().lower()
        if not QUESTION_KEY_RE.fullmatch(key):
            raise ValueError(f"{index}. soru anahtarı sabit ASCII biçiminde olmalıdır.")
        if key in keys:
            raise ValueError("Tekrarlanan soru anahtarı: " + key)
        keys.add(key)
        preset = raw.get("preset", "")
        preset = "" if preset is None else str(preset).strip().lower()
        if preset not in ALLOWED_PRESETS:
            raise ValueError("Geçersiz hazır soru: " + preset)
        if preset:
            if preset in presets:
                raise ValueError("Tekrarlanan hazır soru: " + preset)
            presets.add(preset)
            if key != preset:
                raise ValueError("Hazır soru anahtarı preset değeriyle aynı olmalıdır.")
        label = _normalise_label(raw.get("label"), "Soru", 120)
        qtype = str(raw.get("type") or "").strip().lower()
        if qtype not in {"text", "select"}:
            raise ValueError("Soru tipi text veya select olmalıdır.")
        required = _as_bool(raw.get("required", True), "Soru zorunluluğu")
        options = raw.get("options", [])
        if not isinstance(options, list) or not all(isinstance(item, str) for item in options):
            raise ValueError("Soru seçenekleri string listesi olmalıdır.")
        options = [item.strip() for item in options]
        if any(not item or len(item) > 80 for item in options):
            raise ValueError("Her soru seçeneği 1-80 karakter olmalıdır.")
        if len(options) > 30:
            raise ValueError("Bir soruda en fazla 30 seçenek olabilir.")
        if qtype == "select" and not options:
            raise ValueError("Select soru en az bir seçenek içermelidir.")
        if qtype == "text" and options:
            raise ValueError("Text soru seçenek içeremez.")
        result.append(
            {
                "key": key, "label": label, "preset": preset, "type": qtype,
                "required": required, "options": options,
            }
        )
    return result


def save_category(
    conn,
    code: str,
    label: str,
    mode: str = "custom",
    projects: Iterable[Any] | None = None,
    questions: list[dict[str, Any]] | None = None,
    active: bool = True,
    actor: str = "panel",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Kategori, proje üyeliği ve sıralı soru şemasını atomik kaydeder."""
    ensure_schema(conn)
    code = _normalise_category_code(code)
    label = _normalise_label(label, "Kategori")
    mode = str(mode or "").strip().lower()
    if mode not in LEGACY_MODES | {"custom"}:
        raise ValueError("Geçersiz kategori modu.")
    active = _as_bool(active)
    expected = _expected_revision(expected_revision)
    project_values = _validate_projects(conn, projects) if projects is not None else None
    if questions is None:
        if mode not in LEGACY_MODES:
            raise ValueError("Custom kategori için en az bir soru gönderilmelidir.")
        question_values = _legacy_questions(mode)
    else:
        question_values = _validate_questions(questions)

    with _transaction(conn):
        current = conn.execute("SELECT * FROM kategoriler WHERE code=?", (code,)).fetchone()
        if current is None:
            if expected not in (None, 0):
                raise RevisionConflict("Kategori henüz bu revision ile mevcut değil; sayfayı yenileyin.")
            conn.execute(
                "INSERT INTO kategoriler(code,label,mode,aktif,revision) VALUES(?,?,?,?,1)",
                (code, label, mode, int(active)),
            )
            old: dict[str, Any] | None = None
        else:
            if expected is not None and expected != int(current["revision"]):
                raise RevisionConflict("Kategori başka kullanıcı tarafından değiştirildi; sayfayı yenileyin.")
            old = _category_from_row(conn, current)
            conn.execute(
                "UPDATE kategoriler SET label=?,mode=?,aktif=?,revision=revision+1 WHERE code=?",
                (label, mode, int(active), code),
            )

        if project_values is not None:
            # Açık liste semantiği: seçilmeyen önceki üyelikler pasifleşir;
            # tarihsel ilişki satırı fiziksel olarak silinmez.
            conn.execute("UPDATE proje_kategorileri SET aktif=0 WHERE kategori_code=?", (code,))
            for order, project_code in enumerate(project_values, start=1):
                conn.execute(
                    "INSERT INTO proje_kategorileri(proje_code,kategori_code,aktif,sort_order) "
                    "VALUES(?,?,1,?) ON CONFLICT(proje_code,kategori_code) DO UPDATE SET "
                    "aktif=1,sort_order=excluded.sort_order",
                    (project_code, code, order),
                )

        # UI'da silinen soru pasif kalır. Bu, eski snapshotların kendi anahtar
        # tanımıyla okunmasına ve yanlışlıkla fiziksel veri kaybı olmamasına yarar.
        conn.execute("UPDATE kategori_sorular SET aktif=0 WHERE kategori_code=?", (code,))
        for order, question in enumerate(question_values, start=1):
            conn.execute(
                "INSERT INTO kategori_sorular"
                "(kategori_code,soru_key,source,preset_key,label,type,required,options_json,sort_order,aktif) "
                "VALUES(?,?,?,?,?,?,?,?,?,1) ON CONFLICT(kategori_code,soru_key) DO UPDATE SET "
                "source=excluded.source,preset_key=excluded.preset_key,label=excluded.label,"
                "type=excluded.type,required=excluded.required,options_json=excluded.options_json,"
                "sort_order=excluded.sort_order,aktif=1",
                (
                    code, question["key"], "preset" if question["preset"] else "custom",
                    question["preset"] or None, question["label"], question["type"],
                    int(question["required"]), json.dumps(question["options"], ensure_ascii=False), order,
                ),
            )

        saved = get_category(conn, code)
        db.denetim_yaz(
            conn, actor or "panel", "katalog_kategori_kaydet", anahtar=code,
            eski=json.dumps(old, ensure_ascii=False) if old is not None else None,
            yeni=json.dumps(saved, ensure_ascii=False),
            hedef_turu="kategori", hedef_id=code,
        )
        db.degisti(conn)
    return saved  # type: ignore[return-value]
