# DINOv2 ViT-B/14 视觉一致性 sidecar Dockerfile（P4 W27-T1）。
#
# 设计要点：
# - 与 Jellyfish 主 backend 镜像（python:3.12-slim，无 ML stack）完全隔离；
# - 选择 python:3.11-slim：torch / transformers 在 3.11 的 wheel 覆盖最广；
# - 默认安装 CPU 版 torch（官方 PyPI 上的 wheel 已是 CPU build），上线 GPU
#   时由 docker-compose 的 nvidia runtime + 宿主机 CUDA 驱动注入，无需重建镜像；
# - HF_HOME=/models：模型缓存挂卷到宿主，重启容器不重新下载 ~330MB 权重；
# - HEALTHCHECK 依赖 /health 端点。

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    TRANSFORMERS_CACHE=/models \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# 系统依赖：libgl1 / libglib2.0-0 是 pillow + transformers vision pipeline 常见动态库；
# curl 用于 HEALTHCHECK 自检；ca-certificates 用于 HF Hub TLS。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 利用 Docker layer cache：先装依赖，再 COPY 源码。
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 应用源码：app 目录下 main.py / model.py。
COPY app ./app

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -fsS http://localhost:8001/health || exit 1

# 注意：模型在首次 /embed 调用前由 lifespan startup hook 触发懒加载；
# 这里只起 uvicorn 进程，不在 docker build 阶段下载权重（保持镜像可重建）。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
