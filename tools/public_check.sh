#!/usr/bin/env bash
# 공개 원칙 검사: 빌드 결과(web/dist)에 들어가면 안 되는 문자열이 있는지 본다.
# 사용: tools/public_check.sh
#   PATTERNS_FILE=비공개/패턴.txt  — 개인 정보가 들어간 추가 패턴(한 줄에 「라벨<TAB>정규식」). 저장소에는 두지 않는다
#   NAMES_FILE=비공개/이름.txt     — 사람 이름 목록(한 줄에 하나)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/web/dist"
[ -d "$DIST" ] || { echo "web/dist 없음 — 먼저 빌드하세요"; exit 2; }

fail=0
check() {
  local label="$1" pattern="$2"
  local hits
  hits=$(grep -rIEno --include='*.html' --include='*.js' --include='*.css' --include='*.json' "$pattern" "$DIST" | head -5)
  if [ -n "$hits" ]; then
    echo "[실패] $label"
    echo "$hits" | sed 's/^/    /'
    fail=1
  else
    echo "[통과] $label"
  fi
}

# 누구에게나 해당하는 기본 검사
check "전화번호"     '01[016789][- ]?[0-9]{3,4}[- ]?[0-9]{4}'
check "사설 IP"      '\b(10\.[0-9]+|172\.(1[6-9]|2[0-9]|3[01])|192\.168|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7]))\.[0-9]+\.[0-9]+\b'
check "고객사 식별자" 'appkey|pinkey|mall_id|client_id'
check "토큰·키 형태"  'ntn_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'

# 개인 패턴(비공개 파일)
if [ -n "${PATTERNS_FILE:-}" ] && [ -f "$PATTERNS_FILE" ]; then
  while IFS=$'\t' read -r label pattern; do
    [ -z "${label:-}" ] || [ "${label:0:1}" = "#" ] || [ -z "${pattern:-}" ] && continue
    check "$label" "$pattern"
  done < "$PATTERNS_FILE"
else
  echo "[알림] PATTERNS_FILE 없음 — 기본 검사만 했습니다"
fi

if [ -n "${NAMES_FILE:-}" ] && [ -f "$NAMES_FILE" ]; then
  n=0
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    n=$((n + 1))
    check "사람 이름 #$n" "$name"
  done < "$NAMES_FILE"
fi

exit $fail
