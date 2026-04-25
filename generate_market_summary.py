# -*- coding: utf-8 -*-
"""
配当＆優待ナビ｜日次レポート自動生成スクリプト
- yfinance で株価を取得
- Anthropic API で導入文・ランキング・備考・解説を生成
- 書影は Google Books → openBD → Amazon CDN の順で取得
- 書影は public/images/books に保存してローカル参照にする
- Amazonリンクは StoreID（デフォルト: investinsight-22）付きで生成する
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import yfinance as yf

try:
    import anthropic
except ImportError:
    print("Error: anthropic package is required.", file=sys.stderr)
    sys.exit(2)


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

BOOK_POOL = [
    {
        "title": "改訂版 本当の自由を手に入れる お金の大学",
        "isbn10": "4023323780",
        "isbn13": "9784023323780",
        "desc": "家計管理・投資・副業・保険の見直しまで、資産形成の全体像を1冊で把握できる最新版。",
    },
    {
        "title": "オートモードで月に18.5万円が入ってくる『高配当』株投資",
        "isbn10": "4046055472",
        "isbn13": "9784046055477",
        "desc": "高配当株の選び方・買い方・継続のコツを体系的に学べる、日本株インカム投資の定番。",
    },
    {
        "title": "全面改訂 第3版 ほったらかし投資術（朝日新書）",
        "isbn10": "4022951672",
        "isbn13": "9784022951670",
        "desc": "新NISA時代に合わせて内容が整理された最新版。インデックス投資の土台づくりに最適。",
    },
    {
        "title": "ジェイソン流お金の増やし方 改訂版",
        "isbn10": "4835650018",
        "isbn13": "9784835650012",
        "desc": "支出の最適化と長期・積立・分散をシンプルに学べる、初心者向けの実践入門書。",
    },
    {
        "title": "サイコロジー・オブ・マネー 一生お金に困らない『富』のマインドセット",
        "isbn10": "4478114137",
        "isbn13": "9784478114131",
        "desc": "投資の技術だけでなく、お金との向き合い方そのものを整えたい人に効く一冊。",
    },
    {
        "title": "敗者のゲーム［原著第8版］",
        "isbn10": "4532359112",
        "isbn13": "9784532359119",
        "desc": "インデックス投資の合理性を学ぶ王道の名著。資産配分の考え方を深めたい人向け。",
    },
]

CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")
PUBLIC_BOOK_DIR = Path("public/images/books")
COVER_CACHE_PATH = Path(".bookcovers_cache.json")
AMAZON_STORE_ID = os.environ.get("AMAZON_STORE_ID", "investinsight-22")


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
        return (self.change / self.prev_close) * 100 if self.prev_close else 0.0


def _http_get_json(url: str, timeout: int = 10) -> Optional[object]:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "astro-investment-blog/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _http_download(url: str, timeout: int = 20) -> Optional[Tuple[bytes, str]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return data, ctype
    except Exception:
        return None


def _load_cover_cache() -> Dict[str, str]:
    if COVER_CACHE_PATH.exists():
        try:
            return json.loads(COVER_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cover_cache(cache: Dict[str, str]) -> None:
    try:
        COVER_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _cover_from_google_books(isbn13: str) -> Optional[str]:
    api = "https://www.googleapis.com/books/v1/volumes?q=isbn:" + urllib.parse.quote(isbn13)
    data = _http_get_json(api)
    if not isinstance(data, dict) or not data.get("items"):
        return None
    links = (((data["items"][0] or {}).get("volumeInfo") or {}).get("imageLinks") or {})
    for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
        url = links.get(key)
        if url:
            return url.replace("http://", "https://")
    return None


def _cover_from_openbd(isbn13: str) -> Optional[str]:
    api = "https://api.openbd.jp/v1/get?isbn=" + urllib.parse.quote(isbn13)
    data = _http_get_json(api)
    if not isinstance(data, list) or not data or not data[0]:
        return None
    return ((data[0] or {}).get("summary") or {}).get("cover") or None


def _cover_from_amazon(isbn10: str) -> Optional[str]:
    return f"https://images-na.ssl-images-amazon.com/images/P/{isbn10}.09.LZZZZZZZ.jpg"


def fetch_book_cover_url(isbn10: str, isbn13: str) -> str:
    cache = _load_cover_cache()
    if cache.get(isbn13):
        return cache[isbn13]

    for candidate in (
        _cover_from_google_books(isbn13),
        _cover_from_openbd(isbn13),
        _cover_from_amazon(isbn10),
    ):
        if candidate:
            cache[isbn13] = candidate
            _save_cover_cache(cache)
            return candidate

    placeholder = (
        "data:image/svg+xml;utf8," + urllib.parse.quote(
            '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="170" viewBox="0 0 120 170">'
            '<rect width="120" height="170" fill="#e2e8f0"/>'
            '<text x="60" y="90" font-family="sans-serif" font-size="14" fill="#64748b" text-anchor="middle">No Cover</text>'
            '</svg>'
        )
    )
    cache[isbn13] = placeholder
    _save_cover_cache(cache)
    return placeholder


def materialize_book_cover(isbn10: str, isbn13: str) -> str:
    cover_url = fetch_book_cover_url(isbn10, isbn13)
    if cover_url.startswith("data:image/"):
        return cover_url

    PUBLIC_BOOK_DIR.mkdir(parents=True, exist_ok=True)
    result = _http_download(cover_url)
    if result is None:
        return cover_url

    data, ctype = result
    ext = ".jpg"
    if "png" in ctype:
        ext = ".png"
    elif "webp" in ctype:
        ext = ".webp"

    out = PUBLIC_BOOK_DIR / f"{isbn13}{ext}"
    out.write_bytes(data)
    return f"/images/books/{isbn13}{ext}"


def build_amazon_affiliate_url(asin: str) -> str:
    return f"https://www.amazon.co.jp/dp/{asin}/?tag={AMAZON_STORE_ID}"


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
            results.append(
                PriceInfo(
                    ticker=ticker,
                    name=name,
                    close=float(df.iloc[-1]["Close"]),
                    prev_close=float(df.iloc[-2]["Close"]),
                    yield_pc=float(y_pc),
                )
            )
        except Exception as e:
            print(f"[warn] {ticker} fetch failed: {e}", file=sys.stderr)
    return results


def _extract_text_from_response(response) -> str:
    content = response.content
    if hasattr(content, "text"):
        return content.text
    if isinstance(content, list):
        texts = []
        for block in content:
            if hasattr(block, "text"):
                texts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    return str(content)


def generate_summary(prices: List[PriceInfo], report_date: str) -> Tuple[str, List[str], Dict[str, str], str]:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    data_str = "\n".join(
        f"{p.ticker}, {p.name}, 終値:{p.close:.2f}, 前日比:{p.change_pct:+.2f}%, 配当利回り:{p.yield_pc:.2f}%"
        for p in prices
    )

    system_prompt = """あなたは経験豊富な投資メンターです。以下の厳密なフォーマットで日次の投資レポートを生成してください。

【1行目】経済全体の概況（アイスブレイク）を約200文字で記述。日本市場・米国市場・為替・金利動向に軽く触れ、長期投資家への前向きなメッセージで締める。改行を入れず必ず1行で。
【2行目】注目銘柄ベスト20のティッカーコードのみをカンマ区切りで列挙。余計な記号は付けないこと。
【3行目】各銘柄の備考をJSONオブジェクト1行で出力。コードフェンスや json ラベルは付けないこと。
【4行目以降】各銘柄の詳細解説を「### [順位]位 [銘柄名]（[ティッカー]）」の見出し形式で20件分記述。各解説は2〜3文程度。
重要: 1行目・2行目・3行目は必ず1行で出力し、絶対に途中改行しないこと。"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": f"日付: {report_date}\n\n以下の市場データを基に分析してください:\n\n{data_str}",
            }
        ],
    )

    full_text = _extract_text_from_response(response).strip()
    lines = [line.strip() for line in full_text.split("\n") if line.strip()]
    if len(lines) < 3:
        raise ValueError(f"AI response format error: only {len(lines)} non-empty lines returned")

    intro = lines[0]
    ranking_raw = re.sub(r"[\[\]'\"`]", "", lines[1])
    ranking_tickers = [t.strip() for t in ranking_raw.split(",") if t.strip()]

    remarks: Dict[str, str] = {}
    for cand in lines[2:6]:
        if "{" in cand and "}" in cand:
            try:
                remarks = json.loads(cand[cand.find("{") : cand.rfind("}") + 1])
                break
            except Exception:
                continue

    body = "\n\n".join(line for line in lines[3:] if line and not line.startswith("```"))
    return intro, ranking_tickers, remarks, body


def build_markdown(
    intro: str,
    prices: List[PriceInfo],
    ranking_tickers: List[str],
    remarks: Dict[str, str],
    body: str,
    report_date: str,
) -> str:
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    if not final_list:
        final_list = prices[:20]

    description = intro[:120].replace('"', "'").replace("\n", " ")
    fm = (
        "---\n"
        f'title: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\n'
        f'description: "{description}"\n'
        f"pubDate: {report_date}\n"
        'category: "マーケット分析"\n'
        'tags: ["高配当株", "不労所得", "日次レポート", "新NISA"]\n'
        'author: "配当＆優待ナビ AI編集部"\n'
        "draft: false\n"
        "---\n\n"
    )

    content = f'<div class="lead-text">{intro}</div>\n\n'
    content += "## 📊 本日の注目銘柄ベスト20\n\n"
    content += '<div class="table-wrapper"><table class="stock-table">\n'
    content += '<thead><tr><th>順位</th><th>コード</th><th>銘柄名</th><th>配当率</th><th>終値</th><th>前日比</th><th>変化率</th><th>備考</th></tr></thead>\n'
    content += '<tbody>\n'
    for i, p in enumerate(final_list, 1):
        row_cls = "red-row" if p.change > 0 else ("green-row" if p.change < 0 else "")
        sign = "+" if p.change > 0 else ""
        remark = remarks.get(p.ticker, "—")
        content += (
            f'<tr class="{row_cls}">'
            f'<td class="text-center">{i}</td>'
            f'<td class="text-center"><strong>{p.ticker}</strong></td>'
            f'<td><strong>{p.name}</strong></td>'
            f'<td class="text-right">{p.yield_pc:.2f}%</td>'
            f'<td class="text-right">{p.close:,.1f}</td>'
            f'<td class="text-right">{sign}{p.change:,.1f}</td>'
            f'<td class="text-right">{sign}{p.change_pct:.2f}%</td>'
            f'<td>{remark}</td>'
            '</tr>\n'
        )
    content += '</tbody></table></div>\n\n'
    content += '## 📝 各銘柄の詳細解説\n\n'
    content += body + '\n\n'

    books = '## 📚 本日の注目・おすすめ投資書籍\n\n'
    for b in BOOK_POOL[:4]:
        cover = materialize_book_cover(b['isbn10'], b['isbn13'])
        affiliate = build_amazon_affiliate_url(b['isbn10'])
        books += (
            '<div class="book-item">'
            f'<img src="{cover}" alt="{b["title"]}" referrerpolicy="no-referrer" loading="lazy">'
            '<div class="book-info">'
            f'<strong><a href="{affiliate}" target="_blank" rel="noopener noreferrer sponsored">{b["title"]}</a></strong>'
            f'<p>{b["desc"]}</p>'
            '</div></div>\n\n'
        )

    disclaimer = (
        '---\n\n'
        '<div class="disclaimer-note">'
        '※ 本記事はAIによる自動生成です。情報提供を目的としており、投資判断はご自身の責任において行ってください。<br>'
        '※ 上記書籍リンクはAmazonアソシエイトリンクを使用しています。'
        '</div>\n'
    )

    return fm + content + books + disclaimer


def main() -> int:
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices:
            print("Error: 価格データを取得できませんでした", file=sys.stderr)
            return 1
        intro, ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(intro, prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print(f"Success: src/content/blog/{report_date}.md を生成しました")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
