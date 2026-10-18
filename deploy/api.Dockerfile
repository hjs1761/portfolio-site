# 시뮬레이터 판정 API. 셸을 실행하지 않는 순수 문자열 분석 서버.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_SYSTEM_PYTHON=1
RUN pip install --no-cache-dir uv==0.5.*
WORKDIR /app
COPY api/pyproject.toml api/uv.lock* ./
RUN uv export --no-dev --no-hashes --format requirements-txt > /tmp/req.txt \
    && uv pip install --system --no-cache -r /tmp/req.txt
COPY api/guard_core ./guard_core
COPY api/app ./app
RUN useradd --system --uid 10001 --no-create-home app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-server-header"]
