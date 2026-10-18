"""가상 파일 시스템 — 실제 훅이 디스크·마운트·네트워크에 묻던 것을 대신 답한다.

실제 훅은 `os.path.isfile` / `os.listdir` / `os.path.isdir` 와 TCP 연결 시도로
서버 상태를 확인한다. 여기서는 그 질문들을 고정된 데이터로 답한다.
셸을 실행하거나 실제 디스크를 읽는 일은 없다.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

# ---------- 경로 상수 (실제 훅의 마운트 루트를 가상 경로로 바꾼 것) ----------
MOUNT_ROOT = "/mnt/prod"                 # 운영 서버 마운트 루트
MOUNT_MARK = "/mnt/prod/"                # 원본의 「경로에 마운트 루트 표시가 들어 있나」 판별을 대신한다
MOUNT_HINT = re.compile(r"/mnt/prod")    # 마운트와 무관한 명령을 일찍 통과시키는 정규식
DEFAULT_CWD = "/work/shop"               # 원본 DEV_ROOT 자리 (cwd 가 없을 때의 기준)
VIRTUAL_HOME = "/work"                   # `~` 전개 결과 (실제 서버 계정의 홈을 드러내지 않는다)
BK_ROOT = "/backup/_mount"               # 자동 백업이 떨어지는 가상 위치

# ---------- 기본 시나리오 데이터 ----------
SERVER_FILES = {
    "/mnt/prod/shop/fo/coupon.php",
    "/mnt/prod/shop/fo/order_hook.php",
    "/mnt/prod/shop/skin/event/view.html",
    "/mnt/prod/legacy/fo/old_api.php",
}
SERVER_DIRS = {   # 디렉토리 → 내용(연결된 볼륨만 의미 있음)
    "/mnt/prod/shop": ["fo", "skin", "upload"],
    "/mnt/prod/shop/fo": ["coupon.php", "order_hook.php"],
    "/mnt/prod/shop/skin/event": ["view.html"],
    "/mnt/prod/shop/upload": [],          # 빈 디렉토리 — 신규 파일 허용(2026-09-17 수정 반영)
    "/mnt/prod/legacy/fo": ["old_api.php"],
}
VOLUMES = {"shop": True, "legacy": False}   # legacy = VPN 끊김 상황
LOCAL_FILES = {
    "/work/shop/fo/coupon.php", "/work/shop/fo/order_hook.php",
    "/work/shop/fo/new_feature.php", "/work/shop/skin/event/view.html",
    "/work/scratch/coupon.php",            # 같은 이름의 다른 파일(불일치 시나리오)
}


def volume_of(path):
    """대상 경로에서 마운트 볼륨명(.localized 제외)을 뽑는다. (원본 volume_of 이식)"""
    if not path.startswith(MOUNT_ROOT):
        return None
    rest = path[len(MOUNT_ROOT):].lstrip("/")
    vol = rest.split("/", 1)[0]
    return vol[:-len(".localized")] if vol.endswith(".localized") else vol


def _clean(p: str) -> str:
    p = posixpath.normpath(p or "")
    return "/" + p.lstrip("/") if p.startswith("//") else p


def _in_mount(p: str) -> bool:
    return p == MOUNT_ROOT or p.startswith(MOUNT_MARK)


def _index(files, dirs: dict[str, list[str]], root: str) -> dict[str, set[str]]:
    """파일·디렉토리 목록에서 「디렉토리 → 자식 이름」 색인을 만든다(중간 디렉토리 포함)."""
    idx: dict[str, set[str]] = {d: set(children) for d, children in dirs.items()}
    for p in list(files) + list(dirs):
        child, parent = p, posixpath.dirname(p)
        while child != root and (parent == root or parent.startswith(root.rstrip("/") + "/")):
            idx.setdefault(parent, set()).add(posixpath.basename(child))
            child, parent = parent, posixpath.dirname(parent)
    return idx


@dataclass
class VirtualFS:
    server_files: set[str] = field(default_factory=set)
    server_dirs: dict[str, list[str]] = field(default_factory=dict)
    volumes: dict[str, bool] = field(default_factory=dict)
    local_files: set[str] = field(default_factory=set)

    @classmethod
    def default(cls) -> "VirtualFS":
        return cls(
            server_files=set(SERVER_FILES),
            server_dirs={k: list(v) for k, v in SERVER_DIRS.items()},
            volumes=dict(VOLUMES),
            local_files=set(LOCAL_FILES),
        )

    # ---------- 원본이 실제 시스템에 묻던 질문들 ----------
    @staticmethod
    def volume_of(p: str) -> str | None:
        return volume_of(p)

    def volume_connected(self, vol: str) -> bool:
        return bool(self.volumes.get(vol, False))

    def _mount_visible(self, p: str) -> bool:
        """마운트 경로가 지금 보이는가. 끊긴 볼륨 아래는 아무것도 안 보인다."""
        vol = volume_of(p)
        return not vol or self.volume_connected(vol)

    def _dirs(self, p: str) -> dict[str, set[str]]:
        if _in_mount(p):
            idx = _index(self.server_files, self.server_dirs, MOUNT_ROOT)
            idx.setdefault(MOUNT_ROOT, set()).update(self.volumes)
            return idx
        return _index(self.local_files, {}, "/")

    def is_file(self, p: str) -> bool:
        p = _clean(p)
        if _in_mount(p):
            return self._mount_visible(p) and p in self.server_files
        return p in self.local_files

    def listdir(self, p: str) -> list[str] | None:
        """디렉토리 내용. 볼륨이 끊겼거나 디렉토리가 없으면 None (빈 디렉토리는 [])."""
        p = _clean(p)
        if _in_mount(p) and not self._mount_visible(p):
            return None
        idx = self._dirs(p)
        return sorted(idx[p]) if p in idx else None

    def is_dir(self, p: str) -> bool:
        return self.listdir(p) is not None

    # ---------- 화면용 ----------
    def tree(self) -> dict:
        return {
            "server": [{"path": p, "volume": volume_of(p)} for p in sorted(self.server_files)],
            "local": sorted(self.local_files),
        }
