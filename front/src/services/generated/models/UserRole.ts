/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 用户角色枚举（P5 W32-T1 引入，配合 ``users`` 表 ``role`` 列）。
 *
 * 本枚举严格落地决策 D-P5-3：单表 User + 简单 enum，不引入 Role/Permission
 * 多对多表（YAGNI 原则）。后续真要 fine-grained 再扩 ``permissions`` /
 * ``role_permissions`` 关联表，不需要重构 users。
 *
 * 层级语义（守卫工厂 ``require_role`` 默认按精确匹配，不做 admin>member 隐含
 * 放行——隐含放行由 ``require_member = require_role(ADMIN, MEMBER)`` 这类别名
 * 显式声明，避免歧义）：
 *
 * - ``ADMIN``：全功能。包含 ``/settings/api-keys``、``/settings/llm-providers``、
 * ``/admin/notifications``、项目级写操作（如 subtitle styles 覆盖增删改）。
 * - ``MEMBER``：业务功能。可创建项目、编辑分镜、跑生成任务，但触不到 admin
 * 子树。
 * - ``VIEWER``：只读。仅可浏览公开业务端点，不能改写任何业务实体。
 *
 * 序列化约定：因继承 ``str``，在 Pydantic / OpenAPI 中字符串值即 ``"admin"`` /
 * ``"member"`` / ``"viewer"``，DB 列与 JWT 不存放 enum 名而存值字符串。
 * JWT claims 故意不放 role —— 用户被降权后旧 token 必须立刻失效，因此
 * ``get_current_user`` 在每个请求里用 ``session.get`` 查 DB 拿最新 role
 * （identity map O(1)）。
 */
export type UserRole = 'admin' | 'member' | 'viewer';
