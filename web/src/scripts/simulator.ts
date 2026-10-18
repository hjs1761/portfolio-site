// 배포 가드 시뮬레이터 화면 로직.
// 서버(api/guard_core)는 상태를 저장하지 않는다. diff 기록 같은 세션 상태는 이 스크립트가 들고 다니며
// 요청마다 보내고, 응답에 담겨 온 갱신본으로 바꾼다. 모든 문자열은 textContent 로만 넣는다.

import {
  KIND_LABEL,
  emptyState,
  evaluateGuard,
  type Decision,
  type GuardState,
  type Scenario,
  type ScenarioResponse,
  type Tool,
} from './guard-labels';

interface HistoryItem {
  tool: Tool;
  input: string;
  kind: string;
  decision: 'allow' | 'deny';
  offset: number;
}

// 시나리오로 돌린 판정이면 결과 위에 시나리오 설명과 단계를 붙인다
interface ScenarioContext {
  scenario: Scenario;
  index: number;
  step: number;
  total: number;
}

const DIFF_TTL = 30 * 60;
const STORAGE_KEY = 'deploy-guard-sim';

const CHECK_LABEL: Record<string, string> = {
  mount_involved: '운영 경로가 들어 있나',
  diff_observed: 'diff 실행 기록',
  inplace_delete: '제자리 편집·삭제',
  write_targets: '운영 서버에 쓰는 대상',
  tcp_probe: '서버 접속 확인',
  per_target: '대상별 확인',
  direct_edit: '편집 도구 대상',
};

const EVENT_LABEL: Record<string, string> = {
  diff_recorded: 'diff 기록 저장',
  fetch_tracked: '서버 파일 회수 기록',
  backup: '서버본 자동 백업',
  fresh: '신규 파일로 판정',
  delete_backup: '삭제 전 백업',
  mv_source_backup: '이동 전 원본 백업',
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function formatRemain(sec: number): string {
  if (sec <= 0) return '만료';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}분 ${String(s).padStart(2, '0')}초 남음`;
}

function eventText(e: Decision['events'][number]): string {
  const label = EVENT_LABEL[e.type] ?? e.type;
  const parts = Object.entries(e)
    .filter(([k]) => k !== 'type')
    .map(([, v]) => (Array.isArray(v) ? v.join(', ') : String(v)));
  return parts.length ? `${label}: ${parts.join(' ← ')}` : label;
}

export function mountSimulator(root: HTMLElement): void {
  const q = <T extends HTMLElement>(sel: string) => {
    const found = root.querySelector<T>(sel);
    if (!found) throw new Error(`시뮬레이터 요소 없음: ${sel}`);
    return found;
  };

  const offlineBox = q<HTMLDivElement>('[data-sim-offline]');
  const body = q<HTMLDivElement>('[data-sim-body]');
  const scenarioList = q<HTMLOListElement>('[data-sim-scenarios]');
  const form = q<HTMLFormElement>('[data-sim-form]');
  const toolSelect = q<HTMLSelectElement>('[data-sim-tool]');
  const input = q<HTMLInputElement>('[data-sim-input]');
  const inputLabel = q<HTMLLabelElement>('[data-sim-input-label]');
  const result = q<HTMLDivElement>('[data-sim-result]');
  const diffList = q<HTMLUListElement>('[data-sim-diffs]');
  const clockText = q<HTMLSpanElement>('[data-sim-clock]');
  const advanceBtn = q<HTMLButtonElement>('[data-sim-advance]');
  const resetBtn = q<HTMLButtonElement>('[data-sim-reset]');
  const tree = q<HTMLDivElement>('[data-sim-tree]');
  const history = q<HTMLOListElement>('[data-sim-history]');
  const cwdText = q<HTMLSpanElement>('[data-sim-cwd]');

  let state: GuardState = emptyState();
  let offset = 0;
  let items: HistoryItem[] = [];
  let busy = false;
  // 서버 시각과 브라우저 시각의 차이(초). diff 남은 시간을 서버 기준으로 보여 주려고 쓴다
  let skew = 0;
  let cwd = '/work/shop';

  function save(): void {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ state, offset, items }));
    } catch {
      // 저장소를 못 써도 이번 화면에서는 동작한다
    }
  }

  function load(): void {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { state?: GuardState; offset?: number; items?: HistoryItem[] };
      if (saved.state?.diffs && saved.state.fetch) state = saved.state;
      if (typeof saved.offset === 'number') offset = saved.offset;
      if (Array.isArray(saved.items)) items = saved.items.slice(-12);
    } catch {
      state = emptyState();
    }
  }

  function renderClock(): void {
    clockText.textContent = offset === 0 ? '현재 시각' : `현재 + ${Math.round(offset / 60)}분`;
  }

  function renderDiffs(): void {
    diffList.replaceChildren();
    const entries = Object.entries(state.diffs);
    if (!entries.length) {
      diffList.append(el('li', 'empty', '아직 diff 기록이 없습니다.'));
      return;
    }
    const now = Date.now() / 1000 + skew + offset;
    for (const [target, rec] of entries) {
      const li = el('li', 'diff');
      li.append(el('code', 'target', target));
      li.append(el('span', 'sources', `비교한 로컬 파일: ${rec.sources.join(', ') || '(없음)'}`));
      li.append(el('span', 'remain mono', formatRemain(rec.ts + DIFF_TTL - now)));
      diffList.append(li);
    }
  }

  function renderHistory(): void {
    history.replaceChildren();
    if (!items.length) {
      history.append(el('li', 'empty', '실행한 명령이 여기에 쌓입니다.'));
      return;
    }
    for (const item of [...items].reverse()) {
      const li = el('li', `h-item ${item.decision}`);
      li.append(el('span', 'h-badge mono', item.decision === 'allow' ? '통과' : '차단'));
      li.append(el('code', 'h-input', item.tool === 'Bash' ? `$ ${item.input}` : `${item.tool} ${item.input}`));
      history.append(li);
    }
  }

  function renderResult(d: Decision, tool: Tool, text: string, ctx?: ScenarioContext): void {
    result.replaceChildren();
    result.dataset.decision = d.decision;

    if (ctx) {
      const box = el('div', 'r-scenario');
      const title = el('p', 'r-s-title');
      title.append(el('span', undefined, `${String(ctx.index + 1).padStart(2, '0')} · ${ctx.scenario.title}`));
      if (ctx.total > 1) title.append(el('span', 'r-s-step', `${ctx.total}단계 중 ${ctx.step}단계`));
      box.append(title, el('p', 'r-s-desc', ctx.scenario.description));
      result.append(box);
    }

    const head = el('div', 'r-head');
    head.append(el('span', `r-badge ${d.decision}`, d.decision === 'allow' ? '통과' : '차단'));
    head.append(el('span', 'r-kind', KIND_LABEL[d.kind] ?? d.kind));
    result.append(head);

    result.append(el('code', 'r-cmd', tool === 'Bash' ? `$ ${text}` : `${tool} → ${text}`));

    if (d.message) {
      const pre = el('pre', 'r-msg');
      pre.textContent = d.message;
      result.append(pre);
    }

    if (d.checks.length) {
      const h = el('p', 'r-sub', '판정 순서');
      const ol = el('ol', 'r-checks');
      // 차단이면 마지막으로 걸린 검사가 차단 사유다. 나머지 걸린 검사는 '해당 있음' 정도로만 표시
      const decisive = d.decision === 'deny' ? d.checks.map((c) => c.result).lastIndexOf('hit') : -1;
      d.checks.forEach((c, i) => {
        const li = el('li', `chk ${c.result}${i === decisive ? ' decisive' : ''}`);
        li.append(el('span', 'chk-name', CHECK_LABEL[c.name] ?? c.name));
        if (c.detail) li.append(el('span', 'chk-detail', c.detail));
        ol.append(li);
      });
      result.append(h, ol);
    }

    if (d.events.length) {
      const h = el('p', 'r-sub', '훅이 한 일');
      const ul = el('ul', 'r-events');
      for (const e of d.events) ul.append(el('li', undefined, eventText(e)));
      result.append(h, ul);
    }
  }

  function renderTree(data: ScenarioResponse): void {
    tree.replaceChildren();
    const server = el('div', 't-group');
    server.append(el('p', 't-title', '운영 서버 (원격 드라이브)'));
    const volumes = Object.entries(data.volumes);
    for (const [vol, connected] of volumes) {
      const v = el('div', 't-vol');
      const vh = el('p', 't-vol-head mono');
      vh.append(el('span', undefined, `/mnt/prod/${vol}`));
      vh.append(el('span', `t-conn ${connected ? 'on' : 'off'}`, connected ? '연결됨' : '연결 끊김'));
      v.append(vh);
      const ul = el('ul', 't-files mono');
      for (const f of data.tree.server.filter((s) => s.volume === vol)) {
        ul.append(el('li', undefined, f.path.replace(`/mnt/prod/${vol}/`, '')));
      }
      v.append(ul);
      server.append(v);
    }
    const local = el('div', 't-group');
    local.append(el('p', 't-title', '로컬 작업본 (/work)'));
    const ul = el('ul', 't-files mono');
    for (const f of data.tree.local) ul.append(el('li', undefined, f.replace(/^\/work\//, '')));
    local.append(ul);
    tree.append(server, local);
  }

  function setBusy(on: boolean): void {
    busy = on;
    root.toggleAttribute('data-busy', on);
    root.querySelectorAll<HTMLButtonElement>('button').forEach((b) => (b.disabled = on));
  }

  async function runOne(tool: Tool, text: string, ctx?: ScenarioContext): Promise<void> {
    const d = await evaluateGuard(tool, text, state, cwd, offset);
    skew = d.now - offset - Date.now() / 1000;
    state = d.state;
    items = [...items, { tool, input: text, kind: d.kind, decision: d.decision, offset }].slice(-12);
    renderResult(d, tool, text, ctx);
    renderDiffs();
    renderHistory();
    save();
  }

  function showError(message: string): void {
    result.replaceChildren();
    result.dataset.decision = 'error';
    result.append(el('p', 'r-error', message));
  }

  async function runScenario(s: Scenario, index: number, button: HTMLButtonElement): Promise<void> {
    if (busy) return;
    const total = s.steps.filter((step) => !('advance_sec' in step)).length;
    let stepNo = 0;
    state = emptyState();
    offset = 0;
    items = [];
    renderClock();
    setBusy(true);
    scenarioList.querySelectorAll('button').forEach((b) => b.removeAttribute('aria-pressed'));
    button.setAttribute('aria-pressed', 'true');
    try {
      for (const step of s.steps) {
        if ('advance_sec' in step) {
          offset += step.advance_sec;
          renderClock();
          renderDiffs();
          continue;
        }
        const text = step.tool === 'Bash' ? (step.command ?? '') : (step.file_path ?? '');
        toolSelect.value = step.tool;
        syncInputLabel();
        input.value = text;
        stepNo += 1;
        await runOne(step.tool, text, { scenario: s, index, step: stepNo, total });
      }
      result.focus();
    } catch (err) {
      // 중간에 실패하면 앞 단계의 diff 기록만 남아 이후 판정을 흐린다 → 비우고 알린다
      state = emptyState();
      offset = 0;
      renderClock();
      renderDiffs();
      save();
      showError(`${err instanceof Error ? err.message : '요청에 실패했습니다.'} 시나리오 상태를 비웠습니다.`);
    } finally {
      setBusy(false);
    }
  }

  function syncInputLabel(): void {
    const bash = toolSelect.value === 'Bash';
    inputLabel.textContent = bash ? '명령' : '편집할 파일 경로';
    input.placeholder = bash ? 'cp fo/coupon.php /mnt/prod/shop/fo/coupon.php' : '/mnt/prod/shop/fo/coupon.php';
  }

  function renderScenarios(list: Scenario[]): void {
    scenarioList.replaceChildren();
    list.forEach((s, i) => {
      const li = el('li');
      const b = el('button', 'scenario');
      b.type = 'button';
      // 설명은 목록에 두지 않고, 실행하면 판정 결과 위에 붙인다(좁은 칸에서 줄바꿈이 과해지지 않게)
      b.append(el('span', 's-num mono', String(i + 1).padStart(2, '0')));
      b.append(el('span', 's-title', s.title));
      const last = s.expect[s.expect.length - 1] ?? '';
      const expect = el('span', `s-expect mono ${last.startsWith('deny') ? 'deny' : 'allow'}`);
      expect.append(el('span', 'visually-hidden', '예상 결과 '), last.startsWith('deny') ? '차단' : '통과');
      b.append(expect);
      b.addEventListener('click', () => void runScenario(s, i, b));
      li.append(b);
      scenarioList.append(li);
    });
  }

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const text = input.value.trim();
    if (!text || busy) return;
    const tool = toolSelect.value as Tool;
    setBusy(true);
    runOne(tool, text)
      .catch((err: unknown) => showError(err instanceof Error ? err.message : '요청에 실패했습니다.'))
      .finally(() => setBusy(false));
  });

  toolSelect.addEventListener('change', syncInputLabel);

  advanceBtn.addEventListener('click', () => {
    offset = Math.min(offset + 31 * 60, 7200);
    renderClock();
    renderDiffs();
    save();
  });

  resetBtn.addEventListener('click', () => {
    state = emptyState();
    offset = 0;
    items = [];
    result.replaceChildren(el('p', 'r-empty', '시나리오를 고르거나 명령을 입력해 보세요.'));
    delete result.dataset.decision;
    scenarioList.querySelectorAll('button').forEach((b) => b.removeAttribute('aria-pressed'));
    renderClock();
    renderDiffs();
    renderHistory();
    save();
  });

  // 남은 시간 표시가 흐르도록 30초마다 다시 그린다
  window.setInterval(renderDiffs, 30_000);

  load();
  syncInputLabel();
  renderClock();
  renderDiffs();
  renderHistory();

  fetch('/api/guard/scenario')
    .then((res) => {
      if (!res.ok) throw new Error(String(res.status));
      return res.json() as Promise<ScenarioResponse>;
    })
    .then((data) => {
      cwd = data.cwd || cwd;
      cwdText.textContent = cwd;
      renderScenarios(data.scenarios);
      renderTree(data);
      body.hidden = false;
      offlineBox.hidden = true;
    })
    .catch(() => {
      body.hidden = true;
      offlineBox.hidden = false;
    });
}
