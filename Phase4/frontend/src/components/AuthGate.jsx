import React, { useEffect, useState } from 'react'
import { getAuthConfig, getCurrentUser, setTokenProvider } from '../services/api'

export default function AuthGate({ children }) {
  const [session, setSession] = useState(null)
  const [authClient, setAuthClient] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  useEffect(() => {
    let cancelled = false
    let unsubscribe
    const start = async () => {
      try {
        const config = await getAuthConfig()
        if (cancelled) return
        if (config.mode === 'demo') {
          setSession({ demo: true, workspaces: {}, uid: 'local-demo' })
          setBusy(false)
          return
        }
        const apiKey = import.meta.env.VITE_FIREBASE_API_KEY
        const projectId = import.meta.env.VITE_FIREBASE_PROJECT_ID
        const authDomain = import.meta.env.VITE_FIREBASE_AUTH_DOMAIN
        if (!apiKey || !projectId || !authDomain) throw new Error('Firebase sign-in is not configured. Set the frontend Firebase web configuration and rebuild.')
        const [{ initializeApp, getApps }, authSdk] = await Promise.all([import('firebase/app'), import('firebase/auth')])
        if (cancelled) return
        const app = getApps().find(item => item.name === 'aegisgraph-web') || initializeApp({ apiKey, projectId, authDomain }, 'aegisgraph-web')
        const auth = authSdk.getAuth(app)
        setAuthClient({ auth, sdk: authSdk })
        unsubscribe = authSdk.onAuthStateChanged(auth, async user => {
          setSession(null)
          setTokenProvider(user ? force => user.getIdToken(force) : null)
          if (user) {
            try {
              const identity = await getCurrentUser()
              if (!cancelled && auth.currentUser?.uid === user.uid) setSession({ ...identity, demo: false })
            } catch (err) {
              if (!cancelled) setError(err.message)
            }
          }
          if (!cancelled) setBusy(false)
        })
      } catch (err) {
        if (!cancelled) { setError(err.message); setBusy(false) }
      }
    }
    start()
    return () => { cancelled = true; unsubscribe?.(); setTokenProvider(null) }
  }, [])

  const signOut = async () => {
    setSession(null)
    setTokenProvider(null)
    await authClient.sdk.signOut(authClient.auth)
  }
  const signIn = async event => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await authClient.sdk.signInWithEmailAndPassword(authClient.auth, email.trim(), password)
      setPassword('')
    } catch {
      setError('Sign-in failed. Check your credentials and that your account is enabled.')
      setBusy(false)
    }
  }
  if (session && (session.demo || Object.keys(session.workspaces).length || session.platform_admin)) {
    return children(session, signOut)
  }
  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24 }}>
      <section className="glass-card" style={{ width: '100%', maxWidth: 420 }}>
        <h1>AegisGraph AI</h1>
        <p style={{ color: 'var(--text-secondary)', margin: '16px 0' }}>Sign in to your security workspace.</p>
        {busy && <p role="status">Checking your session…</p>}
        {error && <p role="alert" style={{ color: 'var(--accent-amber)', marginBottom: 16 }}>{error}</p>}
        {session && <><p>Your account has no workspace access. Ask an administrator to assign a workspace.</p><button className="btn-primary" onClick={signOut}>Sign out</button></>}
        {!session && authClient && <form onSubmit={signIn} style={{ display: 'grid', gap: 12 }}>
          <label>Email<input className="chat-input" style={{ width: '100%' }} type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)} /></label>
          <label>Password<input className="chat-input" style={{ width: '100%' }} type="password" autoComplete="current-password" required value={password} onChange={event => setPassword(event.target.value)} /></label>
          <button className="btn-primary" disabled={busy} type="submit">{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>}
      </section>
    </main>
  )
}
