#!/usr/bin/env python3
"""Build the display layer from canonical Markdown; never modify source articles."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import posixpath
import random
import re
import shutil
import struct
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
import yaml

SITE_TITLE = "映画の感想を だらだら呟く"
SITE_URL = "https://tempp-kz.github.io/movielog/"
SITE_DESCRIPTION = "Temppの各所に分散していた映画ログまとめです。"
NAV = [("index.html", "トップ"), ("titles/index.html", "作品名順"),
       ("years/index.html", "公開年順"), ("genres/index.html", "ジャンル"),
       ("directors/index.html", "監督"), ("cast/index.html", "出演者"),
       ("essays/index.html", "エッセイ")]
TYPE_LABEL = {"review": "レビュー", "essay": "エッセイ"}
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)(.*)\Z", re.S)
HIRAGANA = re.compile(r"[ぁ-ゖゝゞー0-9０-９・\s、。！？…〜～「」『』（）()：:－-]+\Z")
NAME_GROUPS = [("a", "あ行", "あいうえお"), ("k", "か行", "かきくけこ"),
               ("s", "さ行", "さしすせそ"), ("t", "た行", "たちつてと"),
               ("n", "な行", "なにぬねの"), ("h", "は行", "はひふへほ"),
               ("m", "ま行", "まみむめも"), ("y", "や行", "やゆよ"),
               ("r", "ら行", "らりるれろ"), ("w", "わ行", "わゐゑをん"),
               ("number", "数字・英語", ""), ("unknown", "読み未登録・要確認", "")]
GENRE_ORDER = "アニメ|ドラマ|恋愛|ホラー|アート・コンテンポラリー|戦争|音楽|ミュージカル|スポーツ|SF|青春|コメディ|アクション|アドベンチャー・冒険|クライム|ショートフィルム・短編|ドキュメンタリー|スリラー|サスペンス|ファミリー|ファンタジー|ミステリー|ヤクザ・任侠|伝記|時代劇|西部劇|歴史|パニック|オムニバス|バイオレンス|ギャング・マフィア".split("|")
MARKER = "_build-report.json"
GENERATOR = "movielog-markdown-site-v1"


def optimized_count(root: Path, articles: list[Article]) -> int:
    """Count distinct articles whose user-approved movie attributes are applied."""
    by_file = {a.path.relative_to(root).as_posix(): a for a in articles}
    optimized = set()
    for record in sorted((root / "migration").glob("metadata-trial*.json")):
        data = json.loads(record.read_text(encoding="utf-8"))
        rows = data.get("outcomes", [])
        if not data.get("confirmed_count") or data.get("confirmed_count") != len(rows):
            continue
        for row in rows:
            article = by_file.get(row.get("file"))
            after = row.get("metadata_after", {})
            fields = ("release_year", "directors", "cast", "genres")
            if article and all(after.get(field) and article.data.get(field) == after[field] for field in fields):
                optimized.add(row["file"])
    return len(optimized)


def e(value: object) -> str:
    return escape(str(value), quote=True)


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:20]


def reading_key(reading: str) -> tuple[str, str]:
    # Gojuon compares voiced and small kana with their base kana first.
    reading = unicodedata.normalize("NFKC", reading)
    base = "".join(c for c in unicodedata.normalize("NFD", reading) if not unicodedata.combining(c))
    base = base.translate(str.maketrans("ぁぃぅぇぉっゃゅょゎゕゖ", "あいうえおつやゆよわかけ"))
    base = re.sub(r"[^ぁ-ゖゝゞー0-9]", "", base)
    vowels = {c: vowel for vowel, kana in (("あ", "あかさたなはまやらわ"), ("い", "いきしちにひみりゐ"),
              ("う", "うくすつぬふむゆる"), ("え", "えけせてねへめれゑ"), ("お", "おこそとのほもよろを")) for c in kana}
    normalized = ""
    for char in base:
        normalized += vowels.get(normalized[-1], "ー") if char == "ー" and normalized else char
    return normalized, reading


def reading_group(reading: str | None) -> str:
    key = reading_key(reading)[0] if reading else ""
    if key[:1].isdigit():
        return "number"
    for group, _, kana in NAME_GROUPS:
        if key and key[0] in kana:
            return group
    return "unknown"


def href(current: str, target: str) -> str:
    """Relative URLs also work after extracting the preview ZIP locally."""
    return quote(posixpath.relpath(target, posixpath.dirname(current) or "."), safe="/#")


def string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{field} は名前の配列で指定してください。")
    return list(dict.fromkeys(value))


@dataclass
class Film:
    data: dict
    key: str | None

    @property
    def title(self) -> str:
        return str(self.data.get("title") or "")

    @property
    def reading(self) -> str | None:
        if self.data.get("reading_status") == "要確認":
            return None
        return self.data.get("reading") or None


@dataclass
class Article:
    path: Path
    data: dict
    body: str
    posted: datetime
    route: str
    films: list[Film]

    @property
    def title(self) -> str:
        return self.data["title"]

    @property
    def kind(self) -> str:
        return self.data["type"]


def film_from(data: dict) -> Film:
    film = dict(data)
    for field in ("genres", "directors", "cast"):
        film[field] = string_list(data.get(field), field)
    reading = film.get("reading")
    if reading is not None and (not isinstance(reading, str) or not HIRAGANA.fullmatch(reading)):
        raise ValueError("reading は全文の読みをひらがな・数字で指定してください。")
    raw_id = data.get("filmarks_id")
    film_id = str(raw_id) if raw_id is not None else None
    if film_id and not re.fullmatch(r"\d+", film_id):
        raise ValueError("filmarks_id はFilmarks作品IDを指定してください。")
    film_url = data.get("filmarks_url")
    key = None
    if film_url:
        url = urlsplit(str(film_url))
        match = re.fullmatch(r"/movies/(\d+)/?", url.path)
        if url.hostname != "filmarks.com" or url.scheme not in ("http", "https") or not match:
            raise ValueError("filmarks_url はFilmarks作品ページのURLを指定してください。")
        if film_id and film_id != match[1]:
            raise ValueError("Filmarks作品IDと作品URLが一致しません。")
        key = "filmarks:" + match[1]
    if film_id:
        key = "filmarks:" + film_id
    year = film.get("release_year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int)):
        raise ValueError("release_year は年を整数で指定してください。")
    if year is None:
        # A known release date supplies its year directly, without filling the source field.
        release = film.get("release_date")
        if isinstance(release, date):
            film["release_year"] = release.year
        elif isinstance(release, str):
            try:
                film["release_year"] = date.fromisoformat(release).year
            except ValueError:
                pass
    return Film(film, key)


def load_articles(root: Path) -> list[Article]:
    articles = []
    for path in sorted((root / "content").rglob("*.md")):
        try:
            match = FRONTMATTER.fullmatch(path.read_text(encoding="utf-8-sig"))
            if not match:
                raise ValueError("YAML frontmatter がありません。")
            data = yaml.safe_load(match[1])
            if not isinstance(data, dict) or data.get("type") not in TYPE_LABEL:
                raise ValueError("type は review または essay を手動指定してください。")
            if not isinstance(data.get("title"), str) or not data["title"].strip():
                raise ValueError("title が空欄です。")
            synopsis = data.get("synopsis")
            if synopsis is not None and not isinstance(synopsis, str):
                raise ValueError("synopsis は短いあらすじを文字列で指定してください。")
            raw_date = data.get("review_date")
            if isinstance(raw_date, (datetime, date)):
                raw_date = raw_date.isoformat()
            posted = datetime.fromisoformat(str(raw_date))
            if posted.tzinfo is not None:
                raise ValueError("review_date はタイムゾーンを付けずに指定してください。")
            if data["type"] == "review":
                films = [film_from(data)]
            else:
                related = data.get("related_films") or []
                if not isinstance(related, list) or any(not isinstance(v, dict) for v in related):
                    raise ValueError("related_films は映画ごとのfrontmatter項目を持つ配列で指定してください。")
                films = [film_from(v) for v in related]
            route = "articles/" + digest(path.relative_to(root).as_posix()) + "/index.html"
            articles.append(Article(path, data, match[2], posted, route, films))
        except (ValueError, yaml.YAMLError) as error:
            raise ValueError(f"{path.relative_to(root)}: {error}") from error
    return sorted(articles, key=lambda a: (a.posted, a.path.name), reverse=True)


class Site:
    def __init__(self, root: Path, output: Path, articles: list[Article]):
        self.root, self.output, self.articles = root, output, articles
        self.by_path = {a.path.resolve(): a for a in articles}
        self.by_film: dict[str, list[Article]] = defaultdict(list)
        self.terms: dict[str, dict[str, list[Article]]] = {name: defaultdict(list) for name in ("genres", "directors", "cast")}
        self.pages = 0
        self.updated = datetime.now(timezone(timedelta(hours=9))).date()
        self.optimized = optimized_count(root, articles)
        self.random_candidates = articles[4:]
        self.initial_random = random.sample(self.random_candidates, min(2, len(self.random_candidates)))
        self.image_sizes = {}
        self.entries = [(a, f) for a in articles for f in a.films if f.title]
        self.name_groups = {group: [] for group, _, _ in NAME_GROUPS}
        self.years: dict[int, dict[str, Article]] = defaultdict(dict)
        for article, film in self.entries:
            self.name_groups[reading_group(film.reading)].append((article, film))
            if film.data.get("release_year") is not None:
                self.years[film.data["release_year"]][article.route] = article
        self.year_unknown = [a for a in articles if not any(f.data.get("release_year") is not None for f in a.films)]
        self.genre_unknown = [a for a in articles if not any(f.data["genres"] for f in a.films)]
        newest_year = max([self.updated.year, *self.years])
        self.display_years = list(range(newest_year, min(self.years, default=newest_year) - 1, -1))
        for article in articles:
            for key in dict.fromkeys(f.key for f in article.films if f.key):
                self.by_film[key].append(article)
            for field in self.terms:
                for name in dict.fromkeys(v for f in article.films for v in f.data[field]):
                    self.terms[field][name].append(article)
        self.markdown = MarkdownIt("commonmark", {"breaks": True, "html": False, "typographer": False}).enable("table")

    def sidebar(self, route: str, active: str) -> str:
        def link(target: str, label: str, count: int | None = None, folder: bool = False) -> str:
            current = ' aria-current="page"' if target == route else (' aria-current="location"' if target == active else '')
            icon = '<span class="folder-icon" aria-hidden="true"></span>' if folder else ''
            number = f'<span class="tree-count">{count:,}</span>' if count is not None else ''
            return f'<a href="{href(route, target)}"{current}>{icon}<span class="tree-label">{e(label)}</span>{number}</a>'

        branches = {
            "titles/index.html": [(f'titles/{group}/index.html', label, len(self.name_groups[group])) for group, label, _ in NAME_GROUPS],
            "years/index.html": [(f'years/{year}/index.html', f'{year}年', len(self.years.get(year, {}))) for year in self.display_years] + [('years/unknown/index.html', '年未登録', len(self.year_unknown))],
            "genres/index.html": [('genres/' + digest(name) + '/index.html', name, len(self.terms['genres'][name])) for name in sorted(self.terms['genres'])] + [('genres/unknown/index.html', 'ジャンル未登録', len(self.genre_unknown))],
        }
        nodes = []
        for target, label in NAV:
            node = link(target, label, folder=target != "index.html")
            if target in branches:
                opened = ' open' if active == target else ''
                children = ''.join('<li>' + link(path, name, count) + '</li>' for path, name, count in branches[target])
                nodes.append(f'<details class="nav-folder"{opened}><summary>{node}</summary><ul>{children}</ul></details>')
            else:
                nodes.append(f'<div class="nav-leaf">{node}</div>')
        return f'''<aside id="site-sidebar" class="site-sidebar" aria-label="映画ログのメニュー">
<form class="sidebar-search" action="{href(route, 'search/index.html')}" method="get" role="search"><label class="visually-hidden" for="site-search">映画ログを検索</label><input id="site-search" name="q" type="search" placeholder="映画ログを検索"><button type="submit">検索</button></form>
<nav class="tree-nav" aria-label="記事の索引">{''.join(nodes)}</nav>
<div class="sidebar-links"><a href="https://tempp-kz.github.io/tempp/">■架空都市神津wiki</a><a href="https://tempp-kz.github.io/pucopac/">■ぷ庫OPAC</a></div></aside>'''

    def write_page(self, route: str, title: str, content: str, active: str = "", description: str | None = None) -> None:
        home = route == "index.html"
        header = "" if home else f'<header class="site-header"><div class="header-inner"><a class="site-name" href="{href(route, "index.html")}">{SITE_TITLE}</a></div></header>'
        data_script = f'<script defer src="{href(route, "assets/article-data.js")}"></script>' if home or route == 'search/index.html' else ''
        page_title = title if home else title + " | " + SITE_TITLE
        page_description = re.sub(r"\s+", " ", description or SITE_DESCRIPTION).strip()[:200]
        card_image = SITE_URL + 'assets/x-card.png'
        social = f'''<meta name="description" content="{e(page_description)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{e(SITE_TITLE)}"><meta property="og:title" content="{e(page_title)}"><meta property="og:description" content="{e(page_description)}"><meta property="og:url" content="{SITE_URL + quote(route, safe='/')}">
<meta property="og:image" content="{card_image}"><meta property="og:image:type" content="image/png"><meta property="og:image:width" content="1280"><meta property="og:image:height" content="670"><meta property="og:image:alt" content="{e(SITE_TITLE)} ©Tempp">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{e(page_title)}"><meta name="twitter:description" content="{e(page_description)}"><meta name="twitter:image" content="{card_image}"><meta name="twitter:image:alt" content="{e(SITE_TITLE)} ©Tempp">'''
        document = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(page_title)}</title>{social}<link rel="stylesheet" href="{href(route, 'assets/site.css')}">{data_script}<script defer src="{href(route, 'assets/site.js')}"></script></head>
<body data-site-root="{href(route, 'index.html')}"><a class="skip-link" href="#main">本文へ</a><div class="site-layout">{self.sidebar(route, active)}<div class="site-content">
<button class="sidebar-toggle" type="button" aria-controls="site-sidebar" aria-expanded="false">メニュー・検索</button>{header}<main id="main" class="site-main{' home-page' if home else ''}">{content}</main>
</div></div><button class="sidebar-backdrop" type="button" aria-label="メニューを閉じる" hidden></button></body></html>'''
        path = self.output / route
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding="utf-8")
        self.pages += 1

    def image_path(self, article: Article) -> str:
        image = article.data.get("image")
        if not image:
            return "assets/banner.png"
        if not isinstance(image, str):
            raise ValueError(f"{article.path.name}: image はローカル画像のパスで指定してください。")
        if image.startswith("![[") and image.endswith("]]"):
            image = image[3:-2]
        image = image.replace("\\", "/")
        url = urlsplit(image)
        if url.scheme or url.netloc:
            raise ValueError(f"{article.path.name}: image はローカル画像を指定してください。")
        relative = Path(unquote(url.path).lstrip("/"))
        candidates = [self.root / relative, article.path.parent / relative]
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_relative_to((self.root / "assets").resolve()) and resolved.is_file():
                return resolved.relative_to(self.root).as_posix()
        raise ValueError(f"{article.path.name}: assets内に画像が見つかりません: {image}")

    def image_size(self, path: str) -> tuple[int, int]:
        if path not in self.image_sizes:
            with (self.root / path).open('rb') as stream:
                header = stream.read(24)
            self.image_sizes[path] = struct.unpack('>II', header[16:24]) if header[:8] == b'\x89PNG\r\n\x1a\n' else (1280, 670)
        return self.image_sizes[path]

    def date_badge(self, article: Article) -> str:
        return f'<span class="article-type">{TYPE_LABEL[article.kind]}</span><time datetime="{article.posted.date().isoformat()}">{article.posted:%Y-%m-%d}</time>'

    def score(self, article: Article) -> str:
        display = article.data.get("rating_display")
        return f'<span class="rating">{e(display)}</span>' if display is not None else ""

    def article_row(self, article: Article, current: str, label: str | None = None, film: Film | None = None, sortable: bool = False) -> str:
        attrs = ''
        if sortable:
            reading = film.reading if film else None
            known = reading_group(reading) != 'unknown'
            meta = {'title': film.title if film else article.title, 'reading': reading_key(reading) if known else None,
                    'reading_label': ('数字・英語' if reading_key(reading)[0][0].isdigit() else reading_key(reading)[0][0]) if known else '読み未登録・要確認',
                    'year': film.data.get('release_year') if film else None, 'genres': film.data.get('genres', []) if film else [],
                    'posted': article.posted.isoformat(), 'file': article.path.name}
            attrs = ' data-index-entry="' + e(json.dumps(meta, ensure_ascii=False, separators=(',', ':'))) + '"'
        return f'<li{attrs}><a class="list-title" href="{href(current, article.route)}">{e(label or article.title)}</a><div class="list-meta">{self.date_badge(article)}{self.score(article)}</div></li>'

    def list_articles(self, articles: list[Article], current: str) -> str:
        if not articles:
            return '<p class="empty">記事はまだありません。</p>'
        return '<ul class="article-list">' + "".join(self.article_row(a, current) for a in articles) + "</ul>"

    def sortable_index(self, content: str, mode: str = 'name') -> str:
        options = ''.join(f'<option value="{value}"' + (' selected' if value == mode else '') + f'>{label}</option>' for value, label in [('name', '名前順'), ('year', '年代順'), ('genre', 'ジャンル順')])
        return f'''<div class="sortable-index"><div class="index-sort-controls" hidden><label>並び順 <select class="index-sort">{options}</select></label><p class="index-sort-status" role="status"></p></div><div class="index-groups">{content}</div></div>'''

    def ordered_index(self, entries: list[tuple[Article, Film | None]], current: str, *, controls: bool = True) -> str:
        """Confirmed readings first; pending readings are never guessed from a title."""
        def order(entry: tuple[Article, Film | None]) -> tuple:
            article, film = entry
            reading = film.reading if film else None
            newest = (-article.posted.toordinal(), -article.posted.hour, -article.posted.minute, -article.posted.second, -article.posted.microsecond)
            if reading_group(reading) != "unknown":
                return (0, reading_key(reading), newest, article.title, article.path.name)
            return (1, (film.title if film else article.title, ""), newest, article.path.name)
        entries = sorted(entries, key=order)
        groups: dict[str, list[tuple[Article, Film | None]]] = {}
        for article, film in entries:
            reading = film.reading if film else None
            label = "読み未登録・要確認"
            if reading_group(reading) != "unknown":
                first = reading_key(reading)[0][0]
                label = "数字・英語" if first.isdigit() else first
            groups.setdefault(label, []).append((article, film))
        known = sum(reading_group(f.reading if f else None) != "unknown" for _, f in entries)
        result = f'<p class="index-summary">{len(entries):,}件（読み確定 {known:,}件・未確定 {len(entries) - known:,}件）</p>'
        for label, group in groups.items():
            rows = []
            for article, film in group:
                title = film.title + " — " + article.title if article.kind == "essay" and film else article.title
                rows.append(self.article_row(article, current, title, film, sortable=True))
            result += f'<section class="index-section"><h2>{e(label)}<span class="count">{len(group):,}件</span></h2><ul class="article-list">' + "".join(rows) + '</ul></section>'
        if not entries:
            result += '<p class="empty">記事はまだありません。</p>'
        return self.sortable_index(result) if controls else result

    def index_articles(self, articles: list[Article], current: str, *, year: int | None = None, field: str | None = None, name: str | None = None, controls: bool = True) -> str:
        entries = []
        for article in articles:
            candidates = [f for f in article.films if f.title and (year is None or f.data.get("release_year") == year) and (field is None or name in f.data[field])]
            film = min(candidates, key=lambda f: (reading_group(f.reading) == "unknown", reading_key(f.reading) if f.reading else (f.title, ""))) if candidates else None
            entries.append((article, film))
        return self.ordered_index(entries, current, controls=controls)

    def count_link(self, current: str, target: str, label: str, count: int) -> str:
        text = f'<span>{e(label)}</span><span class="count">{count:,}件</span>'
        if not count:
            return f'<span class="search-item zero">{text}</span>'
        return f'<a class="search-item" href="{href(current, target)}">{text}</a>'

    def name_links(self, current: str) -> str:
        return '<div class="search-grid name-grid">' + "".join(self.count_link(current, f'titles/{group}/index.html', label, len(self.name_groups[group])) for group, label, _ in NAME_GROUPS if group != "unknown") + '</div><div class="unregistered">' + self.count_link(current, 'titles/unknown/index.html', '読み未登録・要確認', len(self.name_groups['unknown'])) + '</div>'

    def year_links(self, current: str) -> str:
        rows = []
        years = list(self.display_years)
        while years:
            size = min(years[0] % 5 + 1, len(years))
            row, years = years[:size], years[size:]
            rows.append('<div class="year-row">' + "".join(self.count_link(current, f'years/{year}/index.html', f'{year}年', len(self.years.get(year, {}))) for year in row) + '</div>')
        return "".join(rows) + '<div class="unregistered">' + self.count_link(current, 'years/unknown/index.html', '年未登録', len(self.year_unknown)) + '</div>'

    def genre_links(self, current: str) -> str:
        names = [name for name in GENRE_ORDER if name in self.terms['genres']]
        names += sorted(set(self.terms['genres']) - set(names))
        return '<div class="search-grid genre-grid">' + "".join(self.count_link(current, 'genres/' + digest(name) + '/index.html', name, len(self.terms['genres'][name])) for name in names) + '</div><div class="unregistered">' + self.count_link(current, 'genres/unknown/index.html', 'ジャンル未登録', len(self.genre_unknown)) + '</div>'

    def card(self, article: Article) -> str:
        route = 'index.html'
        image = self.image_path(article)
        width, height = self.image_size(image)
        short = article.data.get("short_review")
        short_html = f'<p class="short-review">{e(short)}</p>' if short is not None else ""
        return f'''<article class="review-card" data-article-route="{e(article.route)}"><a class="card-image" href="{href(route, article.route)}" tabindex="-1" aria-hidden="true"><img src="{href(route, image)}" alt="" width="{width}" height="{height}"></a>
<div class="card-content"><div class="article-meta">{self.date_badge(article)}{self.score(article)}</div>
<h3><a href="{href(route, article.route)}">{e(article.title)}</a></h3>{short_html}</div></article>'''

    def home(self) -> None:
        route = "index.html"
        cards = ''.join(self.card(article) for article in self.articles[:4])
        random_cards = ''.join(self.card(article) for article in self.initial_random)
        banner = 'assets/banner.png' if (self.root / 'assets/banner.png').is_file() else 'assets/default.png'
        width, height = self.image_size(banner)
        content = f'''<h1 class="visually-hidden">{SITE_TITLE}</h1><figure class="home-banner"><img src="{href(route, banner)}" alt="{SITE_TITLE} ©Tempp" width="{width}" height="{height}"></figure>
<div class="home-notice"><p>ここはTemppの各所に分散しておいてあった映画ログまとめです。</p><p>古いものは表現に不適切なものがあります。</p><p>時期によって点数にばらつきがあります。</p><ul><li>・数字のものは5点満点</li><li>・★のものは―は３点。プラスは★又は☆、マイナスは×又は△がついています。</li></ul>
<div class="home-progress"><p>現在の作業進捗状況：</p><dl><div><dt>最終更新日：</dt><dd>{self.updated.year}/{self.updated.month}/{self.updated.day}</dd></div><div><dt>感想本数：</dt><dd>{len(self.articles):,}本</dd></div><div><dt>最適化本数：</dt><dd>{self.optimized:,}本</dd></div></dl></div></div>
<section class="home-section" id="latest-reviews"><h2>最新の感想</h2><div class="card-grid">{cards}</div></section>
<section class="home-section" id="random-reviews"><div class="section-heading"><h2>ランダム感想</h2><button id="random-button" type="button" aria-controls="random-cards" hidden>ランダム</button></div><div id="random-cards" class="card-grid">{random_cards}</div><p id="random-status" class="visually-hidden" role="status"></p></section>
<section class="home-section"><h2>名前から検索</h2>{self.name_links(route)}</section>
<section class="home-section"><h2>年代から検索</h2>{self.year_links(route)}</section>
<section class="home-section"><h2>ジャンルから検索</h2>{self.genre_links(route)}<p class="genre-note">複数のジャンルを持つ感想は、それぞれのジャンルに含まれます。</p></section>'''
        self.write_page(route, SITE_TITLE, content, route)

    def interactive_pages(self) -> None:
        data = []
        for index, article in enumerate(self.articles):
            fields = [article.title, article.data.get('short_review') or '', article.body, str(article.posted)]
            for film in article.films:
                fields.extend([film.title, film.reading or '', str(film.data.get('release_year') or '')])
                fields.extend(name for field in ('genres', 'directors', 'cast') for name in film.data[field])
            data.append({'title': article.title, 'route': article.route, 'kind': TYPE_LABEL[article.kind],
                         'date': article.posted.strftime('%Y-%m-%d'), 'datetime': article.posted.isoformat(),
                         'rating': article.data.get('rating_display') or '', 'short': article.data.get('short_review') or '',
                         'search_text': '\n'.join(fields), 'card_html': self.card(article), 'latest': index < 4})
        payload = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
        (self.output / 'assets/article-data.js').write_text('window.movieLogArticles=' + payload + ';\n', encoding='utf-8')
        self.write_page('search/index.html', '検索', '''<div class="page-heading"><h1>検索</h1><p id="search-summary" role="status">左の検索窓に言葉を入れて検索してください。</p></div>
<noscript><p>検索にはJavaScriptを有効にしてください。作品名順・公開年順・ジャンルの一覧からも記事を開けます。</p></noscript>
<ul id="search-results" class="search-results"></ul><button id="search-more" type="button" hidden>さらに表示</button>''')

    def term_links(self, field: str, names: list[str], current: str) -> str:
        return "、".join(f'<a href="{href(current, field + "/" + digest(name) + "/index.html")}">{e(name)}</a>' for name in names)

    def metadata(self, article: Article) -> str:
        blocks = []
        for film in article.films:
            rows = []
            release = film.data.get("release_date") or film.data.get("release_year")
            if release:
                rows.append(f'<dt>公開</dt><dd>{e(release)}</dd>')
            for field, label in (("genres", "ジャンル"), ("directors", "監督")):
                if film.data[field]:
                    rows.append(f'<dt>{label}</dt><dd>{self.term_links(field, film.data[field], article.route)}</dd>')
            cast = film.data["cast"]
            if cast:
                preview = self.term_links("cast", cast[:3], article.route)
                more = f'<details><summary>すべての出演者（{len(cast)}人）</summary>{self.term_links("cast", cast, article.route)}</details>' if len(cast) > 3 else ""
                rows.append(f'<dt>出演者</dt><dd>{preview}{more}</dd>')
            if film.data.get("filmarks_url"):
                rows.append(f'<dt>作品情報</dt><dd><a href="{e(film.data["filmarks_url"])}">Filmarks</a></dd>')
            if rows:
                heading = f'<h3>{e(film.title)}</h3>' if article.kind == "essay" and film.title else ""
                blocks.append(heading + '<dl class="film-metadata">' + "".join(rows) + '</dl>')
        source = article.data.get("source")
        source_url = article.data.get("source_url")
        if source:
            label = f'<a href="{e(source_url)}">{e(source)}</a>' if source_url else e(source)
            blocks.append(f'<p class="source">元媒体：{label}</p>')
        return '<section class="metadata-section"><h2>映画情報</h2>' + "".join(blocks) + "</section>" if blocks else ""

    def related(self, article: Article) -> str:
        candidates = {a.route: a for f in article.films if f.key for a in self.by_film[f.key] if a.route != article.route}
        reviews = sorted((a for a in candidates.values() if a.kind == "review"), key=lambda a: (a.posted, a.path.name), reverse=True)
        essays = sorted((a for a in candidates.values() if a.kind == "essay"), key=lambda a: (a.posted, a.path.name), reverse=True)
        sections = []
        if reviews:
            label = "この映画の他の感想" if article.kind == "review" else "関連する映画の感想"
            sections.append(f'<section class="related"><h2>{label}</h2>{self.list_articles(reviews, article.route)}</section>')
        if essays:
            sections.append(f'<section class="related"><h2>関連エッセイ</h2>{self.list_articles(essays, article.route)}</section>')
        return "".join(sections)

    def render_body(self, article: Article) -> str:
        tokens = self.markdown.parse(article.body)

        def fix_url(value: str) -> str:
            url = urlsplit(value)
            if url.scheme or url.netloc or not url.path:
                return value
            path = unquote(url.path)
            candidates = [article.path.parent / path, self.root / path.lstrip("/")]
            for candidate in candidates:
                resolved = candidate.resolve()
                if resolved in self.by_path:
                    return href(article.route, self.by_path[resolved].route) + ("#" + quote(url.fragment) if url.fragment else "")
                if resolved.is_relative_to((self.root / "assets").resolve()) and resolved.is_file():
                    return href(article.route, resolved.relative_to(self.root).as_posix()) + ("#" + quote(url.fragment) if url.fragment else "")
            return value

        def visit(items: list) -> None:
            for token in items:
                for attribute in ("href", "src"):
                    value = token.attrGet(attribute)
                    if value:
                        token.attrSet(attribute, fix_url(value))
                if token.children:
                    visit(token.children)
        visit(tokens)
        return self.markdown.renderer.render(tokens, self.markdown.options, {})

    def article_pages(self) -> None:
        for article in self.articles:
            image = self.image_path(article)
            width, height = self.image_size(image)
            short = article.data.get("short_review")
            short_html = f'<p class="article-short">{e(short)}</p>' if short is not None else ""
            synopsis = article.data.get("synopsis")
            heading_meta = self.date_badge(article) + self.score(article)
            intro = short_html
            if article.kind == "review" and synopsis and synopsis.strip():
                heading_meta = f'<span class="article-type">{TYPE_LABEL[article.kind]}</span>'
                short_html = f'<p class="article-short"><strong>{e(short)}</strong></p>' if short is not None else ""
                display = article.data.get("rating_display")
                score_html = f'<strong class="rating">{e(display)}</strong>' if display is not None else ""
                intro = f'''<section class="article-intro" aria-label="短評と作品紹介">{short_html}
<p class="review-byline"><time datetime="{article.posted.isoformat()}">{article.posted:%Y-%m-%d}</time>{score_html}</p>
<p class="article-synopsis">{e(synopsis)}</p></section><hr class="review-divider">'''
            content = f'''<article class="full-article"><header class="article-heading"><div class="article-meta">{heading_meta}</div><h1>{e(article.title)}</h1></header>
<img class="article-image" src="{href(article.route, image)}" alt="" width="{width}" height="{height}">
{intro}<div class="article-body">{self.render_body(article)}</div>{self.metadata(article)}{self.related(article)}</article>'''
            self.write_page(article.route, article.title, content, description=article.data.get('short_review'))

    def indexes(self) -> None:
        route = "titles/index.html"
        content = '<div class="page-heading"><h1>作品名順</h1><p>名前順では確定した読みの順に並べ、未登録・要確認の記事は末尾に掲載します。</p></div>' + self.name_links(route) + self.ordered_index(self.entries, route)
        self.write_page(route, "作品名順", content, route)
        for group, label, _ in NAME_GROUPS:
            group_route = f'titles/{group}/index.html'
            self.write_page(group_route, label, f'<div class="page-heading"><p class="eyebrow"><a href="{href(group_route, route)}">名前から検索</a></p><h1>{e(label)}</h1></div>' + self.ordered_index(self.name_groups[group], group_route), route)
        route = "years/index.html"
        content = '<div class="page-heading"><h1>公開年順</h1><p>映画の年が新しい順に掲載します。各年の中は確定した読みの順です。</p></div>' + self.year_links(route)
        year_content = ''
        for year in sorted(self.years, reverse=True):
            year_content += f'<section class="year-section"><h2>{year}年</h2>{self.index_articles(list(self.years[year].values()), route, year=year, controls=False)}</section>'
        year_content += '<section class="year-section"><h2>年未登録</h2>' + self.index_articles(self.year_unknown, route, controls=False) + '</section>'
        content += self.sortable_index(year_content, mode='year')
        self.write_page(route, "公開年順", content, route)
        for year in self.display_years:
            year_route = f'years/{year}/index.html'
            self.write_page(year_route, f'{year}年', f'<div class="page-heading"><p class="eyebrow"><a href="{href(year_route, route)}">年代から検索</a></p><h1>{year}年</h1></div>' + self.index_articles(list(self.years.get(year, {}).values()), year_route, year=year), route)
        self.write_page('years/unknown/index.html', '年未登録', '<div class="page-heading"><h1>年未登録</h1></div>' + self.index_articles(self.year_unknown, 'years/unknown/index.html'), route)
        for field, label in (("genres", "ジャンル"), ("directors", "監督"), ("cast", "出演者")):
            route = field + "/index.html"
            content = f'<div class="page-heading"><h1>{label}別</h1></div><ul class="term-list">'
            for name in sorted(self.terms[field]):
                articles = self.terms[field][name]
                term_route = field + "/" + digest(name) + "/index.html"
                content += f'<li><a href="{href(route, term_route)}">{e(name)}<span class="count">{len(articles):,}件</span></a></li>'
                self.write_page(term_route, name, f'<div class="page-heading"><p class="eyebrow"><a href="{href(term_route, route)}">{label}別</a></p><h1>{e(name)}</h1></div>' + self.index_articles(articles, term_route, field=field, name=name), route)
            content += '</ul>'
            if field == "genres":
                content += '<div class="unregistered">' + self.count_link(route, 'genres/unknown/index.html', 'ジャンル未登録', len(self.genre_unknown)) + '</div>'
                self.write_page('genres/unknown/index.html', 'ジャンル未登録', '<div class="page-heading"><h1>ジャンル未登録</h1></div>' + self.index_articles(self.genre_unknown, 'genres/unknown/index.html'), route)
            if not self.terms[field]:
                content += f'<p class="empty">{label}が登録された記事はまだありません。</p>'
            self.write_page(route, label + "別", content, route)
        route = "essays/index.html"
        self.write_page(route, "エッセイ一覧", '<div class="page-heading"><h1>エッセイ一覧</h1></div>' + self.list_articles([a for a in self.articles if a.kind == "essay"], route), route)


def build(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output == root or root.is_relative_to(output) or output.is_relative_to(root / "content") or output.is_relative_to(root / "assets") or output.is_relative_to(root / "scripts"):
        raise ValueError("生成先は正本・画像・スクリプトとは別のフォルダを指定してください。")
    articles = load_articles(root)
    site = Site(root, output, articles)
    for article in articles:
        site.image_path(article)
    if output.exists() and any(output.iterdir()):
        marker = output / MARKER
        if not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")).get("generator") != GENERATOR:
            raise ValueError("生成先は空のフォルダ、または以前のサイト生成先を指定してください。")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "assets", output / "assets")
    shutil.copyfile(root / "web" / "site.css", output / "assets" / "site.css")
    shutil.copyfile(root / "web" / "site.js", output / "assets" / "site.js")
    site.home()
    site.article_pages()
    site.indexes()
    site.interactive_pages()
    (output / ".nojekyll").write_text("", encoding="utf-8")
    report = {"generator": GENERATOR, "articles": len(articles), "html_pages": site.pages,
              "reviews": sum(a.kind == "review" for a in articles), "essays": sum(a.kind == "essay" for a in articles),
              "articles_with_filmarks": sum(any(f.key for f in a.films) for a in articles),
              "articles_with_reading": sum(any(f.reading for f in a.films) for a in articles),
              "optimized_articles": site.optimized,
              "latest": [{"title": a.title, "review_date": str(a.posted), "route": a.route} for a in articles[:4]],
              "initial_random": [{"title": a.title, "route": a.route} for a in site.initial_random],
              "random_candidates": len(site.random_candidates), "searchable_articles": len(articles)}
    (output / MARKER).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build(args.root, args.output or args.root / "_site")
    except (ValueError, OSError) as error:
        parser.exit(1, f"サイト生成を停止しました: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
