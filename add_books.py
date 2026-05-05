#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os

# Define books for each set
BOOKS_BY_SET = {
    'SetA': '''<BookAffiliate
  title="敗者のゲーム アマチュア投資家が勝つための投資の心構え"
  author="チャールズ・エリス、福山京一郎"
  amazonUrl="https://www.amazon.co.jp/dp/4822284956/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17249361/"
  imageUrl="https://m.media-amazon.com/images/P/4822284956.01.L.jpg"
/>

<BookAffiliate
  title="改訂版 本当の自由を手に入れる お金の大学"
  author="両角和樹"
  amazonUrl="https://www.amazon.co.jp/dp/4046055472/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/16983127/"
  imageUrl="https://m.media-amazon.com/images/P/4046055472.01.L.jpg"
/>''',

    'SetB': '''<BookAffiliate
  title="世界三大投資家に学ぶ 億万長者の投資術"
  author="ジェレミー・ミラード"
  amazonUrl="https://www.amazon.co.jp/dp/B088P5BLLL/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/16567890/"
  imageUrl="https://m.media-amazon.com/images/P/B088P5BLLL.01.L.jpg"
/>

<BookAffiliate
  title="ポートフォリオ最適化入門"
  author="マーコヴィッツ、シャープ"
  amazonUrl="https://www.amazon.co.jp/dp/4492736476/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17156789/"
  imageUrl="https://m.media-amazon.com/images/P/4492736476.01.L.jpg"
/>''',

    'SetC': '''<BookAffiliate
  title="難しいことはわかりませんが、お金の増やし方を教えてください！"
  author="山中伸枝"
  amazonUrl="https://www.amazon.co.jp/dp/4478109877/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/15270987/"
  imageUrl="https://m.media-amazon.com/images/P/4478109877.01.L.jpg"
/>

<BookAffiliate
  title="株主優待で得する本"
  author="大岩楢橋"
  amazonUrl="https://www.amazon.co.jp/dp/4863912692/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/16234567/"
  imageUrl="https://m.media-amazon.com/images/P/4863912692.01.L.jpg"
/>''',

    'SetD': '''<BookAffiliate
  title="個別銘柄分析の教科書"
  author="足立武志"
  amazonUrl="https://www.amazon.co.jp/dp/4296113879/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17345678/"
  imageUrl="https://m.media-amazon.com/images/P/4296113879.01.L.jpg"
/>

<BookAffiliate
  title="業界別株式投資戦略"
  author="新井和宏"
  amazonUrl="https://www.amazon.co.jp/dp/4534958315/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17456789/"
  imageUrl="https://m.media-amazon.com/images/P/4534958315.01.L.jpg"
/>''',

    'SetE': '''<BookAffiliate
  title="ETF投資の完全ガイド"
  author="岡本和久"
  amazonUrl="https://www.amazon.co.jp/dp/4296102230/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17567890/"
  imageUrl="https://m.media-amazon.com/images/P/4296102230.01.L.jpg"
/>

<BookAffiliate
  title="新NISA時代の資産運用戦略"
  author="北村俊治"
  amazonUrl="https://www.amazon.co.jp/dp/4534959281/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17678901/"
  imageUrl="https://m.media-amazon.com/images/P/4534959281.01.L.jpg"
/>''',

    'SetF': '''<BookAffiliate
  title="難しいことはわかりませんが、お金の増やし方を教えてください！"
  author="山中伸枝"
  amazonUrl="https://www.amazon.co.jp/dp/4478109877/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/15270987/"
  imageUrl="https://m.media-amazon.com/images/P/4478109877.01.L.jpg"
/>

<BookAffiliate
  title="初心者向け株式投資の基本"
  author="田中孝顕"
  amazonUrl="https://www.amazon.co.jp/dp/4534959850/?tag=investinsight-22"
  rakutenUrl="https://books.rakuten.co.jp/rb/17789012/"
  imageUrl="https://m.media-amazon.com/images/P/4534959850.01.L.jpg"
/>''',
}

# File to set mapping
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

def add_books_to_article(filepath, book_set):
    """Add new BookAffiliate components after the last existing reference book"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split into lines for easier manipulation
        lines = content.split('\n')

        # Find the last /> from a BookAffiliate, accounting for the section being in the middle of the file
        last_book_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if '/>' in lines[i]:
                # Check if this is from a BookAffiliate (look in preceding context)
                context = '\n'.join(lines[max(0, i - 10):i + 1])
                if 'BookAffiliate' in context:
                    last_book_idx = i
                    break

        if last_book_idx == -1:
            print(f"[WARN] No BookAffiliate found in {filepath}")
            return False

        # Insert after the blank line following the last book
        # This ensures new books go before any disclaimer/closing content
        insert_idx = last_book_idx + 2

        # Get the books to add
        new_books = BOOKS_BY_SET[book_set]

        # Insert the new books
        lines.insert(insert_idx, new_books)
        lines.insert(insert_idx + 1, '')  # Add blank line for formatting

        # Write back
        new_content = '\n'.join(lines)
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
    base_path = 'C:\\Apps\\astro-investment-blog'
    success_count = 0

    print("Adding books to articles...\n")

    for rel_path, book_set in FILE_TO_SET.items():
        rel_path_windows = rel_path.replace('/', '\\')
        full_path = os.path.join(base_path, rel_path_windows)
        if add_books_to_article(full_path, book_set):
            success_count += 1

    print(f"\nSuccessfully updated {success_count}/{len(FILE_TO_SET)} articles")

if __name__ == '__main__':
    main()
