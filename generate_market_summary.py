import os
import sys
import time
import random
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from zoneinfo import ZoneInfo

import pandas as pd
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
    "4063.T": "信越化学工業", "9020.T": "JR東日本", "2802.T": "味の素", "3382.T": "セブン＆アイHD", 
    "7453.T": "良品計画",
}

CLAUDE_MODEL = "claude-opus-4-7"
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")

# ---------- 📚 BOOK_POOL（全項目にimgを完備） ----------
BOOK_POOL = [
    {"title": "本当の自由を手に入れる お金の大学", "url": "https://amzn.to/3UEpYJ1", "img": "https://m.media-amazon.com/images/I/71u9-pG9S6L._SL150_.jpg", "desc": "資産形成の基本が網羅された一冊。"},
    {"title": "オートモードで月に18.5万円が入ってくる「高配当」株投資", "url": "https://amzn.to/3wunL7f", "img": "https://m.media-amazon.com/images/I/81p8j89-zRL._SL150_.jpg", "desc": "日本の高配当株投資のバイブル。"},
    {"title": "サイコロジー・オブ・マネー", "url": "https://amzn.to/49K0A9X", "img": "https://m.media-amazon.com/images/I/71R1zXp6VPL._SL150_.jpg", "desc": "富と幸福に関する深い洞察が得られます。"},
    {"title": "敗者のゲーム", "url": "https://amzn.to/3UPXzRj", "img": "https://m.media-amazon.com/images/I/71f-O-t2mGL._SL150_.jpg", "desc": "インデックス投資の重要性を説く不朽の名著。"},
    {"title": "ジェイソン流お金の増やし方", "url": "https://amzn.to/3I7T6kK", "img": "https://m.media-amazon.com/images/I/71V2T-rG1pL._SL150_.jpg", "desc": "シンプルで力強い投資哲学が学べます。"},
]

@dataclass
class PriceInfo:
    ticker: str; name: str; close: float; prev_close: float; yield_pc: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0
    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "name": self.name, "yield": f"{self.yield_pc:.2f}%", "close": round(self.close, 2), "change_pct": f"{self.change_pct:.2f}%"}

def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="5d", auto_adjust=False).sort_index()
            if df.empty: continue
            y = t.info.get('dividendYield', 0)
            y_pc = (y * 100) if y and y < 1 else (y or 0.0)
            results.append(PriceInfo(ticker, name, float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"]), y_pc))
        except: continue
    return results

SYSTEM_PROMPT = """あなたは不労所得を目指す投資家向けのメンターです。提供データから注目銘柄ベスト20を選定してください。

【出力形式の絶対ルール】
1行目：おすすめ順の銘柄コード（カンマ区切り）
2行目：各銘柄の「備考（20文字以内）」をコード順に並べたJSON形式。
3行目以降：各銘柄の詳細解説（### **[順位]位 [コード] [銘柄名]** の形式で個別に書く）
"""

def force_to_str(obj: Any) -> str:
    if obj is None: return ""
    if isinstance(obj, str): return obj
    if isinstance(obj, list): return "".join([force_to_str(item) for item in obj])
    if hasattr(obj, 'text'): return force_to_str(obj.text)
    if isinstance(obj, dict) and 'text' in obj: return force_to_str(obj['text'])
    return str(obj)

def generate_summary(prices: List[PriceInfo], report_date: str):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    data_str = "\n".join([str(p.to_dict()) for p in prices])
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=3500, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    
    full_text = force_to_str(response.content).strip()
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    
    ranking_line = str(lines)
    ranking_tickers = [t.strip() for t in ranking_line.split(',') if t.strip()]
    
    try: remarks_map = json.loads(lines)
    except: remarks_map = {}
    
    body_content = "\n".join(lines[2:])
    return ranking_tickers, remarks_map, body_content

def build_markdown(prices: List[PriceInfo], ranking_tickers: list, remarks: dict, body: str, report_date: str) -> str:
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    fm = f'---\ntitle: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\ndescription: "AIが厳選した最新の注目銘柄と配当動向をお届けします。"\npubDate: {report_date}\ncategory: "マーケット分析"\ntags: ["高配当株", "株主優待", "不労所得"]\nauthor: "配当＆優待ナビ"\n---\n\n'
    
    table = "## 📊 本日の注目銘柄ベスト20\n\n"
    table += "| 順位 | コード | 銘柄名 | 配当率 | 終値 | 前日比 | 変化率 | 備考 |\n"
    table += "|:---:|:---:|:---|---:|---:|---:|---:|:---|\n"
    
    for i, p in enumerate(final_list, 1):
        sign = "+" if p.change >= 0 else ""
        rm = remarks.get(p.ticker, "-")
        table += f"| {i} | `{p.ticker}` | {p.name} | {p.yield_pc:.2f}% | {p.close:,.1f} | {sign}{p.change:,.1f} | {sign}{p.change_pct:.2f}% | {rm} |\n"
    
    books_html = "\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    # ここを修正：.get() を使って安全に画像URLを取得
    for b in random.sample(BOOK_POOL, 3):
        img_url = b.get('img', '') 
        books_html += f'<div class="book-item"><img src="{img_url}" alt="{b.get("title","")}"><div class="book-info"><strong><a href="{b.get("url","#")}">{b.get("title","")}</a></strong><p>{b.get("desc","")}</p></div></div>\n'

    footer = f"\n\n---\n\n<div class='disclaimer'>\n"
    footer += "※ 免責事項：本記事はAIによる自動生成情報であり、投資判断はご自身の責任において行ってください。<br>\n"
    footer += "※ 上記リンクはAmazonアソシエイトリンクを使用しています。この記事の収益はサイトの維持・運営に役立てられます。\n</div>\n"
    
    return fm + table + "\n" + body + "\n" + books_html + footer

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices: return 1
        ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print("Success")
    except Exception as e:
        print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
    