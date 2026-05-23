# Learnings

## 2026-05-23 Initial Analysis

### Backend Patterns
- FastAPI + Pydantic v2 + SQLAlchemy 2.0 async
- Services are stateless functions taking `db: AsyncSession`
- Task system: dual-layer (core/task_manager + services/worker)
- Celery with Redis broker, results in MySQL
- 13 registered task kinds
- Provider abstraction: openai / volcengine / aliyun_bailian

### Frontend Patterns
- React 18 + Vite 5 + TypeScript strict
- Ant Design (primary UI) + Tailwind (utility)
- Zustand for global state (minimal usage)
- OpenAPI generated client (fetch-based)
- No data caching layer (raw useEffect)
- No frontend tests

### Infrastructure
- Docker Compose: mysql + redis + rustfs + backend + celery + front
- Manual SQL migrations (no Alembic)
- Hugo docs site (Hextra theme)
- CI: GHCR images, pylint, site deploy (no frontend CI)

### Key Code Smells
- ChapterStudio.tsx: 6537 lines, 24 `any` types
- script_processing.py: 1041 lines god-route
- Dead code: aiStudioApi.ts, http.ts, axios dep
- openapi-typescript-codegen: unmaintained (2023)
- react-beautiful-dnd: deprecated
