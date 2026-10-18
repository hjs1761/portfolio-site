// @ts-check
import { defineConfig } from 'astro/config';

// canonical·og:url 이 이 주소로 만들어진다.
export default defineConfig({
  site: 'https://hwangjunseok.dev',
  output: 'static',
  trailingSlash: 'always',
  vite: {
    // 작은 스크립트도 HTML 에 넣지 않고 파일로 낸다 — CSP script-src 'self' 를 지키기 위해
    build: {
      assetsInlineLimit: 0,
    },
    server: {
      proxy: {
        '/api': 'http://127.0.0.1:8000',
      },
    },
  },
});
