'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {
  stripSlackTokens, findKeywords, parseTarget, normalizeConfig, mentionsFor, buildReply,
} = require('../lib/bridge');

const KW = ['petra', 'kote', 'fransa', 'paris'];

test('düz metin @etiket yakalanır, büyük/küçük harf ve Türkçe ek fark etmez', () => {
  assert.deepEqual(findKeywords('Merhaba @petra bakar mısınız', KW), ['petra']);
  assert.deepEqual(findKeywords('@Petra acil', KW), ['petra']);
  assert.deepEqual(findKeywords("@petra'ya iletildi", KW), ['petra']);
  assert.deepEqual(findKeywords('(@petra) ve @kote.', KW), ['petra', 'kote']);
  assert.deepEqual(findKeywords('@paris\n@fransa', KW), ['fransa', 'paris']);
});

test('yanlış pozitifler: bitişik yazım, e-posta, tire, @ olmadan', () => {
  assert.deepEqual(findKeywords('@petrax', KW), []);
  assert.deepEqual(findKeywords('ali@petra.com', KW), []);
  assert.deepEqual(findKeywords('@petra-2', KW), []);
  assert.deepEqual(findKeywords('petra bugün yok', KW), []);
  assert.deepEqual(findKeywords('', KW), []);
  assert.deepEqual(findKeywords(undefined, KW), []);
});

test('gerçek Slack mention/link token\'ları eşleşmez (çift bildirim önlenir)', () => {
  assert.equal(stripSlackTokens('<!subteam^S123|@petra> bak').trim(), 'bak');
  assert.deepEqual(findKeywords('<!subteam^S123|@petra> bakar mısın', KW), []);
  assert.deepEqual(findKeywords('<@U123> <#C1|petra> <https://x.y/@petra>', KW), []);
  assert.deepEqual(findKeywords('<!subteam^S123|@petra> ayrıca @kote', KW), ['kote']);
});

test('require_at=false ile @ olmadan da yakalar', () => {
  assert.deepEqual(findKeywords('petra bakar mı', KW, { requireAt: false }), ['petra']);
  assert.deepEqual(findKeywords('@petra bakar mı', KW, { requireAt: false }), ['petra']);
});

test('hedef türleri: handle / @handle / e-posta / kullanıcı ID', () => {
  assert.deepEqual(parseTarget('petra', 'k'),  { type: 'usergroup', handle: 'petra' });
  assert.deepEqual(parseTarget('@Petra', 'k'), { type: 'usergroup', handle: 'petra' });
  assert.deepEqual(parseTarget('Ali@Firma.com', 'k'), { type: 'email', email: 'ali@firma.com' });
  assert.deepEqual(parseTarget('U0123ABCD', 'k'), { type: 'user', id: 'U0123ABCD' });
  assert.throws(() => parseTarget('', 'k'), /boş/);
  assert.throws(() => parseTarget('a b', 'k'), /geçerli/);
});

test('config: string, liste ve birden fazla keyword; notlar atlanır', () => {
  const c = normalizeConfig({
    keywords: {
      _not: 'yok sayılır',
      petra: 'petra',
      kote: ['kote', 'mehmet@firma.com'],
      '@Fransa': ['ali@firma.com', 'U0123ABCD'],
    },
    channels: ['C1'],
    reply_mode: 'channel',
    require_at: false,
  });
  assert.deepEqual(Object.keys(c.keywords), ['petra', 'kote', 'fransa']);
  assert.equal(c.keywords.kote.length, 2);
  assert.equal(c.keywords.fransa[1].type, 'user');
  assert.ok(c.channels.has('C1'));
  assert.equal(c.replyMode, 'channel');
  assert.equal(c.requireAt, false);
  assert.match(c.replyTemplate, /\{mentions\}/);
});

test('config: hatalı girişler anlaşılır hata verir', () => {
  assert.throws(() => normalizeConfig({}), /keywords/);
  assert.throws(() => normalizeConfig({ keywords: {} }), /hiç keyword/);
  assert.throws(() => normalizeConfig({ keywords: { petra: [] } }), /en az bir hedef/);
  assert.throws(() => normalizeConfig({ keywords: { petra: 'petra' }, reply_mode: 'dm' }), /reply_mode/);
});

test('mention üretimi: çözülemeyen hedef atlanır, tekrar yok', () => {
  const c = normalizeConfig({ keywords: { petra: ['petra', 'ali@firma.com'], kote: ['petra', 'U0123ABCD'] } });
  const resolved = { usergroups: { petra: 'S111' }, users: { 'ali@firma.com': 'U222' } };
  assert.deepEqual(mentionsFor(['petra'], c, resolved), ['<!subteam^S111|@petra>', '<@U222>']);
  assert.deepEqual(mentionsFor(['petra', 'kote'], c, resolved), ['<!subteam^S111|@petra>', '<@U222>', '<@U0123ABCD>']);
  assert.deepEqual(mentionsFor(['kote'], c, { usergroups: {}, users: {} }), ['<@U0123ABCD>']);
});

test('yanıt şablonu', () => {
  assert.equal(buildReply('{mentions} {author} sizi etiketledi.', ['<!subteam^S1|@petra>'], 'U9'),
    '<!subteam^S1|@petra> <@U9> sizi etiketledi.');
  assert.equal(buildReply('{mentions} {author} sizi etiketledi.', ['<@U1>'], undefined),
    '<@U1> sizi etiketledi.');
});
