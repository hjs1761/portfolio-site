"""명령 분해 — 원본 훅의 명령 파싱 함수를 그대로 옮긴 것.

함수 이름·정규식·분기 순서는 원본과 같다. 바뀐 곳은 두 군데뿐이다.
  · 마운트 판별 문자열: 원본의 마운트 루트 표시 → MOUNT_MARK ("/mnt/prod/")
  · `~` 전개: 실제 프로세스의 홈 대신 가상 홈(VIRTUAL_HOME)으로만 푼다
"""
from __future__ import annotations

import posixpath as _path
import re

from .vfs import DEFAULT_CWD, MOUNT_MARK, MOUNT_ROOT, VIRTUAL_HOME, volume_of

__all__ = ["expand_vars", "extract_paths", "tokenize", "parse_segments",
           "norm", "is_mount", "volume_of"]


# ---------- 명령 파싱 ----------
MAX_EXPANDED = 20_000   # 전개 결과 길이 상한(자)
MAX_VARS = 50           # 전개에 쓰는 변수 개수 상한(먼저 정의된 것부터)


def expand_vars(cmd):
    """같은 명령 블록에서 정의된 셸 변수를 실제 값으로 치환 (MP="/mnt/prod/..." 패턴).

    원본과 다른 점(이 함수에서 유일한 차이, 공개 API 방어):
      · 변수가 변수를 여러 번 참조하면 3회 반복 치환에서 길이가 기하급수로 커진다
        (2,000자 입력으로 수십억 자). 치환 결과가 MAX_EXPANDED 를 넘게 되는 순간 — 실제로
        만들기 전에 길이를 계산해 — 중단하고, 반쯤 전개된 문자열이 아니라 **원본 cmd 를
        그대로** 돌려준다. 판정은 전개하지 않은 명령으로 이어진다.
      · 변수는 먼저 정의된 MAX_VARS 개 이름만 쓴다(같은 이름 재대입은 원본처럼 마지막 값).
    """
    env = {}
    for m in re.finditer(r'(?m)^\s*(\w+)=("([^"]*)"|\'([^\']*)\'|(\S+))', cmd):
        if m.group(1) not in env and len(env) >= MAX_VARS:
            continue
        env[m.group(1)] = m.group(3) or m.group(4) or m.group(5) or ""
    out = cmd
    for _ in range(3):  # 변수가 변수를 참조하는 경우 대비
        for k, v in env.items():
            for token in ("${%s}" % k, "$" + k):     # 원본의 .replace 두 번과 같은 순서
                n = out.count(token)
                if not n:
                    continue
                if len(out) + n * (len(v) - len(token)) > MAX_EXPANDED:
                    return cmd
                out = out.replace(token, v)
    return out


def extract_paths(text):
    """따옴표 문자열 + 비따옴표 토큰에서 마운트 경로를 뽑는다. (원본에서도 판정에 쓰이지 않는다)"""
    found = []
    for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'|(\S+)', text):
        tok = m.group(1) or m.group(2) or m.group(3) or ""
        if MOUNT_ROOT in tok or MOUNT_MARK in tok:
            found.append(tok.rstrip(";&|"))
    return found


def tokenize(seg):
    """따옴표를 존중해 인자 목록으로 쪼갠다. 플래그(-r 등)와 리다이렉트 이후는 제외."""
    args = []
    for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'|(\S+)', seg):
        tok = m.group(1) if m.group(1) is not None else (
              m.group(2) if m.group(2) is not None else m.group(3))
        if tok is None:
            continue
        if tok in (";", "&&", "||", "|"):
            break                      # 다음 명령 시작 → 여기까지가 이 cp의 인자
        if tok.startswith(("&&", "||", ";", "|", ">", "<")):
            break
        if tok.startswith("-"):
            continue                   # 플래그
        args.append(tok)
    return args


def parse_segments(cmd):
    """명령을 세그먼트로 쪼개고 (선두 명령어, 플래그들, 인자들) 로 분해한다.

    선두 명령어 기준이라, heredoc·문자열 안에 들어있는 '명령처럼 보이는 텍스트'는
    잡지 않는다 (오탐 제거). 인자는 tokenize 가 따옴표를 지키므로 공백 포함 경로도 안전.
    """
    out = []
    for seg in re.split(r"\n|;|&&|\|\||\|", cmd):
        seg = seg.strip()
        if not seg:
            continue
        toks = []
        for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'|(\S+)', seg):
            t = m.group(1) if m.group(1) is not None else (
                m.group(2) if m.group(2) is not None else m.group(3))
            if t is not None:
                toks.append(t)
        if not toks:
            continue
        i = 0
        while i < len(toks) and re.match(r"^\w+=", toks[i]):
            i += 1                                  # 선행 환경변수 대입 건너뛰기
        if i >= len(toks):
            continue
        verb = _path.basename(toks[i])
        rest = toks[i + 1:]
        flags = [t for t in rest if t.startswith("-")]
        args = [t for t in rest if not t.startswith("-")]
        out.append((verb, flags, args, seg))
    return out


def _expanduser(p):
    """os.path.expanduser 대신. `~`·`~/…` 만 가상 홈으로 풀고, `~user` 는 건드리지 않는다."""
    if p == "~" or p.startswith("~/"):
        return VIRTUAL_HOME + p[1:]
    return p


def norm(p, cwd=None):
    """상대경로를 Bash cwd 기준 절대경로로. 마운트 I/O 없이 문자열만 정규화."""
    if not p:
        return p
    p = _expanduser(p)
    if not _path.isabs(p):
        p = _path.join(cwd or DEFAULT_CWD, p)
    return _path.normpath(p)


def is_mount(p):
    return bool(p) and MOUNT_MARK in p
