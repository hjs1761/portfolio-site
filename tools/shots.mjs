// 화면 캡처 + 가로 넘침 검사.
// 사용: node tools/shots.mjs http://127.0.0.1:8088
// 브라우저는 이미 받아 둔 Chromium 을 쓴다(CHROME 환경변수로 바꿀 수 있음). 결과는 tools/out/.
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import { homedir } from 'node:os';

const base = (process.argv[2] ?? 'http://127.0.0.1:8088').replace(/\/$/, '');
const exe =
  process.env.CHROME ??
  `${homedir()}/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
const out = new URL('./out/', import.meta.url).pathname;
mkdirSync(out, { recursive: true });

const pages = [
  ['home', '/'],
  ['projects', '/projects/'],
  ['project-neopharm', '/projects/neopharm/'],
  ['project-amore', '/projects/amore-d2c/'],
  ['project-krafton', '/projects/krafton/'],
  ['project-foundation', '/projects/roh-foundation/'],
  ['project-jiradoo', '/projects/jiradoo/'],
  ['project-rag', '/projects/rag-search/'],
  ['project-artifacts', '/projects/artifacts/'],
  ['case-guard', '/projects/deploy-guard/'],
  ['resume', '/resume/'],
  ['ai', '/ai/'],
  ['colophon', '/colophon/'],
  ['notfound', '/no-such-page/'],
];
const widths = [
  ['d', 1440, 900],
  ['m', 390, 844],
];
const themes = ['dark', 'light'];

const browser = await chromium.launch({ executablePath: exe });
const problems = [];

for (const theme of themes) {
  for (const [wName, width, height] of widths) {
    const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
    await ctx.addInitScript((t) => localStorage.setItem('theme', t), theme);
    const page = await ctx.newPage();
    const consoleErrors = [];
    let current = '';
    // 일부러 여는 404 페이지의 리소스 오류는 세지 않는다
    page.on('console', (m) => m.type() === 'error' && current !== 'notfound' && consoleErrors.push(`${current}: ${m.text().slice(0, 160)}`));
    for (const [name, path] of pages) {
      current = name;
      const res = await page.goto(base + path, { waitUntil: 'networkidle' });
      const status = res?.status() ?? 0;
      if (name !== 'notfound' && status !== 200) problems.push(`${theme}/${wName} ${path}: HTTP ${status}`);
      if (name === 'case-guard') {
        // 시나리오 하나를 실행해 결과 영역까지 캡처
        const btn = page.locator('.scenario').nth(1);
        if (await btn.count()) {
          await btn.click();
          await page.waitForSelector('.result[data-decision]', { timeout: 5000 }).catch(() => {
            problems.push(`${theme}/${wName} 시뮬레이터 결과 없음`);
          });
          await page.locator('#simulator').scrollIntoViewIfNeeded();
        } else {
          problems.push(`${theme}/${wName} 시나리오 버튼 없음(API 응답 실패?)`);
        }
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (overflow > 1) problems.push(`${theme}/${wName} ${path}: 가로 넘침 ${overflow}px`);
      // 마크다운 굵게가 안 풀린 자리(닫는 ** 앞이 문장부호이고 뒤에 한글이 붙으면 생긴다)
      const stars = await page.evaluate(() => {
        const m = document.querySelector('main')?.innerText.match(/.{0,20}\*\*.{0,20}/);
        return m ? m[0] : '';
      });
      if (stars) problems.push(`${theme}/${wName} ${path}: 굵게 표시 안 풀림 «${stars}»`);
      // 범위 표기 「9~12월 … 1~3월」의 물결표 두 개가 취소선으로 읽힌 자리(마크다운에선 \~ 로 쓴다)
      const struck = await page.evaluate(() => [...document.querySelectorAll('main del, main s')].map((e) => e.textContent).join(' | '));
      if (struck) problems.push(`${theme}/${wName} ${path}: 취소선으로 바뀐 글자 «${struck.slice(0, 60)}»`);
      await page.screenshot({ path: `${out}${theme}-${wName}-${name}.png`, fullPage: true });
    }
    if (consoleErrors.length) problems.push(`${theme}/${wName} 콘솔 오류: ${consoleErrors.slice(0, 3).join(' | ')}`);
    await ctx.close();
  }
}

await browser.close();
if (problems.length) {
  console.log('문제:\n- ' + problems.join('\n- '));
  process.exit(1);
}
console.log(`통과: ${pages.length}개 페이지 × ${widths.length}폭 × ${themes.length}톤, 캡처 ${out}`);
