// 첫 화면 라이브 판정 로그.
// 실제 판정 API 에 시나리오를 차례로 보내 결과를 한 줄씩 보여 준다. 화면 밖·숨은 탭에서는 멈추고,
// 움직임 줄이기 설정이면 타이핑 없이 몇 줄만 정지 상태로 보여 준다. 출력은 전부 textContent.
import {
  KIND_SHORT,
  emptyState,
  evaluateGuard,
  type GuardState,
  type ScenarioResponse,
  type Tool,
} from './guard-labels';

const MAX_LINES = 6;
const FALLBACK: [string, 'allow' | 'deny', string][] = [
  ['cp fo/coupon.php /mnt/prod/shop/fo/coupon.php', 'deny', '직전 diff 기록 없음'],
  ['diff fo/coupon.php /mnt/prod/shop/fo/coupon.php', 'allow', 'diff 기록됨'],
  ['cp fo/coupon.php /mnt/prod/shop/fo/coupon.php', 'allow', '서버본 백업 후 반영'],
  ["sed -i 's/old/new/' /mnt/prod/shop/fo/coupon.php", 'deny', '운영 파일 제자리 편집'],
];

const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms));

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

export function mountLiveLog(root: HTMLElement): void {
  const list = root.querySelector<HTMLOListElement>('[data-log-lines]');
  const status = root.querySelector<HTMLSpanElement>('[data-log-status]');
  if (!list || !status) return;

  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let visible = true;
  let waiters: (() => void)[] = [];

  const io = new IntersectionObserver((entries) => {
    visible = entries.some((e) => e.isIntersecting);
    if (visible && !document.hidden) wake();
  });
  io.observe(root);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && visible) wake();
  });

  function wake() {
    const w = waiters;
    waiters = [];
    w.forEach((f) => f());
  }

  // 보이는 동안만 진행한다
  async function gate() {
    if (visible && !document.hidden) return;
    await new Promise<void>((r) => waiters.push(r));
  }

  function setStatus(text: string, mode: 'live' | 'offline' | 'idle') {
    status!.textContent = text;
    status!.dataset.mode = mode;
  }

  function addLine(command: string): { cmd: HTMLSpanElement; li: HTMLLIElement } {
    const li = el('li', 'line');
    const prompt = el('span', 'prompt', '$');
    const cmd = el('span', 'cmd');
    li.append(prompt, cmd);
    list!.append(li);
    while (list!.children.length > MAX_LINES) list!.firstElementChild?.remove();
    if (reduced) cmd.textContent = command;
    return { cmd, li };
  }

  function addVerdict(li: HTMLLIElement, decision: 'allow' | 'deny', reason: string) {
    const v = el('span', `verdict ${decision}`);
    v.append(el('span', 'badge', decision === 'allow' ? '통과' : '차단'), el('span', 'reason', reason));
    li.append(v);
    li.classList.add('done');
  }

  async function type(target: HTMLSpanElement, text: string) {
    if (reduced) return;
    for (let i = 1; i <= text.length; i++) {
      await gate();
      target.textContent = text.slice(0, i);
      await sleep(text.charCodeAt(i - 1) === 32 ? 40 : 16 + Math.random() * 22);
    }
  }

  function showFallback() {
    setStatus('오프라인 예시', 'offline');
    list!.replaceChildren();
    for (const [cmd, decision, reason] of FALLBACK) {
      const { cmd: c, li } = addLine(cmd);
      c.textContent = cmd;
      addVerdict(li, decision, reason);
    }
  }

  async function run(data: ScenarioResponse) {
    // 시나리오를 섞지 않고 정해진 순서로 돈다 — 같은 화면을 다시 봐도 같은 흐름
    const scenarios = data.scenarios.filter((s) => s.steps.length <= 3);
    const cwd = data.cwd;
    let shown = 0;
    setStatus('실시간 판정', 'live');
    const intro = addLine('# 판정 API 연결됨 — 시나리오를 차례로 보냅니다');
    intro.cmd.textContent = '# 판정 API 연결됨 — 시나리오를 차례로 보냅니다';
    intro.li.classList.add('comment', 'done');
    for (;;) {
      for (const s of scenarios) {
        let state: GuardState = emptyState();
        let offset = 0;
        for (const step of s.steps) {
          if ('advance_sec' in step) {
            offset += step.advance_sec;
            const { cmd, li } = addLine(`# ${Math.round(step.advance_sec / 60)}분 뒤`);
            cmd.textContent = `# ${Math.round(step.advance_sec / 60)}분 뒤`;
            li.classList.add('comment', 'done');
            continue;
          }
          const tool = step.tool as Tool;
          const text = tool === 'Bash' ? (step.command ?? '') : `Edit ${step.file_path ?? ''}`;
          await gate();
          const { cmd, li } = addLine(text);
          await type(cmd, text);
          const d = await evaluateGuard(tool, tool === 'Bash' ? text : (step.file_path ?? ''), state, cwd, offset);
          state = d.state;
          addVerdict(li, d.decision, KIND_SHORT[d.kind] ?? d.kind);
          shown += 1;
          if (reduced && shown >= 4) {
            setStatus('판정 결과', 'idle');
            return;
          }
          await sleep(1300);
        }
        await sleep(1800);
      }
    }
  }

  fetch('/api/guard/scenario')
    .then((r) => {
      if (!r.ok) throw new Error(String(r.status));
      return r.json() as Promise<ScenarioResponse>;
    })
    .then((data) => run(data))
    .catch(() => showFallback());
}
