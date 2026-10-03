import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Overview } from './pages/Overview'
import { SlowQueries } from './pages/SlowQueries'
import { QueryDetails } from './pages/QueryDetails'
import { PlanViewer } from './pages/PlanViewer'
import { GnnAnalysisPage } from './pages/GnnAnalysis'
import { RecommendationsPage } from './pages/Recommendations'
import { SimulationsPage } from './pages/Simulations'
import { ApprovalCenterPage } from './pages/ApprovalCenter'
import { DbaAssistantPage } from './pages/DbaAssistantPage'
import { SystemHealthPage } from './pages/SystemHealth'
import { AuditLogsPage } from './pages/AuditLogsPage'

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        {/* 1. Overview */}
        <Route index element={<Overview />} />
        {/* 2. Slow Queries */}
        <Route path="slow-queries" element={<SlowQueries />} />
        {/* 3. Query Details */}
        <Route path="queries" element={<QueryDetails />} />
        {/* 4. Execution Plan Viewer */}
        <Route path="plans" element={<PlanViewer />} />
        {/* 5. GNN Analysis */}
        <Route path="gnn" element={<GnnAnalysisPage />} />
        {/* 6. Recommendations */}
        <Route path="recommendations" element={<RecommendationsPage />} />
        {/* 7. Simulations */}
        <Route path="simulations" element={<SimulationsPage />} />
        {/* 8. Approval Center */}
        <Route path="approvals" element={<ApprovalCenterPage />} />
        {/* 9. DBA Assistant */}
        <Route path="assistant" element={<DbaAssistantPage />} />
        {/* 10. System Health */}
        <Route path="health" element={<SystemHealthPage />} />
        {/* 11. Audit Logs */}
        <Route path="audit" element={<AuditLogsPage />} />

        {/* Fallback route */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
