"""판정 엔진 — 원본 훅 main() / guard_inplace_and_delete / guard_direct_edit 의 판정 순서 이식.

원본은 deny()/allow() 에서 sys.exit 로 끝난다. 여기서는 같은 자리에서 내부 예외(_Exit)를
던져 evaluate() 가 Decision 으로 돌려준다 — 「그 자리에서 끝나는」 흐름이 원본과 같다.
삭제 세그먼트를 만나면 그 자리에서 통과하는 원본 동작(뒤 명령 검사 생략)도 그대로다.

원본과 동작이 다른 곳 (이것뿐):
  · 신규 파일 판정의 빈 디렉토리 처리 — 이 맥북의 원본(08-27 판)은 `if not entries` 라 빈 디렉토리를
    미연결로 막지만, 2026-09-17 수정판(`if entries is None`)을 따른다. 빈 디렉토리 = 정상.
  · parse.expand_vars 의 전개 길이·변수 개수 상한(공개 서버 증폭 방어). 넘으면 전개하지 않은 명령으로 판정.

가상화한 것:
  · os.path.isfile / os.listdir / os.path.isdir → VirtualFS
  · time.time() → 인자 now
  · reachable() 의 TCP 프로브 → VirtualFS.volume_connected (프로브 캐시 없음)
  · 백업 파일 복사 → backup 이벤트, 로그 파일 기록 → 없음 (시뮬레이터에는 검사를 끄는 경로가 없다)
  · local_candidates 의 git ls-files → VirtualFS.local_files 검색
"""
from __future__ import annotations

import copy
import posixpath as _path
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal

from . import messages as msg
from .parse import expand_vars, is_mount, norm, parse_segments, volume_of
from .targets import DIFF_VERB, diff_records, fetch_pairs, write_targets
from .vfs import BK_ROOT, DEFAULT_CWD, MOUNT_HINT, MOUNT_ROOT, VirtualFS

DIFF_TTL = 30 * 60          # diff 유효시간 30분

# 제자리 편집 / 삭제 계열은 **세그먼트의 선두 명령어**로 판정한다.
INPLACE_CMDS = {"sed", "gsed", "perl", "ruby"}      # -i 플래그가 있을 때만
WIPE_CMDS    = {"truncate", "shred"}
DELETE_CMDS  = {"rm", "unlink", "rmdir"}
RECURSIVE_FLAG = re.compile(r"^-[a-zA-Z]*[rR]")

KST = timezone(timedelta(hours=9))   # 백업 파일 이름의 시각 (서버 시간대와 무관하게 고정)
FAIL_OPEN = True                     # 원본처럼 내부 오류는 통과. 시험에서는 끈다(conftest).

BASH_CHECKS = ("mount_involved", "diff_observed", "inplace_delete",
               "write_targets", "tcp_probe", "per_target")
EDIT_CHECKS = ("mount_involved", "direct_edit")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit")


@dataclass
class Decision:
    decision: Literal["allow", "deny"]
    kind: str            # pass / pass_backup / pass_fresh / pass_delete_backup / deny_*
    title: str           # 메시지 첫 줄
    message: str         # 훅이 출력하는 전체 문구
    events: list[dict] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    state: dict = field(default_factory=dict)


class _Exit(Exception):
    def __init__(self, decision, kind, message="", title=""):
        super().__init__(kind)
        self.decision, self.kind, self.message, self.title = decision, kind, message, title


class _Ctx:
    def __init__(self, fs: VirtualFS, now: float, st: dict):
        self.fs, self.now, self.st = fs, now, st
        self.events: list[dict] = []
        self.checks: list[dict] = []

    def check(self, name, result, detail=""):
        self.checks.append({"name": name, "result": result, "detail": detail})

    def event(self, type_, **kw):
        self.events.append({"type": type_, **kw})


def allow(kind="pass", message="", title=msg.TITLE_PASS_NO_WRITE):
    raise _Exit("allow", kind, message, title)


def deny(kind, reason):
    raise _Exit("deny", kind, reason, reason.split("\n", 1)[0])


def safe(fn, default):
    """원본은 마운트 무응답에 대비해 SIGALRM 타임아웃을 건다. 가상 FS 는 멈추지 않으므로 예외만 막는다."""
    try:
        return fn()
    except Exception:
        return default


def _age(sec):
    sec = int(max(0, sec))
    return f"{sec // 60}분 {sec % 60}초" if sec >= 60 else f"{sec}초"


# ---------- 상태 ----------
def load_state(raw):
    d = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    out = {"diffs": d.get("diffs"), "fetch": d.get("fetch")}
    for k in out:     # {대상: {"ts", "sources"}} / {임시본: {"ts", "target"}}
        if not isinstance(out[k], dict):
            out[k] = {}
    return out


def save_state(st, now):
    st["diffs"] = {k: v for k, v in st.get("diffs", {}).items()
                   if isinstance(v, dict) and now - v.get("ts", 0) < DIFF_TTL}
    st["fetch"] = {k: v for k, v in st.get("fetch", {}).items()
                   if isinstance(v, dict) and now - v.get("ts", 0) < DIFF_TTL}
    return st


# ---------- 제자리 편집·삭제 ----------
def guard_inplace_and_delete(cmd, cwd, ctx: _Ctx):
    """cp/mv 말고도 서버 파일을 바꾸는 경로들을 막는다.

    2026-08-26 우회 점검에서 sed -i / perl -i / rm / truncate / tee / dd 등
    8개 경로가 열려 있었다. sed -i·perl -i 는 상시 패턴이라 실질 구멍이었다.
    """
    for verb, flags, args, seg in parse_segments(cmd):
        mount_args = [a for a in args if is_mount(a)]

        # dd 는 of=<경로> 형태. 토크나이저는 of="공백 포함 경로" 를 공백에서 끊으므로
        # 세그먼트 원문에서 직접 뽑는다 (공백이 든 경로 대응).
        if verb == "dd":
            ofs = []
            for m in re.finditer(r'\bof=("([^"]*)"|\'([^\']*)\'|(\S+))', seg):
                p = m.group(2) or m.group(3) or m.group(4) or ""
                if is_mount(p):
                    ofs.append(p)
            if ofs:
                deny_inplace(ctx, ofs, "dd of=")
            continue

        if not mount_args:
            continue

        if verb in INPLACE_CMDS and any(re.match(r"^-[a-zA-Z]*i", f) for f in flags):
            deny_inplace(ctx, mount_args, f"{verb} -i (in-place)")

        if verb in WIPE_CMDS:
            deny_inplace(ctx, mount_args, verb)

        if verb in DELETE_CMDS:
            if any(RECURSIVE_FLAG.match(f) for f in flags):
                ctx.check("inplace_delete", "hit",
                          f"{verb} {' '.join(flags)} — 재귀 삭제는 백업할 수 없어 차단")
                deny("deny_recursive_delete", msg.deny_recursive_delete(mount_args))
            done = []
            for p in mount_args:
                t = norm(p, cwd)
                b = auto_backup(t, ctx)
                if b:
                    done.append(b)
                    ctx.event("delete_backup", target=t, backup=b)
            if done:
                ctx.check("inplace_delete", "hit",
                          f"{verb} 단일 삭제 — 서버 본 백업 후 그 자리에서 통과(뒤 명령은 검사하지 않음)")
                allow("pass_delete_backup", msg.note_delete_backup(done), msg.TITLE_PASS_DELETE_BACKUP)
            ctx.check("inplace_delete", "hit",
                      f"{verb} 단일 삭제 — 서버 파일로 보이지 않아 백업 없이 그 자리에서 통과")
            allow("pass", "", msg.TITLE_PASS_DELETE_NO_BACKUP)
    ctx.check("inplace_delete", "ok", "제자리 편집·덮어 지우기·삭제 없음")


def deny_inplace(ctx, mount_args, what):
    ctx.check("inplace_delete", "hit", f"{what} — 마운트 파일을 제자리에서 바꾸려 함")
    deny("deny_inplace", msg.deny_inplace(mount_args, what))


# ---------- 도달성 (TCP 프로브 대신 가상 연결 상태) ----------
def reachable(vol, fs: VirtualFS):
    """(ok, detail). 연결 정보가 없는 볼륨은 판정 불가 → 원본처럼 통과(fail-open)."""
    if vol not in fs.volumes:
        return True, "endpoint-unknown"
    ok = fs.volume_connected(vol)
    return ok, f"{vol} (가상 연결 상태: {'연결됨' if ok else '끊김'})"


# ---------- 백업 (실제 복사 대신 경로만 만든다) ----------
def auto_backup(target, ctx: _Ctx):
    if not safe(lambda: ctx.fs.is_file(target), False):
        return None  # 신규 파일 → 백업 대상 없음
    try:
        rel = target[len(MOUNT_ROOT):].lstrip("/") if target.startswith(MOUNT_ROOT) else _path.basename(target)
        stamp = datetime.fromtimestamp(ctx.now, KST).strftime("%Y-%m-%d_%H%M%S")
        return _path.join(BK_ROOT, rel + "." + stamp)
    except Exception:
        return None


# ---------- 마운트 직접 편집 ----------
VOL_ALIAS: dict[str, list[str]] = {}   # 원본: 볼륨명 → 로컬 폴더 별칭. 가상 FS 는 이름이 같아 비어 있다.


def local_candidates(target, fs: VirtualFS):
    """마운트 파일의 로컬 대응본 후보. 같은 basename + 볼륨 이름이 경로에 든 것만, 꼬리 일치순.

    볼륨이 일치하는 후보만 낸다. 같은 basename 의 '다른 곳' 파일을 후보로 주면
    엉뚱한 파일을 고치게 되므로, 확신이 없으면 빈 목록을 낸다.
    """
    base = _path.basename(target)
    vol = volume_of(target)
    if not base or not vol:
        return []
    keys = [vol] + VOL_ALIAS.get(vol, [])
    try:
        hits = sorted(p for p in fs.local_files if _path.basename(p) == base)
        hits = [h for h in hits if any(k and k in h for k in keys)]
        tail = target.replace("\\", "/").split("/")

        def score(h):
            hp = h.split("/")
            n = 0
            while n < min(len(hp), len(tail)) and hp[-1 - n] == tail[-1 - n]:
                n += 1
            return -n
        return sorted(hits, key=score)[:3]
    except Exception:
        return []


def guard_direct_edit(target, ctx: _Ctx):
    """Edit/Write/NotebookEdit 가 마운트를 직접 겨냥하면 차단한다.

    마운트 직접 편집은 (a) git·백업이 없어 복구 수단이 0이고
    (b) 편집 중 파일이 깨진 전례가 있으며
    (c) Bash 가드(diff·도달성·자동백업)를 전부 우회한다.
    """
    if not target or MOUNT_ROOT not in target:
        ctx.check("mount_involved", "ok", "편집 대상이 마운트 밖 → 통과")
        allow("pass", "", msg.TITLE_PASS_LOCAL_EDIT)
    ctx.check("mount_involved", "hit", f"편집 대상이 마운트 안: {target}")
    cands = local_candidates(target, ctx.fs)
    ctx.check("direct_edit", "hit",
              "편집 도구로 마운트 직접 수정 → 차단"
              + (f" (로컬 대응본 후보 {len(cands)}개)" if cands else " (로컬 대응본 후보 없음)"))
    deny("deny_direct_edit", msg.deny_direct_edit(target, cands))


# ---------- main ----------
def _main(ctx: _Ctx, tool, command, file_path, cwd):
    if tool in EDIT_TOOLS:
        guard_direct_edit(file_path or "", ctx)
    if tool != "Bash":
        ctx.check("mount_involved", "ok", f"{tool} 는 검사 대상 도구가 아님 → 통과")
        allow("pass", "", msg.TITLE_PASS_OTHER_TOOL)
    cmd = command or ""
    # 강제 fetch 패턴(`diff /tmp/check.tmp 로컬`)에는 마운트 경로가 없다 →
    # diff 명령이면 마운트 언급이 없어도 통과시키지 말고 기록 단계까지 진행한다.
    has_diff = bool(DIFF_VERB.search(cmd))
    has_mount = bool(MOUNT_HINT.search(cmd))
    if not cmd or (not has_mount and not has_diff):
        ctx.check("mount_involved", "ok", "마운트 경로도 diff 도 없음 → 바로 통과")
        allow("pass", "", msg.TITLE_PASS_UNRELATED)
    ctx.check("mount_involved", "hit",
              " · ".join(x for x, on in (("마운트 경로 언급", has_mount), ("diff 명령", has_diff)) if on))

    st = ctx.st
    now = ctx.now
    expanded = expand_vars(cmd)
    cwd = cwd or DEFAULT_CWD

    # 0) 강제 fetch (`cp 마운트 로컬임시`) 추적 → 임시본 diff 도 대상 diff 로 인정
    pairs = fetch_pairs(expanded, cwd)
    for tmp, mnt in pairs:
        st["fetch"][tmp] = {"ts": now, "target": mnt}
        ctx.event("fetch_tracked", tmp=tmp, target=mnt)

    fetchmap = {k: v["target"] for k, v in st.get("fetch", {}).items()
                if isinstance(v, dict) and v.get("target")}

    # 1) diff 관찰 → (대상, 소스들) 기록
    recs = diff_records(expanded, cwd, fetchmap)
    if recs:
        for t, srcs in recs:
            cur = st["diffs"].get(t) or {}
            merged = sorted(set((cur.get("sources") or []) + srcs))
            st["diffs"][t] = {"ts": now, "sources": merged}
            ctx.event("diff_recorded", target=t, sources=srcs)
    seen = [f"diff 기록: {t} ← {', '.join(s) or '(소스 없음)'}" for t, s in recs]
    seen += [f"회수 추적: {tmp} → {mnt}" for tmp, mnt in pairs]
    ctx.check("diff_observed", "hit" if seen else "ok", " / ".join(seen) or "diff·회수 없음")
    save_state(st, now)

    # 2) 마운트 쓰기 대상 판정
    # 제자리 편집(sed -i·perl -i 등) / 삭제 계열 — cp·mv 가드로는 안 잡히는 경로
    guard_inplace_and_delete(expanded, cwd, ctx)

    moved_away = []
    targets = write_targets(expanded, ctx.fs, moved_away)
    for s in moved_away:            # mv 로 서버에서 사라지는 원본을 먼저 백업
        t = norm(s, cwd)
        b = auto_backup(t, ctx)
        if b:
            ctx.event("mv_source_backup", target=t, backup=b)
    if not targets:
        ctx.check("write_targets", "ok", "마운트로 쓰는 대상 없음(읽기·회수·diff) → 통과")
        allow("pass", "", msg.TITLE_PASS_NO_WRITE)

    targets = [(norm(t, cwd), norm(s, cwd) if s else None) for t, s in targets]
    ctx.check("write_targets", "hit",
              " / ".join(f"{t} ← {s or '(소스 없음: 리다이렉트·tee)'}" for t, s in targets))
    gated, backed, fresh, unreachable, mismatched = [], [], [], [], []

    # 0) TCP 도달성 — 디렉토리 캐시가 살아있어도 실제 SFTP는 못 갈 수 있다.
    #    (원본은 집합을 돌아 순서가 정해져 있지 않다. 화면이 매번 같도록 처음 나온 순서로 돈다)
    vols = [v for v in dict.fromkeys(volume_of(t) for t, _ in targets) if v]
    probed = []
    for vol in vols:
        ok, detail = reachable(vol, ctx.fs)
        if not ok:
            save_state(st, now)
            ctx.check("tcp_probe", "hit", f"{detail} → 차단")
            deny("deny_unreachable_tcp", msg.deny_unreachable_tcp(vol, detail))
        probed.append(detail if detail != "endpoint-unknown" else f"{vol} (연결 정보 없음 → 판정 불가라 통과)")
    ctx.check("tcp_probe", "ok", " / ".join(probed) or "확인할 볼륨 없음")
    save_state(st, now)

    for t, src in targets:
        exists = safe(lambda: ctx.fs.is_file(t), False)
        if not exists:
            # 여기서 '없음'은 두 가지다: (a) 진짜 신규 파일 (b) 마운트 미연결
            # 부모 디렉토리가 응답해야만 (a)로 인정한다. 빈 디렉토리([])는 응답한 것이다
            # (2026-09-17 수정판: `if not entries` → `if entries is None`).
            parent = _path.dirname(t)
            entries = safe(lambda: ctx.fs.listdir(parent), None)
            if entries is None:
                unreachable.append(t)
                ctx.check("per_target", "hit", f"{t} — 서버에 없음 · 부모 디렉토리 응답 없음 → 차단")
                continue
            fresh.append(t)          # 진짜 신규 파일 → diff 불가, 통과
            ctx.event("fresh", target=t)
            ctx.check("per_target", "ok", f"{t} — 서버에 없음 · 부모 디렉토리 응답 → 신규 파일로 통과")
            continue

        rec = st.get("diffs", {}).get(t)
        if not (isinstance(rec, dict) and now - rec.get("ts", 0) < DIFF_TTL):
            gated.append(t)          # 이 대상에 대한 diff 기록 자체가 없음
            ctx.check("per_target", "hit", f"{t} — 서버 파일 있음 · 30분 안 diff 기록 없음 → 차단")
            continue
        srcs = rec.get("sources") or []
        age = _age(now - rec.get("ts", 0))
        if src and src not in srcs:
            mismatched.append((t, src, srcs))   # 다른 파일을 diff하고 이걸 밀어넣으려 함
            ctx.check("per_target", "hit",
                      f"{t} — 서버 파일 있음 · diff {age} 전 · 올릴 파일 {src} 이 diff 소스에 없음 → 차단")
            continue
        b = auto_backup(t, ctx)      # 대상+소스 모두 확인됨 → 백업하고 통과
        if b:
            backed.append((t, b))
            ctx.event("backup", target=t, backup=b)
        ctx.check("per_target", "ok",
                  f"{t} — 서버 파일 있음 · diff {age} 전 · 소스 {'일치' if src else '없음(리다이렉트)'} → 백업 후 통과")

    if mismatched:
        deny("deny_mismatch", msg.deny_mismatch(mismatched))
    if unreachable:
        deny("deny_unreachable_mount", msg.deny_unreachable_mount(unreachable))
    if gated:
        deny("deny_no_diff", msg.deny_no_diff(gated, targets, DIFF_TTL))

    if backed or fresh:
        kind = "pass_backup" if backed else "pass_fresh"
        allow(kind, msg.note_pass(backed, fresh),
              msg.TITLE_PASS_BACKUP if backed else msg.TITLE_PASS_FRESH)
    allow("pass", "", msg.TITLE_PASS_NO_WRITE)


def evaluate(tool: str, command: str | None, file_path: str | None,
             cwd: str | None, state: dict, now: float, fs: VirtualFS) -> Decision:
    """원본 훅 한 번 실행에 해당한다. 셸은 실행하지 않고 문자열만 분석한다."""
    ctx = _Ctx(fs, now, load_state(state))
    pipeline = BASH_CHECKS if tool == "Bash" else EDIT_CHECKS if tool in EDIT_TOOLS else ("mount_involved",)
    try:
        _main(ctx, tool, command, file_path, cwd)
        raise _Exit("allow", "pass", "", msg.TITLE_PASS_NO_WRITE)   # _main 은 늘 allow/deny 로 끝난다
    except _Exit as e:
        decision, kind, message, title = e.decision, e.kind, e.message, e.title
    except Exception as e:   # 원본: 내부 오류는 fail-open (훅 버그가 모든 명령을 막지 않도록)
        if not FAIL_OPEN:
            raise
        ctx.check("internal_error", "hit", type(e).__name__)
        decision, kind, message, title = "allow", "pass", "", msg.TITLE_FAIL_OPEN
    done = {c["name"] for c in ctx.checks}
    for name in pipeline:
        if name not in done:
            ctx.checks.append({"name": name, "result": "skip", "detail": "앞 단계에서 판정이 끝남"})
    return Decision(decision, kind, title, message, ctx.events, ctx.checks,
                    save_state(ctx.st, now))
