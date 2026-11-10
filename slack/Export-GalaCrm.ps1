<#
.SYNOPSIS
    Gala CRM Botu kanalını Excel'e aktarır (Export-GalaCrm). Python motorunu gömülü taşır.

.DESCRIPTION
    Bu dosya tek başına yeterlidir:
      1. İçindeki Python kodunu geçici klasöre yazar,
      2. Bilgisayardaki Python'u bulur (python / py), openpyxl yoksa kurar,
      3. Çalıştırır. Excel OUT_DIR klasörüne düşer.
    Token, kanal ID ve klasör aşağıdaki "BURAYI DOLDUR" bloğundadır.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Export-GalaCrm.ps1
    powershell -ExecutionPolicy Bypass -File .\Export-GalaCrm.ps1 --start 2026-11-01 --end 2026-11-09
#>
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

# =========================== PYTHON KAYNAĞI (dokunma) ===========================
$PythonSource = @'
# PYTHON-BEGIN
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export-GalaCrm.py
=================
Bir Slack kanalındaki TÜM mesajları ve thread yanıtlarını Excel'e aktarır.
Gala CRM Botu bildirimlerini Kategori / Renk / Açıklama / Üye ID / BTag olarak ayrı sütunlara böler.

Bot mesajı formatı:
    🔵 İLK YATIRIM SONRASI ÇEKİM – 50.000 TL VE ALTI
    İlk yatırımını yaptı, para çekti. Son çekiminin üzerinden en az 48 saat geçti.
    Üye ID: 751-505830309
    BTag: 2656818

Excel sayfaları:
    Bildirimler     her bildirim bir satır; yanındaki sütunlarda thread'e kimin ne zaman ne yazdığı (yanıtsızlar kırmızı)
    Kategori Özeti  kategori bazında bildirim / yanıtlanan / yanıtsız / oran
    BTag Özeti      BTag bazında sayılar
    Günlük          gün bazında sayılar
    Yanıtlayanlar   kim kaç yanıt yazmış
    Diğer Mesajlar  bot formatında olmayan mesajlar
    Bilgi           kanal, aralık, toplamlar

Slack app yetkileri (Bot Token Scopes): channels:history (açık kanal) / groups:history (özel kanal), users:read
Bot kanala ekli olmalı:  /invite @BotAdı

Kurulum / çalıştırma:
    pip install openpyxl
    python Export-GalaCrm.py
    python Export-GalaCrm.py --start 2026-11-01 --end 2026-11-09
"""

# ================== BURAYI DOLDUR ==================
TOKEN    = "xoxb-BURAYA-TOKEN"                      # Bot User OAuth Token
CHANNEL  = "C0000000000"                            # Kanal ID
OUT_DIR  = r"C:\Users\IT\Desktop\kalityepanel"      # Excel'in yazılacağı klasör (yoksa oluşturulur)
BOT_NAME = ""                                       # Boş = kanaldaki HER mesaj. "Gala CRM Botu" yazarsan sadece o app'inkiler
# ===================================================

import argparse
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    sys.exit("openpyxl bulunamadı. Önce çalıştır:  pip install openpyxl")

API_BASE = "https://slack.com/api/"
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

ERROR_HELP = {
    "invalid_auth": "Token geçersiz ya da başka workspace'e ait.",
    "not_authed": "Token gönderilmedi.",
    "token_revoked": "Token iptal edilmiş; Slack App > OAuth & Permissions > Reinstall.",
    "account_inactive": "Bot devre dışı.",
    "missing_scope": "Eksik scope. Bot Token Scopes'a channels:history, groups:history, users:read ekle ve Reinstall yap.",
    "not_in_channel": "Bot kanala ekli değil. Kanalda  /invite @BotAdı  yaz.",
    "channel_not_found": "Kanal bulunamadı. ID yanlış ya da bot bu kanalı göremiyor (özel kanalsa bota ekle).",
    "ratelimited": "Rate limit; script bekleyip devam eder.",
    "invalid_ts_latest": "--end tarihi geçersiz.",
    "invalid_ts_oldest": "--start tarihi geçersiz.",
}
SYSTEM_SUBTYPES = {"channel_join", "channel_leave", "channel_purpose", "channel_topic", "channel_name",
                   "channel_archive", "channel_unarchive", "group_join", "group_leave", "bot_add", "bot_remove",
                   "pinned_item", "unpinned_item"}
EMOJI_COLOR = {
    "large_blue_circle": "Mavi", "large_orange_circle": "Turuncu", "red_circle": "Kırmızı",
    "large_green_circle": "Yeşil", "large_yellow_circle": "Sarı", "large_purple_circle": "Mor",
    "white_circle": "Beyaz", "black_circle": "Siyah", "large_brown_circle": "Kahverengi",
    "\U0001F535": "Mavi", "\U0001F7E0": "Turuncu", "\U0001F534": "Kırmızı", "\U0001F7E2": "Yeşil",
    "\U0001F7E1": "Sarı", "\U0001F7E3": "Mor", "\u26AA": "Beyaz", "\u26AB": "Siyah", "\U0001F7E4": "Kahverengi",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------- Slack
class SlackError(Exception):
    def __init__(self, method, code):
        self.method, self.code = method, code
        hint = ERROR_HELP.get(code, "")
        super().__init__(f"{method} -> {code}" + (f"  ({hint})" if hint else ""))


class Slack:
    def __init__(self, token, page_size=200):
        self.token, self.page_size, self.calls = token, page_size, 0

    def call(self, method, **params):
        params = {k: v for k, v in params.items() if v is not None}
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(API_BASE + method, data=data, headers={
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8"})
        attempt = 0
        while True:
            attempt += 1
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = int(e.headers.get("Retry-After", "30") or 30)
                    log(f"  rate limit ({method}); {wait} sn bekleniyor...")
                    time.sleep(wait + 1)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt >= 5:
                    raise
                log(f"  ağ hatası ({e}); {2 ** attempt} sn sonra tekrar...")
                time.sleep(2 ** attempt)
                continue
            if body.get("ok"):
                return body
            code = body.get("error", "unknown_error")
            if code == "ratelimited":
                log(f"  rate limit ({method}); 30 sn bekleniyor...")
                time.sleep(30)
                continue
            raise SlackError(method, code)

    def pages(self, method, key, **params):
        items, cursor = [], None
        while True:
            body = self.call(method, cursor=cursor, **params)
            items.extend(body.get(key, []) or [])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                return items

    def messages(self, method, **params):
        items, cursor = [], None
        while True:
            try:
                body = self.call(method, cursor=cursor, limit=self.page_size, **params)
            except SlackError as e:
                if self.page_size > 15 and e.code in ("invalid_arguments", "invalid_limit"):
                    log(f"  {method}: limit={self.page_size} kabul edilmedi, 15'e düşürülüyor.")
                    self.page_size = 15
                    continue
                raise
            items.extend(body.get("messages", []) or [])
            cursor = (body.get("response_metadata") or {}).get("next_cursor") or None
            if not cursor:
                return items


# ----------------------------------------------------------------------------- yardımcılar
def get_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Istanbul")
    except Exception:
        return timezone(timedelta(hours=3), "TRT")


def ts_to_dt(ts, tz):
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(tz).replace(microsecond=0)


def parse_date(s, tz, end=False):
    if not s:
        return None
    d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=tz)
    if end:
        d += timedelta(days=1)
    return f"{d.timestamp():.6f}"


MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL_RE = re.compile(r"<#[CG][A-Z0-9]+(?:\|([^>]*))?>")
SPECIAL_RE = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")
LINK_RE = re.compile(r"<((?:https?|mailto):[^>|]+)(?:\|([^>]*))?>")
BOLD_LINE_RE = re.compile(r"(?m)^\*(.+?)\*\s*$")


def render_text(text, users):
    if not text:
        return ""
    text = MENTION_RE.sub(lambda m: "@" + users.get(m.group(1), {}).get("name", m.group(1)), text)
    text = CHANNEL_RE.sub(lambda m: "#" + (m.group(1) or "kanal"), text)
    text = SPECIAL_RE.sub(lambda m: "@" + m.group(1), text)
    text = LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})" if m.group(2) and m.group(2) != m.group(1) else m.group(1), text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    text = BOLD_LINE_RE.sub(r"\1", text)
    return text.strip()


def message_text(msg, users):
    """blocks > text; attachments eklenir"""
    parts = []
    for b in msg.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in ("section", "header"):
            if (b.get("text") or {}).get("text"):
                parts.append(b["text"]["text"])
            for f in b.get("fields") or []:
                if f.get("text"):
                    parts.append(f["text"])
        elif t == "context":
            for e in b.get("elements") or []:
                if e.get("text"):
                    parts.append(e["text"])
        elif t == "rich_text":
            out = []
            for el in b.get("elements") or []:
                for x in el.get("elements") or []:
                    xt = x.get("type")
                    if xt == "text":
                        out.append(x.get("text", ""))
                    elif xt == "link":
                        out.append(x.get("text") or x.get("url", ""))
                    elif xt == "user":
                        out.append("@" + users.get(x.get("user_id"), {}).get("name", x.get("user_id", "")))
                    elif xt == "emoji":
                        out.append(f":{x.get('name')}:")
                    elif x.get("text"):
                        out.append(x["text"])
                out.append("\n")
            parts.append("".join(out))
    if not parts and msg.get("text"):
        parts.append(msg["text"])
    for a in msg.get("attachments") or []:
        for key in ("pretext", "title"):
            if a.get(key):
                parts.append(a[key])
        if a.get("text"):
            parts.append(a["text"])
        elif a.get("fallback"):
            parts.append(a["fallback"])
        for f in a.get("fields") or []:
            parts.append(f"{f.get('title', '')}: {f.get('value', '')}")
    return render_text("\n".join(parts), users)


UYE_RE = re.compile(r"(?i)Üye\s*ID\s*[:：]\s*([0-9][0-9\-]*)")
BTAG_RE = re.compile(r"(?i)B\s*Tag\s*[:：]\s*(\S+)")
EMOJI_CODE_RE = re.compile(r"^:([a-z0-9_+\-]+):\s*")
LEAD_SYMBOL_RE = re.compile(r"^[^\w]+", re.UNICODE)


def parse_gala(text):
    """Kategori / Renk / Açıklama / Üye ID / BTag; bildirim değilse None"""
    uye, btag = UYE_RE.search(text), BTAG_RE.search(text)
    if not uye and not btag:
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip() and not re.fullmatch(r"[-_—–=]{3,}", l.strip())]
    title, color = "", ""
    if lines:
        title = lines[0]
        m = EMOJI_CODE_RE.match(title)
        if m:
            emoji = m.group(1)
            title = title[m.end():]
        else:
            m = LEAD_SYMBOL_RE.match(title)
            emoji = m.group(0).strip() if m else ""
            if m:
                title = title[m.end():]
        title = title.strip(" *_")
        if emoji:
            key = emoji.replace("\ufe0f", "").replace("\u200d", "")
            color = EMOJI_COLOR.get(key, emoji)
    desc = [l for l in lines[1:] if not re.match(r"(?i)^Üye\s*ID\s*[:：]", l) and not re.match(r"(?i)^B\s*Tag\s*[:：]", l)]
    return {"kategori": title, "renk": color, "aciklama": " ".join(desc),
            "uye": uye.group(1) if uye else "", "btag": btag.group(1) if btag else ""}


def author(msg, users):
    uid = msg.get("user")
    if uid and uid in users:
        return users[uid]["name"]
    if uid:
        return uid
    for key in ("username",):
        if msg.get(key):
            return f"{msg[key]} (bot)"
    if (msg.get("bot_profile") or {}).get("name"):
        return f"{msg['bot_profile']['name']} (bot)"
    if msg.get("bot_id"):
        return f"{msg['bot_id']} (bot)"
    return ""


def from_bot(msg, users, bot_name):
    if not bot_name:
        return True
    names = []
    if msg.get("username"):
        names.append(msg["username"])
    if (msg.get("bot_profile") or {}).get("name"):
        names.append(msg["bot_profile"]["name"])
    u = users.get(msg.get("user") or "")
    if u:
        names += [u["name"], u["handle"]]
    return any(n and n.strip().lower() == bot_name.strip().lower() for n in names)


def human_minutes(m):
    if m is None:
        return ""
    m = int(round(m))
    d, rem = divmod(m, 1440)
    h, mi = divmod(rem, 60)
    return " ".join(([f"{d} gün"] if d else []) + ([f"{h} sa"] if h else []) + [f"{mi} dk"])


# ----------------------------------------------------------------------------- Excel
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF")
RED_FILL = PatternFill("solid", fgColor="FDE2E2")
TOTAL_FILL = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="D9D9D9")
BORDER = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)


def header(ws, titles, widths):
    ws.append(titles)
    for i, w in enumerate(widths, 1):
        c = ws.cell(row=1, column=i)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"


def finish(ws, wrap_cols=(), fmt=None):
    fmt = fmt or {}
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.border = BORDER
            c.alignment = Alignment(vertical="top", wrap_text=c.column in wrap_cols)
            if c.column in fmt:
                c.number_format = fmt[c.column]
    ws.auto_filter.ref = ws.dimensions


def pct(a, b):
    return (a / b) if b else 0


def write_excel(path, rows, others, info, tz):
    wb = Workbook()
    ws = wb.active
    ws.title = "Bildirimler"
    cols = ["Sıra", "Tarih", "Gün", "Saat", "Kategori", "Renk", "Açıklama", "Üye ID", "BTag",
            "Yanıt Durumu", "Yanıtlayan", "Yanıt Tarihi", "Yanıt Saati", "Yanıt Süresi", "Yanıt Süresi (dk)",
            "Yanıt", "Yanıt Sayısı", "Diğer Yanıtlar", "Gönderen", "Slack Linki"]
    header(ws, cols, [6, 12, 11, 9, 42, 9, 60, 16, 12, 12, 20, 12, 9, 14, 9, 60, 7, 45, 18, 8])
    for i, r in enumerate(rows, 1):
        ws.append([i, r["dt"].replace(tzinfo=None), TR_DAYS[r["dt"].weekday()], r["dt"].strftime("%H:%M:%S"),
                   r["kategori"], r["renk"], r["aciklama"], r["uye"], r["btag"],
                   "Yanıtlandı" if r["answered"] else "YANITSIZ", r["responders"],
                   r["first_dt"].replace(tzinfo=None) if r["first_dt"] else None,
                   r["first_dt"].strftime("%H:%M:%S") if r["first_dt"] else "",
                   human_minutes(r["mins"]), r["mins"], r["reply"], r["reply_count"], r["extra"], r["author"], "Aç"])
        rr = ws.max_row
        link = ws.cell(row=rr, column=20)
        link.hyperlink, link.font = r["link"], Font(color="0563C1", underline="single")
        if not r["answered"]:
            for c in range(1, len(cols) + 1):
                ws.cell(row=rr, column=c).fill = RED_FILL
            ws.cell(row=rr, column=10).font = Font(bold=True, color="C00000")
    finish(ws, wrap_cols=(5, 7, 16, 18), fmt={2: "dd.mm.yyyy", 12: "dd.mm.yyyy"})

    def summary(name, key_fn, key_title, extra=None):
        ws2 = wb.create_sheet(name)
        titles = [key_title, "Bildirim", "Yanıtlanan", "Yanıtsız", "Yanıt Oranı", "Ort. Yanıt (dk)", "Medyan (dk)", "Farklı Üye"]
        widths = [40, 10, 10, 9, 10, 11, 10, 10]
        if extra:
            titles.append(extra[0])
            widths.append(extra[1])
        header(ws2, titles, widths)
        groups = defaultdict(list)
        for r in rows:
            groups[key_fn(r)].append(r)
        order = sorted(groups, key=lambda k: (-len(groups[k]), str(k))) if name != "Günlük" else sorted(groups)
        tot = {"n": 0, "a": 0, "mins": []}
        for k in order:
            g = groups[k]
            ans = [r for r in g if r["answered"]]
            mins = [r["mins"] for r in ans if r["mins"] is not None]
            row = [k, len(g), len(ans), len(g) - len(ans), pct(len(ans), len(g)),
                   round(statistics.mean(mins), 1) if mins else None,
                   round(statistics.median(mins), 1) if mins else None,
                   len({r["uye"] for r in g})]
            if extra:
                row.append(extra[2](g))
            ws2.append(row)
            tot["n"] += len(g)
            tot["a"] += len(ans)
            tot["mins"] += mins
        ws2.append(["TOPLAM", tot["n"], tot["a"], tot["n"] - tot["a"], pct(tot["a"], tot["n"]),
                    round(statistics.mean(tot["mins"]), 1) if tot["mins"] else None,
                    round(statistics.median(tot["mins"]), 1) if tot["mins"] else None,
                    len({r["uye"] for r in rows})] + ([""] if extra else []))
        finish(ws2, wrap_cols=(9,), fmt={5: "0.0%", 1: "dd.mm.yyyy" if name == "Günlük" else "General"})
        for c in ws2[ws2.max_row]:
            c.fill, c.font = TOTAL_FILL, Font(bold=True)

    summary("Kategori Özeti", lambda r: r["kategori"] or "(kategori yok)", "Kategori")
    summary("BTag Özeti", lambda r: r["btag"] or "(yok)", "BTag",
            extra=("Kategoriler", 60, lambda g: " | ".join(sorted({r["kategori"] for r in g if r["kategori"]}))))
    summary("Günlük", lambda r: datetime(r["dt"].year, r["dt"].month, r["dt"].day), "Tarih")

    ws3 = wb.create_sheet("Yanıtlayanlar")
    header(ws3, ["Yanıtlayan", "Yanıt Sayısı", "Ort. Yanıt (dk)", "Medyan (dk)", "İlk Yanıt", "Son Yanıt"], [24, 10, 11, 10, 16, 16])
    per = defaultdict(list)
    for r in rows:
        for name in r["responder_list"]:
            per[name].append(r)
    for name in sorted(per, key=lambda k: -len(per[k])):
        g = per[name]
        mins = [r["mins"] for r in g if r["mins"] is not None]
        dts = [r["first_dt"] for r in g if r["first_dt"]]
        ws3.append([name, len(g), round(statistics.mean(mins), 1) if mins else None,
                    round(statistics.median(mins), 1) if mins else None,
                    min(dts).replace(tzinfo=None) if dts else None, max(dts).replace(tzinfo=None) if dts else None])
    finish(ws3, fmt={5: "dd.mm.yyyy HH:MM", 6: "dd.mm.yyyy HH:MM"})

    ws4 = wb.create_sheet("Diğer Mesajlar")
    header(ws4, ["Tarih", "Gün", "Saat", "Gönderen", "Mesaj", "Slack Linki"], [12, 11, 9, 22, 90, 8])
    for o in others:
        ws4.append([o["dt"].replace(tzinfo=None), TR_DAYS[o["dt"].weekday()], o["dt"].strftime("%H:%M:%S"),
                    o["author"], o["text"], "Aç"])
        link = ws4.cell(row=ws4.max_row, column=6)
        link.hyperlink, link.font = o["link"], Font(color="0563C1", underline="single")
    finish(ws4, wrap_cols=(5,), fmt={1: "dd.mm.yyyy"})

    ws5 = wb.create_sheet("Bilgi")
    ws5.column_dimensions["A"].width = 24
    ws5.column_dimensions["B"].width = 100
    for k, v in info:
        ws5.append([k, v])
        ws5.cell(row=ws5.max_row, column=1).font = Font(bold=True)
        ws5.cell(row=ws5.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Slack kanalını (Gala CRM bildirimleri ayrıştırılmış) Excel'e aktarır.")
    ap.add_argument("--token", default=os.environ.get("SLACK_BOT_TOKEN") or TOKEN)
    ap.add_argument("--channel", default=CHANNEL)
    ap.add_argument("--bot-name", default=BOT_NAME)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--output", help="Tam .xlsx yolu (verilirse --out-dir yok sayılır)")
    ap.add_argument("--start", help="YYYY-MM-DD (dahil)")
    ap.add_argument("--end", help="YYYY-MM-DD (dahil)")
    ap.add_argument("--include-system", action="store_true")
    ap.add_argument("--page-size", type=int, default=200)
    args = ap.parse_args()

    if not args.token or args.token.startswith("xoxb-BURAYA"):
        sys.exit("Token girilmemiş. Dosyanın başındaki TOKEN satırını doldur.")
    if not args.channel or args.channel == "C0000000000":
        sys.exit("Kanal ID girilmemiş. Dosyanın başındaki CHANNEL satırını doldur.")

    tz = get_tz()
    sl = Slack(args.token, args.page_size)
    channel = args.channel.strip().lstrip("#")

    log("Bağlanılıyor...")
    auth = sl.call("auth.test")
    team_url = (auth.get("url") or "https://slack.com/").rstrip("/")
    log(f"Workspace: {auth.get('team')}   bot: {auth.get('user')}")

    channel_name = channel
    try:
        channel_name = sl.call("conversations.info", channel=channel)["channel"].get("name", channel)
    except Exception as e:
        log(f"  (kanal adı alınamadı, ID kullanılacak: {e})")
    log(f"Kanal: #{channel_name} ({channel})")

    log("Kullanıcı listesi çekiliyor...")
    users = {}
    try:
        for u in sl.pages("users.list", "members", limit=200):
            p = u.get("profile") or {}
            name = p.get("display_name") or p.get("real_name") or u.get("real_name") or u.get("name") or u["id"]
            if u.get("deleted"):
                name += " (silinmiş hesap)"
            users[u["id"]] = {"name": name, "handle": u.get("name", "")}
        log(f"  {len(users)} kullanıcı.")
    except SlackError as e:
        log(f"  users.list okunamadı ({e.code}); isimler ID olarak yazılacak.")

    log("Kanal mesajları çekiliyor...")
    history = sl.messages("conversations.history", channel=channel, inclusive="true",
                          oldest=parse_date(args.start, tz), latest=parse_date(args.end, tz, end=True))
    log(f"  {len(history)} kayıt geldi.")

    seen, parents, filtered = set(), [], 0
    for m in history:
        ts = m.get("ts")
        if not ts or ts in seen:
            continue
        seen.add(ts)
        if m.get("subtype") == "thread_broadcast" and m.get("thread_ts") and m["thread_ts"] != ts:
            continue
        if not args.include_system and m.get("subtype") in SYSTEM_SUBTYPES:
            continue
        if not from_bot(m, users, args.bot_name):
            filtered += 1
            continue
        parents.append(m)
    parents.sort(key=lambda m: float(m["ts"]))
    if args.bot_name:
        log(f"  '{args.bot_name}' filtresi: {len(parents)} mesaj alındı, {filtered} başkasına ait (atlandı).")

    threads = {}
    with_thread = [m for m in parents if m.get("reply_count")]
    log(f"  {len(parents)} ana mesaj, {len(with_thread)} tanesinde thread var. Yanıtlar çekiliyor...")
    for i, m in enumerate(with_thread, 1):
        try:
            reps = sl.messages("conversations.replies", channel=channel, ts=m["ts"])
        except SlackError as e:
            if e.code == "thread_not_found":
                continue
            raise
        threads[m["ts"]] = sorted([r for r in reps if r.get("ts") != m["ts"]], key=lambda r: float(r["ts"]))
        if i % 10 == 0 or i == len(with_thread):
            log(f"  thread {i} / {len(with_thread)}")

    # users.list'te olmayan (dış) kullanıcılar
    all_msgs = parents + [r for v in threads.values() for r in v]
    for uid in {m.get("user") for m in all_msgs if m.get("user")} - set(users):
        try:
            u = sl.call("users.info", user=uid)["user"]
            p = u.get("profile") or {}
            users[uid] = {"name": p.get("display_name") or p.get("real_name") or u.get("name") or uid, "handle": u.get("name", "")}
        except Exception:
            users[uid] = {"name": uid, "handle": ""}

    rows, others = [], []
    for p in parents:
        dt = ts_to_dt(p["ts"], tz)
        text = message_text(p, users)
        link = f"{team_url}/archives/{channel}/p{p['ts'].replace('.', '')}"
        g = parse_gala(text)
        if g is None:
            others.append({"dt": dt, "author": author(p, users), "text": text, "link": link})
            continue
        reps = threads.get(p["ts"], [])
        first = reps[0] if reps else None
        responders = []
        for r in reps:
            a = author(r, users)
            if a not in responders:
                responders.append(a)
        extra = ""
        if len(reps) > 1:
            extra = "\n".join(f"[{ts_to_dt(r['ts'], tz).strftime('%d.%m %H:%M')}] {author(r, users)}: {message_text(r, users)}"
                              for r in reps[1:])
        rows.append({
            **g, "dt": dt, "link": link, "author": author(p, users),
            "answered": bool(reps),
            "responders": ", ".join(responders), "responder_list": responders,
            "first_dt": ts_to_dt(first["ts"], tz) if first else None,
            "mins": round((float(first["ts"]) - float(p["ts"])) / 60, 1) if first else None,
            "reply": message_text(first, users) if first else "",
            "reply_count": len(reps), "extra": extra,
        })
    log(f"  {len(rows)} bildirim, {len(others)} diğer mesaj.")
    if not rows:
        log("UYARI: Hiç bildirim bulunamadı. 'Üye ID:' / 'BTag:' alanı aranıyor; 'Diğer Mesajlar' sayfasına bak.")

    answered = sum(1 for r in rows if r["answered"])
    info = [
        ("Workspace", auth.get("team", "")),
        ("Kanal", f"#{channel_name} ({channel})"),
        ("Gönderen filtresi", f"{args.bot_name} ({filtered} başka mesaj atlandı)" if args.bot_name else "yok"),
        ("Çekim zamanı", datetime.now(tz).strftime("%d.%m.%Y %H:%M")),
        ("Saat dilimi", "Europe/Istanbul"),
        ("İstenen aralık", f"{args.start or 'başlangıç'} -> {args.end or 'bugün'}"),
        ("Bildirim sayısı", len(rows)),
        ("Yanıtlanan", answered),
        ("Yanıtsız", len(rows) - answered),
        ("Farklı üye", len({r["uye"] for r in rows})),
        ("Farklı BTag", len({r["btag"] for r in rows})),
        ("Diğer mesaj", len(others)),
        ("API çağrısı", sl.calls),
        ("Not", "Bildirimler sayfasında kırmızı satır = thread yanıtı yok. Yanıt Süresi = bildirim ile ilk yanıt arasındaki süre."),
    ]

    out = args.output
    if not out:
        out_dir = args.out_dir or os.path.join(os.path.expanduser("~"), "Desktop")
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        tag = f"{args.start or 'bas'}_{args.end or 'bugun'}" if (args.start or args.end) else datetime.now(tz).strftime("%Y%m%d_%H%M")
        safe_name = re.sub(r"[^\w\-]", "_", channel_name)
        out = os.path.join(out_dir, f"gala_{safe_name}_{tag}.xlsx")

    log("Excel yazılıyor...")
    write_excel(out, rows, others, info, tz)
    log(f"Bitti: {len(rows)} bildirim ({answered} yanıtlı, {len(rows) - answered} yanıtsız), {len(others)} diğer mesaj.")
    log(f"Excel dosyası: {os.path.abspath(out)}")


if __name__ == "__main__":
    try:
        main()
    except SlackError as e:
        sys.exit(f"HATA: {e}")
    except KeyboardInterrupt:
        sys.exit("\nİptal edildi.")
# PYTHON-END
'@
# ================================================================================

# Python kodunu dosyadan UTF-8 olarak oku (Not Defteri BOM'suz kaydetse bile Türkçe karakterler bozulmasın)
$code = $PythonSource
try {
    $raw = [IO.File]::ReadAllText($MyInvocation.MyCommand.Path, [Text.Encoding]::UTF8)
    $mb = '# PYTHON-' + 'BEGIN'
    $me = '# PYTHON-' + 'END'
    $b = $raw.IndexOf($mb)
    $e = $raw.IndexOf($me)
    if ($b -ge 0 -and $e -gt $b) { $code = $raw.Substring($b, $e - $b) }
} catch { }

$pyFile = Join-Path $env:TEMP 'Export-GalaCrm.py'
[IO.File]::WriteAllText($pyFile, $code, (New-Object Text.UTF8Encoding($false)))

# Python'u bul
$exe = $null
foreach ($cand in @('python', 'py')) {
    try {
        & $cand --version 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { $exe = $cand; break }
    } catch { }
}
if (-not $exe) {
    Write-Host 'Python bulunamadı. https://www.python.org/downloads/ adresinden kur; kurulumda "Add python.exe to PATH" kutusunu işaretle.' -ForegroundColor Red
    exit 1
}
Write-Host "Python: $exe" -ForegroundColor DarkGray

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'

# openpyxl yoksa kur
& $exe -c "import openpyxl" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'openpyxl kuruluyor (tek seferlik)...' -ForegroundColor Cyan
    & $exe -m pip install openpyxl
    if ($LASTEXITCODE -ne 0) { & $exe -m pip install --user openpyxl }
}

# Çalıştır (ek parametreler aynen Python'a gider, örn: --start 2026-11-01 --end 2026-11-09)
& $exe $pyFile @args
exit $LASTEXITCODE
