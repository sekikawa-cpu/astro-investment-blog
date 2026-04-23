import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  // Vercelから提供される一時的なURLでも動くように、仮のURLを設定します
  site: 'https://example.com', 
  integrations: [sitemap()],
});
