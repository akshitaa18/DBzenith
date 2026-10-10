import { Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Layout } from './components/Layout'
import { LoginPage } from './pages/LoginPage'
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
import { UserAdminPage } from './pages/UserAdminPage'

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />

        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
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
          <Route
            path="approvals"
            element={
              <ProtectedRoute minRole="DBA">
                <ApprovalCenterPage />
              </ProtectedRoute>
            }
          />
          {/* 9. DBA Assistant */}
          <Route path="assistant" element={<DbaAssistantPage />} />
          {/* 10. System Health */}
          <Route path="health" element={<SystemHealthPage />} />
          {/* 11. Audit Logs */}
          <Route
            path="audit"
            element={
              <ProtectedRoute minRole="ANALYST">
                <AuditLogsPage />
              </ProtectedRoute>
            }
          />
          {/* 12. User & RBAC Administration (Admin only) */}
          <Route
            path="users"
            element={
              <ProtectedRoute minRole="ADMIN">
                <UserAdminPage />
              </ProtectedRoute>
            }
          />

          {/* Fallback route */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
