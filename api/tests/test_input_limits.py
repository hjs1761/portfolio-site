"""공개 API 입력 상한 — 원본 훅은 로컬 전용이라 필요 없었던 방어.

API 는 명령을 2,000자까지 받는다. 그 안에서 만들 수 있는 최악 입력으로
변수 전개 증폭과 정규식 역추적 폭발이 없는지 잰다.
"""
import time
import tracemalloc

import pytest

from guard_core import evaluate
from guard_core.parse import (MAX_EXPANDED, MAX_VARS, expand_vars, extract_paths,
                              parse_segments, tokenize)
from guard_core.targets import diff_records, fetch_pairs, write_targets
from guard_core.vfs import VirtualFS

FS = VirtualFS.default()
LIMIT_SEC = 0.5
CMD_MAX = 2000


def amplifier():
    """변수가 앞 변수를 180번씩 참조하는 사슬. 제한이 없으면 2회차 치환에서 수천만 자가 된다."""
    lines = ['A="' + "x" * 400 + '"']
    for prev, name in zip("ABCD", "BCDE"):
        lines.append(f'{name}="' + f"${prev}" * 180 + '"')
    lines.append("cp a.php $E")
    cmd = "\n".join(lines)
    assert len(cmd) <= CMD_MAX
    return cmd


def test_expand_vars_amplification_returns_original_cmd_fast():
    cmd = amplifier()
    tracemalloc.start()
    t0 = time.perf_counter()
    out = expand_vars(cmd)
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert out == cmd                       # 반쯤 전개된 문자열이 아니라 원본 그대로
    assert elapsed < LIMIT_SEC
    assert peak < 2 * 1024 * 1024           # 상한(2만 자) 근처에서 멈춘다


def test_expand_vars_within_limit_still_expands():
    cmd = 'A="' + "x" * 100 + '"\nB="$A$A"\ncp a.php "/mnt/prod/shop/$B"'
    out = expand_vars(cmd)
    assert "/mnt/prod/shop/" + "x" * 200 in out and len(out) <= MAX_EXPANDED


def test_expand_vars_uses_first_max_vars_only():
    defs = [f"N{i}X=/mnt/prod/v{i}" for i in range(MAX_VARS + 10)]
    cmd = "\n".join(defs) + f"\ncp a.php $N0X $N{MAX_VARS - 1}X $N{MAX_VARS}X"
    out = expand_vars(cmd).split("\n")[-1]
    assert out == f"cp a.php /mnt/prod/v0 /mnt/prod/v{MAX_VARS - 1} $N{MAX_VARS}X"


def test_expand_vars_reassignment_still_last_wins():
    assert expand_vars("A=1\nA=2\necho $A").endswith("echo 2")


# --- 정규식 역추적: 2,000자 최악 입력 ---
ADVERSARIAL = {
    "newlines": "\n" * CMD_MAX,
    "spaces": " " * CMD_MAX,
    "newline_space": "\n " * (CMD_MAX // 2),
    "word_no_eq": "a" * CMD_MAX,
    "eq_chain": "a=" * (CMD_MAX // 2),
    "open_dquote": '"' + "a " * ((CMD_MAX - 1) // 2),
    "open_squote": "'" + "a " * ((CMD_MAX - 1) // 2),
    "quotes": "\"'" * (CMD_MAX // 2),
    "redirect_spaces": "/mnt/prod " + ">" + " " * (CMD_MAX - 11),
    "redirects": "/mnt/prod " + "> " * ((CMD_MAX - 10) // 2),
    "redirect_quotes": "/mnt/prod " + '>"' * ((CMD_MAX - 10) // 2),
    "redirect_dquote_open": "/mnt/prod >\"" + "a" * (CMD_MAX - 12),
    "seps_spaces": (";" + " " * 19) * (CMD_MAX // 20),
    "diff_words": " diff" * (CMD_MAX // 5),
    "diff_args": "diff " + "a " * ((CMD_MAX - 5) // 2),
    "cp_words": " cp" * (CMD_MAX // 3),
    "cp_mount_dir": "cp " + "a " * 989 + "/mnt/prod/shop/fo/",
    "long_flag": "rm -" + "a" * (CMD_MAX - 30) + " /mnt/prod/shop/x",
    "dd_of": "dd " + "of=" * ((CMD_MAX - 3) // 3),
    "dollar_vars": "A=1\n" + "$A" * ((CMD_MAX - 4) // 2),
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_no_regex_blowup_on_2000_chars(name):
    cmd = ADVERSARIAL[name]
    assert len(cmd) <= CMD_MAX
    fns = [
        lambda: expand_vars(cmd),
        lambda: extract_paths(cmd),
        lambda: tokenize(cmd),
        lambda: parse_segments(cmd),
        lambda: write_targets(cmd, FS, []),
        lambda: diff_records(cmd, "/work/shop", {}),
        lambda: fetch_pairs(cmd, "/work/shop"),
        lambda: evaluate("Bash", cmd, None, "/work/shop", {}, 1_800_000_000.0, FS),
    ]
    for fn in fns:
        t0 = time.perf_counter()
        fn()
        assert time.perf_counter() - t0 < LIMIT_SEC, name
