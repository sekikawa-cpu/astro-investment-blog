import { defineCollection, z } from 'astro:content';

const blog = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    description: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    author: z.string().default('Invest Insights 編集部'),
    category: z.enum(['マーケット分析', '資産運用', '投資戦略', '経済ニュース', '初心者ガイド', 'キーワード解説', 'コラム']).default('マーケット分析'),
    // slug: z.string().optional(),
    tags: z.array(z.string()).default([]),
    heroImage: z.string().optional(),
    draft: z.boolean().default(false),
  }),
});

export const collections = { blog };
