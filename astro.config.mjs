import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';
import mdx from '@astrojs/mdx';

export default defineConfig({
  image: {
    domains: ['cover.openbd.jp', 'books.google.com', 'images-na.ssl-images-amazon.com', 'img-c.udemycdn.com', 'm.media-amazon.com'],
  },
  site: 'https://tech-wealth-mind.com/',
  trailingSlash: 'always',
  integrations: [
    tailwind(),
    mdx(),
  ],
  vite: {
    ssr: {
      external: ['@astrojs/tailwind'],
    },
  },
});

