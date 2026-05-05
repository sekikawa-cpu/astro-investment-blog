#!/usr/bin/env python3
import re
import os
import glob

# Mapping of ASIN to book information
BOOKS_INFO = {
    "4046055472": {
        "title": "オートモードで月に18.5万円が入ってくる「高配当」株投資",
        "author": "長期株式投資",
        "asin": "4046055472"
    },
    "4478116989": {
        "title": "JUST KEEP BUYING 自動的に富が増え続ける「お金」と「時間」の法則",
        "author": "ニック・マジューリ",
        "asin": "4478116989"
    },
    "4023323780": {
        "title": "改訂版 本当の自由を手に入れる お金の大学",
        "author": "両＠リベ大学長",
        "asin": "4023323780"
    }
}

def extract_asin_from_url(url):
    match = re.search(r'dp/(\d+[A-Z0-9]*)', url)
    return match.group(1) if match else None

def convert_book_html_to_affiliate(content):
    """Convert old book-item divs to BookAffiliate components"""
    
    # Check if BookAffiliate import is already there
    if 'import BookAffiliate' not in content:
        # Add import after frontmatter
        lines = content.split('\n')
        frontmatter_end = 0
        in_frontmatter = False
        for i, line in enumerate(lines):
            if line.strip() == '---':
                if in_frontmatter:
                    frontmatter_end = i + 1
                    break
                else:
                    in_frontmatter = True
        
        import_line = "import BookAffiliate from '../../components/BookAffiliate.astro';"
        lines.insert(frontmatter_end + 1, import_line)
        content = '\n'.join(lines)
    
    # Replace old HTML book items with BookAffiliate components
    pattern = r'<div class="book-item" data-isbn="(\d+[A-Z0-9]*)">.*?<a href="([^"]+)"[^>]*><img src="[^"]+"[^>]*></a>.*?<strong><a href="[^"]*">([^<]+)</a></strong>.*?<p class="book-author">著者: ([^<]+)</p>.*?</div>\s*</div>\s*</div>'
    
    def replace_book(match):
        asin = match.group(1)
        amazon_url = match.group(2)
        title = match.group(3)
        author = match.group(4)
        
        image_url = f"https://m.media-amazon.com/images/P/{asin}.01.L.jpg"
        
        component = f'''<BookAffiliate 
  title="{title}"
  author="{author}"
  amazonUrl="{amazon_url}"
  imageUrl="{image_url}"
/>'''
        return component
    
    content = re.sub(pattern, replace_book, content, flags=re.DOTALL)
    
    # Fix disclaimer tag
    content = content.replace('<br>', '<br />')
    
    return content

# Process each file
files = glob.glob('src/content/blog/2026-*.mdx') + glob.glob('src/content/blog/*-haito-*.mdx')
for file_path in files:
    if os.path.basename(file_path) == '2026-04-25.mdx':  # Skip already processed
        continue
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if file has old HTML book items
        if 'book-item' in content:
            print(f"Converting {file_path}...")
            content = convert_book_html_to_affiliate(content)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"  ✓ Converted")
        else:
            print(f"Skipping {file_path} (no book items)")
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

print("Done!")
