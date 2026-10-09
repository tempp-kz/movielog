"""Verify preservation, association and generated indexes with isolated fixtures."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import yaml

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_site", REPO / "scripts" / "build-site.py")
site = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = site
SPEC.loader.exec_module(site)


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "content" / "reviews").mkdir(parents=True)
        (self.root / "content" / "essays").mkdir()
        (self.root / "assets").mkdir()
        (self.root / "web").mkdir()
        shutil.copy(REPO / "assets" / "default.png", self.root / "assets" / "default.png")
        shutil.copy(REPO / "web" / "site.css", self.root / "web" / "site.css")
        shutil.copy(REPO / "web" / "site.js", self.root / "web" / "site.js")
        self.output = self.root / "_site"

    def add(self, title="映画A", posted="2005-01-01 12:00:00", **overrides):
        data = dict(type="review", title=title, reading=None, reading_status="未調査", release_date=None,
                    release_year=None, genres=[], directors=[], cast=[], filmarks_id=None, filmarks_url=None,
                    review_date=posted, rating=3, rating_display="3点", rating_original="－", short_review="短評。", source="FC2", source_url=None, image=None)
        body = overrides.pop("body", "原文のまま…誤字です。\n次の行。\n")
        data.update(overrides)
        folder = "essays" if data["type"] == "essay" else "reviews"
        path = self.root / "content" / folder / f"{title}_{posted[:10]}.md"
        path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n\n" + body, encoding="utf-8")
        return path

    def article(self, path):
        return next(a for a in site.load_articles(self.root) if a.path == path)

    def read(self, route):
        return (self.output / route).read_text(encoding="utf-8")

    def test_latest_four_and_two_random_preserve_posting_order_and_full_short_text(self):
        self.add("古いレビュー", "2003-01-01")
        for i in range(1, 8):
            self.add(f"新しい{i}", f"2020-01-{i:02d}", type="essay" if i == 7 else "review", short_review="長い短評。" * 80 if i == 7 else "短評。")
        report = site.build(self.root, self.output)
        self.assertEqual([v["title"] for v in report["latest"]], [f"新しい{i}" for i in range(7, 3, -1)])
        self.assertEqual(len(report['initial_random']), 2)
        self.assertEqual(len({v['route'] for v in report['initial_random']}), 2)
        self.assertFalse({v['route'] for v in report['initial_random']} & {v['route'] for v in report['latest']})
        home = self.read("index.html")
        self.assertEqual(home.count('class="review-card"'), 6)
        self.assertIn("長い短評。" * 80, home)
        self.assertIn("エッセイ", home)
        self.assertIn('id="random-button"', home)
        data = json.loads(self.read('assets/article-data.js').removeprefix('window.movieLogArticles=').removesuffix(';\n'))
        self.assertEqual(len(data), 8)
        self.assertEqual(sum(item['latest'] for item in data), 4)
        self.assertIn('原文のまま…誤字です。', data[0]['search_text'])
        self.assertIn('T00:00:00', data[0]['datetime'])

    def test_sidebar_has_search_tree_and_external_links_on_all_page_types(self):
        path = self.add(reading='かんせん', reading_status='取得済み', release_year=2024, genres=['ホラー'])
        site.build(self.root, self.output)
        for route in ('index.html', 'titles/k/index.html', self.article(path).route, 'search/index.html'):
            page = self.read(route)
            self.assertEqual(page.count('aria-label="記事の索引"'), 1)
            self.assertNotIn('site-footer', page)
            self.assertIn('id="site-sidebar"', page)
            self.assertLess(page.index('class="sidebar-search"'), page.index('class="tree-nav"'))
            self.assertLess(page.index('class="tree-nav"'), page.index('class="sidebar-links"'))
            self.assertIn('action="' + site.href(route, 'search/index.html') + '"', page)
            self.assertIn('■架空都市神津wiki', page)
            self.assertIn('href="https://tempp-kz.github.io/pucopac/"', page)
        self.assertIn('<details class="nav-folder" open>', self.read('titles/k/index.html'))

    def test_optimized_count_uses_applied_confirmed_records_and_deduplicates_articles(self):
        attrs = dict(release_year=2024, genres=['ホラー'], directors=['監督'], cast=['出演者'])
        approved = self.add('確認済み', **attrs)
        self.add('属性だけ揃う', **attrs)
        pending = self.add('未確認', **attrs)
        (self.root / 'migration').mkdir()
        row = {'file': approved.relative_to(self.root).as_posix(), 'metadata_after': attrs}
        for name in ('metadata-trial30-a.json', 'metadata-trial30-b.json'):
            (self.root / 'migration' / name).write_text(json.dumps({'confirmed_count': 1, 'outcomes': [row]}))
        (self.root / 'migration' / 'metadata-trial-pending.json').write_text(json.dumps({'confirmed_count': 0, 'outcomes': [{'file': pending.relative_to(self.root).as_posix(), 'metadata_after': attrs}]}))
        report = site.build(self.root, self.output)
        self.assertEqual(report['optimized_articles'], 1)
        self.assertIn('最適化本数：</dt><dd>1本', self.read('index.html'))
        changed = yaml.safe_load(site.FRONTMATTER.fullmatch(approved.read_text())[1])
        changed['cast'] = []
        approved.write_text('---\n' + yaml.safe_dump(changed, allow_unicode=True) + '---\n\n本文')
        self.assertEqual(site.build(self.root, self.output)['optimized_articles'], 0)

    def test_small_article_collection_has_no_latest_random_overlap(self):
        for i in range(3):
            self.add('映画' + str(i), f'2024-01-{i + 1:02d}')
        report = site.build(self.root, self.output)
        self.assertEqual(len(report['latest']), 3)
        self.assertEqual(report['initial_random'], [])

    def test_all_saved_cast_and_multiple_directors_are_indexed(self):
        p = self.add(filmarks_id="10", directors=["監督A", "監督B"], cast=["出演者1", "出演者2", "出演者3", "出演者4"], genres=["ホラー"])
        site.build(self.root, self.output)
        self.assertIn("映画A", self.read("cast/" + site.digest("出演者4") + "/index.html"))
        self.assertIn("映画A", self.read("directors/" + site.digest("監督B") + "/index.html"))
        article = self.read(self.article(p).route)
        self.assertIn("すべての出演者（4人）", article)
        self.assertIn(site.digest("出演者4"), article)

    def test_repeated_reviews_stay_separate_and_do_not_match_by_title(self):
        first = self.add("映画A", "2005-01-01", filmarks_id="10")
        second = self.add("映画A", "2006-01-01", filmarks_url="https://filmarks.com/movies/10/?x=1")
        other = self.add("映画A", "2007-01-01", filmarks_id="20")
        site.build(self.root, self.output)
        page = self.read(self.article(first).route)
        self.assertIn("この映画の他の感想", page)
        self.assertIn(site.href(self.article(first).route, self.article(second).route), page)
        self.assertNotIn(site.href(self.article(first).route, self.article(other).route), page)
        self.assertEqual(len(list((self.output / "articles").glob("*/index.html"))), 3)

    def test_one_essay_is_related_to_two_films_without_duplication(self):
        a = self.add("映画A", "2005-01-01", filmarks_id="10")
        b = self.add("映画B", "2005-01-02", filmarks_id="20")
        essay = self.add("二作品を考える", "2010-01-01", type="essay", related_films=[dict(title="映画A", reading="えいがあ", filmarks_id="10"), dict(title="映画B", reading="えいがびー", filmarks_id="20")])
        site.build(self.root, self.output)
        for review in (a, b):
            page = self.read(self.article(review).route)
            self.assertIn("関連エッセイ", page)
            self.assertIn(site.href(self.article(review).route, self.article(essay).route), page)
        titles = self.read("titles/index.html")
        self.assertIn("映画A — 二作品を考える", titles)
        self.assertIn("映画B — 二作品を考える", titles)
        self.assertEqual(len(list((self.output / "articles").glob("*/index.html"))), 3)

    def test_reading_order_and_unconfirmed_reading(self):
        self.add("漢字B", "2005-01-01", reading="かた", reading_status="取得済み")
        self.add("漢字A", "2005-01-02", reading="がい", reading_status="取得済み")
        self.add("不確実", "2005-01-03", reading="あい", reading_status="要確認")
        site.build(self.root, self.output)
        titles = self.read("titles/index.html")
        self.assertLess(titles.find("漢字A"), titles.find("漢字B"))
        self.assertGreater(titles.find("不確実"), titles.find("読み未登録"))
        self.assertEqual(site.reading_key("きゃく")[0], "きやく")
        self.assertEqual(site.reading_key("きー")[0], "きい")

    def test_name_group_pages_use_reading_not_display_title_and_accept_digits(self):
        english = self.add("AFFLICTED", reading="あふりくてっど", reading_status="取得済み")
        number = self.add("11：11：11", reading="１１１１１１", reading_status="取得済み")
        pending = self.add("保留", reading="あい", reading_status="要確認")
        site.build(self.root, self.output)
        self.assertIn("AFFLICTED", self.read("titles/a/index.html"))
        self.assertNotIn("AFFLICTED", self.read("titles/number/index.html"))
        self.assertIn("11：11：11", self.read("titles/number/index.html"))
        self.assertIn("保留", self.read("titles/unknown/index.html"))
        self.assertNotIn("保留", self.read("titles/a/index.html"))
        self.assertEqual(site.reading_key("１１１１１１"), site.reading_key("111111"))
        self.assertEqual(site.reading_group("がい"), "k")
        self.assertEqual(site.reading_group("111111"), "number")
        for path in (english, number, pending):
            self.assertIn(site.href("titles/index.html", self.article(path).route), self.read("titles/index.html"))

    def test_year_and_genre_indexes_sort_confirmed_readings_before_pending(self):
        common = dict(release_year=2024, genres=["ホラー"])
        self.add("確定B", "2003-01-01", reading="かた", reading_status="取得済み", **common)
        self.add("確定A", "2002-01-01", reading="がい", reading_status="取得済み", **common)
        self.add("保留", "2024-01-01", reading="あい", reading_status="要確認", **common)
        self.add("未登録", "2025-01-01", **common)
        repeated = self.add("確定A", "2001-01-01", reading="がい", reading_status="取得済み", **common)
        old = self.add("昔の映画", "2026-01-01", release_year=1969)
        site.build(self.root, self.output)
        for route in ("years/2024/index.html", "genres/" + site.digest("ホラー") + "/index.html"):
            page = self.read(route)
            self.assertLess(page.index('>確定A</a>'), page.index('>確定B</a>'))
            self.assertLess(page.index('>確定B</a>'), page.index('>保留</a>'))
            self.assertLess(page.index('読み未登録・要確認'), page.index('>保留</a>'))
            self.assertLess(page.index('読み未登録・要確認'), page.index('>未登録</a>'))
            self.assertEqual(page.count('>確定A</a>'), 2)
            self.assertIn("5件（読み確定 3件・未確定 2件）", page)
            self.assertIn(site.href(route, self.article(repeated).route), page)
        years = self.read("years/index.html")
        self.assertLess(years.index('>2024年</span>'), years.index('>1969年</span>'))
        self.assertIn(site.href("years/1969/index.html", self.article(old).route), self.read("years/1969/index.html"))

    def test_home_has_approved_sections_dynamic_counts_and_unknown_index_links(self):
        self.add("登録済み", reading="かんせん", reading_status="取得済み", release_year=2024, genres=["ホラー", "SF"])
        self.add("未登録")
        site.build(self.root, self.output)
        page = self.read("index.html")
        self.assertLess(page.index('class="home-banner"'), page.index("ここはTempp"))
        self.assertLess(page.index("現在の作業進捗状況"), page.index("最新の感想"))
        self.assertLess(page.index("最新の感想"), page.index("名前から検索"))
        self.assertLess(page.index("名前から検索"), page.index("年代から検索"))
        self.assertLess(page.index("年代から検索"), page.index("ジャンルから検索"))
        self.assertIn("感想本数：</dt><dd>2本", page)
        for route in ("titles/k/index.html", "titles/unknown/index.html", "years/2024/index.html", "years/unknown/index.html", "genres/unknown/index.html"):
            self.assertIn(site.href("index.html", route), page)
            self.assertTrue((self.output / route).is_file())
        self.assertIn("未登録", self.read("years/unknown/index.html"))
        self.assertIn("未登録", self.read("genres/unknown/index.html"))

    def test_sources_are_unchanged_and_stale_pages_are_removed_on_rebuild(self):
        first = self.add("映画A", "2005-01-01")
        second = self.add("映画B", "2005-01-02")
        before = {p: p.read_bytes() for p in (first, second)}
        old_route = self.article(second).route
        site.build(self.root, self.output)
        for p, content in before.items():
            self.assertEqual(p.read_bytes(), content)
        second.unlink()
        site.build(self.root, self.output)
        self.assertFalse((self.output / old_route).exists())
        self.assertEqual(first.read_bytes(), before[first])

    def test_local_image_and_markdown_links_work_in_generated_pages(self):
        own = self.root / "assets" / "自作 絵.png"
        shutil.copy(self.root / "assets" / "default.png", own)
        first = self.add("映画A", "2005-01-01", image="assets/自作 絵.png")
        second = self.add("映画B", "2005-01-02", body='[前の感想](映画A_2005-01-01.md)\n\n![自作](../../assets/自作%20絵.png)\n\n**太字**')
        site.build(self.root, self.output)
        page = self.read(self.article(second).route)
        self.assertIn(site.href(self.article(second).route, self.article(first).route), page)
        self.assertIn(site.href(self.article(second).route, "assets/自作 絵.png"), page)
        self.assertIn("<strong>太字</strong>", page)
        self.assertIn(site.href("index.html", "assets/自作 絵.png"), self.read("index.html"))

    def test_conflicting_film_identity_is_rejected(self):
        self.add(filmarks_id="10", filmarks_url="https://filmarks.com/movies/20")
        with self.assertRaisesRegex(ValueError, "作品IDと作品URLが一致"):
            site.build(self.root, self.output)

    def test_release_date_alone_is_enough_for_year_index_without_source_changes(self):
        path = self.add(release_date="2005-04-16", release_year=None)
        original = path.read_bytes()
        site.build(self.root, self.output)
        self.assertIn("2005年", self.read("years/index.html"))
        self.assertIn("映画A", self.read("years/index.html"))
        self.assertEqual(path.read_bytes(), original)
        self.assertIsNone(self.article(path).data["release_year"])

    def test_unowned_output_is_not_overwritten(self):
        self.add()
        self.output.mkdir()
        note = self.output / "my-note.txt"
        note.write_text("残す", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "生成先は空"):
            site.build(self.root, self.output)
        self.assertEqual(note.read_text(encoding="utf-8"), "残す")


if __name__ == "__main__":
    unittest.main()
