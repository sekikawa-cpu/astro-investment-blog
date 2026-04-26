# -*- coding: utf-8 -*-
"""
配当＆優待ナビ｜日次レポート自動生成スクリプト（v4）

機能:
- yfinance で株価を取得
- Yahoo!ファイナンス RSS からニューストピックを取得
- Anthropic API (claude-sonnet-4-6) で導入文・ランキング・備考・解説・テーマ判定を生成
- テーマに基づいて books_data.json から最適な3冊を選書
- 書影は public/images/books/{ISBN13}.jpg（download_covers.py で事前DL済み）を使用
- Amazon アフィリエイトリンク: https://www.amazon.co.jp/dp/{ASIN}?tag=investinsight-22
- frontmatter + 本文を src/content/blog/{YYYY-MM-DD}.md に書き出し
"""
import json
import os
import random
import re
import sys
import urllib.request
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import yfinance as yf

try:
    import anthropic
except ImportError:
    print("Error: anthropic package is required.", file=sys.stderr)
    sys.exit(2)

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-6"
AFFILIATE_TAG = "investinsight-22"
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")
BOOKS_JSON = Path("books_data.json")
PUBLIC_BOOKS_DIR = Path("public/images/books")

NEWS_RSS_URLS = [
    "https://news.yahoo.co.jp/rss/categories/business.xml",
]

TICKER_POOL: Dict[str, str] = {
    "1489.T": "日経高配当50ETF",
    "^GSPC": "S&P 500",
    "SPYD": "SPYD (米国高配当)",
    "VYM": "VYM (米国高配当)",
    "2914.T": "JT",
    "8306.T": "三菱UFJFG",
    "9432.T": "NTT",
    "8058.T": "三菱商事",
    "8593.T": "三菱HCキャピタル",
    "1605.T": "INPEX",
    "1928.T": "積水ハウス",
    "7203.T": "トヨタ自動車",
    "8267.T": "イオン",
    "9433.T": "KDDI",
    "2702.T": "日本マクドナルドHD",
    "3197.T": "すかいらーくHD",
    "9861.T": "吉野家HD",
    "8282.T": "ケーズHD",
    "2503.T": "キリンHD",
    "9202.T": "ANAHD",
    "9101.T": "日本郵船",
    "8001.T": "伊藤忠商事",
    "4502.T": "武田薬品工業",
    "8316.T": "三井住友FG",
    "4063.T": "信越化学工業",
    "9020.T": "JR東日本",
    "2802.T": "味の素",
    "3382.T": "セブン＆アイHD",
    "7453.T": "良品計画",
}


# ---------------------------------------------------------------------------
# Amazon アフィリエイトリンク生成
# ---------------------------------------------------------------------------
def amazon_url(asin: str) -> str:
    """公式形式のアフィリエイトURL"""
    return f"https://www.amazon.co.jp/dp/{asin}?tag={AFFILIATE_TAG}"


# ---------------------------------------------------------------------------
# 書籍データ読み込み
# ---------------------------------------------------------------------------
def load_books() -> List[Dict]:
    if not BOOKS_JSON.exists():
        print(f"[warn] {BOOKS_JSON} not found. Using empty list.", file=sys.stderr)
        return []
    data = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    return data.get("books", [])


# ---------------------------------------------------------------------------
# テーマに基づく書籍選定（AI判断）
# ---------------------------------------------------------------------------
def select_books_by_theme(books: List[Dict], themes: List[str], count: int = 3) -> List[Dict]:
    """
    AI が返したテーマリストに一致する書籍を優先しつつ、
    重複なく count 冊を選定する。
    テーマが少なすぎる場合はランダムで補充。
    """
    themes_set = set(themes)
    scored: List[Tuple[int, Dict]] = []
    for b in books:
        book_themes = set(b.get("themes", []))
        score = len(themes_set & book_themes)
        scored.append((score, b))

    # スコア降順でソート（同スコアはランダム）
    scored.sort(key=lambda x: (-x[0], random.random()))

    selected = [b for _, b in scored[:count]]
    return selected


# ---------------------------------------------------------------------------
# 書影パス解決
# ---------------------------------------------------------------------------
def resolve_cover_src(book: Dict) -> str:
    """
    書影URLを以下の優先順で解決する:
    1. public/images/books/{ISBN13}.jpg (download_covers.py でDL済みのローカルファイル)
    2. books_data.json の cover_url フィールド（楽天ブックスCDN確認済みURL）
    3. openBD / Google Books API（フォールバック）
    4. SVG プレースホルダー（最終手段）
    """
    isbn13 = book.get("isbn13", "")

    # 1. ローカルファイルが存在する場合は最優先
    local_path = PUBLIC_BOOKS_DIR / f"{isbn13}.jpg"
    if local_path.exists() and local_path.stat().st_size > 1024:
        return book["image_local"]  # /images/books/... → Astro が static ファイルとして配信

    # 2. books_data.json に登録済みの cover_url（楽天ブックスCDN）
    cover_url = book.get("cover_url", "")
    if cover_url:
        return cover_url

    # 3. openBD / Google Books API（ネット環境必須）
    url = _try_remote_cover(isbn13)
    if url:
        return url

    # 4. SVG プレースホルダー
    title_short = (book.get("title", "Book") or "")[:8]
    safe = title_short.replace('"', "").replace("'", "")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="170" viewBox="0 0 120 170">'
        '<rect width="120" height="170" fill="#1e293b"/>'
        '<rect x="5" y="5" width="110" height="160" fill="none" stroke="#475569" stroke-width="1.5"/>'
        f'<text x="60" y="90" font-family="sans-serif" font-size="10" fill="#e2e8f0" '
        f'text-anchor="middle" dominant-baseline="middle">{safe}</text></svg>'
    )
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def _try_remote_cover(isbn13: str) -> Optional[str]:
    """Google Books API → openBD の順で書影URLを取得（APIキー不要・安定）"""
    import re as _re
    # 1. Google Books API（最も安定・APIキー不要）
    try:
        api = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{urllib.parse.quote(isbn13)}&country=JP"
        req = urllib.request.Request(api, headers={"User-Agent": "astro-investment-blog/4.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data and data.get("items"):
            links = (data["items"][0].get("volumeInfo") or {}).get("imageLinks", {}) or {}
            for k in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
                url = links.get(k)
                if url:
                    url = url.replace("http://", "https://")
                    url = _re.sub(r"zoom=\d+", "zoom=1", url)
                    return url
    except Exception:
        pass
    # 2. openBD（日本書籍に強い）
    try:
        api = f"https://api.openbd.jp/v1/get?isbn={urllib.parse.quote(isbn13)}"
        req = urllib.request.Request(api, headers={"User-Agent": "astro-investment-blog/4.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data and isinstance(data, list) and data[0]:
            cover = (data[0].get("summary") or {}).get("cover")
            if cover:
                return cover.replace("http://", "https://")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _http_get(url: str, timeout: int = 10, accept: str = "*/*") -> Optional[bytes]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; astro-investment-blog/4.0)",
                "Accept": accept,
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"[http] fail {url}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# ニュース取得
# ---------------------------------------------------------------------------
@dataclass
class NewsItem:
    title: str
    link: str
    pub_date: str
    source: str


def collect_news(max_items: int = 5) -> List[NewsItem]:
    items: List[NewsItem] = []
    for url in NEWS_RSS_URLS:
        body = _http_get(url, accept="application/rss+xml,application/xml,text/xml")
        if body is None:
            continue
        try:
            root = ET.fromstring(body)
            for it in root.iter("item"):
                title_el = it.find("title")
                link_el = it.find("link")
                date_el = it.find("pubDate")
                src_el = it.find("source")
                if title_el is None or link_el is None:
                    continue
                title = (title_el.text or "").strip()
                link = (link_el.text or "").strip()
                raw_date = (date_el.text or "").strip() if date_el is not None else ""
                source = (src_el.text or "Yahoo!ニュース").strip() if src_el is not None else "Yahoo!ニュース"
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(raw_date).astimezone(TZ)
                    pub_date = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pub_date = raw_date[:16]
                if title and link:
                    items.append(NewsItem(title=title, link=link, pub_date=pub_date, source=source))
                if len(items) >= max_items * 3:
                    break
        except Exception as e:
            print(f"[news] RSS parse fail: {e}", file=sys.stderr)

    keywords = ["株", "市場", "投資", "配当", "金利", "FRB", "日銀", "為替", "ドル",
                "円安", "円高", "決算", "業績", "増配", "NISA", "ETF", "国債", "原油"]
    items.sort(key=lambda it: sum(1 for k in keywords if k in it.title), reverse=True)
    return items[:max_items]


# ---------------------------------------------------------------------------
# 株価データ
# ---------------------------------------------------------------------------
@dataclass
class PriceInfo:
    ticker: str
    name: str
    close: float
    prev_close: float
    yield_pc: float

    @property
    def change(self) -> float:
        return self.close - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0.0


# ---------------------------------------------------------------------------
# 通貨ユーティリティ
# ---------------------------------------------------------------------------
# .T で終わる銘柄は東証 → 円、それ以外は USD
# インデックス（^で始まる）も USD 扱いにする
def get_currency(ticker: str) -> str:
    """ティッカーから通貨記号を返す。東証(.T)は円、それ以外はUSD。"""
    if ticker.endswith(".T"):
        return "円"
    return "USD"


def fmt_price(value: float, ticker: str) -> str:
    """通貨に応じた価格フォーマット。円は小数不要、USDは2桁。"""
    if ticker.endswith(".T"):
        return f"{value:,.1f}"
    return f"${value:,.2f}"


def fmt_change(value: float, ticker: str) -> str:
    """通貨に応じた前日比フォーマット。符号は $ の前に付ける。"""
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    abs_val = abs(value)
    if ticker.endswith(".T"):
        return f"{sign}{abs_val:,.1f}"
    return f"{sign}${abs_val:,.2f}"


def collect_prices() -> List[PriceInfo]:
    results: List[PriceInfo] = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="5d", auto_adjust=False).sort_index()
            if df.empty or len(df) < 2:
                continue
            try:
                y = t.info.get("dividendYield", 0) or 0
            except Exception:
                y = 0
            y_pc = (y * 100) if y and y < 1 else (y or 0.0)
            results.append(PriceInfo(
                ticker=ticker, name=name,
                close=float(df.iloc[-1]["Close"]),
                prev_close=float(df.iloc[-2]["Close"]),
                yield_pc=float(y_pc),
            ))
        except Exception as e:
            print(f"[warn] {ticker}: {e}", file=sys.stderr)
    return results


# ---------------------------------------------------------------------------
# Anthropic レスポンス → テキスト（'list' object has no attribute 'text' 回避）
# ---------------------------------------------------------------------------
def _extract_text(response) -> str:
    content = response.content
    if hasattr(content, "text"):
        return content.text
    if isinstance(content, list):
        return "\n".join(
            block.text if hasattr(block, "text")
            else (block.get("text", "") if isinstance(block, dict) else "")
            for block in content
        )
    return str(content)


# ---------------------------------------------------------------------------
# AI 生成（銘柄分析 + テーマ判定）
# ---------------------------------------------------------------------------
def generate_summary(
    prices: List[PriceInfo], report_date: str
) -> Tuple[str, List[str], Dict[str, str], str, List[str]]:
    """
    Returns: (intro, ranking_tickers, remarks, body, themes)
    themes: その日の市場テーマを表すキーワードリスト（書籍選定に使用）
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    data_str = "\n".join(
        f"{p.ticker}, {p.name}, 終値:{p.close:.2f}, "
        f"前日比:{p.change_pct:+.2f}%, 配当利回り:{p.yield_pc:.2f}%"
        for p in prices
    )

    # テーマ候補（books_data.json の themes キーと対応）
    theme_list = (
        "foundation, household, savings, nisa, high_dividend_jp, high_dividend_us, "
        "us_stocks, passive_income, psychology, behavior, mindset, index, index_us, "
        "long_term, passive_investing, fire, beginner, dca, data_driven, philosophy, "
        "lifestyle, spending"
    )

    system_prompt = f"""あなたは経験豊富な投資メンターです。以下の厳密なフォーマットで日次の投資レポートを生成してください。

【1行目】経済全体の概況（アイスブレイク）を約200文字で記述。日本市場・米国市場・為替・金利動向に軽く触れ、長期投資家への前向きなメッセージで締める。改行を入れず必ず1行で。

【2行目】注目銘柄ベスト20のティッカーコードのみをカンマ区切りで列挙。例: 1489.T,9432.T,8306.T,...

【3行目】各銘柄の備考をJSONオブジェクト1行で出力。例: {{"1489.T":"増配基調で安定","9432.T":"通信インフラの王者"}}
備考は各銘柄15〜25文字程度の簡潔なコメント。JSONのみ。

【4行目】本日の市場テーマを以下の候補から最大5個をカンマ区切りで出力（1行）。
候補: {theme_list}
例: high_dividend_jp,nisa,long_term,passive_income,index

【5行目以降】各銘柄の詳細解説を「### [順位]位 [銘柄名]（[ティッカー]）」の見出し形式で20件分。各解説は2〜3文。

重要: 1〜4行目は必ず1行で出力し、途中改行しないこと。"""

    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4096, system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"日付: {report_date}\n\n市場データ:\n{data_str}"
        }],
    )

    full_text = _extract_text(response).strip()
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    if len(lines) < 4:
        raise ValueError(f"AI response too short: {len(lines)} lines")

    # 1行目: 導入文
    intro = lines[0]

    # 2行目: ランキング
    ranking_raw = re.sub(r"[\[\]'\"`]", "", lines[1])
    ranking_raw = re.sub(r"^\s*json\s*[:：]?\s*", "", ranking_raw, flags=re.IGNORECASE)
    ranking_tickers = [t.strip() for t in ranking_raw.split(",") if t.strip()]

    # 3行目: 備考JSON
    remarks: Dict[str, str] = {}
    for cand in lines[2:6]:
        if "{" in cand and "}" in cand:
            try:
                s, e = cand.find("{"), cand.rfind("}") + 1
                remarks = json.loads(cand[s:e])
                break
            except Exception:
                continue

    # 4行目: テーマ（カンマ区切り、JSONや余分な記号を除去）
    themes: List[str] = []
    for cand in lines[3:6]:
        if "{" in cand or "###" in cand:
            continue
        raw = re.sub(r"[\[\]'\"`{}]", "", cand)
        candidates = [t.strip() for t in raw.split(",") if t.strip() and " " not in t.strip()]
        if candidates:
            themes = candidates[:5]
            break

    # 5行目以降: 詳細解説
    body_start = 4
    body_lines = []
    for l in lines[body_start:]:
        if l.startswith("```") or l.lower().strip() == "json":
            continue
        body_lines.append(l)
    body = "\n\n".join(body_lines)

    return intro, ranking_tickers, remarks, body, themes



# ---------------------------------------------------------------------------
# 時事ネタ連動タイトル生成
# ---------------------------------------------------------------------------
def _extract_topic_title(intro: str, news: List["NewsItem"]) -> str:
    """
    当日の市場動向・ニュースから読者が引きつけられるタイトルを生成する。
    intro と news の内容をキーワード解析し、最も強いテーマを反映したタイトルを返す。
    """
    combined = intro + " " + " ".join(n.title for n in news)

    # キーワード → タイトルテンプレートのマッピング（優先度順）
    patterns = [
        # 金利・日銀
        (["日銀", "利上げ", "金融正常化", "利下げ", "FOMC", "FRB"], "金利動向が変わる！銀行・高配当株の注目銘柄ベスト20"),
        # 為替・円安円高
        (["円安", "ドル高", "為替"], "円安局面で狙う！外貨収益・資源株の注目銘柄ベスト20"),
        (["円高", "ドル安"], "円高局面の守り方！ディフェンシブ高配当株の注目銘柄ベスト20"),
        # 半導体・AI・テクノロジー
        (["半導体", "AI", "人工知能", "NVIDIA", "エヌビディア", "テック"], "AI・半導体相場に乗る！テクノロジー関連と高配当株の注目銘柄ベスト20"),
        # 最高値・上昇相場
        (["最高値", "最高水準", "史上", "6万円", "最高値更新"], "日経最高値更新！上昇相場で配当を積み上げる注目銘柄ベスト20"),
        # 資源・原油
        (["原油", "資源", "エネルギー", "INPEX", "石油"], "資源価格上昇で恩恵！エネルギー・商社株の注目銘柄ベスト20"),
        # 決算・業績
        (["決算", "増益", "増配", "業績"], "好決算ラッシュ！増配・業績好調の注目銘柄ベスト20"),
        # 商社
        (["商社", "三菱商事", "伊藤忠", "バフェット"], "バフェットも注目！総合商社と高配当株の注目銘柄ベスト20"),
        # 銀行・金融
        (["銀行", "メガバンク", "金融", "三菱UFJ", "三井住友"], "金利上昇で輝く！銀行・金融株の注目銘柄ベスト20"),
        # NISA・新NISA
        (["NISA", "新NISA", "積立"], "新NISA活用！長期で育てる高配当・優待株の注目銘柄ベスト20"),
        # 不労所得・配当
        (["配当", "高配当", "不労所得", "インカム"], "配当金で不労所得を構築！高配当の注目銘柄ベスト20"),
        # 調整・下落
        (["調整", "下落", "急落", "売られ"], "調整局面は仕込みどき！押し目買いの注目高配当銘柄ベスト20"),
        # 米国株
        (["S&P", "ダウ", "米国株", "ナスダック"], "米国市場に連動！日米高配当株の注目銘柄ベスト20"),
    ]

    for keywords, template in patterns:
        if any(kw in combined for kw in keywords):
            return template

    # どれも一致しない場合のデフォルト
    return "市場を動かすテーマで選ぶ！高配当・優待株の注目銘柄ベスト20"


# ---------------------------------------------------------------------------
# Markdown 構築
# ---------------------------------------------------------------------------
def build_markdown(
    intro: str,
    prices: List[PriceInfo],
    ranking_tickers: List[str],
    remarks: Dict[str, str],
    body: str,
    news: List[NewsItem],
    selected_books: List[Dict],
    report_date: str,
) -> str:
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    if not final_list:
        final_list = prices[:20]

    description = (intro[:120] + "…") if len(intro) > 120 else intro
    description = description.replace('"', "'").replace("\n", " ")

    # --- frontmatter ---
    # 時事ネタ連動タイトルを生成（introの最初の話題から抽出）
    topic_title = _extract_topic_title(intro, news)

    fm = (
        "---\n"
        f'title: "{topic_title}"\n'
        f'description: "{description}"\n'
        f"pubDate: {report_date}\n"
        'category: "マーケット分析"\n'
        'tags: ["高配当株", "不労所得", "日次レポート"]\n'
        'author: "配当＆優待ナビ 編集部"\n'
        "draft: false\n"
        "---\n\n"
    )

    # --- 導入文 ---
    content = f'<div class="lead-text">{intro}</div>\n\n'

    # --- ニューストピック ---
    if news:
        content += "## 📰 ニューストピック\n\n"
        content += '<div class="news-list">\n'
        for n in news:
            t = (n.title or "").replace("<", "&lt;").replace(">", "&gt;")
            content += (
                f'  <a class="news-item" href="{n.link}" target="_blank" rel="noopener noreferrer">'
                f'<span class="news-date">{n.pub_date}</span>'
                f'<span class="news-title">{t}</span>'
                f'<span class="news-source">{n.source}</span>'
                '</a>\n'
            )
        content += "</div>\n\n"

    # --- ランキングテーブル ---
    content += "## 📊 本日の注目銘柄ベスト20\n\n"
    content += '<div class="table-wrapper"><table class="stock-table">\n'
    content += (
        "<thead><tr>"
        "<th>順位</th><th>コード</th><th>銘柄名</th><th>配当率</th>"
        "<th>終値</th><th>前日比</th><th>変化率</th><th>備考</th>"
        "</tr></thead>\n<tbody>\n"
    )
    for i, p in enumerate(final_list, 1):
        cls = "red-row" if p.change > 0 else ("green-row" if p.change < 0 else "")
        sign = "+" if p.change > 0 else ""
        remark = remarks.get(p.ticker, "—")
        content += (
            f'<tr class="{cls}">'
            f'<td class="text-center">{i}</td>'
            f'<td class="text-center"><strong>{p.ticker}</strong></td>'
            f"<td><strong>{p.name}</strong></td>"
            f'<td class="text-right">{p.yield_pc:.2f}%</td>'
            f'<td class="text-right">{fmt_price(p.close, p.ticker)}</td>'
            f'<td class="text-right">{fmt_change(p.change, p.ticker)}</td>'
            f'<td class="text-right">{sign}{p.change_pct:.2f}%</td>'
            f"<td>{remark}</td>"
            f"</tr>\n"
        )
    content += "</tbody></table></div>\n\n"

    # --- 詳細解説 ---
    content += "## 📝 各銘柄の詳細解説\n\n"
    content += body + "\n\n"

    # --- 書籍紹介 ---
    books_html = "\n## 📚 本日のテーマで選んだおすすめ投資書籍\n\n"
    for b in selected_books:
        cover_src = resolve_cover_src(b)
        aff_url = amazon_url(b["asin"])
        title_esc = b["title"].replace('"', "&quot;")
        books_html += (
            '<div class="book-item">'
            f'<a href="{aff_url}" target="_blank" rel="noopener noreferrer sponsored" class="book-cover-link">'
            f'<img src="{cover_src}" alt="{title_esc}" '
            'referrerpolicy="no-referrer" loading="lazy" '
            'onerror="this.onerror=null;this.style.opacity=\'0.25\';">'
            '</a>'
            '<div class="book-info">'
            f'<strong><a href="{aff_url}" target="_blank" rel="noopener noreferrer sponsored">{b["title"]}</a></strong>'
            f'<p class="book-author">著者: {b.get("author", "")}</p>'
            f'<p>{b["desc"]}</p>'
            "</div></div>\n\n"
        )

    disclaimer = (
        "\n---\n\n"
        '<div class="disclaimer-note">'
        "※ 本記事の情報は投資判断の参考を目的としており、特定銘柄の売買を推奨するものではありません。投資はご自身の判断と責任で行ってください。<br>"
        "※ 書籍リンクはAmazonアソシエイトプログラムを利用しています。"
        "</div>\n"
    )

    return fm + content + books_html + disclaimer


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 土日コラム：テーマ定義
# ---------------------------------------------------------------------------

# 土曜：投資初心者向けテーマ（ローテーション）
SATURDAY_TOPICS = [
    {
        "title": "「複利」の力を知れば投資が変わる――お金が雪だるま式に増える仕組み",
        "theme_keys": ["foundation", "long_term", "beginner"],
        "prompt": (
            "投資初心者向けに「複利」について解説する投資コラムを書いてください。"
            "\n・複利とはどういう仕組みか"
            "\n・単利との違いを具体的な数字で示す"
            "\n・新NISAで複利効果を最大化するコツ"
            "\n・長期投資への行動を促す前向きなまとめ"
            "\n文字数: 1,000〜1,500字。親しみやすく初心者が読んで実践できる内容にしてください。"
        ),
    },
    {
        "title": "高配当株とインデックス、どちらを選ぶべき？あなたのスタイルで選ぼう",
        "theme_keys": ["high_dividend_jp", "index", "beginner"],
        "prompt": (
            "投資初心者向けに「高配当株投資」と「インデックス投資」の違いと選び方を解説するコラムを書いてください。"
            "\n・それぞれの特徴とメリット・デメリット"
            "\n・どんな人に向いているか"
            "\n・両方組み合わせる方法"
            "\n文字数: 1,000〜1,500字。難しい用語は避け、具体例を交えて。"
        ),
    },
    {
        "title": "新NISAを今すぐ始めるべき理由――非課税のメリットを最大化する方法",
        "theme_keys": ["nisa", "beginner", "index"],
        "prompt": (
            "投資初心者向けに新NISAのメリットと始め方を解説するコラムを書いてください。"
            "\n・旧NISAとの違い"
            "\n・成長投資枠と積立投資枠の使い分け"
            "\n・初心者におすすめの銘柄・ETFの選び方"
            "\n文字数: 1,000〜1,500字。今すぐ行動できるよう背中を押す内容に。"
        ),
    },
    {
        "title": "投資で失敗しないために知っておくべき「分散投資」の基本",
        "theme_keys": ["beginner", "index", "psychology"],
        "prompt": (
            "投資初心者向けに分散投資の重要性と実践方法を解説するコラムを書いてください。"
            "\n・なぜ一点集中はリスクが高いのか"
            "\n・業種・地域・資産クラスの分散"
            "\n・少額から始められる分散投資の方法"
            "\n文字数: 1,000〜1,500字。身近な例えで分かりやすく。"
        ),
    },
    {
        "title": "配当金生活への第一歩――月3万円の不労所得を作るロードマップ",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "投資初心者向けに「配当金で月3万円の不労所得を作る」ための具体的なロードマップを解説するコラムを書いてください。"
            "\n・必要な投資額の目安"
            "\n・おすすめの高配当ETFや銘柄タイプ"
            "\n・配当再投資で加速させる方法"
            "\n文字数: 1,000〜1,500字。数字を交えて具体的に。"
        ),
    },
    {
        "title": "株価が下がっても慌てない！長期投資家のメンタル管理術",
        "theme_keys": ["psychology", "mindset", "long_term"],
        "prompt": (
            "投資初心者向けに「株価暴落時のメンタル管理」について解説するコラムを書いてください。"
            "\n・暴落は必ず来ると知っておく重要性"
            "\n・過去の暴落から学ぶ（リーマンショック・コロナショック等）"
            "\n・感情的な売却を防ぐ具体的な習慣"
            "\n文字数: 1,000〜1,500字。不安を和らげ、長期投資を続ける力が出る内容に。"
        ),
    },
    {
        "title": "ETFって何？投資信託との違いをわかりやすく解説",
        "theme_keys": ["beginner", "index", "nisa"],
        "prompt": (
            "投資初心者向けにETF（上場投資信託）の基本と投資信託との違いを解説するコラムを書いてください。"
            "\n・ETFの仕組みとメリット"
            "\n・投資信託との違い（コスト・流動性・分配金など）"
            "\n・初心者におすすめのETF選びのポイント"
            "\n文字数: 1,000〜1,500字。図解できない分、言葉で丁寧に。"
        ),
    },
]

# 日曜：FIRE・ライフスタイルテーマ（ローテーション）
SUNDAY_TOPICS = [
    {
        "title": "FIREを目指す前に知っておきたい「4%ルール」の真実",
        "theme_keys": ["fire", "philosophy", "long_term"],
        "prompt": (
            "FIRE（経済的独立・早期リタイア）を目指す読者向けに「4%ルール」について深掘りするコラムを書いてください。"
            "\n・4%ルールとは何か（トリニティスタディの解説）"
            "\n・日本でFIREする場合の注意点（税制・社会保険）"
            "\n・4%ルールの限界と補完する考え方"
            "\n文字数: 1,000〜1,500字。現実的かつ希望が持てる内容に。"
        ),
    },
    {
        "title": "お金を使い切って死ぬ――DIE WITH ZEROが教える豊かな人生設計",
        "theme_keys": ["lifestyle", "fire", "spending"],
        "prompt": (
            "「DIE WITH ZERO」の考え方をベースに、お金の使い方と人生設計について深掘りするコラムを書いてください。"
            "\n・お金を使わずに死ぬことの機会損失"
            "\n・経験にお金を使うことの価値"
            "\n・資産形成と人生の楽しみのバランス"
            "\n文字数: 1,000〜1,500字。投資と人生を両立する視点で。"
        ),
    },
    {
        "title": "サイドFIREという選択――完全リタイアしない「半リタイア」のすすめ",
        "theme_keys": ["fire", "lifestyle", "passive_income"],
        "prompt": (
            "サイドFIRE（半リタイア）という生き方について解説するコラムを書いてください。"
            "\n・完全FIREとサイドFIREの違い"
            "\n・サイドFIREのメリット（精神的安定・社会との接続）"
            "\n・サイドFIREに必要な資産と配当収入の目安"
            "\n文字数: 1,000〜1,500字。現実的に実現できる道を示す内容に。"
        ),
    },
    {
        "title": "高配当株で作る「給料日が毎月来る」ポートフォリオの設計法",
        "theme_keys": ["high_dividend_jp", "passive_income", "fire"],
        "prompt": (
            "高配当株を使って「毎月配当金が受け取れる」ポートフォリオを設計する方法を解説するコラムを書いてください。"
            "\n・日本株・米国株の配当月の違いを活用する"
            "\n・毎月分配の仕組みを作るポートフォリオ例"
            "\n・配当金を生活費の一部に組み込む考え方"
            "\n文字数: 1,000〜1,500字。具体的なイメージが持てる内容に。"
        ),
    },
    {
        "title": "投資家の「感情」がパフォーマンスを決める――行動経済学から学ぶお金の心理",
        "theme_keys": ["psychology", "behavior", "mindset"],
        "prompt": (
            "行動経済学の観点から「投資家の感情とパフォーマンスの関係」を解説するコラムを書いてください。"
            "\n・損失回避バイアスとは（損の痛みは得の喜びの2倍）"
            "\n・ホームカントリーバイアス・群衆心理の危険性"
            "\n・感情に左右されない投資習慣の作り方"
            "\n文字数: 1,000〜1,500字。自分の行動を振り返れる内容に。"
        ),
    },
    {
        "title": "ドルコスト平均法が最強の理由――「タイミング投資」との徹底比較",
        "theme_keys": ["dca", "data_driven", "long_term"],
        "prompt": (
            "ドルコスト平均法（定額積立投資）について、タイミング投資と比較しながら解説するコラムを書いてください。"
            "\n・ドルコスト平均法の仕組みと歴史的な実績"
            "\n・タイミング投資が失敗しやすい理由（統計的根拠）"
            "\n・新NISAの積立投資枠で実践する方法"
            "\n文字数: 1,000〜1,500字。データを使って説得力ある内容に。"
        ),
    },
    {
        "title": "老後2,000万円問題を冷静に考える――配当収入で「逃げ切り」は可能か",
        "theme_keys": ["fire", "foundation", "passive_income"],
        "prompt": (
            "「老後2,000万円問題」をテーマに、高配当投資で老後資金を作る現実的な方法を解説するコラムを書いてください。"
            "\n・2,000万円問題の本質（不足額の根拠を整理）"
            "\n・配当収入で不足分をカバーする試算"
            "\n・40代・50代から始めても間に合う積立戦略"
            "\n文字数: 1,000〜1,500字。不安を解消し前向きになれる内容に。"
        ),
    },
]


# ---------------------------------------------------------------------------
# 土日コラム生成
# ---------------------------------------------------------------------------
def generate_column(
    topic: Dict, books: List[Dict], report_date: str, day_label: str
) -> str:
    """Claude API でコラム本文を生成し Markdown を返す"""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = """あなたは投資・お金・ライフスタイルの専門ライターです。
読者は20〜40代の社会人で、投資に興味があるが忙しくてじっくり勉強できない方々です。
以下のルールで読みやすいコラムを書いてください:
- 親しみやすい文体（です・ます調）
- 難しい用語は平易な言葉で言い換える
- 具体的な数字や例えを使う
- 各段落は3〜5文程度でテンポよく
- 小見出し（##）を2〜3個入れて読みやすくする
- 冒頭で読者の共感を引く問いかけをする
- 末尾は行動を促す前向きなまとめで締める
- 文字数: 1,000〜1,500字"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": topic["prompt"]}],
    )
    body = _extract_text(response).strip()

    # 書籍選定
    selected_books = select_books_by_theme(books, topic["theme_keys"], count=3)

    # タイトル
    title = topic["title"]
    description = title[:80] + "…" if len(title) > 80 else title

    # frontmatter
    fm = (
        "---\n"
        f'title: "{title}"\n'
        f'description: "{description}"\n'
        f"pubDate: {report_date}\n"
        f'category: "{day_label}"\n'
        'tags: ["投資コラム", "高配当株", "不労所得"]\n'
        'author: "配当＆優待ナビ 編集部"\n'
        "draft: false\n"
        "---\n\n"
    )

    content = f'<div class="lead-text">{body.split(chr(10))[0]}</div>\n\n'
    content += "\n".join(body.split("\n")[1:]) + "\n\n"

    # 書籍紹介
    books_html = "\n## 📚 このコラムに合わせたおすすめ投資書籍\n\n"
    for b in selected_books:
        cover_src = b.get("cover_url") or resolve_cover_src(b)
        aff_url = amazon_url(b["asin"])
        title_esc = b["title"].replace('"', "&quot;")
        books_html += (
            '<div class="book-item">'
            f'<a href="{aff_url}" target="_blank" rel="noopener noreferrer sponsored" class="book-cover-link">'
            f'<img src="{cover_src}" alt="{title_esc}" '
            'referrerpolicy="no-referrer" loading="lazy" '
            'onerror="this.onerror=null;this.style.opacity=\'0.25\';">'
            '</a>'
            '<div class="book-info">'
            f'<strong><a href="{aff_url}" target="_blank" rel="noopener noreferrer sponsored">{b["title"]}</a></strong>'
            f'<p class="book-author">著者: {b.get("author", "")}</p>'
            f'<p>{b["desc"]}</p>'
            "</div></div>\n\n"
        )

    disclaimer = (
        "\n---\n\n"
        '<div class="disclaimer-note">'
        "※ 本記事の情報は投資判断の参考を目的としており、特定銘柄の売買を推奨するものではありません。投資はご自身の判断と責任で行ってください。<br>"
        "※ 書籍リンクはAmazonアソシエイトプログラムを利用しています。"
        "</div>\n"
    )

    return fm + content + books_html + disclaimer


def get_column_topic(weekday: int, report_date: str) -> tuple[Dict, str]:
    """
    weekday: 5=土曜, 6=日曜
    report_date: YYYY-MM-DD（週番号でローテーション）
    Returns: (topic, day_label)
    """
    # 週番号でローテーション（同じ週なら同じテーマ）
    week_num = datetime.strptime(report_date, "%Y-%m-%d").isocalendar()[1]

    if weekday == 5:  # 土曜
        topic = SATURDAY_TOPICS[week_num % len(SATURDAY_TOPICS)]
        return topic, "初心者ガイド"
    else:  # 日曜
        topic = SUNDAY_TOPICS[week_num % len(SUNDAY_TOPICS)]
        return topic, "投資戦略"

def main() -> int:
    now = datetime.now(TZ)
    report_date = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0=月, 1=火, ..., 5=土, 6=日

    try:
        books = load_books()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{report_date}.md"

        if weekday in (5, 6):
            # ── 土日：コラム記事を生成 ──────────────────────────────
            day_name = "土曜" if weekday == 5 else "日曜"
            print(f"[info] {day_name}コラムモードで生成します", file=sys.stderr)

            topic, day_label = get_column_topic(weekday, report_date)
            print(f"[info] Topic: {topic['title']}", file=sys.stderr)

            md = generate_column(topic, books, report_date, day_label)
        else:
            # ── 月〜金：株価レポートを生成 ──────────────────────────
            prices = collect_prices()
            if not prices:
                print("Error: 株価データ取得失敗", file=sys.stderr)
                return 1

            news = collect_news(max_items=5)
            intro, ranking, remarks, body, themes = generate_summary(prices, report_date)
            print(f"[info] AI themes: {themes}", file=sys.stderr)

            selected_books = select_books_by_theme(books, themes, count=3)
            print(f"[info] Selected books: {[b['id'] for b in selected_books]}", file=sys.stderr)

            md = build_markdown(
                intro, prices, ranking, remarks, body, news, selected_books, report_date
            )

        out_path.write_text(md, encoding="utf-8")
        print(f"Success: {out_path}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
    
