import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatTimestamp, renderMessageContent, type LarkMessage } from '../lark.js';
import { parseTime } from '../server.js';

function message(msgType: string, content: unknown, extra: Partial<LarkMessage> = {}): LarkMessage {
  return {
    message_id: 'om_test',
    msg_type: msgType,
    body: { content: JSON.stringify(content) },
    ...extra
  };
}

test('renders plain text', () => {
  assert.equal(renderMessageContent(message('text', { text: 'ペペロンチーノの量を見直したい' })), 'ペペロンチーノの量を見直したい');
});

test('substitutes @-mention placeholders with display names', () => {
  const msg = message('text', { text: '@_user_1 確認お願いします' }, {
    mentions: [{ key: '@_user_1', id: 'ou_abc', name: '榊原' }]
  });
  assert.equal(renderMessageContent(msg), '@榊原 確認お願いします');
});

test('falls back to the mention id when no name is present', () => {
  const msg = message('text', { text: 'cc @_user_1' }, { mentions: [{ key: '@_user_1', id: 'ou_abc' }] });
  assert.equal(renderMessageContent(msg), 'cc @ou_abc');
});

test('flattens rich text posts including links and mentions', () => {
  const msg = message('post', {
    ja_jp: {
      title: '8月シフト',
      content: [
        [
          { tag: 'text', text: '確定版は ' },
          { tag: 'a', text: 'こちら', href: 'https://example.com/shift' }
        ],
        [{ tag: 'at', user_name: '若杉' }]
      ]
    }
  });
  assert.equal(renderMessageContent(msg), '8月シフト\n確定版は こちら (https://example.com/shift)\n@若杉');
});

test('picks a locale that actually carries content', () => {
  const msg = message('post', {
    zh_cn: {},
    en_us: { title: 'Menu', content: [[{ tag: 'text', text: 'pasta' }]] }
  });
  assert.equal(renderMessageContent(msg), 'Menu\npasta');
});

test('summarises non-text message types instead of dropping them', () => {
  assert.equal(renderMessageContent(message('image', { image_key: 'img_1' })), '[image image_key=img_1]');
  assert.equal(renderMessageContent(message('file', { file_name: '利益表.xlsx', file_key: 'f_1' })), '[file 利益表.xlsx file_key=f_1]');
  assert.match(renderMessageContent(message('unknown_type', { foo: 1 })), /^\[unknown_type\]/);
});

test('extracts readable text from interactive cards', () => {
  const msg = message('interactive', {
    elements: [{ tag: 'div', text: { tag: 'lark_md', content: '日報が提出されました' } }]
  });
  assert.equal(renderMessageContent(msg), '[card] 日報が提出されました');
});

test('returns the raw body when the content is not valid JSON', () => {
  const msg: LarkMessage = { message_id: 'om_1', msg_type: 'text', body: { content: 'not json' } };
  assert.equal(renderMessageContent(msg), 'not json');
});

test('formats timestamps in the requested time zone', () => {
  // 2026-07-21T00:00:00Z is 09:00 the same day in Tokyo.
  assert.equal(formatTimestamp('1784592000000', 'Asia/Tokyo'), '2026-07-21 09:00');
  assert.equal(formatTimestamp('1784592000000', 'UTC'), '2026-07-21 00:00');
  assert.equal(formatTimestamp(undefined, 'UTC'), 'unknown time');
});

test('parses the accepted time formats', () => {
  assert.equal(parseTime('1784592000', 'start_time'), 1784592000);
  assert.equal(parseTime('1784592000000', 'start_time'), 1784592000);
  assert.equal(parseTime('2026-07-21T00:00:00Z', 'start_time'), 1784592000);
  // A bare date resolves against LARK_TIME_ZONE (Asia/Tokyo by default), so
  // 2026-07-21 local midnight is 2026-07-20T15:00Z.
  assert.equal(parseTime('2026-07-21', 'start_time'), 1784559600);
});

test('rejects unparseable times with an actionable message', () => {
  assert.throws(() => parseTime('last tuesday', 'start_time'), /Could not parse start_time/);
});
