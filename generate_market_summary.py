"""
1489.T(NEXT FUNDS 日経高配当50指数連動型ETF)と S&P500(^GSPC)の終値・前日比を取得し、
Claude API に市場解説文を生成させて Astro ブログ用 Markdown として保存するスクリプト。

処理フロー:
  1. yfinance で価格取得(指数バックオフ付きリトライ)
  2. Claude API に解説生成を依頼(リトライ付き)
  3. Frontmatter 付き Markdown を src/content/blog/YYYY-MM-DD.md として保存

必要な環境変数:
  ANTHROPIC_API_KEY  — Claude API のキー

使い方:
  pip install yfinance pandas anthropic
  export ANTHROPIC_API_KEY="sk-ant-..."
  python generate_market_summary.py
"""

from __future__ import annotations

import logging
import os
import sys
import time
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
TICKERS: dict[str, str] = {
    "1489.T": "NEXT FUNDS 日経高配当50指数連動型ETF",
    "^GSPC": "S&P 500",
}

# 価格取得
MAX_RETRIES = 3
INITIAL_BACKOFF = 2.0
FETCH_PERIOD = "5d"

# Claude API
CLAUDE_MODEL = "claude-opus-4-7"
CLAUDE_MAX_TOKENS = 1200
CLAUDE_MAX_RETRIES = 3
CLAUDE_INITIAL_BACKOFF = 3.0

# 出力先(Astro プロジェクトの src/content/blog/ 配下)
OUTPUT_DIR = Path("src/content/blog")

# タイムゾーン(日付の基準)
TZ = ZoneInfo("Asia/Tokyo")

# アフィリエイト・リンクのプレースホルダー
# 実運用時は実際のリンクに差し替える
AFFILIATE_SECTION = """
---

## 🔗 関連リンク

本記事で紹介した指数・ETFへの投資に関心のある方は、以下のリンクから各証券会社の口座開設ページをご覧いただけます。

- 📈 [証券会社A で口座開設する](https://example.com/affiliate/broker-a?ref=PLACEHOLDER)
- 💰 [証券会社B の積立NISA口座](https://example.com/affiliate/broker-b?ref=PLACEHOLDER)
- 📚 [投資の書籍をAmazonで見る](https://example.com/affiliate/amazon?ref=PLACEHOLDER)

> ※ 上記リンクはアフィリエイト広告を含みます。リンク経由でのお申し込みにより、当サイトに収益が発生する場合があります。
"""


# ---------- ロガー ----------
def setup_logger(log_file: str = "generate_market_summary.log") -> logging.Logger:
    logger = logging.getLogger("market_summary")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    try:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError as e:
        logger.warning("ログファイルを開けませんでした: %s", e)

    return logger


logger = setup_logger()


# ---------- データクラス ----------
@dataclass
class PriceInfo:
    ticker: str
    name: str
    date: pd.Timestamp
    close: float
    prev_close: float

    @property
    def change(self) -> float:
        return self.close - self.prev_close

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.change / self.prev_close) * 100

    def to_dict(self) -> dict:
        """LLM に渡すための辞書表現。"""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "date": self.date.strftime("%Y-%m-%d"),
            "close": round(self.close, 2),
            "prev_close": round(self.prev_close, 2),
            "change": round(self.change, 2),
            "change_pct": round(self.change_pct, 2),
        }


# ---------- 価格取得 ----------
def fetch_history(ticker: str, period: str = FETCH_PERIOD) -> pd.DataFrame:
    last_exc: Optional[Exception] = None
    backoff = INITIAL_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("価格取得 %d/%d: %s", attempt, MAX_RETRIES, ticker)
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if df is None or df.empty:
                raise ValueError(f"{ticker} のデータが空です")
            return df
        except (RequestException, ValueError, KeyError) as e:
            last_exc = e
            logger.warning("取得失敗 (%s): %s — %.1f秒後にリトライ", ticker, e, backoff)
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
        except Exception as e:
            logger.exception("予期しないエラー (%s)", ticker)
            raise

    raise RuntimeError(f"{ticker} の取得に {MAX_RETRIES} 回失敗しました") from last_exc


def extract_price_info(ticker: str, name: str, df: pd.DataFrame) -> PriceInfo:
    if len(df) < 2:
        raise ValueError(f"{ticker}: 2営業日分のデータがありません(取得件数: {len(df)})")

    df_sorted = df.sort_index()
    latest = df_sorted.iloc[-1]
    prev = df_sorted.iloc[-2]

    close = float(latest["Close"])
    prev_close = float(prev["Close"])
    if pd.isna(close) or pd.isna(prev_close):
        raise ValueError(f"{ticker}: 終値に NaN が含まれています")

    return PriceInfo(
        ticker=ticker,
        name=name,
        date=df_sorted.index[-1],
        close=close,
        prev_close=prev_close,
    )


def collect_prices() -> list[PriceInfo]:
    """全銘柄の価格を取得。失敗した銘柄があれば例外を投げる(記事生成には全銘柄必要)。"""
    results: list[PriceInfo] = []
    for ticker, name in TICKERS.items():
        df = fetch_history(ticker)
        info = extract_price_info(ticker, name, df)
        logger.info(
            "取得成功: %s 終値=%.2f 前日比=%+.2f (%+.2f%%)",
            ticker, info.close, info.change, info.change_pct,
        )
        results.append(info)
    return results


# ---------- Claude API による解説生成 ----------
SYSTEM_PROMPT = """あなたは日本の個人投資家向けの金融ライターです。
提供された株価データを元に、中立的で事実に基づいた市場サマリー記事を日本語で執筆してください。

記事の要件:
- 文字数は600〜900字程度
- 読者は投資初心者〜中級者
- 断定的な将来予測や投資推奨は避け、「〜の可能性がある」「〜と見られる」など慎重な表現を使う
- 与えられた数値データのみを事実として扱い、架空の情報や出所不明の情報は追加しない
- 見出し(##)を2〜3個使って構造化する
- 最後に「本記事は情報提供を目的としており、投資判断はご自身の責任で行ってください」という注意書きを添える
- Markdown形式で出力し、記事本文のみを返す(frontmatterやタイトルは不要)
"""


def build_user_prompt(prices: list[PriceInfo], report_date: str) -> str:
    """LLM に渡すユーザープロンプトを組み立てる。"""
    lines = [f"【レポート対象日】{report_date}", "", "【本日の市場データ】"]
    for p in prices:
        d = p.to_dict()
        sign = "+" if d["change"] >= 0 else ""
        lines.append(
            f"- {d['name']}({d['ticker']})"
            f" 終値: {d['close']:,.2f} / 前日比: {sign}{d['change']:.2f} "
            f"({sign}{d['change_pct']:.2f}%) / 基準日: {d['date']}"
        )
    lines += [
        "",
        "上記のデータを元に、日本の高配当株(日経平均高配当50)と"
        "米国株(S&P 500)の動向を比較する市場サマリー記事を作成してください。",
    ]
    return "\n".join(lines)


def generate_summary(prices: list[PriceInfo], report_date: str) -> str:
    """Claude API を呼び出して市場サマリーを生成する。リトライ付き。"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("環境変数 ANTHROPIC_API_KEY が設定されていません")

    client = anthropic.Anthropic(api_key=api_key)
    user_prompt = build_user_prompt(prices, report_date)

    last_exc: Optional[Exception] = None
    backoff = CLAUDE_INITIAL_BACKOFF

    for attempt in range(1, CLAUDE_MAX_RETRIES + 1):
        try:
            logger.info("Claude API 呼び出し %d/%d (model=%s)",
                        attempt, CLAUDE_MAX_RETRIES, CLAUDE_MODEL)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # 応答からテキストブロックを抽出
            text_parts = [
                block.text for block in response.content
                if getattr(block, "type", None) == "text"
            ]
            text = "\n".join(text_parts).strip()

            if not text:
                raise ValueError("Claude API から空の応答が返されました")

            logger.info("Claude API 成功(入力 %d / 出力 %d トークン)",
                        response.usage.input_tokens, response.usage.output_tokens)
            return text

        except (RateLimitError, APIConnectionError) as e:
            # レート制限や一時的な接続エラーはリトライ
            last_exc = e
            logger.warning("一時的な API エラー: %s — %.1f秒後にリトライ", e, backoff)
            if attempt < CLAUDE_MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2
        except APIError as e:
            # 400系は基本リトライしても無駄なので即停止
            logger.error("Claude API エラー(非リトライ対象): %s", e)
            raise
        except ValueError as e:
            # 空応答はリトライする価値がある
            last_exc = e
            logger.warning("%s — %.1f秒後にリトライ", e, backoff)
            if attempt < CLAUDE_MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2

    raise RuntimeError(f"Claude API 呼び出しに {CLAUDE_MAX_RETRIES} 回失敗しました") from last_exc


# ---------- Markdown 生成 ----------
def yaml_escape(s: str) -> str:
    """frontmatter 用に安全な文字列(ダブルクォート)に整形。"""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def build_markdown(prices: list[PriceInfo], summary_body: str, report_date: str) -> str:
    """frontmatter + 価格サマリー表 + LLM 生成本文 + アフィリエイトを結合する。"""
    # タイトル・description を数値ベースで生成
    nikkei = next((p for p in prices if p.ticker == "1489.T"), None)
    sp500 = next((p for p in prices if p.ticker == "^GSPC"), None)

    def trend_word(p: Optional[PriceInfo]) -> str:
        if p is None:
            return "データ欠損"
        if p.change > 0:
            return "上昇"
        if p.change < 0:
            return "下落"
        return "横ばい"

    title = f"{report_date} 市場サマリー:高配当ETFとS&P500の動向"
    description = (
        f"{report_date}時点の市場レポート。"
        f"日経高配当50連動ETF(1489.T)は{trend_word(nikkei)}、"
        f"S&P 500は{trend_word(sp500)}。主要指数の終値と前日比を解説します。"
    )
    tags = ["市場サマリー", "高配当ETF", "S&P500", "日経平均"]

    # frontmatter(Astro Content Collections のスキーマに合わせる)
    frontmatter_lines = [
        "---",
        f'title: "{yaml_escape(title)}"',
        f'description: "{yaml_escape(description)}"',
        f"pubDate: {report_date}",
        'category: "マーケット分析"',
        "tags:",
    ]
    frontmatter_lines += [f'  - "{yaml_escape(t)}"' for t in tags]
    frontmatter_lines += [
        'author: "Invest Insights 編集部"',
        "draft: false",
        "---",
        "",
    ]

    # データ表(事実ベースの部分は機械的に生成してLLMの誤記リスクを減らす)
    table_lines = [
        "## 本日の市場データ",
        "",
        "| 銘柄 | 終値 | 前日比 | 変化率 |",
        "|------|------|--------|--------|",
    ]
    for p in prices:
        sign = "+" if p.change >= 0 else ""
        table_lines.append(
            f"| {p.name} ({p.ticker}) "
            f"| {p.close:,.2f} "
            f"| {sign}{p.change:,.2f} "
            f"| {sign}{p.change_pct:.2f}% |"
        )
    table_lines.append("")
    table_lines.append(f"*基準日: {report_date}(データソース: Yahoo! Finance)*")
    table_lines.append("")

    return "\n".join(frontmatter_lines) + "\n".join(table_lines) + "\n" + summary_body + "\n" + AFFILIATE_SECTION


def save_markdown(content: str, report_date: str, output_dir: Path = OUTPUT_DIR) -> Path:
    """src/content/blog/YYYY-MM-DD.md として保存する。既存ファイルは上書き警告。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{report_date}.md"
    if out_path.exists():
        logger.warning("既存ファイルを上書きします: %s", out_path)

    out_path.write_text(content, encoding="utf-8")
    logger.info("保存完了: %s (%d バイト)", out_path, len(content.encode("utf-8")))
    return out_path


# ---------- メイン ----------
def main() -> int:
    logger.info("=== 市場サマリー生成開始 ===")

    report_date = datetime.now(TZ).strftime("%Y-%m-%d")
    logger.info("レポート対象日: %s", report_date)

    try:
        prices = collect_prices()
    except Exception as e:
        logger.error("価格取得に失敗したため処理を中止します: %s", e)
        return 1

    try:
        summary_body = generate_summary(prices, report_date)
    except Exception as e:
        logger.error("Claude API での記事生成に失敗しました: %s", e)
        return 1

    try:
        md = build_markdown(prices, summary_body, report_date)
        out_path = save_markdown(md, report_date)
    except OSError as e:
        logger.error("Markdown 保存に失敗しました: %s", e)
        return 1

    print(f"\n✅ 記事を生成しました: {out_path}")
    logger.info("=== 市場サマリー生成完了 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
