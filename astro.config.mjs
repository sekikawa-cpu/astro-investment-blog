import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://astro-investment-blog-1gwd.vercel.app',
  integrations: [
    tailwind(),
  ],
});

