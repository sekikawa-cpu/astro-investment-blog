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

# ---------- 📚 BOOK_POOL（サムネイルURLを追加） ----------
# 画像URLは適切なものに差し替えてください
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

@dataclass
class PriceInfo:
    ticker: str
    name: str
    close: float
    prev_close: float
    yield_pc: float  # 配当利回り(%)

    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0
    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker, 
            "name": self.name, 
            "yield": f"{self.yield_pc:.2f}%",
            "close": round(self.close, 2), 
            "change_pct": f"{self.change_pct:.2f}%"
        }

def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="5d", auto_adjust=False).sort_index()
            if df.empty: continue
            
            # 配当利回りの取得（infoから取得、取得できない場合は0.0）
            info = t.info
            y = info.get('dividendYield', 0)
            if y is None: y = 0
            y_pc = y * 100 if y < 1 else y # 小数かパーセントか補正
            
            results.append(PriceInfo(ticker, name, float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"]), y_pc))
        except: continue
    return results

SYSTEM_PROMPT = """あなたは不労所得を目指す投資家向けのメンターです。
提供されたデータから「長期投資家が今注目すべき銘柄」をベスト20選定してください。

【出力形式の絶対ルール】
1. 1行目：おすすめ順の銘柄コード（カンマ区切り）
2. 2行目：各銘柄の「備考（20文字以内）」をコード順に並べたJSON形式
   例: {"1489.T": "利回り4%超の鉄板ETF", "9432.T": "NTT、安定感抜群"...}
3. 3行目以降：各銘柄の詳細解説
   - フォーマット：
     ### **[順位]位 [コード] [銘柄名]**
     （ここに改行を入れる）
     [解説本文を150文字程度で記述]

※16〜20位も省略せず、上記###形式で1つずつ個別に解説してください。
"""

def generate_summary(prices: List[PriceInfo], report_date: str):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=api_key)
    data_str = "\n".join([str(p.to_dict()) for p in prices])
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=3000, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    
    full_text = response.content.text
    lines = [l.strip() for l in full_text.strip().split('\n') if l.strip()]
    
    ranking_tickers = [t.strip() for t in lines.split(',') if t.strip()]
    
    # 備考JSONの解析
    import json
    try:
        remarks_map = json.loads(lines)
    except:
        remarks_map = {}
        
    body_content = "\n".join(lines[2:])
    return ranking_tickers, remarks_map, body_content

def build_markdown(prices: List[PriceInfo], ranking_tickers: List[str], remarks: Dict, body: str, report_date: str) -> str:
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    title = f"{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"
    desc = "最新の市場動向から、不労所得を最大化するための注目銘柄をAIが厳選。"
    
    fm = f'---\ntitle: "{title}"\ndescription: "{desc}"\npubDate: {report_date}\ncategory: "マーケット分析"\ntags: ["高配当株", "株主優待", "不労所得"]\nauthor: "配当＆優待ナビ"\n---\n\n'
    
    # テーブル作成
    table = "## 📊 本日の注目銘柄ベスト20\n\n"
    table += "| 順位 | コード | 銘柄名 | 配当率 | 終値 | 前日比 | 変化率 | 備考 |\n"
    table += "|:---:|:---:|:---|---:|---:|---:|---:|:---|\n"
    
    for i, p in enumerate(final_list, 1):
        sign = "+" if p.change >= 0 else ""
        rm = remarks.get(p.ticker, "-")
        table += f"| {i} | `{p.ticker}` | {p.name} | {p.yield_pc:.2f}% | {p.close:,.1f} | {sign}{p.change:,.1f} | {sign}{p.change_pct:.2f}% | {rm} |\n"
    
    # 書籍セクション（サムネイル付き）
    books_html = "## 📚 本日の注目・おすすめ投資書籍\n\n"
    selected_books = random.sample(BOOK_POOL, 3)
    for b in selected_books:
        books_html += f'<div class="book-item"><img src="{b["img"]}" alt="{b["title"]}"><div class="book-info"><strong><a href="{b["url"]}">{b["title"]}</a></strong><p>{b["desc"]}</p></div></div>\n'

    # 免責事項の統合
    footer = f"\n\n---\n\n<div class='disclaimer'>\n"
    footer += "※ 免責事項：本記事はAIによる自動生成情報であり、特定の銘柄の購入を推奨するものではありません。投資判断は必ずご自身の責任において行ってください。<br>\n"
    footer += "※ 上記リンクはAmazonアソシエイトリンクを使用しています。この記事の収益はサイトの維持・運営に役立てられます。\n"
    footer += "</div>\n"
    
    return fm + table + "\n" + body + "\n" + books_html + footer

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print(f"Success")
    except Exception as e:
        print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
    