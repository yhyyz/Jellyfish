import { lazy, Suspense } from 'react'
import type React from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import Settings from './pages/Settings'
import NotFound from './pages/NotFound'
import ProjectLobby from './pages/aiStudio/project/ProjectLobby'
import ProjectWorkbench from './pages/aiStudio/project/ProjectWorkbench'
import RoleDetailPage from './pages/aiStudio/project/ProjectWorkbench/RoleDetailPage'
import { PageSkeleton } from './components/PageSkeleton'
import { AuthProvider } from './contexts/AuthContext'
import { ProtectedRoute } from './router/ProtectedRoute'
import LoginPage from './pages/auth/LoginPage'
import './App.css'

// 路由级懒加载：大页面拆分为独立 chunk，减小首屏 bundle 体积
const ChapterStudio = lazy(() => import('./pages/aiStudio/chapter/ChapterStudio'))
const AssetManager = lazy(() => import('./pages/aiStudio/assets/AssetManager'))
const ActorAssetEditPage = lazy(() => import('./pages/aiStudio/assets/ActorAssetEditPage'))
const SceneAssetEditPage = lazy(() => import('./pages/aiStudio/assets/SceneAssetEditPage'))
const PropAssetEditPage = lazy(() => import('./pages/aiStudio/assets/PropAssetEditPage'))
const CostumeAssetEditPage = lazy(() => import('./pages/aiStudio/assets/CostumeAssetEditPage'))
const PromptTemplateManager = lazy(() => import('./pages/aiStudio/prompts/PromptTemplateManager'))
const FileManager = lazy(() => import('./pages/aiStudio/files/FileManager'))
const VideoEditor = lazy(() => import('./pages/aiStudio/editor/VideoEditor'))
const AgentManagement = lazy(() => import('./pages/aiStudio/agents/AgentManagement'))
const AgentEdit = lazy(() => import('./pages/aiStudio/agents/AgentEdit'))
const ModelManagement = lazy(() => import('./pages/aiStudio/models/ModelManagement'))
const ChapterShotsPage = lazy(() => import('./pages/aiStudio/shots/ChapterShotsPage').then(m => ({ default: m.ChapterShotsPage })))
const ChapterShotEditPage = lazy(() => import('./pages/aiStudio/shots/ChapterShotEditPage').then(m => ({ default: m.ChapterShotEditPage })))
const ProductLibrary = lazy(() => import('./pages/aiStudio/commerce/products/ProductLibrary'))
const StoryProjectLobby = lazy(() => import('./pages/aiStudio/commerce/projects/StoryProjectLobby'))
const StoryWorkbench = lazy(() => import('./pages/aiStudio/commerce/projects/StoryWorkbench'))
const ComplianceCenter = lazy(() => import('./pages/aiStudio/commerce/compliance/ComplianceCenter'))
const FormulaLibrary = lazy(() => import('./pages/aiStudio/commerce/formulas/FormulaLibrary'))
// W20 Wave C：音色库 / 字幕样式库（剧情带货模块的资源管理页）
const VoicePackLibrary = lazy(() => import('./pages/aiStudio/commerce/voicePacks/VoicePackLibrary'))
const SubtitleStyleLibrary = lazy(() => import('./pages/aiStudio/commerce/subtitleStyles/SubtitleStyleLibrary'))
// W23-T1：多平台导出预设库（P4 Wave A）
const PlatformExportPresetLibrary = lazy(() => import('./pages/aiStudio/commerce/exportPresets/PlatformExportPresetLibrary'))
// W22-T3：A/B 数据归因可视化（P4 Wave B）；含 ant-design/charts 的重 chunk，独立 lazy 加载
const AnalyticsPage = lazy(() => import('./pages/aiStudio/commerce/analytics/AnalyticsPage'))
// W24-T5：API Key admin 管理页（P4 Wave B 7/11）
const ApiKeysPage = lazy(() => import('./pages/settings/ApiKeysPage'))

/** 兼容旧链接 `/projects/:projectId/chapters` → 工作台章节 Tab */
function NavigateToWorkbenchChaptersTab() {
  const { projectId } = useParams<{ projectId: string }>()
  return <Navigate to={`/projects/${projectId}?tab=chapters`} replace />
}

const App: React.FC = () => {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/403"
            element={
              <div style={{ padding: 64, textAlign: 'center' }}>
                <h2>403 - Access Denied</h2>
                <a href="/">Back to home</a>
              </div>
            }
          />
          <Route path="/" element={<MainLayout />}>
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectLobby />} />
            <Route path="projects/:projectId" element={<ProjectWorkbench />} />
            <Route path="projects/:projectId/chapters" element={<NavigateToWorkbenchChaptersTab />} />
            <Route path="projects/:projectId/roles/:characterId/edit" element={<RoleDetailPage />} />
            <Route path="projects/:projectId/chapters/:chapterId/prep/*" element={<Navigate to="../shots" replace />} />
            <Route path="projects/:projectId/chapters/:chapterId/studio" element={<Suspense fallback={<PageSkeleton />}><ChapterStudio /></Suspense>} />
            <Route path="projects/:projectId/chapters/:chapterId/shots/:shotId/edit" element={<Suspense fallback={<PageSkeleton />}><ChapterShotEditPage /></Suspense>} />
            <Route path="projects/:projectId/chapters/:chapterId/shots" element={<Suspense fallback={<PageSkeleton />}><ChapterShotsPage /></Suspense>} />
            <Route path="projects/:projectId/chapters/:chapterId/prep-drafts" element={<Navigate to="../shots" replace />} />
            <Route path="projects/:projectId/chapters/:chapterId/timeline" element={<Suspense fallback={<PageSkeleton />}><VideoEditor /></Suspense>} />
            <Route path="projects/:projectId/editor" element={<Suspense fallback={<PageSkeleton />}><VideoEditor /></Suspense>} />
            <Route path="assets" element={<Suspense fallback={<PageSkeleton />}><AssetManager /></Suspense>} />
            <Route path="assets/actors/:actorImageId/edit" element={<Suspense fallback={<PageSkeleton />}><ActorAssetEditPage /></Suspense>} />
            <Route path="assets/scenes/:sceneId/edit" element={<Suspense fallback={<PageSkeleton />}><SceneAssetEditPage /></Suspense>} />
            <Route path="assets/props/:propId/edit" element={<Suspense fallback={<PageSkeleton />}><PropAssetEditPage /></Suspense>} />
            <Route path="assets/costumes/:costumeId/edit" element={<Suspense fallback={<PageSkeleton />}><CostumeAssetEditPage /></Suspense>} />
            <Route path="prompts" element={<Suspense fallback={<PageSkeleton />}><PromptTemplateManager /></Suspense>} />
            <Route path="files" element={<Suspense fallback={<PageSkeleton />}><FileManager /></Suspense>} />
            <Route path="agents/:id/edit" element={<Suspense fallback={<PageSkeleton />}><AgentEdit /></Suspense>} />
            <Route path="agents" element={<Suspense fallback={<PageSkeleton />}><AgentManagement /></Suspense>} />
            <Route path="models" element={<Suspense fallback={<PageSkeleton />}><ModelManagement /></Suspense>} />
            <Route path="commerce/products" element={<Suspense fallback={<PageSkeleton />}><ProductLibrary /></Suspense>} />
            <Route path="commerce/projects" element={<Suspense fallback={<PageSkeleton />}><StoryProjectLobby /></Suspense>} />
            <Route path="commerce/projects/:projectId" element={<Suspense fallback={<PageSkeleton />}><StoryWorkbench /></Suspense>} />
            <Route path="commerce/compliance" element={<Suspense fallback={<PageSkeleton />}><ComplianceCenter /></Suspense>} />
            <Route path="commerce/formulas" element={<Suspense fallback={<PageSkeleton />}><FormulaLibrary /></Suspense>} />
            <Route path="commerce/voice-packs" element={<Suspense fallback={<PageSkeleton />}><VoicePackLibrary /></Suspense>} />
            <Route path="commerce/subtitle-styles" element={<Suspense fallback={<PageSkeleton />}><SubtitleStyleLibrary /></Suspense>} />
            <Route path="commerce/export-presets" element={<Suspense fallback={<PageSkeleton />}><PlatformExportPresetLibrary /></Suspense>} />
            <Route path="commerce/analytics" element={<Suspense fallback={<PageSkeleton />}><AnalyticsPage /></Suspense>} />
            <Route path="settings" element={<Settings />} />
            <Route
              path="settings/api-keys"
              element={
                <ProtectedRoute requiredRole="admin">
                  <Suspense fallback={<PageSkeleton />}>
                    <ApiKeysPage />
                  </Suspense>
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
