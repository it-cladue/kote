"""Etiket Köprüsü.

Slack Connect kanalında düz metin "@petra" görünce @petra user group'unun üyelerine bildirim gönderir.
@petra'nın olduğu workspace'e kurulur; Socket Mode kullanır, dışa açık endpoint gerekmez.
Bot hangi kanala eklendiyse orada çalışır (config.json > channels boşsa); yönetim komutları bota DM'den,
sadece config.json > admins listesindeki hesaplardan (bkz. commands.py > HELP ya da DM'de `yardım`).

    .env dosyası (app.py'nin yanında):
        SLACK_BOT_TOKEN=xoxb-...      zorunlu (Bot User OAuth Token)
        SLACK_APP_TOKEN=xapp-...      zorunlu (App-Level Token, connections:write)
        SLACK_ADMIN_TOKEN=xoxp-...    isteğe bağlı (User OAuth Token); `grup …` komutları bununla çalışır, yoksa bot token
    python app.py

notify_mode:
  dm      -> kanala/thread'e HİÇBİR ŞEY yazılmaz; kanalda olan grup üyelerine "şu kanalda şu kişi sizi etiketledi,
             mesaja git" DM'i gider (Slack'in kendi "kanalda etiketlendiniz" Slackbot mesajı gibi).
  thread  -> mesajın thread'ine gerçek <!subteam^…|@petra> mention'ı yazılır.
  channel -> kanala ayrı bir mesaj olarak yazılır.

Dayanıklılık:
  - state.json: kanal başına son işlenen mesaj zamanı. Bot açılınca, kapalı kaldığı süre için (en fazla 1 saat)
    kanal geçmişini tarar ve kaçırdığı @etiketleri bildirir (thread yanıtları hariç).
  - Slack bağlantısı 5 dakikadan uzun kopuk kalırsa süreç çıkar; servis (NSSM) yeniden başlatır.
  - Rate limit'te DM 3 kez yeniden denenir. Log satırlarında workspace adı bulunur.
"""
import copy
import json
import logging
import os
import sys
import threading
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

import bridge
import commands

HERE = os.path.dirname(os.path.abspath(__file__))


def load_dotenv(path):
    """Yanındaki .env dosyasından token'ları okur. .env varsa ortam değişkenini ezer; tek doğru kaynak .env olsun diye
    (token yenilemede sadece .env düzenlenir). Notepad'in koyduğu BOM'u tolere eder."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip().lstrip("﻿")
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ[key.strip()] = value


load_dotenv(os.path.join(HERE, ".env"))
BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
ADMIN_TOKEN = os.environ.get("SLACK_ADMIN_TOKEN")
CONFIG_PATH = os.environ.get("BRIDGE_CONFIG") or os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(CONFIG_PATH)), "state.json")
RESOLVE_TTL = 15 * 60        # grup/kişi ID'leri: yeni grup en geç 15 dk'da görülür
MEMBERS_TTL = 5 * 60         # grup üye listesi ve kanal üye listesi: değişiklik en geç 5 dk'da görülür
CATCHUP_WINDOW = 60 * 60     # açılışta en fazla bu kadar geriye bakılır
WATCHDOG_SECONDS = 5 * 60    # bağlantı bu kadar süre kopuksa çık (servis yeniden başlatsın)
HEARTBEAT_SECONDS = 30

state = {
    "config": None,
    "resolved": {"usergroups": {}, "users": {}},   # handle -> S…, email -> U…
    "resolved_at": 0.0,
    "admin_ids": set(),
    "members": {},                                  # S… -> (zaman, [U…])
    "chan_members": {},                             # C… -> (zaman, {U…})
    "team_url": "",
    "team_name": "",
    "seen": {},                                     # "C…:ts" -> zaman (aynı event'i iki kez işlememek için)
    "last_ts": {},                                  # C… -> son işlenen mesaj ts (state.json'a yazılır)
    "started_at": time.time(),
    "last_event_at": None,
    "last_notice": None,                            # {"channel","ts","hits","n","at"}
    "sent_total": 0,
    "failed_total": 0,
    "catchup": None,                                # {"scanned","notified","channels"}
    "handler": None,
    "admin_client": None,
}


class TeamFilter(logging.Filter):
    """Her log satırına workspace adını ekler (iki bot aynı dosyaya yazsa bile ayırt edilir)."""

    def filter(self, record):
        record.team = state.get("team_name") or "-"
        return True


logging.basicConfig(
    level=logging.DEBUG if os.environ.get("BRIDGE_DEBUG") else logging.INFO,
    format="%(asctime)s %(levelname)s [%(team)s] %(message)s",
)
for _h in logging.getLogger().handlers:
    _h.addFilter(TeamFilter())
log = logging.getLogger("bridge")

if not BOT_TOKEN or not APP_TOKEN:
    print("SLACK_BOT_TOKEN (xoxb-...) ve SLACK_APP_TOKEN (xapp-...) gerekli: app.py'nin yanına .env dosyası koy "
          "(satır satır SLACK_BOT_TOKEN=... / SLACK_APP_TOKEN=...) ya da ortam değişkeni olarak ver.", file=sys.stderr)
    sys.exit(1)

_client = WebClient(token=BOT_TOKEN)
_client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
app = App(client=_client, logger=logging.getLogger("bolt"), token_verification_enabled=False)  # auth_test'i main() yapar
if ADMIN_TOKEN:
    state["admin_client"] = WebClient(token=ADMIN_TOKEN)
    state["admin_client"].retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=3))
loader = bridge.ConfigLoader(CONFIG_PATH)
lock = threading.Lock()        # config + hedef çözümleme + grup üyelik değişiklikleri
seen_lock = threading.Lock()   # seen sözlüğü (listener'lar paralel çalışır)
state_lock = threading.Lock()  # state.json yazımı


def slack_error(e):
    return e.response.get("error") if getattr(e, "response", None) else str(e)


# ---------------- kalıcı durum (state.json) ----------------

def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        state["last_ts"] = {k: str(v) for k, v in (data.get("last_ts") or {}).items()}
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        log.warning("state.json okunamadı (%s); sıfırdan başlanıyor.", e)


def save_state():
    with state_lock:
        data = {
            "last_ping": time.time(),
            "team": state["team_name"],
            "connected": is_connected(),
            "last_event_at": state["last_event_at"],
            "last_ts": dict(state["last_ts"]),
        }
        try:
            bridge.atomic_write_json(STATE_PATH, data)
        except OSError as e:
            log.warning("state.json yazılamadı (%s).", e)


def is_connected():
    h = state.get("handler")
    try:
        return bool(h and h.client.is_connected())
    except Exception:  # noqa: BLE001
        return False


# ---------------- hedef çözümleme ----------------

def lookup_email(client, email):
    cached = state["resolved"]["users"].get(email)
    if cached:
        return cached
    uid = client.users_lookupByEmail(email=email)["user"]["id"]
    state["resolved"]["users"][email] = uid
    return uid


def compute_admin_ids():
    cfg = state["config"]
    users = state["resolved"]["users"]
    state["admin_ids"] = {
        t["id"] if t["type"] == "user" else users.get(t["email"]) for t in cfg["admins"]
    } - {None}


def resolve_targets(client):
    """config'deki handle ve e-postaları Slack ID'lerine çevirir. Bulunamayan loglanır, bot düşmez."""
    groups = {}
    for g in client.usergroups_list(include_disabled=False).get("usergroups", []):
        groups[g["handle"].lower()] = g["id"]
    users = dict(state["resolved"]["users"])
    cfg = state["config"]
    for targets in list(cfg["keywords"].values()) + [cfg["admins"]]:
        for t in targets:
            if t["type"] == "usergroup" and t["handle"] not in groups:
                log.warning("@%s diye bir user group bu workspace'te yok (ya da devre dışı); atlanıyor.", t["handle"])
            elif t["type"] == "email" and t["email"] not in users:
                try:
                    users[t["email"]] = client.users_lookupByEmail(email=t["email"])["user"]["id"]
                except SlackApiError as e:
                    log.warning("%s bu workspace'te bulunamadı (%s); atlanıyor.", t["email"], slack_error(e))
    state["resolved"] = {"usergroups": groups, "users": users}
    compute_admin_ids()
    state["resolved_at"] = time.time()
    state["members"] = {}
    log.info("Hedefler çözüldü: %d user group, %d kişi, %d yetkili.", len(groups), len(users), len(state["admin_ids"]))


def ensure_fresh(client):
    """config değiştiyse yükler; hedefleri gerekirse çözer. Slack'e ulaşılamazsa eldeki bilgiyle devam eder."""
    with lock:
        config, changed = loader.load()
        state["config"] = config
        if changed:
            log.info("config yüklendi: %s  (mod: %s)", ", ".join("@" + k for k in config["keywords"]), config["notify_mode"])
            compute_admin_ids()  # ağ gerektirmeyen kısım hemen (ID ile tanımlı yetkililer ve önbellekteki e-postalar)
        if changed or time.time() - state["resolved_at"] > RESOLVE_TTL:
            try:
                resolve_targets(client)
            except Exception as e:  # noqa: BLE001  (ratelimited, ağ) -> bir sonraki olayda yeniden dene
                state["resolved_at"] = 0
                log.warning("Hedefler çözülemedi (%s); eldeki bilgiyle devam, sonra yeniden denenecek.", e)


def members_of(client):
    def fetch(gid):
        cached = state["members"].get(gid)
        if cached and time.time() - cached[0] < MEMBERS_TTL:
            return cached[1]
        try:
            ids = client.usergroups_users_list(usergroup=gid).get("users", [])
        except Exception as e:  # noqa: BLE001  (hata önbelleğe alınmaz; bir sonraki mesajda yeniden denenir)
            log.warning("%s üyeleri alınamadı (%s).", gid, slack_error(e) if isinstance(e, SlackApiError) else e)
            return cached[1] if cached else []
        state["members"][gid] = (time.time(), ids)
        return ids
    return fetch


def channel_members(client, channel):
    """Kanal üyeleri (kısa önbellek). Alınamazsa eski önbellek; hiç yoksa None (filtre uygulanamaz)."""
    cached = state["chan_members"].get(channel)
    if cached and time.time() - cached[0] < MEMBERS_TTL:
        return cached[1]
    try:
        members, cursor = set(), None
        while True:
            r = client.conversations_members(channel=channel, limit=1000, cursor=cursor)
            members.update(r.get("members", []))
            cursor = (r.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:  # noqa: BLE001
        log.warning("%s kanal üyeleri alınamadı (%s).", channel, slack_error(e) if isinstance(e, SlackApiError) else e)
        return cached[1] if cached else None
    state["chan_members"][channel] = (time.time(), members)
    return members


def already_seen(key):
    with seen_lock:
        now = time.time()
        seen = state["seen"]
        if key in seen:
            return True
        seen[key] = now
        if len(seen) > 1000:
            state["seen"] = {k: t for k, t in seen.items() if now - t <= 600}
        return False


def bot_channels(client):
    """Botun üye olduğu kanallar (users.conversations, sayfalı)."""
    chans, cursor = [], None
    while True:
        r = client.users_conversations(types="public_channel,private_channel", exclude_archived=True, limit=200, cursor=cursor)
        chans += r.get("channels", [])
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return chans


# ---------------- kanal mesajları: etiket -> bildirim ----------------

def message_link(client, event):
    """Slack'in kendi kalıcı linki (thread parametrelerini de o ekler); alınamazsa elle kurulan biçim."""
    try:
        return client.chat_getPermalink(channel=event["channel"], message_ts=event["ts"])["permalink"]
    except Exception as e:  # noqa: BLE001  (link yüzünden bildirim düşmesin)
        log.debug("chat.getPermalink başarısız (%s); link elle kuruluyor.", e)
        return bridge.permalink(state["team_url"], event["channel"], event["ts"], event.get("thread_ts"))


def notify_by_dm(event, hits, client):
    cfg = state["config"]
    recipients = bridge.recipients_for(hits, cfg, state["resolved"], members_of(client), exclude=(event["user"],))
    if not recipients:
        log.warning('"%s" eşleşti ama bildirim gidecek kimse yok (grup boş / bulunamadı).', ", ".join(hits))
        return 0
    # Slack'in kendi davranışı gibi: yalnızca KANALDA olan üyeler. Kanalda olmayan, karşı tarafın mesajını görmemeli.
    members = channel_members(client, event["channel"])
    if members is None:
        log.warning("Kanal üyeleri doğrulanamadı; %d alıcıya filtresiz gönderiliyor.", len(recipients))
    else:
        skipped = [u for u in recipients if u not in members]
        recipients = [u for u in recipients if u in members]
        if skipped:
            log.info("Kanalda olmayan üyeler atlandı (kanala ekleyin): %s", " ".join(skipped))
        if not recipients:
            log.warning('"%s" eşleşti ama grubun hiçbir üyesi kanalda değil.', ", ".join(hits))
            return 0
    link = message_link(client, event)
    try:
        text = bridge.build_dm_text(cfg["dm_template"], event["channel"], event["user"], hits, event.get("text"), link)
    except Exception as e:  # noqa: BLE001  (şablon hatası bildirimi düşürmesin)
        log.error("dm_template uygulanamadı (%s); varsayılan şablon kullanıldı.", e)
        text = bridge.build_dm_text(bridge.DEFAULT_DM_TEMPLATE, event["channel"], event["user"], hits, event.get("text"), link)
    sent = failed = 0
    for uid in recipients:
        try:
            client.chat_postMessage(channel=uid, text=text, unfurl_links=False, unfurl_media=False)
            sent += 1
        except Exception as e:  # noqa: BLE001  (bir kişi hata verirse diğerleri yine alsın)
            failed += 1
            log.warning("%s kişisine DM gönderilemedi (%s).", uid, slack_error(e) if isinstance(e, SlackApiError) else e)
    if failed:
        log.warning("%d/%d kişiye DM gidemedi.", failed, len(recipients))
    state["sent_total"] += sent
    state["failed_total"] += failed
    return sent


def notify_in_channel(event, hits, client):
    cfg = state["config"]
    mentions = bridge.mentions_for(hits, cfg, state["resolved"])
    if not mentions:
        log.warning('"%s" eşleşti ama çözülebilen hedef yok (grup/kişi bulunamadı).', ", ".join(hits))
        return 0
    params = {"channel": event["channel"], "text": bridge.build_reply(cfg["reply_template"], mentions, event["user"])}
    if cfg["notify_mode"] == "thread":
        params["thread_ts"] = event.get("thread_ts") or event["ts"]
    client.chat_postMessage(**params)
    return len(mentions)


def remember_ts(channel, ts):
    prev = state["last_ts"].get(channel)
    if prev is None or float(ts) > float(prev):
        state["last_ts"][channel] = ts
        save_state()


def hits_in(text):
    """Metindeki etiketler: başka zone'un gerçek etiketi düz metin sayılır, kendi grubumuzun gerçek etiketi sayılmaz
    (Slack zaten bildirdi), kendi grubumuzun gerçek etiketiyle aynı mesajdaki düz "@petra" da sayılmaz."""
    cfg = state["config"]
    groups = state["resolved"]["usergroups"]
    exposed = bridge.expose_foreign_subteams(text, set(groups.values()))
    hits = bridge.find_keywords(exposed, list(cfg["keywords"]), require_at=cfg["require_at"])
    if hits:
        native = bridge.local_mentioned_handles(text, {v: k for k, v in groups.items()})
        hits = [h for h in hits if h not in native]
    return hits


def handle_channel_message(event, client):
    """Dönen: gönderilen bildirim sayısı (eşleşme yoksa 0)."""
    cfg = state["config"]
    if cfg["channels"] and event["channel"] not in cfg["channels"]:
        log.info("%s kanal filtresi dışında; mesaj atlandı.", event["channel"])
        return 0
    n = 0
    try:
        hits = hits_in(event.get("text"))
        if event.get("previous_text") is not None:  # düzenleme: yalnızca yeni eklenen etiketler
            old = hits_in(event["previous_text"])
            hits = [h for h in hits if h not in old]
        if not hits:
            return 0
        if cfg["notify_mode"] == "dm":
            n = notify_by_dm(event, hits, client)
            what = f"{n} kişiye DM"
        else:
            n = notify_in_channel(event, hits, client)
            what = f"{n} mention ({cfg['notify_mode']})"
        if n and cfg["ack_reaction"]:
            try:
                client.reactions_add(channel=event["channel"], timestamp=event["ts"], name=cfg["ack_reaction"])
            except SlackApiError as e:
                if slack_error(e) != "already_reacted":
                    log.warning("Emoji konulamadı (%s).", slack_error(e))
        state["last_notice"] = {"channel": event["channel"], "ts": event["ts"], "hits": hits, "n": n, "at": time.time()}
        log.info("%s %s: @%s -> %s.", event["channel"], event["ts"], ", @".join(hits), what)
        return n
    finally:
        if event.get("previous_text") is None:
            remember_ts(event["channel"], event["ts"])


# ---------------- DM: yönetim komutları ----------------

def group_client(client):
    """Slack user group'larını değiştiren çağrılar için: varsa yönetici (xoxp) token'ı, yoksa bot token'ı."""
    return state.get("admin_client") or client


def find_group(client, handle):
    handle = handle.lstrip("@").lower()
    for g in client.usergroups_list(include_disabled=True, include_users=True).get("usergroups", []):
        if g["handle"].lower() == handle:
            return g
    return None


def resolve_people(client, args):
    ids, problems = [], []
    for a in args:
        try:
            t = bridge.parse_target(a, "kişi")
        except ValueError as e:
            problems.append(str(e))
            continue
        if t["type"] == "user":
            ids.append(t["id"])
        elif t["type"] == "email":
            try:
                ids.append(lookup_email(client, t["email"]))
            except SlackApiError as e:
                problems.append(f"{t['email']} bulunamadı ({slack_error(e)})")
        else:
            problems.append(f"`{a}` bir kişi değil; `@kişi` ya da e-posta ver.")
    return ids, problems


def save_config(raw):
    """Doğrular ve yazar; yazma hatasını komut yanıtına çevirir."""
    try:
        loader.save(raw)
    except OSError as e:
        raise commands.CommandError(f"config.json yazılamadı ({e}). Dosya başka bir programda açık olabilir; kapatıp tekrar dene.")
    state["resolved_at"] = 0  # yeni hedef/yetkili ID'lerini hemen çöz


def editable_raw():
    """Komutla değiştirilecek config'in taze kopyası. Diskteki dosya elle bozulmuşsa üzerine yazmayı reddeder."""
    try:
        loader.load()
    except Exception as e:  # noqa: BLE001
        raise commands.CommandError(f"config.json diskteki haliyle geçersiz ({e}). Önce dosyayı düzelt (ya da .bak1 yedeğinden geri al), sonra komutu tekrar ver.")
    return copy.deepcopy(loader.raw)


GROUP_ERR_HINT = {
    "invalid_users": "kişi bu workspace'in tam üyesi değil (guest ya da başka workspace).",
    "permission_denied": "workspace ayarı user group yönetimini sadece Owner/Admin'e veriyor. Ya Workspace Settings > Permissions > User Groups ayarını genişlet ya da .env'e Owner/Admin'in User OAuth Token'ını (SLACK_ADMIN_TOKEN=xoxp-…) ekleyip botu yeniden başlat.",
    "missing_scope": "token'da usergroups:write scope'u yok; manifesti güncelleyip Reinstall yap.",
    "not_allowed_token_type": "bu token türü user group yönetemiyor; SLACK_ADMIN_TOKEN (xoxp) kullan.",
}


def group_command(cmd, args, client):
    """grup liste / oluştur / ekle / çıkar: gerçek Slack user group'ları."""
    gclient = group_client(client)
    if cmd == "grup liste":
        groups = client.usergroups_list(include_disabled=False, include_users=True, include_count=True).get("usergroups", [])
        if args:
            g = find_group(client, args[0])
            if not g:
                raise commands.CommandError(f"@{args[0].lstrip('@')} diye bir user group yok.")
            users = g.get("users") or []
            shown = " ".join(f"<@{u}>" for u in users[:100]) or "_(üye yok)_"
            note = "  ⚠️ devre dışı" if g.get("date_delete") else ""
            return f"*@{g['handle']}* ({g['id']}) {len(users)} üye{note}:\n{shown}"
        if not groups:
            return "Bu workspace'te aktif user group yok."
        return "*User group'lar*\n" + "\n".join(f"• `@{g['handle']}` {g.get('user_count', len(g.get('users') or []))} üye" for g in groups)

    if cmd == "grup olustur":
        if not args:
            raise commands.CommandError("Kullanım: `grup oluştur <handle> [ad]`")
        handle = bridge.fold(args[0].lstrip("@"))
        if not bridge.HANDLE_RE.match(handle) or handle.startswith("_"):
            raise commands.CommandError(f"`{args[0]}` geçerli bir handle değil.")
        name = " ".join(args[1:]) or handle
        existing = find_group(client, handle)
        try:
            if existing:
                if existing.get("date_delete"):
                    gclient.usergroups_enable(usergroup=existing["id"])
                    note = f"@{handle} devre dışıydı, yeniden aktif edildi."
                else:
                    note = f"@{handle} zaten vardı."
            else:
                g = gclient.usergroups_create(name=name, handle=handle)["usergroup"]
                note = f"Slack'te *@{g['handle']}* user group'u açıldı ({g['id']}). Üye eklemek için `grup ekle {handle} @kişi`."
        except SlackApiError as e:
            err = slack_error(e)
            raise commands.CommandError(f"Slack hatası: `{err}` {GROUP_ERR_HINT.get(err, '')}".strip())
        with lock:
            raw = editable_raw()
            reply, _ = commands.apply(raw, "ekle", [handle], {"known_groups": None})
            save_config(raw)
        return note + "\nEtiket: " + reply.splitlines()[-1]

    if cmd in ("grup ekle", "grup cikar"):
        if len(args) < 2:
            raise commands.CommandError(f"Kullanım: `{ 'grup ekle' if cmd == 'grup ekle' else 'grup çıkar' } <handle> <kişi…>`")
        with lock:  # iki yetkili aynı anda değiştirmesin (users.update tüm listeyi değiştirir)
            g = find_group(client, args[0])
            if not g:
                raise commands.CommandError(f"@{args[0].lstrip('@')} diye bir user group yok. `grup oluştur {args[0].lstrip('@')}` ile açabilirsin.")
            if g.get("date_delete"):
                raise commands.CommandError(f"@{g['handle']} devre dışı; önce `grup oluştur {g['handle']}` ile aktif et.")
            ids, problems = resolve_people(client, args[1:])
            try:  # güncel üye listesi (users.update listeyi KOMPLE değiştirir; eksik liste grubu siler)
                current = list(client.usergroups_users_list(usergroup=g["id"]).get("users") or [])
            except SlackApiError as e:
                raise commands.CommandError(f"Üye listesi alınamadı (`{slack_error(e)}`); değişiklik yapılmadı.")
            if cmd == "grup ekle":
                new = current + [u for u in ids if u not in current]
                changed = [u for u in ids if u not in current]
            else:
                new = [u for u in current if u not in ids]
                changed = [u for u in ids if u in current]
            lines = []
            if problems:
                lines.append("⚠️ " + "\n⚠️ ".join(problems))
            if not changed:
                lines.append("Değişiklik yok." if not problems else "Geçerli kişi kalmadı, değişiklik yok.")
                return "\n".join(lines)
            if not new:
                raise commands.CommandError("Slack user group'u boş bırakmaz; son üyeyi çıkaramazsın.")
            try:
                gclient.usergroups_users_update(usergroup=g["id"], users=",".join(new))
            except SlackApiError as e:
                err = slack_error(e)
                raise commands.CommandError(f"Slack hatası: `{err}` {GROUP_ERR_HINT.get(err, '')}".strip())
            state["members"].pop(g["id"], None)
        verb = "eklendi" if cmd == "grup ekle" else "çıkarıldı"
        lines.append(f"*@{g['handle']}* {verb}: " + " ".join(f"<@{u}>" for u in changed) + f"\nŞu an {len(new)} üye.")
        return "\n".join(lines)

    raise commands.CommandError(f"`{cmd}` bilinmiyor.")


def _ago(t):
    if not t:
        return "hiç"
    s = int(time.time() - t)
    if s < 60:
        return f"{s} sn önce"
    if s < 3600:
        return f"{s // 60} dk önce"
    if s < 86400:
        return f"{s // 3600} sa {s % 3600 // 60} dk önce"
    return f"{s // 86400} gün önce"


def status_text(client):
    cfg = state["config"]
    up = int(time.time() - state["started_at"])
    ln = state["last_notice"]
    lines = [
        f"*Workspace:* {state['team_name']}  *Mod:* `{cfg['notify_mode']}`  *Emoji:* {(':' + cfg['ack_reaction'] + ':') if cfg['ack_reaction'] else 'kapalı'}",
        f"*Bağlantı:* {'açık' if is_connected() else 'KOPUK'}  *Çalışma süresi:* {up // 3600} sa {up % 3600 // 60} dk  *Son olay:* {_ago(state['last_event_at'])}",
        f"*Son bildirim:* " + (f"<#{ln['channel']}> @{', @'.join(ln['hits'])} → {ln['n']} kişi, {_ago(ln['at'])}" if ln else "hiç")
        + f"  *Toplam:* {state['sent_total']} gönderildi, {state['failed_total']} başarısız",
        f"*Etiketler:* " + (", ".join("@" + k for k in cfg["keywords"]) or "yok"),
        f"*Çözülen:* {len(state['resolved']['usergroups'])} user group, {len(state['resolved']['users'])} kişi",
        f"*Yetkililer:* " + (" ".join(f"<@{u}>" for u in sorted(state["admin_ids"])) or "yok"),
        "*Grup yönetimi:* " + ("yönetici token'ı (xoxp)" if state.get("admin_client") else "bot token'ı (workspace izni gerekir)"),
        f"*Config:* `{CONFIG_PATH}`",
    ]
    cu = state["catchup"]
    if cu:
        lines.append(f"*Açılış taraması:* {cu['channels']} kanal, {cu['scanned']} mesaj, {cu['notified']} bildirim")
    all_targets = [t for ts in cfg["keywords"].values() for t in ts] + list(cfg["admins"])
    missing_groups = sorted({t["handle"] for t in all_targets if t["type"] == "usergroup" and t["handle"] not in state["resolved"]["usergroups"]})
    missing_mails = sorted({t["email"] for t in all_targets if t["type"] == "email" and t["email"] not in state["resolved"]["users"]})
    if missing_groups:
        lines.append("⚠️ Slack'te olmayan gruplar: " + ", ".join("@" + h for h in missing_groups))
    if missing_mails:
        lines.append("⚠️ Bu workspace'te bulunamayan e-postalar: " + ", ".join(missing_mails))
    return "\n".join(lines)


def channels_text(client):
    cfg = state["config"]
    try:
        chans = bot_channels(client)
    except SlackApiError as e:
        return f"Kanal listesi alınamadı ({slack_error(e)}); channels:read / groups:read scope'u gerekir."
    if not chans:
        inside = "_hiçbir kanalda değil_ (kanalda `/invite @Etiket Köprüsü` yaz)"
    else:
        inside = "\n".join(
            f"• <#{c['id']}>" + (" (Slack Connect)" if c.get("is_ext_shared") or c.get("is_shared") else "")
            + ("" if not cfg["channels"] or c["id"] in cfg["channels"] else " _(filtre dışı)_")
            for c in chans
        )
    filt = ", ".join(f"<#{c}>" for c in cfg["channels"]) if cfg["channels"] else "yok (eklendiği her kanalda çalışır)"
    out = f"*Botun olduğu kanallar*\n{inside}\n*Filtre:* {filt}"
    if not any(c.get("is_ext_shared") or c.get("is_shared") for c in chans):
        out += ("\n⚠️ Slack Connect kanalı görünmüyor. Botu paylaşımlı kanala kendi workspace'inden biri eklemeli; "
                "davet 'yalnızca gönderme' izniyle geldiyse app eklenemez, karşı taraf izni 'gönderme, davet ve daha fazlası' yapmalı.")
    return out


def handle_command(event, client):
    uid = event["user"]
    text = (event.get("text") or "").strip()

    def reply(msg):
        client.chat_postMessage(channel=event["channel"], text=msg, unfurl_links=False)

    if not state["admin_ids"]:
        reply("Yönetici tanımlı değil. `config.json` içindeki `admins` alanına kendi kullanıcı ID'ni (U…) ya da e-postanı yaz.")
        return
    if uid not in state["admin_ids"]:
        if commands.is_command(text):
            log.warning("Yetkisiz komut denemesi: %s", uid)
            reply("Bu botu yönetme yetkin yok.")
        else:  # bildirim DM'ine yazılan "tamam", "teşekkürler" gibi yanıtlar
            log.debug("Yetkisiz kişiden DM (%s), yok sayıldı.", uid)
            reply("Ben otomatik bildirim gönderen bir botum; mesajı yanıtlamak için bildirimdeki *Mesaja git* linkini kullan.")
        return
    try:
        cmd, args = commands.parse(text)
        if cmd == "yardim":
            reply(commands.HELP)
        elif cmd == "durum":
            reply(status_text(client))
        elif cmd == "kanallar":
            reply(channels_text(client))
        elif cmd.startswith("grup "):
            reply(group_command(cmd, args, client))
        else:
            with lock:
                raw = editable_raw()
                me_email = next((e for e, u in state["resolved"]["users"].items() if u == uid), None)
                ctx = {"me": uid, "me_email": me_email, "known_groups": set(state["resolved"]["usergroups"])}
                msg, changed = commands.apply(raw, cmd, args, ctx)
                if changed:
                    save_config(raw)
            reply(msg)
        log.info("Komut (%s): %s", uid, text)
    except commands.CommandError as e:
        reply(f"{e}\nKomutlar için `yardım` yaz.")
    except SlackApiError as e:
        reply(f"Slack hatası: `{slack_error(e)}`")
        log.warning("Komut Slack hatası (%s): %s", text, slack_error(e))
    except ValueError as e:  # config doğrulaması
        reply(f"Ayar kaydedilemedi: {e}")
    except Exception as e:  # noqa: BLE001
        log.exception("Komut işlenemedi (%s)", text)
        reply(f"Beklenmeyen hata: {type(e).__name__}: {e}")
    finally:
        try:
            ensure_fresh(client)
        except Exception as e:  # noqa: BLE001
            log.error("config okunamadı: %s", e)


# ---------------- olay girişi ----------------

def process_event(event, client):
    """Canlı event ve açılış taraması aynı yoldan geçer. Dönen: bildirim sayısı."""
    subtype = event.get("subtype")
    if subtype == "message_changed":  # düzenlemeyle eklenen etiket de bildirilir (Slack'in kendi etiketi gibi)
        msg = event.get("message") or {}
        prev = event.get("previous_message") or {}
        if msg.get("bot_id") or not msg.get("user") or msg.get("subtype") not in (None, "file_share", "thread_broadcast"):
            return 0
        edited_ts = (msg.get("edited") or {}).get("ts") or event.get("event_ts") or event.get("ts")
        if already_seen(f"{event['channel']}:{msg['ts']}:edit:{edited_ts}"):
            return 0
        event = {"type": "message", "channel": event["channel"], "user": msg["user"], "text": msg.get("text"),
                 "ts": msg["ts"], "thread_ts": msg.get("thread_ts"), "previous_text": prev.get("text") or ""}
    else:
        if subtype and subtype not in ("file_share", "thread_broadcast"):
            return 0
        if event.get("bot_id") or not event.get("user"):
            return 0
        if already_seen(f"{event['channel']}:{event['ts']}"):
            return 0
    try:
        ensure_fresh(client)
    except Exception as e:  # noqa: BLE001  (config bozuksa eski config ile devam, bot düşmez)
        log.error("config okunamadı: %s", e)
        if not state["config"]:
            return 0
    if event.get("channel_type") == "im":
        handle_command(event, client)
        return 0
    return handle_channel_message(event, client)


@app.event("message")
def on_message(event, client):
    state["last_event_at"] = time.time()
    process_event(event, client)


def catch_up(client):
    """Bot kapalıyken yazılanları tarar: state.json'daki son ts'den (en fazla 1 saat) bugüne, botun olduğu kanallar."""
    now = time.time()
    scanned = notified = channels = 0
    try:
        chans = bot_channels(client)
    except SlackApiError as e:
        log.warning("Açılış taraması yapılamadı, kanal listesi alınamadı (%s).", slack_error(e))
        return
    for ch in chans:
        last = state["last_ts"].get(ch["id"])
        if not last:
            continue  # bu kanalı daha önce hiç görmedik; geçmişi bildirmek yanlış olur
        oldest = max(float(last), now - CATCHUP_WINDOW)
        try:
            r = client.conversations_history(channel=ch["id"], oldest=f"{oldest:.6f}", inclusive=False, limit=200)
        except SlackApiError as e:
            log.warning("%s geçmişi okunamadı (%s).", ch["id"], slack_error(e))
            continue
        channels += 1
        for m in sorted(r.get("messages", []), key=lambda x: float(x["ts"])):
            ev = {"type": "message", "channel": ch["id"], "user": m.get("user"), "text": m.get("text"),
                  "ts": m["ts"], "subtype": m.get("subtype"), "bot_id": m.get("bot_id"), "thread_ts": m.get("thread_ts")}
            scanned += 1
            notified += process_event(ev, client)
    state["catchup"] = {"scanned": scanned, "notified": notified, "channels": channels}
    if scanned:
        log.info("Açılış taraması: %d kanal, %d mesaj, %d bildirim.", channels, scanned, notified)


def main():
    try:
        me = app.client.auth_test()
    except SlackApiError as e:
        log.error("Bot token geçersiz: %s", slack_error(e))
        sys.exit(1)
    except Exception as e:  # noqa: BLE001  (ağ yok, proxy vb.)
        log.error("Slack'e ulaşılamadı: %s", e)
        sys.exit(2)
    state["team_url"] = me["url"]
    state["team_name"] = me["team"]
    log.info("Workspace: %s (%s)  bot: %s  config: %s", me["team"], me["team_id"], me["user"], CONFIG_PATH)
    if state.get("admin_client"):
        try:
            who = state["admin_client"].auth_test()
            if who.get("team_id") != me["team_id"]:
                log.warning("SLACK_ADMIN_TOKEN başka bir workspace'e ait (%s); grup komutları bot token'ı ile çalışacak.", who.get("team"))
                state["admin_client"] = None
            else:
                log.info("Grup yönetimi için yönetici token'ı: %s", who.get("user"))
        except Exception as e:  # noqa: BLE001
            log.warning("SLACK_ADMIN_TOKEN geçersiz (%s); grup komutları bot token'ı ile çalışacak.", e)
            state["admin_client"] = None
    try:
        ensure_fresh(app.client)
    except Exception as e:  # noqa: BLE001
        log.error("config hatası (%s): %s", CONFIG_PATH, e)
        sys.exit(1)
    if not state["admin_ids"]:
        log.warning("config.json > admins boş; DM komutları kapalı. Kendi kullanıcı ID'ni ya da e-postanı ekle.")
    load_state()
    catch_up(app.client)

    handler = SocketModeHandler(app, APP_TOKEN)
    state["handler"] = handler
    handler.connect()
    log.info("Etiket Köprüsü çalışıyor (Socket Mode). Botu kanala eklemeyi unutma: /invite @Etiket Köprüsü")
    disconnected_since = None
    while True:
        time.sleep(HEARTBEAT_SECONDS)
        if is_connected():
            disconnected_since = None
        else:
            disconnected_since = disconnected_since or time.time()
            gap = int(time.time() - disconnected_since)
            log.warning("Slack bağlantısı yok (%d sn).", gap)
            if gap >= WATCHDOG_SECONDS:
                log.error("Bağlantı %d sn'dir kurulamadı; çıkılıyor, servis yeniden başlatsın.", gap)
                save_state()
                sys.exit(3)
        save_state()


if __name__ == "__main__":
    main()
