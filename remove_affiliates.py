"""
アフィリエイトリンクをMDXファイルから一括削除するスクリプト

削除対象:
1. import BookAffiliate/AmazonRakutenLink/CourseAffiliate の import行
2. <BookAffiliate .../> などのコンポーネント使用箇所（複数行）
3. その直前にある書籍紹介セクションヘッダー（## 📚 ...書籍... 等）
"""

import re
import os
import glob

BLOG_DIR = r"src\content\blog"

# 削除対象のimport行パターン
IMPORT_PATTERNS = [
    r"^import\s+BookAffiliate\s+from\s+['\"].*BookAffiliate\.astro['\"];?\s*$",
    r"^import\s+AmazonRakutenLink\s+from\s+['\"].*AmazonRakutenLink\.astro['\"];?\s*$",
    r"^import\s+CourseAffiliate\s+from\s+['\"].*CourseAffiliate\.astro['\"];?\s*$",
]

# 削除対象のコンポーネントタグ（開始パターン）
COMPONENT_STARTS = [
    "<BookAffiliate",
    "<AmazonRakutenLink",
    "<CourseAffiliate",
]

# 削除対象のセクションヘッダーキーワード（直後にコンポーネントがある場合のみ削除）
HEADER_KEYWORDS = [
    "おすすめ投資書籍",
    "あわせて読みたい書籍",
    "あわせて読みたいおすすめ投資書籍",
    "参考書籍",
    "参考資料・関連書籍",
    "初心者向けおすすめ投資書籍",
    "おすすめ書籍",
    "長期資産運用を深く学びたい方へ",
    "本日のテーマで選んだおすすめ投資書籍",
]


def should_delete_header(line):
    """この行が削除対象のセクションヘッダーか判定"""
    if not line.startswith("##"):
        return False
    for kw in HEADER_KEYWORDS:
        if kw in line:
            return True
    return False


def remove_affiliates_from_file(filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()

    original = content
    lines = content.split("\n")
    result_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # 1. import行を削除
        is_import = False
        for pat in IMPORT_PATTERNS:
            if re.match(pat, line.rstrip()):
                is_import = True
                break
        if is_import:
            i += 1
            continue

        # 2. セクションヘッダーチェック（削除対象ヘッダーか）
        if should_delete_header(line):
            # 次の非空行がコンポーネントタグなら、ヘッダーも削除
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and any(lines[j].strip().startswith(cs) for cs in COMPONENT_STARTS):
                # ヘッダーをスキップ（後続の空行も含めてスキップ）
                i += 1
                while i < len(lines) and lines[i].strip() == "":
                    i += 1
                continue

        # 3. コンポーネントタグの削除（複数行にまたがる）
        is_component = False
        for cs in COMPONENT_STARTS:
            if line.strip().startswith(cs):
                is_component = True
                break

        if is_component:
            # 閉じタグ />  または自己閉じ /> まで読み飛ばす
            # BookAffiliate は <BookAffiliate ... /> の形式
            # 単一行の場合もある
            block = line
            if "/>" in line:
                # 同一行で閉じている
                i += 1
                continue
            else:
                # 複数行: /> が出るまで読み飛ばす
                i += 1
                while i < len(lines):
                    block += "\n" + lines[i]
                    if "/>" in lines[i]:
                        i += 1
                        break
                    i += 1
                continue

        result_lines.append(line)
        i += 1

    # 連続する空行を最大2行に圧縮
    cleaned = []
    blank_count = 0
    for line in result_lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)

    new_content = "\n".join(cleaned)

    if new_content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True
    return False


def main():
    mdx_files = glob.glob(os.path.join(BLOG_DIR, "*.mdx"))
    changed = 0
    unchanged = 0

    for filepath in sorted(mdx_files):
        if remove_affiliates_from_file(filepath):
            print(f"[UPDATED] {os.path.basename(filepath)}")
            changed += 1
        else:
            unchanged += 1

    print(f"\nDone: {changed} updated, {unchanged} unchanged")


if __name__ == "__main__":
    main()
