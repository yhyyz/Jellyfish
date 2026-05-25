-- W2-T5: 创建剧情带货商品资产相关 4 张表（products / product_images / project_product_links / commerce_story_configs）
-- 全部使用 CREATE TABLE IF NOT EXISTS，幂等执行；列类型与 SQLAlchemy 模型逐字段对齐。

CREATE TABLE IF NOT EXISTS `products` (
  `id` VARCHAR(64) NOT NULL COMMENT '商品唯一标识',
  `name` VARCHAR(255) NOT NULL COMMENT '商品名称',
  `brand` VARCHAR(128) NOT NULL DEFAULT '' COMMENT '品牌',
  `category` VARCHAR(32) NOT NULL DEFAULT 'other' COMMENT '商品分类（电子/美妆/食品/服饰/家居/健康/其他）',
  `description` TEXT NOT NULL COMMENT '商品描述/卖点摘要',
  `price_anchor` DOUBLE NULL COMMENT '锚定价（人民币）',
  `sku` VARCHAR(64) NULL COMMENT 'SKU / 货号',
  `selling_points` JSON NOT NULL COMMENT '卖点列表（JSON 数组，建议 ≤5）',
  `pain_points_solved` JSON NOT NULL COMMENT '解决的痛点（JSON 数组）',
  `target_audience` JSON NOT NULL COMMENT '目标受众 JSON',
  `catchphrases` JSON NOT NULL COMMENT '金句台词列表',
  `competitor_names` JSON NOT NULL COMMENT '禁止提及的竞品名列表',
  `health_disclaimer_required` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否需要健康类免责声明',
  `visual_style` VARCHAR(16) NOT NULL DEFAULT '现实' COMMENT '视觉风格',
  `style` VARCHAR(32) NOT NULL DEFAULT '真人都市' COMMENT '题材风格',
  `prompt_template_id` VARCHAR(64) NULL COMMENT '关联提示词模板 ID',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_products_name` (`name`),
  KEY `ix_products_name` (`name`),
  KEY `ix_products_category` (`category`),
  KEY `ix_products_prompt_template_id` (`prompt_template_id`),
  CONSTRAINT `fk_products_prompt_template`
    FOREIGN KEY (`prompt_template_id`) REFERENCES `prompt_templates` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='剧情带货商品主体表（D1：name 全库唯一）';

CREATE TABLE IF NOT EXISTS `product_images` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `product_id` VARCHAR(64) NOT NULL COMMENT '所属商品 ID',
  `file_id` VARCHAR(64) NULL COMMENT '关联文件 ID',
  `quality_level` VARCHAR(16) NOT NULL DEFAULT 'LOW' COMMENT '质量等级（LOW/MEDIUM/HIGH/ULTRA）',
  `view_angle` VARCHAR(32) NOT NULL DEFAULT 'FRONT' COMMENT '视角（FRONT/LEFT/RIGHT/...）',
  `is_primary` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否主图',
  `width` INT NULL COMMENT '宽（像素）',
  `height` INT NULL COMMENT '高（像素）',
  `fmt` VARCHAR(16) NULL COMMENT '格式',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_product_images_quality_angle` (`product_id`, `quality_level`, `view_angle`),
  KEY `ix_product_images_product_id` (`product_id`),
  KEY `ix_product_images_file_id` (`file_id`),
  KEY `ix_product_images_quality_level` (`quality_level`),
  KEY `ix_product_images_view_angle` (`view_angle`),
  CONSTRAINT `fk_product_images_product`
    FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_product_images_file`
    FOREIGN KEY (`file_id`) REFERENCES `files` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='商品多角度图片';

CREATE TABLE IF NOT EXISTS `project_product_links` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `project_id` VARCHAR(64) NOT NULL COMMENT '项目 ID',
  `chapter_id` VARCHAR(64) NULL COMMENT '章节 ID',
  `shot_id` VARCHAR(64) NULL COMMENT '镜头 ID',
  `product_id` VARCHAR(64) NOT NULL COMMENT '商品 ID',
  `role_in_story` VARCHAR(32) NOT NULL DEFAULT 'savior' COMMENT '商品在剧情中的角色',
  `appearance_timing` VARCHAR(16) NOT NULL DEFAULT 'middle' COMMENT '出现时机',
  `appearance_duration_sec` INT NOT NULL DEFAULT 5 COMMENT '出现时长（秒）',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_project_product_links_scope` (`product_id`, `project_id`, `chapter_id`, `shot_id`),
  KEY `ix_project_product_links_project_id` (`project_id`),
  KEY `ix_project_product_links_chapter_id` (`chapter_id`),
  KEY `ix_project_product_links_shot_id` (`shot_id`),
  KEY `ix_project_product_links_product_id` (`product_id`),
  CONSTRAINT `fk_ppl_project`
    FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_ppl_chapter`
    FOREIGN KEY (`chapter_id`) REFERENCES `chapters` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_ppl_shot`
    FOREIGN KEY (`shot_id`) REFERENCES `shots` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_ppl_product`
    FOREIGN KEY (`product_id`) REFERENCES `products` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='项目-商品多对多关联（可挂在 project/chapter/shot 任一层）';

CREATE TABLE IF NOT EXISTS `commerce_story_configs` (
  `project_id` VARCHAR(64) NOT NULL COMMENT '项目 ID（PK，1:1）',
  `target_platform` VARCHAR(32) NOT NULL DEFAULT 'douyin' COMMENT '目标平台',
  `target_duration_sec` INT NOT NULL DEFAULT 60 COMMENT '目标时长（秒）',
  `formula_id` VARCHAR(64) NULL COMMENT '选定的剧情公式 ID',
  `archetype` VARCHAR(32) NULL COMMENT '品牌人格 archetype',
  `tone_grid` JSON NOT NULL COMMENT '语调维度 JSON',
  `audience_override` JSON NULL COMMENT '覆盖商品默认受众的项目级配置',
  `compliance_region` VARCHAR(16) NOT NULL DEFAULT 'cn_mainland' COMMENT '合规地域',
  `compliance_profile_id` VARCHAR(64) NOT NULL DEFAULT 'cn_mainland_default' COMMENT '合规规则集 ID',
  `target_kpi` VARCHAR(32) NULL COMMENT '目标 KPI: awareness/clicks/conversion',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`project_id`),
  KEY `ix_commerce_story_configs_formula_id` (`formula_id`),
  CONSTRAINT `fk_csc_project`
    FOREIGN KEY (`project_id`) REFERENCES `projects` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='剧情带货项目专属配置（与 Project 1:1）';
