# -*- coding: utf-8 -*-
"""Kanıt kontrolü için güvenli, biçimden bağımsız satır yükleyicileri.

Bu modül *yalnızca okur*.  Serbest dosya başlıkları hiçbir zaman SQL adı değildir;
eşleştirme katmanı yalnız kendi allowlist alanlarını sütun indislerine bağlar.
"""
from __future__ import annotations

import csv
import io
import os
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 150
MAX_ZIP_ENTRIES = 10_000
MAX_SOURCE_ROWS = 50_000
MAX_RELEVANT_ROWS = 20_000
MAX_COLUMNS = 512
MAX_FIELD_CHARS = 32_768
MAX_TOTAL_TEXT_CHARS = 24 * 1024 * 1024

# csv.field_size_limit süreç genelidir. Her istek sırasında değiştirip eski değere
# dönmek eşzamanlı denetimlerde yarış yaratacağından güvenli üst sınırı bir kez
# modül yüklenirken sabitliyoruz.
csv.field_size_limit(MAX_FIELD_CHARS)

_COLUMN_RE = re.compile(r"^[A-Z]{1,3}$")
_DATE_NUMFMTS = set(range(14, 23)) | {45, 46, 47}
_XLSX_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class SourceError(ValueError):
    """Kullanıcıya gösterilebilecek, yol sızdırmayan kaynak doğrulama hatası."""


@dataclass(frozen=True)
class Cell:
    """Bir hücrenin karşılaştırma ve teşhis için minimal, güvenli temsili."""

    raw_text: str | None = None
    display_text: str | None = None
    kind: str = "blank"  # text, numeric, date, boolean, formula, blank
    flags: frozenset[str] = field(default_factory=frozenset)

    def text(self) -> str:
        return "" if self.raw_text is None else str(self.raw_text).strip()

    def has_data(self) -> bool:
        # Tek başına Excel/ODS boolean işareti kayıt satırı değildir.
        return bool(self.text()) or "formula_without_value" in self.flags


@dataclass(frozen=True)
class SourceRow:
    """Fiziksel konumu korunmuş seyrek kaynak satırı."""

    source: str
    row: int
    cells: dict[int, Cell]
    sheet: str | None = None


def _error(message: str) -> SourceError:
    return SourceError(message)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _attr(element: ET.Element, name: str, default: str = "") -> str:
    """Namespace'e bağlı olmadan ODF niteliği alır."""
    if name in element.attrib:
        return element.attrib[name]
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return default


def _column_letter(index: int) -> str:
    result = ""
    number = index + 1
    while number:
        number, rem = divmod(number - 1, 26)
        result = chr(65 + rem) + result
    return result


def column_index(value: Any) -> int:
    clean = str(value or "").strip().upper()
    if not _COLUMN_RE.fullmatch(clean):
        raise _error("Geçersiz kaynak sütunu seçildi.")
    number = 0
    for character in clean:
        number = number * 26 + ord(character) - 64
    if not 1 <= number <= 16_384:
        raise _error("Geçersiz kaynak sütunu seçildi.")
    return number - 1


def _source_format(path: os.PathLike[str] | str, options: dict[str, Any] | None = None) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".xlsx":
        return "xlsx"
    if suffix == ".ods":
        return "ods"
    if suffix in (".csv", ".tsv"):
        return "delimited"
    if suffix == ".txt":
        mode = str((options or {}).get("text_mode") or "ids").strip().lower()
        if mode not in ("ids", "table"):
            raise _error("TXT modu yalnızca ids veya table olabilir.")
        return "id_list" if mode == "ids" else "delimited"
    if suffix in (".xls", ".xlsm", ".xlsb"):
        raise _error(".xls, .xlsm ve .xlsb desteklenmez; dosyayı .xlsx, .ods veya metin tablo olarak dışa aktarın.")
    raise _error("Yalnızca .xlsx, .ods, .csv, .tsv veya .txt kaynakları desteklenir.")


def source_format(path: os.PathLike[str] | str, options: dict[str, Any] | None = None) -> str:
    """Uzantı temelli desteklenen kaynak biçimini döndürür."""
    return _source_format(path, options)


def _assert_file_size(path: os.PathLike[str] | str) -> None:
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        raise _error("Kaynak dosya okunamadı.") from exc
    if size > MAX_UPLOAD_BYTES:
        raise _error("Dosya 12 MB yükleme sınırını aşıyor.")


def _safe_archive(archive: zipfile.ZipFile, expected: set[str], label: str) -> set[str]:
    infos = archive.infolist()
    if not infos:
        raise _error(f"Geçerli bir {label} çalışma kitabı değil.")
    if len(infos) > MAX_ZIP_ENTRIES:
        raise _error("Çalışma kitabında çok fazla arşiv girdisi var.")
    names: set[str] = set()
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        parts = [part for part in name.split("/") if part]
        if not name or name.startswith("/") or ".." in parts:
            raise _error(f"Geçerli bir {label} çalışma kitabı değil.")
        if name in names:
            raise _error("Çalışma kitabında yinelenen ZIP girdisi var.")
        names.add(name)
        if info.flag_bits & 0x1:
            raise _error("Şifreli çalışma kitapları desteklenmez.")
        total += info.file_size
        if total > MAX_DECOMPRESSED_BYTES:
            raise _error("Çalışma kitabının açılmış boyutu 128 MB sınırını aşıyor.")
        if info.file_size >= 1024 * 1024 and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
            raise _error("Çalışma kitabının sıkıştırma oranı güvenli sınırı aşıyor.")
    if not expected.issubset(names):
        raise _error(f"Geçerli bir {label} çalışma kitabı değil.")
    # ElementTree dahili entity'leri genişletebildiğinden bütün XML parçalarında DTD
    # ve ENTITY bildirimi, ayrıştırmadan önce, akış halinde reddedilir.
    for info in infos:
        if not info.filename.lower().endswith(".xml"):
            continue
        with archive.open(info) as source:
            tail = b""
            for chunk in iter(lambda: source.read(64 * 1024), b""):
                upper = (tail + chunk).upper()
                if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                    raise _error("XML dış varlık/DTD içeren çalışma kitabı kabul edilmez.")
                tail = (tail + chunk)[-16:]
    return names


def validate_xlsx(path: os.PathLike[str] | str) -> bool:
    candidate = Path(path)
    if candidate.suffix.lower() != ".xlsx":
        if candidate.suffix.lower() == ".xls":
            raise _error("Yalnızca .xlsx çalışma kitapları desteklenir; .xls desteklenmez.")
        raise _error("Yalnızca .xlsx çalışma kitabı yüklenebilir.")
    _assert_file_size(candidate)
    try:
        with zipfile.ZipFile(candidate) as archive:
            _safe_archive(archive, {"[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"}, ".xlsx")
    except SourceError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _error("Geçerli bir .xlsx çalışma kitabı değil.") from exc
    return True


def validate_ods(path: os.PathLike[str] | str) -> bool:
    candidate = Path(path)
    if candidate.suffix.lower() != ".ods":
        raise _error("Yalnızca .ods çalışma kitabı yüklenebilir.")
    _assert_file_size(candidate)
    try:
        with zipfile.ZipFile(candidate) as archive:
            _safe_archive(archive, {"mimetype", "content.xml"}, ".ods")
            # ODF mimetype zorunlu olarak OpenDocument Spreadsheet olmalıdır.
            if archive.read("mimetype") != b"application/vnd.oasis.opendocument.spreadsheet":
                raise _error("Geçerli bir .ods çalışma kitabı değil.")
    except SourceError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _error("Geçerli bir .ods çalışma kitabı değil.") from exc
    return True


def _encoding_candidates(raw: bytes) -> list[str]:
    candidates: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf8bom")
    try:
        raw.decode("utf-8", errors="strict")
        candidates.append("utf8")
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp1254", errors="strict")
        candidates.append("cp1254")
    except UnicodeDecodeError:
        pass
    return list(dict.fromkeys(candidates))


def _normal_encoding(value: Any, raw: bytes) -> tuple[str, str, list[str]]:
    requested = str(value or "auto").strip().lower().replace("_", "").replace("-", "")
    aliases = {"utf8bom": ("utf8bom", "utf-8-sig"), "utf8sig": ("utf8bom", "utf-8-sig"),
               "utf8": ("utf8", "utf-8"), "cp1254": ("cp1254", "cp1254")}
    candidates = _encoding_candidates(raw)
    if requested not in ("", "auto"):
        if requested not in aliases:
            raise _error("Kodlama utf8bom, utf8 veya cp1254 olmalıdır.")
        name, codec = aliases[requested]
        try:
            raw.decode(codec, errors="strict")
        except UnicodeDecodeError as exc:
            raise _error("Seçilen kodlama dosyayı kayıpsız okuyamadı.") from exc
        return name, codec, candidates
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf8bom", "utf-8-sig", candidates
    try:
        raw.decode("utf-8", errors="strict")
        return "utf8", "utf-8", candidates
    except UnicodeDecodeError:
        try:
            raw.decode("cp1254", errors="strict")
            return "cp1254", "cp1254", candidates
        except UnicodeDecodeError as exc:
            raise _error("Dosya UTF-8/BOM veya CP1254 olarak kayıpsız okunamadı.") from exc


def _normal_delimiter(value: Any, suffix: str, text: str) -> tuple[str, str, list[str]]:
    requested = str(value or "auto").strip().lower()
    aliases = {"comma": ("comma", ","), ",": ("comma", ","),
               "semicolon": ("semicolon", ";"), ";": ("semicolon", ";"),
               "tab": ("tab", "\t"), "\\t": ("tab", "\t")}
    if requested not in ("", "auto"):
        if requested not in aliases:
            raise _error("Ayraç comma, semicolon, tab veya auto olmalıdır.")
        name, delimiter = aliases[requested]
        return name, delimiter, [name]

    # Sniffer kullanmadan, ilk sınırlı mantıksal kayıtta en tutarlı çok-alanlı
    # ayrımı seçer. Eşitlikte uzantı varsayılanı kullanılır; kullanıcı override eder.
    scores: dict[str, tuple[int, int]] = {}
    for name, delimiter in (("comma", ","), ("semicolon", ";"), ("tab", "\t")):
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))[:20]
        except csv.Error:
            rows = []
        widths = [len(row) for row in rows if row]
        multi = sum(width > 1 for width in widths)
        consistent = max(widths.count(width) for width in set(widths)) if widths else 0
        scores[name] = (multi, consistent)
    preferred = "tab" if suffix == ".tsv" else "comma"
    best = max(scores.values()) if scores else (0, 0)
    names = [name for name, score in scores.items() if score == best and score[0] > 0]
    if preferred in names:
        choice = preferred
    elif len(names) == 1:
        choice = names[0]
    else:
        choice = preferred
    return choice, {"comma": ",", "semicolon": ";", "tab": "\t"}[choice], names or [choice]


def _read_text(path: os.PathLike[str] | str, options: dict[str, Any] | None) -> tuple[str, str, list[str]]:
    _assert_file_size(path)
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise _error("Kaynak dosya okunamadı.") from exc
    if b"\x00" in raw:
        raise _error("Metin kaynağı NUL karakteri içeriyor.")
    name, codec, candidates = _normal_encoding((options or {}).get("encoding"), raw)
    try:
        text = raw.decode(codec, errors="strict")
    except UnicodeDecodeError as exc:  # _normal_encoding already verifies; defensive
        raise _error("Seçilen kodlama dosyayı kayıpsız okuyamadı.") from exc
    if len(text) > MAX_TOTAL_TEXT_CHARS:
        raise _error("Metin kaynağı karakter işleme sınırını aşıyor.")
    return text, name, candidates


def _numeric_text(value: str) -> str:
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return value.strip()
    if not number.is_finite():
        return value.strip()
    if number == number.to_integral_value():
        return format(number.quantize(Decimal("1")), "f")
    return format(number.normalize(), "f")


def _identifier_precision_risk(value: str, format_code: str = "") -> bool:
    digits = re.sub(r"[^0-9]", "", value)
    return len(digits.lstrip("0")) > 15 or "e+" in format_code.casefold()


def _is_date_style(number_format: int, code: str) -> bool:
    if number_format in _DATE_NUMFMTS:
        return True
    clean = re.sub(r'"[^"]*"|\\.', "", code).casefold()
    return bool(clean and re.search(r"[ymdhss]", clean))


def _zero_pad_style(code: str) -> bool:
    # Kesrin sağındaki 00 normal sayı hassasiyeti olabilir; yalnız tamsayı biçimindeki
    # birden çok sıfır, kimlikte görünmeyen baştaki sıfır riski sayılır.
    primary = code.split(";")[0]
    primary = re.sub(r'"[^"]*"|\\.|\[[^]]*\]', "", primary)
    integral = primary.split(".", 1)[0]
    return bool(re.search(r"0{2,}", integral))


def _xlsx_style_info(archive: zipfile.ZipFile) -> dict[int, tuple[bool, bool, str]]:
    try:
        root = ET.fromstring(archive.read("xl/styles.xml"))
    except KeyError:
        return {}
    except ET.ParseError as exc:
        raise _error("Çalışma kitabındaki XML okunamadı.") from exc
    custom: dict[int, str] = {}
    for element in root.iter():
        if _local(element.tag) == "numFmt":
            try:
                custom[int(element.attrib.get("numFmtId", "-1"))] = element.attrib.get("formatCode", "")
            except ValueError:
                continue
    builtin = {1: "0", 2: "0.00", 3: "#,##0", 4: "#,##0.00", 11: "0.00E+00", 49: "@"}
    cell_xfs = next((element for element in root.iter() if _local(element.tag) == "cellXfs"), None)
    result: dict[int, tuple[bool, bool, str]] = {}
    if cell_xfs is None:
        return result
    for index, xf in enumerate(cell_xfs):
        if _local(xf.tag) != "xf":
            continue
        try:
            fmt_id = int(xf.attrib.get("numFmtId", "0"))
        except ValueError:
            fmt_id = 0
        code = custom.get(fmt_id, builtin.get(fmt_id, ""))
        result[index] = (_is_date_style(fmt_id, code), _zero_pad_style(code), code)
    return result


def _xlsx_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError) as exc:
        raise _error("Geçerli bir .xlsx çalışma kitabı değil.") from exc
    targets = {item.attrib.get("Id"): item.attrib.get("Target", "") for item in rels.iter() if _local(item.tag) == "Relationship"}
    sheets: list[tuple[str, str]] = []
    for item in workbook.iter():
        if _local(item.tag) != "sheet":
            continue
        name = item.attrib.get("name", "")
        target = targets.get(item.attrib.get(_XLSX_REL_NS + "id"))
        if not name or not target:
            continue
        xml_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        if xml_path.startswith("../"):
            raise _error("Geçerli bir .xlsx çalışma kitabı değil.")
        sheets.append((name, xml_path))
    if not sheets:
        raise _error("Çalışma kitabında okunabilir sayfa yok.")
    return sheets


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    except ET.ParseError as exc:
        raise _error("Çalışma kitabındaki XML okunamadı.") from exc
    return ["".join(node.text or "" for node in item.iter() if _local(node.tag) == "t")
            for item in root if _local(item.tag) == "si"]


def _xlsx_cell(cell: ET.Element, shared: list[str], styles: dict[int, tuple[bool, bool, str]]) -> Cell:
    cell_type = cell.attrib.get("t", "")
    try:
        style = int(cell.attrib.get("s", "-1"))
    except ValueError:
        style = -1
    date_style, zero_style, fmt = styles.get(style, (False, False, ""))
    formula = any(_local(child.tag) == "f" for child in cell)
    value: str | None = None
    inline: str | None = None
    for child in cell:
        local = _local(child.tag)
        if local == "v" and child.text is not None:
            value = child.text
        elif local == "is":
            inline = "".join(node.text or "" for node in child.iter() if _local(node.tag) == "t")
    if formula and value is None and inline is None:
        return Cell(kind="formula", flags=frozenset({"formula_without_value"}))
    if cell_type == "s":
        try:
            text = shared[int(value or "")]
        except (ValueError, IndexError):
            text = ""
        return Cell(text, text, "formula" if formula else "text")
    if cell_type in ("inlineStr", "str", "e"):
        text = inline if inline is not None else (value or "")
        return Cell(text, text, "formula" if formula else "text")
    if cell_type == "b":
        # Boolean checkbox-style columns alone satır sayılmamalıdır.
        display = "TRUE" if value in ("1", "true", "TRUE") else "FALSE"
        return Cell(None, display, "boolean")
    if value is None:
        return Cell()
    raw = _numeric_text(value)
    flags: set[str] = set()
    if date_style:
        flags.add("formatted_identifier_risk")
        return Cell(raw, raw, "date", frozenset(flags))
    if zero_style or _identifier_precision_risk(value, fmt):
        flags.add("formatted_identifier_risk")
    return Cell(raw, raw, "formula" if formula else "numeric", frozenset(flags))


def _xlsx_rows(path: os.PathLike[str] | str) -> Iterator[SourceRow]:
    validate_xlsx(path)
    try:
        with zipfile.ZipFile(path) as archive:
            sheets = _xlsx_sheets(archive)
            shared = _xlsx_shared_strings(archive)
            styles = _xlsx_style_info(archive)
            for name, xml_path in sheets:
                try:
                    source = archive.open(xml_path)
                except KeyError as exc:
                    raise _error("Çalışma sayfası XML'i eksik.") from exc
                with source:
                    try:
                        for _, row_element in ET.iterparse(source, events=("end",)):
                            if _local(row_element.tag) != "row":
                                continue
                            try:
                                number = int(row_element.attrib.get("r", "0"))
                            except ValueError:
                                number = 0
                            cells: dict[int, Cell] = {}
                            for cell in row_element:
                                if _local(cell.tag) != "c":
                                    continue
                                match = re.match(r"([A-Za-z]+)", cell.attrib.get("r", ""))
                                if not match:
                                    continue
                                try:
                                    index = column_index(match.group(1))
                                except SourceError:
                                    continue
                                if index < MAX_COLUMNS:
                                    cells[index] = _xlsx_cell(cell, shared, styles)
                            if number:
                                yield SourceRow(f"{name}!{number}", number, cells, name)
                            row_element.clear()
                    except ET.ParseError as exc:
                        raise _error("Çalışma kitabındaki XML okunamadı.") from exc
    except SourceError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise _error("Çalışma kitabı okunamadı.") from exc


def _ods_cell(element: ET.Element) -> Cell:
    formula = bool(_attr(element, "formula"))
    value_type = _attr(element, "value-type").casefold()
    display = "".join(node.text or "" for node in element.iter() if _local(node.tag) == "p").strip()
    if value_type in ("", "string"):
        if formula and not display:
            return Cell(kind="formula", flags=frozenset({"formula_without_value"}))
        return Cell(display or None, display or None, "formula" if formula else ("text" if display else "blank"))
    if value_type == "boolean":
        return Cell(None, display or _attr(element, "boolean-value"), "boolean")
    if value_type in ("float", "currency", "percentage"):
        raw = _numeric_text(_attr(element, "value"))
        if formula and not (display or raw):
            return Cell(kind="formula", flags=frozenset({"formula_without_value"}))
        # ODS number styles (styles.xml) görünür baştaki sıfırları gizleyebilir.
        # Stil zincirini kısmen yorumlayıp kesin yok üretmek yerine tüm sayısal ODS
        # ID adaylarını muhafazakâr biçimde belirsiz sayarız.
        flags = frozenset({"formatted_identifier_risk"})
        return Cell(raw or None, display or raw or None, "formula" if formula else "numeric", flags)
    if value_type in ("date", "time"):
        raw = _attr(element, "date-value") or _attr(element, "time-value")
        if formula and not (display or raw):
            return Cell(kind="formula", flags=frozenset({"formula_without_value"}))
        return Cell(raw or None, display or raw or None, "formula" if formula else "date", frozenset({"formatted_identifier_risk"}))
    # Bilinmeyen tip, ancak görünür metin varsa metin gibi ele alınır; yoksa boş.
    if formula and not display:
        return Cell(kind="formula", flags=frozenset({"formula_without_value"}))
    return Cell(display or None, display or None, "formula" if formula else ("text" if display else "blank"))


def _ods_rows(path: os.PathLike[str] | str) -> Iterator[SourceRow]:
    validate_ods(path)
    try:
        with zipfile.ZipFile(path) as archive, archive.open("content.xml") as source:
            table_stack: list[str] = []
            row_numbers: dict[str, int] = {}
            seen_rows: dict[str, int] = {}
            for event, element in ET.iterparse(source, events=("start", "end")):
                local = _local(element.tag)
                if event == "start" and local == "table":
                    table_stack.append(_attr(element, "name") or "Sayfa")
                    continue
                if event == "end" and local == "table-row":
                    if not table_stack:
                        element.clear()
                        continue
                    sheet = table_stack[-1]
                    try:
                        repeats = int(_attr(element, "number-rows-repeated", "1"))
                    except ValueError as exc:
                        raise _error("ODS tekrar satır değeri geçersiz.") from exc
                    if repeats < 1 or repeats > MAX_SOURCE_ROWS:
                        raise _error("ODS tekrar satır sınırı güvenli değil.")
                    seen_rows[sheet] = seen_rows.get(sheet, 0) + repeats
                    if seen_rows[sheet] > MAX_SOURCE_ROWS:
                        raise _error("ODS fiziksel satır sınırını aşıyor.")
                    cells: dict[int, Cell] = {}
                    index = 0
                    for child in element:
                        child_local = _local(child.tag)
                        if child_local not in ("table-cell", "covered-table-cell"):
                            continue
                        try:
                            width = int(_attr(child, "number-columns-repeated", "1"))
                        except ValueError as exc:
                            raise _error("ODS tekrar sütun değeri geçersiz.") from exc
                        if width < 1 or width > MAX_COLUMNS or index + width > MAX_COLUMNS:
                            raise _error("ODS sütun/tekrar sınırı güvenli değil.")
                        value = _ods_cell(child) if child_local == "table-cell" else Cell()
                        for column in range(index, index + width):
                            if value.kind != "blank" or value.flags:
                                cells[column] = value
                        index += width
                    start = row_numbers.get(sheet, 0) + 1
                    row_numbers[sheet] = start + repeats - 1
                    for number in range(start, start + repeats):
                        yield SourceRow(f"{sheet}!{number}", number, dict(cells), sheet)
                    element.clear()
                    continue
                if event == "end" and local == "table":
                    if table_stack:
                        table_stack.pop()
                    element.clear()
    except SourceError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise _error("ODS çalışma kitabı okunamadı.") from exc


def _delimited_rows(path: os.PathLike[str] | str, options: dict[str, Any] | None) -> tuple[Iterator[SourceRow], dict[str, Any]]:
    text, encoding, encoding_candidates = _read_text(path, options)
    delimiter_name, delimiter, delimiter_candidates = _normal_delimiter((options or {}).get("delimiter"), Path(path).suffix.lower(), text)

    def iterator() -> Iterator[SourceRow]:
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            total = 0
            for logical, fields in enumerate(reader, 1):
                total += 1
                if total > MAX_SOURCE_ROWS:
                    raise _error("Metin kaynağı fiziksel satır sınırını aşıyor.")
                if len(fields) > MAX_COLUMNS:
                    raise _error("Metin kaynağı sütun sınırını aşıyor.")
                if any(len(item) > MAX_FIELD_CHARS for item in fields):
                    raise _error("Metin kaynağında çok uzun alan var.")
                # reader.line_num, tırnak içi satır sonlarında fiziksel bitiş satırını verir.
                physical = reader.line_num or logical
                cells = {index: Cell(item, item, "text") for index, item in enumerate(fields) if item != ""}
                yield SourceRow(f"satır {physical}", physical, cells, "Tablo")
        except csv.Error as exc:
            raise _error("Metin tablosunun tırnaklama/ayraç yapısı güvenle ayrıştırılamadı.") from exc

    return iterator(), {"encoding": encoding, "encoding_candidates": encoding_candidates,
                        "delimiter": delimiter_name, "delimiter_candidates": delimiter_candidates}


def _id_rows(path: os.PathLike[str] | str, options: dict[str, Any] | None) -> tuple[Iterator[SourceRow], dict[str, Any]]:
    text, encoding, encoding_candidates = _read_text(path, options)

    def iterator() -> Iterator[SourceRow]:
        # splitlines, virgül/noktalı virgül/tab dahil satır içi karakterleri asla bölmez.
        for number, line in enumerate(text.splitlines(), 1):
            if number > MAX_SOURCE_ROWS:
                raise _error("TXT ID kaynağı fiziksel satır sınırını aşıyor.")
            value = line.strip()
            if len(value) > MAX_FIELD_CHARS:
                raise _error("TXT ID kaynağında çok uzun alan var.")
            cells = {0: Cell(value, value, "text")} if value else {}
            yield SourceRow(f"satır {number}", number, cells, "ID listesi")

    return iterator(), {"encoding": encoding, "encoding_candidates": encoding_candidates,
                        "delimiter": "none", "delimiter_candidates": ["none"]}


def iter_source_rows(path: os.PathLike[str] | str, options: dict[str, Any] | None = None) -> Iterator[SourceRow]:
    """Aynı doğrulanmış seçeneklerle ortak SourceRow sözleşmesini üretir."""
    fmt = _source_format(path, options)
    if fmt == "xlsx":
        yield from _xlsx_rows(path)
    elif fmt == "ods":
        yield from _ods_rows(path)
    elif fmt == "id_list":
        rows, _ = _id_rows(path, options)
        yield from rows
    else:
        rows, _ = _delimited_rows(path, options)
        yield from rows


def _header_row(options: dict[str, Any] | None, fmt: str) -> int:
    if fmt == "id_list":
        return 0
    value = (options or {}).get("header_row", 1)
    try:
        row = int(value)
    except (TypeError, ValueError) as exc:
        raise _error("Başlık satırı 0 veya 1–100 olmalıdır.") from exc
    if not 0 <= row <= 100:
        raise _error("Başlık satırı 0 veya 1–100 olmalıdır.")
    return row


def _layout(rows: Iterator[SourceRow], header_row: int) -> list[dict[str, Any]]:
    layouts: dict[str, dict[str, Any]] = {}
    for source_row in rows:
        sheet = source_row.sheet or "Tablo"
        item = layouts.setdefault(sheet, {"name": sheet, "header_cells": None, "sample": [], "indices": set(), "max_index": -1})
        if header_row and source_row.row == header_row and item["header_cells"] is None:
            item["header_cells"] = source_row.cells
            item["indices"] = {index for index, cell in source_row.cells.items() if cell.text()}
            continue
        if source_row.row <= header_row:
            continue
        item["max_index"] = max(item["max_index"], *(source_row.cells.keys() or [-1]))
        if item["header_cells"] is not None:
            indexes = sorted(item["indices"])
        else:
            indexes = list(range(min(item["max_index"] + 1, MAX_COLUMNS)))
        values = [source_row.cells.get(index, Cell()).text() for index in indexes]
        if any(cell.has_data() for cell in source_row.cells.values()) and len(item["sample"]) < 5:
            item["sample"].append(values)
    result: list[dict[str, Any]] = []
    for item in layouts.values():
        if header_row:
            cells = item["header_cells"]
            if cells is None:
                headers: list[dict[str, str]] = []
            else:
                headers = [{"column": _column_letter(index), "label": cells[index].text()}
                           for index in sorted(item["indices"])]
        else:
            headers = [{"column": _column_letter(index), "label": f"Sütun {_column_letter(index)}"}
                       for index in range(min(item["max_index"] + 1, MAX_COLUMNS))]
        result.append({"name": item["name"], "headers": headers, "sample": item["sample"]})
    if not result:
        raise _error("Kaynakta okunabilir sayfa veya satır yok.")
    return result


def field_catalog_metadata() -> dict[str, Any]:
    return {
        "allowed_fields": ["proje", "kategori", "personel", "uye_id", "ana_uye_id", "tip", "lead_id"],
        "suggestions": [
            {"field": "tarih", "supported": False, "reason": "Tarih eşleştirmesi bu sürümde kontrollü gün/interval kuralı olmadan desteklenmez."},
            {"field": "custom", "supported": False, "reason": "Serbest dosya başlığı SQL alanı değildir; özel alan eşleştirmesi kapsam dışıdır."},
        ],
    }


def validate_source(path: os.PathLike[str] | str, options: dict[str, Any] | None = None) -> bool:
    """Desteklenen kaynağı imza/yapı/limit bakımından doğrular."""
    fmt = _source_format(path, options)
    if fmt == "xlsx":
        return validate_xlsx(path)
    if fmt == "ods":
        return validate_ods(path)
    _read_text(path, options)
    if fmt == "delimited":
        # Kodlama ve ayraç kararının yanı sıra CSV yapısını da tüketerek doğrula.
        iterator, _ = _delimited_rows(path, options)
        for _ in iterator:
            pass
    elif fmt == "id_list":
        iterator, _ = _id_rows(path, options)
        for _ in iterator:
            pass
    return True


def inspect_source(path: os.PathLike[str] | str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sayfa/başlık/5 satır önizleme ve güvenli ayrıştırma meta verisini döndürür."""
    options = dict(options or {})
    fmt = _source_format(path, options)
    validate_source(path, options)
    header_row = _header_row(options, fmt)
    metadata: dict[str, Any] = {"format": fmt, "header_row": header_row,
                                "warnings": [], "limits": {"upload_bytes": MAX_UPLOAD_BYTES,
                                "decompressed_bytes": MAX_DECOMPRESSED_BYTES,
                                "relevant_rows": MAX_RELEVANT_ROWS, "source_rows": MAX_SOURCE_ROWS,
                                "columns": MAX_COLUMNS}, "field_catalog": field_catalog_metadata()}
    if fmt == "delimited":
        _, text_meta = _delimited_rows(path, options)
        metadata.update(text_meta)
    elif fmt == "id_list":
        _, text_meta = _id_rows(path, options)
        metadata.update(text_meta)
        metadata["text_mode"] = "ids"
        metadata["warnings"].append("TXT ID modunda her boş olmayan fiziksel satır tek ID'dir; satır içi ayraçlar bölünmez.")
    else:
        metadata.update({"encoding": None, "delimiter": None, "sheet_required": True})
    metadata["sheets"] = _layout(iter_source_rows(path, options), header_row)
    return metadata
