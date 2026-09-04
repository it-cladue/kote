'use strict';
// Slack'e bağlanmayan saf mantık: config okuma/doğrulama, metinde etiket arama, yanıt metni.
// app.js bunları kullanır; test/ altında Slack olmadan test edilir.

const fs = require('fs');

const EMAIL_RE   = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const USER_ID_RE = /^[UW][A-Z0-9]{8,}$/;

// Slack'in kendi token'larını (<@U..>, <!subteam^S..|@petra>, <#C..|kanal>, <http://..>) metinden atar.
// Atılmazsa gerçek bir @petra mention'ının içindeki "@petra" da yakalanır ve ekip iki kez bildirim alır.
function stripSlackTokens(text) {
  return String(text || '').replace(/<[^>]*>/g, ' ');
}

// Metinde geçen keyword'leri config'deki sırayla, tekrarsız döndürür.
// "@petra", "@Petra", "@petra'ya", "@petra." eşleşir; "@petrax", "x@petra", "@petra-2" eşleşmez.
function findKeywords(text, keywords, { requireAt = true } = {}) {
  const clean = stripSlackTokens(text).toLowerCase();
  const found = [];
  for (const kw of keywords) {
    const esc = kw.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const at  = requireAt ? '@' : '@?';
    const re  = new RegExp(`(^|[^\\p{L}\\p{N}_@])${at}${esc}(?![\\p{L}\\p{N}_-])`, 'u');
    if (re.test(clean)) found.push(kw);
  }
  return found;
}

// "petra" | "@petra" -> usergroup, "ali@firma.com" -> email, "U0123ABCD" -> user id
function parseTarget(raw, keyword) {
  if (typeof raw !== 'string' || !raw.trim()) {
    throw new Error(`config: "${keyword}" altında boş ya da string olmayan hedef var.`);
  }
  const s = raw.trim();
  if (EMAIL_RE.test(s))   return { type: 'email', email: s.toLowerCase() };
  if (USER_ID_RE.test(s)) return { type: 'user', id: s };
  const handle = s.replace(/^@/, '');
  if (!/^[\p{L}\p{N}_.-]+$/u.test(handle)) {
    throw new Error(`config: "${keyword}" altındaki "${raw}" ne e-posta, ne kullanıcı ID'si, ne de geçerli bir user group handle'ı.`);
  }
  return { type: 'usergroup', handle: handle.toLowerCase() };
}

function normalizeConfig(raw) {
  if (!raw || typeof raw !== 'object' || !raw.keywords || typeof raw.keywords !== 'object') {
    throw new Error('config: "keywords" nesnesi zorunlu. Örnek için config.example.json dosyasına bak.');
  }
  const keywords = {};
  for (const [kw, value] of Object.entries(raw.keywords)) {
    if (kw.startsWith('_')) continue;                      // "_aciklama" gibi notlar
    const key = kw.trim().replace(/^@/, '').toLowerCase();
    if (!key) throw new Error('config: boş keyword.');
    const list = Array.isArray(value) ? value : [value];
    if (!list.length) throw new Error(`config: "${kw}" için en az bir hedef gerekli.`);
    keywords[key] = list.map((t) => parseTarget(t, kw));
  }
  if (!Object.keys(keywords).length) throw new Error('config: hiç keyword tanımlı değil.');

  const replyMode = raw.reply_mode || 'thread';
  if (!['thread', 'channel'].includes(replyMode)) {
    throw new Error(`config: reply_mode "thread" ya da "channel" olmalı, "${raw.reply_mode}" değil.`);
  }
  return {
    keywords,
    channels:      new Set(Array.isArray(raw.channels) ? raw.channels : []),
    replyMode,
    requireAt:     raw.require_at !== false,
    replyTemplate: typeof raw.reply_template === 'string' && raw.reply_template.includes('{mentions}')
                     ? raw.reply_template
                     : '{mentions} {author} sizi etiketledi.',
  };
}

// Dosya değiştiyse yeniden okur (mtime'a bakar). Dönen: { config, changed }.
function makeConfigLoader(filePath) {
  let cached = null;
  let mtimeMs = -1;
  return function load() {
    const stat = fs.statSync(filePath);
    if (cached && stat.mtimeMs === mtimeMs) return { config: cached, changed: false };
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    cached  = normalizeConfig(parsed);
    mtimeMs = stat.mtimeMs;
    return { config: cached, changed: true };
  };
}

function formatMention(target, resolved) {
  if (target.type === 'usergroup') {
    const id = resolved.usergroups[target.handle];
    return id ? `<!subteam^${id}|@${target.handle}>` : null;
  }
  if (target.type === 'email') {
    const id = resolved.users[target.email];
    return id ? `<@${id}>` : null;
  }
  return `<@${target.id}>`;
}

// Eşleşen keyword'lerin hedeflerini gerçek mention string'lerine çevirir (tekrarsız).
function mentionsFor(hits, config, resolved) {
  const out = [];
  for (const kw of hits) {
    for (const t of config.keywords[kw] || []) {
      const m = formatMention(t, resolved);
      if (m && !out.includes(m)) out.push(m);
    }
  }
  return out;
}

function buildReply(template, mentions, authorId) {
  return template
    .replace('{mentions}', mentions.join(' '))
    .replace('{author}', authorId ? `<@${authorId}>` : '')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

module.exports = {
  stripSlackTokens, findKeywords, parseTarget, normalizeConfig,
  makeConfigLoader, formatMention, mentionsFor, buildReply,
};
