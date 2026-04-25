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

# ---------- 📚 BOOK_POOL（Amazon公式配信URL） ----------
def get_amazon_img(asin: str) -> str:
    return f"https://ws-fe.amazon-adsystem.com/widgets/q?_encoding=UTF8&ASIN={asin}&Format=_SL250_&ID=AsinImage&MarketPlace=JP&ServiceVersion=20070822&WS=1"

BOOK_POOL = [
    {"title": "本当の自由を手に入れる お金の大学", "url": "https://amzn.to/4vOVqrt", "img": get_amazon_img("B08688RT6T"), "desc": "資産形成の基本が網羅された一冊。"},
    {"title": "オートモードで月に18.5万円が入ってくる「高配当」株投資", "url": "https://amzn.to/4cvqRzx", "img": get_amazon_img("B0B9XF5Z8V"), "desc": "日本の高配当株投資のバイブル。"},
    {"title": "サイコロジー・オブ・マネー", "url": "https://amzn.to/4d9ozFx", "img": get_amazon_img("B08X49G7QY"), "desc": "富と幸福に関する深い洞察が得られます。"},
    {"title": "敗者のゲーム", "url": "https://amzn.to/3QvojJd", "img": get_amazon_img("B07K963L4V"), "desc": "インデックス投資の重要性を説く不朽の名著。"},
    {"title": "ジェイソン流お金の増やし方", "url": "https://amzn.to/4d587XL", "img": get_amazon_img("B09MT96T85"), "desc": "シンプルで力強い投資哲学が学べます。"},
    {"title": "ほったらかし投資術", "url": "https://amzn.to/3OAYhUh", "img": get_amazon_img("B09QXN9L7F"), "desc": "手間をかけずに資産を築く具体的な手法。"},
    {"title": "バカでも稼げる 「米国株」高配当投資", "url": "https://amzn.to/4e3igFr", "img": get_amazon_img("B07P88Z2N4"), "desc": "米国高配当株の魅力が分かりやすく解説されています。"},
    {"title": "父が娘に伝える 自由に生きるための30の投資の教え", "url": "https://amzn.to/4cQ85lp", "img": get_amazon_img("B08L39W8Z8"), "desc": "投資の本質を突いた感動的な一冊。"},
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
    
    system_prompt = """あなたは不労所得を目指す投資メンターです。以下の構成で出力してください。
1行目：【導入文】経済概況や投資家へのメッセージ（200文字程度）。
2行目：おすすめ銘柄ベスト20のコードをカンマ区切りで（20件）。
3行目：各銘柄の「備考（25文字以内）」をJSON形式で。増配、優待、決算など注目トピックを優先。
4行目以降：詳細解説（### [順位]位 [コード] [銘柄名] 形式）。
"""
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=3500, system=system_prompt,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n{data_str}"}]
    )
    full_text = force_to_str(response.content).strip()
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]
    
    intro_text = lines
    ranking_line = lines.replace('[', '').replace(']', '').replace("'", "").replace('"', '')
    ranking_tickers = [t.strip() for t in ranking_line.split(',') if t.strip()]
    
    try:
        remarks_map = {}
        for line in lines[2:6]:
            if '{' in line and '}' in line:
                remarks_map = json.loads(line)
                break
    except: remarks_map = {}
        
    return intro_text, ranking_tickers, remarks_map, "\n".join(lines[3:])

def build_markdown(intro, prices, ranking_tickers, remarks, body, report_date):
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]
    
    fm = f'---\ntitle: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\ndescription: "{intro[:50]}..." \npubDate: {report_date}\ntags: ["高配当株", "不労所得"]\n---\n\n'
    
    intro_content = f'<div class="lead-text">{intro}</div>\n\n'
    
    table = "## 📊 本日の注目銘柄ベスト20\n\n"
    table += '<div class="table-wrapper"><table>\n'
    table += '<thead><tr><th>順位</th><th>コード</th><th>銘柄名</th><th>配当率</th><th>終値</th><th>前日比</th><th>変化率</th><th>備考</th></tr></thead>\n'
    table += '<tbody>\n'
    for i, p in enumerate(final_list, 1):
        row_class = ' class="row-up"' if p.change > 0 else (' class="row-down"' if p.change < 0 else '')
        table += f'  <tr{row_class}>\n'
        table += f'    <td style="text-align:center;">{i}</td>\n'
        table += f'    <td style="text-align:center;"><strong>{p.ticker}</strong></td>\n'
        table += f'    <td><strong>{p.name}</strong></td>\n'
        table += f'    <td style="text-align:right;">{p.yield_pc:.2f}%</td>\n'
        table += f'    <td style="text-align:right;">{p.close:,.1f}</td>\n'
        table += f'    <td style="text-align:right;">{"+" if p.change > 0 else ""}{p.change:,.1f}</td>\n'
        table += f'    <td style="text-align:right;">{"+" if p.change > 0 else ""}{p.change_pct:.2f}%</td>\n'
        table += f'    <td>{remarks.get(p.ticker, "-")}</td>\n'
        table += '  </tr>\n'
    table += '</tbody></table></div>\n\n'
    
    books = "\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    for b in random.sample(BOOK_POOL, 3):
        books += f'<div class="book-item"><img src="{b["img"]}" alt="{b["title"]}"><div class="book-info"><strong><a href="{b["url"]}">{b["title"]}</a></strong><p>{b["desc"]}</p></div></div>\n'
    
    footer = "\n\n---\n\n<div class='disclaimer'>※ 免責事項：投資判断はご自身の責任において行ってください。<br>※ 上記リンクはAmazonアソシエイトリンクを使用しています。</div>\n"
    return fm + intro_content + table + "\n" + body + "\n" + books + footer

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        intro, ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(intro, prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print("Success")
    except Exception as e: print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__": sys.exit(main())
