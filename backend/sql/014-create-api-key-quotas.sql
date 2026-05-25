-- W2-T5: 创建 api_key_quotas 表（P3 启用 partner API 时使用，P1 仅建表预留）
-- 主键直接采用 api_key_hash（API key 的 bcrypt 哈希），避免持久化明文 key。

CREATE TABLE IF NOT EXISTS `api_key_quotas` (
  `api_key_hash` VARCHAR(128) NOT NULL COMMENT 'API key 的 bcrypt 哈希（PK）',
  `daily_limit` INT NOT NULL DEFAULT 1000 COMMENT '日调用上限',
  `monthly_limit` INT NOT NULL DEFAULT 30000 COMMENT '月调用上限',
  `rate_per_minute` INT NOT NULL DEFAULT 60 COMMENT '每分钟请求数上限',
  `consumed_today` INT NOT NULL DEFAULT 0 COMMENT '今日已消耗',
  `consumed_this_month` INT NOT NULL DEFAULT 0 COMMENT '本月已消耗',
  `last_reset_daily` DATE NOT NULL COMMENT '上次日重置日期',
  `last_reset_monthly` DATE NOT NULL COMMENT '上次月重置日期',
  `description` VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'key 用途备注',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否启用',
  `created_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) COMMENT '创建时间',
  `updated_at` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6) COMMENT '更新时间',
  PRIMARY KEY (`api_key_hash`),
  KEY `ix_api_key_quotas_is_active` (`is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API key 配额记录（P3 启用 partner API 时使用，P1 仅建表预留）';
