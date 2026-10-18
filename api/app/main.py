"""배포 가드 시뮬레이터 API.

상태를 저장하지 않는다. diff 기록 같은 세션 상태는 브라우저가 들고 다니며 요청마다 보내고
갱신본을 받는다. 셸을 실행하지 않는다 — 명령은 문자열로만 분석한다.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field, StringConstraints

from guard_core import SCENARIOS, VirtualFS, evaluate
from guard_core.vfs import DEFAULT_CWD

MAX_COMMAND = 2000
MAX_PATH = 300
MAX_ENTRIES = 50     # diffs·fetch 각각
MAX_SOURCES = 10     # diff 기록 하나의 소스 수

PathStr = Annotated[str, StringConstraints(max_length=MAX_PATH)]


class DiffRec(BaseModel):
    ts: float = Field(allow_inf_nan=False)
    sources: list[PathStr] = Field(default_factory=list, max_length=MAX_SOURCES)


class FetchRec(BaseModel):
    ts: float = Field(allow_inf_nan=False)
    target: PathStr


class GuardState(BaseModel):
    diffs: dict[PathStr, DiffRec] = Field(default_factory=dict, max_length=MAX_ENTRIES)
    fetch: dict[PathStr, FetchRec] = Field(default_factory=dict, max_length=MAX_ENTRIES)


class EvaluateRequest(BaseModel):
    tool: Literal["Bash", "Edit", "Write"]
    command: str | None = Field(None, max_length=MAX_COMMAND)
    file_path: str | None = Field(None, max_length=MAX_PATH)
    cwd: str | None = Field(None, max_length=MAX_PATH)
    state: GuardState = Field(default_factory=GuardState)
    clock_offset_sec: int = Field(0, ge=0, le=7200)


STATE_BUDGET = 24_000   # 돌려줄 상태의 JSON 크기 상한(바이트). 앞단 요청 본문 상한(32KB) 안에
                        # 상태 + 명령(2,000자) + 나머지가 들어가야 다음 요청이 막히지 않는다.


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode())


def clamp_state(st: dict) -> dict:
    """돌려줄 상태를 다음 요청이 받아들여지는 크기로 맞춘다. 판정은 이미 끝났다.

    한 명령으로 요청 상한보다 많은 기록을 만들 수 있다(예: diff 한 번에 대상 60개).
    그대로 돌려주면 다음 요청이 422(개수 상한)나 앞단 413(본문 크기)으로 막힌다.
    최근 기록부터 남기고(개수·크기 예산 안에서), 소스는 정렬 순서 앞에서부터,
    경로 상한을 넘는 항목은 버린다."""
    def fits(p):
        return isinstance(p, str) and len(p) <= MAX_PATH

    items = []
    for k, v in st.get("diffs", {}).items():
        if fits(k):
            items.append(("diffs", k, {"ts": v["ts"],
                                       "sources": [s for s in v.get("sources", []) if fits(s)][:MAX_SOURCES]}))
    for k, v in st.get("fetch", {}).items():
        if fits(k) and fits(v.get("target")):
            items.append(("fetch", k, {"ts": v["ts"], "target": v["target"]}))
    items.sort(key=lambda it: it[2]["ts"], reverse=True)

    out: dict = {"diffs": {}, "fetch": {}}
    used = _size(out)
    for kind, k, v in items:
        if len(out[kind]) >= MAX_ENTRIES:
            continue
        cost = _size({k: v}) + 1
        if used + cost > STATE_BUDGET:
            continue
        out[kind][k] = v
        used += cost
    return out


MAX_EVENTS = 50
MAX_CHECKS = 60
MAX_DETAIL = 300
MAX_MESSAGE = 6000


def clamp_output(d: dict) -> dict:
    """응답 크기 상한. 한 줄 명령으로 대상 수십 개 × 소스 수십 개를 만들면 이벤트·검사 설명이
    입력의 수백 배로 불어난다(1.3KB 명령 → 420KB). 판정 결과(decision·kind)는 건드리지 않고
    보여 주는 목록만 자른다. 잘린 곳은 표시한다."""
    events = []
    for e in d["events"][:MAX_EVENTS]:
        e = dict(e)
        if len(e.get("sources", [])) > MAX_SOURCES:
            e["omitted"] = len(e["sources"]) - MAX_SOURCES
            e["sources"] = e["sources"][:MAX_SOURCES]
        events.append(e)
    checks = [{**c, "detail": c["detail"] if len(c["detail"]) <= MAX_DETAIL
               else c["detail"][:MAX_DETAIL] + " …(생략)"} for c in d["checks"][:MAX_CHECKS]]
    if len(d["checks"]) > MAX_CHECKS:
        checks[-1]["detail"] += f" (이하 {len(d['checks']) - MAX_CHECKS}건 생략)"
    message = d["message"]
    if len(message) > MAX_MESSAGE:
        message = message[:MAX_MESSAGE] + "\n… (이하 생략)"
    return {**d, "events": events, "checks": checks, "message": message}


app = FastAPI(title="deploy-guard-simulator", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/guard/scenario")
def scenario():
    fs = VirtualFS.default()
    return {
        "cwd": DEFAULT_CWD,
        "volumes": dict(fs.volumes),
        "tree": fs.tree(),
        "scenarios": [asdict(s) for s in SCENARIOS],
    }


@app.post("/api/guard/evaluate")
def evaluate_endpoint(req: EvaluateRequest):
    now = time.time() + req.clock_offset_sec
    d = evaluate(req.tool, req.command, req.file_path, req.cwd,
                 req.state.model_dump(), now, VirtualFS.default())
    return {**clamp_output(asdict(d)), "state": clamp_state(d.state), "now": now}
