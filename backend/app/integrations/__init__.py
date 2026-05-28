"""第三方 / 外部服务 integration 子包根。

为什么独立成 ``app/integrations``：
    本目录下的模块只承担"调用外部协议（HTTP webhook、SMTP）"这一职责，
    不依赖业务模型、不持有领域状态。把它从 :mod:`app.services` 中拆出
    来，便于：

    - 单测时直接 mock integration 函数而非整条 service 链路；
    - 后续新增 Telegram / 飞书 / 钉钉等渠道时不再污染 service 层。

当前子包：
    - :mod:`notifications`：合规告警 Slack / email 投递。
"""
