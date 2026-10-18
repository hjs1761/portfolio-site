"""미리 만든 시나리오 10개.

단계 형식 (웹 시뮬레이터가 그대로 읽는다):
  {"tool": "Bash", "command": "..."}       명령 하나 판정
  {"tool": "Edit", "file_path": "..."}     편집 도구 판정
  {"advance_sec": 1860}                    가상 시각을 앞으로 (판정 없음)
expect 는 판정 단계마다의 기대 kind (advance 단계는 빠진다).
시나리오마다 빈 상태·시각 이동 0 에서 시작한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CP = "cp fo/coupon.php /mnt/prod/shop/fo/coupon.php"
DIFF = "diff fo/coupon.php /mnt/prod/shop/fo/coupon.php"


@dataclass
class Scenario:
    id: str
    title: str
    description: str
    expect: list[str]
    steps: list[dict] = field(default_factory=list)


def bash(command: str) -> dict:
    return {"tool": "Bash", "command": command}


SCENARIOS: list[Scenario] = [
    Scenario("cp-without-diff", "diff 없이 운영 파일 덮어쓰기",
             "서버 파일과 비교하지 않고 바로 덮어씁니다. 그사이 다른 사람이 서버를 고쳤다면 "
             "그 변경이 조용히 사라지므로 막습니다.",
             ["deny_no_diff"], [bash(CP)]),
    Scenario("diff-then-cp", "diff로 확인한 뒤 덮어쓰기",
             "올릴 파일로 diff를 먼저 하면 「대상 + 소스」 쌍이 기록됩니다. 30분 안의 cp는 "
             "서버 본을 백업한 뒤 통과합니다.",
             ["pass", "pass_backup"], [bash(DIFF), bash(CP)]),
    Scenario("diff-other-file", "다른 파일을 diff하고 덮어쓰기",
             "이름이 같은 다른 로컬 파일로 diff를 해 두고 실제로는 작업본을 올립니다. "
             "기록이 파일 이름이 아니라 절대경로 쌍이라 승인되지 않습니다.",
             ["pass", "deny_mismatch"],
             [bash("diff /work/scratch/coupon.php /mnt/prod/shop/fo/coupon.php"), bash(CP)]),
    Scenario("sed-in-place", "운영 파일을 제자리에서 고치기",
             "sed -i 로 서버 파일을 직접 고치면 비교할 로컬 소스가 없어 diff 확인이 성립하지 않습니다. "
             "로컬본을 고쳐서 올리라고 안내합니다.",
             ["deny_inplace"], [bash("sed -i 's/old/new/' /mnt/prod/shop/fo/coupon.php")]),
    Scenario("rm-recursive", "운영 디렉토리 통째로 지우기",
             "재귀 삭제는 지우기 전에 백업을 뜰 수 없어 복구 수단이 남지 않으므로 막습니다.",
             ["deny_recursive_delete"], [bash("rm -rf /mnt/prod/shop/skin/event")]),
    Scenario("rm-single", "운영 파일 하나 지우기",
             "파일 하나를 지울 때는 서버 본을 먼저 백업하고 통과시킵니다.",
             ["pass_delete_backup"], [bash("rm /mnt/prod/shop/fo/order_hook.php")]),
    Scenario("new-file", "서버에 없는 새 파일 올리기",
             "덮어쓸 원본이 없으니 diff할 대상도 없습니다. 부모 폴더가 응답하면 신규 파일로 보고 통과합니다.",
             ["pass_fresh"], [bash("cp fo/new_feature.php /mnt/prod/shop/fo/new_feature.php")]),
    Scenario("unreachable", "연결이 끊긴 서버에 올리기",
             "원격 드라이브 폴더는 보여도 실제 서버에 닿지 않으면, 올린 파일이 대기열에 쌓였다가 나중에 "
             "남의 작업을 덮어쓸 수 있어 막습니다.",
             ["deny_unreachable_tcp"], [bash("cp fo/coupon.php /mnt/prod/legacy/fo/old_api.php")]),
    Scenario("edit-tool", "편집 도구로 운영 파일 직접 고치기",
             "편집 도구로 서버 파일을 직접 고치면 diff·연결 확인·백업을 모두 건너뜁니다. "
             "로컬 대응본을 알려 주고 막습니다.",
             ["deny_direct_edit"], [{"tool": "Edit", "file_path": "/mnt/prod/shop/fo/coupon.php"}]),
    Scenario("expired-diff", "diff하고 31분 뒤에 덮어쓰기",
             "diff 기록은 30분만 유효합니다. 그사이 서버가 바뀌었을 수 있으니 다시 diff하라고 막습니다.",
             ["pass", "deny_no_diff"], [bash(DIFF), {"advance_sec": 1860}, bash(CP)]),
]
