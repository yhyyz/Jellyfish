# Decisions

## 2026-05-23 Plan Created

### Execution Order Rationale
- P0-3 first: lowest risk, cleanest win, unblocks P0-1
- P0-1 before P0-2: TanStack Query easier to add after component split
- P1-2 (Alembic) before P2-2 (Auth): auth needs user table migration
- P2-4 (Monitoring) before P2-1 (Task unification): need observability during risky refactor
- P3-2 (Tests) after P0-1: split components are easier to test

### Technology Choices
- TanStack Query over SWR: better mutation support, devtools, wider adoption
- @hey-api/openapi-ts over orval: more active maintenance, closer API to current tool
- @dnd-kit over @hello-pangea/dnd: better TypeScript support, more flexible
- Alembic over manual SQL: industry standard, autogenerate, rollback support
- structlog over loguru: better structured output, production-ready
