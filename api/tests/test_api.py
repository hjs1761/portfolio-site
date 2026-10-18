from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)

def test_health():
    assert c.get("/api/health").json() == {"ok": True}

def test_scenario_lists_ten_and_tree():
    j = c.get("/api/guard/scenario").json()
    assert len(j["scenarios"]) == 10 and "tree" in j and j["volumes"]["legacy"] is False

def test_evaluate_round_trip_state():
    r1 = c.post("/api/guard/evaluate", json={"tool": "Bash",
          "command": "diff fo/coupon.php /mnt/prod/shop/fo/coupon.php", "state": {}}).json()
    r2 = c.post("/api/guard/evaluate", json={"tool": "Bash",
          "command": "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", "state": r1["state"]}).json()
    assert r2["kind"] == "pass_backup"

def test_clock_offset_expires_diff():
    r1 = c.post("/api/guard/evaluate", json={"tool": "Bash",
          "command": "diff fo/coupon.php /mnt/prod/shop/fo/coupon.php", "state": {}}).json()
    r2 = c.post("/api/guard/evaluate", json={"tool": "Bash", "clock_offset_sec": 1860,
          "command": "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", "state": r1["state"]}).json()
    assert r2["kind"] == "deny_no_diff"

def test_rejects_oversized_command():
    r = c.post("/api/guard/evaluate", json={"tool": "Bash", "command": "x" * 2001, "state": {}})
    assert r.status_code == 422

def test_rejects_unknown_tool_and_oversized_state():
    assert c.post("/api/guard/evaluate", json={"tool": "Rm", "command": "ls", "state": {}}).status_code == 422
    big = {"diffs": {f"/mnt/prod/shop/f{i}": {"ts": 1.0, "sources": []} for i in range(51)}, "fetch": {}}
    assert c.post("/api/guard/evaluate", json={"tool": "Bash", "command": "ls", "state": big}).status_code == 422

def test_never_executes_shell(tmp_path, monkeypatch):
    import subprocess, os
    def boom(*a, **k): raise AssertionError("shell executed")
    monkeypatch.setattr(subprocess, "run", boom); monkeypatch.setattr(os, "system", boom)
    c.post("/api/guard/evaluate", json={"tool": "Bash", "command": "rm -rf /", "state": {}})


# --- 아래는 이식하며 덧붙인 것 ---
import json  # noqa: E402
import time  # noqa: E402

import pytest  # noqa: E402

KINDS = {"pass", "pass_backup", "pass_fresh", "pass_delete_backup", "deny_no_diff", "deny_mismatch",
         "deny_inplace", "deny_recursive_delete", "deny_unreachable_tcp", "deny_unreachable_mount",
         "deny_direct_edit"}


def test_scenario_response_shape():
    """웹 시뮬레이터가 읽는 형식 (메인 세션 요청으로 고정)."""
    j = c.get("/api/guard/scenario").json()
    assert set(j) == {"cwd", "volumes", "tree", "scenarios"}
    assert j["cwd"] == "/work/shop"
    assert j["volumes"] == {"shop": True, "legacy": False}
    assert set(j["tree"]) == {"server", "local"}
    server = j["tree"]["server"]
    assert server and all(set(e) == {"path", "volume"} for e in server)
    assert [e["path"] for e in server] == sorted(e["path"] for e in server)
    assert {"path": "/mnt/prod/shop/fo/coupon.php", "volume": "shop"} in server
    local = j["tree"]["local"]
    assert local == sorted(local) and all(isinstance(p, str) for p in local)
    for s in j["scenarios"]:
        assert set(s) == {"id", "title", "description", "expect", "steps"}
        runs = [st for st in s["steps"] if "tool" in st]
        assert len(s["expect"]) == len(runs) and set(s["expect"]) <= KINDS
        for st in s["steps"]:
            if "advance_sec" in st:
                assert set(st) == {"advance_sec"} and isinstance(st["advance_sec"], int)
            elif st["tool"] == "Bash":
                assert set(st) == {"tool", "command"}
            else:
                assert st["tool"] == "Edit" and set(st) == {"tool", "file_path"}
    assert [s["id"] for s in j["scenarios"]] == [
        "cp-without-diff", "diff-then-cp", "diff-other-file", "sed-in-place", "rm-recursive",
        "rm-single", "new-file", "unreachable", "edit-tool", "expired-diff"]


def test_evaluate_response_shape():
    j = c.post("/api/guard/evaluate", json={"tool": "Bash",
               "command": "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", "state": {}}).json()
    assert set(j) == {"decision", "kind", "title", "message", "events", "checks", "state", "now"}
    assert j["decision"] in {"allow", "deny"} and j["kind"] in KINDS
    assert isinstance(j["now"], float) and set(j["state"]) == {"diffs", "fetch"}
    assert j["checks"] and all(set(ch) == {"name", "result", "detail"} for ch in j["checks"])
    assert all(ch["result"] in {"ok", "hit", "skip"} for ch in j["checks"])
    assert all("type" in e for e in j["events"])


def run_scenario(s):
    state, offset, kinds = {}, 0, []
    for st in s["steps"]:
        if "advance_sec" in st:
            offset += st["advance_sec"]
            continue
        body = {**st, "state": state, "clock_offset_sec": offset}
        r = c.post("/api/guard/evaluate", json=body)
        assert r.status_code == 200, r.text
        state = r.json()["state"]
        kinds.append(r.json()["kind"])
    return kinds


def test_all_scenarios_hit_expected_kinds_via_api():
    for s in c.get("/api/guard/scenario").json()["scenarios"]:
        assert run_scenario(s) == s["expect"], s["id"]


def test_amplification_input_answers_fast():
    lines = ['A="' + "x" * 400 + '"'] + [f'{n}="' + f"${p}" * 180 + '"' for p, n in zip("ABCD", "BCDE")]
    cmd = "\n".join(lines + ["cp a.php $E"])
    assert len(cmd) <= 2000
    t0 = time.perf_counter()
    r = c.post("/api/guard/evaluate", json={"tool": "Bash", "command": cmd, "state": {}})
    assert r.status_code == 200 and time.perf_counter() - t0 < 0.5


def test_returned_state_always_fits_next_request():
    """한 명령으로 상한(대상 50개·소스 10개)을 넘는 기록을 만들어도 돌려준 상태는 다음 요청에 들어가야 한다."""
    srcs = " ".join(f"s{i}" for i in range(15))
    tgts = " ".join(f"/mnt/prod/shop/t{i}" for i in range(60))
    r = c.post("/api/guard/evaluate", json={"tool": "Bash", "command": f"diff {srcs} {tgts}", "state": {}})
    st = r.json()["state"]
    assert len(st["diffs"]) == 50 and all(len(v["sources"]) <= 10 for v in st["diffs"].values())
    r2 = c.post("/api/guard/evaluate", json={"tool": "Bash", "command": "ls", "state": st})
    assert r2.status_code == 200


WORST = {
    "many_sources_many_targets":
        "diff " + " ".join(f"a{i}" for i in range(150)) + " " + " ".join(f"/mnt/prod/{i}" for i in range(80)),
    "long_sources":
        "diff " + " ".join(f"{i}" + "s" * 140 for i in range(10)) + " " + " ".join(f"/mnt/prod/{i}" for i in range(40)),
    "cp_many_into_dir": "cp " + " ".join(f"a{i}" for i in range(400)) + " /mnt/prod/shop/fo/",
    "rm_many": "rm " + " ".join(f"/mnt/prod/shop/x{i}" for i in range(90)),
}


@pytest.mark.parametrize("name", sorted(WORST))
def test_worst_case_response_stays_small(name):
    cmd = WORST[name]
    assert len(cmd) <= 2000
    r = c.post("/api/guard/evaluate", json={"tool": "Bash", "command": cmd, "state": {}})
    j = r.json()
    assert r.status_code == 200 and len(r.content) < 150_000, len(r.content)
    assert len(j["events"]) <= 50 and len(j["checks"]) <= 60 and len(j["message"]) <= 6100
    assert all(len(e.get("sources", [])) <= 10 for e in j["events"])
    # 돌려받은 상태를 그대로 실어 보낸 다음 요청이 앞단 본문 상한(32KB) 안에 들어가야 한다
    nxt = json.dumps({"tool": "Bash", "command": "x" * 2000, "state": j["state"]}, ensure_ascii=False)
    assert len(nxt.encode()) < 32 * 1024
    assert c.post("/api/guard/evaluate", content=nxt,
                  headers={"content-type": "application/json"}).status_code == 200


def test_clamp_marks_what_was_cut():
    j = c.post("/api/guard/evaluate", json={"tool": "Bash", "state": {},
               "command": WORST["cp_many_into_dir"]}).json()
    assert j["kind"] == "pass_fresh"                      # 판정은 그대로
    assert j["message"].endswith("… (이하 생략)")
    assert j["checks"][-1]["detail"].endswith("건 생략)")
    j = c.post("/api/guard/evaluate", json={"tool": "Bash", "state": {},
               "command": WORST["many_sources_many_targets"]}).json()
    assert j["events"][0]["omitted"] == 140


@pytest.mark.parametrize("body", [
    {"tool": "Bash", "command": "ls", "state": {}, "clock_offset_sec": 7201},
    {"tool": "Bash", "command": "ls", "state": {}, "clock_offset_sec": -1},
    {"tool": "Edit", "file_path": "x" * 301, "state": {}},
    {"tool": "Bash", "command": "ls", "cwd": "x" * 301, "state": {}},
    {"tool": "Bash", "command": "ls", "state": {"diffs": {"x" * 301: {"ts": 1.0, "sources": []}}}},
    {"tool": "Bash", "command": "ls", "state": {"diffs": {"/a": {"ts": 1.0, "sources": ["s"] * 11}}}},
    {"tool": "Bash", "command": "ls", "state": {"fetch": {f"/t{i}": {"ts": 1.0, "target": "/m"} for i in range(51)}}},
])
def test_rejects_out_of_range_inputs(body):
    assert c.post("/api/guard/evaluate", json=body).status_code == 422


def test_no_docs_pages():
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404
