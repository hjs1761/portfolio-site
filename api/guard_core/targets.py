"""쓰기 대상·diff 기록 추출 — 원본 훅의 fetch_pairs / write_targets / diff_records 이식.

정규식과 분기 순서는 원본과 같다. 바뀐 곳:
  · 마운트 판별 문자열 → MOUNT_MARK / MOUNT_HINT
  · 디렉토리 판정 os.path.isdir → fs.is_dir (가상 파일 시스템)
"""
from __future__ import annotations

import posixpath as _path
import re

from .parse import is_mount, norm, tokenize
from .vfs import MOUNT_HINT, MOUNT_MARK, VirtualFS

WRITE_VERB = re.compile(r"(?:^|[;&|]\s*|\s)(cp|mv|rsync|install|tee)\s", re.M)
DIFF_VERB = re.compile(r'(?:^|[;&|]\s*|\s)diff\s')


def fetch_pairs(cmd, cwd):
    """`cp <마운트> <로컬임시>` (강제 fetch) 를 찾아 임시본 → 원래 대상 매핑을 만든다.

    `cp 서버 /tmp/check.tmp && diff /tmp/check.tmp 로컬` 패턴을 지원하기 위함.
    이 매핑이 없으면 그 워크플로가 게이트에 걸려버린다.
    """
    out = []
    for line in cmd.split("\n"):
        for mv in WRITE_VERB.finditer(line):
            args = tokenize(line[mv.end():])
            if len(args) != 2:
                continue
            src, dst = norm(args[0], cwd), norm(args[1], cwd)
            if is_mount(src) and not is_mount(dst):
                out.append((dst, src))     # 임시본 → 마운트 원본
    return out


def write_targets(cmd, fs: VirtualFS, moved_away=None):
    """마운트를 '대상'으로 하는 쓰기만 골라낸다. (마운트→로컬 회수는 제외)

    moved_away: mv 로 서버에서 사라지는 소스 경로를 담아 돌려준다 (호출자가 백업).
    """
    targets = []
    if moved_away is None:
        moved_away = []
    for line in cmd.split("\n"):
        if not MOUNT_HINT.search(line):
            continue

        # 리다이렉트 ( > "마운트경로" ) — 소스 개념 없음
        for m in re.finditer(r'>>?\s*("([^"]+)"|\'([^\']+)\'|(\S+))', line):
            p = m.group(2) or m.group(3) or m.group(4) or ""
            if MOUNT_MARK in p:
                targets.append((p, None))

        # cp / mv / rsync / install / tee — 대상은 '마지막 인자'
        for mv in WRITE_VERB.finditer(line):
            verb = mv.group(1)
            seg = line[mv.end():]
            args = tokenize(seg)
            if verb == "tee" and len(args) >= 1:
                # tee 는 stdin 을 받으므로 대상이 유일한 인자일 수 있다 (소스 없음)
                for a in args:
                    if MOUNT_MARK in a:
                        targets.append((a, None))
                continue
            if len(args) < 2:
                continue
            dst, srcs = args[-1], args[:-1]
            if MOUNT_MARK not in dst:
                continue               # 대상이 마운트가 아님 → 회수 등, 게이트 없음
            if dst.endswith("/") or fs.is_dir(dst):
                for s in srcs:         # cp A B DIR/ → (DIR/A, A), (DIR/B, B)
                    targets.append((_path.join(dst.rstrip("/"), _path.basename(s)), s))
            else:
                targets.append((dst, srcs[-1]))
            # mv 는 소스를 지운다 → 소스가 마운트면 그쪽도 백업 대상 (서버 파일 이동/개명)
            if verb == "mv":
                for s in srcs:
                    if MOUNT_MARK in s:
                        moved_away.append(s)

    # 백업 디렉토리로 뜨는 cp 는 대상에서 제외 + 중복 제거
    out, seen = [], set()
    for t, s in targets:
        if "/.backups/" in t or t in seen:
            continue
        seen.add(t)
        out.append((t, s))
    return out


def diff_records(cmd, cwd, fetchmap):
    """diff 명령에서 (마운트 대상, [비교한 로컬 소스들]) 을 뽑는다.

    basename 이 아니라 **절대경로 쌍**으로 기록한다.
    basename 키잉은 '탐색용으로 다른 로컬 파일을 diff한 것'이
    '실제 배포'를 무단 승인하는 구멍을 만들었다 (2026-08-26 점검에서 실측).
    """
    recs = []
    for line in cmd.split("\n"):
        if not DIFF_VERB.search(line):
            continue
        mm = DIFF_VERB.search(line)
        args = [norm(a, cwd) for a in tokenize(line[mm.end():])]
        tgts, srcs = [], []
        for a in args:
            if is_mount(a):
                tgts.append(a)
            elif a in fetchmap:          # 강제 fetch 임시본 → 원래 마운트 대상
                tgts.append(fetchmap[a])
                srcs.append(a)
            else:
                srcs.append(a)
        for t in tgts:
            recs.append((t, [s for s in srcs if s != t]))
    return recs
