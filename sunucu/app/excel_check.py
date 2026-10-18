# -*- coding: utf-8 -*-
"""Kanıt kontrolü: XLSX/ODS/metin kaynaklarını yalnızca SELECT ile eşleştirir.

Serbest dosya sütunları SQL sütunu değildir.  Bu modülün sabit alan kataloğu dışına
çıkılmaz; kontrol ``kayitlar`` tablosuna kayıt eklemez/değiştirmez.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import file_sources

# SQL sütun adı üretiminde kullanılabilecek tek liste.
FIELDS = ("proje", "kategori", "personel", "uye_id", "ana_uye_id", "tip", "lead_id")
FIELD_LABELS = {
    "proje": "Proje", "kategori": "Kategori", "personel": "Personel",
    "uye_id": "Üye ID", "ana_uye_id": "Ana üye ID", "tip": "Tür", "lead_id": "Lead ID",
}
KEY_FIELDS = ("personel", "uye_id", "ana_uye_id", "lead_id")
CATEGORICAL_FIELDS = frozenset(("proje", "kategori", "tip"))
MAX_RELEVANT_ROWS = file_sources.MAX_RELEVANT_ROWS
MAX_MATCH_IDS = 1_000


class ExcelCheckError(ValueError):
    """Kullanıcıya gösterilebilecek, dosya yolu içermeyen doğrulama hatası."""


def yerel_zaman_metni(value: Any) -> str:
    """Rapordaki UTC/ISO damgasını sunucunun yerel saatiyle "gg.aa.yyyy ss:dd" biçiminde verir.

    Boş değer boş döner; çözülemeyen değer olduğu gibi döner (bilgi kaybolmasın)."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%d.%m.%Y %H:%M")


def _as_error(exc: Exception) -> ExcelCheckError:
    return ExcelCheckError(str(exc))


def _text(value: Any) -> str:
    if isinstance(value, file_sources.Cell):
        return value.text()
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _normal(value: Any, field: str) -> str:
    text = _text(value)
    return text.casefold() if field in CATEGORICAL_FIELDS else text


def _column_letter(index: int) -> str:
    result = ""
    number = index + 1
    while number:
        number, rem = divmod(number - 1, 26)
        result = chr(65 + rem) + result
    return result


def validate_source(path: str | Path, options: dict[str, Any] | None = None) -> bool:
    """Yeni ortak doğrulama API'si; biçimi uzantı/opsiyonla güvenle doğrular."""
    try:
        return file_sources.validate_source(path, options)
    except file_sources.SourceError as exc:
        raise _as_error(exc) from exc


def inspect_source(path: str | Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Yeni ortak inceleme API'si; legacy ``sheets/headers/sample`` anahtarları korunur."""
    try:
        return file_sources.inspect_source(path, options)
    except file_sources.SourceError as exc:
        raise _as_error(exc) from exc


def validate_xlsx(path: str | Path) -> bool:
    """Eski API wrapper'ı: yalnızca XLSX kabulü ve eski hata türü korunur."""
    try:
        return file_sources.validate_xlsx(path)
    except file_sources.SourceError as exc:
        raise _as_error(exc) from exc


def inspect_workbook(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Eski API wrapper'ı: eski sonuç şekli **yalnızca** sheets'tir."""
    validate_xlsx(path)
    inspected = inspect_source(path, {"header_row": 1})
    return {"sheets": inspected["sheets"]}


def _allowed_projects(allowed_projects: Any) -> tuple[list[str], dict[str, str]]:
    allowed: list[str] = []
    normalized: dict[str, str] = {}
    for raw in allowed_projects or []:
        project = str(raw or "").strip()
        if project and project.casefold() not in normalized:
            allowed.append(project)
            normalized[project.casefold()] = project
    return allowed, normalized


def _get_options(path: str | Path, options: dict[str, Any], allowed_projects: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Dosya seçeneklerini layout ve sabit alan kataloğuna göre doğrular."""
    if not isinstance(options, dict):
        raise ExcelCheckError("Kontrol seçenekleri geçersiz.")
    inspected = inspect_source(path, options)
    fmt = inspected["format"]
    sheets = inspected["sheets"]
    is_id_list = fmt == "id_list"

    selected_name = str(options.get("sheet") or "").strip()
    if is_id_list:
        selected = sheets[0]
        if selected_name and selected_name != selected["name"]:
            raise ExcelCheckError("TXT ID listesinde çalışma sayfası seçilemez.")
    elif selected_name:
        selected = next((item for item in sheets if item["name"] == selected_name), None)
        if selected is None:
            raise ExcelCheckError("Seçilen çalışma sayfası bulunamadı.")
    elif len(sheets) == 1:
        selected = sheets[0]
    else:
        raise ExcelCheckError("Çalışma sayfası seçin.")

    raw_match_fields = options.get("match_fields") or []
    if isinstance(raw_match_fields, str):
        raw_match_fields = [raw_match_fields]
    if not isinstance(raw_match_fields, (list, tuple, set)):
        raise ExcelCheckError("Karşılaştırma alanları geçersiz.")
    match_fields: list[str] = []
    for field in raw_match_fields:
        if field not in FIELDS:
            raise ExcelCheckError("Desteklenmeyen karşılaştırma alanı seçildi.")
        if field not in match_fields:
            match_fields.append(field)

    raw_columns = options.get("columns") or {}
    if not isinstance(raw_columns, dict):
        raise ExcelCheckError("Sütun eşleştirmeleri geçersiz.")
    columns: dict[str, int] = {}
    if is_id_list:
        id_field = str(options.get("id_field") or (match_fields[0] if len(match_fields) == 1 else ""))
        if id_field not in KEY_FIELDS or match_fields != [id_field]:
            raise ExcelCheckError("TXT ID modu yalnızca tek bir anahtar alanla (personel, üye ID, ana üye ID veya Lead ID) kontrol edilir.")
        if any(field in FIELDS and value not in (None, "", "-") for field, value in raw_columns.items()):
            raise ExcelCheckError("TXT ID modunda ikinci sütun/eşleştirme kullanılamaz.")
        columns[id_field] = 0
    else:
        available = {header["column"] for header in selected.get("headers", [])}
        header_row = int(inspected.get("header_row", 1))
        for field, source_column in raw_columns.items():
            if field not in FIELDS:
                raise ExcelCheckError("Desteklenmeyen alan eşleştirmesi seçildi.")
            if source_column in (None, "", "-"):
                continue
            try:
                index = file_sources.column_index(source_column)
            except file_sources.SourceError as exc:
                raise _as_error(exc) from exc
            letter = _column_letter(index)
            if header_row and letter not in available:
                raise ExcelCheckError("Seçilen sütunun başlığı seçilen başlık satırında bulunamadı.")
            columns[field] = index

    if not match_fields:
        raise ExcelCheckError("En az bir karşılaştırma alanı seçin.")
    if not any(field in KEY_FIELDS for field in match_fields):
        raise ExcelCheckError("En az bir anahtar alan (personel, üye ID, ana üye ID veya Lead ID) seçin.")
    missing = [field for field in match_fields if field not in columns]
    if missing:
        raise ExcelCheckError("Seçili karşılaştırma alanının sütun eşleştirmesi eksik.")

    allowed, allowed_normal = _allowed_projects(allowed_projects)
    requested_project = str(options.get("project") or "").strip()
    fixed_project = None
    if requested_project:
        fixed_project = allowed_normal.get(requested_project.casefold())
        if fixed_project is None:
            raise ExcelCheckError("Seçilen proje erişim kapsamınızda değil.")
    kt = str(options.get("kt") or "hepsi")
    if kt not in ("hepsi", "onayli", "bekleyen"):
        raise ExcelCheckError("Geçersiz KT filtresi seçildi.")

    cleaned = {
        "format": fmt, "sheet": selected["name"], "header_row": inspected.get("header_row", 0),
        "columns": {field: _column_letter(index) for field, index in columns.items()},
        "match_fields": match_fields, "project": fixed_project or "", "kt": kt,
        "encoding": inspected.get("encoding"), "delimiter": inspected.get("delimiter"),
        "text_mode": "ids" if is_id_list else (str(options.get("text_mode") or "table") if Path(path).suffix.lower() == ".txt" else None),
    }
    return {"selected": selected, "columns": columns, "match_fields": match_fields,
            "allowed": allowed, "allowed_normal": allowed_normal, "fixed_project": fixed_project,
            "kt": kt, "format": fmt, "header_row": int(inspected.get("header_row", 0))}, cleaned


def _row_value(row: Any, field: str) -> Any:
    if hasattr(row, "keys"):
        return row[field]
    indexes = {"id": 0, "proje": 1, "kategori": 2, "personel": 3, "uye_id": 4,
               "ana_uye_id": 5, "tip": 6, "lead_id": 7}
    return row[indexes[field]]


def _candidate_rows(conn: Any, allowed: list[str], fixed_project: str | None, kt: str,
                    values: dict[str, str], match_fields: list[str], cache: dict[tuple[Any, ...], list[Any]]) -> list[Any]:
    """Parametreli SELECT ile yalnız izinli, silinmemiş adayları getirir."""
    projects = [fixed_project] if fixed_project else allowed
    if not projects:
        return []
    cache_key = (tuple(projects), kt, tuple((field, values[field]) for field in match_fields))
    if cache_key in cache:
        return cache[cache_key]
    where = ["silindi=0", "UPPER(proje) IN (" + ",".join("?" for _ in projects) + ")"]
    params: list[Any] = [project.upper() for project in projects]
    if kt == "onayli":
        where.append("kt=1")
    elif kt == "bekleyen":
        where.append("kt=0")
    for field in match_fields:
        if field in CATEGORICAL_FIELDS:
            where.append(f"KANIT_CASEFOLD(COALESCE({field},''))=?")
            params.append(values[field].casefold())
        else:
            where.append(f"TRIM(COALESCE({field},''))=?")
            params.append(values[field])
    sql = ("SELECT id,proje,kategori,personel,uye_id,ana_uye_id,tip,lead_id "
           "FROM kayitlar WHERE " + " AND ".join(where) + " ORDER BY id LIMIT ?")
    result = conn.execute(sql, (*params, MAX_MATCH_IDS + 1)).fetchall()
    cache[cache_key] = result
    return result


def _matches(candidate: Any, values: dict[str, str], match_fields: list[str]) -> bool:
    return all(_normal(_row_value(candidate, field), field) == _normal(values[field], field)
               for field in match_fields)


def _snapshot_begin(conn: Any) -> bool:
    """Yazı kilidi almayan SQLite deferred snapshot başlatır."""
    if getattr(conn, "in_transaction", False):
        return False
    conn.execute("BEGIN")
    return True


def _status_row(source_row: file_sources.SourceRow, values: dict[str, str], status: str,
                reason: str, ids: list[int] | None = None) -> dict[str, Any]:
    return {"row": source_row.row, "source": source_row.source, "values": values,
            "status": status, "reason": reason, "ids": ids or []}


def check_source(path: str | Path, conn: Any, allowed_projects: Any,
                 options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Her desteklenen kaynağı tek snapshot'ta salt-okunur kontrol eder.

    ``yok`` yalnız güvenilir olarak ayrıştırılmış satırda üretilir. Biçim, formül,
    anahtar ya da proje-kapsam belirsizliği ayrı durum olarak raporlanır.
    """
    options = dict(options or {})
    parsed, clean_options = _get_options(path, options, allowed_projects)
    started_snapshot = False
    rows: list[dict[str, Any]] = []
    cache: dict[tuple[Any, ...], list[Any]] = {}
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    skipped_blank_rows = 0
    relevant = 0
    selected_sheet = parsed["selected"]["name"]
    columns: dict[str, int] = parsed["columns"]
    match_fields: list[str] = parsed["match_fields"]

    try:
        # Kullanıcının aynı bağlantıda yazma transaction'ı açılmışsa onu bozmadan
        # kullanır; normal panel bağlantısında BEGIN deferred ile okunur.
        started_snapshot = _snapshot_begin(conn)
        conn.create_function("KANIT_CASEFOLD", 1, lambda value: _text(value).casefold(), deterministic=True)
        for source_row in file_sources.iter_source_rows(path, options):
            if source_row.sheet != selected_sheet:
                continue
            if source_row.row <= parsed["header_row"]:
                continue
            cells = {field: source_row.cells.get(index, file_sources.Cell()) for field, index in columns.items()}
            data_like = any(cell.has_data() for cell in cells.values())
            if not data_like:
                skipped_blank_rows += 1
                continue
            relevant += 1
            if relevant > MAX_RELEVANT_ROWS:
                raise ExcelCheckError("Seçili kaynakta 20.000'den fazla ilgili satır var; dosyayı bölerek tekrar deneyin.")
            values = {field: cells[field].text() for field in match_fields}

            selected_formula_missing = [field for field in match_fields if "formula_without_value" in cells[field].flags]
            if selected_formula_missing:
                rows.append(_status_row(source_row, values, "formul_sonucsuz", "Seçili hücrede güvenilir saklanmış formül sonucu yok."))
                continue
            blank_keys = [field for field in match_fields if field in KEY_FIELDS and not values[field]]
            missing_fields = [field for field in match_fields if not values[field]]
            if blank_keys:
                rows.append(_status_row(source_row, values, "anahtar_bos", "Veri bulunan satırda zorunlu anahtar alan boş."))
                continue
            if missing_fields:
                rows.append(_status_row(source_row, values, "eksik_alan", "Seçili karşılaştırma alanı boş veya boolean."))
                continue

            # Proje sütunu seçilmiş karşılaştırma alanı olmasa bile sabit filtreyle
            # çelişiyorsa sorgu yapılmaz; yanlış projedeki kayıt ID'si asla dönmez.
            project_cell = cells.get("proje")
            project_value = project_cell.text() if project_cell else ""
            if project_cell and "formula_without_value" in project_cell.flags:
                rows.append(_status_row(source_row, values, "formul_sonucsuz", "Eşlenmiş proje hücresinin güvenilir formül sonucu yok."))
                continue
            if project_value and project_value.casefold() not in parsed["allowed_normal"]:
                rows.append(_status_row(source_row, values, "erisim_kapsami_disi", "Dosyadaki proje erişim kapsamınızda değil."))
                continue
            if parsed["fixed_project"] and project_value and project_value.casefold() != parsed["fixed_project"].casefold():
                rows.append(_status_row(source_row, values, "proje_filtre_uyusmazligi", "Dosyadaki proje sabit proje filtresiyle uyuşmuyor."))
                continue

            candidates = _candidate_rows(conn, parsed["allowed"], parsed["fixed_project"], parsed["kt"], values, match_fields, cache)
            ids = [int(_row_value(candidate, "id")) for candidate in candidates if _matches(candidate, values, match_fields)]
            if len(ids) == 1:
                status, reason = "bulundu", "Tek eşleşen kayıt bulundu."
            elif len(ids) > 1:
                status, reason = "birden_cok", "Birden çok kayıt tüm seçili ölçütlerle eşleşiyor."
            elif any("formatted_identifier_risk" in cells[field].flags for field in match_fields if field in KEY_FIELDS):
                status, reason = "bicim_belirsiz", "ID sayı/tarih/biçim hassasiyeti taşıyor; sütunu Metin yapıp yeniden yükleyin."
            else:
                status, reason = "yok", "Snapshot içinde kesin eşleşme yok."
            report_row = _status_row(source_row, values, status, reason, ids[:MAX_MATCH_IDS])
            if len(ids) > MAX_MATCH_IDS:
                report_row["truncated"] = True
            rows.append(report_row)
    except file_sources.SourceError as exc:
        raise _as_error(exc) from exc
    finally:
        if started_snapshot:
            # SELECT snapshot'ı kapatır; BEGIN IMMEDIATE/commit kullanılmaz.
            conn.rollback()

    found = sum(item["status"] == "bulundu" for item in rows)
    missing = sum(item["status"] == "yok" for item in rows)
    multiple = sum(item["status"] == "birden_cok" for item in rows)
    invalid = sum(item["status"] not in {"bulundu", "yok", "birden_cok"} for item in rows)
    metadata = {
        "checked_at": checked_at, "snapshot": "deferred_read" if started_snapshot else "caller_transaction",
        "scope": {"allowed_projects": parsed["allowed"], "fixed_project": parsed["fixed_project"], "kt": parsed["kt"]},
        "options": clean_options, "limits": {"relevant_rows": MAX_RELEVANT_ROWS, "match_ids": MAX_MATCH_IDS},
        "skipped_blank_rows": skipped_blank_rows, "field_catalog": file_sources.field_catalog_metadata(),
    }
    return {"rows": rows, "found": found, "missing": missing, "ambiguous": multiple,
            "multiple": multiple, "invalid": invalid, "total": len(rows), "metadata": metadata}


def check_workbook(path: str | Path, conn: Any, allowed_projects: Any,
                   options: dict[str, Any]) -> dict[str, Any]:
    """Eski XLSX API wrapper'ı; sonuç anahtarları korunur, metadata eklenir."""
    validate_xlsx(path)
    return check_source(path, conn, allowed_projects, options)
