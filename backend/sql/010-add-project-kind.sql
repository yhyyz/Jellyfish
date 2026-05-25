-- W2-T5: 添加 projects.kind 列 + ix_projects_kind 索引（MySQL 5.7+/8.x 兼容，幂等执行）

SET @has_projects_kind = (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND COLUMN_NAME = 'kind'
);

SET @add_projects_kind = IF(
  @has_projects_kind = 0,
  "ALTER TABLE `projects` ADD COLUMN `kind` VARCHAR(32) NOT NULL DEFAULT 'drama' COMMENT '项目类型：drama=短剧；commerce_story=剧情带货'",
  'SELECT 1'
);
PREPARE stmt_add_projects_kind FROM @add_projects_kind;
EXECUTE stmt_add_projects_kind;
DEALLOCATE PREPARE stmt_add_projects_kind;

-- 兜底：旧库新增列后可能存在 NULL，统一回填为 drama
UPDATE `projects` SET `kind` = 'drama' WHERE `kind` IS NULL;

SET @has_ix_projects_kind = (
  SELECT COUNT(*)
  FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'projects'
    AND INDEX_NAME = 'ix_projects_kind'
);

SET @create_ix_projects_kind = IF(
  @has_ix_projects_kind = 0,
  'CREATE INDEX ix_projects_kind ON `projects` (`kind`)',
  'SELECT 1'
);
PREPARE stmt_ix_projects_kind FROM @create_ix_projects_kind;
EXECUTE stmt_ix_projects_kind;
DEALLOCATE PREPARE stmt_ix_projects_kind;
