#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re
import requests
from bs4 import BeautifulSoup

# Book mapping: rakuten_id -> title
BOOKS_DATA = {
    '17249361': '敗者のゲーム',
    '16644062': '改訂版 本当の自由を手に入れる お金の大学',
    '16567890': '世界三大投資家に学ぶ 億万長者の投資術',
    '17156789': 'ポートフォリオ最適化入門',
    '15270987': '難しいことはわかりませんが、お金の増やし方を教えてください！',
    '17678901': '新NISA時代の資産運用戦略',
    '17345678': '個別銘柄分析の教科書',
    '17456789': '業界別株式投資戦略',
}

def get_book_image_from_rakuten(rakuten_id, title):
    """楽天書籍ページから画像URLをスクレイピング"""
    try:
        url = f"https://books.rakuten.co.jp/rb/{rakuten_id}/"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        print(f"[GET] {title}...", end=' ', flush=True)
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'

        # BeautifulSoupでHTMLを解析
        soup = BeautifulSoup(response.content, 'html.parser')

        # 画像を探す
        # 楽天の書籍ページにはいくつかの画像パターンがある
        img_tag = soup.find('img', {'alt': lambda x: x and '商品画像' in x})

        if not img_tag:
            # 別のパターンで探す
            img_tag = soup.find('img', class_=lambda x: x and 'book-image' in x)

        if not img_tag:
            # メイン画像を探す
            picture = soup.find('picture')
            if picture:
                img_tag = picture.find('img')

        if img_tag and img_tag.get('src'):
            image_url = img_tag['src']
            # HTTPSに統一
            if image_url.startswith('//'):
                image_url = 'https:' + image_url
            elif image_url.startswith('http://'):
                image_url = image_url.replace('http://', 'https://')

            print(f"OK")
            return image_url
        else:
            print(f"SKIP")
            return None

    except Exception as e:
        print(f"ERROR: {str(e)[:30]}")
        return None

def update_image_urls_in_files(image_url_map):
    """ファイル内の画像URLを更新"""
    base_path = os.getcwd()
    blog_dir = os.path.join(base_path, 'src', 'content', 'blog')

    updated_count = 0
    for filename in os.listdir(blog_dir):
        if not filename.endswith('.mdx'):
            continue

        filepath = os.path.join(blog_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content

            # 各rakuten_idについて画像URLを更新
            for rakuten_id, new_image_url in image_url_map.items():
                if not new_image_url:
                    continue

                # 正規表現で該当するrakuten_idの画像URLを置換
                pattern = rf'(rakutenUrl="https://books\.rakuten\.co\.jp/rb/{re.escape(rakuten_id)}/"\s+imageUrl=")[^"]*(")'
                replacement = rf'\1{new_image_url}\2'
                content = re.sub(pattern, replacement, content)

            # 変更があった場合のみ保存
            if content != original_content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
                print(f"  UPDATE: {filename}")
                updated_count += 1

        except Exception as e:
            print(f"  ERROR: {filename}")

    return updated_count

def main():
    print("="*60)
    print("Fetching book thumbnails from Rakuten")
    print("="*60 + "\n")

    # 楽天から各書籍の画像URLを取得
    image_url_map = {}
    for rakuten_id, title in BOOKS_DATA.items():
        image_url = get_book_image_from_rakuten(rakuten_id, title)
        if image_url:
            image_url_map[rakuten_id] = image_url

    print(f"\nSuccess: {len(image_url_map)}/{len(BOOKS_DATA)}\n")

    if image_url_map:
        print("Updating files...\n")
        updated = update_image_urls_in_files(image_url_map)
        print(f"\nUpdated {updated} files")
    else:
        print("No image URLs were fetched")

if __name__ == '__main__':
    main()
