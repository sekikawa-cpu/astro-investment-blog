"""
設定した銘柄プールからAIが今日のベスト20を厳選・ランキングし、
不労所得特化型の市場解説文を生成するスクリプト。
"""

from __future__ import annotations
import logging
import os
import sys
import time
import random
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

try:
    import anthropic
except ImportError:
    print("エラー: anthropic パッケージが必要です。", file=sys.stderr)
    sys.exit(2)

# ---------- 設定 ----------
# AIが選定・ランキングするための「銘柄プール（30種）」
# ここからAIが今日のベスト20を選び出します
TICKER_POOL: dict[str, str] = {
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
    # 追加の動的候補（優待・高配当）
    "9101.T": "日本郵船",
    "8001.T": "伊藤忠商事",
    "4502.T": "武田薬品工業",
    "8316.T": "三井住友FG",
    "4063.T": "信越化学工業",
    "9020.T": "JR東日本",
    "3088.T": "マツキヨココカラ",
    "7453.T": "良品計画",
    "3382.T": "セブン＆アイHD",
    "2802.T": "味の素",
}

MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
FETCH_PERIOD = "5d"

CLAUDE_MODEL = "claude-opus-4-7"
CLAUDE_MAX_TOKENS = 2000 
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")

# ---------- 📚 BOOK_POOL（内容は保持） ----------
BOOK_POOL = [
    {"title": "本当の自由を手に入れる お金の大学", "url": "https://amzn.to/4vOVqrt", "desc": "資産形成の基本が網羅された一冊。"},
    {"title": "オートモードで月に18.5万円が入ってくる「高配当」株投資", "url": "https://amzn.to/4cvqRzx", "desc": "日本の高配当株投資のバイブル。"},
    {"title": "サイコロジー・オブ・マネー", "url": "https://amzn.to/4d9ozFx", "desc": "富と幸福に関する深い洞察が得られます。"},
    {"title": "敗者のゲーム", "url": "https://amzn.to/3QvojJd", "desc": "インデックス投資の重要性を説く不朽の名著。"},
    {"title": "ジェイソン流お金の増やし方", "url": "https://amzn.to/4d587XL", "desc": "シンプルで力強い投資哲学が学べます。"},
    {"title": "ほったらかし投資術", "url": "https://amzn.to/3OAYhUh", "desc": "手間をかけずに資産を築く具体的な手法。"},
    {"title": "バカでも稼げる 「米国株」高配当投資", "url": "https://amzn.to/4e3igFr", "desc": "米国高配当株の魅力が分かりやすく解説されています。"},
    {"title": "父が娘に伝える 自由に生きるための30の投資の教え", "url": "https://amzn.to/4cQ85lp", "desc": "投資の本質を突いた感動的な一冊。"},
]

def get_dynamic_affiliate_section() -> str:
    num_to_select = random.randint(3, 5)
    selected_books = random.sample(BOOK_POOL, num_to_select)
    section = "\n---\n\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    for book in selected_books:
        section += f"- 📖 **[{book['title']}]({book['url']})**\n  - {book['desc']}\n"
    section += "\n> ※ 上記リンクはAmazonアソシエイトリンクを使用しています。\n"
    return section

@dataclass
class PriceInfo:
    ticker: str; name: str; date: pd.Timestamp; close: float; prev_close: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0
    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "name": self.name, "close": round(self.close, 2), "change_pct": round(self.change_pct, 2)}

def collect_prices() -> list[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            df = yf.Ticker(ticker).history(period=FETCH_PERIOD, auto_adjust=False).sort_index()
            if df.empty: continue
            results.append(PriceInfo(ticker, name, df.index[-1], float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"])))
        except: continue
    return results

SYSTEM_PROMPT = """あなたは不労所得を目指す投資家向けのメンターです。
与えられた銘柄リストから、今日の相場状況を踏まえ「長期投資家が今注目すべき銘柄」をベスト20の順位で選定し、分析レポートを書いてください。

【出力のルール】
1. 最初に「ベスト20の銘柄コード」を、おすすめ順にカンマ区切りで一行目に書いてください。（例: 9432.T, 1489.T, ...）
2. 次に、Markdown形式でレポート本文を書いてください。
3. 文体は温かく、モチベーションが上がる表現を。
4. 本文のみを返し、タイトルやfrontmatterは不要です。
"""

def generate_summary(prices: list[PriceInfo], report_date: str):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    data_str = "\n".join([str(p.to_dict()) for p in prices])
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=CLAUDE_MAX_TOKENS, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    
    full_text = "".join([b.text for b in response.content if hasattr(b, 'text')])
    lines = full_text.strip().split('\n')
    # 一行目からランキングを取得
    ranking_tickers = [t.strip() for t in lines.split(',')]
    body = '\n'.join(lines[1:]).strip()
    return ranking_tickers, body

def build_markdown(prices: list[PriceInfo], ranking_tickers: list[str], body: str, report_date: str) -> str:
    # ランキングに基づいてデータを並べ替え（最大20件）
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    title = f"{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"
    desc = "最新の市場動向から、配当・優待投資家が注目すべき20銘柄をAIが厳選。日々の積み重ねが未来の不労所得を作ります。"
    
    fm = f'---\ntitle: "{title}"\ndescription: "{desc}"\npubDate: {report_date}\ncategory: "マーケット分析"\ntags: ["高配当株", "株主優待", "不労所得"]\nauthor: "配当＆優待ナビ"\ndraft: false\n---\n\n'
    
    table = "## 📊 本日の注目銘柄データ（AI推奨順ベスト20）\n\n"
    table += "| 順位 | 銘柄名 | コード | 終値 | 前日比 | 変化率 |\n"
    table += "|:---:|:---|:---:|---:|---:|---:|\n" # 右揃え設定
    
    for i, p in enumerate(final_list, 1):
        sign = "+" if p.change >= 0 else ""
        table += f"| {i} | {p.name} | `{p.ticker}` | {p.close:,.1f} | {sign}{p.change:,.1f} | {sign}{p.change_pct:.2f}% |\n"
    
    disclaimer = "\n\n<small style='color: #666;'>※ 免責事項：本記事はAIによる自動生成情報であり、特定の銘柄の購入を推奨するものではありません。投資判断は必ずご自身の責任において行ってください。</small>\n"
    
    return fm + table + "\n" + body + get_dynamic_affiliate_section() + disclaimer

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        ranking, body = generate_summary(prices, report_date)
        md = build_markdown(prices, ranking, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print(f"Success: {report_date}.md")
    except Exception as e:
        print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
    