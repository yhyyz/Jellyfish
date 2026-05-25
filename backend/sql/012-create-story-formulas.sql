-- W2-T5: 创建剧情公式相关 3 张表（story_formulas / story_variants / story_outcomes）
-- 全部使用 CREATE TABLE IF NOT EXISTS，幂等执行；列类型与 SQLAlchemy 模型逐字段对齐。
-- 注意：story_outcomes.plays 使用 BIGINT，避免爆款短视频播放量超过 2^31。

CREATE TABLE IF NOT EXISTS `story_formulas` (
  `id` VARCHAR(64) NOT NULL COMMENT '公式 ID（如 underdog_triumph）',
  `name` VARCHAR(255) NOT NULL COMMENT '中文名称',
  `region` VARCHAR(16) NOT NULL DEFAULT 'cn' COMMENT '适用地域：cn / global',
  `category` VARCHAR(64) NOT NULL DEFAULT 'cn_viral' COMMENT '分类标签',
  `structure` JSON NOT NULL COMMENT '完整 beat 结构 JSON',
  `risk_flags` JSON NOT NULL COMMENT '风险标记数组',
  `sample_dialog` TEXT NOT NULL COMMENT '完整示例剧本',
  `typical_duration_sec` INT NOT NULL DEFAULT 60 COMMENT '典型时长（秒）',
  `typical_shot_count` INT NOT NULL DEFAULT 4 COMMENT '典型镜头数',
  `psychology` TEXT NOT NULL COMMENT '心理学原理',
  `use_cases` JSON NOT NULL COMMENT '适用场景',
  `avoid_cases` JSON NOT NULL COMMENT '禁忌场景',
  `prompt_template_id` VARCHAR(64) NOT NULL COMMENT '绑定的提示词模板',
  `is_system` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '系统模板，不可删除',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT 'UI 显示排序',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_story_formulas_region` (`region`),
  KEY `ix_story_formulas_category` (`category`),
  KEY `ix_story_formulas_prompt_template_id` (`prompt_template_id`),
  KEY `ix_story_formulas_sort_order` (`sort_order`),
  KEY `ix_story_formulas_region_category` (`region`, `category`),
  CONSTRAINT `fk_story_formulas_prompt_template`
    FOREIGN KEY (`prompt_template_id`) REFERENCES `prompt_templates` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='剧情公式注册表（系统级）';

CREATE TABLE IF NOT EXISTS `story_variants` (
  `id` VARCHAR(64) NOT NULL COMMENT '变体唯一 ID',
  `project_id` VARCHAR(64) NOT NULL COMMENT '所属项目',
  `chapter_id` VARCHAR(64) NOT NULL COMMENT '所属章节',
  `formula_id` VARCHAR(64) NOT NULL COMMENT '使用的剧情公式',
  `hook_pattern_id` VARCHAR(64) NULL COMMENT '钩子模式 ID（P2）',
  `cta_pattern_id` VARCHAR(64) NULL COMMENT 'CTA 模式 ID（P2）',
  `archetype` VARCHAR(32) NULL COMMENT '品牌人格（P2）',
  `script_full_text` TEXT NOT NULL COMMENT '完整剧本文本',
  `script_breakdown` JSON NOT NULL COMMENT '镜头分解结果 JSON',
  `status` VARCHAR(16) NOT NULL DEFAULT 'draft' COMMENT '状态：draft / generating / ready / failed',
  `is_champion` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否冠军变体（P2）',
  `compliance_score` INT NOT NULL DEFAULT 0 COMMENT '合规评分 0-100',
  `generated_by_task_id` VARCHAR(64) NULL COMMENT '生成此变体的 GenerationTask ID',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_story_variants_project_id` (`project_id`),
  KEY `ix_story_variants_chapter_id` (`chapter_id`),
  KEY `ix_story_variants_formula_id` (`formula_id`),
  KEY `ix_story_variants_hook_pattern_id` (`hook_pattern_id`),
  KEY `ix_story_variants_cta_pattern_id` (`cta_pattern_id`),
  KEY `ix_story_variants_status` (`status`),
  KEY `ix_story_variants_generated_by_task_id` (`generated_by_task_id`),
  CONSTRAINT `fk_story_variants_project`
    FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_story_variants_chapter`
    FOREIGN KEY (`chapter_id`) REFERENCES `chapters` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_story_variants_formula`
    FOREIGN KEY (`formula_id`) REFERENCES `story_formulas` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脚本变体（A/B 测试单元）';

CREATE TABLE IF NOT EXISTS `story_outcomes` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `variant_id` VARCHAR(64) NOT NULL COMMENT '关联变体',
  `platform` VARCHAR(32) NOT NULL DEFAULT 'douyin' COMMENT '投放平台',
  `plays` BIGINT NOT NULL DEFAULT 0 COMMENT '播放量（BIGINT，避免爆款超 2^31）',
  `completion_rate_3s` DOUBLE NULL COMMENT '3 秒完播率（0~1）',
  `completion_rate_full` DOUBLE NULL COMMENT '完整完播率（0~1）',
  `interactions` INT NOT NULL DEFAULT 0 COMMENT '互动量（点赞+评论+分享）',
  `cart_clicks` INT NOT NULL DEFAULT 0 COMMENT '加购点击',
  `orders` INT NOT NULL DEFAULT 0 COMMENT '订单数',
  `gmv` DOUBLE NOT NULL DEFAULT 0 COMMENT 'GMV（人民币）',
  `notes` TEXT NOT NULL COMMENT '备注',
  `raw_payload` JSON NOT NULL COMMENT '平台原始数据 JSON',
  `recorded_at` DATETIME(6) NOT NULL COMMENT '数据记录时点',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_story_outcomes_variant_id` (`variant_id`),
  KEY `ix_story_outcomes_platform` (`platform`),
  CONSTRAINT `fk_story_outcomes_variant`
    FOREIGN KEY (`variant_id`) REFERENCES `story_variants` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='脚本变体的真实投放效果数据';
