"""Telegram ekleyen profili için yalnızca-okunur, proje kapsamlı kanıt sorguları.

Bu modül Flask bağlamına bağlı değildir: endpoint, kendi yetki denetiminden sonra
``get_profile`` çağırır.  ``allowed_projects`` her sorguda kullanılır; süper
admin bayrağı yalnızca sıfır kayıtlı bir Telegram kullanıcısının meta verisinin
okunmasına izin verir, proje kapsamını genişletmez.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

_PAGE_SIZE = 50
_STRICT_TG_ID = re.compile(r"[0-9]+\Z")
_CONFIDENT_SOURCES = ("kesin", "telegram")
_VALID_STATES = {"hepsi", "onayli", "bekleyen", "silinen"}


def _tg_id(value: Any) -> str:
    """Yalnızca ondalık Telegram kimliklerini kabul eder; boşluk düzeltmez."""
    identifier = str(value)
    if not _STRICT_TG_ID.fullmatch(identifier):
        raise ValueError("Geçersiz Telegram kullanıcı kimliği.")
    return identifier


def _allowed_projects(projects: Sequence[Any] | None) -> list[str]:
    """Sorguda kullanılacak izinli proje adlarını sabit sırayla tekilleştirir."""
    result: list[str] = []
    for project in projects or ():
        if not isinstance(project, str) or not project or project in result:
            continue
        result.append(project)
    return result


def _filter_value(filters: Mapping[str, Any] | None, *names: str, default: Any = "") -> Any:
    if not filters:
        return default
    for name in names:
        try:
            value = filters.get(name, None)
        except AttributeError:
            return default
        if value is not None:
            if isinstance(value, (list, tuple)):
                return value[0] if value else default
            return value
    return default


def _normalise_filters(
    filters: Mapping[str, Any] | None,
    allowed: list[str],
    expected_project: str | None,
) -> dict[str, Any]:
    """İstemci girdisini güvenli filtre durumuna dönüştürür.

    Açık kapsam dışı istek başka projedeki sonuçlara sessizce dönmez.
    Proje hiç seçilmemişse yalnız izinli kapsamın tamamı kullanılır.
    """
    project = _filter_value(filters, "project", "proje")
    if project and (not isinstance(project, str) or project not in allowed):
        raise PermissionError("Proje kapsamı dışında.")
    project = project or ""

    category = _filter_value(filters, "kategori")
    category = category.strip()[:100] if isinstance(category, str) else ""

    state = _filter_value(filters, "kt", "durum", default="hepsi")
    state = state if state in _VALID_STATES else "hepsi"

    outside = "1" if _filter_value(filters, "outside", default="0") == "1" and expected_project else "0"
    if project and project == expected_project and outside == "1":
        outside = "0"

    raw_page = _filter_value(filters, "page", "s", default="1")
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        raise ValueError("Geçersiz sayfa.") from None
    if page < 1:
        raise ValueError("Geçersiz sayfa.")

    # 2.3.1: tarih aralığı (Kayıtlar gelişmiş filtresiyle aynı biçim); ters aralık düzeltilir ve uyarıyla bildirilir.
    dates: dict[str, str] = {}
    for name in ("tarih1", "tarih2"):
        value = _filter_value(filters, name)
        value = value.strip()[:10] if isinstance(value, str) else ""
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                raise ValueError("Tarih biçimi geçersiz; takvimden seçin (YYYY-AA-GG).") from None
        dates[name] = value
    warning = ""
    if dates["tarih1"] and dates["tarih2"] and dates["tarih1"] > dates["tarih2"]:
        dates["tarih1"], dates["tarih2"] = dates["tarih2"], dates["tarih1"]
        warning = "Başlangıç tarihi bitişten sonraydı; tarihler yer değiştirildi (%s → %s)." % (dates["tarih1"], dates["tarih2"])

    return {"project": project, "kategori": category, "kt": state, "outside": outside, "page": page,
            "tarih1": dates["tarih1"], "tarih2": dates["tarih2"], "uyari": warning}


def _date_where(current: Mapping[str, Any]) -> tuple[list[str], list[Any]]:
    """Kayıt tarihi (``tarih``) aralığı; Kayıtlar sayfasıyla aynı sınırlar (gün başı / gün sonu)."""
    parts: list[str] = []
    params: list[Any] = []
    if current.get("tarih1"):
        parts.append("tarih >= ?"); params.append(current["tarih1"] + " 00:00:00")
    if current.get("tarih2"):
        parts.append("tarih <= ?"); params.append(current["tarih2"] + " 23:59:59")
    return parts, params


TIP_SUTUNLARI = (("sessiz", "Sessiz"), ("telesekreter", "Telesekreter"), ("diger", "Diğer / boş"))


def _tip_kodu(value: Any) -> str:
    text = str(value or "").strip().casefold()
    if text.startswith("sessiz"):
        return "sessiz"
    if text.startswith("tele"):
        return "telesekreter"
    return "diger"


def _bos_sayac() -> dict[str, int]:
    return {"sessiz": 0, "telesekreter": 0, "diger": 0, "toplam": 0}


def _capraz_tablo(conn: Any, where: str, params: list[Any]) -> dict[str, Any]:
    """Kategori × tip çapraz tablosu: satır kategori, sütun tip, satır/sütun toplamları; proje birden fazlaysa proje alt toplamları."""
    rows = conn.execute(
        f"""SELECT COALESCE(NULLIF(TRIM(kategori), ''), '') AS kategori, COALESCE(tip, '') AS tip, proje, COUNT(*) AS adet
              FROM kayitlar WHERE {where} GROUP BY 1, 2, 3""",
        tuple(params),
    ).fetchall()
    categories: dict[str, dict[str, int]] = {}
    projects: dict[str, dict[str, int]] = {}
    total = _bos_sayac()
    for row in rows:
        code = _tip_kodu(row["tip"]); count = int(row["adet"] or 0)
        for bucket in (categories.setdefault(row["kategori"], _bos_sayac()), projects.setdefault(row["proje"], _bos_sayac()), total):
            bucket[code] += count; bucket["toplam"] += count
    satirlar = [dict(kategori=name or "— (kategori yok)", **values) for name, values in categories.items()]
    satirlar.sort(key=lambda item: (-item["toplam"], item["kategori"].casefold()))
    proje_satirlari = [dict(proje=name, **values) for name, values in sorted(projects.items(), key=lambda item: (-item[1]["toplam"], item[0]))]
    return {"satirlar": satirlar, "toplam": total, "projeler": proje_satirlari if len(proje_satirlari) > 1 else [],
            "sutunlar": [dict(kod=code, etiket=label) for code, label in TIP_SUTUNLARI]}


def _scope_where(identifier: str, allowed: list[str], onayli_zorunlu: list[str] | None = None) -> tuple[str, list[Any]]:
    """Tüm profile sorgularında zorunlu olan ekleyen + proje kapsamı.

    2.3.1 ``onayli_zorunlu``: bu projelerde yalnız onaylı, silinmemiş kayıtlar kapsama girer (ONAYSIZ_GORUNUM=gizle,
    kullanıcının kt yetkisi olmayan projeler)."""
    if not allowed:
        return "1=0", []
    where = "ekleyen_id=? AND proje IN ({})".format(",".join("?" for _ in allowed))
    params: list[Any] = [identifier, *allowed]
    gizli = [p for p in (onayli_zorunlu or ()) if p in allowed]
    if gizli:
        where += " AND (proje NOT IN ({}) OR (kt=1 AND silindi=0))".format(",".join("?" for _ in gizli))
        params.extend(gizli)
    return where, params


def _has_eligible_evidence(conn: Any, scope: str, scope_params: list[Any]) -> bool:
    return conn.execute(
        f"SELECT 1 FROM kayitlar WHERE {scope} LIMIT 1", tuple(scope_params)
    ).fetchone() is not None


def _user_metadata(conn: Any, identifier: str) -> dict[str, str | None]:
    """Ana proje sütunu henüz eklenmemiş eski veritabanlarıyla da okunur."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tg_kullanicilar)")}
    has_expected = "ana_proje" in columns
    select = "id, username, first_name" + (", ana_proje" if has_expected else "")
    row = conn.execute(f"SELECT {select} FROM tg_kullanicilar WHERE id=?", (identifier,)).fetchone()
    if not row:
        return {"id": identifier, "username": "", "first_name": "", "ana_proje": None}
    return {
        "id": str(row["id"]),
        "username": row["username"] or "",
        "first_name": row["first_name"] or "",
        "ana_proje": (row["ana_proje"] if has_expected else None),
    }


def _computed_expected(conn: Any, scope: str, scope_params: list[Any]) -> str | None:
    """Yalnız güvenilir Telegram atfından proje göstergesi hesaplar.

    Tahmini veya kimliği olmayan eski satırlar, sayfalansa bile bu karara etki
    etmez.  Eşitlikte proje adı ile kararlı bir sonuç seçilir.
    """
    row = conn.execute(
        f"""
        SELECT proje, COUNT(*) AS adet
          FROM kayitlar
         WHERE {scope}
           AND (ekleyen_guven IN (?, ?) OR kaynak=?)
         GROUP BY proje
         ORDER BY adet DESC, proje COLLATE UNICODE_NOCASE ASC
         LIMIT 1
        """,
        (*scope_params, *_CONFIDENT_SOURCES, "telegram"),
    ).fetchone()
    return row["proje"] if row else None


def _count_value(row: Any, key: str) -> int:
    return int(row[key] or 0)


def _safe_rows(conn: Any, where: str, params: list[Any], page: int) -> tuple[list[dict[str, Any]], int]:
    total = int(conn.execute(f"SELECT COUNT(*) FROM kayitlar WHERE {where}", tuple(params)).fetchone()[0])
    offset = (page - 1) * _PAGE_SIZE
    rows = conn.execute(
        f"""
        SELECT id, proje, kategori, tarih, personel, uye_id, kt, silindi,
               ekleyen_id, ekleyen_ad, ekleyen_guven, kaynak, surum
          FROM kayitlar
         WHERE {where}
         ORDER BY COALESCE(tarih, '') DESC, id DESC
         LIMIT ? OFFSET ?
        """,
        (*params, _PAGE_SIZE, offset),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for source_row in rows:
        row = dict(source_row)
        confidence = row.get("ekleyen_guven")
        # Eski/tahmini eşleşmeler görünür kalır; kesin kullanıcı göstergesi
        # hesaplanırken sessizce kullanılmış gibi gösterilmez.
        row["estimated"] = confidence not in _CONFIDENT_SOURCES
        row["confidence_label"] = {
            "kesin": "Kesin eşleştirme",
            "telegram": "Telegram kaydı",
            "tahmini": "Tahmini geçmiş eşleştirme",
        }.get(confidence, "Geçmiş / belirsiz eşleştirme")
        result.append(row)
    return result, total


def get_profile(
    conn: Any,
    tg_id: Any,
    allowed_projects: Sequence[Any] | None,
    filters: Mapping[str, Any] | None,
    superadmin: bool = False,
    onayli_zorunlu: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Bir Telegram ekleyenin, yalnızca izinli projelerdeki kanıt profilini döndürür.

    Dönüş sözleşmesi endpoint için kasıtlı olarak yalnızca okuma verisi içerir.
    ``PermissionError`` alan çağrı, normal bir panel kullanıcısı için kapsamda
    hiç kayıt bulunmadığında 403 üretmelidir.  Bu denetim **kullanıcı meta
    verisi sorgulanmadan önce** yapıldığı için profil varlığı sızdırılmaz.
    """
    identifier = _tg_id(tg_id)
    allowed = _allowed_projects(allowed_projects)
    scope, scope_params = _scope_where(identifier, allowed, _allowed_projects(onayli_zorunlu))

    if not superadmin and not _has_eligible_evidence(conn, scope, scope_params):
        raise PermissionError("Bu kullanıcı için erişilebilir kanıt yok.")

    metadata = _user_metadata(conn, identifier)
    assigned = metadata.pop("ana_proje", None)
    # Atanmış fakat bu panel oturumunun kapsamı dışında kalan bir proje adı
    # asla dönüşe konmaz. Güvenilir, kapsam içi kanıt varsa onun göstergesi
    # kullanılabilir; yoksa gösterge belirsizdir.
    if assigned in allowed:
        expected_project: str | None = assigned
        expected_source = "atanan"
    else:
        expected_project = _computed_expected(conn, scope, scope_params)
        expected_source = "hesaplanan" if expected_project else "belirsiz"

    current_filters = _normalise_filters(filters, allowed, expected_project)
    # Tarih aralığı sayaçları, proje listesini, satırları ve çapraz tabloyu daraltır; beklenen proje ve erişim denetimi tüm geçmişe bakar.
    date_parts, date_params = _date_where(current_filters)
    ranged = " AND ".join([scope, *date_parts])
    ranged_params = [*scope_params, *date_params]

    count_row = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN kt=0 AND silindi=0 THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN kt=1 AND silindi=0 THEN 1 ELSE 0 END) AS approved,
               SUM(CASE WHEN silindi=1 THEN 1 ELSE 0 END) AS deleted,
               SUM(CASE WHEN COALESCE(ekleyen_guven, '') NOT IN (?, ?)
                        THEN 1 ELSE 0 END) AS estimated
          FROM kayitlar
         WHERE {ranged}
        """,
        (*_CONFIDENT_SOURCES, *ranged_params),
    ).fetchone()
    counts = {
        "total": _count_value(count_row, "total"),
        "outside": 0,
        "pending": _count_value(count_row, "pending"),
        "approved": _count_value(count_row, "approved"),
        "deleted": _count_value(count_row, "deleted"),
        "estimated": _count_value(count_row, "estimated"),
    }
    if expected_project:
        outside_row = conn.execute(
            f"SELECT COUNT(*) FROM kayitlar WHERE {ranged} AND proje<>?",
            (*ranged_params, expected_project),
        ).fetchone()
        counts["outside"] = int(outside_row[0])

    projects = [
        {"proje": row["proje"], "adet": int(row["adet"])}
        for row in conn.execute(
            f"""SELECT proje, COUNT(*) AS adet
                  FROM kayitlar
                 WHERE {ranged}
                 GROUP BY proje
                 ORDER BY adet DESC, proje COLLATE UNICODE_NOCASE ASC""",
            tuple(ranged_params),
        ).fetchall()
    ]

    where_parts = [ranged]
    row_params: list[Any] = list(ranged_params)
    if current_filters["project"]:
        where_parts.append("proje=?")
        row_params.append(current_filters["project"])
    if current_filters["kategori"]:
        where_parts.append("kategori COLLATE UNICODE_NOCASE=?")
        row_params.append(current_filters["kategori"])
    if current_filters["outside"] == "1":
        where_parts.append("proje<>?")
        row_params.append(expected_project)
    state = current_filters["kt"]
    if state == "onayli":
        where_parts.append("kt=1 AND silindi=0")
    elif state == "bekleyen":
        where_parts.append("kt=0 AND silindi=0")
    elif state == "silinen":
        where_parts.append("silindi=1")

    rows, total_filtered = _safe_rows(conn, " AND ".join(where_parts), row_params, current_filters["page"])
    pages = max(1, (total_filtered + _PAGE_SIZE - 1) // _PAGE_SIZE)
    # Çapraz tablo bu görünümü (proje, kategori, durum sekmesi, tarih aralığı) izler; "Tümü" sekmesinde silinenler tabloya girmez.
    table_parts = list(where_parts) if state != "hepsi" else [*where_parts, "silindi=0"]
    capraz = _capraz_tablo(conn, " AND ".join(table_parts), row_params)
    capraz["silinen_haric"] = state == "hepsi"
    link_args = {key: value for key, value in (("project", current_filters["project"]), ("kategori", current_filters["kategori"]),
                                              ("kt", current_filters["kt"] if current_filters["kt"] != "hepsi" else ""),
                                              ("outside", "1" if current_filters["outside"] == "1" else ""),
                                              ("tarih1", current_filters["tarih1"]), ("tarih2", current_filters["tarih2"])) if value}
    return {
        "capraz": capraz,
        "link_args": link_args,
        "user": metadata,
        "expected_project": expected_project,
        "expected_source": expected_source,
        "counts": counts,
        "projects": projects,
        "rows": rows,
        "page": current_filters["page"],
        "pages": pages,
        "total_filtered": total_filtered,
        "filters": current_filters,
    }
