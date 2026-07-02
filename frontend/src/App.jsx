/**
 * App.jsx — AIBridge routes
 * Added: DataQuality (/quality), Scheduler (/scheduler), PipelineLogs (/logs)
 */

import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { AuthProvider, useAuth } from './components/AuthContext'
import { ErrorBoundary, ToastProvider } from './components/ErrorBoundary'
import Layout from './components/Layout'
import Onboarding from './pages/Onboarding'

import Login           from './pages/Login'
import Dashboard       from './pages/Dashboard'
import EtlAgent        from './pages/EtlAgent'
import DataModel       from './pages/DataModel'
import EtlMapping      from './pages/EtlMapping'
import SqlScripts      from './pages/SqlScripts'
import SourceTarget    from './pages/SourceTarget'
import SchemaEvolution from './pages/SchemaEvolution'
import Analytics       from './pages/Analytics'
import Pipelines       from './pages/Pipelines'
import Connectors      from './pages/Connectors'
import Team            from './pages/Team'
import RecoveryLogs    from './pages/RecoveryLogs'
import DataQuality     from './pages/DataQuality'
import Scheduler       from './pages/Scheduler'
import Logs            from './pages/Logs'
import Cost            from './pages/Cost'

const Stub = ({ name }) => (
  <div style={{ padding: 40, fontFamily: 'system-ui' }}>
    <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{name}</div>
    <div style={{ fontSize: 13, color: '#888' }}>Coming soon!</div>
  </div>
)

function PrivateRoute({ children }) {
  const { user, loading } = useAuth()
  const [showOnboarding, setShowOnboarding] = useState(false)

  useEffect(() => {
    if (user) {
      const done = localStorage.getItem(`onboarding_done_${user.id}`)
      if (!done) setShowOnboarding(true)
    }
  }, [user])

  const completeOnboarding = () => {
    if (user) localStorage.setItem(`onboarding_done_${user.id}`, '1')
    setShowOnboarding(false)
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
      height: '100vh', fontFamily: 'system-ui', color: '#888', fontSize: 13,
      flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 32 }}>⚙️</div>
      Loading AIBridge...
    </div>
  )

  if (!user) return <Navigate to="/login" replace />

  return (
    <>
      {showOnboarding && <Onboarding onComplete={completeOnboarding} />}
      <Layout>{children}</Layout>
    </>
  )
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login"          element={<Login />} />
      <Route path="/"               element={<PrivateRoute><Dashboard /></PrivateRoute>} />
      <Route path="/agent"          element={<PrivateRoute><EtlAgent /></PrivateRoute>} />
      <Route path="/source-target"  element={<PrivateRoute><SourceTarget /></PrivateRoute>} />
      <Route path="/model"          element={<PrivateRoute><DataModel /></PrivateRoute>} />
      <Route path="/mapping"        element={<PrivateRoute><EtlMapping /></PrivateRoute>} />
      <Route path="/sql"            element={<PrivateRoute><SqlScripts /></PrivateRoute>} />
      <Route path="/evolution"      element={<PrivateRoute><SchemaEvolution /></PrivateRoute>} />
      <Route path="/analytics"      element={<PrivateRoute><Analytics /></PrivateRoute>} />
      <Route path="/pipelines"      element={<PrivateRoute><Pipelines /></PrivateRoute>} />
      <Route path="/quality"        element={<PrivateRoute><DataQuality /></PrivateRoute>} />
      <Route path="/scheduler"      element={<PrivateRoute><Scheduler /></PrivateRoute>} />
      <Route path="/logs"           element={<PrivateRoute><Logs /></PrivateRoute>} />
      <Route path="/recovery-logs"  element={<PrivateRoute><RecoveryLogs /></PrivateRoute>} />
      <Route path="/cost"           element={<PrivateRoute><Cost /></PrivateRoute>} />
      <Route path="/connectors"     element={<PrivateRoute><Connectors /></PrivateRoute>} />
      <Route path="/team"           element={<PrivateRoute><Team /></PrivateRoute>} />
      <Route path="/settings"       element={<PrivateRoute><Stub name="AI provider settings" /></PrivateRoute>} />
      <Route path="*"               element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <AppRoutes />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
