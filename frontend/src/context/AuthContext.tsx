import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  clearAuthSession,
  getCurrentUserProfile,
  getStoredSession,
  loginUser,
  logoutUser,
  setAuthSession,
  type AuthUser,
  type UserRole,
} from '../lib/api'

const ROLE_WEIGHT: Record<UserRole, number> = {
  VIEWER: 1,
  ANALYST: 2,
  DBA: 3,
  ADMIN: 4,
}

export interface AuthContextValue {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  sessionExpired: boolean
  login: (usernameOrEmail: string, password: string) => Promise<AuthUser>
  logout: (reason?: 'manual' | 'expired') => Promise<void>
  clearExpiredNotice: () => void
  hasMinRole: (minRole: UserRole) => boolean
  canApprove: boolean
  canSimulate: boolean
  canManageUsers: boolean
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initial = useMemo(() => getStoredSession(), [])
  const [user, setUser] = useState<AuthUser | null>(initial.session?.user ?? null)
  const [sessionExpired, setSessionExpired] = useState<boolean>(initial.expired)
  const [isLoading, setIsLoading] = useState<boolean>(Boolean(initial.session))

  // Verify stored token against /api/v1/auth/me on mount
  useEffect(() => {
    const { session, expired } = getStoredSession()
    if (expired) {
      setUser(null)
      setSessionExpired(true)
      setIsLoading(false)
      return
    }
    if (!session) {
      setIsLoading(false)
      return
    }

    let cancelled = false
    getCurrentUserProfile()
      .then((profile) => {
        if (cancelled) return
        const verifiedUser: AuthUser = {
          id: Number(profile.user_id) || session.user.id,
          username: profile.username,
          email: profile.email || session.user.email,
          role: profile.role,
        }
        const remainingSec = Math.max(1, Math.floor(profile.expires_at - Date.now() / 1000))
        setAuthSession(session.token, verifiedUser, remainingSec)
        setUser(verifiedUser)
      })
      .catch((err: any) => {
        if (cancelled) return
        const msg = String(err?.message || '')
        if (msg.includes('401')) {
          clearAuthSession()
          setUser(null)
          setSessionExpired(true)
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Listen for centralized 401 session-expired events from api.ts
  useEffect(() => {
    const handleExpired = () => {
      clearAuthSession()
      setUser(null)
      setSessionExpired(true)
    }
    window.addEventListener('dbzenith:session-expired', handleExpired)
    return () => window.removeEventListener('dbzenith:session-expired', handleExpired)
  }, [])

  // Periodically check client-side token expiry timer
  useEffect(() => {
    if (!user) return
    const timer = window.setInterval(() => {
      const { session, expired } = getStoredSession()
      if (expired || !session) {
        setUser(null)
        setSessionExpired(true)
      }
    }, 15000)
    return () => window.clearInterval(timer)
  }, [user])

  const login = useCallback(async (usernameOrEmail: string, password: string): Promise<AuthUser> => {
    const res = await loginUser(usernameOrEmail, password)
    setSessionExpired(false)
    setUser(res.user)
    return res.user
  }, [])

  const logout = useCallback(async (reason: 'manual' | 'expired' = 'manual') => {
    await logoutUser()
    setUser(null)
    setSessionExpired(reason === 'expired')
  }, [])

  const clearExpiredNotice = useCallback(() => {
    setSessionExpired(false)
  }, [])

  const hasMinRole = useCallback(
    (minRole: UserRole): boolean => {
      if (!user) return false
      return (ROLE_WEIGHT[user.role] ?? 0) >= (ROLE_WEIGHT[minRole] ?? 99)
    },
    [user],
  )

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: Boolean(user),
      isLoading,
      sessionExpired,
      login,
      logout,
      clearExpiredNotice,
      hasMinRole,
      canApprove: hasMinRole('DBA'),
      canSimulate: hasMinRole('ANALYST'),
      canManageUsers: hasMinRole('ADMIN'),
    }),
    [user, isLoading, sessionExpired, login, logout, clearExpiredNotice, hasMinRole],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
