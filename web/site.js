(function () {
  'use strict';

  function normalize(value) {
    return String(value).normalize('NFKC').toLowerCase()
      .replace(/[ァ-ヶ]/g, character => String.fromCharCode(character.charCodeAt(0) - 0x60))
      .replace(/\s+/g, '');
  }

  function searchArticles(articles, query) {
    const words = String(query).normalize('NFKC').trim().split(/\s+/).filter(Boolean).map(normalize);
    if (!words.length) return [];
    return articles.filter(article => words.every(word => normalize(article.search_text).includes(word)));
  }

  function pickRandom(articles, previous = [], count = 2, draw = Math.random) {
    const pool = articles.filter(article => !article.latest);
    const old = new Set(previous);
    const fresh = pool.filter(article => !old.has(article.route));
    const repeat = pool.filter(article => old.has(article.route));
    const picked = [];
    for (const candidates of [fresh, repeat]) {
      while (picked.length < count && candidates.length) {
        const index = Math.min(candidates.length - 1, Math.floor(draw() * candidates.length));
        picked.push(candidates.splice(index, 1)[0]);
      }
    }
    return picked;
  }

  function randomController(articles, cards, button, status) {
    let previous = [];
    function update() {
      const picked = pickRandom(articles, previous);
      cards.innerHTML = picked.map(article => article.card_html).join('');
      previous = picked.map(article => article.route);
      status.textContent = picked.length ? picked.map(article => article.title).join('、') + 'を表示しました。' : 'ランダム表示できる感想はまだありません。';
    }
    button.hidden = false;
    button.disabled = articles.filter(article => !article.latest).length <= 2;
    button.addEventListener('click', update);
    update();
    return update;
  }

  function compareText(a, b) { return a < b ? -1 : a > b ? 1 : 0; }

  function compareNames(a, b) {
    if (Boolean(a.reading) !== Boolean(b.reading)) return a.reading ? -1 : 1;
    const left = a.reading || [a.title, ''];
    const right = b.reading || [b.title, ''];
    return compareText(left[0], right[0]) || compareText(left[1], right[1]) ||
      compareText(b.posted, a.posted) || compareText(a.title, b.title) || compareText(a.file, b.file);
  }

  function groupIndexEntries(entries, mode) {
    const groups = new Map();
    for (const entry of entries) {
      const labels = mode === 'year' ? [entry.year ? entry.year + '年' : '年未登録'] :
        mode === 'genre' ? (entry.genres.length ? Array.from(new Set(entry.genres)) : ['ジャンル未登録']) : [entry.reading_label];
      for (const label of labels) {
        if (!groups.has(label)) groups.set(label, []);
        groups.get(label).push(entry);
      }
    }
    for (const group of groups.values()) group.sort(compareNames);
    const result = Array.from(groups, ([label, rows]) => ({label, entries: rows}));
    if (mode === 'year') result.sort((a, b) => (a.label === '年未登録') - (b.label === '年未登録') ||
      Number.parseInt(b.label, 10) - Number.parseInt(a.label, 10));
    else if (mode === 'genre') {
      const collator = new Intl.Collator('ja');
      result.sort((a, b) => (a.label === 'ジャンル未登録') - (b.label === 'ジャンル未登録') || collator.compare(a.label, b.label));
    } else result.sort((a, b) => compareNames(a.entries[0], b.entries[0]));
    return result;
  }

  function indexController(root) {
    const select = root.querySelector('.index-sort');
    const target = root.querySelector('.index-groups');
    const status = root.querySelector('.index-sort-status');
    const rows = Array.from(target.querySelectorAll('li[data-index-entry]'));
    const entries = rows.map((row, index) => ({...JSON.parse(row.dataset.indexEntry), index}));
    const owner = root.ownerDocument;
    function update() {
      const groups = groupIndexEntries(entries, select.value);
      const fragment = owner.createDocumentFragment();
      for (const group of groups) {
        const section = owner.createElement('section');
        section.className = 'index-section';
        const heading = owner.createElement('h2');
        heading.textContent = group.label;
        const count = owner.createElement('span');
        count.className = 'count';
        count.textContent = group.entries.length.toLocaleString('ja-JP') + '件';
        heading.append(count);
        const list = owner.createElement('ul');
        list.className = 'article-list';
        for (const entry of group.entries) list.append(rows[entry.index].cloneNode(true));
        section.append(heading, list);
        fragment.append(section);
      }
      if (!groups.length) {
        const empty = owner.createElement('p'); empty.className = 'empty'; empty.textContent = '記事はまだありません。'; fragment.append(empty);
      }
      target.replaceChildren(fragment);
      const label = {name: '名前順', year: '年代順', genre: 'ジャンル順'}[select.value];
      const known = entries.filter(entry => entry.reading).length;
      status.textContent = entries.length.toLocaleString('ja-JP') + '件（読み確定 ' + known.toLocaleString('ja-JP') +
        '件・未確定 ' + (entries.length - known).toLocaleString('ja-JP') + '件）を' + label + 'で表示しています。' +
        (select.value === 'year' ? '映画の公開年が新しい順です。' : '') +
        (select.value === 'genre' ? '複数ジャンルの記事はそれぞれに掲載します。' : '');
    }
    root.querySelector('.index-sort-controls').hidden = false;
    select.addEventListener('change', update);
    return update;
  }

  const api = {normalize, searchArticles, pickRandom, randomController, compareNames, groupIndexEntries, indexController};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  document.documentElement.classList.add('js');

  const sidebar = document.getElementById('site-sidebar');
  const toggle = document.querySelector('.sidebar-toggle');
  const backdrop = document.querySelector('.sidebar-backdrop');
  const mobile = window.matchMedia('(max-width: 860px)');
  function closeSidebar() {
    document.body.classList.remove('sidebar-open');
    toggle.setAttribute('aria-expanded', 'false');
    backdrop.hidden = true;
  }
  function toggleSidebar() {
    const open = !document.body.classList.contains('sidebar-open');
    document.body.classList.toggle('sidebar-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    backdrop.hidden = !open;
    if (open) sidebar.querySelector('input').focus();
  }
  toggle.addEventListener('click', toggleSidebar);
  backdrop.addEventListener('click', () => { closeSidebar(); toggle.focus(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
      closeSidebar(); toggle.focus();
    }
  });
  mobile.addEventListener('change', closeSidebar);

  for (const root of document.querySelectorAll('.sortable-index')) indexController(root);

  const articles = window.movieLogArticles || [];
  const cards = document.getElementById('random-cards');
  if (cards) randomController(articles, cards, document.getElementById('random-button'), document.getElementById('random-status'));

  const results = document.getElementById('search-results');
  if (!results) return;
  const query = new URLSearchParams(window.location.search).get('q') || '';
  document.getElementById('site-search').value = query;
  const summary = document.getElementById('search-summary');
  const more = document.getElementById('search-more');
  const matches = searchArticles(articles, query);
  const base = new URL(document.body.dataset.siteRoot, window.location.href);
  let shown = 0;
  function appendResults() {
    const end = Math.min(shown + 50, matches.length);
    for (const article of matches.slice(shown, end)) {
      const item = document.createElement('li');
      const title = document.createElement('h2');
      const link = document.createElement('a');
      link.href = new URL(article.route, base).href;
      link.textContent = article.title;
      title.append(link);
      const meta = document.createElement('p');
      meta.className = 'search-meta';
      meta.textContent = [article.kind, article.date, article.rating].filter(Boolean).join('　');
      item.append(title, meta);
      if (article.short) {
        const short = document.createElement('p');
        short.className = 'short-review';
        short.textContent = article.short;
        item.append(short);
      }
      results.append(item);
    }
    shown = end;
    summary.textContent = query.trim() ? '「' + query + '」の検索結果：' + matches.length.toLocaleString('ja-JP') + '件（' + shown.toLocaleString('ja-JP') + '件表示）' : '左の検索窓に言葉を入れて検索してください。';
    more.hidden = shown >= matches.length;
  }
  more.addEventListener('click', appendResults);
  appendResults();
}());
