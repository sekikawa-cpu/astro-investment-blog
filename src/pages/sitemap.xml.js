import { getCollection } from 'astro:content';

export async function GET() {
  const allPosts = await getCollection('blog');
  const posts = allPosts.filter(p => !p.data.noindex);
  const site = 'https://tech-wealth-mind.com';

  // 末尾スラッシュあり（実際のサーバー配信形式に合わせる）
  const staticPages = [
    '/',
    '/profile/',
    '/contact/',
    '/privacy/',
    '/search/',
  ];

  const allPages = [
    ...staticPages.map(page => ({
      url: `${site}${page}`,
      lastmod: new Date().toISOString().split('T')[0],
      changefreq: 'weekly',
      priority: page === '/' ? '1.0' : '0.8',
    })),
    ...posts.map(post => ({
      url: `${site}/blog/${post.slug}/`,
      lastmod: post.data.updatedDate
        ? post.data.updatedDate.toISOString().split('T')[0]
        : post.data.pubDate.toISOString().split('T')[0],
      changefreq: 'monthly',
      priority: '0.7',
    })),
  ];

  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${allPages
  .map(
    page => `  <url>
    <loc>${page.url}</loc>
    <lastmod>${page.lastmod}</lastmod>
    <changefreq>${page.changefreq}</changefreq>
    <priority>${page.priority}</priority>
  </url>`
  )
  .join('\n')}
</urlset>`;

  return new Response(xml, {
    headers: {
      'Content-Type': 'application/xml',
    },
  });
}
