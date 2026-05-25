"""共享的 Jinja2 严格环境工厂。

- 为什么存在：本仓库历史上的提示词 SQL seed 直接嵌入 Jinja 片段，但缺少
  统一的渲染策略，导致 “未声明变量被静默替换为空字符串”等隐蔽 bug。
  本模块提供唯一的 ``Environment`` 工厂入口，确保所有调用方都使用同一
  份配置：``StrictUndefined`` 让模板引用未定义变量时立即抛出，配合
  Pydantic ``extra="forbid"`` 的上下文模型形成双向边界校验。
- 做什么：返回一个用于内联模板字符串渲染的 ``Environment`` 对象。
"""

from __future__ import annotations

from jinja2 import BaseLoader, Environment, StrictUndefined, select_autoescape


def make_strict_jinja_env() -> Environment:
    """构造严格模式 Jinja2 环境。

    设计要点：
    - ``undefined=StrictUndefined``：未定义变量立即触发 ``UndefinedError``，
      避免“变量名拼错就静默渲染为空”的隐性问题。
    - ``loader=BaseLoader()``：模板内容由调用方以字符串方式持有（数据库
      存储），无需文件系统加载器；保留一个空 loader 以满足 Jinja2 API。
    - ``autoescape``：仅对 HTML/XML 等显式扩展启用自动转义，使纯文本
      提示词（``.txt`` / ``.md``）保持原样输出。
    - ``keep_trailing_newline=True``：与历史 SQL seed 中的换行约定保持
      一致，便于与人工编辑的多行模板做字符串比较 / 快照测试。

    Returns:
        预配置好的 ``jinja2.Environment`` 实例。
    """

    return Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        autoescape=select_autoescape(disabled_extensions=("txt", "md")),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
    )


__all__ = ["make_strict_jinja_env"]
