// 시뮬레이터 e2e: 시나리오를 전부 눌러 예상 판정과 실제 판정이 같은지, 결과 위에 시나리오 설명이 붙는지 확인한다.
// 사용: node tools/e2e.mjs  (BASE 로 주소 변경)
import { chromium } from 'playwright-core';
import { homedir } from 'node:os';

const base = process.env.BASE ?? 'http://127.0.0.1:8088';
const exe =
  process.env.CHROME ??
  `${homedir()}/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
const b = await chromium.launch({ executablePath: exe });
const p = await b.newPage();
const errors = [];
p.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 120)));
await p.goto(`${base}/projects/deploy-guard/`, { waitUntil: 'networkidle' });
const n = await p.locator('.scenario').count();
let ok = 0;
for (let i = 0; i < n; i++) {
  const btn = p.locator('.scenario').nth(i);
  const title = (await btn.locator('.s-title').textContent()).trim();
  const expect = (await btn.locator('.s-expect').textContent()).replace('예상 결과', '').trim();
  await btn.click();
  await p.waitForFunction(() => !document.querySelector('[data-simulator]').hasAttribute('data-busy'));
  await p.waitForTimeout(150);
  const got = (await p.locator('.result .r-badge').textContent())?.trim();
  const ctxTitle = (await p.locator('.result .r-s-title').textContent())?.trim();
  const pass = got === expect && ctxTitle?.includes(title);
  ok += pass ? 1 : 0;
  console.log(`${pass ? 'OK ' : 'BAD'} ${String(i + 1).padStart(2, '0')} ${title} → ${got}`);
}
await p.locator('[data-sim-input]').fill('cp fo/coupon.php /mnt/prod/shop/fo/coupon.php');
await p.locator('[data-sim-form] button[type=submit]').click();
// 고정 시간만 기다리면 응답이 느린 실제 주소에서 직전 시나리오 결과를 읽는다
await p.waitForFunction(() => !document.querySelector('[data-simulator]').hasAttribute('data-busy'));
await p.waitForTimeout(150);
const manualCtx = await p.locator('.result .r-scenario').count();
console.log(`직접 입력: ${(await p.locator('.result .r-kind').textContent())?.trim()} · 시나리오 설명 붙음 ${manualCtx}`);
await b.close();
const bad = n - ok + (manualCtx ? 1 : 0) + errors.length;
console.log(`시나리오 ${ok}/${n}, 콘솔 오류 ${errors.length}`, errors.slice(0, 2));
process.exit(bad ? 1 : 0);
