const {test} = require('node:test');
const assert = require('node:assert/strict');
const {normalize, searchArticles, pickRandom, randomController} = require('../web/site.js');

test('search matches title, reading, body and metadata with normalized numbers and kana', () => {
  const rows = [
    {route: 'a', search_text: '11:11:11 １１１１１１ あふりくてっど 本文にだけある語 ホラー SF 監督A'},
    {route: 'b', search_text: '別作品 コメディ 監督B'},
  ];
  for (const query of ['111111', 'アフリクテッド', '本文にだけある語', 'ホラー ＳＦ', '監督a']) {
    assert.deepEqual(searchArticles(rows, query).map(row => row.route), ['a']);
  }
  assert.deepEqual(searchArticles(rows, 'ホラー コメディ'), []);
  assert.deepEqual(searchArticles(rows, '<script>'), []);
  assert.deepEqual(searchArticles(rows, '　'), []);
  assert.equal(normalize(' ＡＢＣ　カナ１２ '), 'abcかな12');
});

test('random picks two distinct articles and excludes latest and previous picks', () => {
  const rows = Array.from({length: 12}, (_, i) => ({route: String(i), latest: i < 4}));
  let previous = [];
  for (let i = 0; i < 50; i++) {
    const picked = pickRandom(rows, previous);
    assert.equal(picked.length, 2);
    assert.equal(new Set(picked.map(row => row.route)).size, 2);
    assert.ok(picked.every(row => !row.latest && !previous.includes(row.route)));
    previous = picked.map(row => row.route);
  }
});

test('random selection handles zero, one, two and three eligible articles without loops', () => {
  assert.deepEqual(pickRandom([{latest: true}]), []);
  for (const count of [1, 2, 3]) {
    const rows = Array.from({length: count}, (_, i) => ({route: String(i)}));
    const first = pickRandom(rows, [], 2, () => 0);
    const second = pickRandom(rows, first.map(row => row.route), 2, () => 0);
    assert.equal(second.length, Math.min(count, 2));
    assert.equal(new Set(second.map(row => row.route)).size, second.length);
    if (count === 3) assert.ok(second.some(row => !first.includes(row)));
  }
});

test('random button replaces both cards in place and preserves full generated short text', () => {
  const rows = Array.from({length: 10}, (_, i) => ({route: String(i), latest: i < 4,
    title: '感想' + i, card_html: '<article data-route="' + i + '">' + ('長い短評。'.repeat(80)) + '</article>'}));
  const cards = {innerHTML: ''};
  const button = {hidden: true, addEventListener(event, listener) { assert.equal(event, 'click'); this.click = listener; }};
  const status = {textContent: ''};
  randomController(rows, cards, button, status);
  const before = cards.innerHTML;
  assert.equal(button.hidden, false);
  assert.equal(button.disabled, false);
  button.click();
  assert.notEqual(cards.innerHTML, before);
  assert.equal((cards.innerHTML.match(/<article /g) || []).length, 2);
  assert.ok(cards.innerHTML.includes('長い短評。'.repeat(80)));
  assert.ok(status.textContent.endsWith('を表示しました。'));
});
