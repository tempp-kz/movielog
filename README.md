# movielog
昔見た映画の感想をだらだら書く

正本はObsidian互換のMarkdownです。1記事を1ファイルとして保存し、同じ映画の複数レビューも別記事として保持します。

## 現在の移行状況

2026-10-08のユーザー確認を反映したFC2抽出版です。公開済み映画カテゴリ2,758元記事のうち2,749記事を抽出し、「感染／予言」「水蒸気急行／ライブイン茅ヶ崎」の指定分割によって2,751ファイルを生成しました。指定除外は9件、個別確認待ちは0件です。

- `content/reviews/`：通常レビュー。ファイル名は作品名→レビュー投稿日。
- `assets/default.png`：ユーザー提供の共通画像。
- `migration/fc2-audit.json`：元ファイルのハッシュ、抽出範囲、文字照合結果、除外・確認待ちの一覧。
- `migration/approved-decisions.json`：明示的な評価・日付修正と除外。
- `migration/approved-article-overrides.json`：ユーザーが指定した差し替え本文と分割内容。
- `migration/approved-headline-overrides.json`：個別確認で確定した点数・短評と元の評価欄。
- `scripts/import-fc2.py`：承認済みの抽出を再現するスクリプト。

本文・短評は原文を保持し、「サンキュー・スモーキング」「水蒸気急行」「ライブイン茅ヶ崎」はユーザー指定本文を使用しています。画像・商品情報・あらすじ・旧クレジットを取り除き、表示用の評価は現在の5点満点、旧表記は`rating_original`に保持しています。未記載の評価は空欄です。

確認01・10・16・28・32を採用しました。「遥かなる大地へ」は「強」を誤字として計算から除外し、4点としています。2026-10-08のユーザー承認に基づき、旧記号評価全体を基準3点、★=+0.5、☆=+0.3、×=−1、△=−0.5で再換算しました。括弧内の加点を含め、上限は5点、無点は3点です。既存617記事は表示用評価だけ変更し、本文・短評・投稿日・元評価表記を保持しています。数値評価と個別指定の点数は変えていません。

確認23（アタマスキャン）・30（ザ・パシフィック）・31（解任）はユーザー指定で非採用としました。残っていた上映会・映画祭等の20件は、ユーザー承認に基づき通常のreviewとして採用しました。承認済みの作品名を使用し、短評・本人本文・投稿日は元ログのままです。

FC2の抽出・切り分けの確認待ちはありません。「コンスタンティン」「感染」「予言」の3記事にFilmarksメタデータと全文のひらがな読みを反映しました。Filmarks掲載の出演者はそれぞれ12人・11人・11人を全員保存しています。確認した出典と本文保全の記録は`migration/metadata-sources.json`にあります。残る2,748記事の映画メタデータ・読みと、元記事URLは未取得のままです。

## 表示と索引

`scripts/build-site.py`が、その時点の`content/`内のMarkdownからHTMLを生成します。正本Markdownを変更せず、作品情報を別の映画DBに保存しません。

- トップはレビュー投稿日が新しい6記事。PCは2列×3段、スマートフォンは1列です。reviewとessayを混在させ、短評は全文を表示します。
- 個別画像はローカルの`assets/`内の画像を使用します。`image`が空欄なら`assets/default.png`を使用します。
- 作品名順、公開年順、ジャンル別、監督別、出演者別、エッセイ一覧を自動生成します。人物名・ジャンル名は該当記事へのリンクになります。出演者別索引には保存した全員を使います。
- `reading`が未登録、または`reading_status: 要確認`の記事は、作品名一覧の「読み未登録」に表示します。読みを推測して五十音順へ混ぜません。公開年・人物・ジャンルが未登録の記事は、その条件の索引には入りません。
- Filmarks作品IDまたは作品URLが一致するレビューは「この映画の他の感想」で相互に辿れます。同名だけでは関連付けません。該当映画に結び付いたessayは「関連エッセイ」に表示します。
- 評価は`rating_display`の現在の点数を表示し、`rating_original`の旧評価記号は表示しません。

HTMLは`_site/`へ生成します。索引ファイルを手作業で更新する必要はありません。生成したHTML・CSS・画像は相対リンクなので、`_site/index.html`をブラウザで開くことも、GitHub Pagesの`/movielog/`で閲覧することもできます。

Python 3.12以降を用意した環境で、依存パッケージを入れてサイトを生成するコマンドです。

```sh
python -m pip install -r requirements.txt
python scripts/build-site.py
```

## 新しい感想を残す

Obsidianではリポジトリのフォルダを保管庫として開きます。レビューは`content/reviews/作品名_YYYY-MM-DD.md`、エッセイは`content/essays/記事名_YYYY-MM-DD.md`に保存してください。ファイル名のWindows禁止文字は対応する全角文字にします。`review_date`は投稿する日付です。映画公開日・公開年とは分けます。

下はレビューの記入例です。映画情報がまだ分からない項目は空欄のままで構いません。本文は区切り線の後へ書き、長さでessayへ変更しません。

```yaml
---
type: review
title: 作品名
reading: null
reading_status: 未調査
release_date: null
release_year: null
genres: []
directors: []
cast: []
filmarks_url: null
filmarks_id: null
review_date: '2026-10-08 21:00:00'
rating: 3.5
rating_display: 3.5点
short_review: ここに短い感想。
source: Obsidian
source_url: null
image: null
---

ここに感想本文。
```

自作画像は`assets/images/`等に保存し、`image: assets/images/自作画像.png`と指定します。Obsidianからも画像を見たい場合は、本文へ通常のMarkdown画像リンクを追加できます。例えば`content/reviews/`からは`![自作画像](../../assets/images/自作画像.png)`です。第三者の商品画像・ポスターは追加しません。

essayは`type: essay`を手動指定し、記事は1ファイルだけ作ります。作品を紐付ける場合は、以下のように映画ごとに`related_films`へ書きます。例のIDは説明用です。通常レビューと共通する実際のFilmarks作品IDまたは作品URLを使ってください。関連作品の公開年・ジャンル・監督・出演者も、reviewと同じ項目を各作品へ記入できます。

```yaml
related_films:
  - title: 映画A
    filmarks_id: '123'
  - title: 映画B
    filmarks_url: https://filmarks.com/movies/456
```

本文はMarkdownとして表示します。記号の自動整文・表記修正は行いません。画像・記事リンクは通常のMarkdown形式を使ってください。

## GitHub Pages

`.github/workflows/pages.yml`を用意しました。確認用ブランチでは生成ルールのテストとHTML生成まで実行します。`main`へ反映し、GitHubのSettings → Pages → Build and deployment → Sourceを**GitHub Actions**にした後は、`main`へのpushで生成・公開されます。公開先は`https://tempp-kz.github.io/movielog/`です。今回の確認用ブランチへのpushだけでは公開しません。

Obsidianで編集したMarkdownと自作画像をGitで保存・pushすると、索引と表示も自動更新されます。

生成ルールのテストを実行するコマンドです。

```sh
python -m unittest discover -s tests -v
```

## 抽出の再現

通常の閲覧・Obsidian編集にこのコマンドは不要です。再抽出する場合のみ、Python 3とPyYAMLを用意し、元のFC2エクスポートを指定してください。出力先は空の別フォルダである必要があります。

```sh
python -m pip install -r requirements.txt
python scripts/import-fc2.py /path/to/FC2log.txt /path/to/empty-output /path/to/audit-output
```

元のFC2エクスポートはこのリポジトリには追加していません。
