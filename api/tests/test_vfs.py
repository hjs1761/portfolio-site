from guard_core.vfs import VirtualFS

def test_default_scenario_files():
    fs = VirtualFS.default()
    assert fs.is_file("/mnt/prod/shop/fo/coupon.php")
    assert not fs.is_file("/mnt/prod/shop/fo/new_feature.php")
    assert fs.listdir("/mnt/prod/shop/fo") == ["coupon.php", "order_hook.php"]
    assert fs.listdir("/mnt/prod/shop/upload") == []          # 빈 디렉토리 ≠ 미연결
    assert fs.listdir("/mnt/prod/legacy/fo") is None          # 끊긴 볼륨
    assert not fs.is_file("/mnt/prod/legacy/fo/old_api.php")  # 끊기면 파일도 안 보임
    assert fs.volume_connected("shop") and not fs.volume_connected("legacy")
    assert fs.is_dir("/mnt/prod/shop/fo")


# --- 아래는 이식하며 덧붙인 것 ---

def test_intermediate_dirs_are_derived_from_files():
    """계획 데이터에 따로 적지 않은 중간 디렉토리도 실제 디렉토리처럼 보여야 한다."""
    fs = VirtualFS.default()
    assert fs.is_dir("/mnt/prod/shop/skin")
    assert fs.listdir("/mnt/prod/shop/skin") == ["event"]
    assert fs.listdir("/mnt/prod/shop") == ["fo", "skin", "upload"]


def test_missing_dir_and_unknown_volume():
    fs = VirtualFS.default()
    assert fs.listdir("/mnt/prod/shop/nope") is None
    assert not fs.is_dir("/mnt/prod/shop/fo/coupon.php")
    assert fs.listdir("/mnt/prod/other/fo") is None
    assert not fs.volume_connected("other")
    assert fs.volume_of("/mnt/prod/shop/fo/coupon.php") == "shop"
    assert fs.volume_of("/work/shop/fo/coupon.php") is None


def test_disconnected_volume_hides_dirs():
    fs = VirtualFS.default()
    assert not fs.is_dir("/mnt/prod/legacy/fo")


def test_local_files():
    fs = VirtualFS.default()
    assert fs.is_file("/work/shop/fo/coupon.php")
    assert not fs.is_file("/work/shop/fo/nothing.php")


def test_tree_shape():
    t = VirtualFS.default().tree()
    assert set(t) == {"server", "local"}
    paths = [e["path"] for e in t["server"]]
    assert paths == sorted(paths)
    assert {"path": "/mnt/prod/legacy/fo/old_api.php", "volume": "legacy"} in t["server"]
    assert t["local"] == sorted(t["local"]) and "/work/scratch/coupon.php" in t["local"]


def test_default_is_a_fresh_copy():
    a = VirtualFS.default()
    a.server_files.add("/mnt/prod/shop/fo/x.php")
    assert not VirtualFS.default().is_file("/mnt/prod/shop/fo/x.php")
