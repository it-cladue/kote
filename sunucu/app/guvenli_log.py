"""Log ve geçmiş gösteriminde sırları saklamayan güvenli, sınırlı serileştirme."""
import json
import os
import re

_SENSITIVE = re.compile(r'(sifre|password|passwd|token|secret|api.?key|authorization|cookie|csrf|session.?key)', re.I)
_BOT_KEY = re.compile(r'(?:bot)?\d{6,}:[A-Za-z0-9_-]{20,}')
_FIELDS = re.compile(r'''(?i)((?:access_token|telegram_token|gyazo_token|bot_password|admin_password|password|sifre|authorization|api_key|secret)\s*[=:]\s*["']?)[^\s&"',}\]]+''')
_HASH = re.compile(r'(?:scrypt|pbkdf2):[A-Za-z0-9_$:./=+\-]+')


def text(value):
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str('' if value is None else value))
    value = _BOT_KEY.sub('[GİZLİ]', value)
    value = _FIELDS.sub(lambda m: m.group(1) + '[GİZLİ]', value)
    value = _HASH.sub('[PAROLA HASHİ]', value)
    for key in ('TELEGRAM_TOKEN', 'GYAZO_TOKEN', 'BOT_PASSWORD', 'ADMIN_PASSWORD', 'SESSION_SECRET'):
        secret = os.environ.get(key)
        if secret:
            value = value.replace(secret, '[GİZLİ]')
    return value[:4000]


def temizle(value, depth=0):
    if depth > 5:
        return '[DERİNLİK SINIRI]'
    if isinstance(value, dict):
        return {str(k)[:80]: '[GİZLİ]' if _SENSITIVE.search(str(k)) else temizle(v, depth + 1)
                for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [temizle(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            return text(value)
        if isinstance(decoded, (dict, list)):
            return temizle(decoded, depth + 1)
        return text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return text(value)


def serialize(value):
    if value is None:
        return None
    cleaned = temizle(value)
    return (json.dumps(cleaned, ensure_ascii=False) if isinstance(cleaned, (dict, list)) else text(cleaned))[:4000]


def log_row(row):
    result = dict(row)
    for key in ('eski', 'yeni', 'aciklama'):
        if key in result:
            result[key] = serialize(result[key])
    return result
