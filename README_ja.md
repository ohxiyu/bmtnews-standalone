<div align="center">
<h1>🛰️ BMTNews</h1>

<p><strong>暗号資産・AI・政策を対象とした、AI キュレーションによる日次インテリジェンス。</strong></p>

[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Tool uv](https://img.shields.io/badge/Tool-uv-4B275F?style=for-the-badge&logo=uv&logoColor=white)](https://github.com/astral-sh/uv)
[![Website](https://img.shields.io/badge/Website-bmt.news-263238?style=for-the-badge&logo=homepage&logoColor=white)](https://bmt.news/)
[![Daily](https://img.shields.io/github/actions/workflow/status/ohxiyu/bmtnews-standalone/daily-summary.yml?branch=main&label=Daily&style=for-the-badge&logo=date-fns&logoColor=white)](https://bmt.news/)

📡 1 日 1 号、英語と中国語 · [**サイトで読む →**](https://bmt.news/)

[📖 サイト](https://bmt.news/) · [📋 設定](project-docs/configuration.md) · [English](README.md) · [简体中文](README_zh.md)

</div>

## BMTNews とは

暗号資産の情報量は、誰も追いきれない速度で増え続けています。BMTNews は
取引所のアナウンスチャンネル、プロトコルのリリース、規制当局、暗号資産と AI
のメディアを監視し、**毎朝 08:30（アジア/上海）に 1 号だけ**、重要度順に
並べた 7〜14 本の記事を公開します。各記事には背景、市場への影響分析、
出典リンクが付きます。

GitHub Actions と GitHub Pages だけで動作します。サーバーもデータベースも
常駐サービスもありません。git がストレージ層であり、公開物はすべて静的
ファイルです。

## 主な機能

- **📡 冗長な情報源** — 取引所の Telegram、プロトコルの GitHub リリース、
  規制当局（SEC / CFTC / FRB）、暗号資産メディア、AI ラボ、Hacker News、
  GDELT、Google News
- **📄 全文取得** — 主要な情報源は RSS の抜粋ではなく本文を取得
- **🧵 ストーリースレッド** — 継続中の出来事を日付をまたいで連結
- **🏷️ エンティティページ** — 企業・プロトコル・規制当局ごとに報道を集約
- **🔍 背景と市場影響** — 調査に基づく背景と波及経路の分析（投資助言ではありません）
- **✍️ 編集レイヤー** — 独自記事の挿入、表示明示型の広告枠、記事の非表示
- **🌐 二言語** — 同一ソースから英語版と中国語版を生成
- **🔌 機械可読** — 日付ごとの `edition.json`、`latest.json`、カテゴリ別 Atom フィード
- **📬 マルチチャネル配信** — サイト、Telegram、メール、Webhook、ピーク時間帯に
  分散する X 配信（任意）

## クイックスタート

```bash
uv sync --extra trafilatura
cp data/config.example.json data/config.json
cp .env.example .env
uv run bmtnews --mode publish --hours 24 --cutoff-hour 8
```

詳細は [project-docs/configuration.md](project-docs/configuration.md) を参照してください。

## ライセンス

BMTNews のソースコードは MIT ライセンスで提供されます。詳細は
[LICENSE](LICENSE) を参照してください。生成されたニュース版および第三者の
ニュース素材はソフトウェアライセンスの対象外です。詳細は
[コンテンツとデータの権利](CONTENT-LICENSE.md)および
[第三者通知](THIRD_PARTY_NOTICES.md)を参照してください。
