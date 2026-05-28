"""DINOv2 ViT-B/14 模型加载与推理封装。

为什么存在：
    sidecar 进程仅加载一次模型，所有 HTTP 请求共用同一个 :class:`Dinov2Embedder`
    单例（FastAPI lifespan 在启动期触发懒加载，避免 Docker build 时下载权重）。

边界：
    - 不暴露任何 HTTP 接口（由 :mod:`app.main` 负责）；
    - 不维护任何业务侧的 shot / product 概念；
    - 仅做 "PIL.Image -> 768-dim embedding" 与 "两个 embedding -> 余弦相似度"
      两件事；
    - 设备选择：``torch.cuda.is_available()`` 决定 GPU/CPU；CPU fallback OK，
      P4 阶段不强依赖 GPU 推理。
"""

from __future__ import annotations

import logging
import threading
from io import BytesIO

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModel

logger = logging.getLogger(__name__)

# DINOv2 base 模型在 HF Hub 上的 repo 名；ViT-B/14 即 base 规模，patch_size=14。
# 输出 cls token 维度固定 768。
_MODEL_NAME = "facebook/dinov2-base"
_EMBED_DIM = 768


class Dinov2Embedder:
    """DINOv2 ViT-B/14 的线程安全嵌入器。

    设计要点：
        - 懒加载：``__init__`` 不下载权重，``ensure_loaded()`` 触发首次加载；
        - 线程安全：用 :class:`threading.Lock` 保护权重加载与推理（
          uvicorn 在 ``--workers 1`` 下仍可能并发处理请求）；
        - 单例风格：sidecar 全局只构造一次（在 lifespan startup hook）。

    属性：
        device: ``"cuda"`` 或 ``"cpu"``；GPU 不可用时自动降级。
        embed_dim: 输出向量维度（DINOv2-base 固定为 768）。
    """

    def __init__(self, *, model_name: str = _MODEL_NAME) -> None:
        self._model_name = model_name
        self._processor: AutoImageProcessor | None = None
        self._model: AutoModel | None = None
        self._lock = threading.Lock()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.embed_dim = _EMBED_DIM

    def ensure_loaded(self) -> None:
        """触发模型权重与图像处理器的加载。

        幂等：多次调用只加载一次；HF Hub 的本地缓存命中后耗时 < 2s。
        失败时抛 :class:`RuntimeError`，由调用方决定是否退出进程。
        """

        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            logger.info(
                "loading DINOv2 weights model=%s device=%s",
                self._model_name,
                self.device,
            )
            try:
                self._processor = AutoImageProcessor.from_pretrained(self._model_name)
                model = AutoModel.from_pretrained(self._model_name)
                model.eval()
                model.to(self.device)
                self._model = model
            except Exception as exc:  # noqa: BLE001
                logger.exception("failed to load DINOv2 model: %s", exc)
                raise RuntimeError(f"DINOv2 load failed: {exc}") from exc
            logger.info("DINOv2 weights ready dim=%s", self.embed_dim)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def embed_image(self, image_bytes: bytes) -> list[float]:
        """计算单张图片的 768-dim embedding。

        Args:
            image_bytes: 任意可被 PIL 解码的二进制（jpg/png/webp）。

        Returns:
            长度为 ``embed_dim`` 的 Python ``list[float]``，已做 L2 归一，
            可直接拿去算余弦相似度（dot product == cosine）。

        Raises:
            ValueError: 图片解码失败 / 不是 RGB / 尺寸为 0；
            RuntimeError: 模型尚未加载（ensure_loaded 未调用）。
        """

        if self._model is None or self._processor is None:
            raise RuntimeError("Dinov2Embedder is not loaded; call ensure_loaded() first")

        try:
            with Image.open(BytesIO(image_bytes)) as raw:
                image = raw.convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"invalid image bytes: {exc}") from exc

        # processor + model 在并发请求下需要同一把锁：HF transformers ViT 内部
        # 的某些 GPU 推理路径不是完全 reentrant；CPU fallback 下序列化也比
        # 抢锁失败更稳。锁粒度限定到单张图片，单 sidecar 进程不会成为瓶颈。
        with self._lock:
            with torch.inference_mode():
                inputs = self._processor(images=image, return_tensors="pt")
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                outputs = self._model(**inputs)
                # DINOv2 backbone 输出 ``last_hidden_state``；CLS token 取 [:, 0]
                # 是官方推荐做法（pooler_output 在 DINOv2 中等价的 CLS embedding）。
                if hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
                    emb = outputs.pooler_output[0]
                else:
                    emb = outputs.last_hidden_state[0, 0]
                # L2 归一，便于后续直接做点积 = cosine。
                emb = torch.nn.functional.normalize(emb, p=2, dim=0)
                vector = emb.detach().cpu().numpy().astype(np.float32)

        if vector.shape != (self.embed_dim,):
            raise RuntimeError(
                f"unexpected embed shape: got {vector.shape}, expected ({self.embed_dim},)"
            )
        return vector.tolist()


def cosine_similarity(a: list[float] | np.ndarray, b: list[float] | np.ndarray) -> float:
    """计算两个 1-D 向量的余弦相似度。

    输入向量已 L2 归一时退化为点积；保留通用实现以便外部调用方传入未归一向量。
    """

    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.shape != vb.shape:
        raise ValueError(f"vector shape mismatch: {va.shape} vs {vb.shape}")
    if va.ndim != 1:
        raise ValueError("cosine_similarity expects 1-D vectors")
    norm_a = float(np.linalg.norm(va))
    norm_b = float(np.linalg.norm(vb))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


__all__ = [
    "Dinov2Embedder",
    "cosine_similarity",
]
