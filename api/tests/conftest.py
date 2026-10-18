import pytest

import guard_core.engine as engine


@pytest.fixture(autouse=True)
def _strict_engine(monkeypatch):
    """원본처럼 내부 오류를 통과(fail-open)시키면 엔진 버그가 「pass」 로 숨는다. 시험에서는 끈다."""
    monkeypatch.setattr(engine, "FAIL_OPEN", False)
