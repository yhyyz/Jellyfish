# Frontend Integration Learnings — Jellyfish (front/)

Captured: 2026-05-25
Goal: support "story-driven product placement" feature on front/.

## Routing
- Single root: `front/src/App.tsx` (BrowserRouter, all pages under `MainLayout`)
- Nested layout: `<Route path="/" element={<MainLayout />}>` with `<Outlet/>`
- Pattern: import small/critical pages eagerly; `lazy(() => import(...))` + `<Suspense fallback={<PageSkeleton />}>` for heavy ones.
- Adding new page = (1) add `lazy()` import in App.tsx, (2) add `<Route path=... element=...>`, (3) add menu entry in `MainLayout.tsx` (`menuItems`, `selectedKeys`, `pathLabels` for breadcrumb).

## Navigation
- File: `front/src/layouts/MainLayout.tsx`
- AntD Sider+Header layout. Menu items hard-coded in array; no plugin registry.
- Breadcrumb auto-derived from `location.pathname` via `pathLabels` map — must extend when adding routes.
- Language switcher uses Zustand `useAppStore.language` + i18next `i18n.changeLanguage`.
- Inside layout: `TaskRuntimeProvider` wraps `<Content><Outlet/></Content>` and renders global `<TaskCenter/>`.

## Page patterns
- "List + create/edit modal" canonical example = `aiStudio/assets/tabs/ActorsTab.tsx`:
  - `useState` for list/loading/page/search
  - direct fetch via thin wrapper `services/studioEntities.ts` (NOT TanStack Query in this case)
  - `Card title=... extra={<Search + Refresh + 新建>}` header
  - `DisplayImageCard` grid + `<Pagination/>` + `Empty`
  - `Modal.confirm({...})` for destructive ops
  - Form modal as sibling component (e.g. `ActorEntityFormModal`)
- TanStack Query example = `aiStudio/project/queries.ts` + `ProjectLobby.tsx`:
  - `projectKeys` factory (`all`, `list`, `detail(id)`)
  - `useQuery({ queryKey, queryFn })` reads from generated services
  - `useMutation({ mutationFn, onSuccess: invalidateQueries })`
- Tabbed config page = `aiStudio/models/ModelManagement.tsx` (simple `useState<string>('providers')` driven Tabs).
- Tabbed CRUD page with URL sync = `aiStudio/assets/AssetManager.tsx` (uses `useSearchParams` to keep `?tab=...`).

## Form patterns (AntD Form)
- `const [form] = Form.useForm()` per modal; separate `form` and `editForm` instances for create vs edit.
- `<Form layout="vertical" onFinish={handleSubmit} initialValues={...}>`.
- Validation via `rules={[{ required: true, message: '...' }]}` on `Form.Item`.
- Submit errors → AntD `message.error('...')`; success → `message.success('...')`.
- `notification` is NOT used in main flows; `message` is the convention.
- Confirm dialogs: `<Popconfirm ...>` inline or `Modal.confirm({...})` imperatively.
- Some modals (StudioAssetTypeFormModal) skip `Form` and use plain `useState` per field — both styles exist.

## State management
- Global = Zustand. Single store at `front/src/store/useAppStore.ts` (siderCollapsed, user, language).
- Server state = TanStack Query. Provider at `main.tsx`; default config `staleTime=30s, refetchOnWindowFocus=false, retry=1` in `queryClient.ts`.
- Devtools enabled (`<ReactQueryDevtools/>`).
- Generated client at `services/generated/` (openapi-typescript-codegen). Initialized in `services/openapi.ts`. Use the Service classes (e.g. `StudioProjectsService.xxx({ ... })`); they return `CancelablePromise<ApiResponse_X_>` and you read `res.data`.
- Some thin wrappers exist (`services/studioEntities.ts`, `services/aiStudioApi.ts`, `services/filmTaskLinks.ts`) — preferred when same generated method is called from many places with shared defaults.
- Mock support via MSW gated by `import.meta.env.VITE_USE_MOCK === 'true'` (see `mocks/`).

## Components inventory
Top-level shared (`front/src/components/`):
- `PageSkeleton` — Spin centered fallback for `<Suspense>`.
- `CustomCard`, `CustomButton` — Tailwind-only legacy primitives, rarely used by the new pages (most pages use AntD directly).

aiStudio shared (`front/src/pages/aiStudio/components/`):
- `ScrollablePage` — `h-full min-h-0 overflow-y-auto` wrapper used by tabbed manager pages.
- `TaskCenter` / `TaskRuntimeProvider` — global async task tracking UI; do not duplicate in feature pages.
- `taskActionHelpers`, `taskCenterMeta`, `taskCopy`, `taskNotificationHelpers`, `taskPageContext`, `taskResultHelpers`, `taskUiStore` — task system glue.

Feature-local reusable components (worth importing):
- `pages/aiStudio/assets/components/DisplayImageCard.tsx` — image+title+meta+actions card with built-in preview Modal.
- `pages/aiStudio/assets/components/StudioAssetTypeFormModal.tsx` — generic asset CRUD modal pattern (for scene/prop/costume).
- `pages/aiStudio/assets/components/ActorEntityFormModal.tsx` — actor-specific variant (referenced from ActorsTab).
- `pages/aiStudio/assets/components/AssetEditPageBase.tsx` — full-page asset editor scaffold.
- `pages/aiStudio/project/ProjectVisualStyleAndStyleFields.tsx` — paired visual_style / style fields.
- `pages/aiStudio/project/useProjectStyleOptions.ts` — hook returning style option lists.

## i18n
- Loader: `front/src/i18n.ts`, namespaces: `common`, `layout`, `settings`, `notFound`. Default NS = `layout`.
- Locales: `front/src/locales/{zh-CN,en-US}/{common,layout,settings,notFound}.json`.
- Adoption is partial: many pages use hard-coded Chinese strings (e.g. ProjectLobby, AssetManager, all asset tabs). Only layout/settings/notFound are translated.
- Pattern to add a new namespace: create `xxx.json` in both `zh-CN/` and `en-US/`, import in `i18n.ts`, add to `resources` and `ns` array; in component `const { t } = useTranslation('xxx')`.
- Language is persisted in localStorage key `jellyfish_language`; antd's `ConfigProvider` locale switches via `useAppStore.language` in `main.tsx`.

## Recipe: add a new feature page (e.g. story-product-placement)
1. Create `front/src/pages/aiStudio/<feature>/<FeaturePage>.tsx` (default export).
2. (optional) `front/src/pages/aiStudio/<feature>/queries.ts` with `xxxKeys` factory + `useXxxList/useCreateXxx/useUpdateXxx/useDeleteXxx`.
3. Register route in `App.tsx` with `lazy + Suspense + PageSkeleton`.
4. Add side-menu entry + breadcrumb label in `MainLayout.tsx`.
5. If new backend endpoints: backend → `pnpm run openapi:update` from `front/` → use generated `XxxService` directly or wrap in `front/src/services/<feature>.ts`.
6. For list-and-modal CRUD, copy `ActorsTab.tsx` shape; for tab manager, copy `AssetManager.tsx`; for tabbed config, copy `ModelManagement.tsx`; for grid+sidebar lobby, copy `ProjectLobby.tsx`.

## Conventions / gotchas
- AGENTS.md: front must call OpenAPI generated client; do not add hand-written service wrappers unless they serve as shared helpers.
- After backend API change: run `pnpm run openapi:update` in `front/`.
- Page state separation per AGENTS.md: editing/preparation pages = "prepare"; studio pages = "generate"; task center = thin status panel.
- `shot.status` ∈ `{pending, ready}` only; runtime "generating" comes from task system + `video-readiness`. Mirror these semantics for new placement entities if they also have ready/generating states.
