"""
1489.T(NEXT FUNDS 日経高配当50指数連動型ETF)と
S&P500(^GSPC)の最新終値・前日比を取得するスクリプト。

- yfinance でデータ取得
- 通信エラー等に対する指数バックオフ付きリトライ
- ログ出力(コンソール + ファイル)
- 取得不能時の明示的エラーハンドリング
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf
from requests.exceptions import RequestException


# ---------- 設定 ----------
TICKERS: dict[str, str] = {
    "1489.T": "NEXT FUNDS 日経高配当50指数連動型ETF",
    "^GSPC": "S&P 500",
}

MAX_RETRIES = 3          # 最大リトライ回数
INITIAL_BACKOFF = 2.0    # 初回待機秒数(指数バックオフ)
FETCH_PERIOD = "5d"      # 前日比を計算するため余裕を持って5営業日分取得


# ---------- ロガー ----------
def setup_logger(log_file: str = "fetch_prices.log") -> logging.Logger:
    """コンソールとファイル両方に出力するロガーを構成する。"""
    logger = logging.getLogger("fetch_prices")
    logger.setLevel(logging.INFO)

    # 二重登録を避ける
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    logger.addHandler(stream_handler)

    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as e:
        # ログファイルが作れなくてもコンソール出力は継続
        logger.warning("ログファイルを開けませんでした: %s", e)

    return logger


logger = setup_logger()


# ---------- データクラス ----------
@dataclass
class PriceInfo:
    """銘柄ごとの価格情報を格納するデータクラス。"""
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


# ---------- データ取得 ----------
def fetch_history(ticker: str, period: str = FETCH_PERIOD) -> pd.DataFrame:
    """
    yfinance から株価履歴を取得する。
    指数バックオフ付きでリトライし、最終的に失敗したら例外を投げる。
    """
    last_exc: Optional[Exception] = None
    backoff = INITIAL_BACKOFF

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info("取得試行 %d/%d: %s", attempt, MAX_RETRIES, ticker)
            # auto_adjust=False で Close をそのまま(終値)扱いにする
            df = yf.Ticker(ticker).history(period=period, auto_adjust=False)

            if df is None or df.empty:
                # データ空は一時的な可能性もあるのでリトライ対象にする
                raise ValueError(f"{ticker} のデータが空です(市場休場や遅延の可能性)")

            return df

        except (RequestException, ValueError, KeyError) as e:
            last_exc = e
            logger.warning(
                "取得失敗 (%s): %s — %.1f秒後にリトライします",
                ticker, e, backoff,
            )
            if attempt < MAX_RETRIES:
                time.sleep(backoff)
                backoff *= 2  # 指数バックオフ
        except Exception as e:
            # 予期しない例外はリトライせずに即時停止(握り潰さない)
            logger.exception("予期しないエラー (%s): %s", ticker, e)
            raise

    # ここに来たらリトライ全滅
    raise RuntimeError(
        f"{ticker} の取得に {MAX_RETRIES} 回失敗しました"
    ) from last_exc


def extract_price_info(ticker: str, name: str, df: pd.DataFrame) -> PriceInfo:
    """履歴DataFrameから最新終値と前日終値を取り出す。"""
    if len(df) < 2:
        raise ValueError(
            f"{ticker} は前日比計算に必要な2営業日分のデータがありません(取得件数: {len(df)})"
        )

    df_sorted = df.sort_index()
    latest_row = df_sorted.iloc[-1]
    prev_row = df_sorted.iloc[-2]

    close = float(latest_row["Close"])
    prev_close = float(prev_row["Close"])

    if pd.isna(close) or pd.isna(prev_close):
        raise ValueError(f"{ticker} の終値に欠損値(NaN)が含まれています")

    return PriceInfo(
        ticker=ticker,
        name=name,
        date=df_sorted.index[-1],
        close=close,
        prev_close=prev_close,
    )


def format_price(info: PriceInfo) -> str:
    """人間が読みやすい形式にフォーマットする。"""
    sign = "+" if info.change >= 0 else ""
    arrow = "▲" if info.change > 0 else ("▼" if info.change < 0 else "─")
    date_str = info.date.strftime("%Y-%m-%d")
    return (
        f"{info.ticker:<8} ({info.name})\n"
        f"  日付       : {date_str}\n"
        f"  終値       : {info.close:,.2f}\n"
        f"  前日終値   : {info.prev_close:,.2f}\n"
        f"  前日比     : {arrow} {sign}{info.change:,.2f} "
        f"({sign}{info.change_pct:.2f}%)"
    )


# ---------- メイン ----------
def main() -> int:
    logger.info("=== 株価取得開始 ===")
    results: list[PriceInfo] = []
    errors: list[tuple[str, Exception]] = []

    for ticker, name in TICKERS.items():
        try:
            df = fetch_history(ticker)
            info = extract_price_info(ticker, name, df)
            results.append(info)
            logger.info(
                "取得成功: %s 終値=%.2f 前日比=%+.2f (%+.2f%%)",
                ticker, info.close, info.change, info.change_pct,
            )
        except Exception as e:
            logger.error("取得断念: %s — %s", ticker, e)
            errors.append((ticker, e))

    # --- 結果表示 ---
    print("\n" + "=" * 56)
    print(" 株価サマリー")
    print("=" * 56)
    for info in results:
        print(format_price(info))
        print("-" * 56)

    if errors:
        print("\n取得できなかった銘柄:")
        for ticker, e in errors:
            print(f"  - {ticker}: {e}")

    logger.info(
        "=== 株価取得終了(成功: %d件、失敗: %d件) ===",
        len(results), len(errors),
    )

    # 1件でも失敗があれば終了コード 1(cron等で検知しやすくするため)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
