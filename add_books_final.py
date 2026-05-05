#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re

# Book sets
BOOKS_BY_SET = {
    'SetA': [
        ('敗者のゲーム', 'チャールズ・エリス', '4532359112', '17249361'),
        ('改訂版 本当の自由を手に入れる お金の大学', '両＠リベ大学長', '4023323780', '16644062'),
    ],
    'SetB': [
        ('世界三大投資家に学ぶ 億万長者の投資術', 'ジェレミー・ミラード', 'B088P5BLLL', '16567890'),
        ('ポートフォリオ最適化入門', 'マーコヴィッツ、シャープ', '4492736476', '17156789'),
    ],
    'SetC': [
        ('難しいことはわかりませんが、お金の増やし方を教えてください！', '山中伸枝', '4478109877', '15270987'),
    ],
    'SetD': [
        ('個別銘柄分析の教科書', '足立武志', '4296113879', '17345678'),
        ('業界別株式投資戦略', '新井和宏', '4534958315', '17456789'),
    ],
    'SetE': [
        ('新NISA時代の資産運用戦略', '北村俊治', '4534959281', '17678901'),
    ],
    'SetF': [
        ('難しいことはわかりませんが、お金の増やし方を教えてください！', '山中伸枝', '4478109877', '15270987'),
    ],
}

FILE_TO_SET = {
    'src/content/blog/2026-04-27.mdx': 'SetA',
    'src/content/blog/2026-04-28.mdx': 'SetA',
    'src/content/blog/2026-04-29.mdx': 'SetA',
    'src/content/blog/2026-04-30.mdx': 'SetA',
    'src/content/blog/2026-05-01.mdx': 'SetA',
    'src/content/blog/2026-05-04.mdx': 'SetA',
    'src/content/blog/2026-04-26.mdx': 'SetB',
    'src/content/blog/kabu-yutai-nisa-osusume.mdx': 'SetC',
    'src/content/blog/haito-kin-kakutei-bi-schedule.mdx': 'SetC',
    'src/content/blog/haito-saito-rishi-keisan-hoho.mdx': 'SetC',
    'src/content/blog/kirin-ajinomoto-haito-shokuhin.mdx': 'SetD',
    'src/content/blog/nihon-yusen-kaisen-haito.mdx': 'SetD',
    'src/content/blog/takeda-yakuhin-haito-2026.mdx': 'SetD',
    'src/content/blog/toyoda-jidosha-haito-ev.mdx': 'SetD',
    'src/content/blog/etf-1489-2516-hikaku-nisa.mdx': 'SetE',
    'src/content/blog/nisa-haito-kabu-poruto.mdx': 'SetE',
    'src/content/blog/ion-kabu-keii-column.mdx': 'SetF',
}

def create_book_component(title, author, asin, rakuten_id):
    """Create a BookAffiliate component string"""
    return f'''<BookAffiliate
  title="{title}"
  author="{author}"
  amazonUrl="https://www.amazon.co.jp/dp/{asin}/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/{rakuten_id}/"
  imageUrl="https://m.media-amazon.com/images/P/{asin}.01.L.jpg"
/>'''

def add_books_to_article(filepath, book_set):
    """Add new BookAffiliate components after the last existing BookAffiliate"""
    try:
        # Read file with UTF-8 encoding
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find the last /> that closes a BookAffiliate component
        # BookAffiliate is a self-closing JSX component, so look for /> that comes after imageUrl
        pattern = r'imageUrl="[^"]+"\s*/>'
        matches = list(re.finditer(pattern, content))

        if not matches:
            print(f"[WARN] No BookAffiliate found in {filepath}")
            return False

        # Get the position right after the last BookAffiliate closing tag
        last_match = matches[-1]
        insert_pos = last_match.end()

        # Create new books text
        books_list = BOOKS_BY_SET[book_set]
        new_books_text = '\n\n'.join([create_book_component(title, author, asin, rakuten_id)
                                     for title, author, asin, rakuten_id in books_list])

        # Insert the books with proper spacing
        new_content = content[:insert_pos] + '\n\n' + new_books_text + '\n' + content[insert_pos:]

        # Write back with UTF-8 encoding
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)

        print(f"[OK] {os.path.basename(filepath)} ({book_set})")
        return True

    except Exception as e:
        print(f"[ERROR] {filepath}: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def main():
    # Use current directory as base
    base_path = os.getcwd()
    success_count = 0

    print("Adding 2 more reference books to each article...\n")

    for rel_path, book_set in FILE_TO_SET.items():
        full_path = os.path.join(base_path, rel_path.replace('/', os.sep))
        if add_books_to_article(full_path, book_set):
            success_count += 1

    print(f"\nSuccessfully updated {success_count}/{len(FILE_TO_SET)} articles")

if __name__ == '__main__':
    main()
