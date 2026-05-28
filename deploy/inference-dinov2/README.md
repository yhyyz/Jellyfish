# DINOv2 ViT-B/14 一致性服务 sidecar

P4 Wave A（W27-T1）—— 视觉一致性引擎基础设施。**ML stack（torch + transformers
+ pillow）完全隔离在独立 sidecar，主 backend 镜像不增重**（DECISION D-VISION-DEPLOY）。

## 用途

为 backend 的 `shot_consistency_check` 任务提供两类能力：

1. 把单张视频帧 / 参考图编码为 768 维 embedding（DINOv2-base CLS token）。
2. 直接计算两张图片的余弦相似度。

backend 的 `app.core.integrations.dinov2.client.Dinov2HttpClient` 走 httpx 调
本 sidecar，链路是：

```
shot.dubbed_video_file_id -> ffmpeg 抽 6 帧 -> POST /embed × 6 ->
均值 -> ProductImage(front/three_quarter) -> POST /embed -> cosine
                                       -> shot.consistency_score
```

## 端点

- `GET /health`：判活 + 模型是否就绪。模型未加载时返回 `model_loaded=false`。
- `POST /embed`：multipart 文件 / form `image_b64` / form `image_url`，三选一。
  返回 `{embedding: float[768], dim: 768, elapsed_ms}`。
- `POST /embed-json`：JSON 形式 `{image_b64?, image_url?}`，便于纯 JSON 调用方。
- `POST /similarity`：JSON `{frame_b64, reference_b64}` → `{similarity, elapsed_ms}`。

所有 embedding 都已 L2 归一，外部可直接做点积得 cosine。

## 本地构建

```bash
cd deploy/inference-dinov2
docker build -t jellyfish-dinov2-sidecar .
```

镜像约 2-3GB（torch + transformers）。模型权重不会在 build 阶段下载——首次
请求触发懒加载，缓存到 `HF_HOME=/models`。建议在 compose 中把 `/models` 挂卷
持久化。

## 单容器手动启动

```bash
docker run -d --name dinov2-sidecar \
  -p 8001:8001 \
  -v dinov2-models:/models \
  jellyfish-dinov2-sidecar
curl -s http://localhost:8001/health | jq
```

首次启动需要 5-15 秒加载模型；可结合 `--health-start-period=120s`
配合 docker-compose 的 healthcheck。

## GPU 加速（可选）

sidecar 默认在 CPU 上运行，单帧 embed 约 200-500ms，已满足 P4 P95 SLA。

如需 GPU：

1. 宿主机安装 NVIDIA Container Toolkit。
2. compose 中把 `inference-dinov2` 服务设置 `runtime: nvidia` 或 `deploy.resources.reservations.devices`。
3. 容器内 `torch.cuda.is_available()` 自动返回 `true`，模型会被搬到 `cuda:0`。

镜像本身不绑定 GPU 驱动，CPU/GPU 切换无需重新 build。

## 与主 backend 的依赖关系

| 维度 | 主 backend 镜像 | dinov2 sidecar |
| --- | --- | --- |
| 基础镜像 | `python:3.12-slim` | `python:3.11-slim` |
| Python 依赖 | FastAPI + SQLAlchemy + httpx | FastAPI + torch + transformers + pillow |
| 镜像体积 | ~700MB | ~2.5GB |
| GPU 依赖 | 无 | 可选 |
| 升级节奏 | 跟随 backend | 与 P4 视觉一致性需求绑定 |

## 故障排查

- `model_loaded=false` 持续 > 1 分钟：检查容器日志是否被 HF Hub 限速 / 网络隔离；
  把 HF_HOME 卷预热到一个已 download 的 `models--facebook--dinov2-base/` 目录。
- `503 DINOv2 model is not ready`：sidecar 仍在加载，调用方按 `Retry-After: 5`
  退避；backend 客户端默认有 3 次指数退避重试。
- embed 单次 > 5s：CPU 模式下属正常，可启用 GPU 或在 compose 中扩容副本数（
  本镜像支持 stateless 横向扩展，无 session 状态）。
