"""엔진 — 계획 표 밖에서 덧붙인 시험 (검사 순서·이벤트·메시지·상태·공개 원칙)."""
import copy
import pathlib
import re

import pytest

import guard_core.engine as engine
from guard_core import DIFF_TTL, VirtualFS, evaluate

FS = VirtualFS.default()
T0 = 1_800_000_000.0
CWD = "/work/shop"
ALL_KINDS = {"pass", "pass_backup", "pass_fresh", "pass_delete_backup", "deny_no_diff",
             "deny_mismatch", "deny_inplace", "deny_recursive_delete", "deny_unreachable_tcp",
             "deny_unreachable_mount", "deny_direct_edit"}


def run(cmd, state=None, now=T0, tool="Bash", file_path=None, cwd=CWD):
    return evaluate(tool, cmd, file_path, cwd, state or {}, now, FS)


def names(d):
    return [(c["name"], c["result"]) for c in d.checks]


# --- 검사 순서 ---
def test_unrelated_command_checks_then_skips():
    assert names(run("git status")) == [
        ("mount_involved", "ok"), ("diff_observed", "skip"), ("inplace_delete", "skip"),
        ("write_targets", "skip"), ("tcp_probe", "skip"), ("per_target", "skip")]


def test_no_diff_check_sequence():
    assert names(run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php")) == [
        ("mount_involved", "hit"), ("diff_observed", "ok"), ("inplace_delete", "ok"),
        ("write_targets", "hit"), ("tcp_probe", "ok"), ("per_target", "hit")]


def test_inplace_stops_at_inplace_check():
    assert names(run("sed -i 's/a/b/' /mnt/prod/shop/fo/coupon.php"))[2:] == [
        ("inplace_delete", "hit"), ("write_targets", "skip"), ("tcp_probe", "skip"), ("per_target", "skip")]


def test_tcp_stops_before_per_target():
    d = run("cp fo/coupon.php /mnt/prod/legacy/fo/old_api.php")
    assert names(d)[-2:] == [("tcp_probe", "hit"), ("per_target", "skip")]
    assert "legacy" in d.title


def test_edit_check_sequence_and_candidates():
    d = run(None, tool="Edit", file_path="/mnt/prod/shop/fo/coupon.php")
    assert names(d) == [("mount_involved", "hit"), ("direct_edit", "hit")]
    assert "/work/shop/fo/coupon.php" in d.message
    assert "/work/scratch/coupon.php" not in d.message      # 볼륨이 다른 같은 이름 파일은 후보가 아니다


def test_edit_without_local_candidate():
    d = run(None, tool="Edit", file_path="/mnt/prod/shop/skin/event/none.html")
    assert d.kind == "deny_direct_edit" and "로컬 대응본을 못 찾았습니다" in d.message


def test_every_check_has_known_result():
    for cmd in ["git status", "diff fo/coupon.php /mnt/prod/shop/fo/coupon.php",
                "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", "rm /mnt/prod/shop/fo/order_hook.php"]:
        for c in run(cmd).checks:
            assert set(c) == {"name", "result", "detail"} and c["result"] in {"ok", "hit", "skip"}


# --- 결과·이벤트 ---
def test_backup_path_uses_kst_stamp():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    d = run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 60)
    (ev,) = [e for e in d.events if e["type"] == "backup"]
    assert ev == {"type": "backup", "target": "/mnt/prod/shop/fo/coupon.php",
                  "backup": "/backup/_mount/shop/fo/coupon.php.2027-01-15_170100"}
    assert d.message == "[mount_guard] 백업됨: " + ev["backup"]
    assert d.title.startswith("통과")


def test_diff_and_fetch_events():
    d = run("cp /mnt/prod/shop/fo/coupon.php /tmp/check.tmp")
    assert d.events == [{"type": "fetch_tracked", "tmp": "/tmp/check.tmp",
                         "target": "/mnt/prod/shop/fo/coupon.php"}]
    d = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php")
    assert d.events == [{"type": "diff_recorded", "target": "/mnt/prod/shop/fo/coupon.php",
                         "sources": ["/work/shop/fo/coupon.php"]}]
    assert d.state["diffs"]["/mnt/prod/shop/fo/coupon.php"] == {"ts": T0, "sources": ["/work/shop/fo/coupon.php"]}


def test_fresh_and_delete_events():
    d = run("cp fo/new_feature.php /mnt/prod/shop/fo/new_feature.php")
    assert d.events == [{"type": "fresh", "target": "/mnt/prod/shop/fo/new_feature.php"}]
    d = run("rm /mnt/prod/shop/fo/order_hook.php")
    assert [e["type"] for e in d.events] == ["delete_backup"]
    assert d.message.startswith("[mount_guard] 삭제 전 백업됨: /backup/_mount/shop/fo/order_hook.php.")


@pytest.mark.parametrize("cmd", [
    "cp fo/new_feature.php /mnt/prod/shop/nope/new_feature.php",   # 없는 디렉토리
    "cp fo/new_feature.php /mnt/prod/other/fo/new_feature.php",    # 연결 정보 없는 볼륨(TCP 판정 불가 → 통과 → 디렉토리 확인)
])
def test_unreachable_mount(cmd):
    d = run(cmd)
    assert d.kind == "deny_unreachable_mount" and "부모 디렉토리" in d.message


def test_deny_precedence_mismatch_before_no_diff():
    s = run("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php").state
    d = run("cp fo/coupon.php fo/order_hook.php /mnt/prod/shop/fo/", s, T0 + 5)
    assert d.kind == "deny_mismatch"


def test_mixed_backup_and_fresh_is_pass_backup():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    d = run("cp fo/coupon.php fo/new_feature.php /mnt/prod/shop/fo/", s, T0 + 5)
    assert d.kind == "pass_backup" and {e["type"] for e in d.events} == {"backup", "fresh"}


def test_variable_paths_are_expanded():
    s = run('MP="/mnt/prod/shop/fo"\ndiff fo/coupon.php "$MP/coupon.php"').state
    assert run('MP="/mnt/prod/shop/fo"\ncp fo/coupon.php "$MP/coupon.php"', s, T0 + 5).kind == "pass_backup"


def test_retrieve_then_deploy_in_one_call_is_denied_whole():
    d = run("cp /mnt/prod/shop/fo/coupon.php fo/coupon.php && cp fo/order_hook.php /mnt/prod/shop/fo/order_hook.php")
    assert d.kind == "deny_no_diff" and "회수(마운트→로컬)와 배포(cp)를 한 Bash 호출에 묶지 마세요" in d.message


# --- 상태 ---
def test_input_state_is_not_mutated():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    before = copy.deepcopy(s)
    run("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 5)
    assert s == before


def test_sources_merge_across_diffs():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    s = run("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 5).state
    assert s["diffs"]["/mnt/prod/shop/fo/coupon.php"]["sources"] == [
        "/work/scratch/coupon.php", "/work/shop/fo/coupon.php"]
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 10).kind == "pass_backup"


def test_ttl_boundary():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + DIFF_TTL - 1).kind == "pass_backup"
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + DIFF_TTL).kind == "deny_no_diff"


def test_malformed_state_is_tolerated():
    d = run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", {"diffs": [], "fetch": "x", "probes": {}})
    assert d.kind == "deny_no_diff" and d.state == {"diffs": {}, "fetch": {}}


def test_state_shape_always_two_keys():
    for cmd, tool, fp in [("git status", "Bash", None), (None, "Edit", "/mnt/prod/shop/fo/coupon.php"),
                          ("rm -r /mnt/prod/shop/skin/event", "Bash", None)]:
        assert set(run(cmd, tool=tool, file_path=fp).state) == {"diffs", "fetch"}


# --- fail-open (원본처럼 내부 오류는 통과) ---
def test_fail_open_on_internal_error(monkeypatch):
    monkeypatch.setattr(engine, "FAIL_OPEN", True)

    def boom(_):
        raise RuntimeError("x")
    monkeypatch.setattr(engine, "expand_vars", boom)
    d = run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php")
    assert d.decision == "allow" and d.kind == "pass" and "fail-open" in d.title
    assert ("internal_error", "hit") in names(d)


# --- 공개 원칙: 메시지·코드에 내부 정보가 없어야 한다 ---
FORBIDDEN = re.compile(r"/Users/|Volumes\.noindex|Mountain ?Duck|/deploy\b|\.21[02]\b|WireGuard|"
                       r"메디킨|라보|app\.weaver|아모레|네오팜|hwangjunseok|[\U0001F300-\U0001FAFF⚠]")

SAMPLES = [
    ("Bash", "sed -i 's/a/b/' /mnt/prod/shop/fo/coupon.php", None),
    ("Bash", "rm -r /mnt/prod/shop/skin/event", None),
    ("Bash", "rm /mnt/prod/shop/fo/order_hook.php", None),
    ("Bash", "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", None),
    ("Bash", "cp fo/coupon.php /mnt/prod/legacy/fo/old_api.php", None),
    ("Bash", "cp fo/new_feature.php /mnt/prod/shop/nope/x.php", None),
    ("Bash", "cp fo/new_feature.php /mnt/prod/shop/fo/new_feature.php", None),
    ("Edit", None, "/mnt/prod/shop/fo/coupon.php"),
    ("Edit", None, "/mnt/prod/shop/fo/none.php"),
]


def test_messages_have_no_internal_info():
    other = run("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php").state
    same = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    outs = [run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", other, T0 + 5),
            run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", same, T0 + 5)]
    outs += [run(cmd, tool=tool, file_path=fp) for tool, cmd, fp in SAMPLES]
    assert {d.kind for d in outs} == ALL_KINDS - {"pass"}
    for d in outs:
        text = d.title + "\n" + d.message + repr(d.events) + repr(d.checks)
        assert not FORBIDDEN.search(text), (d.kind, FORBIDDEN.search(text))
        if d.decision == "deny":
            assert d.title.startswith("[차단]")


def test_source_files_have_no_internal_info():
    root = pathlib.Path(__file__).resolve().parents[1]
    for p in list((root / "guard_core").glob("*.py")) + list((root / "app").glob("*.py")):
        m = FORBIDDEN.search(p.read_text(encoding="utf-8"))
        assert not m, (p.name, m)
