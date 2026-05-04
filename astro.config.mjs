import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  image: {
    domains: ['cover.openbd.jp', 'books.google.com', 'images-na.ssl-images-amazon.com'],
  },
  site: 'https://tech-wealth-mind.com',
  integrations: [
    tailwind(),
  ],
});

