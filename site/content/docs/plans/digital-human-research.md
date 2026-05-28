---
title: "数字人 / 真 lip-sync 集成路径调研"
weight: 70
description: "Sadtalker / D-ID / Wav2Lip 三条候选路径的集成成本、画质、合规对比；P5 W33 调研产出，推迟 P5+ 实装。"
---

> 本文属于"任务计划"文档。范围严格限定为 P5 Wave 33 的调研产出，**不包含任何代码改动**。
> 当前 D10 决策（不做 lip-sync，仅 silent_with_tts + keep_native + ASR 反推字幕）保持不变；
> 真正的实装拆分到 Wave 35+，本文最后一章给出预拆解，便于将来直接落地。

# 数字人 / 真 lip-sync 集成路径调研

## 1. Goals

### 1.1 为什么要做这次调研

P3 Wave 17 收尾时落地了 D10 决策：

> 不做 lip-sync，仅 `silent_with_tts` 路径；演员张嘴 / 口播镜头通过 `keep_native` 路径处理 +
> Level 2 prompt hint 引导自然口型 + Paraformer-v2 ASR 反推字幕。
> 数字人 / 真 lip-sync 推迟 P5+。

这条决策在 P3/P4 阶段是正确的，因为：

- `silent_with_tts` 让镜头与 TTS 解耦，避免任何对口型偏差成为返工成本；
- `keep_native` 直接复用 happyhorse-1.0-r2v 自带原音 + Paraformer ASR 字幕，零额外推理；
- Level 2 prompt hint（"嘴型自然"、"避免长时段开口"）规避了 r2v 模型对话场景的最差表现区。

但随着 P4/P5 业务向 **剧情带货 (story-driven commerce)** 与 **虚拟主持** 倾斜，
单纯的 keep_native + 静音叠加 TTS 已经不能覆盖三类核心场景：

1. **剧情带货主播口播带货剧本**：演员需要直接对镜头说"这款洗发水我用了三个月..."，
   口型必须对得上 TTS 输出，不然抖音 / 视频号 / 小红书的审核员（人工）一眼能看出口型与声音错位。
2. **虚拟主持人**：固定形象 + 固定音色 + 反复对镜头说不同台词，
   场景对图像一致性要求极高，r2v 的随机性会破坏稳定形象。
3. **二创账号矩阵**：同一段脚本配不同形象播报，要求"换脸不换稿"，
   现有 keep_native 路径需要每次重新跑 r2v，无法批量复用。

### 1.2 D10 当前局限

| 局限项 | 现状 | 业务影响 |
| --- | --- | --- |
| 口型不对应 | TTS 与画面口型独立生成，依赖 r2v 模型自洽 | 长口播镜头明显穿帮 |
| 形象不稳定 | 每次 r2v 都重新生成，相同 prompt 不保证人物一致 | 虚拟主持账号无法长期运营 |
| 单镜头开口时长上限 | r2v happyhorse 对长开口画面（>3s）质量明显下降 | 不能做 5–10s 长口播 |
| 二次配音成本高 | 同一画面换台词必须重新跑 r2v | 矩阵化生产链路不顺 |
| ASR 反推延迟 | Paraformer-v2 对原音质量敏感，r2v 输出嘈杂时漏字率上升 | 字幕需要二次人工校对 |

D10 决策本身并未失效——大部分剧情类镜头依然走 `silent_with_tts`。
本次调研要解决的是 **口播镜头 / 虚拟主持镜头** 这条窄而高价值的子路径，
让用户在分镜工作室 (`StoryShotStudio`) 看到镜头被打上 "需要 lip-sync" 标签时，
能选择数字人 path 而不是被迫 keep_native + 半成品口型。

### 1.3 调研范围

本调研只覆盖三条主流候选路径：

- **SadTalker**：开源单图驱动整脸（嘴型 + 头部姿态）方案，CVPR 2023。
- **D-ID**：商业 SaaS API，单图 + audio → talking head 视频。
- **Wav2Lip**：开源研究方向的 lip-only post-processing，仅替换嘴部。

不在范围内的路径（备注，不展开）：

- **HeyGen / Synthesia**：偏向"模板化 avatar"，不允许任意上传角色，
  与 jellyfish 的"用户生成自定义形象"模式不匹配。
- **MuseTalk / V-Express / EchoMimic / Hallo**：2024–2025 学术新方法，
  社区落地不足、license/部署稳定性未经验证，留待 Wave 36+ 二次迭代时再评估。
- **Wan 2.6 / Sora-style 端到端**：直接在 r2v 阶段集成 lip 控制，
  与现有 happyhorse 流水线耦合度过高，归到"r2v 模型升级"路线，不属于本文范围。

### 1.4 调研产出

本文产出三类工件：

1. **Comparison Matrix**（第 2 章）：10+ 维度横向对比；
2. **Recommended Path**（第 3 章）：推荐 / 次选 / 不推荐 + 推理；
3. **Wave 35+ Pre-Decomposition**（第 5 章）：基于推荐路径的 atomic task 预拆解，
   便于实装阶段直接复用，不需要重新分析。

---

## 2. Comparison Matrix

下表的成本 / 时延 / VRAM 数据来源：
SadTalker GitHub README / Issue #650 / Replicate `cjwbw/sadtalker` 卡片 /
D-ID 官网 `pricing/api/` 与 `pricing/studio/` 页 / 第三方评测 (heyfish.ai, tekpon, tavus) /
Wav2Lip GitHub README 与 Issue #104 / #623。

### 2.1 主对比表

| 维度 | SadTalker (开源) | D-ID (商业 SaaS) | Wav2Lip (开源研究) |
| --- | --- | --- | --- |
| **License** | Apache 2.0（2023 年中已从 non-commercial 切到 Apache 2.0；模型权重同条款） | 商业付费许可（Lite / Pro / Advanced / Enterprise 分档），Pro 及以上含商用授权 | Code/权重 = 仅个人 / 研究 / 非商业；商业必须联系 Sync Labs 单独购买 |
| **部署模式** | Sidecar 自部署（Python + PyTorch + CUDA），可起独立服务封装 REST | Cloud API（仅 SaaS，无私有化部署） | Sidecar 自部署，模型小可与主进程同栈跑 |
| **输入要求** | 单张正面人脸图（建议 256×256 / 512×512）+ wav 音频 | 单张人脸图 / 已有 presenter / 上传素材 + audio (mp3/wav) | **必须有源视频**（提供画面帧序列）+ wav；只换嘴，不动头/身 |
| **输出** | 整脸驱动视频（嘴型 + 头部微动 + 眨眼），分辨率受输入图限制，配 GFPGAN 可超分到 1080p | 1080p talking head 视频，分辨率与时长由套餐档决定 | 与输入视频同分辨率，仅嘴部区域被替换 |
| **lip-sync 精度** | 中（SyncNet 对中文打分明显低于英文，社区 Issue #868 确认） | 高（专有模型，多语言均衡，含中文优化） | 高（专精嘴型，SyncNet loss ~0.2 是该路径最低）；但中文/普通话 phoneme 对齐弱于英文 |
| **头部姿态自然度** | 中–高（3DMM 系数驱动，支持 still / head-motion 两档） | 高（专有 motion model，姿态 + 微表情自然） | **不支持**（只换嘴，头/身保留输入视频原样） |
| **单镜头成本（1080p × 5s）** | ¥0（自建）+ 摊销 GPU 时长 ≈ ¥0.05–0.15（按 RTX 3090 ¥1.5/h 折算 60–90s 推理） | API ≈ $5.90/min（heyfish.ai 实测，含基础 1080p）；5s 镜头约 ¥3.5 | ¥0 + GPU 摊销，比 SadTalker 更轻；¥0.02–0.05 |
| **推理时延 P50（5s 输出）** | RTX 3090 ≈ 60–90s，A100 ≈ 30–50s（Replicate 卡片：A100 完整 pipeline ≈ 83s） | API 调用 ≈ 30–60s 异步；webhook 回调 | RTX 3090 ≈ 10–20s，比 SadTalker 快 4–5×（仅嘴部，无 motion 模块） |
| **GPU VRAM** | 最低 8 GB（dlib + face renderer），稳定推荐 12 GB；Issue #118 实测 6 GB OOM | N/A（云端） | 4–6 GB 即可跑（模型小，~140 MB） |
| **与 keep_native r2v 兼容性** | 需要 face crop + 单帧驱动；与 r2v **冲突**（r2v 自带头身动作，SadTalker 重新驱动头部会破坏） | 完全独立路径，**替代** keep_native 而非补充 | **天然适配**：直接在 r2v 输出之上做嘴部替换，头/身保留 r2v 动作 |
| **商业带货合规** | OSS license 允许商用，**但内容合规由部署方自行兜底**（敏感人脸 / 政治 / 名人均无平台审核） | 内置 ToS：禁止 deepfake、政治领导人、未经授权名人；明确商业带货允许 | 商用必须走 Sync Labs 商业版；研究版严禁商用 |
| **中国大陆访问** | 自部署无依赖 | **被墙 / 需国际链路**；国内代理稳定性不可控；HeyGen 同样状况 | 自部署无依赖 |
| **中文语音支持** | 中（4 声调对齐弱于英文，但能用；可接 CosyVoice / 阿里 TTS wav 直接喂入） | 高（官方支持中文 voice 与中文 lip-sync 优化） | 中（与 SadTalker 接近，中文 phoneme 训练样本不足） |
| **CosyVoice 接驳** | 直接喂 wav，无需中间格式 | 接受 mp3/wav 上传（接近最简，需 multipart upload） | 直接喂 wav |
| **多镜头一致性** | 同张人脸图 → 同人脸输出，但姿态随机（每次微动作不同） | Personal Avatar 锁定形象，跨镜头一致性最强 | 完全继承 r2v 输入视频，一致性 = r2v 一致性 |
| **可控性（情绪 / 节奏）** | `--still` / `--enhancer gfpgan` / `--expression_scale` 等 CLI 参数 | API 支持 `driver_url` / `expressions` / `result_format` | 几乎无（只跟音频走） |
| **失败模式** | 长 audio (>30s) 显存波动；GFPGAN 对眼部偶发伪影 | 配额超限、SLA 抖动、单调 webhook 错误码 | 输入帧人脸过小 / 侧脸 / 多人脸时嘴部对齐崩溃 |
| **生产案例（公开可查）** | Replicate / HuggingFace Space / Discord bot 大量个人 + 中小工作室 | HeyGen 营销 / 培训行业、跨境电商口播视频 | Sync Labs 商业版被多家影视后期 / 配音工作室采用 |
| **二次开发空间** | 整套 PyTorch 源码可改，可单独接管 face_renderer / mapping_net | 仅 API 层，不开放模型 | 整套 PyTorch 源码可改，但 license 把商用堵死 |

### 2.2 集成模式归类

按"与现有 happyhorse-1.0-r2v 流水线"的接驳关系，三条路径分成三种模式：

- **替代模式（Substitute）**：D-ID 完全独立，不依赖 r2v；对镜头打 "lip-sync" 标后直接绕过 r2v。
- **后处理模式（Post-process）**：Wav2Lip 在 r2v 输出之上做嘴部替换，复用头身动作。
- **并行模式（Parallel-input）**：SadTalker 用单张 keyframe + audio 自己生成完整画面，
  与 r2v 输出**独立**而非叠加，等价于"另一条 r2v 通道"。

### 2.3 jellyfish 现有上下文匹配度

| 现有能力 | SadTalker 匹配 | D-ID 匹配 | Wav2Lip 匹配 |
| --- | --- | --- | --- |
| `chapter_av_export` 两挡音频混合（W31 已落） | 与 `voice_bgm` 兼容（输出 mp4 + 独立 voice 轨） | 兼容（输出 mp4 含音频，需要分轨） | 与 r2v 后处理兼容，voice 轨已对齐 |
| W17 `silent_with_tts` 路径 | 可作为该路径的"画面层"上位替代 | 直接覆盖整条路径 | 直接喂 silent_with_tts 的 voice + r2v 视频 |
| W17 `keep_native` 路径 | **冲突**（重新生成头部动作覆盖原 r2v） | **替代** keep_native | **互补**（r2v 提供头身，Wav2Lip 提供口型） |
| W31 `voice_bgm` / `full` ducking | 兼容 | 兼容（输出已含 voice，主轨 ducking 需独立处理） | 兼容 |
| W29 自定义音色（VoicePack） | 通过 wav 输入直接复用 | 接受任意 wav 上传 | 通过 wav 输入直接复用 |
| W30 项目级字幕样式 | 字幕渲染层独立，无影响 | 字幕渲染层独立，无影响 | 字幕渲染层独立，无影响 |
| W32 RBAC（admin / member） | 需要新加 `digital_human:create` 权限位 | 需要新加 `digital_human:create` + 配额管理 | 需要新加 `digital_human:create` |
| Paraformer-v2 ASR 反推 | 与 SadTalker 输出错位（音频是新生成 wav） | 与 D-ID 输出错位（音频是新生成 wav） | 与 r2v 输入一致，ASR 路径不变 |

---

## 3. Recommended Path

### 3.1 推荐结论

| 排序 | 路径 | 定位 |
| --- | --- | --- |
| **首选 / 推荐** | **Wav2Lip (商业版 via Sync Labs)** + 自维护 OSS 备份 path | 与 happyhorse r2v 后处理天然耦合，最小破坏现有流水线 |
| **次选** | **SadTalker (Apache 2.0 自建 sidecar)** | 极端场景下作为不依赖 r2v 的"独立数字人通道" |
| **不推荐** | **D-ID** | 国内访问 + 价格 + 完全替代既有流水线，与 jellyfish 现状不匹配 |

### 3.2 为什么首选 Wav2Lip 商业版（含 OSS fallback）

1. **与 happyhorse-1.0-r2v 天然解耦**：r2v 负责画面（头身动作 + 场景 + 服化），
   Wav2Lip 在其输出 mp4 上仅替换嘴部 ROI，单独可控、单独可回滚；
   失败时直接 fallback 回 keep_native，零业务影响。
2. **现有 W17 `silent_with_tts` 路径无需改动**：CosyVoice 输出的 wav 直接作为
   Wav2Lip 输入；TTS 模块、字幕模块、`chapter_av_export` 全部不动。
3. **GPU 成本最低**：4–6 GB VRAM，可与现有 sidecar 容器同 GPU 复用，
   不需要为数字人单开 GPU 节点；推理时间是 SadTalker 的 1/4。
4. **形象一致性 = r2v 的一致性**：r2v 已经投入 W19 / DINOv2 一致性预算，
   后处理路径直接继承所有人物 / 场景 / 服化的稳定性。
5. **license 问题清晰可控**：Sync Labs 商业版有标准 EULA，付费即可商用；
   OSS 版只用于 staging / dev 环境的 e2e smoke，生产链路只跑商业版。

### 3.3 为什么把 SadTalker 留作次选

SadTalker 的 Apache 2.0 license 是巨大优势（不依赖任何商业谈判），
但它带来三个硬约束让它不适合做主路径：

- **不可叠加 r2v**：SadTalker 重新驱动头部，r2v 已经生成的头身动作会被覆盖，
  等于推翻 W19 一致性投入；
- **中文 lip-sync 质量是已知短板**（GitHub Issue #868），多个社区报告中文场景"时好时坏"；
- **单镜头成本不止是 GPU**：还要走 dlib 人脸 landmark + 3DMM 拟合 + face renderer，
  failure surface 比 Wav2Lip 大很多。

但 SadTalker 在 **"完全没有 r2v 输出"** 的虚拟主持场景仍有价值：
单张固定 portrait + audio → 整脸视频，是真正的"数字人"语义，
所以保留为次选，覆盖 Wave 36+ 的 "纯虚拟主持账号" 子场景。

### 3.4 为什么不推荐 D-ID

- **国内访问受限**：D-ID 主站与 API 端点在中国大陆默认被墙，
  必须走 VPN / 第三方代理或部署中转；
  `chapter_av_export` 是一个长任务（>30s 的 polling），
  网络抖动会显著抬高失败率，违背 W31 已经落地的 SLA 假设。
- **完全替代而非补充**：D-ID 一次调用产整段视频，绕过 happyhorse r2v；
  这意味着 jellyfish 的"分镜 → 资产 → 视频"主流程被旁路，
  W19 / W20 / W30 在画面层的所有投入对该路径无效。
- **成本曲线陡峭**：API 单价 $5.90/min，5s 镜头约 ¥3.5，
  按一个项目 100 个口播镜头估算 ≈ ¥350 / 项目；
  与 W29 自建音色每镜头 ¥0.X 完全不在一个数量级。
- **合规风险代理给第三方**：D-ID ToS 自带政治领导人 / 名人 / deepfake 黑名单，
  但执法在 D-ID 侧；如果用户上传自有授权人脸，平台仍可能误杀，
  失败模式不可控且回放无法本地 reproduce。

### 3.5 推荐路径执行口径

正式实装阶段（Wave 35+）按以下口径走：

1. **主路径 = Wav2Lip 商业版 (Sync Labs API)**：
   `chapter_av_export` 在镜头打上 `requires_lip_sync=true` 时，
   先跑 r2v 拿到无声画面 → CosyVoice 拿 wav → Sync Labs 后处理嘴部 → 与字幕合成。
2. **OSS Wav2Lip 仅用于 dev/staging**：
   通过 `LIP_SYNC_PROVIDER=oss|sync_labs` env 切换；
   生产环境硬约束为 `sync_labs`，OSS 路径在 staging 跑 e2e smoke。
3. **SadTalker 作为 Wave 36+ 探索分支**：
   仅在"纯虚拟主持"场景下被启用，不进入主带货剧情链路。
4. **D-ID 永久排除**：写入 `tech-radar.md`（如果将来引入），明确标注"已评估，不引入"。

---

## 4. Pre-Implementation Risks

实装阶段（Wave 35+）开工前必须先解决以下硬骨头。每条含：风险描述 / 触发条件 / 缓解措施。

### R-DH-1：Sync Labs 商业 EULA 与定价谈判周期长

- **描述**：Sync Labs（Wav2Lip 作者团队的商业实体）目前没有公开标准定价，
  必须邮件联系（rudrabha@synclabs.so / prajwal@synclabs.so）走 enterprise 谈判，
  签约周期可能 4–8 周，期间无法走商业 API。
- **触发条件**：Wave 35 启动当周即进入合规审批；team 没有现成 license 可复用。
- **缓解措施**：
  1. Wave 33 报告产出当周即由商务侧发起 Sync Labs 接洽（与 W34 release 并行）；
  2. 谈判期内 staging 用 OSS 版跑 e2e；
  3. 预留 SadTalker 兜底路径，如 Sync Labs 谈崩则切到 SadTalker 主路径（次选自动顶上）。

### R-DH-2：r2v → Wav2Lip 后处理的人脸 ROI 不稳定

- **描述**：happyhorse-1.0-r2v 输出的人脸位置、尺寸、姿态在镜头内会随机变化，
  Wav2Lip 需要在每帧检测人脸 ROI；当人脸过小 (<80px) 或侧脸 (>45°) 时嘴部对齐崩溃。
- **触发条件**：r2v prompt 包含远景 / 侧脸 / 多人脸场景。
- **缓解措施**：
  1. 在镜头层加 `lip_sync_capability` 预检（人脸面积比 / 姿态范围），
     不达标的镜头禁用 lip-sync 选项，引导用户回编辑页改 prompt；
  2. 单镜头预 ffprobe 提取关键帧、过 mediapipe face mesh 估算 P25 人脸尺寸，
     低于阈值（建议 96px @ 1080p）时直接 fallback keep_native；
  3. ROI 检测失败时**不静默退化**，明确返回任务 error 并提示用户改 prompt。

### R-DH-3：CosyVoice wav 与 r2v 视频时长不一致

- **描述**：W17 `silent_with_tts` 已假设 TTS 长度可与画面"对得上"，
  但 r2v 输出严格 5s（happyhorse 切片），CosyVoice 长度由文本长度决定，
  可能 3.5s 或 6.2s；Wav2Lip 后处理需要严格等长，否则要么截断音频，要么循环视频。
- **触发条件**：任何 `silent_with_tts` 路径下 wav.duration ≠ video.duration。
- **缓解措施**：
  1. 在 chapter_av_planner 加 `duration_align_strategy` 字段（pad_silence / trim_audio /
     stretch_video），默认 `pad_silence`（音频不足时尾部补静音）；
  2. wav.duration > video.duration 时，要么走 `trim_audio` 截断，要么提示用户拆镜重生成，
     **不允许 stretch 视频**（会破坏 r2v 节奏）；
  3. 在 OpenAPI schema 显式暴露该字段，前端工作室提供下拉选项。

### R-DH-4：Sync Labs API 异步轮询与现有任务系统的耦合

- **描述**：Sync Labs API 是异步 polling 模式，任务回调不可控，
  jellyfish 现有 task system 是 worker pull 模型，
  两套异步必须收敛到同一张任务表，否则会出现"双 polling"造成请求放大。
- **触发条件**：lip-sync 任务和现有 task worker 同时被调度。
- **缓解措施**：
  1. 新建 `lip_sync_provider_jobs` 表（外部 job_id / status / cost / submitted_at），
     由专用 `lip_sync_polling_worker` 轮询，非通用 task worker；
  2. 主任务 `chapter_av_export` 依赖该子任务完成，状态机走 `provider_pending → provider_done → merge`；
  3. 全局并发数上限（`LIP_SYNC_MAX_CONCURRENT`，默认 3）防止同时打爆 Sync Labs SLA。

### R-DH-5：OSS Wav2Lip license 边界与生产环境意外混用

- **描述**：OSS Wav2Lip 仅允许个人 / 研究 / 非商业；如果生产环境因 env 配错或代码 bug
  误调用 OSS path，整个 jellyfish 商用部署立即违反 license。
- **触发条件**：`LIP_SYNC_PROVIDER` 环境变量缺失 / 拼写错误 / 测试代码漏到 prod。
- **缓解措施**：
  1. provider 配置走 strict enum，缺省值 → 不允许启动，service 直接 panic exit；
  2. OSS 实现独立 sidecar 镜像，生产环境 helm chart 显式不部署该镜像；
  3. CI 加 sanity check：`grep -r "wav2lip_oss" backend/app/services/lip_sync/factory.py`
     在 production manifest 中必须为 0 引用；
  4. Sync Labs 调用入口加 license token 校验（启动时拉一次 `/license/validate`）。

### R-DH-6：中文 phoneme 对齐质量不达预期

- **描述**：Wav2Lip 与 SadTalker 的 SyncNet 训练样本以英文为主，
  中文四声调 + 卷舌音 / 鼻音的口型对齐误差比英文大；
  抖音 / 视频号审核员（人工抽检）一旦标记"口型穿帮"，
  封面会被打降权标签，账号侧风险显著。
- **触发条件**：第一批口播带货视频上线后被平台抽检。
- **缓解措施**：
  1. Wave 35 实装前先走 50 镜头中文 fixture 离线评测，
     SyncNet score < 5.0（论文阈值）的样本占比必须 < 15%；
  2. 上线初期默认对中文剧情带货项目仅启用 "lip-sync as preview"，
     生产视频仍需用户人工 confirm 后才走商业 API；
  3. 未来引入中文 fine-tune（Wave 36+ 候选），但前提是 Sync Labs 提供训练数据接口
     或 SadTalker 切到 GeneFace++ 中文权重（社区已有先例，见 SadTalker Issue #868）。

### R-DH-7：合规审核：用户上传 portrait 的授权链路缺失

- **描述**：剧情带货 / 虚拟主持都需要用户上传自有形象，
  当前 jellyfish `EntityImage` 没有上传授权声明字段（face license / consent record）；
  一旦用户用未授权人脸（如名人 / 同事）跑 lip-sync，
  jellyfish 平台方有连带责任。
- **触发条件**：第一个 lip-sync 任务被发起。
- **缓解措施**：
  1. 在 `EntityImage` 加 `face_consent_status` 字段（`unset` / `self_declared` / `signed_doc`）；
  2. 启动 lip-sync 任务前 service 层 hard-check `face_consent_status != unset`；
  3. UI 在上传 portrait 时强制弹"我确认已获得肖像权授权"勾选框（不勾不能上传）；
  4. 操作日志（`audit_logs`）记录每次 lip-sync 任务的 portrait 来源 + consent 字段值。

### R-DH-8：现有 `chapter_av_export` 时长 SLA 被打破

- **描述**：W31 已经落地 5 分钟章节 < N 秒的 SLA 基线（baseline benchmark），
  加 Wav2Lip 后处理后单镜头多 10–20s，章节级 ≈ 多 N×镜头数，
  极端 100 镜头长章节直接超时。
- **触发条件**：用户对长章节启用全镜头 lip-sync。
- **缓解措施**：
  1. lip-sync 改为镜头级 opt-in（默认关闭），用户在工作室手动勾选需要 lip-sync 的镜头；
  2. lip-sync 子任务并发上限 `LIP_SYNC_MAX_CONCURRENT=3`，主任务 progress
     按 lip-sync 与非 lip-sync 镜头分别计算；
  3. 把 lip-sync 镜头的 SLA 单独建模（`SLA_LIP_SYNC_PER_SHOT_SECONDS`），
     与原 SLA 解耦，不混入 W31 baseline 触发误报。

---

## 5. Wave 35+ Pre-Decomposition

> 本章假设走推荐路径 = **Wav2Lip 商业版 (Sync Labs) 主 + OSS staging fallback**。
> 如果 R-DH-1 谈判失败，需要切到 SadTalker 主路径，本章 5–7 个任务需要替换实现细节，
> 但任务编号 / 依赖图保持不变（接口契约级别一致）。

### Wave 35 — Foundation：合规、契约、provider 抽象（约 4 工作日）

| 任务 ID | 内容 | 依赖 | category + skills | 验证手段 |
| --- | --- | --- | --- | --- |
| **W35-T1** | `backend/app/models/entity_image.py` 加 `face_consent_status` 字段（Enum: `unset` / `self_declared` / `signed_doc`，默认 `unset`）；alembic `0022_p5plus_face_consent.py` 双向 migration | W34 release v0.7.0 in HEAD | `quick / []` | alembic forward + downgrade clean；pylint ≥ 9.5 |
| **W35-T2** | `backend/app/core/contracts/lip_sync.py` 抽象：`LipSyncRequest` / `LipSyncResult` / `LipSyncProvider` Protocol；`integrations/lip_sync/sync_labs.py` 与 `integrations/lip_sync/oss_wav2lip.py` 双实现壳（仅 stub） | W35-T1 | `deep / []` | pylint ≥ 9.5；契约文件 ≤ 200 行；不依赖 `tasks/*` |
| **W35-T3** | `backend/app/services/lip_sync_service.py`：provider factory（`LIP_SYNC_PROVIDER` env strict enum）+ feature flag `ENABLE_LIP_SYNC` + license token 启动校验 | W35-T2 | `deep / []` | unit 6 cases（factory / flag-off / token-missing / wrong-provider / sync-labs-ok / oss-ok） |
| **W35-T4** | `backend/app/api/v1/endpoints/lip_sync.py`：`POST /api/v1/lip-sync/preview`（单镜头试跑）+ `GET /api/v1/lip-sync/jobs/{id}` + RBAC 新权限位 `digital_human:create`（hooks 进 W32 user role 检查） | W35-T2/T3 | `deep / []` | curl smoke matrix（admin 200 / member 403 / no token 401 / flag-off 503） |
| **W35-T5** | `front/src/services/generated/*` 同步 + `pnpm run openapi:update` zero diff；新增 `LipSyncPreviewModal` 组件（未启用，仅契约存在） | W35-T4 | `visual-engineering / [frontend-ui-ux]` | RTL 3 cases（render / submit / error）；`pnpm exec tsc --noEmit` 绿 |

Commit 模板：`[feat] W35: lip-sync foundation (provider 抽象 + RBAC + UI 契约)`

### Wave 36 — Sync Labs 主路径打通（约 6 工作日）

| 任务 ID | 内容 | 依赖 | category + skills | 验证手段 |
| --- | --- | --- | --- | --- |
| **W36-T1** | `lip_sync_provider_jobs` 表 + alembic `0023_p5plus_lip_sync_jobs.py`（external_job_id / status / cost / submitted_at / completed_at / shot_id FK） | W35 全部 in HEAD | `quick / []` | forward + downgrade clean |
| **W36-T2** | `integrations/lip_sync/sync_labs.py` 真实实现：upload (multipart) → submit → polling → download；vcr cassette 离线回放 | W36-T1 | `deep / []` | unit 8 cases（含 timeout / 4xx / 5xx / partial download retry） |
| **W36-T3** | `lip_sync_polling_worker.py`（独立 worker，非通用 task worker）；并发上限 `LIP_SYNC_MAX_CONCURRENT=3`；指数退避；`max_attempts=60 × 5s` 共 5 分钟硬超时 | W36-T2 | `deep / []` | integration test（mock provider + 100 jobs 调度，无并发越界） |
| **W36-T4** | `chapter_av_planner` 加 `requires_lip_sync` 字段 + `lip_sync_capability` 预检（mediapipe face mesh，P25 人脸尺寸 < 96px → 自动 fallback keep_native） | W36-T3 | `deep / []` | unit 5 cases（5 类不同人脸尺寸 fixture） |
| **W36-T5** | `chapter_av_export` worker：在 r2v 输出后插入 lip-sync 后处理步骤；duration_align_strategy（默认 `pad_silence`） | W36-T4 | `deep / []` | e2e fixture：1 镜头 r2v + CosyVoice → lip-sync → 合成成功，spectral check pass |
| **W36-T6** | front `StoryShotStudio` 加"启用 lip-sync"勾选 + `face_consent_status` 强制 hard-check（unset → 不允许提交） | W36-T5 | `visual-engineering / [frontend-ui-ux]` | RTL 6 cases（勾选 / 取消 / consent missing / consent ok / preview / error） |
| **W36-T7** | `EntityImage` 上传弹窗加肖像权授权强制勾选（不勾不能上传）；操作日志 audit_log 记录 portrait 来源 | W36-T6 | `visual-engineering / [frontend-ui-ux]` | RTL 4 cases |
| **W36-T8** | 50 镜头中文 fixture 离线评测脚本 `backend/scripts/lip_sync_chinese_eval.py`，输出 SyncNet score 分布；< 5.0 占比 ≥ 15% 时 CI 触发 review | W36-T5 | `quick / []` | 跑 fixture，输出 markdown 报告 |
| **W36-T9** | verify batch + curl smoke matrix（含 R-DH-2 ROI 失败路径 / R-DH-3 时长不齐路径 / R-DH-5 license 校验路径） | W36-T1/.../T8 | `quick / []` | CI + 多路 smoke 全过 |

Commit 模板：`[feat] W36: 数字人 / lip-sync Sync Labs 主路径打通`

### Wave 37 — OSS staging fallback + SadTalker 探索（约 4 工作日）

| 任务 ID | 内容 | 依赖 | category + skills | 验证手段 |
| --- | --- | --- | --- | --- |
| **W37-T1** | `integrations/lip_sync/oss_wav2lip.py` 真实实现（独立 sidecar 镜像，仅 staging）；强制 license 注释 + 启动横幅 | W36 全部 in HEAD | `deep / []` | docker compose staging up；e2e 1 镜头 success |
| **W37-T2** | `integrations/lip_sync/sadtalker.py` 探索分支（feature flag `ENABLE_SADTALKER_EXPERIMENTAL=false`）；仅虚拟主持场景启用 | W37-T1 | `deep / []` | unit 4 cases；标记为 `pytest.mark.experimental` |
| **W37-T3** | CI sanity check：production manifest grep `wav2lip_oss` / `sadtalker` 必须为 0；helm chart 显式排除两个镜像 | W37-T2 | `quick / []` | CI job 绿 |
| **W37-T4** | `site/content/docs/architecture/digital-human.md`：当前生效 = Sync Labs 主 + OSS staging + SadTalker 实验；与本调研报告交叉引用 | W37-T1/T2 | `writing / []` | hugo build 绿 |

Commit 模板：`[feat] W37: 数字人 OSS staging + SadTalker 实验通道`

### Wave 38 — Release v0.8.0（约 1 工作日）

| 任务 ID | 内容 | 依赖 | category + skills | 验证手段 |
| --- | --- | --- | --- | --- |
| **W38-T1** | `site/content/blog/v0-8-0.md` 17 章节模板（同 v0.7.0 风格）；`Highlights` 突出 lip-sync；`Breaking Changes` 标注 `face_consent_status` 字段为强制；`Migration Guide` 给出 `JWT_FALLBACK_TO_STATIC` 默认关闭 + `LIP_SYNC_PROVIDER` 配置示例 | W35–W37 全在 HEAD | `writing / []` | hugo build 绿 + 17 章节齐全 |

Commit 模板：`[docs] W38-T1: site/content/blog/v0-8-0.md release note (P5+ 数字人整合)`

### Wave 35+ 关键架构决策（待落地确认）

| ID | 决定 |
| --- | --- |
| D-DH-1 | provider 抽象走 Protocol + factory，不开多态继承；env `LIP_SYNC_PROVIDER` strict enum，缺省 panic exit |
| D-DH-2 | `lip_sync_provider_jobs` 单独建表，不复用通用 `tasks` 表；专用 polling worker 避免任务系统污染 |
| D-DH-3 | `face_consent_status` 加在 `EntityImage` 而非 `Entity`：portrait 是图像级别的授权，不同图可能授权不同 |
| D-DH-4 | `requires_lip_sync` 加在 `chapter_timeline_segment` 字段而非镜头属性：lip-sync 是 export 时段决策，与编辑期镜头状态正交 |
| D-DH-5 | duration_align_strategy 默认 `pad_silence`：保守方案，绝不 stretch 视频（破坏 r2v 节奏） |
| D-DH-6 | OSS Wav2Lip 仅 staging；生产硬约束 Sync Labs；CI grep + helm 双重防漏 |
| D-DH-7 | SadTalker 走 `ENABLE_SADTALKER_EXPERIMENTAL=false` flag；不进 prod 主路径，仅纯虚拟主持子场景实验 |
| D-DH-8 | 中文 SyncNet score < 5.0 占比 > 15% 触发 review，不自动 block；upgrade path 留给 Wave 39+ 中文 fine-tune |

### Wave 35+ 风险登记

- **R-W35+-1**：Sync Labs 谈判超 8 周未签约 → 切 SadTalker 主路径（次选自动顶上），W36 实现切换约 3 工作日延期；
- **R-W35+-2**：mediapipe face mesh 在 sidecar 部署体积过大 → 切到 ultralytics yolov8-face（轻量替代），face ROI 检测精度差异 < 5%；
- **R-W35+-3**：Sync Labs 上行带宽不稳定 → 加 OSS object store 中转（S3 presigned URL），避免直连大文件上传；
- **R-W35+-4**：W37 OSS sidecar 镜像意外被生产 helm chart 引用 → CI grep 漏掉时由 W38 release 前 manual review 兜底，写入 release checklist；
- **R-W35+-5**：`face_consent_status` 字段加上后存量 `EntityImage` 默认 `unset`，导致老用户已上传 portrait 无法启用 lip-sync → 加一条 backfill 指南到 `Migration Guide`，提示用户在 Studio "我的资产"页批量勾选；
- **R-W35+-6**：长章节（>50 镜头）lip-sync 全开后 `chapter_av_export` 超 SLA 阈值 → 默认 lip-sync opt-in 关闭，必须用户手动勾选每个镜头；
- **R-W35+-7**：D10 决策保留至 P5+ 后，部分用户已习惯 keep_native + ASR，迁移到 lip-sync 后 ASR 不再适用，字幕回归手工编辑 → 在前端工作室明确提示"启用 lip-sync 时字幕来源切换为 TTS 文本输入"。

### Wave 35+ 完成标准

- [ ] Sync Labs 商业版 EULA 已签 + license token in vault
- [ ] `face_consent_status` 字段已上 + 老数据 backfill 指南已发
- [ ] alembic head=0023 + forward + downgrade clean
- [ ] `chapter_av_planner` `requires_lip_sync` + `lip_sync_capability` 预检 e2e fixture 通过
- [ ] 50 镜头中文 fixture SyncNet score < 5.0 占比 < 15%
- [ ] `chapter_av_export` `voice_bgm` / `full` 两种音频混合模式与 lip-sync 共存 e2e 通过
- [ ] CI grep + helm 双重防漏 OSS Wav2Lip 引用
- [ ] `digital-human.md` architecture page 上线，与本调研报告交叉引用
- [ ] `v0-8-0.md` 17 章节齐全 + frontmatter 完整
- [ ] `pylint backend ≥ 9.5` + `pytest -q` 全绿（除 pre-existing skip / xfail）+ `pnpm exec tsc --noEmit` + `pnpm run build` + `pnpm run openapi:update` zero diff
- [ ] `backend/scripts/p3_e2e_smoke.py` + `lip_sync_chinese_eval.py` 双绿

### Wave 35+ 任务依赖图（ASCII 简版）

```text
W34 release v0.7.0 (HEAD)
   │
   ├─► W35 Foundation        (T1 → T2 → T3 → T4 → T5)
   │
   ├─► W36 Sync Labs 主路径   (T1 → T2 → T3 → T4 → T5 → T6 → T7)
   │                          (T8 并行 T5 之后；T9 verify 全部之后)
   │
   ├─► W37 OSS + SadTalker   (T1 → T2 → T3 → T4)
   │
   └─► W38 Release v0.8.0    (T1，等 W35–W37 全 in HEAD)
```

### Wave 35+ alembic 迁移链

P5 末尾 head = `0021_p5_users_rbac`。Wave 35+ 在此之后串两个独立 migration：

| 版本 | wave | 内容 |
| --- | --- | --- |
| `0022_p5plus_face_consent.py` | W35 | `entity_images` 加 `face_consent_status SAEnum unset/self_declared/signed_doc DEFAULT unset NOT NULL` |
| `0023_p5plus_lip_sync_jobs.py` | W36 | 新建 `lip_sync_provider_jobs` 表（id BIGINT / external_job_id VARCHAR / status SAEnum pending/running/done/failed / cost_cents INT / submitted_at / completed_at / shot_id BIGINT FK shots(id) ON DELETE CASCADE） |

每个 migration `downgrade()` 必须实测可执行，不允许写死的不可逆 DDL。

---

## 6. 跨阶段决定（保持稳定）

- **D10 不变**：默认主流程仍是 `silent_with_tts` + `keep_native` + ASR；
  lip-sync 是 opt-in 子路径，不替代默认链路。
- **不引入 D-ID**：调研已结论；写入未来 tech-radar 时归类为"已评估，不引入"。
- **OSS Wav2Lip 永不进 prod**：license 边界硬约束，CI + helm 双重防漏。
- **SadTalker 仅作次选**：留给纯虚拟主持子场景，不进入剧情带货主路径。
- **数字人 path 与 chapter_av_export 强耦合**：lip-sync 是 export 阶段后处理，
  不影响编辑页 / 工作室的"准备 / 生成"职责边界（编辑页继续准备，工作室继续生成，
  数字人开关在工作室 export 时勾选）。

## 7. 调研引用（来源汇总）

- SadTalker GitHub README / Issue #118 / #293 / #583 / #625 / #650 / #868 / #890 / LICENSE
- SadTalker on Replicate (`cjwbw/sadtalker`) 模型卡片
- D-ID 官网 `pricing/api/` / `pricing/studio/`
- D-ID 第三方评测：heyfish.ai / tekpon / tavus / g2.com / shotstack
- Wav2Lip GitHub README / Issue #104 / #623 / inference.py
- Wav2Lip 中文社区评测：lipsync.com 综述 / argil.ai 综述
- Sync Labs 官方介绍（synclabs.so，由 Wav2Lip GitHub README 链接进入）

> 本调研引用的均为 2024–2025 年公开材料；价格 / SLA / license 条款随时可能变更，
> 实装阶段（Wave 35+）启动时必须重新核验最新条款。
