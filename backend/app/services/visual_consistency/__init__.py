"""视觉一致性服务包（P4 W27-T1）。

包含：
    - :mod:`sampler`：纯函数 ffmpeg / ffprobe 参数构造器；
    - :mod:`consistency_worker`：``shot_consistency_check`` task_kind 异步执行器。

为什么分包：
    把 "ffmpeg 抽帧 / DINOv2 调用 / score 写库" 这条新 pipeline 与既有
    ``app.services.studio.chapter_av_export`` 解耦——后者负责章节级配音 +
    字幕烧录，本包只做"裸视频 vs 商品参考图的视觉相似度"，职责互不重叠。
"""
