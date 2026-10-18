// 한 화면 캡처: node tools/clip.mjs <폭> <높이> <경로> <스크롤y> <출력.png> [dark|light]
// 브라우저는 이미 받아 둔 Chromium(shots.mjs 와 같음). 움직임 줄이기로 찍어 애니메이션 중간 상태를 피한다.
import { chromium } from 'playwright-core';
import { homedir } from 'node:os';

const [w, h, path, y = '0', out, theme = 'dark'] = process.argv.slice(2);
if (!w || !h || !path || !out) {
  console.error('사용: node tools/clip.mjs <폭> <높이> <경로> <스크롤y> <출력.png> [dark|light]');
  process.exit(2);
}
const base = process.env.BASE ?? 'http://127.0.0.1:8088';
const exe =
  process.env.CHROME ??
  `${homedir()}/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
const b = await chromium.launch({ executablePath: exe });
const ctx = await b.newContext({ viewport: { width: +w, height: +h }, reducedMotion: 'reduce' });
await ctx.addInitScript((t) => localStorage.setItem('theme', t), theme);
const p = await ctx.newPage();
await p.goto(base + path, { waitUntil: 'networkidle' });
await p.evaluate((yy) => window.scrollTo(0, yy), +y);
await p.waitForTimeout(300);
await p.screenshot({ path: out });
await b.close();
