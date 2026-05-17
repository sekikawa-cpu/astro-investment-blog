import { defineCollection, z } from 'astro:content';

const blog = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    author: z.string().default('ただの会社員'),
    pillar: z.enum(['投資', 'ビジネス・AI・DX', '心理学']).default('投資'),
    category: z.enum([
      // 投資
      'マーケット分析', '資産運用', '投資戦略', '経済ニュース', '初心者ガイド', 'キーワード解説',
      '用語・基礎知識', '銘柄分析', 'ファンド・ETF',
      // AI・DX
      'AI最新情報', 'DX・業務改善', '資格・学習',
      // 心理学
      '心理学・メンタル', '生きづらさと回復', '書籍レビュー',
      // 共通
      'コラム',
    ]).default('マーケット分析'),
    // slug: z.string().optional(),
    tags: z.array(z.string()).default([]),
    heroImage: z.string().optional(),
    draft: z.boolean().default(false),
    noindex: z.boolean().default(false),
  }),
});

export const collections = { blog };
