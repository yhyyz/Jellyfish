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
- **openapi-typescript-codegen (0.30.0) deprecated since 2023** — pinned at last release. Migration to `@hey-api/openapi-ts` evaluated and deferred because:
  - New tool generates fundamentally different output structure (flat `sdk.gen.ts` + `types.gen.ts` vs `services/` + `models/` directories)
  - Class names differ (`Health` vs `HealthService`, `Film` vs `FilmService`)
  - Method signatures incompatible (new: `options: Options<T>` object; old: destructured named params)
  - No `CancelablePromise`, `OpenAPI`, `ApiError` core exports in new tool
  - Would require rewriting all 17 service class imports + every API call site (100+ files)
  - **Future path**: When doing a major frontend refactor, migrate to `@hey-api/openapi-ts` with its new function-based SDK pattern (no classes), updating all call sites at once
