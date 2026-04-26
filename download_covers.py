# -*- coding: utf-8 -*-
"""
書影ダウンロード＆URL解決スクリプト（毎回実行OK・冪等）

実行方法:
    python download_covers.py

動作:
1. books_data.json の全書籍について Google Books API → openBD → 楽天ブックス の順で
   書影URLを解決し、books_data.json の cover_url フィールドを更新（上書き）する。
2. 解決できた書影を public/images/books/{ISBN13}.jpg としてローカルに保存する。
3. cover_url が books_data.json に書き戻されるため、ローカル画像が存在しなくても
   generate_market_summary.py が cover_url を直接参照して書影を表示できる。

依存: 標準ライブラリのみ（urllib, json, re）
"""
import json
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path

BOOKS_JSON = Path("books_data.json")
PUBLIC_DIR = Path("public/images/books")
UA = "Mozilla/5.0 (compatible; astro-investment-blog/1.0; +https://github.com)"


def http_get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://books.rakuten.co.jp/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# ソース別 URL 取得
# ---------------------------------------------------------------------------
def cover_from_google_books(isbn13: str) -> str | None:
    """Google Books Volumes API（APIキー不要・最も安定）"""
    api = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{urllib.parse.quote(isbn13)}&country=JP"
    try:
        data = json.loads(http_get(api).decode("utf-8"))
        if not data.get("items"):
            return None
        links = (data["items"][0].get("volumeInfo") or {}).get("imageLinks", {}) or {}
        for k in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
            url = links.get(k)
            if url:
                # zoom=1 でより大きい画像を要求、http→https
                url = url.replace("http://", "https://")
                url = re.sub(r"zoom=\d+", "zoom=1", url)
                return url
    except Exception as e:
        print(f"  [google] fail: {e}", file=sys.stderr)
    return None


def cover_from_openbd(isbn13: str) -> str | None:
    """openBD API（日本書籍に強い・無料）"""
    api = f"https://api.openbd.jp/v1/get?isbn={urllib.parse.quote(isbn13)}"
    try:
        data = json.loads(http_get(api).decode("utf-8"))
        if data and isinstance(data, list) and data[0]:
            cover = (data[0].get("summary") or {}).get("cover")
            if cover and cover.startswith("http"):
                return cover.replace("http://", "https://")
    except Exception as e:
        print(f"  [openbd] fail: {e}", file=sys.stderr)
    return None


def cover_from_rakuten(rakuten_id: str, isbn13: str) -> str | None:
    """楽天ブックスHTMLから書影URLをスクレイプ（最終手段）"""
    if not rakuten_id:
        return None
    try:
        html = http_get(f"https://books.rakuten.co.jp/rb/{rakuten_id}/").decode("utf-8", errors="replace")
        last4 = isbn13[-4:]
        # 厳密パターン
        for pat in [
            re.compile(r"https://shop\.r10s\.jp/book/cabinet/" + re.escape(last4) + r"/" + re.escape(isbn13) + r"_1_\d+\.jpg"),
            re.compile(r"https://shop\.r10s\.jp/book/cabinet/[^/]+/" + re.escape(isbn13) + r"_\d+_\d+\.jpg"),
        ]:
            m = pat.search(html)
            if m:
                return m.group(0)
    except Exception as e:
        print(f"  [rakuten] fail: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# 書影ダウンロード
# ---------------------------------------------------------------------------
def download_image(url: str, dest: Path) -> bool:
    """URLから画像をダウンロードして保存。1KB未満は破損とみなす。"""
    try:
        data = http_get(url)
        if len(data) < 1024:
            print(f"  [warn] too small ({len(data)}B): {url}", file=sys.stderr)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception as e:
        print(f"  [warn] download fail: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> int:
    if not BOOKS_JSON.exists():
        print(f"Error: {BOOKS_JSON} not found", file=sys.stderr)
        return 1

    books_data = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    books = books_data.get("books", [])

    print("=" * 60)
    print(f"書影URL解決＆ダウンロード（{len(books)}冊）")
    print("=" * 60)

    updated = False
    success, failed = 0, []

    for b in books:
        isbn13 = b.get("isbn13", "")
        rakuten_id = b.get("rakuten_id", "")
        title_short = (b.get("title") or "")[:35]
        print(f"\n[{b['id']}] {title_short}…")
        print(f"  ISBN13={isbn13}")

        dest = PUBLIC_DIR / f"{isbn13}.jpg"

        # ローカルに既存かつ有効なファイルがあればスキップ
        if dest.exists() and dest.stat().st_size > 1024:
            print(f"  [skip] local file exists: {dest}")
            success += 1
            continue

        # URL解決: Google Books → openBD → 楽天
        url = None
        for name, getter in [
            ("google", lambda: cover_from_google_books(isbn13)),
            ("openbd", lambda: cover_from_openbd(isbn13)),
            ("rakuten", lambda: cover_from_rakuten(rakuten_id, isbn13)),
        ]:
            try:
                url = getter()
            except Exception as e:
                print(f"  [{name}] error: {e}", file=sys.stderr)
                url = None
            if url:
                print(f"  [{name}] URL: {url}")
                break
            else:
                print(f"  [{name}] not found")

        if not url:
            print(f"  [FAIL] cannot resolve cover URL")
            failed.append((b["id"], isbn13))
            continue

        # books_data.json の cover_url を更新
        if b.get("cover_url") != url:
            b["cover_url"] = url
            updated = True
            print(f"  [update] cover_url -> {url}")

        # ローカルに保存
        if download_image(url, dest):
            print(f"  [save] {dest} ({dest.stat().st_size:,}B)")
            success += 1
        else:
            # ダウンロード失敗でも cover_url は更新済みなので半成功
            print(f"  [warn] local save failed but cover_url updated")
            success += 1

    # books_data.json を書き戻す
    if updated:
        BOOKS_JSON.write_text(
            json.dumps(books_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n✓ books_data.json updated with resolved cover_url fields")

    print(f"\n" + "=" * 60)
    print(f"完了: 成功 {success}/{len(books)} 冊")
    if failed:
        print(f"失敗: {len(failed)} 冊")
        for fid, fisbn in failed:
            print(f"  - {fid} (ISBN={fisbn})")
        print("\n手動で公式サイトから書影URLを取得し books_data.json の cover_url に設定してください。")
    print("=" * 60)

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
