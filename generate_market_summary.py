import os
import sys
import time
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

try:
    import anthropic
except ImportError:
    print("Error: anthropic package is required.", file=sys.stderr)
    sys.exit(2)

# ---------- 設定 ----------
# 監視銘柄プール（ここからAIがベスト20を厳選）
TICKER_POOL: Dict[str, str] = {
    "1489.T": "日経高配当50ETF", "^GSPC": "S&P 500", "SPYD": "SPYD (米国高配当)", "VYM": "VYM (米国高配当)",
    "2914.T": "JT", "8306.T": "三菱UFJFG", "9432.T": "NTT", "8058.T": "三菱商事",
    "8593.T": "三菱HCキャピタル", "1605.T": "INPEX", "1928.T": "積水ハウス", "7203.T": "トヨタ自動車",
    "8267.T": "イオン", "9433.T": "KDDI", "2702.T": "日本マクドナルドHD", "3197.T": "すかいらーくHD",
    "9861.T": "吉野家HD", "8282.T": "ケーズHD", "2503.T": "キリンHD", "9202.T": "ANAHD",
    "9101.T": "日本郵船", "8001.T": "伊藤忠商事", "4502.T": "武田薬品工業", "8316.T": "三井住友FG",
    "4063.T": "信越化学工業", "9020.T": "JR東日本", "3088.T": "マツキヨココカラ", "7453.T": "良品計画",
    "3382.T": "セブン＆アイHD", "2802.T": "味の素",
}

CLAUDE_MODEL = "claude-opus-4-7"
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")

# ---------- 📚 BOOK_POOL（内容は保持してください） ----------
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
    ticker: str; name: str; close: float; prev_close: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0
    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "name": self.name, "close": round(self.close, 2), "change_pct": round(self.change_pct, 2)}

def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            df = yf.Ticker(ticker).history(period="5d", auto_adjust=False).sort_index()
            if df.empty: continue
            results.append(PriceInfo(ticker, name, float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"])))
        except: continue
    return results

SYSTEM_PROMPT = """あなたは不労所得を目指す投資家向けのメンターです。
与えられた銘柄リストから、長期投資家が今注目すべき銘柄をベスト20の順位で選定し、分析レポートを書いてください。

【出力の絶対ルール】
1. 最初の1行目には必ず、おすすめ順の銘柄コード（カンマ区切り）だけを書いてください。
   例: 1489.T, 9432.T, SPYD, ...
2. 2行目から、Markdown形式でレポート本文を書いてください。本文のみを出力し、タイトルは不要です。
"""

def generate_summary(prices: List[PriceInfo], report_date: str):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    data_str = "\n".join([str(p.to_dict()) for p in prices])
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2000, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    
    # 修正箇所：もっとも安全なテキスト抽出
    full_text = response.content.text
    lines = [line for line in full_text.strip().split('\n') if line.strip()]
    
    # 1行目からランキングを取得
    ranking_line = lines
    ranking_tickers = [t.strip() for t in ranking_line.split(',') if t.strip()]
    
    body = '\n'.join(lines[1:]).strip()
    return ranking_tickers, body

def build_markdown(prices: List[PriceInfo], ranking_tickers: List[str], body: str, report_date: str) -> str:
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    title = f"{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"
    desc = "最新の市場動向から、配当・優待投資家が注目すべき20銘柄をAIが厳選。日々の積み重ねが未来の不労所得を作ります。"
    
    fm = f'---\ntitle: "{title}"\ndescription: "{desc}"\npubDate: {report_date}\ncategory: "マーケット分析"\ntags: ["高配当株", "株主優待", "不労所得"]\nauthor: "配当＆優待ナビ"\ndraft: false\n---\n\n'
    
    table = "## 📊 本日の注目銘柄データ（AI推奨順ベスト20）\n\n"
    table += "| 順位 | 銘柄名 | コード | 終値 | 前日比 | 変化率 |\n"
    table += "|:---:|:---|:---:|---:|---:|---:|\n" # 揃え方向：中央、左、中央、右、右、右
    
    for i, p in enumerate(final_list, 1):
        sign = "+" if p.change >= 0 else ""
        table += f"| {i} | {p.name} | `{p.ticker}` | {p.close:,.1f} | {sign}{p.change:,.1f} | {sign}{p.change_pct:.2f}% |\n"
    
    disclaimer = "\n\n<small style='color: #94a3b8;'>※ 免責事項：本記事はAIによる自動生成情報であり、特定の銘柄の購入を推奨するものではありません。投資判断は必ずご自身の責任において行ってください。</small>\n"
    
    return fm + table + "\n" + body + get_dynamic_affiliate_section() + disclaimer

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices: return 1
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
    