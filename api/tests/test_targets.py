from guard_core.targets import fetch_pairs, write_targets, diff_records
from guard_core.vfs import VirtualFS
FS = VirtualFS.default()

def test_retrieve_is_not_a_write_target():
    assert write_targets("cp /mnt/prod/shop/fo/coupon.php /work/shop/fo/coupon.php", FS) == []

def test_cp_target_and_source():
    assert write_targets("cp fo/coupon.php /mnt/prod/shop/fo/coupon.php", FS) == [
        ("/mnt/prod/shop/fo/coupon.php", "fo/coupon.php")]

def test_cp_into_dir_expands_basenames():
    t = write_targets("cp a.php b.php /mnt/prod/shop/fo/", FS)
    assert ("/mnt/prod/shop/fo/a.php", "a.php") in t and ("/mnt/prod/shop/fo/b.php", "b.php") in t

def test_redirect_and_tee_have_no_source():
    assert write_targets('echo x > "/mnt/prod/shop/fo/coupon.php"', FS) == [("/mnt/prod/shop/fo/coupon.php", None)]
    assert write_targets("echo x | tee /mnt/prod/shop/fo/coupon.php", FS) == [("/mnt/prod/shop/fo/coupon.php", None)]

def test_mv_marks_server_source_moved_away():
    moved = []
    write_targets("mv /mnt/prod/shop/fo/coupon.php /mnt/prod/shop/fo/coupon_old.php", FS, moved)
    assert moved == ["/mnt/prod/shop/fo/coupon.php"]

def test_diff_records_absolute_pairs():
    recs = diff_records("diff fo/coupon.php /mnt/prod/shop/fo/coupon.php", "/work/shop", {})
    assert recs == [("/mnt/prod/shop/fo/coupon.php", ["/work/shop/fo/coupon.php"])]

def test_fetch_pair_maps_tmp_to_target():
    assert fetch_pairs("cp /mnt/prod/shop/fo/coupon.php /tmp/check.tmp", "/work/shop") == [
        ("/tmp/check.tmp", "/mnt/prod/shop/fo/coupon.php")]

def test_known_limit_only_first_diff_per_line_recorded():
    # 계획 원문은 따옴표 없이 `coupon.php; diff ...` 였다. 원본 tokenize 는 붙어 있는 `;` 를
    # 경로의 일부로 읽기 때문에 그 입력에서는 「첫 diff만」이 되지 않는다(아래 테스트).
    # 실제로 물린 형태(2026-10-06, 경로를 큰따옴표로 감싼 diff 여러 개)로 입력을 바로잡았다.
    recs = diff_records('diff a.php "/mnt/prod/shop/fo/coupon.php"; diff b.php "/mnt/prod/shop/fo/order_hook.php"',
                        "/work/shop", {})
    assert [t for t, _ in recs] == ["/mnt/prod/shop/fo/coupon.php"]   # 원본과 같은 한계


# --- 아래는 이식하며 덧붙인 것 ---

def test_known_limit_spaced_separator_also_first_only():
    recs = diff_records("diff a.php /mnt/prod/shop/fo/coupon.php && diff b.php /mnt/prod/shop/fo/order_hook.php",
                        "/work/shop", {})
    assert [t for t, _ in recs] == ["/mnt/prod/shop/fo/coupon.php"]


def test_original_quirk_attached_semicolon_kept_in_target():
    """따옴표 없이 `;` 를 붙이면 원본은 `coupon.php;` 라는 깨진 대상과 둘째 대상을 둘 다 기록하고,
    둘째 대상의 소스에 첫 diff 의 파일과 `diff` 라는 낱말까지 섞인다. (원본 동작 그대로 고정)"""
    recs = diff_records("diff a.php /mnt/prod/shop/fo/coupon.php; diff b.php /mnt/prod/shop/fo/order_hook.php",
                        "/work/shop", {})
    assert [t for t, _ in recs] == ["/mnt/prod/shop/fo/coupon.php;", "/mnt/prod/shop/fo/order_hook.php"]
    assert recs[1][1] == ["/work/shop/a.php", "/work/shop/diff", "/work/shop/b.php"]


def test_multiline_diffs_each_recorded():
    recs = diff_records("diff a.php /mnt/prod/shop/fo/coupon.php\ndiff b.php /mnt/prod/shop/fo/order_hook.php",
                        "/work/shop", {})
    assert [t for t, _ in recs] == ["/mnt/prod/shop/fo/coupon.php", "/mnt/prod/shop/fo/order_hook.php"]


def test_fetch_map_turns_tmp_into_target():
    recs = diff_records("diff /tmp/check.tmp fo/coupon.php", "/work/shop",
                        {"/tmp/check.tmp": "/mnt/prod/shop/fo/coupon.php"})
    assert recs == [("/mnt/prod/shop/fo/coupon.php", ["/tmp/check.tmp", "/work/shop/fo/coupon.php"])]


def test_cp_into_existing_dir_without_slash():
    assert write_targets("cp fo/coupon.php /mnt/prod/shop/upload", FS) == [
        ("/mnt/prod/shop/upload/coupon.php", "fo/coupon.php")]


def test_backup_dir_targets_are_skipped():
    assert write_targets("cp /mnt/prod/shop/fo/coupon.php /mnt/prod/shop/.backups/coupon.php", FS) == []


def test_lines_without_mount_hint_are_ignored():
    assert write_targets("cp a.php b.php", FS) == []
