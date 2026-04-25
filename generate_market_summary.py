import os, sys, time, random, json
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
    "4063.T": "信越化学工業", "9020.T": "JR東日本", "2802.T": "味の素", "3382.T": "セブン＆アイHD", "7453.T": "良品計画",
}

CLAUDE_MODEL = "claude-opus-4-7"
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")

BOOK_POOL = [
    {"title": "本当の自由を手に入れる お金の大学", "url": "https://amzn.to/4vOVqrt", "img": "https://m.media-amazon.com/images/P/B08688RT6T.01.LZZZZZZZ.jpg", "desc": "資産形成の基本が網羅された一冊。"},
    {"title": "オートモードで月に18.5万円が入ってくる「高配当」株投資", "url": "https://amzn.to/4cvqRzx", "img": "https://m.media-amazon.com/images/P/B0B9XF5Z8V.01.LZZZZZZZ.jpg", "desc": "日本の高配当株投資のバイブル。"},
    {"title": "サイコロジー・オブ・マネー", "url": "https://amzn.to/4d9ozFx", "img": "https://m.media-amazon.com/images/P/B08X49G7QY.01.LZZZZZZZ.jpg", "desc": "富と幸福に関する深い洞察が得られます。"},
    {"title": "敗者のゲーム", "url": "https://amzn.to/3QvojJd", "img": "https://m.media-amazon.com/images/P/B07K963L4V.01.LZZZZZZZ.jpg", "desc": "インデックス投資の重要性を説く不朽の名著。"},
    {"title": "ジェイソン流お金の増やし方", "url": "https://amzn.to/4d587XL", "img": "https://m.media-amazon.com/images/P/B09MT96T85.01.LZZZZZZZ.jpg", "desc": "シンプルで力強い投資哲学が学べます。"},
    {"title": "ほったらかし投資術", "url": "https://amzn.to/3OAYhUh", "img": "https://m.media-amazon.com/images/P/B09QXN9L7F.01.LZZZZZZZ.jpg", "desc": "手間をかけずに資産を築く具体的な手法。"},
    {"title": "バカでも稼げる 「米国株」高配当投資", "url": "https://amzn.to/4e3igFr", "img": "https://m.media-amazon.com/images/P/B07P88Z2N4.01.LZZZZZZZ.jpg", "desc": "米国高配当株の魅力が分かりやすく解説されています。"},
    {"title": "父が娘に伝える 自由に生きるための30の投資の教え", "url": "https://amzn.to/4cQ85lp", "img": "https://m.media-amazon.com/images/P/B08L39W8Z8.01.LZZZZZZZ.jpg", "desc": "投資の本質を突いた感動的な一冊。"},
]

@dataclass
class PriceInfo:
    ticker: str; name: str; close: float; prev_close: float; yield_pc: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float: return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0
    def to_dict(self) -> dict: return {"ticker": self.ticker, "name": self.name, "yield": f"{self.yield_pc:.2f}%", "close": round(self.close, 2), "change_pct": f"{self.change_pct:.2f}%"}

def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker); df = t.history(period="5d", auto_adjust=False).sort_index()
            if df.empty: continue
            y = t.info.get('dividendYield', 0); y_pc = (y * 100) if y and y < 1 else (y or 0.0)
            results.append(PriceInfo(ticker, name, float(df.iloc[-1]["Close"]), float(df.iloc[-2]["Close"]), y_pc))
        except: continue
    return results

def force_to_str(obj: Any) -> str:
    if obj is None: return ""
    if isinstance(obj, str): return obj
    if isinstance(obj, list): return "".join([force_to_str(item) for item in obj])
    if hasattr(obj, 'text'): return force_to_str(obj.text)
    return str(obj)

def generate_summary(prices: List[PriceInfo], report_date: str):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    data_str = "\n".join([str(p.to_dict()) for p in prices])
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=3500,
        system="1行目：銘柄コード（カンマ区切り）、2行目：備考JSON、3行目以降：詳細解説（### [順位]位 形式）。必ず16-20位も個別に解説してください。",
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    full_text = force_to_str(response.content).strip()
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    
    # 柔軟な解析: 1行目がランキング、2行目がJSONであることを想定
    ranking_tickers = [t.strip() for t in str(lines).split(',') if t.strip()]
    try:
        remarks_map = json.loads(lines)
    except:
        remarks_map = {}
        
    return ranking_tickers, remarks_map, "\n".join(lines[2:])

def build_markdown(prices, ranking_tickers, remarks, body, report_date):
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    fm = f'---\ntitle: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\ndescription: "AIが厳選した最新の高配当・優待銘柄動向。"\npubDate: {report_date}\ntags: ["高配当株", "不労所得"]\n---\n\n'
    
    table = "## 📊 本日の注目銘柄ベスト20\n\n"
    table += "| 順位 | コード | 銘柄名 | 配当率 | 終値 | 前日比 | 変化率 | 備考 |\n"
    table += "|:---:|:---:|:---|---:|---:|---:|---:|:---|\n"
    for i, p in enumerate(final_list, 1):
        sign = "+" if p.change >= 0 else ""
        table += f"| {i} | `{p.ticker}` | {p.name} | {p.yield_pc:.2f}% | {p.close:,.1f} | {sign}{p.change:,.1f} | {sign}{p.change_pct:.2f}% | {remarks.get(p.ticker, '-')} |\n"
    
    books = "\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    for b in random.sample(BOOK_POOL, 3):
        books += f'<div class="book-item"><img src="{b["img"]}" alt="{b["title"]}" referrerpolicy="no-referrer"><div class="book-info"><strong><a href="{b["url"]}">{b["title"]}</a></strong><p>{b["desc"]}</p></div></div>\n'
    
    footer = "\n\n---\n\n<div class='disclaimer'>※ 免責事項：投資判断はご自身の責任において行ってください。<br>※ 上記リンクはAmazonアソシエイトリンクを使用しています。</div>\n"
    
    return fm + table + "\n" + body + "\n" + books + footer

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
    except Exception as e: print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__": sys.exit(main())
