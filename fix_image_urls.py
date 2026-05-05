#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re

# 異なる画像URL形式を試す（優先順位順）
IMAGE_URL_FORMATS = [
    # 形式1: 標準的なNS形式（最も確実）
    lambda asin: f"https://images-na.ssl-images-amazon.com/images/P/{asin}.01.LZZZZZZZ.jpg",
    # 形式2: モバイルメディア形式（.09版）
    lambda asin: f"https://m.media-amazon.com/images/P/{asin}.09.L.jpg",
    # 形式3: FE形式
    lambda asin: f"https://images-fe.ssl-images-amazon.com/images/P/{asin}.01.L.jpg",
]

def extract_asin(url):
    """URLからASINを抽出"""
    match = re.search(r'/P/([A-Z0-9]+)', url)
    if match:
        return match.group(1)
    return None

def fix_image_urls(filepath, format_index=0):
    """画像URLをより標準的なフォーマットに変更"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # すべてのimageUrl属性を見つけて、ASINを抽出し、新しいURLに置換
        def replace_url(match):
            old_url = match.group(1)
            asin = extract_asin(old_url)
            if asin:
                new_url = IMAGE_URL_FORMATS[format_index](asin)
                return f'imageUrl="{new_url}"'
            return match.group(0)

        # imageUrl="..." パターンを置換
        new_content = re.sub(r'imageUrl="([^"]*)"', replace_url, content)

        # 変更があった場合のみファイルを更新
        if new_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True
        return False

    except Exception as e:
        print(f"[ERROR] {filepath}: {str(e)}")
        return False

def main():
    base_path = os.getcwd()

    # すべてのブログファイルを見つける
    blog_dir = os.path.join(base_path, 'src', 'content', 'blog')
    files_to_fix = []

    for filename in os.listdir(blog_dir):
        if filename.endswith('.mdx'):
            files_to_fix.append(os.path.join(blog_dir, filename))

    # フォーマット0を使用（推奨フォーマット）
    format_index = 0
    print(f"画像URL形式を更新しています...")
    print(f"使用フォーマット: {IMAGE_URL_FORMATS[format_index]('ASIN').replace('ASIN', '{ASIN}')}\n")

    success_count = 0
    for filepath in sorted(files_to_fix):
        filename = os.path.basename(filepath)
        if fix_image_urls(filepath, format_index):
            print(f"[OK] {filename}")
            success_count += 1
        else:
            print(f"[SKIP] {filename} (変更なし)")

    print(f"\n{success_count}ファイルの画像URL形式を更新しました")

if __name__ == '__main__':
    main()
