#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re

# ASINのリスト（すべて）
ASIN_LIST = [
    '4046055472',  # オートモード
    '4478116989',  # JUST KEEP BUYING
    '4023323780',  # 改訂版 本当の自由（リベ大学長版）
    '4532359112',  # 敗者のゲーム（新しいASIN）
    '4822284956',  # 敗者のゲーム（古いASIN）
    'B088P5BLLL',  # 世界三大投資家
    '4492736476',  # ポートフォリオ最適化入門
    '4478109877',  # 難しいことはわかりませんが
    '17678901',    # 新NISA時代
    '4296113879',  # 個別銘柄分析
    '4534958315',  # 業界別株式投資
]

def standardize_image_urls(filepath):
    """画像URLを標準的なAmazon形式に統一"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original = content

        # すべてのASINについて、統一されたURL形式に変更
        # パターン1: m.media-amazon.com/images/P/{ASIN}...
        pattern1 = r'imageUrl="https://m\.media-amazon\.com/images/P/([A-Z0-9]+)\..*?\.jpg"'
        content = re.sub(pattern1, r'imageUrl="https://images-na.ssl-images-amazon.com/images/P/\1.01.LZZZZZZZ.jpg"', content)

        # パターン2: images-fe.ssl-images-amazon.com...
        pattern2 = r'imageUrl="https://images-fe\.ssl-images-amazon\.com/images/P/([A-Z0-9]+)\..*?\.jpg"'
        content = re.sub(pattern2, r'imageUrl="https://images-na.ssl-images-amazon.com/images/P/\1.01.LZZZZZZZ.jpg"', content)

        # パターン3: 既に正しい形式だが、バリエーションがある場合
        pattern3 = r'imageUrl="https://images-na\.ssl-images-amazon\.com/images/P/([A-Z0-9]+)\..*?\.jpg"'
        content = re.sub(pattern3, r'imageUrl="https://images-na.ssl-images-amazon.com/images/P/\1.01.LZZZZZZZ.jpg"', content)

        if content != original:
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

    print("Standardizing image URL format...\n")

    updated_count = 0
    for filename in os.listdir(blog_dir):
        if filename.endswith('.mdx'):
            filepath = os.path.join(blog_dir, filename)
            if standardize_image_urls(filepath):
                print(f"[OK] {filename}")
                updated_count += 1

    print(f"\nStandardized {updated_count} files")
    print("All image URLs now use: https://images-na.ssl-images-amazon.com/images/P/{ASIN}.01.LZZZZZZZ.jpg")

if __name__ == '__main__':
    main()
