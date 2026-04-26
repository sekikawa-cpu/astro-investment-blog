import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://astro-investment-blog-1gwd.vercel.app',
  integrations: [
    tailwind(),
    sitemap(),
  ],
});
