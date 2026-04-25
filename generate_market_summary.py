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

CLAUDE_MODEL = "claude-sonnet-4-6"
TZ = ZoneInfo("Asia/Tokyo")
OUTPUT_DIR = Path("src/content/blog")

def get_amazon_img(asin: str) -> str:
    return f"https://m.media-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg"

BOOK_POOL = [
    {"title": "本当の自由を手に入れる お金の大学", "url": "https://amzn.to/4vOVqrt", "asin": "B08688RT6T", "desc": "資産形成の基本が網羅された一冊。"},
    {"title": "オートモードで月に18.5万円が入ってくる「高配当」株投資", "url": "https://amzn.to/4cvqRzx", "asin": "B0B9XF5Z8V", "desc": "日本の高配当株投資のバイブル。"},
    {"title": "サイコロジー・オブ・マネー", "url": "https://amzn.to/4d9ozFx", "asin": "B08X49G7QY", "desc": "富と幸福に関する深い洞察が得られます。"},
    {"title": "敗者のゲーム", "url": "https://amzn.to/3QvojJd", "asin": "B07K963L4V", "desc": "インデックス投資の重要性を説く不朽の名著。"},
    {"title": "ジェイソン流お金の増やし方", "url": "https://amzn.to/4d587XL", "asin": "B09MT96T85", "desc": "シンプルで力強い投資哲学が学べます。"},
    {"title": "ほったらかし投資術", "url": "https://amzn.to/3OAYhUh", "asin": "B09QXN9L7F", "desc": "手間をかけずに資産を築く具体的な手法。"},
    {"title": "バカでも稼げる 「米国株」高配当投資", "url": "https://amzn.to/4e3igFr", "asin": "B07P88Z2N4", "desc": "米国高配当株の魅力が分かりやすく解説されています。"},
    {"title": "父が娘に伝える 自由に生きるための30の投資の教え", "url": "https://amzn.to/4cQ85lp", "asin": "B08L39W8Z8", "desc": "投資の本質を突いた感動的な一冊。"},
]

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
        return (self.change / self.prev_close) * 100 if self.prev_close != 0 else 0


def collect_prices() -> List[PriceInfo]:
    results = []
    for ticker, name in TICKER_POOL.items():
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="5d", auto_adjust=False).sort_index()
            if df.empty or len(df) < 2:
                continue
            try:
                y = t.info.get('dividendYield', 0) or 0
            except Exception:
                y = 0
            y_pc = (y * 100) if y and y < 1 else (y or 0.0)
            results.append(PriceInfo(
                ticker, name,
                float(df.iloc[-1]["Close"]),
                float(df.iloc[-2]["Close"]),
                float(y_pc)
            ))
        except Exception:
            continue
    return results


def _extract_text_from_response(response) -> str:
    """
    Anthropic SDK の response.content は TextBlock のリスト。
    制約事項に従い response.content.text 形式でアクセスできるよう吸収する。
    """
    content = response.content
    # ケース1: SDK が単一オブジェクトを返した場合
    if hasattr(content, "text"):
        return content.text
    # ケース2: リストの場合（通常）→ text を持つブロックを連結
    if isinstance(content, list):
        texts = []
        for block in content:
            if hasattr(block, "text"):
                texts.append(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                texts.append(block.get("text", ""))
        return "\n".join(texts)
    return str(content)


def generate_summary(prices: List[PriceInfo], report_date: str):
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    data_str = "\n".join([
        f"{p.ticker}, {p.name}, 終値:{p.close:.2f}, 前日比:{p.change_pct:+.2f}%, 配当利回り:{p.yield_pc:.2f}%"
        for p in prices
    ])

    system_prompt = """あなたは経験豊富な投資メンターです。以下の厳密なフォーマットで出力してください。

【1行目】経済全体の概況（アイスブレイク）を約200文字で記述。日本市場・米国市場・為替・金利動向に軽く触れ、長期投資家への前向きなメッセージで締める。改行を入れず1行で。

【2行目】注目銘柄ベスト20のティッカーコードのみをカンマ区切りで列挙。例: 1489.T,9432.T,8306.T,...

【3行目】各銘柄の備考を JSON オブジェクト（1行）で出力。例: {"1489.T":"増配基調で安定","9432.T":"通信インフラの王者"}
備考は各銘柄15〜25文字程度の簡潔なコメントとする。

【4行目以降】各銘柄の詳細解説を「### [順位]位 [銘柄名]（[ティッカー]）」の見出し形式で20件分記述。各解説は2〜3文程度。

重要: 1行目・2行目・3行目は必ず1行で出力し、絶対に途中改行しないこと。"""

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": f"日付: {report_date}\n\n以下の市場データを基に分析してください:\n\n{data_str}"}]
    )

    full_text = _extract_text_from_response(response).strip()
    lines = [l.strip() for l in full_text.split('\n') if l.strip()]

    if len(lines) < 3:
        raise ValueError(f"AI response format error: only {len(lines)} lines returned")

    # 1行目: 導入文
    intro = lines[0]

    # 2行目: ランキング（カンマ区切り）
    ranking_raw = lines[1].replace('[', '').replace(']', '').replace("'", "").replace('"', '').replace('`', '')
    ranking_tickers = [t.strip() for t in ranking_raw.split(',') if t.strip()]

    # 3行目: 備考JSON
    remarks: Dict[str, str] = {}
    for l in lines[2:6]:
        if '{' in l and '}' in l:
            try:
                start = l.find('{')
                end = l.rfind('}') + 1
                remarks = json.loads(l[start:end])
                break
            except Exception:
                continue

    # 4行目以降: 詳細解説本文
    body_start = 3
    body = "\n\n".join(lines[body_start:])
    return intro, ranking_tickers, remarks, body


def build_markdown(intro, prices, ranking_tickers, remarks, body, report_date):
    price_map = {p.ticker: p for p in prices}
    final_list = [price_map[t] for t in ranking_tickers if t in price_map][:20]

    # フォールバック: AIランキングが取れなかった場合は全銘柄から先頭20件
    if not final_list:
        final_list = prices[:20]

    fm = (
        f'---\n'
        f'title: "{report_date} 投資レポート：不労所得を育てる本日の注目銘柄ベスト20"\n'
        f'pubDate: {report_date}\n'
        f'tags: ["高配当株", "不労所得"]\n'
        f'---\n\n'
    )

    content = f'<div class="lead-text">{intro}</div>\n\n## 📊 本日の注目銘柄ベスト20\n\n'
    content += '<div class="table-wrapper"><table class="stock-table">\n'
    content += '<thead><tr><th>順位</th><th>コード</th><th>銘柄名</th><th>配当率</th><th>終値</th><th>前日比</th><th>変化率</th><th>備考</th></tr></thead>\n'
    content += '<tbody>\n'

    for i, p in enumerate(final_list, 1):
        cls = "red-row" if p.change > 0 else ("green-row" if p.change < 0 else "")
        sign = "+" if p.change > 0 else ""
        remark = remarks.get(p.ticker, "-")
        content += (
            f'<tr class="{cls}">'
            f'<td class="text-center">{i}</td>'
            f'<td class="text-center"><strong>{p.ticker}</strong></td>'
            f'<td><strong>{p.name}</strong></td>'
            f'<td class="text-right">{p.yield_pc:.2f}%</td>'
            f'<td class="text-right">{p.close:,.1f}</td>'
            f'<td class="text-right">{sign}{p.change:,.1f}</td>'
            f'<td class="text-right">{sign}{p.change_pct:.2f}%</td>'
            f'<td>{remark}</td>'
            f'</tr>\n'
        )
    content += '</tbody></table></div>\n\n'

    books = "\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    for b in random.sample(BOOK_POOL, 3):
        img_url = get_amazon_img(b['asin'])
        books += (
            f'<div class="book-item">'
            f'<img src="{img_url}" alt="{b["title"]}" referrerpolicy="no-referrer" loading="lazy">'
            f'<div class="book-info">'
            f'<strong><a href="{b["url"]}" target="_blank" rel="noopener noreferrer">{b["title"]}</a></strong>'
            f'<p>{b["desc"]}</p>'
            f'</div></div>\n'
        )

    return fm + content + body + "\n\n" + books


def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices:
            print("Error: 価格データを取得できませんでした")
            return 1
        intro, ranking, remarks, body = generate_summary(prices, report_date)
        md = build_markdown(intro, prices, ranking, remarks, body, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print("Success")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
    