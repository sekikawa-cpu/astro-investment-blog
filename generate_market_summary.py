"""
設定した20銘柄の終値・前日比を取得し、
Claude API に不労所得特化型の市場解説文を生成させて Astro ブログ用 Markdown として保存するスクリプト。
"""

from __future__ import annotations
import logging
import os
import sys
import time
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from requests.exceptions import RequestException

try:
    import anthropic
    from anthropic import APIError, APIConnectionError, RateLimitError
except ImportError:
    print("エラー: anthropic パッケージが必要です。`pip install anthropic` を実行してください。", file=sys.stderr)
    sys.exit(2)

# ---------- 設定 ----------
# 不労所得＆優待マネーマシン向けの厳選20銘柄
TICKERS: dict[str, str] = {
    # 王道インデックス＆ETF
    "1489.T": "日経高配当50ETF",
    "^GSPC": "S&P 500",
    "SPYD": "SPYD (米国高配当ETF)",
    "VYM": "VYM (米国高配当ETF)",
    # 日本の高配当・累進配当スター銘柄
    "2914.T": "JT (超高配当)",
    "8306.T": "三菱UFJFG (高配当)",
    "9432.T": "NTT (高配当・分割・優待)",
    "8058.T": "三菱商事 (累進配当)",
    "8593.T": "三菱HCキャピタル (連続増配)",
    "1605.T": "INPEX (高配当)",
    "1928.T": "積水ハウス (高配当)",
    "7203.T": "トヨタ自動車 (日本株代表・配当)",
    # 生活密着型の強力な株主優待銘柄
    "8267.T": "イオン (買い物・キャッシュバック優待)",
    "9433.T": "KDDI (連続増配・カタログ優待)",
    "2702.T": "日本マクドナルドHD (飲食優待)",
    "3197.T": "すかいらーくHD (飲食優待)",
    "9861.T": "吉野家HD (飲食優待)",
    "8282.T": "ケーズHD (家電優待・高配当)",
    "2503.T": "キリンHD (飲食料品優待)",
    "9202.T": "ANAHD (航空券優待)",
}

MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
FETCH_PERIOD = "5d"

# 修正箇所1：最新のClaudeモデルを指定
CLAUDE_MODEL = "claude-opus-4-7"
CLAUDE_MAX_TOKENS = 1500 
CLAUDE_MAX_RETRIES = 3
CLAUDE_INITIAL_BACKOFF = 3.0

OUTPUT_DIR = Path("src/content/blog")
TZ = ZoneInfo("Asia/Tokyo")

# ---------- 📚 おすすめ書籍のプール ----------
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
    """BOOK_POOLからランダムに3〜5冊を選んでセクションを作成する。"""
    num_to_select = random.randint(3, 5)
    selected_books = random.sample(BOOK_POOL, num_to_select)
    
    section = "\n---\n\n## 📚 本日の注目・おすすめ投資書籍\n\n"
    section += "市場動向と合わせてチェックしておきたい、資産形成に役立つ良書をピックアップしました。\n\n"
    
    for book in selected_books:
        section += f"- 📖 **[{book['title']}]({book['url']})**\n"
        section += f"  - {book['desc']}\n"
    
    section += "\n> ※ 上記リンクはAmazonアソシエイトリンクを使用しています。この記事の収益はサイトの維持・運営に役立てられます。\n"
    return section

# ---------- ロガー・データクラス ----------
def setup_logger(log_file: str = "generate_market_summary.log") -> logging.Logger:
    logger = logging.getLogger("market_summary")
    logger.setLevel(logging.INFO)
    if logger.handlers: return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout); sh.setFormatter(fmt); logger.addHandler(sh)
    try:
        fh = logging.FileHandler(log_file, encoding="utf-8"); fh.setFormatter(fmt); logger.addHandler(fh)
    except OSError: pass
    return logger

logger = setup_logger()

@dataclass
class PriceInfo:
    ticker: str; name: str; date: pd.Timestamp; close: float; prev_close: float
    @property
    def change(self) -> float: return self.close - self.prev_close
    @property
    def change_pct(self) -> float:
        if self.prev_close == 0: return 0.0
        return (self.change / self.prev_close) * 100
    def to_dict(self) -> dict:
        return {"ticker": self.ticker, "name": self.name, "date": self.date.strftime("%Y-%m-%d"),
                "close": round(self.close, 2), "prev_close": round(self.prev_close, 2),
                "change": round(self.change, 2), "change_pct": round(self.change_pct, 2)}

# ---------- 各種処理関数 ----------
def fetch_history(ticker: str, period: str = FETCH_PERIOD) -> pd.DataFrame:
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if df is None or df.empty: raise ValueError("Data empty")
            return df
        except Exception as e:
            if attempt < MAX_RETRIES: time.sleep(backoff); backoff *= 2
    raise RuntimeError(f"Failed to fetch {ticker}")

def extract_price_info(ticker: str, name: str, df: pd.DataFrame) -> PriceInfo:
    df_sorted = df.sort_index()
    latest, prev = df_sorted.iloc[-1], df_sorted.iloc[-2]
    return PriceInfo(ticker=ticker, name=name, date=df_sorted.index[-1], close=float(latest["Close"]), prev_close=float(prev["Close"]))

def collect_prices() -> list[PriceInfo]:
    """20銘柄中、エラーが起きてもスキップして可能な限りデータを集める仕様"""
    results: list[PriceInfo] = []
    for ticker, name in TICKERS.items():
        try:
            df = fetch_history(ticker)
            info = extract_price_info(ticker, name, df)
            results.append(info)
        except Exception as e:
            logger.warning(f"取得スキップ ({ticker}): {e}") # 1つ失敗しても全体は止めない
    return results

SYSTEM_PROMPT = """あなたは「配当金と株主優待で不労所得（マネーマシン）の構築を目指す個人投資家」に寄り添う、温かくも鋭いAI投資メンターです。
提供された20銘柄の株価データを元に、読者が「今日も投資を頑張ろう！」「長期保有を続けよう！」とモチベーションが上がるような魅力的なレポートを執筆してください。

記事の要件:
- 文字数は800〜1200字程度。絵文字（💰, 🎁, 📈など）を使って親しみやすく。
- すべての銘柄に言及する必要はありません。全体的な傾向や、特に動きの大きかった銘柄、読者が注目すべき数銘柄をピックアップして解説してください。
- 日々の価格の上下に一喜一憂するのではなく、「暴落時は高利回りで買えるチャンス」「優待・配当の長期的な恩恵」といった、不労所得を狙う投資家目線での考察を必ず入れること。
- 専門用語は適度に噛み砕き、これから資産形成を始める初心者にも理解できるレベルにすること。
- Markdown形式で出力し、記事本文のみを返す(frontmatterや大タイトルは不要)。

【記事の構成】以下の見出し(## または ###)を使って構造化してください。
1. 本日の不労所得トピックス（今日の相場を一言で表すポジティブな箇条書き）
2. 注目銘柄の動向（高配当ETFや優待銘柄の値動きが、私たちの配当利回りにどう影響するか）
3. メンターからのアドバイス（長期目線での心構えや、明日以降の戦略）
4. 免責事項（本記事は情報提供を目的としており、投資判断はご自身の責任で行ってください、という旨）
"""

def generate_summary(prices: list[PriceInfo], report_date: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key: raise RuntimeError("API Key missing")
    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = f"レポート対象日: {report_date}\n\n【本日の市場データ】\n" + "\n".join([str(p.to_dict()) for p in prices])
    
    response = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=CLAUDE_MAX_TOKENS, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )
    
    # 修正箇所2：安全なテキスト抽出処理
    text_parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(block.get("text", ""))
            
    if not text_parts:
        raise ValueError("Claudeからの応答にテキストが含まれていませんでした。")
        
    return "\n".join(text_parts).strip()

def build_markdown(prices: list[PriceInfo], summary_body: str, report_date: str) -> str:
    title = f"{report_date} 市場サマリー: 高配当ETFと優待銘柄の動向"
    frontmatter = f'---\ntitle: "{title}"\npubDate: {report_date}\ncategory: "マーケット分析"\nauthor: "Invest Insights"\n---\n\n'
    
    table = "## 本日の監視銘柄データ（全20種）\n\n| 銘柄 | 終値 | 前日比 | 変化率 |\n|---|---|---|---|\n"
    for p in prices:
        sign = "+" if p.change >= 0 else ""
        table += f"| {p.name} | {p.close:,.2f} | {sign}{p.change:,.2f} | {sign}{p.change_pct:.2f}% |\n"
    
    return frontmatter + table + "\n" + summary_body + get_dynamic_affiliate_section()

def main():
    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    try:
        prices = collect_prices()
        if not prices:
            raise ValueError("1件もデータを取得できませんでした。")
        summary = generate_summary(prices, report_date)
        md = build_markdown(prices, summary, report_date)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / f"{report_date}.md").write_text(md, encoding="utf-8")
        print(f"Success: {report_date}.md")
    except Exception as e:
        print(f"Error: {e}"); return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
    