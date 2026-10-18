import pytest
from guard_core import evaluate, VirtualFS

FS = VirtualFS.default()
T0 = 1_800_000_000.0
CWD = "/work/shop"

def run(cmd, state=None, now=T0, tool="Bash", file_path=None):
    return evaluate(tool, cmd, file_path, CWD, state or {}, now, FS)

# --- 우회 경로 10종: 전부 막히거나(또는 백업 후 통과) 해야 한다
@pytest.mark.parametrize("cmd,kind", [
    ("sed -i 's/a/b/' /mnt/prod/shop/fo/coupon.php", "deny_inplace"),
    ("perl -pi -e 's/a/b/' /mnt/prod/shop/fo/coupon.php", "deny_inplace"),
    ("truncate -s 0 /mnt/prod/shop/fo/coupon.php", "deny_inplace"),
    ("shred /mnt/prod/shop/fo/coupon.php", "deny_inplace"),
    ('dd if=/dev/zero of="/mnt/prod/shop/fo/coupon.php" bs=1 count=1', "deny_inplace"),
    ("echo x | tee /mnt/prod/shop/fo/coupon.php", "deny_no_diff"),
    ("rm /mnt/prod/shop/fo/order_hook.php", "pass_delete_backup"),
    ("rm -r /mnt/prod/shop/skin/event", "deny_recursive_delete"),
    ("mv /mnt/prod/shop/fo/coupon.php /mnt/prod/shop/fo/coupon_old.php", "pass_fresh"),
    ('echo x > "/mnt/prod/shop/fo/coupon.php"', "deny_no_diff"),
])
def test_bypass_paths(cmd, kind):
    assert run(cmd).kind == kind

def test_mv_backs_up_server_source():
    d = run("mv /mnt/prod/shop/fo/coupon.php /mnt/prod/shop/fo/coupon_old.php")
    assert any(e["type"] == "mv_source_backup" for e in d.events)

# --- 정상 작업 회귀 9종: 막으면 안 된다
@pytest.mark.parametrize("cmd", [
    "sed -i 's/a/b/' fo/coupon.php",                               # 로컬 sed
    "perl -pi -e 's/a/b/' fo/coupon.php",                          # 로컬 perl
    "rm fo/new_feature.php",                                       # 로컬 rm
    "cat /mnt/prod/shop/fo/coupon.php",                            # 마운트 읽기
    "ls /mnt/prod/shop/fo",                                        # 마운트 목록
    "python3 -c 'import os; print(os.listdir(\"/mnt/prod/shop/fo\"))'",  # 읽기전용 스크립트
    "python3 - <<EOF\nprint('sed -i x /mnt/prod/shop/fo/coupon.php')\nEOF",  # heredoc 문자열
    "cp /mnt/prod/shop/fo/coupon.php /work/shop/fo/coupon.php",    # 회수
    "git status",                                                  # 무관
])
def test_normal_workflows_pass(cmd):
    d = run(cmd)
    assert d.decision == "allow" and d.kind == "pass"

# --- diff 쌍 게이트 5종
def test_cp_without_diff_denied():
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php").kind == "deny_no_diff"

def test_diff_then_cp_passes_with_backup():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    d = run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 60)
    assert d.kind == "pass_backup" and any(e["type"] == "backup" for e in d.events)

def test_diff_of_other_file_does_not_authorize():
    s = run("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php").state
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 60).kind == "deny_mismatch"

def test_diff_expires_after_30_minutes():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 1860).kind == "deny_no_diff"

def test_forced_fetch_diff_authorizes():
    s = run("cp /mnt/prod/shop/fo/coupon.php /tmp/check.tmp").state
    s = run("diff /tmp/check.tmp fo/coupon.php", s, T0 + 10).state
    assert run("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", s, T0 + 20).kind == "pass_backup"

# --- 연결·신규 파일
def test_new_file_passes():
    assert run("cp fo/new_feature.php /mnt/prod/shop/fo/new_feature.php").kind == "pass_fresh"

def test_new_file_in_empty_dir_passes():
    assert run("cp fo/new_feature.php /mnt/prod/shop/upload/new_feature.php").kind == "pass_fresh"

def test_unreachable_volume_denied():
    assert run("cp fo/coupon.php /mnt/prod/legacy/fo/old_api.php").kind == "deny_unreachable_tcp"

# --- Edit/Write 2종
def test_edit_tool_on_mount_denied():
    assert run(None, tool="Edit", file_path="/mnt/prod/shop/fo/coupon.php").kind == "deny_direct_edit"

def test_edit_tool_on_local_passes():
    assert run(None, tool="Write", file_path="/work/shop/fo/coupon.php").kind == "pass"

# --- 원본과 같은 알려진 한계 (고치지 않고 고정)
def test_known_limit_delete_short_circuits_rest_of_command():
    d = run("rm /mnt/prod/shop/fo/order_hook.php && cp fo/coupon.php /mnt/prod/shop/fo/coupon.php")
    assert d.kind == "pass_delete_backup"     # 뒤의 cp 가 diff 검사를 건너뛴다(실제 훅 동작)

def test_state_prunes_expired_entries():
    s = run("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php").state
    s2 = run("git status", s, T0 + 4000).state
    assert s2["diffs"] == {} or "/mnt/prod/shop/fo/coupon.php" not in s2["diffs"]
