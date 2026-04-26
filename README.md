# Invest Insights - Astro投資ブログテンプレート

Astro + Content Collections APIで構築した、投資情報ブログ向けの静的サイトテンプレートです。信頼感のある青を基調としたシンプルでモダンなUI設計になっています。

## 特徴

- 📝 **Markdown記事** — `src/content/blog/` にMarkdownを置くだけで記事が公開されます
- 🔒 **型安全** — Content Collections APIでfrontmatterが型チェックされます
- 🎨 **Trust Blue デザイン** — 投資情報に適した落ち着いた青を基調とした配色
- 📱 **レスポンシブ** — モバイル・タブレット・デスクトップに対応
- 📡 **RSS配信** — `/rss.xml` で自動生成
- 🗺️ **サイトマップ** — `@astrojs/sitemap` で自動生成
- ⚠️ **免責事項** — 投資情報メディアに必要な免責表示を各記事に自動挿入

## セットアップ

```bash
npm install
npm run dev
```

ブラウザで `http://localhost:4321` を開くとサイトが確認できます。

## 記事の追加方法

`src/content/blog/` にMarkdownファイル(例: `my-post.md`)を作成してください。frontmatterの書式は以下の通りです。

```markdown
---
title: '記事タイトル'
description: '記事の概要(一覧ページやOGPで使われます)'
pubDate: 2026-04-20
updatedDate: 2026-04-22   # 任意
category: 'マーケット分析' # 必須: 5種類から選択
tags: ['タグ1', 'タグ2']
author: 'Invest Insights 編集部'
heroImage: '/images/hero.jpg' # 任意
draft: false               # trueにすると非公開
---

本文をMarkdownで書きます。
```

### 選択可能なカテゴリー

- マーケット分析
- 資産運用
- 投資戦略
- 経済ニュース
- 初心者ガイド

カテゴリーを追加・変更したい場合は `src/content/config.ts` の `z.enum([...])` を編集してください。

## ディレクトリ構成

```
src/
├── components/      # Header, Footer, PostCard など
├── content/
│   ├── blog/        # ← 記事のMarkdownをここに置く
│   └── config.ts    # Collection schema(frontmatterの型定義)
├── layouts/
│   ├── BaseLayout.astro
│   └── BlogPost.astro
├── pages/
│   ├── index.astro          # トップページ
│   ├── about.astro          # 運営者情報
│   ├── rss.xml.js           # RSSフィード
│   └── blog/
│       ├── index.astro      # 記事一覧
│       └── [...slug].astro  # 記事詳細(動的ルート)
├── styles/
│   └── global.css           # デザイントークンと共通スタイル
└── consts.ts                # サイトタイトル等の定数
```

## カスタマイズ

### サイト情報
`src/consts.ts` を編集してサイトタイトルや説明文を変更できます。

### 配色
`src/styles/global.css` の `:root` セクションでCSS変数として定義しています。
`--color-primary-*` を変更すると全体の配色が変わります。

### 本番公開URL
`astro.config.mjs` の `site` を公開URLに変更してください(RSSやサイトマップで使われます)。

## ビルド

```bash
npm run build    # dist/ に静的ファイルを出力
npm run preview  # ビルド結果をプレビュー
```

`dist/` ディレクトリをNetlify、Vercel、Cloudflare Pages、GitHub Pagesなど任意の静的ホスティングにデプロイできます。
