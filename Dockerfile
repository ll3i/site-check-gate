FROM python:3.12-slim

ENV PYTHONIOENCODING=utf-8 \
    PORT=8080 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ---- 빌드 의존성 (Pillow·numpy 등 C 확장 대응) ---------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# ---- 애플리케이션 의존성 (레이어 캐시 활용) ------------------------------------
COPY requirements.txt requirements-vision.txt ./

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-vision.txt

# ---- 애플리케이션 코드 ---------------------------------------------------------
COPY service/ ./service/
COPY assets/ ./assets/
COPY prelim-skill/ ./prelim-skill/
COPY prelim-extra/ ./prelim-extra/
COPY mcpServers.json ./

# ---- 포트 ------------------------------------------------------------------------
EXPOSE 8080

# ---- 실행 ------------------------------------------------------------------------
# PORT 환경변수를 우선하고, 미설정 시 8080 을 사용한다 (shell 확장 사용).
CMD uvicorn service.api.app:app --host 0.0.0.0 --port ${PORT:-8080}
