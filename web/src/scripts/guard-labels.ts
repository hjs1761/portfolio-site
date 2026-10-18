// 판정 API(kind) → 화면 문구. 시뮬레이터와 첫 화면 라이브 로그가 같이 쓴다.
export const KIND_LABEL: Record<string, string> = {
  pass: '통과',
  pass_backup: '통과 · 서버본 자동 백업',
  pass_fresh: '통과 · 서버에 없는 새 파일',
  pass_delete_backup: '통과 · 삭제 전 자동 백업',
  deny_no_diff: '차단 · 직전 diff 기록 없음',
  deny_mismatch: '차단 · diff한 파일과 올리는 파일이 다름',
  deny_inplace: '차단 · 운영 파일 제자리 편집',
  deny_recursive_delete: '차단 · 재귀 삭제',
  deny_unreachable_tcp: '차단 · 서버 접속 불가',
  deny_unreachable_mount: '차단 · 원격 드라이브 미연결',
  deny_direct_edit: '차단 · 편집 도구로 운영 파일 직접 수정',
};

// 짧은 판정 이유 (라이브 로그 한 줄용)
export const KIND_SHORT: Record<string, string> = {
  pass: 'diff 기록됨',
  pass_backup: '서버본 백업 후 반영',
  pass_fresh: '새 파일 · 덮어쓸 원본 없음',
  pass_delete_backup: '삭제 전 백업',
  deny_no_diff: '직전 diff 기록 없음',
  deny_mismatch: 'diff한 파일과 다름',
  deny_inplace: '운영 파일 제자리 편집',
  deny_recursive_delete: '재귀 삭제 — 백업 불가',
  deny_unreachable_tcp: '서버 접속 불가',
  deny_unreachable_mount: '원격 드라이브 미연결',
  deny_direct_edit: '편집 도구로 직접 수정',
};

export type Tool = 'Bash' | 'Edit' | 'Write';

export interface GuardState {
  diffs: Record<string, { ts: number; sources: string[] }>;
  fetch: Record<string, { ts: number; target: string }>;
}

export interface Decision {
  decision: 'allow' | 'deny';
  kind: string;
  title: string;
  message: string;
  events: { type: string; [key: string]: unknown }[];
  checks: { name: string; result: 'ok' | 'hit' | 'skip'; detail?: string }[];
  state: GuardState;
  now: number;
}

export type Step = { tool: Tool; command?: string; file_path?: string } | { advance_sec: number };

export interface Scenario {
  id: string;
  title: string;
  description: string;
  expect: string[];
  steps: Step[];
}

export interface ScenarioResponse {
  cwd: string;
  volumes: Record<string, boolean>;
  tree: { server: { path: string; volume: string }[]; local: string[] };
  scenarios: Scenario[];
}

export function emptyState(): GuardState {
  return { diffs: {}, fetch: {} };
}

export async function evaluateGuard(
  tool: Tool,
  text: string,
  state: GuardState,
  cwd: string,
  offset: number,
): Promise<Decision> {
  const payload: Record<string, unknown> = { tool, state, cwd, clock_offset_sec: offset };
  if (tool === 'Bash') payload.command = text;
  else payload.file_path = text;
  const res = await fetch('/api/guard/evaluate', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const msg =
      res.status === 422
        ? '입력이 너무 길거나 형식이 맞지 않습니다.'
        : res.status === 429
          ? '요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.'
          : `서버 오류 (${res.status})`;
    throw new Error(msg);
  }
  return (await res.json()) as Decision;
}
