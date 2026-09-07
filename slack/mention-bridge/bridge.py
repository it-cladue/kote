"""Slack'e bağlanmayan saf mantık: config okuma/doğrulama, metinde etiket arama, bildirim metinleri.

app.py bunları kullanır; test_bridge.py Slack olmadan test eder.
"""
import json
import os
import re
import shutil
import threading
import time

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,}$")
CHANNEL_ID_RE = re.compile(r"^[CG][A-Z0-9]{8,}$")
HANDLE_RE = re.compile(r"^[\w.-]+$")
TOKEN_RE = re.compile(r"<[^>]*>")
CODE_RE = re.compile(r"```.*?```|`[^`\n]*`", re.S)
SUBTEAM_TOKEN_RE = re.compile(r"<!subteam\^([A-Z0-9]+)(?:\|@?([^>|]+))?>")
TR_FOLD = str.maketrans({"İ": "i", "ı": "i"})   # Türkçe İ/ı, lower() öncesi (İ.lower() = 'i' + nokta işareti olurdu)
NOTIFY_MODES = ("dm", "thread", "channel")

DEFAULT_DM_TEMPLATE = (
    "<#{channel}> kanalında <@{author}> *@{keyword}* etiketini kullandı:\n"
    "{quote}\n"
    "<{link}|Mesaja git>"
)
DEFAULT_REPLY_TEMPLATE = "{mentions} {author} sizi etiketledi."
QUOTE_MAX = 400


def fold(text):
    """Büyük/küçük harf ve Türkçe İ/ı duyarsız karşılaştırma için."""
    return (text or "").translate(TR_FOLD).lower()


def strip_slack_tokens(text):
    """Kod bloklarını/aralıklarını ve Slack'in kendi token'larını (<@U..>, <!subteam^S..|@petra>, <#C..>, <http..>) atar.

    Token atılmazsa gerçek bir @petra mention'ının içindeki "@petra" da yakalanır ve ekip iki kez bildirim alır.
    Kod içindeki `@petra` ("etiketi şöyle kullanın: `@petra`") tetiklemez.
    """
    return TOKEN_RE.sub(" ", CODE_RE.sub(" ", text or ""))


def expose_foreign_subteams(text, local_group_ids):
    """Başka workspace'in gerçek grup etiketini (<!subteam^S…|@petra>) düz " @petra " metnine çevirir.

    İki zone'lu kurulumda A'dan biri otomatik tamamlamayla gerçek @petra yazınca Slack yalnızca A'daki
    üyeleri bildirir; B'deki botun bunu düz "@petra" gibi görüp B'deki üyelere haber vermesi gerekir.
    Kendi workspace'imizin grubu ise olduğu gibi bırakılır (strip_slack_tokens atar; Slack zaten bildirdi).
    Boşluklarla çevrelenir ki "…>lar" gibi bitişik ekler eşleşmeyi bozmasın.
    """
    def repl(m):
        sid, handle = m.group(1), m.group(2)
        if sid in local_group_ids or not handle:
            return m.group(0)
        return f" @{handle.strip()} "
    return SUBTEAM_TOKEN_RE.sub(repl, text or "")


def local_mentioned_handles(text, id_to_handle):
    """Mesajda gerçek etiketi geçen KENDİ gruplarımızın handle'ları (Slack zaten bildirdi; tekrar bildirme)."""
    out = set()
    for sid, _ in SUBTEAM_TOKEN_RE.findall(text or ""):
        if sid in id_to_handle:
            out.add(id_to_handle[sid])
    return out


def plain_subteams(text):
    """Alıntı için: her grup etiketini düz "@handle" yapar (DM'de ham token ya da ikinci bildirim olmasın)."""
    return SUBTEAM_TOKEN_RE.sub(lambda m: "@" + (m.group(2) or "grup").strip(), text or "")


def find_keywords(text, keywords, require_at=True):
    """Metinde geçen keyword'leri config'deki sırayla, tekrarsız döndürür.

    "@petra", "@Petra", "@petra'ya", "(@petra)", "@petra." eşleşir;
    "@petrax", "ali@petra.com", "@petra-2", "@petra.ops" (ayrı bir handle) eşleşmez.
    """
    clean = fold(strip_slack_tokens(text))
    at = "@" if require_at else "@?"
    found = []
    for kw in keywords:
        pattern = r"(?<![\w@])" + at + re.escape(fold(kw)) + r"(?![\w-]|\.\w)"
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
    return {"type": "usergroup", "handle": fold(handle)}


def normalize_config(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("keywords"), dict):
        raise ValueError('config: "keywords" nesnesi zorunlu. Örnek için config.example.json dosyasına bak.')
    keywords = {}
    for kw, value in raw["keywords"].items():
        if kw.startswith("_"):  # "_aciklama" gibi notlar
            continue
        key = fold(kw.strip().lstrip("@"))
        if not key:
            raise ValueError("config: boş keyword.")
        targets = value if isinstance(value, list) else [value]
        if not targets:
            raise ValueError(f'config: "{kw}" için en az bir hedef gerekli.')
        parsed = [parse_target(t, kw) for t in targets]
        if key in keywords:  # "@Fransa" ve "fransa" aynı etiket
            for t in parsed:
                if t not in keywords[key]:
                    keywords[key].append(t)
        else:
            keywords[key] = parsed
    if not keywords:
        raise ValueError("config: hiç keyword tanımlı değil.")

    mode = raw.get("notify_mode", "dm")
    if mode not in NOTIFY_MODES:
        raise ValueError(f'config: notify_mode {", ".join(NOTIFY_MODES)} olmalı, "{mode}" değil.')

    require_at = raw.get("require_at", True)
    if not isinstance(require_at, bool):
        raise ValueError("config: require_at true ya da false olmalı (tırnaksız).")

    dm_template = raw.get("dm_template")
    if dm_template is None:
        dm_template = DEFAULT_DM_TEMPLATE
    elif not isinstance(dm_template, str) or "{link}" not in dm_template:
        raise ValueError("config: dm_template bir metin olmalı ve {link} içermeli.")
    try:
        build_dm_text(dm_template, "C0", "U0", ["k"], "q", "l")
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(
            f"config: dm_template hatalı ({e}). Kullanılabilir alanlar: {{channel}} {{author}} {{keyword}} {{quote}} {{link}}"
        )
    reply_template = raw.get("reply_template")
    if reply_template is None:
        reply_template = DEFAULT_REPLY_TEMPLATE
    elif not isinstance(reply_template, str) or "{mentions}" not in reply_template:
        raise ValueError("config: reply_template bir metin olmalı ve {mentions} içermeli.")

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
        if t not in admins:
            admins.append(t)
    return {
        "keywords": keywords,
        "channels": set(channels) if isinstance(channels, list) else set(),
        "notify_mode": mode,
        "require_at": require_at,
        "ack_reaction": ack.strip(":"),
        "dm_template": dm_template,
        "reply_template": reply_template,
        "admins": admins,
    }


def atomic_write_json(path, data):
    """Önce benzersiz bir .tmp'ye yazar, sonra yerine koyar; Windows'ta dosya kısa süre kilitliyse birkaç kez dener."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.2 * (attempt + 1))


def rotate_backups(path, keep=3):
    """config.json -> config.json.bak1, eskiler .bak2/.bak3 olur (DM komutları dosyayı yazdığı için yedek)."""
    if not os.path.exists(path):
        return
    for i in range(keep, 1, -1):
        src, dst = f"{path}.bak{i - 1}", f"{path}.bak{i}"
        if os.path.exists(src):
            os.replace(src, dst)
    shutil.copyfile(path, f"{path}.bak1")


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
        with open(self.path, encoding="utf-8-sig") as f:
            raw = json.load(f)
        self._config = normalize_config(raw)
        self.raw = raw
        self._mtime = mtime
        return self._config, True

    def disk_changed(self):
        """Diskteki dosya belleğe alınandan farklı mı (elle düzenlenmiş ve henüz okunamamış olabilir)."""
        try:
            return os.stat(self.path).st_mtime != self._mtime
        except OSError:
            return True

    def save(self, raw):
        """Önce doğrular, yedek alır, sonra atomik yazar (yarım dosya kalmaz). Dönen: yeni normalize config."""
        config = normalize_config(raw)
        try:
            rotate_backups(self.path)
        except OSError:
            pass  # yedek alınamaması kaydı engellemesin
        atomic_write_json(self.path, raw)
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
    """Mesaj metnini alıntı bloğuna çevirir; grup etiketlerini düz metne indirir, uzunsa kelime/token sınırında kısaltır."""
    t = plain_subteams(text).strip()
    if len(t) > limit:
        cut = t[:limit]
        cut = re.sub(r"<[^>]*$", "", cut)          # yarım kalan <@U…> / <http…> token'ı
        ws = cut.rfind(" ")
        if ws > limit // 2:
            cut = cut[:ws]
        t = cut.rstrip() + "…"
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
