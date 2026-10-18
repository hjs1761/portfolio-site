"""차단·통과 문구 — 원본 훅이 출력하는 문장 구조를 그대로 두고 내부 정보만 일반화했다.

일반화한 것: 이모지 → [차단]/[주의] 텍스트 접두, 실제 경로·마운트 도구 이름 → 「마운트 도구」,
사내망 경유 안내 → 「VPN 연결」, 사고·시스템 이름 → 「전례」·「점검」, 내부 배포 명령 이름 → 절차 설명.
"""
from __future__ import annotations

import posixpath as _path

# ---------- 통과 제목 (원본은 통과 시 제목 없이 조용히 끝나거나 한 줄 알림만 낸다) ----------
TITLE_PASS_OTHER_TOOL = "통과 — 검사 대상 도구가 아님"
TITLE_PASS_UNRELATED = "통과 — 마운트와 무관한 명령"
TITLE_PASS_NO_WRITE = "통과 — 마운트로 쓰는 대상 없음(읽기·회수·diff)"
TITLE_PASS_LOCAL_EDIT = "통과 — 마운트 밖 파일 편집"
TITLE_PASS_BACKUP = "통과 — diff 확인됨, 서버 본 백업 후 덮어쓰기"
TITLE_PASS_FRESH = "통과 — 신규 파일(서버에 원본 없음)"
TITLE_PASS_DELETE_BACKUP = "통과 — 삭제 전 서버 본 백업"
TITLE_PASS_DELETE_NO_BACKUP = "통과 — 삭제 대상이 서버 파일로 보이지 않아 백업 없이 통과"
TITLE_FAIL_OPEN = "통과 — 훅 내부 오류(fail-open)"


# ---------- 차단 사유 7종 ----------
def deny_recursive_delete(mount_args):
    return "\n".join([
        "[차단] 마운트 재귀 삭제 차단.", "",
        "  대상: " + "\n        ".join(mount_args[:4]), "",
        "재귀 삭제는 자동 백업이 불가능해 복구 수단이 남지 않습니다.",
        "정말 필요하면 사용자에게 확인받고, 지울 파일을 하나씩 지정하세요",
        "(단일 파일 삭제는 훅이 자동 백업 후 통과시킵니다).",
    ])


def deny_inplace(mount_args, what):
    return "\n".join([
        "[차단] 마운트 제자리 편집 차단 — 로컬본을 고쳐서 cp 하세요.", "",
        "  대상: " + "\n        ".join(mount_args[:4]),
        f"  감지: {what}", "",
        "이유:",
        "  · 로컬 소스가 없어 diff 게이트가 성립하지 않습니다(무엇과 비교할지가 없음).",
        "  · 서버 본 자동 백업·라이브 검증도 함께 건너뛰게 됩니다.",
        "  · 마운트 제자리 쓰기는 fsync 실패로 파일이 깨진 전례가 있습니다.",
        "",
        "올바른 순서 (각각 별도 Bash 호출로):",
        "  1) cp \"<마운트 대상>\" \"<로컬 작업본>\"      ← 회수",
        "  2) 로컬 작업본 편집 (줄바꿈 보존 확인)",
        "  3) diff \"<로컬 작업본>\" \"<마운트 대상>\"",
        "  4) 보고·컨펌 후 cp",
    ])


def deny_direct_edit(target, cands):
    lines = ["[차단] 마운트 직접 편집 차단 — 로컬에서 편집하고 cp 하세요.", "",
             f"  대상: {target}", ""]
    if cands:
        lines.append("  로컬 대응본 후보:")
        for c in cands:
            lines.append(f"    {c}")
        lines.append("")
    else:
        lines += ["  로컬 대응본을 못 찾았습니다. 먼저 가져오세요:",
                  f'    cp "{target}" "<로컬 작업 폴더 안 적절한 경로>"', ""]
    lines += [
        "이유:",
        "  · 마운트는 git 추적이 안 되고 백업도 없어 깨지면 복구 수단이 0입니다.",
        "  · 마운트 Edit은 fsync 실패로 파일이 깨진 전례가 있습니다.",
        "  · Edit으로 마운트를 건드리면 cp 가드(diff·도달성 확인·서버본 자동 백업)를",
        "    전부 우회합니다.",
        "",
        "올바른 순서: 로컬본 편집 → diff → 보고·컨펌 → cp → 라이브 검증",
    ]
    return "\n".join(lines)


def deny_unreachable_tcp(vol, detail):
    return "\n".join([
        f"[차단] 운영 반영 차단 — SFTP 서버에 TCP 도달 불가 ({vol})", "",
        f"  프로브 실패: {detail}",
        "",
        "마운트 디렉토리는 로컬 캐시라 보일 수 있지만 실제 서버엔 못 갑니다.",
        "이 상태로 cp 하면 업로드 큐에만 쌓였다가 나중에 남의 작업을 덮어씁니다.",
        "",
        "확인할 것: 회사망인지 / VPN 연결이 필요한지 /",
        "           네트워크 전환 직후면 stale 세션 정리 후 마운트 도구 재실행",
        "",
        "사용자에게 보고하고 연결을 기다리세요.",
    ])


def deny_mismatch(mismatched):
    lines = ["[차단] 운영 반영 차단 — diff한 파일과 지금 올리려는 파일이 다릅니다.", ""]
    for t, src, srcs in mismatched:
        lines.append(f"  대상:      {t}")
        lines.append(f"  올릴 파일: {src}")
        lines.append(f"  diff한 것: {', '.join(srcs) if srcs else '(없음)'}")
        lines.append(f"  실행할 것: diff \"{src}\" \"{t}\"")
        lines.append("")
    lines += [
        "이유: 탐색용으로 다른 로컬 파일을 diff한 기록이 실제 배포를 승인해버리는 구멍을 막습니다.",
        "      (2026-08-26 점검에서 실제로 통과한 사례가 있었습니다)",
        "",
        "지금 올릴 그 파일로 diff를 다시 실행하고 결과를 사용자에게 보고한 뒤 재시도하세요.",
    ]
    return "\n".join(lines)


def deny_unreachable_mount(unreachable):
    lines = ["[차단] 운영 반영 차단 — 마운트에 도달할 수 없습니다.", ""]
    for t in unreachable:
        lines.append(f"  대상: {t}")
        lines.append(f"  부모 디렉토리가 없거나 응답하지 않음: {_path.dirname(t)}")
    lines += [
        "",
        "이 상태로 cp 하면 로컬 캐시에만 쓰이고 '성공한 것처럼' 보입니다.",
        "이후 네트워크 복귀 시 큐가 흘러들어가 다른 작업자의 변경을 덮어쓸 수 있습니다.",
        "",
        "확인할 것:",
        "  1) 마운트 도구에서 해당 볼륨이 연결(Connect) 상태인지",
        "  2) 집·타 네트워크라면 VPN 연결이 필요한지",
        "  3) 네트워크 전환 직후라면 stale TCP 세션 → 세션 정리 후 마운트 도구 재실행",
        "",
        "사용자에게 상황을 보고하고 연결을 기다리세요.",
    ]
    return "\n".join(lines)


def deny_no_diff(gated, targets, ttl):
    lines = ["[차단] 운영 반영 차단 — cp 직전 diff 기록이 없습니다.", ""]
    for t in gated:
        src = next((s for tt, s in targets if tt == t and s), None)
        lines.append(f"  대상: {t}")
        lines.append(f"  실행할 것: diff \"{src or '<올릴 로컬 파일>'}\" \"{t}\"")
    lines += [
        "",
        "이유: 마운트 캐시가 stale하거나 다른 작업자가 서버를 먼저 고쳤을 수 있습니다.",
        "      diff 없이 cp 하면 그 변경이 조용히 날아갑니다.",
        f"      (유효시간 {ttl // 60}분. 「대상 절대경로 + 올릴 소스 파일」 쌍으로 기록됩니다.)",
        "",
        "[주의] 회수(마운트→로컬)와 배포(cp)를 한 Bash 호출에 묶지 마세요.",
        "  훅은 호출 '전체'를 차단하므로 회수까지 같이 무효가 됩니다. 별도 호출로 나누세요.",
        "",
        "diff를 실행하고 결과를 사용자에게 보고한 뒤 다시 시도하세요.",
        "서버 본 백업은 통과 시 훅이 자동으로 뜹니다.",
    ]
    return "\n".join(lines)


# ---------- 통과 알림 ----------
def note_delete_backup(done):
    return "[mount_guard] 삭제 전 백업됨: " + " / ".join(done)


def note_pass(backed, fresh):
    msg = [f"백업됨: {b}" for _, b in backed]
    msg += [f"신규 파일(서버에 원본 없음): {t}" for t in fresh]
    return "[mount_guard] " + " / ".join(msg)
