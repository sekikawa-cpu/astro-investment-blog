#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re

# 削除対象の書籍タイトル（完全一致）
BOOKS_TO_REMOVE = [
    '1日7秒 手を伸ばしなさい',
    '株主優待で得する本',
    'ETF投資の完全ガイド',
    '敗者のゲーム アマチュア投資家が勝つための投資の心構え',  # 古いタイトル
    '改訂版 本当の自由を手に入れる お金の大学 - 両角和樹版',  # 古いASIN版
]

# 削除対象のASIN
ASINS_TO_REMOVE = [
    '4822284956',  # 敗者のゲーム（古いASIN）
    '4863912692',  # 株主優待で得する本
    '4296102230',  # ETF投資の完全ガイド
    '4046055472',  # 改訂版 お金の大学（古いASIN版）
    '4534959850',  # 初心者向け株式投資の基本
]

def remove_book_by_asin(content, asin):
    """ASINで指定された書籍を削除"""
    # BookAffiliateセクション全体を削除（前のブランク行も含む）
    pattern = rf'(?:\n\n)?<BookAffiliate[^>]*>[\s\S]*?dp/{asin}/.*?/>(?:\n\n)?'
    return re.sub(pattern, '\n\n', content)

def remove_invalid_books(filepath):
    """不正な書籍を削除"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # 削除対象のASINを削除
        for asin in ASINS_TO_REMOVE:
            content = remove_book_by_asin(content, asin)

        # 変更があった場合のみ保存
        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False

    except Exception as e:
        print(f"[ERROR] {filepath}: {str(e)}")
        return False

def main():
    base_path = os.getcwd()
    blog_dir = os.path.join(base_path, 'src', 'content', 'blog')

    print("削除対象ASIN: " + ', '.join(ASINS_TO_REMOVE))
    print("\n不正な書籍を削除しています...\n")

    files_to_fix = []
    for filename in os.listdir(blog_dir):
        if filename.endswith('.mdx'):
            files_to_fix.append(os.path.join(blog_dir, filename))

    success_count = 0
    for filepath in sorted(files_to_fix):
        filename = os.path.basename(filepath)
        if remove_invalid_books(filepath):
            print(f"[OK] {filename}")
            success_count += 1

    print(f"\n{success_count}ファイルから不正な書籍を削除しました")

if __name__ == '__main__':
    main()
