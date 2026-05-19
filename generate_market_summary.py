# -*- coding: utf-8 -*-
"""
配当＆優待ナビ｜日次レポート自動生成スクリプト（v4・安定出力修正版）

機能:
- yfinance で株価を取得
- Yahoo!ファイナンス RSS 等からニューストピックを分散して取得
- Anthropic API (claude-sonnet-4-6) で導入文・ランキング・備考・解説・所感・テーマ判定を生成
- テーマに基づいて books_data.json から最適な3冊を選書
- 書影は public/images/books/{ISBN13}.jpg を使用
- Amazon アフィリエイトリンク: https://www.amazon.co.jp/dp/{ASIN}?tag=investinsight-22
- frontmatter + 本文を src/content/blog/{YYYY-MM-DD}.mdx に書き出し
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

# ニュースRSS（複数媒体）
NEWS_RSS_URLS = [
    "https://news.yahoo.co.jp/rss/categories/business.xml",       # Yahoo!ニュース ビジネス
    "https://toyokeizai.net/list/feed/rss",                        # 東洋経済オンライン
    "https://www.lifehacker.jp/feed/index.xml",                    # ライフハッカー（マネー記事あり）
    "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",          # ITmedia NEWS
    "https://feeds.feedburner.com/zaikeicom",                      # 財経新聞
    "https://www.sankeibiz.jp/rss/news/macro.rss",                 # SankeiBiz マクロ経済
]

_MEDIA_NAMES: dict = {
    "yahoo.co.jp":      "Yahoo!ニュース",
    "toyokeizai.net":   "東洋経済オンライン",
    "lifehacker.jp":    "ライフハッカー",
    "itmedia.co.jp":    "ITmedia",
    "zaikei.co.jp":     "財経新聞",
    "sankeibiz.jp":     "SankeiBiz",
    "feedburner.com":   "財経新聞",
}

def _media_name_from_url(url: str) -> str:
    for domain, name in _MEDIA_NAMES.items():
        if domain in url:
            return name
    return "経済メディア"

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
# ---------------------------------------------------------------------------
# 書影URLキャッシュ（プロセス内メモリキャッシュ・APIコール削減）
# ---------------------------------------------------------------------------
_COVER_CACHE: Dict[str, str] = {}


def resolve_cover_src(book: Dict) -> str:
    """
    書影URLを解決する。
    openBD Cover API (cover.openbd.jp/{isbn13}.jpg) が日本書籍に最も確実。
    books_data.json の cover_url を優先し、なければ isbn13 から直接生成。
    """
    isbn13 = book.get("isbn13", "")
    if not isbn13:
        return _svg_placeholder(book)

    # キャッシュ確認
    if isbn13 in _COVER_CACHE:
        return _COVER_CACHE[isbn13]

    # books_data.json の cover_url を優先（openBD URLが設定されているはず）
    stored = book.get("cover_url", "")
    if stored and "r10s.jp" not in stored:
        _COVER_CACHE[isbn13] = stored
        return stored

    # isbn13 から openBD URL を直接生成（フォールバック）
    url = f"https://cover.openbd.jp/{isbn13}.jpg"
    _COVER_CACHE[isbn13] = url
    return url


def _cover_google_books(isbn13: str) -> Optional[str]:
    """Google Books Volumes API で書影URL取得（APIキー不要）"""
    try:
        api = (
            "https://www.googleapis.com/books/v1/volumes"
            f"?q=isbn:{urllib.parse.quote(isbn13)}&country=JP&maxResults=1"
        )
        req = urllib.request.Request(
            api, headers={"User-Agent": "astro-investment-blog/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not data.get("items"):
            return None
        links = (data["items"][0].get("volumeInfo") or {}).get("imageLinks") or {}
        for k in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            url = links.get(k)
            if url:
                # http→https、zoom=1で大きい画像を取得
                url = url.replace("http://", "https://")
                url = re.sub(r"zoom=\d+", "zoom=1", url)
                return url
    except Exception as e:
        print(f"[cover] google books fail {isbn13}: {e}", file=sys.stderr)
    return None


def _cover_openbd(isbn13: str) -> Optional[str]:
    """openBD API で書影URL取得"""
    try:
        api = f"https://api.openbd.jp/v1/get?isbn={urllib.parse.quote(isbn13)}"
        req = urllib.request.Request(
            api, headers={"User-Agent": "astro-investment-blog/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data and isinstance(data, list) and data[0]:
            cover = (data[0].get("summary") or {}).get("cover")
            if cover:
                return cover.replace("http://", "https://")
    except Exception as e:
        print(f"[cover] openbd fail {isbn13}: {e}", file=sys.stderr)
    return None


def _svg_placeholder(book: Dict) -> str:
    """テキストベースのSVGプレースホルダー"""
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
    """
    各ソースから均等に取得してから投資キーワードでスコアリングし、
    メディアが分散するようにピックアップする。
    """
    per_source = max(2, max_items)      # 各ソースから最大 per_source 件取得
    pool: List[NewsItem] = []
    seen_titles: set = set()

    for feed_url in NEWS_RSS_URLS:
        body = _http_get(feed_url, accept="application/rss+xml,application/xml,text/xml")
        if body is None:
            print(f"[news] fetch fail: {feed_url}", file=sys.stderr)
            continue
        try:
            text = body.decode("utf-8", errors="replace").lstrip("\ufeff")
            root = ET.fromstring(text)
        except Exception as e:
            print(f"[news] parse fail {feed_url}: {e}", file=sys.stderr)
            continue

        default_source = _media_name_from_url(feed_url)
        source_count = 0

        for it in root.iter("item"):
            if source_count >= per_source:
                break
            title_el = it.find("title")
            link_el  = it.find("link")
            date_el  = it.find("pubDate")
            src_el   = it.find("source")
            if title_el is None or link_el is None:
                continue
            title = (title_el.text or "").strip()
            link  = (link_el.text  or "").strip()
            if not title or not link or title in seen_titles:
                continue
            seen_titles.add(title)

            raw_date = (date_el.text or "").strip() if date_el is not None else ""
            source   = (src_el.text  or "").strip() if src_el is not None else ""
            if not source:
                source = default_source

            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(raw_date).astimezone(TZ)
                pub_date = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pub_date = raw_date[:16] if raw_date else ""

            pool.append(NewsItem(title=title, link=link, pub_date=pub_date, source=source))
            source_count += 1

        print(f"[news] {default_source}: {source_count}件取得", file=sys.stderr)

    # 投資関連キーワードでスコアリング
    keywords = ["株", "市場", "投資", "配当", "金利", "FRB", "日銀", "為替", "ドル",
                "円安", "円高", "決算", "業績", "増配", "NISA", "ETF", "国債", "原油",
                "インフレ", "利上げ", "利下げ", "景気", "経済", "東証", "日経"]
    
    # キーワードスコアを計算
    scored_pool = [(sum(1 for k in keywords if k in it.title), it) for it in pool]
    # スコアが高い順にソート
    scored_pool.sort(key=lambda x: x[0], reverse=True)

    result = []
    used_sources = set()

    # 1巡目: 偏りを防ぐため、各メディアから優先的に1件ずつピックアップ
    for score, it in scored_pool:
        if len(result) >= max_items:
            break
        if it.source not in used_sources:
            result.append(it)
            used_sources.add(it.source)

    # 2巡目: もし5件に満たない場合は、スコア順に残りを補充
    for score, it in scored_pool:
        if len(result) >= max_items:
            break
        if it not in result:
            result.append(it)
            
    sources = [it.source for it in result]
    print(f"[news] 採用 {len(result)}件: {sources}", file=sys.stderr)
    return result


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

    system_prompt = f"""あなたは高配当株・新NISA・株主優待への長期投資を実践している個人投資家ブロガー「ただの会社員」（45歳・新潟市在住・IT企業AI/DX推進部副部長・イオン株300株やNTT株など高配当株を保有）です。以下の厳密なフォーマットで日次の投資レポートを生成してください。

【1行目】経済全体の概況（アイスブレイク）を約300文字で記述。日本市場・米国市場・為替・金利動向に軽く触れ、長期投資家への前向きなメッセージで締める。改行を入れず必ず1行で。

【2行目】注目銘柄ベスト20のティッカーコードのみをカンマ区切りで列挙。例: 1489.T,9432.T,8306.T,...

【3行目】各銘柄の備考をJSONオブジェクト1行で出力。例: {{"1489.T":"増配基調で安定","9432.T":"通信インフラの王者"}}
備考は各銘柄15〜25文字程度の簡潔なコメント。JSONのみ。

【4行目】本日の市場テーマを以下の候補から最大5個をカンマ区切りで出力（1行）。
候補: {theme_list}
例: high_dividend_jp,nisa,long_term,passive_income,index

【5行目以降】各銘柄の詳細解説を「### [順位]位 [銘柄名]（[ティッカー]）」の見出し形式で出力すること。
※絶対厳守事項※：途中で省略せず、必ず「1位から20位まで」すべての銘柄（計20件）を出力してください。各解説は約150文字（3〜4文）とし、「私も実際に保有しており〜」など一人称コメントを各銘柄に1文ずつ入れること。

【記事の末尾】20件の解説が終わった後、必ず「### 投稿者の所感」という見出しを設けてください。新潟でのAI/DX推進業務や、心理学の知見、コア・サテライト戦略の実践などを自然に織り交ぜながら、当日の相場に対する個人的な総評を300文字程度で記述すること。

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
    themes: Optional[List[str]] = None,
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
        'author: "ただの会社員"\n'
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
        isbn13 = b.get('isbn13', '')
        books_html += (
            f'<div class="book-item" data-isbn="{isbn13}">'
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
# 平日：SEOキーワード特化記事（月〜金・ローテーション）
# ---------------------------------------------------------------------------
WEEKDAY_KEYWORD_TOPICS = [
    {
        "slug": "nihon-kabu-kohaito-ranking",
        "title": "日本株 高配当ランキング2026｜利回り4%超の厳選10銘柄",
        "keyword": "日本株 高配当 ランキング",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「日本株 高配当 ランキング」で検索するユーザー向けに、2026年の高配当日本株ランキングを解説する記事を書いてください。"
            "\n・利回り4%超の厳選10銘柄リスト（銘柄名・ティッカー・利回り目安）"
            "\n・ランキングの選定基準（配当継続性・財務健全性・増配実績）"
            "\n・セクター別の特徴（金融・通信・商社・資源・生活必需品）"
            "\n・高利回りだけで選ぶ危険性（減配リスクの確認方法）"
            "\n・新NISAでの活用方法"
            "\n文字数: 1,500〜2,000字。具体的な銘柄名と数字を使ってランキング形式で。"
        ),
    },
    {
        "slug": "haito-kabu-erabikata-shoshinja",
        "title": "高配当株の選び方【初心者向け】失敗しない5つのチェックポイント",
        "keyword": "高配当株 選び方 初心者",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "beginner", "passive_income"],
        "prompt": (
            "「高配当株 選び方 初心者」で検索するユーザー向けに、高配当株の選び方を解説する記事を書いてください。"
            "\n・配当利回りの計算方法と目安（3〜5%が狙い目の理由）"
            "\n・配当性向で持続性を確認する方法"
            "\n・減配リスクを避けるための財務チェック（自己資本比率・フリーCF）"
            "\n・業種分散の重要性"
            "\n・新NISAでの購入ステップ"
            "\n文字数: 1,500〜2,000字。初心者が迷わず行動できる内容に。"
        ),
    },
    {
        "slug": "nisa-tsumitate-index-vs-haito",
        "title": "新NISAは積立インデックスと高配当株どちらがいい？目的別に徹底比較",
        "keyword": "新NISA 積立 高配当 どっち",
        "category": "キーワード解説",
        "theme_keys": ["nisa", "index", "high_dividend_jp", "beginner"],
        "prompt": (
            "「新NISA 積立 高配当 どっち」で検索するユーザー向けに、積立インデックスと高配当株の使い分けを解説する記事を書いてください。"
            "\n・新NISAの積立投資枠と成長投資枠の違い"
            "\n・積立インデックス投資のメリット・向いている人"
            "\n・高配当株投資のメリット・向いている人"
            "\n・両方を組み合わせる理想的な配分例"
            "\n・年齢・目的別のおすすめ戦略"
            "\n文字数: 1,500〜2,000字。明確な結論を出す内容に。"
        ),
    },
    {
        "slug": "itochu-haito-shousha-hikaku",
        "title": "伊藤忠商事（8001）の配当と将来性｜三菱商事・三井物産と比較",
        "keyword": "伊藤忠商事 配当 将来性",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "long_term", "passive_income"],
        "prompt": (
            "「伊藤忠商事 配当 将来性」で検索するユーザー向けに、伊藤忠商事（8001）の投資価値を解説する記事を書いてください。"
            "\n・2026年の配当利回りと増配の推移"
            "\n・非資源型商社として安定している理由（ファミマ・繊維・食料）"
            "\n・三菱商事・三井物産との比較（利回り・成長性・安定性）"
            "\n・株価の割安・割高判断（PER・PBRの目安）"
            "\n・長期保有で期待できるリターンのシミュレーション"
            "\n文字数: 1,500〜2,000字。3大商社の比較を含めて客観的に。"
        ),
    },
    {
        "slug": "sumitomo-fudosan-kabu-haito",
        "title": "三井住友FG（8316）の配当利回りとROE｜メガバンク最高水準の理由",
        "keyword": "三井住友FG 配当 ROE",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「三井住友FG 配当 ROE」で検索するユーザー向けに、三井住友フィナンシャルグループ（8316）を解説する記事を書いてください。"
            "\n・2026年の配当利回りと増配の推移"
            "\n・メガバンク3社でROEが最高水準の理由"
            "\n・金利上昇局面での収益改善メカニズム"
            "\n・自社株買いと配当の組み合わせによる総還元利回り"
            "\n・三菱UFJ・みずほとの比較"
            "\n文字数: 1,500〜2,000字。ROEの数字を使って具体的に。"
        ),
    },
    {
        "slug": "haito-saito-rishi-keisan-hoho",
        "title": "配当再投資で資産が加速する仕組み｜複利効果を数字で実感する方法",
        "keyword": "配当 再投資 複利 計算",
        "category": "キーワード解説",
        "theme_keys": ["passive_income", "long_term", "dca", "foundation"],
        "prompt": (
            "「配当 再投資 複利 計算」で検索するユーザー向けに、配当再投資の複利効果を解説する記事を書いてください。"
            "\n・配当再投資とは何か（DRIPの仕組み）"
            "\n・100万円を利回り4%で20年運用した場合のシミュレーション"
            "\n・再投資なし vs 再投資ありの資産差（具体的な数字）"
            "\n・新NISAで配当再投資する際の注意点（課税タイミング）"
            "\n・実践的な再投資の方法（自動・手動）"
            "\n文字数: 1,500〜2,000字。数字で複利の威力を実感させる内容に。"
        ),
    },
    {
        "slug": "toyoda-jidosha-haito-ev",
        "title": "トヨタ自動車（7203）の配当と株価｜EV転換期の投資価値を分析",
        "keyword": "トヨタ 配当 株価 EV",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "long_term", "passive_income"],
        "prompt": (
            "「トヨタ 配当 株価 EV」で検索するユーザー向けに、トヨタ自動車（7203）の投資価値を解説する記事を書いてください。"
            "\n・2026年の配当利回りと直近の配当推移"
            "\n・EV戦略（全固体電池・ハイブリッド）が株価に与える影響"
            "\n・世界販売台数トップの安定性と財務の強さ"
            "\n・自動車セクターのリスク（円高・関税・EV競争）"
            "\n・長期保有の投資判断（配当目的 vs 成長目的）"
            "\n文字数: 1,500〜2,000字。EV転換期というタイムリーな視点を軸に。"
        ),
    },
    {
        "slug": "etf-1489-2516-hikaku-nisa",
        "title": "高配当ETF（1489 vs 2516）どっちがいい？特徴と利回りを徹底比較",
        "keyword": "高配当ETF 1489 2516 比較",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "nisa", "index", "passive_income"],
        "prompt": (
            "「高配当ETF 1489 2516 比較」で検索するユーザー向けに、日本の高配当ETF2本を徹底比較する記事を書いてください。"
            "\n・日経高配当50ETF（1489）の特徴・利回り・コスト"
            "\n・JPX高配当指数ETF（2516）の特徴・利回り・コスト"
            "\n・組み入れ銘柄の違い（重複・セクター比率）"
            "\n・どちらを選ぶべきか（目的別の結論）"
            "\n・新NISAでの購入方法と注意点"
            "\n文字数: 1,500〜2,000字。比較表を含めて決断しやすい内容に。"
        ),
    },
    {
        "slug": "kirin-ajinomoto-haito-shokuhin",
        "title": "食品・飲料株の高配当おすすめ｜キリン・味の素・マクドナルドを比較",
        "keyword": "食品株 高配当 おすすめ",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「食品株 高配当 おすすめ」で検索するユーザー向けに、食品・飲料セクターの高配当株を解説する記事を書いてください。"
            "\n・キリンHD（2503）：利回り・事業の特徴・安定性"
            "\n・味の素（2802）：利回り・グローバル展開・成長性"
            "\n・日本マクドナルドHD（2702）：利回り・優待・フランチャイズモデル"
            "\n・食品セクターがディフェンシブな理由（景気に左右されにくい）"
            "\n・3銘柄の比較と選び方のポイント"
            "\n文字数: 1,500〜2,000字。生活に身近な銘柄で親しみやすく。"
        ),
    },
    {
        "slug": "kabu-yutai-nisa-osusume",
        "title": "株主優待と配当の両取り戦略｜新NISAで始める優待株おすすめ5選",
        "keyword": "株主優待 配当 両取り NISA",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "nisa", "passive_income", "beginner"],
        "prompt": (
            "「株主優待 配当 両取り NISA」で検索するユーザー向けに、配当と優待を両取りできる銘柄戦略を解説する記事を書いてください。"
            "\n・配当＋優待の合計利回りの計算方法"
            "\n・おすすめ5銘柄（KDDI・イオン・すかいらーく・オリックス・日本マクドナルド）"
            "\n・各銘柄の配当利回り・優待内容・実質利回り"
            "\n・新NISAで優待株を保有する際の注意点"
            "\n・優待廃止リスクへの備え方"
            "\n文字数: 1,500〜2,000字。実質利回りの計算を丁寧に示す。"
        ),
    },
    {
        "slug": "roujin-2000-man-haito-kabu",
        "title": "老後2000万円を高配当株で作る｜40代・50代からでも間に合う積立戦略",
        "keyword": "老後2000万円 高配当株 積立",
        "category": "キーワード解説",
        "theme_keys": ["passive_income", "fire", "foundation", "long_term"],
        "prompt": (
            "「老後2000万円 高配当株 積立」で検索するユーザー向けに、高配当株で老後資金を作る方法を解説する記事を書いてください。"
            "\n・老後2000万円問題の本質（月約5.5万円の不足）"
            "\n・高配当株の配当金で不足分をカバーする計算式"
            "\n・40代から始めた場合のシミュレーション（毎月5万円積立）"
            "\n・50代からでも間に合う集中投資戦略"
            "\n・新NISAを最大活用した具体的なプラン"
            "\n文字数: 1,500〜2,000字。不安を希望に変える前向きな内容に。"
        ),
    },
    {
        "slug": "anahd-nipponyusen-kohaito-hikaku",
        "title": "ANAと日本郵船、高配当株として買えるか？景気敏感株の投資判断",
        "keyword": "ANA 日本郵船 高配当 景気敏感",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "psychology"],
        "prompt": (
            "「ANA 日本郵船 高配当 景気敏感」で検索するユーザー向けに、景気敏感な高配当株の投資判断を解説する記事を書いてください。"
            "\n・ANAホールディングス（9202）の配当と業績回復の現状"
            "\n・日本郵船（9101）の配当と海運市況の関係"
            "\n・景気敏感株特有のリスク（コロナ・リーマンショック時の減配実績）"
            "\n・ポートフォリオに景気敏感株を組み込む比率の考え方"
            "\n・ディフェンシブ株とのバランス戦略"
            "\n文字数: 1,500〜2,000字。リスクを正直に伝えながら活用法も示す。"
        ),
    },
    {
        "slug": "haito-kin-kakutei-bi-schedule",
        "title": "高配当株の配当金はいつもらえる？権利確定日・支払日の完全ガイド",
        "keyword": "配当金 いつ もらえる 権利確定日",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「配当金 いつ もらえる 権利確定日」で検索するユーザー向けに、配当スケジュールを完全解説する記事を書いてください。"
            "\n・権利確定日・権利付最終日・権利落ち日の違い"
            "\n・配当金の支払いまでのスケジュール（確定→支払いまで約3ヶ月）"
            "\n・3月・9月・12月決算の違いと受け取りタイミング"
            "\n・毎月配当を受け取るポートフォリオの作り方"
            "\n・新NISAで受け取る配当金の課税関係"
            "\n文字数: 1,500〜2,000字。初心者が混乱しやすいスケジュールを図解するように説明。"
        ),
    },
    {
        "slug": "shoken-kouza-haito-kabu-erabikata",
        "title": "高配当株投資を始める証券口座の選び方｜SBI・楽天・松井を比較",
        "keyword": "高配当株 証券口座 おすすめ",
        "category": "キーワード解説",
        "theme_keys": ["beginner", "nisa", "foundation"],
        "prompt": (
            "「高配当株 証券口座 おすすめ」で検索するユーザー向けに、高配当株投資に向いた証券口座を比較する記事を書いてください。"
            "\n・SBI証券：特徴・手数料・新NISA対応・ポイント"
            "\n・楽天証券：特徴・手数料・楽天ポイント連携"
            "\n・松井証券：特徴・手数料・サポート体制"
            "\n・高配当株投資で重視すべきポイント（手数料・銘柄数・NISA対応）"
            "\n・初心者に最もおすすめの証券口座と開設手順"
            "\n文字数: 1,500〜2,000字。具体的な結論を出す内容に。"
        ),
    },
]

def get_weekday_keyword_topic(report_date: str) -> Dict:
    """平日のキーワード記事トピックを日付から決定（ローテーション）"""
    from datetime import datetime as _dt
    day_of_year = _dt.strptime(report_date, "%Y-%m-%d").timetuple().tm_yday
    return WEEKDAY_KEYWORD_TOPICS[day_of_year % len(WEEKDAY_KEYWORD_TOPICS)]


# ---------------------------------------------------------------------------
# 土日：SEOキーワード特化記事
# ---------------------------------------------------------------------------
SATURDAY_TOPICS = [
    {
        "slug": "ntt-haito-rimawari-keisan",
        "title": "NTT（9432）の配当利回りを計算してみた｜2026年最新版",
        "keyword": "NTT 配当利回り 計算",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「NTT 配当利回り 計算」で検索するユーザー向けに、NTT（9432）の配当利回りを徹底解説する記事を書いてください。"
            "\n・配当利回りの計算式と現在の数値（2026年時点の目安）"
            "\n・過去5年の配当推移（増配傾向を示す）"
            "\n・NTTの配当が安定している理由（通信インフラ・独占的地位）"
            "\n・新NISAでNTT株を保有するメリット"
            "\n・配当金の実際の受け取り方（支払い月）"
            "\n文字数: 1,500〜2,000字。具体的な数字を多用し、検索意図に直接答える内容に。"
        ),
    },
    {
        "slug": "shin-nisa-kohaito-etf-osusume",
        "title": "新NISA 高配当ETFおすすめ3選｜1489・SPYD・VYMを徹底比較",
        "keyword": "新NISA 高配当ETF おすすめ",
        "category": "キーワード解説",
        "theme_keys": ["nisa", "high_dividend_jp", "high_dividend_us", "index"],
        "prompt": (
            "「新NISA 高配当ETF おすすめ」で検索するユーザー向けに、おすすめ高配当ETFを比較解説する記事を書いてください。"
            "\n・日経高配当50ETF（1489）：特徴・利回り・メリット"
            "\n・SPYD（米国高配当）：特徴・利回り・為替リスク"
            "\n・VYM（バンガード米国高配当）：特徴・利回り・安定性"
            "\n・どのETFをどんな人が選ぶべきか（初心者・中級者・分散したい人）"
            "\n・新NISAの成長投資枠との組み合わせ方"
            "\n文字数: 1,500〜2,000字。比較表も含め、決断を助ける内容に。"
        ),
    },
    {
        "slug": "mitsubishi-shoji-kabu-mitooshi",
        "title": "三菱商事（8058）の株価見通し2026｜配当・業績・バフェット効果を分析",
        "keyword": "三菱商事 株価 見通し",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "long_term", "passive_income"],
        "prompt": (
            "「三菱商事 株価 見通し」で検索するユーザー向けに、三菱商事（8058）の株価と投資価値を解説する記事を書いてください。"
            "\n・2026年時点の株価・PER・配当利回り"
            "\n・バークシャー・ハサウェイ（バフェット）の保有継続の意味"
            "\n・商社セクターが注目される理由（資源・インフラ・食料）"
            "\n・配当の推移と累進配当方針"
            "\n・長期保有する場合のリスクと注意点"
            "\n文字数: 1,500〜2,000字。投資判断の参考になる客観的な分析を。"
        ),
    },
    {
        "slug": "mufg-haito-rimawari-2026",
        "title": "三菱UFJ（8306）の配当利回り2026年版｜金利上昇で増配は続くか",
        "keyword": "三菱UFJ 配当利回り 2026",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「三菱UFJ 配当利回り 2026」で検索するユーザー向けに、三菱UFJ（8306）の配当と投資魅力を解説する記事を書いてください。"
            "\n・2026年の配当利回りの目安と計算方法"
            "\n・日銀の金利正常化がメガバンクに与える恩恵"
            "\n・過去5年の配当推移と増配見通し"
            "\n・株主還元（自社株買い）との組み合わせ効果"
            "\n・メガバンク3社（三菱UFJ・三井住友・みずほ）の比較"
            "\n文字数: 1,500〜2,000字。数字中心で分かりやすく。"
        ),
    },
    {
        "slug": "takeda-yakuhin-haito-2026",
        "title": "武田薬品（4502）の配当金はいつもらえる？利回り・権利確定日を解説",
        "keyword": "武田薬品 配当 いつ",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「武田薬品 配当 いつ」で検索するユーザー向けに、武田薬品（4502）の配当スケジュールと投資魅力を解説する記事を書いてください。"
            "\n・配当金の支払いスケジュール（権利確定日・支払い日）"
            "\n・2026年の配当利回りの目安"
            "\n・配当性向と継続性（グローバル製薬大手として安定した理由）"
            "\n・新NISAでの保有メリット"
            "\n・株価の注意点（円安・パイプラインリスク）"
            "\n文字数: 1,500〜2,000字。配当スケジュールを明確に示して。"
        ),
    },
    {
        "slug": "kddi-haito-yutai-hikaku",
        "title": "KDDI（9433）配当と優待どちらが魅力？利回り・株主優待を比較",
        "keyword": "KDDI 配当 優待",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「KDDI 配当 優待」で検索するユーザー向けに、KDDIの配当と株主優待を徹底解説する記事を書いてください。"
            "\n・2026年の配当利回りと直近の配当推移"
            "\n・株主優待の内容（カタログギフト）と実質利回り"
            "\n・配当＋優待の合計利回り計算"
            "\n・長期保有特典（3年以上でギフトアップ）の詳細"
            "\n・NTTとの比較（通信2社どちらを選ぶか）"
            "\n文字数: 1,500〜2,000字。配当と優待の両面から魅力を伝える内容に。"
        ),
    },
    {
        "slug": "sekisui-house-haito-ruishin",
        "title": "積水ハウス（1928）の累進配当とは？利回り4%超の高配当株を解説",
        "keyword": "積水ハウス 配当 累進",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「積水ハウス 配当 累進」で検索するユーザー向けに、積水ハウス（1928）の累進配当の魅力を解説する記事を書いてください。"
            "\n・累進配当方針とは何か（減配しないコミットメント）"
            "\n・2026年の配当利回りと過去10年の配当推移"
            "\n・住宅大手として安定している理由（ストック型ビジネス）"
            "\n・米国事業の拡大による成長期待"
            "\n・NISAで長期保有する場合のシミュレーション"
            "\n文字数: 1,500〜2,000字。累進配当の価値を丁寧に説明する内容に。"
        ),
    },
]

SUNDAY_TOPICS = [
    {
        "slug": "jt-haito-rimawari-2026",
        "title": "JT（2914）配当利回り4%超の理由と注意点｜2026年最新版",
        "keyword": "JT 配当 利回り",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「JT 配当 利回り」で検索するユーザー向けに、日本たばこ産業（JT・2914）の配当を徹底解説する記事を書いてください。"
            "\n・2026年の配当利回り計算（年間配当÷株価）"
            "\n・過去10年の配当推移（増配・維持・減配の歴史）"
            "\n・利回り4%超を維持できる理由（海外事業・稼ぐ力）"
            "\n・たばこ株特有のリスク（規制・ESG問題）"
            "\n・新NISAでの保有是非（非課税の恩恵 vs リスク）"
            "\n文字数: 1,500〜2,000字。メリット・デメリットをフラットに。"
        ),
    },
    {
        "slug": "inpex-haito-shigen-kabu",
        "title": "INPEX（1605）は高配当資源株の本命？利回り・原油連動リスクを解説",
        "keyword": "INPEX 配当 資源株",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「INPEX 配当 資源株」で検索するユーザー向けに、INPEX（1605）の投資価値を解説する記事を書いてください。"
            "\n・2026年の配当利回りと原油価格との連動性"
            "\n・エネルギー安全保障の観点からINPEXが重要な理由"
            "\n・資源株特有のリスク（原油価格下落時の減配リスク）"
            "\n・配当性向と株主還元の方針"
            "\n・ポートフォリオに資源株を入れる意味（分散効果）"
            "\n文字数: 1,500〜2,000字。リスクを正直に伝えながら魅力も示す。"
        ),
    },
    {
        "slug": "spyd-vym-hikaku-nisa",
        "title": "SPYD vs VYM どっちがいい？新NISAで選ぶ米国高配当ETF比較",
        "keyword": "SPYD VYM 比較 どっち",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_us", "nisa", "index_us"],
        "prompt": (
            "「SPYD VYM 比較 どっち」で検索するユーザー向けに、2つの米国高配当ETFを徹底比較する記事を書いてください。"
            "\n・SPYD：組み入れ銘柄・利回り・特徴・リスク"
            "\n・VYM：組み入れ銘柄・利回り・特徴・安定性"
            "\n・利回り重視ならSPYD、安定重視ならVYMの理由"
            "\n・新NISAでどちらを選ぶべきか（目的別の結論）"
            "\n・為替リスクへの対処法"
            "\n文字数: 1,500〜2,000字。明確な結論を出すことを意識して。"
        ),
    },
    {
        "slug": "nihon-yusen-kaisen-haito",
        "title": "日本郵船（9101）の配当はなぜ高い？海運株のリスクと将来性を解説",
        "keyword": "日本郵船 配当 海運",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「日本郵船 配当 海運」で検索するユーザー向けに、日本郵船（9101）の高配当の背景と注意点を解説する記事を書いてください。"
            "\n・2026年の配当利回りと配当の仕組み"
            "\n・コンテナ運賃と海運市況が配当に与える影響"
            "\n・過去の大幅増配・減配の歴史（景気敏感株の特性）"
            "\n・商船三井・川崎汽船との比較"
            "\n・高配当だけで判断する危険性と長期保有の考え方"
            "\n文字数: 1,500〜2,000字。景気敏感株のリスクをしっかり伝える。"
        ),
    },
    {
        "slug": "nisa-haito-kabu-poruto",
        "title": "新NISAで高配当株ポートフォリオを作る方法｜100万円から始める実例",
        "keyword": "新NISA 高配当株 ポートフォリオ",
        "category": "キーワード解説",
        "theme_keys": ["nisa", "high_dividend_jp", "passive_income", "beginner"],
        "prompt": (
            "「新NISA 高配当株 ポートフォリオ」で検索するユーザー向けに、実践的なポートフォリオ構築法を解説する記事を書いてください。"
            "\n・新NISAの成長投資枠（240万円/年）を使ったポートフォリオ設計"
            "\n・100万円から始める具体的な銘柄配分例（日本株・米国ETF）"
            "\n・セクター分散の考え方（金融・通信・商社・資源・生活必需品）"
            "\n・配当金の受け取りシミュレーション（年間・月換算）"
            "\n・定期的なリバランスの方法"
            "\n文字数: 1,500〜2,000字。具体的な数字と銘柄名を使って実践的に。"
        ),
    },
    {
        "slug": "mitsubishi-hc-capital-renzon-zozai",
        "title": "三菱HCキャピタル（8593）が連続増配を続ける理由｜リース株の魅力",
        "keyword": "三菱HCキャピタル 増配 連続",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "passive_income", "long_term"],
        "prompt": (
            "「三菱HCキャピタル 増配 連続」で検索するユーザー向けに、三菱HCキャピタル（8593）の連続増配の魅力を解説する記事を書いてください。"
            "\n・連続増配年数と増配の実績（具体的な数字）"
            "\n・リース業のビジネスモデルと安定収益の理由"
            "\n・配当利回りと配当性向（持続可能性の確認）"
            "\n・同じく連続増配の花王・三菱商事との比較"
            "\n・長期保有でどれだけ配当が増えるかシミュレーション"
            "\n文字数: 1,500〜2,000字。連続増配の価値を数字で実感させる内容に。"
        ),
    },
    {
        "slug": "kohaito-etf-1489-tokuchou",
        "title": "日経高配当50ETF（1489）の特徴と利回り｜新NISAで買うべきか徹底検証",
        "keyword": "日経高配当50ETF 1489 利回り",
        "category": "キーワード解説",
        "theme_keys": ["high_dividend_jp", "nisa", "index", "passive_income"],
        "prompt": (
            "「日経高配当50ETF 1489 利回り」で検索するユーザー向けに、1489の特徴と投資価値を解説する記事を書いてください。"
            "\n・日経高配当50ETFの仕組みと組み入れ銘柄の特徴"
            "\n・2026年の分配利回りの目安"
            "\n・信託報酬とコストの透明性"
            "\n・個別株との比較（分散効果 vs 利回り）"
            "\n・新NISAの成長投資枠で購入する方法と注意点"
            "\n文字数: 1,500〜2,000字。初心者でも分かるようにETFの基本から丁寧に。"
        ),
    },
]

# ---------------------------------------------------------------------------
# 記事カード SVG 透かしライブラリ
# ---------------------------------------------------------------------------

def _svg_watermark(title: str, category: str, themes: list) -> str:
    """
    記事タイトル・カテゴリー・テーマから最適なSVG透かしを返す。
    MDのHTMLブロックとして埋め込む。
    """
    t = title.lower()
    th = " ".join(themes).lower()

    if any(k in t for k in ["海運", "郵船", "船", "コンテナ"]):
        svg = _wm_ship()
    elif any(k in t for k in ["銀行", "メガバンク", "mufg", "三菱uf", "三井住友", "みずほ", "金利", "日銀"]):
        svg = _wm_bank()
    elif any(k in t for k in ["nisa", "新nisa", "積立", "非課税"]):
        svg = _wm_nisa()
    elif any(k in t for k in ["複利", "再投資", "雪だるま", "指数"]):
        svg = _wm_compound()
    elif any(k in t for k in ["ポートフォリオ", "毎月", "分散", "配分", "給料"]):
        svg = _wm_portfolio()
    elif any(k in t for k in ["商社", "三菱商事", "伊藤忠", "資源", "inpex", "原油"]):
        svg = _wm_trading_company()
    elif any(k in t for k in ["etf", "インデックス", "1489", "spyd", "vym", "積立"]):
        svg = _wm_etf()
    elif any(k in t for k in ["配当利回り", "利回り", "配当金", "配当率", "高配当"]):
        svg = _wm_dividend()
    elif any(k in t for k in ["最高値", "上昇", "ベスト20", "注目銘柄", "レポート"]):
        svg = _wm_chart_up()
    elif any(k in t for k in ["初心者", "始め", "選び方", "証券口座", "開設"]):
        svg = _wm_beginner()
    elif any(k in t for k in ["fire", "リタイア", "老後", "セミリタイア"]):
        svg = _wm_fire()
    elif any(k in t for k in ["優待", "株主優待"]):
        svg = _wm_yutai()
    elif category == "キーワード解説":
        svg = _wm_search()
    elif category == "マーケット分析":
        svg = _wm_chart_up()
    else:
        svg = _wm_chart_up()

    return (
        '<div class="card-watermark" aria-hidden="true">\n'
        + svg + "\n</div>\n"
    )

def _wm_chart_up() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <line x1="0" y1="140" x2="320" y2="140" stroke="#1d4ed8" stroke-width="0.8"/>
  <line x1="0" y1="105" x2="320" y2="105" stroke="#1d4ed8" stroke-width="0.5" stroke-dasharray="4,4"/>
  <line x1="0" y1="70" x2="320" y2="70" stroke="#1d4ed8" stroke-width="0.5" stroke-dasharray="4,4"/>
  <line x1="0" y1="35" x2="320" y2="35" stroke="#1d4ed8" stroke-width="0.5" stroke-dasharray="4,4"/>
  <line x1="64" y1="20" x2="64" y2="150" stroke="#1d4ed8" stroke-width="0.4" stroke-dasharray="3,5"/>
  <line x1="128" y1="20" x2="128" y2="150" stroke="#1d4ed8" stroke-width="0.4" stroke-dasharray="3,5"/>
  <line x1="192" y1="20" x2="192" y2="150" stroke="#1d4ed8" stroke-width="0.4" stroke-dasharray="3,5"/>
  <line x1="256" y1="20" x2="256" y2="150" stroke="#1d4ed8" stroke-width="0.4" stroke-dasharray="3,5"/>
  <path d="M0,130 L40,120 L80,108 L120,95 L160,80 L200,55 L240,40 L280,25 L320,15 L320,150 L0,150Z" fill="#1d4ed8" opacity="0.3"/>
  <polyline points="0,130 40,120 80,108 120,95 160,80 200,55 240,40 280,25 320,15" fill="none" stroke="#1d4ed8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="40" y1="112" x2="40" y2="128" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="34" y="116" width="12" height="8" fill="none" stroke="#1d4ed8" stroke-width="1.5" rx="1"/>
  <line x1="120" y1="88" x2="120" y2="102" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="114" y="91" width="12" height="8" fill="#1d4ed8" rx="1"/>
  <line x1="200" y1="48" x2="200" y2="62" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="194" y="51" width="12" height="8" fill="none" stroke="#1d4ed8" stroke-width="1.5" rx="1"/>
  <line x1="280" y1="18" x2="280" y2="32" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="274" y="21" width="12" height="8" fill="#1d4ed8" rx="1"/>
  <path d="M270,110 L295,80 L310,85 L295,60 L280,65 L295,45" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <polygon points="295,38 287,52 303,52" fill="#1d4ed8"/>
</svg>"""

def _wm_compound() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <path d="M0,165 Q80,160 120,145 Q180,120 220,85 Q270,40 320,10 L320,170 L0,170Z" fill="#166534" opacity="0.25"/>
  <path d="M0,165 Q80,160 120,145 Q180,120 220,85 Q270,40 320,10" fill="none" stroke="#166534" stroke-width="2.5"/>
  <circle cx="60" cy="148" r="10" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="100" cy="138" r="15" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="150" cy="120" r="22" fill="none" stroke="#166534" stroke-width="1.8"/>
  <circle cx="215" cy="90" r="30" fill="none" stroke="#166534" stroke-width="2"/>
  <circle cx="290" cy="48" r="40" fill="none" stroke="#166534" stroke-width="2"/>
  <line x1="60" y1="158" x2="60" y2="168" stroke="#166534" stroke-width="1"/>
  <line x1="150" y1="142" x2="150" y2="168" stroke="#166534" stroke-width="1"/>
  <line x1="290" y1="88" x2="290" y2="168" stroke="#166534" stroke-width="1"/>
  <ellipse cx="55" cy="30" rx="12" ry="5" fill="none" stroke="#166534" stroke-width="1.5"/>
  <line x1="43" y1="30" x2="43" y2="42" stroke="#166534" stroke-width="1.5"/>
  <line x1="67" y1="30" x2="67" y2="42" stroke="#166534" stroke-width="1.5"/>
  <ellipse cx="55" cy="42" rx="12" ry="5" fill="none" stroke="#166534" stroke-width="1.5"/>
  <path d="M80,35 Q110,15 130,38" fill="none" stroke="#166534" stroke-width="1.5" stroke-dasharray="3,3"/>
  <polygon points="130,38 122,30 126,42" fill="#166534"/>
</svg>"""

def _wm_portfolio() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <circle cx="95" cy="88" r="70" fill="none" stroke="#92400e" stroke-width="1"/>
  <path d="M95,88 L95,18 A70,70 0 0,1 156,123 Z" fill="#92400e" opacity="0.5"/>
  <path d="M95,88 L156,123 A70,70 0 0,1 34,123 Z" fill="#92400e" opacity="0.3"/>
  <path d="M95,88 L34,123 A70,70 0 0,1 34,53 Z" fill="#92400e" opacity="0.15"/>
  <path d="M95,88 L34,53 A70,70 0 0,1 95,18 Z" fill="#92400e" opacity="0.08"/>
  <circle cx="95" cy="88" r="30" fill="var(--color-background-primary)"/>
  <rect x="185" y="15" width="120" height="145" fill="none" stroke="#92400e" stroke-width="1" rx="4"/>
  <line x1="185" y1="35" x2="305" y2="35" stroke="#92400e" stroke-width="1"/>
  <rect x="192" y="42" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="223" y="42" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="254" y="42" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="285" y="42" width="16" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="192" y="66" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="223" y="66" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="254" y="66" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="285" y="66" width="16" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="192" y="90" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="223" y="90" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="254" y="90" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="285" y="90" width="16" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="192" y="114" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="223" y="114" width="27" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <rect x="254" y="114" width="27" height="20" rx="2" fill="#92400e" opacity="0.2"/>
  <rect x="285" y="114" width="16" height="20" rx="2" fill="#92400e" opacity="0.4"/>
  <circle cx="210" cy="140" r="6" fill="none" stroke="#92400e" stroke-width="1.5"/>
  <circle cx="235" cy="148" r="7" fill="none" stroke="#92400e" stroke-width="1.5"/>
  <circle cx="260" cy="140" r="8" fill="none" stroke="#92400e" stroke-width="1.5"/>
</svg>"""

def _wm_ship() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <path d="M0,125 Q40,113 80,125 Q120,137 160,125 Q200,113 240,125 Q280,137 320,125 L320,170 L0,170Z" fill="#166534" opacity="0.2"/>
  <path d="M0,135 Q40,123 80,135 Q120,147 160,135 Q200,123 240,135 Q280,147 320,135" fill="none" stroke="#166534" stroke-width="1.5"/>
  <path d="M0,150 Q40,138 80,150 Q120,162 160,150 Q200,138 240,150 Q280,162 320,150" fill="none" stroke="#166534" stroke-width="1" opacity="0.6"/>
  <path d="M25,122 L25,80 L270,80 L295,122 Z" fill="none" stroke="#166534" stroke-width="2"/>
  <rect x="55" y="52" width="170" height="28" fill="none" stroke="#166534" stroke-width="1.5" rx="2"/>
  <rect x="195" y="25" width="55" height="27" fill="none" stroke="#166534" stroke-width="1.5" rx="2"/>
  <rect x="204" y="32" width="9" height="8" rx="1" fill="none" stroke="#166534" stroke-width="1"/>
  <rect x="219" y="32" width="9" height="8" rx="1" fill="none" stroke="#166634" stroke-width="1"/>
  <rect x="234" y="32" width="9" height="8" rx="1" fill="none" stroke="#166534" stroke-width="1"/>
  <rect x="65" y="58" width="24" height="16" fill="none" stroke="#166534" stroke-width="1" rx="1"/>
  <rect x="93" y="58" width="24" height="16" fill="none" stroke="#166534" stroke-width="1" rx="1"/>
  <rect x="121" y="58" width="24" height="16" fill="none" stroke="#166534" stroke-width="1" rx="1"/>
  <rect x="149" y="58" width="24" height="16" fill="none" stroke="#166534" stroke-width="1" rx="1"/>
  <rect x="177" y="58" width="24" height="16" fill="none" stroke="#166534" stroke-width="1" rx="1"/>
  <rect x="218" y="12" width="11" height="13" fill="none" stroke="#166534" stroke-width="1.5"/>
  <path d="M224,12 Q218,4 224,0 Q230,0 224,0" fill="none" stroke="#166534" stroke-width="1" opacity="0.5"/>
  <line x1="5" y1="15" x2="5" y2="75" stroke="#166534" stroke-width="1" opacity="0.5"/>
  <line x1="5" y1="75" x2="50" y2="75" stroke="#166534" stroke-width="1" opacity="0.5"/>
  <rect x="10" y="52" width="9" height="23" fill="#166534" opacity="0.35"/>
  <rect x="23" y="40" width="9" height="35" fill="#166534" opacity="0.35"/>
  <rect x="36" y="47" width="9" height="28" fill="#166534" opacity="0.35"/>
</svg>"""

def _wm_bank() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <rect x="55" y="72" width="210" height="90" fill="none" stroke="#1d4ed8" stroke-width="2"/>
  <path d="M45,72 L160,18 L275,72 Z" fill="none" stroke="#1d4ed8" stroke-width="2"/>
  <rect x="75" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="105" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="135" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="165" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="195" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="225" y="72" width="13" height="90" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <rect x="140" y="122" width="40" height="40" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <polyline points="270,30 288,20 305,10 320,2" fill="none" stroke="#1d4ed8" stroke-width="2"/>
  <polygon points="320,2 312,10 322,12" fill="#1d4ed8"/>
  <line x1="265" y1="38" x2="265" y2="2" stroke="#1d4ed8" stroke-width="1" opacity="0.5"/>
  <line x1="265" y1="38" x2="322" y2="38" stroke="#1d4ed8" stroke-width="1" opacity="0.5"/>
  <circle cx="22" cy="100" r="16" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>
  <circle cx="22" cy="100" r="10" fill="none" stroke="#1d4ed8" stroke-width="1"/>
  <circle cx="22" cy="132" r="14" fill="none" stroke="#1d4ed8" stroke-width="1.5" opacity="0.7"/>
  <circle cx="22" cy="158" r="10" fill="none" stroke="#1d4ed8" stroke-width="1.5" opacity="0.4"/>
</svg>"""

def _wm_nisa() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <line x1="18" y1="8" x2="18" y2="158" stroke="#6b21a8" stroke-width="1.5"/>
  <line x1="18" y1="158" x2="225" y2="158" stroke="#6b21a8" stroke-width="1.5"/>
  <rect x="28" y="132" width="24" height="26" fill="#6b21a8" opacity="0.3" rx="2"/>
  <rect x="58" y="115" width="24" height="43" fill="#6b21a8" opacity="0.35" rx="2"/>
  <rect x="88" y="96" width="24" height="62" fill="#6b21a8" opacity="0.4" rx="2"/>
  <rect x="118" y="74" width="24" height="84" fill="#6b21a8" opacity="0.45" rx="2"/>
  <rect x="148" y="50" width="24" height="108" fill="#6b21a8" opacity="0.5" rx="2"/>
  <rect x="178" y="24" width="24" height="134" fill="#6b21a8" opacity="0.6" rx="2"/>
  <polyline points="40,132 70,115 100,96 130,74 160,50 190,24" fill="none" stroke="#6b21a8" stroke-width="1.5" stroke-dasharray="3,2"/>
  <rect x="232" y="12" width="82" height="30" rx="15" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <path d="M248,30 L258,18 L262,22 L272,10 L276,14 L286,8" fill="none" stroke="#6b21a8" stroke-width="1.5" stroke-linecap="round"/>
  <path d="M242,75 L262,52 L282,75 Z" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <rect x="250" y="75" width="24" height="32" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <rect x="256" y="85" width="11" height="22" fill="none" stroke="#6b21a8" stroke-width="1"/>
  <circle cx="250" cy="135" r="9" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <circle cx="268" cy="142" r="11" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <circle cx="290" cy="135" r="14" fill="none" stroke="#6b21a8" stroke-width="1.5"/>
  <line x1="300" y1="42" x2="318" y2="42" stroke="#6b21a8" stroke-width="2"/>
  <line x1="309" y1="33" x2="309" y2="51" stroke="#6b21a8" stroke-width="2"/>
</svg>"""

def _wm_trading_company() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <circle cx="160" cy="85" r="65" fill="none" stroke="#92400e" stroke-width="1.5"/>
  <ellipse cx="160" cy="85" rx="30" ry="65" fill="none" stroke="#92400e" stroke-width="1"/>
  <line x1="95" y1="85" x2="225" y2="85" stroke="#92400e" stroke-width="1"/>
  <line x1="100" y1="55" x2="220" y2="55" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3"/>
  <line x1="100" y1="115" x2="220" y2="115" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3"/>
  <path d="M100,30 Q160,22 220,30" fill="none" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3"/>
  <path d="M100,140 Q160,148 220,140" fill="none" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3"/>
  <line x1="160" y1="20" x2="160" y2="150" stroke="#92400e" stroke-width="1"/>
  <rect x="10" y="60" width="60" height="50" rx="4" fill="none" stroke="#92400e" stroke-width="1.5"/>
  <line x1="25" y1="75" x2="55" y2="75" stroke="#92400e" stroke-width="1.2"/>
  <line x1="25" y1="85" x2="55" y2="85" stroke="#92400e" stroke-width="1.2"/>
  <line x1="25" y1="95" x2="45" y2="95" stroke="#92400e" stroke-width="1.2"/>
  <rect x="250" y="60" width="60" height="50" rx="4" fill="none" stroke="#92400e" stroke-width="1.5"/>
  <line x1="265" y1="75" x2="295" y2="75" stroke="#92400e" stroke-width="1.2"/>
  <line x1="265" y1="85" x2="295" y2="85" stroke="#92400e" stroke-width="1.2"/>
  <line x1="265" y1="95" x2="285" y2="95" stroke="#92400e" stroke-width="1.2"/>
  <path d="M70,85 L95,85" fill="none" stroke="#92400e" stroke-width="1.5" marker-end="url(#arr)"/>
  <path d="M225,85 L250,85" fill="none" stroke="#92400e" stroke-width="1.5"/>
</svg>"""

def _wm_etf() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <line x1="15" y1="10" x2="15" y2="155" stroke="#1d4ed8" stroke-width="1.5"/>
  <line x1="15" y1="155" x2="310" y2="155" stroke="#1d4ed8" stroke-width="1.5"/>
  <path d="M15,130 Q80,115 130,100 Q180,85 240,60 Q280,45 305,30" fill="none" stroke="#1d4ed8" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M15,140 Q80,128 130,115 Q180,100 240,78 Q280,62 305,48" fill="none" stroke="#1d4ed8" stroke-width="1" stroke-dasharray="4,3" opacity="0.5"/>
  <path d="M15,155 Q80,145 130,132 Q180,118 240,95 Q280,78 305,65 L305,155Z" fill="#1d4ed8" opacity="0.12"/>
  <circle cx="130" cy="100" r="5" fill="#1d4ed8"/>
  <circle cx="240" cy="60" r="5" fill="#1d4ed8"/>
  <circle cx="305" cy="30" r="5" fill="#1d4ed8"/>
  <rect x="30" y="10" width="40" height="16" rx="3" fill="none" stroke="#1d4ed8" stroke-width="1"/>
  <rect x="80" y="10" width="40" height="16" rx="3" fill="none" stroke="#1d4ed8" stroke-width="1"/>
  <rect x="130" y="10" width="40" height="16" rx="3" fill="none" stroke="#1d4ed8" stroke-width="1"/>
  <rect x="180" y="10" width="40" height="16" rx="3" fill="#1d4ed8" opacity="0.3" rx="3"/>
  <rect x="230" y="10" width="40" height="16" rx="3" fill="none" stroke="#1d4ed8" stroke-width="1"/>
  <rect x="280" y="10" width="30" height="16" rx="3" fill="none" stroke="#1d4ed8" stroke-width="1"/>
</svg>"""

def _wm_dividend() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <circle cx="80" cy="70" r="55" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="80" cy="70" r="38" fill="none" stroke="#166534" stroke-width="1"/>
  <circle cx="80" cy="70" r="22" fill="none" stroke="#166534" stroke-width="1"/>
  <circle cx="80" cy="70" r="8" fill="#166534" opacity="0.4"/>
  <line x1="80" y1="15" x2="80" y2="125" stroke="#166534" stroke-width="0.8" stroke-dasharray="2,3"/>
  <line x1="25" y1="70" x2="135" y2="70" stroke="#166534" stroke-width="0.8" stroke-dasharray="2,3"/>
  <rect x="160" y="20" width="28" height="40" fill="#166534" opacity="0.25" rx="2"/>
  <rect x="196" y="35" width="28" height="25" fill="#166534" opacity="0.35" rx="2"/>
  <rect x="232" y="10" width="28" height="50" fill="#166534" opacity="0.45" rx="2"/>
  <rect x="268" y="25" width="28" height="35" fill="#166534" opacity="0.3" rx="2"/>
  <line x1="155" y1="65" x2="300" y2="65" stroke="#166534" stroke-width="1"/>
  <line x1="155" y1="65" x2="155" y2="10" stroke="#166534" stroke-width="1"/>
  <path d="M160,60 L185,48 L220,22 L248,38 L282,15" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="160" cy="115" r="18" fill="none" stroke="#166534" stroke-width="1.5"/>
  <line x1="155" y1="115" x2="165" y2="115" stroke="#166534" stroke-width="1.5"/>
  <line x1="160" y1="110" x2="160" y2="120" stroke="#166534" stroke-width="1.5"/>
  <circle cx="210" cy="130" r="14" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="255" cy="120" r="18" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="300" cy="132" r="12" fill="none" stroke="#166534" stroke-width="1.5"/>
</svg>"""

def _wm_beginner() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <path d="M160,10 C120,10 88,40 88,75 C88,100 102,120 122,130 L122,148 L198,148 L198,130 C218,120 232,100 232,75 C232,40 200,10 160,10 Z" fill="none" stroke="#6b21a8" stroke-width="2"/>
  <line x1="122" y1="155" x2="198" y2="155" stroke="#6b21a8" stroke-width="2" stroke-linecap="round"/>
  <line x1="130" y1="162" x2="190" y2="162" stroke="#6b21a8" stroke-width="1.5" stroke-linecap="round"/>
  <line x1="160" y1="40" x2="160" y2="70" stroke="#6b21a8" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="160" cy="82" r="5" fill="#6b21a8"/>
  <line x1="20" y1="20" x2="20" y2="160" stroke="#6b21a8" stroke-width="1" opacity="0.4"/>
  <line x1="20" y1="160" x2="80" y2="160" stroke="#6b21a8" stroke-width="1" opacity="0.4"/>
  <rect x="25" y="130" width="14" height="30" fill="#6b21a8" opacity="0.25" rx="1"/>
  <rect x="43" y="110" width="14" height="50" fill="#6b21a8" opacity="0.3" rx="1"/>
  <rect x="61" y="90" width="14" height="70" fill="#6b21a8" opacity="0.35" rx="1"/>
  <line x1="250" y1="20" x2="250" y2="160" stroke="#6b21a8" stroke-width="1" opacity="0.4"/>
  <line x1="250" y1="160" x2="310" y2="160" stroke="#6b21a8" stroke-width="1" opacity="0.4"/>
  <rect x="255" y="120" width="14" height="40" fill="#6b21a8" opacity="0.25" rx="1"/>
  <rect x="273" y="100" width="14" height="60" fill="#6b21a8" opacity="0.3" rx="1"/>
  <rect x="291" y="80" width="14" height="80" fill="#6b21a8" opacity="0.35" rx="1"/>
</svg>"""

def _wm_fire() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <path d="M160,165 C100,165 55,130 55,88 C55,60 72,40 88,28 C82,48 90,60 102,58 C88,38 105,10 130,5 C118,25 128,45 145,48 C138,32 150,15 165,12 C155,30 165,52 178,55 C170,35 185,18 200,22 C188,38 192,58 205,62 C222,50 235,30 228,10 C250,28 265,58 258,88 C265,78 268,62 265,48 C278,62 285,82 285,100 C285,135 228,165 160,165 Z" fill="none" stroke="#92400e" stroke-width="2"/>
  <path d="M160,155 C120,155 88,132 88,105 C88,88 98,75 110,68 C106,80 112,90 122,88 C112,75 122,58 138,55 C130,68 138,82 150,82 C145,70 155,58 165,58 C158,70 165,84 175,85 C168,72 178,58 188,62 C180,75 182,90 192,92 C202,82 208,65 205,52 C218,68 222,88 218,105 C222,98 225,88 222,78 C230,90 232,105 232,115 C232,138 200,155 160,155 Z" fill="#92400e" opacity="0.2"/>
  <line x1="10" y1="165" x2="310" y2="165" stroke="#92400e" stroke-width="1.5"/>
  <line x1="10" y1="10" x2="10" y2="165" stroke="#92400e" stroke-width="1" opacity="0.5"/>
  <line x1="10" y1="90" x2="45" y2="90" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3" opacity="0.5"/>
  <line x1="10" y1="40" x2="45" y2="40" stroke="#92400e" stroke-width="0.8" stroke-dasharray="3,3" opacity="0.5"/>
</svg>"""

def _wm_yutai() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <rect x="60" y="30" width="200" height="130" rx="8" fill="none" stroke="#166534" stroke-width="2"/>
  <rect x="60" y="30" width="200" height="35" rx="8" fill="none" stroke="#166534" stroke-width="1"/>
  <line x1="160" y1="65" x2="160" y2="160" stroke="#166534" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="60" y1="112" x2="260" y2="112" stroke="#166534" stroke-width="1" stroke-dasharray="3,3"/>
  <circle cx="110" cy="88" r="15" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="110" cy="135" r="12" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="210" cy="88" r="18" fill="none" stroke="#166534" stroke-width="1.5"/>
  <circle cx="210" cy="135" r="14" fill="none" stroke="#166534" stroke-width="1.5"/>
  <path d="M100,43 L108,55 L120,38" fill="none" stroke="#166534" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M195,43 L203,55 L215,38" fill="none" stroke="#166534" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="10" y1="30" x2="40" y2="30" stroke="#166534" stroke-width="1.5"/>
  <line x1="10" y1="60" x2="40" y2="60" stroke="#166534" stroke-width="1.5"/>
  <line x1="10" y1="90" x2="40" y2="90" stroke="#166534" stroke-width="1.5"/>
  <line x1="10" y1="120" x2="40" y2="120" stroke="#166534" stroke-width="1.5"/>
  <line x1="10" y1="150" x2="40" y2="150" stroke="#166534" stroke-width="1.5"/>
  <line x1="280" y1="30" x2="310" y2="30" stroke="#166534" stroke-width="1.5"/>
  <line x1="280" y1="60" x2="310" y2="60" stroke="#166534" stroke-width="1.5"/>
  <line x1="280" y1="90" x2="310" y2="90" stroke="#166534" stroke-width="1.5"/>
  <line x1="280" y1="120" x2="310" y2="120" stroke="#166534" stroke-width="1.5"/>
  <line x1="280" y1="150" x2="310" y2="150" stroke="#166534" stroke-width="1.5"/>
</svg>"""

def _wm_search() -> str:
    return """<svg viewBox="0 0 320 170" xmlns="[http://www.w3.org/2000/svg](http://www.w3.org/2000/svg)" preserveAspectRatio="xMidYMid slice">
  <circle cx="130" cy="80" r="60" fill="none" stroke="#166534" stroke-width="2"/>
  <circle cx="130" cy="80" r="42" fill="none" stroke="#166534" stroke-width="1" opacity="0.5"/>
  <circle cx="130" cy="80" r="24" fill="none" stroke="#166534" stroke-width="0.8" opacity="0.3"/>
  <line x1="178" y1="128" x2="255" y2="160" stroke="#166534" stroke-width="5" stroke-linecap="round"/>
  <line x1="100" y1="68" x2="160" y2="68" stroke="#166534" stroke-width="2" stroke-linecap="round"/>
  <line x1="100" y1="80" x2="160" y2="80" stroke="#166534" stroke-width="2" stroke-linecap="round"/>
  <line x1="100" y1="92" x2="145" y2="92" stroke="#166534" stroke-width="2" stroke-linecap="round"/>
  <rect x="260" y="15" width="50" height="8" rx="4" fill="#166534" opacity="0.25"/>
  <rect x="260" y="30" width="40" height="8" rx="4" fill="#166534" opacity="0.2"/>
  <rect x="260" y="45" width="48" height="8" rx="4" fill="#166534" opacity="0.25"/>
  <rect x="260" y="60" width="35" height="8" rx="4" fill="#166534" opacity="0.2"/>
  <rect x="260" y="75" width="45" height="8" rx="4" fill="#166534" opacity="0.25"/>
  <rect x="260" y="90" width="38" height="8" rx="4" fill="#166534" opacity="0.2"/>
  <line x1="10" y1="30" x2="55" y2="30" stroke="#166534" stroke-width="1.5" opacity="0.4"/>
  <line x1="10" y1="50" x2="45" y2="50" stroke="#166534" stroke-width="1.5" opacity="0.3"/>
  <line x1="10" y1="70" x2="55" y2="70" stroke="#166534" stroke-width="1.5" opacity="0.4"/>
  <line x1="10" y1="90" x2="40" y2="90" stroke="#166534" stroke-width="1.5" opacity="0.3"/>
  <line x1="10" y1="110" x2="50" y2="110" stroke="#166534" stroke-width="1.5" opacity="0.4"/>
</svg>"""

def generate_column(
    topic: Dict, books: List[Dict], report_date: str, day_label: str
) -> tuple[str, str]:
    """
    Claude API でキーワード特化記事を生成し (markdown, slug) を返す。
    slug はファイル名として使用される（URLになる）。
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_prompt = """あなたは45歳の新潟市在住・IT企業AI/DX推進部副部長「ただの会社員」として記事を書く個人投資家ブロガーです。
読者は検索エンジンで特定のキーワードを調べている20〜40代の社会人です。
以下のプロフィールを踏まえ、リアルな一人称で記事を書いてください。

【投稿者プロフィール（実際の保有株）】
- 45歳・男性・新潟市・IT企業副部長（年収約600万円）、妻と5歳の子供1人
- NISA成長枠：イオン300株（含み損-29.9%）、三菱商事100株（+37.9%）、NTT100株、KDDI200株、積水ハウス40株、日経高配当50ETF110株など
- つみたてNISA：eMAXIS Slim S&P500・FANG+・NASDAQ100
- 目標：配当金によるサイドFIREと子供の大学進学費用の確保

【文体・トーン】
- です・ます調。飾らないサラリーマン目線の親しみやすい文体
- 「私もイオン株を300株持っていますが、正直いまは含み損で〜」など実態を正直に書く
- 「新潟の地方サラリーマンとして〜」「副業ゼロの会社員だからこそ〜」など等身大の表現を使う

【構成ルール】
- 冒頭でキーワードに直接答える（結論ファースト）
- 小見出し（##）を4〜5個使って読みやすく構成する
- 具体的な数字・銘柄名・利回りを積極的に使う
- 比較・一覧・シミュレーションを含める
- 末尾に「## 投稿者の所感」として2〜3文の個人的総評を添える
- 文字数: 1,500〜2,000字"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": topic["prompt"]}],
    )
    body = _extract_text(response).strip()

    # 書籍選定（テーマに合わせて）
    selected_books = select_books_by_theme(books, topic["theme_keys"], count=3)

    # スラッグ（URLになる）
    slug = topic.get("slug", report_date)

    # タイトル・description
    title = topic["title"]
    keyword = topic.get("keyword", "")
    description = f"{keyword}について徹底解説。{title}"
    description = description[:120].replace('"', "'")

    # カテゴリ
    category = topic.get("category", day_label)

    # タグ（キーワードをタグに含める）
    tags = ["高配当株", "不労所得", "投資解説"]
    if keyword:
        tags.append(keyword.split()[0])  # キーワードの最初の単語をタグに

    tags_str = ", ".join(f'"{t}"' for t in tags)

    # frontmatter
    fm = (
        "---\n"
        f'title: "{title}"\n'
        f'description: "{description}"\n'
        f"pubDate: {report_date}\n"
        f'category: "{category}"\n'
        f'tags: [{tags_str}]\n'
        'author: "ただの会社員"\n'
        "draft: false\n"
        "---\n\n"
    )

    # リード文（最初の段落をlead-textに）
    lines = body.split("\n")
    first_para = lines[0] if lines else ""
    rest = "\n".join(lines[1:])

    content = f'<div class="lead-text">{first_para}</div>\n\n'
    content += rest + "\n\n"

    # 書籍紹介
    books_html = "\n## 📚 あわせて読みたいおすすめ投資書籍\n\n"
    for b in selected_books:
        cover_src = resolve_cover_src(b)
        aff_url = amazon_url(b["asin"])
        title_esc = b["title"].replace('"', "&quot;")
        isbn13 = b.get('isbn13', '')
        books_html += (
            f'<div class="book-item" data-isbn="{isbn13}">'
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

    return fm + content + books_html + disclaimer, slug


def get_column_topic(weekday: int, report_date: str) -> tuple[Dict, str]:
    """
    weekday: 5=土曜, 6=日曜
    report_date: YYYY-MM-DD（週番号でローテーション）
    Returns: (topic, day_label)
    """
    week_num = datetime.strptime(report_date, "%Y-%m-%d").isocalendar()[1]

    if weekday == 5:  # 土曜
        topic = SATURDAY_TOPICS[week_num % len(SATURDAY_TOPICS)]
        return topic, "キーワード解説"
    else:  # 日曜
        topic = SUNDAY_TOPICS[week_num % len(SUNDAY_TOPICS)]
        return topic, "キーワード解説"

def main() -> int:
    now = datetime.now(TZ)
    report_date = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0=月, 1=火, ..., 5=土, 6=日

    try:
        books = load_books()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{report_date}.mdx"

        if weekday in (5, 6):
            # ── 土日：SEOキーワード特化記事を生成 ──────────────────
            day_name = "土曜" if weekday == 5 else "日曜"
            print(f"[info] {day_name}キーワード記事モードで生成します", file=sys.stderr)

            topic, day_label = get_column_topic(weekday, report_date)
            print(f"[info] Topic: {topic['title']}", file=sys.stderr)
            print(f"[info] Keyword: {topic.get('keyword', '')}", file=sys.stderr)

            md, article_slug = generate_column(topic, books, report_date, day_label)
            # スラッグをファイル名に使用（URLになる）
            out_path = OUTPUT_DIR / f"{article_slug}.mdx"
            # 既存ファイルがある場合はスキップ（同じ記事の重複生成防止）
            if out_path.exists():
                print(f"[info] Skip: {out_path} already exists", file=sys.stderr)
                return 0
        else:
            # ── 月〜金：株価レポート ＋ キーワード記事の2本生成 ──────
            prices = collect_prices()
            if not prices:
                print("Error: 株価データ取得失敗", file=sys.stderr)
                return 1

            news = collect_news(max_items=5)
            intro, ranking, remarks, body, themes = generate_summary(prices, report_date)
            print(f"[info] AI themes: {themes}", file=sys.stderr)

            selected_books = select_books_by_theme(books, themes, count=3)
            print(f"[info] Selected books: {[b['id'] for b in selected_books]}", file=sys.stderr)

            # 1本目：株価レポート（日付スラッグ）
            md = build_markdown(
                intro, prices, ranking, remarks, body, news, selected_books, report_date, themes
            )
            out_path.write_text(md, encoding="utf-8")
            print(f"Success: {out_path}")

            # 2本目：キーワード記事（SEOスラッグ）
            kw_topic = get_weekday_keyword_topic(report_date)
            print(f"[info] Keyword article: {kw_topic['title']}", file=sys.stderr)
            kw_md, kw_slug = generate_column(kw_topic, books, report_date, "キーワード解説")
            kw_path = OUTPUT_DIR / f"{kw_slug}.mdx"
            if kw_path.exists():
                print(f"[info] Skip keyword article: {kw_path} already exists", file=sys.stderr)
            else:
                kw_path.write_text(kw_md, encoding="utf-8")
                print(f"Success: {kw_path}")
            return 0

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
    