# movielog
昔見た映画の感想をだらだら書く

正本はObsidian互換のMarkdownです。1記事を1ファイルとして保存し、同じ映画の複数レビューも別記事として保持します。

## 現在の移行状況

2026-10-08のユーザー確認を反映したFC2抽出版です。公開済み映画カテゴリ2,758元記事のうち2,724記事を抽出し、「感染／予言」「水蒸気急行／ライブイン茅ヶ崎」の指定分割によって2,726ファイルを生成しました。指定除外は6件、個別確認待ちは28件です。

- `content/reviews/`：通常レビュー。ファイル名は作品名→レビュー投稿日。
- `assets/default.png`：ユーザー提供の共通画像。
- `migration/fc2-audit.json`：元ファイルのハッシュ、抽出範囲、文字照合結果、除外・確認待ちの一覧。
- `migration/approved-decisions.json`：明示的な評価・日付修正と除外。
- `migration/approved-article-overrides.json`：ユーザーが指定した差し替え本文と分割内容。
- `scripts/import-fc2.py`：承認済みの抽出を再現するスクリプト。

本文・短評は原文を保持し、「サンキュー・スモーキング」「水蒸気急行」「ライブイン茅ヶ崎」はユーザー指定本文を使用しています。画像・商品情報・あらすじ・旧クレジットを取り除き、表示用の評価は現在の5点満点、旧表記は`rating_original`に保持しています。未記載の評価は空欄です。

Filmarksメタデータ、タイトル読み、元記事URLの未取得欄は空欄です。確認待ちの記事は本文を削らず、今回の抽出対象から保留しています。GitHub Pages表示層は次の工程です。

## 抽出の再現

通常の閲覧・Obsidian編集にこのコマンドは不要です。再抽出する場合のみ、Python 3とPyYAMLを用意し、元のFC2エクスポートを指定してください。出力先は空の別フォルダである必要があります。

```sh
python -m pip install -r requirements.txt
python scripts/import-fc2.py /path/to/FC2log.txt /path/to/empty-output /path/to/audit-output
```

元のFC2エクスポートはこのリポジトリには追加していません。
