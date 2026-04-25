# -*- coding: utf-8 -*-
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

# ---------- 設定 ----------
TICKER_POOL: Dict[str, str] = {
    "1489.T": "日経高配当50ETF", "^GSPC": "S&P 500", "SPYD": "SPYD (米国高配当)", "VYM": "VYM (米国高配当)",
    "2914.T": "JT", "8306.T": "三菱UFJFG", "9432.T": "NTT", "8058.T": "三菱商事",
    "8593.T": "三菱HCキャピタル", "1605.T": "INPEX", "1928.T": "積水ハウス", "7203.T": "トヨタ自動車",
    "8267.T": "イオン", "9433.T": "KDDI", "2702.T": "日本マクドナルドHD", "3197.T": "すかいらーくHD",
    "9861.T": "吉野家HD", "8282.T": "ケーズHD", "2503.T": "キリンHD", "9202.T": "ANAHD",
    "9101.T": "日本郵船", "8001.T": "伊藤忠商事", "4502.T": "武田薬品工業", "8316.T": "三井住友FG",
    "4063.T": "信越化学工業", "9020.T": "JR東日本", "2802.T": "味の素", "3382.T": "セブン＆アイHD", "7453.T": "良品計画",
}

BOOK_POOL = [
    {"title": "改訂版 本当の自由を手に入れる お金の大学", "isbn10": "4023323780", "isbn13": "9784023323780", "desc": "資産形成の全体像を把握できる最新版。"},
    {"title": "オートモードで月に18.5万円が入ってくる『高配当』株投資", "isbn10": "4046055472", "isbn13": "9784046055477", "desc": "日本株インカム投資の定番。"},
    {"title": "全面改訂 第3版 ほったらかし投資術", "isbn10": "4022951672", "isbn13": "9784022951670", "desc": "新NISA時代に最適な入門書。"},
    {"title": "サイコロジー・オブ・マネー", "isbn10": "4478114137", "isbn13": "9784478114131", "desc": "富と幸福に関するマインドセットを整える一冊。"},
]

CLAUDE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")
PUBLIC_BOOK_DIR = Path("public/images/books")
AMAZON_STORE_ID = os.environ.get("AMAZON_STORE_ID", "investinsight-22")

@dataclass
class PriceInfo:
    ticker: str; name: str; close: float; prev_close: float; yield_pc: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float: return (self.change / self.prev_close) * 100 if self.prev_close else 0.0

def _http_download(url: str) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp: return resp.read()
    except: return None

def materialize_book_cover(isbn10: str, isbn13: str) -> str:
    cover_url = f"https://m.media-amazon.com/images/P/{isbn10}.01.LZZZZZZZ.jpg"
    PUBLIC_BOOK_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PUBLIC_BOOK_DIR / f"{isbn13}.jpg"
    if not out_path.exists():
        data = _http_download(cover_url)
        if data: out_path.write_bytes(data)
    return f"/images/books/{isbn13}.jpg" if out_path.exists() else ""

def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker); df = t.history(period="5d").sort_index()
            if df.empty or len(df) < 2: continue
            y = t.info.get("dividendYield", 0) or 0
            y_pc = (y * 100) if y and y < 1 else (y or 0.0)
            results.append(PriceInfo(ticker, name, float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"]), y_pc))
        except: continue
    return results

def generate_summary(prices: List[PriceInfo], report_date: str) -> Tuple[str, List[str], Dict[str, str], str]:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    data_str = "\n".join([f"{p.ticker}, {p.name}, 前日比:{p.change_pct:+.2f}%" for p in prices])

    system_prompt = """あなたは投資メンターです。以下の構成で出力してください。
1行目：経済概況を約200文字で（1行、改行禁止）。
2行目：おすすめ20銘柄のコードをカンマ区切りで。
3行目：各銘柄の備考をJSON形式で（1行、改行禁止）。
4行目以降：各銘柄の詳細解説。"""

    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4000, system=system_prompt,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )

    # 1. SDKのレスポンス形式に依存しない安全なテキスト抽出
    full_text = ""
    if hasattr(response.content, 'text'): full_text = response.content.text
    elif isinstance(response.content, list): full_text = "".join(b.text for b in response.content if hasattr(b, 'text'))
    else: full_text = str(response.content)
    
    lines = [l.strip() for l in full_text.strip().split("\n") if l.strip()]
    
    # 2. 挨拶などを飛ばして「導入文」「銘柄リスト」「JSON」を内容から探す（動的解析）
    intro, ranking_tickers, remarks, body_lines = "", [], {}, []
    for line in lines:
        if not intro and len(line) > 50: intro = line
        elif not ranking_tickers and "," in line and len(line.split(",")) >= 10:
            ranking_tickers = [t.strip() for t in re.sub(r"[\[\]'\"`]", "", line).split(",") if t.strip()]
        elif not remarks and "{" in line and "}" in line:
            try: remarks = json.loads(line[line.find("{"):line.rfind("}")+1])
            except: pass
        else: body_lines.append(line)

    return intro or "マーケット概況の生成に失敗しました。", ranking_tickers[:20], remarks, "\n\n".join(body_lines)

def build_markdown(intro, prices, ranking_tickers, remarks, body, report_date):
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    if not final_list: final_list = prices[:20]

    # Astroスキーマ完全準拠
    clean_desc = intro[:120].replace('"', "'").replace("\n", " ")
    fm = (
        "---\n"
        f'title: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\n'
        f'description: "{clean_desc}"\n'
        f"pubDate: {report_date}\n"
        'category: "マーケット分析"\n'
        'tags: ["高配当株", "不労所得", "日次レポート", "新NISA"]\n'
        'author: "配当＆優待ナビ AI編集部"\n'
        "draft: false\n"
        "---\n\n"
    )

    content = f'<div class="lead-text">{intro}</div>\n\n## 📊 本日の注目銘柄ベスト20\n\n'
    content += '<div class="table-wrapper"><table class="stock-table"><thead><tr><th>順位</th><th>コード</th><th>銘柄名</th><th>配当率</th><th>終値</th><th>前日比</th><th>変化率</th><th>備考</th></tr></thead><tbody>\n'
    for i, p in enumerate(final_list, 1):
        cls = "red-row" if p.change > 0 else ("green-row" if p.change < 0 else "")
        content += f'<tr class="{cls}"><td class="text-center">{i}</td><td class="text-center"><strong>{p.ticker}</strong></td><td><strong>{p.name}</strong></td><td class="text-right">{p.yield_pc:.2f}%</td><td class="text-right">{p.close:,.1f}</td><td class="text-right">{"+" if p.change > 0 else ""}{p.change:,.1f}</td><td class="text-right">{"+" if p.change > 0 else ""}{p.change_pct:.2f}%</td><td>{remarks.get(p.ticker, "—")}</td></tr>\n'
    content += '</tbody></table></div>\n\n## 📝 各銘柄の詳細解説\n\n' + body + '\n\n'
    
    books = '## 📚 本日の注目・おすすめ投資書籍\n\n'
    for b in BOOK_POOL:
        cover = materialize_book_cover(b['isbn10'], b['isbn13'])
        url = f"https://www.amazon.co.jp/dp/{b['isbn10']}/?tag={AMAZON_STORE_ID}"
        books += f'<div class="book-item"><img src="{cover}" alt="{b["title"]}" referrerpolicy="no-referrer" loading="lazy"><div class="book-info"><strong><a href="{url}" target="_blank" rel="noopener noreferrer sponsored">{b["title"]}</a></strong><p>{b["desc"]}</p></div></div>\n\n'

    return fm + content + books

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices: return 1
        intro, ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(intro, prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr); return 1

if __name__ == "__main__":
    sys.exit(main())
    