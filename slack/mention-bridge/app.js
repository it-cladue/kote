'use strict';
// Etiket Köprüsü: Slack Connect kanalında düz metin "@petra" görünce thread'e gerçek
// <!subteam^S…|@petra> (ve/veya <@U…>) mention'ı ile yanıt yazar. @petra'nın olduğu workspace'e kurulur.
//
//   $env:SLACK_BOT_TOKEN = "xoxb-..."   # OAuth & Permissions > Bot User OAuth Token
//   $env:SLACK_APP_TOKEN = "xapp-..."   # Basic Information > App-Level Tokens (connections:write)
//   npm start
//
// Ayarlar: config.json (config.example.json'dan kopyala). Dosya değişince bot yeniden başlatmadan alır.

const path = require('path');
const { App, LogLevel } = require('@slack/bolt');
const { makeConfigLoader, findKeywords, mentionsFor, buildReply } = require('./lib/bridge');

const botToken = process.env.SLACK_BOT_TOKEN;
const appToken = process.env.SLACK_APP_TOKEN;
if (!botToken || !appToken) {
  console.error('SLACK_BOT_TOKEN (xoxb-...) ve SLACK_APP_TOKEN (xapp-...) ortam değişkenleri gerekli.');
  process.exit(1);
}
const configPath = process.env.BRIDGE_CONFIG || path.join(__dirname, 'config.json');
const loadConfig = makeConfigLoader(configPath);

const app = new App({
  token: botToken,
  appToken,
  socketMode: true,
  logLevel: process.env.BRIDGE_DEBUG ? LogLevel.DEBUG : LogLevel.INFO,
});

let config   = null;
let resolved = { usergroups: {}, users: {} };   // handle -> S…, email -> U…
let resolvedAt = 0;
const RESOLVE_TTL_MS = 15 * 60 * 1000;          // yeni grup/kişi eklenirse en geç 15 dk'da görülür

// config'deki handle ve e-postaları Slack ID'lerine çevirir. Bulunamayanlar loglanır, bot düşmez.
async function resolveTargets(client, logger) {
  const groups = {};
  const list = await client.usergroups.list({ include_disabled: false });
  for (const g of list.usergroups || []) groups[g.handle.toLowerCase()] = g.id;

  const users = { ...resolved.users };
  for (const targets of Object.values(config.keywords)) {
    for (const t of targets) {
      if (t.type === 'usergroup' && !groups[t.handle]) {
        logger.warn(`@${t.handle} diye bir user group bu workspace'te yok (ya da devre dışı); atlanıyor.`);
      }
      if (t.type === 'email' && !users[t.email]) {
        try {
          const r = await client.users.lookupByEmail({ email: t.email });
          users[t.email] = r.user.id;
        } catch (e) {
          logger.warn(`${t.email} bu workspace'te bulunamadı (${e.data?.error || e.message}); atlanıyor.`);
        }
      }
    }
  }
  resolved   = { usergroups: groups, users };
  resolvedAt = Date.now();
  logger.info(`Hedefler çözüldü: ${Object.keys(groups).length} user group, ${Object.keys(users).length} kişi.`);
}

async function ensureFresh(client, logger) {
  const { config: c, changed } = loadConfig();
  config = c;
  if (changed) logger.info(`config yüklendi: ${Object.keys(config.keywords).map((k) => '@' + k).join(', ')}`);
  if (changed || Date.now() - resolvedAt > RESOLVE_TTL_MS) await resolveTargets(client, logger);
}

// Aynı mesajı iki kez işlememek için (Slack nadiren aynı event'i tekrar yollar).
const seen = new Map();
function alreadySeen(key) {
  if (seen.has(key)) return true;
  seen.set(key, Date.now());
  if (seen.size > 1000) {
    const cutoff = Date.now() - 10 * 60 * 1000;
    for (const [k, t] of seen) if (t < cutoff) seen.delete(k);
  }
  return false;
}

app.event('message', async ({ event, client, logger }) => {
  // Sadece yeni, insan yazımı mesajlar. Düzenleme/silme/kanal olayları ve botlar (kendimiz dahil) atlanır.
  if (event.subtype && !['file_share', 'thread_broadcast'].includes(event.subtype)) return;
  if (event.bot_id || !event.user) return;
  if (alreadySeen(`${event.channel}:${event.ts}`)) return;

  try {
    await ensureFresh(client, logger);
  } catch (e) {
    logger.error(`config okunamadı: ${e.message}`);
    return;
  }
  if (config.channels.size && !config.channels.has(event.channel)) return;

  const hits = findKeywords(event.text, Object.keys(config.keywords), { requireAt: config.requireAt });
  if (!hits.length) return;

  const mentions = mentionsFor(hits, config, resolved);
  if (!mentions.length) {
    logger.warn(`"${hits.join(', ')}" eşleşti ama çözülebilen hedef yok (grup/kişi bulunamadı).`);
    return;
  }

  const params = { channel: event.channel, text: buildReply(config.replyTemplate, mentions, event.user) };
  if (config.replyMode === 'thread') params.thread_ts = event.thread_ts || event.ts;
  await client.chat.postMessage(params);
  logger.info(`${event.channel} ${event.ts}: @${hits.join(', @')} -> ${mentions.length} mention gönderildi.`);
});

(async () => {
  const me = await app.client.auth.test({ token: botToken });
  console.log(`Workspace: ${me.team} (${me.team_id})  bot: ${me.user}`);
  try {
    await ensureFresh(app.client, app.logger);
  } catch (e) {
    console.error(`config hatası (${configPath}): ${e.message}`);
    process.exit(1);
  }
  await app.start();
  console.log('Etiket Köprüsü çalışıyor (Socket Mode). Botu kanala eklemeyi unutma: /invite @Etiket Köprüsü');
})().catch((e) => {
  console.error(`Başlatılamadı: ${e.data?.error || e.message}`);
  process.exit(1);
});
