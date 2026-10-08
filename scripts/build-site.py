#!/usr/bin/env python3
"""Build the display layer from canonical Markdown; never modify source articles."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import posixpath
import re
import shutil
import unicodedata
from urllib.parse import quote, unquote, urlsplit

from markdown_it import MarkdownIt
import yaml

SITE_TITLE = "映画の感想を だらだら呟く"
NAV = [("index.html", "最新"), ("titles/index.html", "作品名順"),
       ("years/index.html", "公開年順"), ("genres/index.html", "ジャンル"),
       ("directors/index.html", "監督"), ("cast/index.html", "出演者"),
       ("essays/index.html", "エッセイ")]
TYPE_LABEL = {"review": "レビュー", "essay": "エッセイ"}
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)(.*)\Z", re.S)
HIRAGANA = re.compile(r"[ぁ-ゖゝゞー・\s、。！？…〜～「」『』（）()：:－-]+\Z")
MARKER = "_build-report.json"
GENERATOR = "movielog-markdown-site-v1"


def e(value: object) -> str:
    return escape(str(value), quote=True)


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:20]


def reading_key(reading: str) -> tuple[str, str]:
    # Gojuon compares voiced and small kana with their base kana first.
    base = "".join(c for c in unicodedata.normalize("NFD", reading) if not unicodedata.combining(c))
    base = base.translate(str.maketrans("ぁぃぅぇぉっゃゅょゎゕゖ", "あいうえおつやゆよわかけ"))
    base = re.sub(r"[^ぁ-ゖゝゞー]", "", base)
    vowels = {c: vowel for vowel, kana in (("あ", "あかさたなはまやらわ"), ("い", "いきしちにひみりゐ"),
              ("う", "うくすつぬふむゆる"), ("え", "えけせてねへめれゑ"), ("お", "おこそとのほもよろを")) for c in kana}
    normalized = ""
    for char in base:
        normalized += vowels.get(normalized[-1], "ー") if char == "ー" and normalized else char
    return normalized, reading


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
        raise ValueError("reading は全文の読みをひらがなで指定してください。")
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
        for article in articles:
            for key in dict.fromkeys(f.key for f in article.films if f.key):
                self.by_film[key].append(article)
            for field in self.terms:
                for name in dict.fromkeys(v for f in article.films for v in f.data[field]):
                    self.terms[field][name].append(article)
        self.markdown = MarkdownIt("commonmark", {"breaks": True, "html": False, "typographer": False}).enable("table")

    def write_page(self, route: str, title: str, content: str, active: str = "") -> None:
        nav = "".join(f'<a href="{href(route, target)}"' + (' aria-current="page"' if target == active else '') + f'>{label}</a>' for target, label in NAV)
        document = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | {SITE_TITLE}</title><link rel="stylesheet" href="{href(route, 'assets/site.css')}"></head>
<body><a class="skip-link" href="#main">本文へ</a><header class="site-header"><div class="header-inner">
<a class="site-name" href="{href(route, 'index.html')}">{SITE_TITLE}</a><nav aria-label="記事の索引">{nav}</nav>
</div></header><main id="main" class="site-main">{content}</main>
<footer class="site-footer"><a href="{href(route, 'index.html')}">最新の感想へ</a></footer></body></html>'''
        path = self.output / route
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document, encoding="utf-8")
        self.pages += 1

    def image_path(self, article: Article) -> str:
        image = article.data.get("image")
        if not image:
            return "assets/default.png"
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

    def date_badge(self, article: Article) -> str:
        return f'<span class="article-type">{TYPE_LABEL[article.kind]}</span><time datetime="{article.posted.date().isoformat()}">{article.posted:%Y-%m-%d}</time>'

    def score(self, article: Article) -> str:
        display = article.data.get("rating_display")
        return f'<span class="rating">{e(display)}</span>' if display is not None else ""

    def article_row(self, article: Article, current: str, label: str | None = None) -> str:
        return f'<li><a class="list-title" href="{href(current, article.route)}">{e(label or article.title)}</a><div class="list-meta">{self.date_badge(article)}{self.score(article)}</div></li>'

    def list_articles(self, articles: list[Article], current: str) -> str:
        if not articles:
            return '<p class="empty">記事はまだありません。</p>'
        return '<ul class="article-list">' + "".join(self.article_row(a, current) for a in articles) + "</ul>"

    def home(self) -> None:
        route = "index.html"
        cards = []
        for article in self.articles[:6]:
            short = article.data.get("short_review")
            short_html = f'<p class="short-review">{e(short)}</p>' if short is not None else ""
            cards.append(f'''<article class="review-card"><a class="card-image" href="{href(route, article.route)}" tabindex="-1" aria-hidden="true"><img src="{href(route, self.image_path(article))}" alt="" width="1280" height="670"></a>
<div class="card-content"><div class="article-meta">{self.date_badge(article)}{self.score(article)}</div>
<h2><a href="{href(route, article.route)}">{e(article.title)}</a></h2>{short_html}</div></article>''')
        self.write_page(route, "最新の感想", '<div class="page-heading"><h1>最新の感想</h1></div><div class="card-grid">' + "".join(cards) + "</div>", route)

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
            short = article.data.get("short_review")
            short_html = f'<p class="article-short">{e(short)}</p>' if short is not None else ""
            content = f'''<article class="full-article"><header class="article-heading"><div class="article-meta">{self.date_badge(article)}{self.score(article)}</div><h1>{e(article.title)}</h1></header>
<img class="article-image" src="{href(article.route, self.image_path(article))}" alt="" width="1280" height="670">
{short_html}<div class="article-body">{self.render_body(article)}</div>{self.metadata(article)}{self.related(article)}</article>'''
            self.write_page(article.route, article.title, content)

    def indexes(self) -> None:
        route = "titles/index.html"
        entries = [(a, f) for a in self.articles for f in a.films if f.title]
        known = sorted((v for v in entries if v[1].reading), key=lambda v: (reading_key(v[1].reading), -v[0].posted.toordinal(), -v[0].posted.hour, -v[0].posted.minute, -v[0].posted.second, v[0].title))
        unknown = sorted((v for v in entries if not v[1].reading), key=lambda v: (v[1].title, v[0].path.name))
        content = '<div class="page-heading"><h1>作品名順</h1><p>読みが登録された作品を五十音順に並べています。</p></div>'
        for label, group in (("五十音順", known), ("読み未登録", unknown)):
            if group:
                content += f'<section class="index-section"><h2>{label}<span class="count">{len(group):,}件</span></h2>'
                rows = [self.article_row(a, route, f.title + " — " + a.title if a.kind == "essay" else a.title) for a, f in group]
                content += '<ul class="article-list">' + "".join(rows) + '</ul></section>'
        self.write_page(route, "作品名順", content, route)
        route = "years/index.html"
        years: dict[int, dict[str, Article]] = defaultdict(dict)
        for article, film in entries:
            if film.data.get("release_year") is not None:
                years[film.data["release_year"]][article.route] = article
        content = '<div class="page-heading"><h1>公開年順</h1><p>公開年が登録された記事を並べています。</p></div>'
        for year in sorted(years):
            content += f'<section class="index-section"><h2>{year}年</h2>{self.list_articles(list(years[year].values()), route)}</section>'
        if not years:
            content += '<p class="empty">公開年が登録された記事はまだありません。</p>'
        self.write_page(route, "公開年順", content, route)
        for field, label in (("genres", "ジャンル"), ("directors", "監督"), ("cast", "出演者")):
            route = field + "/index.html"
            content = f'<div class="page-heading"><h1>{label}別</h1></div><ul class="term-list">'
            for name in sorted(self.terms[field]):
                articles = self.terms[field][name]
                term_route = field + "/" + digest(name) + "/index.html"
                content += f'<li><a href="{href(route, term_route)}">{e(name)}<span class="count">{len(articles):,}件</span></a></li>'
                self.write_page(term_route, name, f'<div class="page-heading"><p class="eyebrow">{label}別</p><h1>{e(name)}</h1></div>' + self.list_articles(articles, term_route), route)
            content += '</ul>'
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
    site.home()
    site.article_pages()
    site.indexes()
    (output / ".nojekyll").write_text("", encoding="utf-8")
    report = {"generator": GENERATOR, "articles": len(articles), "html_pages": site.pages,
              "reviews": sum(a.kind == "review" for a in articles), "essays": sum(a.kind == "essay" for a in articles),
              "articles_with_filmarks": sum(any(f.key for f in a.films) for a in articles),
              "articles_with_reading": sum(any(f.reading for f in a.films) for a in articles),
              "latest": [{"title": a.title, "review_date": str(a.posted), "route": a.route} for a in articles[:6]]}
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
