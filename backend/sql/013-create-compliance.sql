-- W2-T5: 创建合规管理相关 2 张表（compliance_profiles / compliance_findings）
-- 全部使用 CREATE TABLE IF NOT EXISTS，幂等执行；列类型与 SQLAlchemy 模型逐字段对齐。
-- 注意：联合索引 ix_compliance_findings_variant_severity 用于按变体快速过滤 blocker。

CREATE TABLE IF NOT EXISTS `compliance_profiles` (
  `id` VARCHAR(64) NOT NULL COMMENT 'profile ID',
  `name` VARCHAR(255) NOT NULL COMMENT '显示名称',
  `region` VARCHAR(16) NOT NULL DEFAULT 'cn_mainland' COMMENT '适用地域',
  `rules` JSON NOT NULL COMMENT '规则数组 JSON',
  `is_system` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '系统预置',
  `description` TEXT NOT NULL COMMENT 'profile 用途说明',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_compliance_profiles_region` (`region`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合规规则集（按地域+品类分组）';

CREATE TABLE IF NOT EXISTS `compliance_findings` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `variant_id` VARCHAR(64) NOT NULL COMMENT '所属脚本变体',
  `severity` VARCHAR(16) NOT NULL DEFAULT 'warning' COMMENT '严重度',
  `rule_id` VARCHAR(64) NOT NULL COMMENT '触发的规则 ID',
  `rule_kind` VARCHAR(32) NOT NULL DEFAULT 'banned_phrase' COMMENT '规则类型',
  `description` TEXT NOT NULL COMMENT '问题描述',
  `location` VARCHAR(255) NULL COMMENT '脚本中位置',
  `suggested_fix` TEXT NULL COMMENT '建议修复方案',
  `is_resolved` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否已解决',
  `detected_at` DATETIME(6) NOT NULL COMMENT '检测时间',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `ix_compliance_findings_variant_id` (`variant_id`),
  KEY `ix_compliance_findings_severity` (`severity`),
  KEY `ix_compliance_findings_rule_id` (`rule_id`),
  KEY `ix_compliance_findings_is_resolved` (`is_resolved`),
  KEY `ix_compliance_findings_variant_severity` (`variant_id`, `severity`),
  CONSTRAINT `fk_compliance_findings_variant`
    FOREIGN KEY (`variant_id`) REFERENCES `story_variants` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='合规检查产出的具体问题';
