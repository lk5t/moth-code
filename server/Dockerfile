# MOTH Server image (accounts, billing, referrals, training coordinator, model registry, MOTH Cloud).
# Build from the repository root:  docker build -f server/Dockerfile -t moth-server .
# CPU PyTorch by default. For GPU inference, build FROM an NVIDIA CUDA runtime image and install
# a CUDA PyTorch wheel instead (see docs/SERVER.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MOTH_SERVER_DATA_DIR=/data
RUN useradd --system --uid 10001 --home /data moth && mkdir -p /data && chown moth /data
WORKDIR /app
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY backend /app/backend
COPY server /app/server
RUN pip install /app/backend "/app/server[postgres]"
USER moth
EXPOSE 8900
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8900/v1/health', timeout=4)"
CMD ["moth-server", "serve", "--host", "0.0.0.0", "--port", "8900"]
