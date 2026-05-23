# Issues

## 2026-05-23 Known Issues

### Blockers
- None currently

### Risks
- P0-1 (ChapterStudio split): May break existing functionality if state flow is misunderstood
- P2-1 (Task unification): Core system, high blast radius
- P1-2 (Alembic): Existing databases need careful baseline stamping

### Technical Debt Tracked
- No auth system (anyone can call any API)
- No rate limiting
- S3 client recreated per call (no pooling)
- Celery enable_utc=False with Asia/Shanghai timezone
- 47 `any` occurrences in frontend (24 in ChapterStudio alone)
- pylint disables 40+ rules
