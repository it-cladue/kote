"""Slack'e bağlanmayan saf mantık: config okuma/doğrulama, metinde etiket arama, bildirim metinleri.

app.py bunları kullanır; test_bridge.py Slack olmadan test eder.
"""
import json
import os
import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,}$")
HANDLE_RE = re.compile(r"^[\w.-]+$")
TOKEN_RE = re.compile(r"<[^>]*>")
NOTIFY_MODES = ("dm", "thread", "channel")

DEFAULT_DM_TEMPLATE = (
    "<#{channel}> kanalında <@{author}> *@{keyword}* etiketini kullandı:\n"
    "{quote}\n"
    "<{link}|Mesaja git>"
)
DEFAULT_REPLY_TEMPLATE = "{mentions} {author} sizi etiketledi."
QUOTE_MAX = 400


def strip_slack_tokens(text):
    """Slack'in kendi token'larını (<@U..>, <!subteam^S..|@petra>, <#C..>, <http..>) metinden atar.

    Atılmazsa gerçek bir @petra mention'ının içindeki "@petra" da yakalanır ve ekip iki kez bildirim alır.
    """
    return TOKEN_RE.sub(" ", text or "")


def find_keywords(text, keywords, require_at=True):
    """Metinde geçen keyword'leri config'deki sırayla, tekrarsız döndürür.

    "@petra", "@Petra", "@petra'ya", "(@petra)" eşleşir; "@petrax", "ali@petra.com", "@petra-2" eşleşmez.
    """
    clean = strip_slack_tokens(text).lower()
    at = "@" if require_at else "@?"
    found = []
    for kw in keywords:
        pattern = r"(?<![\w@])" + at + re.escape(kw.lower()) + r"(?![\w-])"
        if re.search(pattern, clean):
            found.append(kw)
    return found


def parse_target(raw, keyword):
    """'petra' | '@petra' -> usergroup, 'ali@firma.com' -> email, 'U0123ABCD' -> user id."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f'config: "{keyword}" altında boş ya da string olmayan hedef var.')
    s = raw.strip()
    if EMAIL_RE.match(s):
        return {"type": "email", "email": s.lower()}
    if USER_ID_RE.match(s):
        return {"type": "user", "id": s}
    handle = s[1:] if s.startswith("@") else s
    if not HANDLE_RE.match(handle):
        raise ValueError(
            f'config: "{keyword}" altındaki "{raw}" ne e-posta, ne kullanıcı ID\'si, '
            f"ne de geçerli bir user group handle'ı."
        )
    return {"type": "usergroup", "handle": handle.lower()}


def normalize_config(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("keywords"), dict):
        raise ValueError('config: "keywords" nesnesi zorunlu. Örnek için config.example.json dosyasına bak.')
    keywords = {}
    for kw, value in raw["keywords"].items():
        if kw.startswith("_"):  # "_aciklama" gibi notlar
            continue
        key = kw.strip().lstrip("@").lower()
        if not key:
            raise ValueError("config: boş keyword.")
        targets = value if isinstance(value, list) else [value]
        if not targets:
            raise ValueError(f'config: "{kw}" için en az bir hedef gerekli.')
        keywords[key] = [parse_target(t, kw) for t in targets]
    if not keywords:
        raise ValueError("config: hiç keyword tanımlı değil.")

    mode = raw.get("notify_mode", "dm")
    if mode not in NOTIFY_MODES:
        raise ValueError(f'config: notify_mode {", ".join(NOTIFY_MODES)} olmalı, "{mode}" değil.')

    dm_template = raw.get("dm_template")
    if not isinstance(dm_template, str) or "{link}" not in dm_template:
        dm_template = DEFAULT_DM_TEMPLATE
    reply_template = raw.get("reply_template")
    if not isinstance(reply_template, str) or "{mentions}" not in reply_template:
        reply_template = DEFAULT_REPLY_TEMPLATE
    ack = raw.get("ack_reaction") or ""
    if not isinstance(ack, str):
        raise ValueError("config: ack_reaction emoji adı (string) olmalı, ör. \"bell\".")

    channels = raw.get("channels") or []
    admins_raw = raw.get("admins") or []
    if not isinstance(admins_raw, list):
        raise ValueError('config: "admins" bir liste olmalı (kullanıcı ID\'si ya da e-posta).')
    admins = []
    for a in admins_raw:
        t = parse_target(a, "admins")
        if t["type"] == "usergroup":
            raise ValueError(f'config: admins içindeki "{a}" bir kullanıcı ID\'si (U…) ya da e-posta olmalı.')
        admins.append(t)
    return {
        "keywords": keywords,
        "channels": set(channels) if isinstance(channels, list) else set(),
        "notify_mode": mode,
        "require_at": raw.get("require_at", True) is not False,
        "ack_reaction": ack.strip(":"),
        "dm_template": dm_template,
        "reply_template": reply_template,
        "admins": admins,
    }


class ConfigLoader:
    """Dosya değiştiyse yeniden okur (mtime'a bakar). load() -> (config, changed). save(raw) dosyaya yazar."""

    def __init__(self, path):
        self.path = path
        self.raw = None
        self._config = None
        self._mtime = None

    def load(self):
        mtime = os.stat(self.path).st_mtime
        if self._config is not None and mtime == self._mtime:
            return self._config, False
        with open(self.path, encoding="utf-8") as f:
            raw = json.load(f)
        self._config = normalize_config(raw)
        self.raw = raw
        self._mtime = mtime
        return self._config, True

    def save(self, raw):
        """Önce doğrular, sonra atomik yazar (yarım dosya kalmaz). Dönen: yeni normalize config."""
        config = normalize_config(raw)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, self.path)
        self.raw = raw
        self._config = config
        self._mtime = os.stat(self.path).st_mtime
        return config


def permalink(team_url, channel, ts, thread_ts=None):
    """Mesajın kalıcı linki. Thread yanıtı ise thread parametresiyle açılır."""
    link = f"{team_url.rstrip('/')}/archives/{channel}/p{ts.replace('.', '')}"
    if thread_ts and thread_ts != ts:
        link += f"?thread_ts={thread_ts}&cid={channel}"
    return link


def quote(text, limit=QUOTE_MAX):
    """Mesaj metnini alıntı bloğuna çevirir; uzunsa kısaltır."""
    t = (text or "").strip()
    if len(t) > limit:
        t = t[:limit].rstrip() + "…"
    if not t:
        return "> _(metin yok)_"
    return "\n".join("> " + line for line in t.splitlines())


def build_dm_text(template, channel, author, keywords, text, link):
    return template.format(
        channel=channel,
        author=author,
        keyword=", @".join(keywords),
        quote=quote(text),
        link=link,
    )


def format_mention(target, resolved):
    if target["type"] == "usergroup":
        gid = resolved["usergroups"].get(target["handle"])
        return f"<!subteam^{gid}|@{target['handle']}>" if gid else None
    if target["type"] == "email":
        uid = resolved["users"].get(target["email"])
        return f"<@{uid}>" if uid else None
    return f"<@{target['id']}>"


def mentions_for(hits, config, resolved):
    """thread/channel modu: eşleşen keyword'lerin hedeflerini gerçek mention string'lerine çevirir (tekrarsız)."""
    out = []
    for kw in hits:
        for target in config["keywords"].get(kw, []):
            m = format_mention(target, resolved)
            if m and m not in out:
                out.append(m)
    return out


def recipients_for(hits, config, resolved, members_of, exclude=()):
    """dm modu: eşleşen keyword'lerin hedeflerini kullanıcı ID listesine açar (tekrarsız, sıralı).

    members_of(usergroup_id) -> [user_id, ...] (app.py Slack'ten çeker, test sahte verir).
    """
    out = []

    def add(uid):
        if uid and uid not in out and uid not in exclude:
            out.append(uid)

    for kw in hits:
        for target in config["keywords"].get(kw, []):
            if target["type"] == "usergroup":
                gid = resolved["usergroups"].get(target["handle"])
                if gid:
                    for uid in members_of(gid) or []:
                        add(uid)
            elif target["type"] == "email":
                add(resolved["users"].get(target["email"]))
            else:
                add(target["id"])
    return out


def build_reply(template, mentions, author_id):
    text = template.replace("{mentions}", " ".join(mentions))
    text = text.replace("{author}", f"<@{author_id}>" if author_id else "")
    return re.sub(r"\s{2,}", " ", text).strip()
