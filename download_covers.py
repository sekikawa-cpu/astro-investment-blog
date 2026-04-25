# -*- coding: utf-8 -*-
"""
書影ダウンロードスクリプト（一度だけ実行すればOK）

実行方法:
    python download_covers.py

これを実行すると、books_data.json の全書籍について楽天ブックスから書影を取得し、
public/images/books/{ISBN13}.jpg として保存します。

リポジトリにコミットすれば、書影は永続的に表示されます。

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


def http_get(url: str, timeout: int = 15) -> bytes:
    """HTTP GET（楽天ブックスは User-Agent 必須）"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://books.rakuten.co.jp/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cover_url_from_rakuten(rakuten_id: str, isbn13: str) -> str | None:
    """楽天ブックスの商品ページHTMLから書影URLを抽出。"""
    if not rakuten_id:
        return None
    page_url = f"https://books.rakuten.co.jp/rb/{rakuten_id}/"
    try:
        body = http_get(page_url).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [warn] page fetch failed: {e}", file=sys.stderr)
        return None

    last4 = isbn13[-4:]
    pat1 = re.compile(
        r"https://shop\.r10s\.jp/book/cabinet/" + re.escape(last4) +
        r"/" + re.escape(isbn13) + r"_1_\d+\.jpg"
    )
    m = pat1.search(body)
    if m:
        return m.group(0)
    pat2 = re.compile(
        r"https://shop\.r10s\.jp/book/cabinet/[^/]+/" + re.escape(isbn13) + r"_\d+_\d+\.jpg"
    )
    m = pat2.search(body)
    if m:
        return m.group(0)
    return None


def cover_url_from_openbd(isbn13: str) -> str | None:
    """openBD API からカバー画像URLを取得（フォールバック）"""
    api = f"https://api.openbd.jp/v1/get?isbn={urllib.parse.quote(isbn13)}"
    try:
        data = json.loads(http_get(api).decode("utf-8"))
        if data and isinstance(data, list) and data[0]:
            cover = (data[0].get("summary") or {}).get("cover")
            if cover:
                return cover
    except Exception as e:
        print(f"  [warn] openBD fail: {e}", file=sys.stderr)
    return None


def cover_url_from_google_books(isbn13: str) -> str | None:
    """Google Books API（追加フォールバック）"""
    api = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{urllib.parse.quote(isbn13)}"
    try:
        data = json.loads(http_get(api).decode("utf-8"))
        if data and data.get("items"):
            links = (data["items"][0].get("volumeInfo") or {}).get("imageLinks", {}) or {}
            for k in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
                if links.get(k):
                    # zoom=1 の方が大きいので置き換え
                    u = links[k].replace("http://", "https://").replace("zoom=5", "zoom=1")
                    return u
    except Exception as e:
        print(f"  [warn] google books fail: {e}", file=sys.stderr)
    return None


def download_cover(isbn13: str, rakuten_id: str, dest: Path) -> bool:
    """3段階フォールバックで書影をDL → ローカル保存。"""
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"  [skip] {dest.name} already exists")
        return True

    sources = [
        ("rakuten", lambda: cover_url_from_rakuten(rakuten_id, isbn13)),
        ("openbd", lambda: cover_url_from_openbd(isbn13)),
        ("google", lambda: cover_url_from_google_books(isbn13)),
    ]
    for name, getter in sources:
        try:
            url = getter()
        except Exception as e:
            print(f"  [warn] {name} URL resolve fail: {e}", file=sys.stderr)
            continue
        if not url:
            print(f"  [info] {name}: no URL")
            continue
        try:
            print(f"  [{name}] downloading {url}")
            img_bytes = http_get(url)
            if len(img_bytes) < 1024:
                print(f"  [warn] {name}: image too small ({len(img_bytes)} bytes), skipping")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(img_bytes)
            print(f"  [ok]   saved {dest} ({len(img_bytes):,} bytes)")
            return True
        except Exception as e:
            print(f"  [warn] {name}: download failed: {e}", file=sys.stderr)
            continue

    print(f"  [FAIL] cannot fetch cover for ISBN={isbn13}")
    return False


def main() -> int:
    if not BOOKS_JSON.exists():
        print(f"Error: {BOOKS_JSON} not found", file=sys.stderr)
        return 1

    data = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    books = data.get("books", [])

    print(f"=" * 60)
    print(f"書影ダウンロード（{len(books)}冊）")
    print(f"=" * 60)

    success, failed = 0, []
    for b in books:
        isbn13 = b["isbn13"]
        rakuten_id = b.get("rakuten_id", "")
        title_short = (b.get("title", "") or "")[:30]
        print(f"\n[{b['id']}] {title_short}…  ISBN={isbn13}")
        dest = PUBLIC_DIR / f"{isbn13}.jpg"
        if download_cover(isbn13, rakuten_id, dest):
            success += 1
        else:
            failed.append((b["id"], isbn13))

    print(f"\n" + "=" * 60)
    print(f"完了: 成功 {success}/{len(books)} 冊")
    if failed:
        print(f"失敗: {len(failed)} 冊")
        for fid, fisbn in failed:
            print(f"  - {fid} (ISBN={fisbn})")
        print(f"\n失敗した書籍は手動で書影を public/images/books/{{ISBN13}}.jpg に置いてください。")
    print(f"=" * 60)

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
