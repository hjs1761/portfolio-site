# portfolio-site

황준석 포트폴리오·이력서 사이트 — **https://hwangjunseok.dev**

글은 Astro 정적 페이지이고, 「배포 가드 시뮬레이터」만 작은 FastAPI로 판정합니다.
운영은 Docker Compose로 띄우고 Cloudflare Tunnel 뒤에 둡니다(공인 포트를 열지 않음).

## 구성

```
web/      Astro — 홈·프로젝트 8개·이력서·글, 시뮬레이터 화면
api/      FastAPI + guard_core — 실제 배포 가드 훅의 판정 규칙을 가상 파일 시스템 위로 옮긴 것
deploy/   docker-compose.yml · nginx.conf(보안 헤더·CSP·요청 제한) · Dockerfile 2개
tools/    shots.mjs · clip.mjs · e2e.mjs · public_check.sh
```

## 로컬 실행

### 한 번에 (Docker)

```bash
docker compose -f deploy/docker-compose.yml up -d --build
open http://127.0.0.1:8088
```

### 개발 모드

```bash
# API
cd api && uv sync && uv run uvicorn app.main:app --port 8000 --reload
# 웹 (다른 터미널) — /api 는 8000 으로 넘어간다
cd web && npm install && npm run dev
```

## 검증

```bash
cd api && uv run pytest -q                  # 판정 코어 충실도 + API
cd web && npx astro check && npm run build  # 타입·빌드
node tools/shots.mjs                        # 전 페이지 × 데스크톱·모바일 × 어두운·밝은 톤: 가로 넘침·콘솔 오류·마크다운 깨짐
node tools/e2e.mjs                          # 시뮬레이터 시나리오 전부 예상 판정과 대조
tools/public_check.sh                       # 빌드 결과 공개 원칙 검사
```

`public_check.sh` 는 누구에게나 해당하는 기본 검사(전화번호·사설 IP·식별자·토큰 형태)만 저장소에 둡니다.
개인 정보가 들어간 패턴과 사람 이름 목록은 저장소 밖 비공개 파일로 넘깁니다 — `PATTERNS_FILE`, `NAMES_FILE`.

## 콘텐츠를 고칠 때

- 프로젝트: `web/src/content/projects/*.md` — 프런트매터 `source` 에 근거 출처를 남긴다(화면에는 안 나옴).
- 이력서: `web/src/content/resume/resume.md` — 비공개 원본을 공개 원칙으로 거른 판.
- 공개 원칙: 연락처는 이메일 하나, 고객사 보안 사고·취약점 세부·보안 설정·내부 주소·사람 이름·고객사 데이터 규모 금지. 근거 없는 문장 금지.
- 마크다운 주의: 닫는 `**` 앞이 문장부호면 굵게가 안 풀리고(`<strong>` 사용), 범위 물결표 두 개는 취소선이 된다(`\~`). 둘 다 `shots.mjs` 가 잡는다.
- 연락처·이름·메뉴: `web/src/site.ts`
