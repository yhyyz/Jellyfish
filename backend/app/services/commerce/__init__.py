"""剧情带货（Story-Driven Commerce）业务服务包。

P1 阶段聚焦：
- 系统级 ``StoryFormula`` 种子数据加载（``builtin_story_formulas`` 模块）。

后续 P2/P3 会在此包内继续扩展：
- 钩子模式库 / CTA 模式库 / 品牌人格档案
- 商品提取 / 合规检查的 service 编排（保持 ``api`` 与 ``service`` 分层，
  仅做业务逻辑，不在此处声明跨层 DTO，跨层契约统一收敛在
  ``app/core/contracts``）。
"""
