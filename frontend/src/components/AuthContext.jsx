/**
 * AuthContext.jsx
 * Global authentication state.
 * Wrap your app in <AuthProvider> and call useAuth() anywhere.
 */

import { createContext, useContext, useState, useEffect } from 'react'
import { authAPI } from '../api/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null)
  const [loading, setLoading] = useState(true)

  // On app load — check if user is already logged in
  useEffect(() => {
    const token = localStorage.getItem('aibridge_token')
    if (token) {
      authAPI.me()
        .then(res => setUser(res.data))
        .catch(()  => localStorage.removeItem('aibridge_token'))
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (email, password) => {
    const res = await authAPI.login(email, password)
    const me  = await authAPI.me()
    setUser(me.data)
    return res.data
  }

  const logout = async () => {
    await authAPI.logout()
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
