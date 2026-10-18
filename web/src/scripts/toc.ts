// 목차의 현재 위치 표시.
// 고정 머리글 바로 아래 기준선을 지난 마지막 제목을 «지금 읽는 곳»으로 본다.
export function mountToc(nav: HTMLElement): void {
  // 링크와 제목을 쌍으로 묶는다 — 제목이 없는 링크를 걸러도 짝이 어긋나지 않게
  const pairs = [...nav.querySelectorAll<HTMLAnchorElement>('[data-toc-link]')]
    .map((link) => ({ link, target: document.getElementById(decodeURIComponent(link.hash.slice(1))) }))
    .filter((p): p is { link: HTMLAnchorElement; target: HTMLElement } => p.target !== null);
  if (!pairs.length) return;

  let ticking = false;

  // 기준선 = 화면 위쪽 1/3. 단 고정 머리글(--header-h) + 60px 보다 위로는 올리지 않는다.
  // 머리글 바로 밑을 기준으로 두면 첫 구획을 읽는 동안 아무 항목도 켜지지 않는다
  function baseline(): number {
    const h = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--header-h'));
    return Math.max((Number.isFinite(h) ? h : 60) + 60, window.innerHeight / 3);
  }

  function update(): void {
    ticking = false;
    const line = baseline();
    let current = -1;
    pairs.forEach(({ target }, i) => {
      if (target.getBoundingClientRect().top <= line) current = i;
    });
    // 끝까지 내렸으면 짧은 마지막 구획은 기준선에 닿지 못한다 → 화면 안의 마지막 제목을 현재로 본다
    const doc = document.documentElement;
    if (window.innerHeight + window.scrollY >= doc.scrollHeight - 2) {
      pairs.forEach(({ target }, i) => {
        if (target.getBoundingClientRect().top < window.innerHeight) current = Math.max(current, i);
      });
    }
    pairs.forEach(({ link }, i) => {
      if (i === current) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  }

  function onScroll(): void {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll, { passive: true });
  update();
}
