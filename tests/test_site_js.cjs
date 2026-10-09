const {test} = require('node:test');
const assert = require('node:assert/strict');
const {normalize, searchArticles, pickRandom, randomController, groupIndexEntries} = require('../web/site.js');

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

const indexRow = overrides => ({title: '映画', reading: null, reading_label: '読み未登録・要確認',
  year: null, genres: [], posted: '2000-01-01T12:00:00', file: 'a.md', ...overrides});

test('index name sort preserves confirmed gojuon order and newest review tie-breaking', () => {
  const rows = [
    indexRow({title:'未確定', reading_label:'読み未登録・要確認'}),
    indexRow({title:'確定B', reading:['かた','かた'], reading_label:'か'}),
    indexRow({title:'確定A旧', reading:['かい','がい'], reading_label:'か', posted:'1999-01-01T12:00:00'}),
    indexRow({title:'確定A新', reading:['かい','がい'], reading_label:'か', posted:'2024-01-01T12:00:00'}),
  ];
  const groups = groupIndexEntries(rows, 'name');
  assert.deepEqual(groups.map(group=>group.label), ['か','読み未登録・要確認']);
  assert.deepEqual(groups.flatMap(group=>group.entries.map(row=>row.title)), ['確定A新','確定A旧','確定B','未確定']);
  assert.deepEqual(groupIndexEntries([], 'name'), []);
});

test('index year sort uses movie year, preserves membership and places unregistered years last', () => {
  const rows = [indexRow({year:1969,posted:'2026-01-01T12:00:00'}), indexRow({year:null}),
    indexRow({year:2024,posted:'2000-01-01T12:00:00'}),indexRow({year:2009})];
  const groups = groupIndexEntries(rows, 'year');
  assert.deepEqual(groups.map(group=>group.label), ['2024年','2009年','1969年','年未登録']);
  assert.equal(groups.reduce((sum,group)=>sum+group.entries.length,0), rows.length);
});

test('index genre sort retains all memberships without duplicate genre labels and leaves missing metadata last', () => {
  const rows = [indexRow({title:'複数', genres:['ホラー','SF','ホラー']}),indexRow({title:'空欄'})];
  const groups = groupIndexEntries(rows, 'genre');
  assert.equal(groups.at(-1).label, 'ジャンル未登録');
  assert.equal(groups.find(group=>group.label==='ホラー').entries.length, 1);
  assert.equal(groups.find(group=>group.label==='SF').entries[0].title, '複数');
  assert.equal(groups.find(group=>group.label==='ジャンル未登録').entries[0].title, '空欄');
  assert.deepEqual(rows[0].genres, ['ホラー','SF','ホラー']);
});
