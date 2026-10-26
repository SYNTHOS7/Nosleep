import React, { useEffect, useRef, useState } from 'react'
import { getAuthConfig, getCurrentUser, setTokenProvider } from '../services/api'
import { createNeonAuth, getNeonSession, getNeonToken, signInNeon, registerNeon } from '../services/neonAuth'

export default function AuthGate({ children }) {
  const [session, setSession] = useState(null)
  const [authClient, setAuthClient] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [register, setRegister] = useState(false)
  const generation = useRef(0)

  const loadIdentity = async client => {
    const attempt = ++generation.current
    const user = await getNeonSession(client)
    if (attempt !== generation.current) return false
    if (!user) { setTokenProvider(null); setSession(null); return false }
    setTokenProvider(() => getNeonToken(client))
    const identity = await getCurrentUser()
    if (attempt !== generation.current) return false
    setSession({ ...identity, demo: false })
    return true
  }

  useEffect(() => {
    let cancelled = false
    const start = async () => {
      try {
        const config = await getAuthConfig()
        if (cancelled) return
        if (config.mode === 'demo') {
          setSession({ demo: true, workspaces: {}, uid: 'local-demo' })
          setBusy(false)
          return
        }
        const url = import.meta.env.VITE_NEON_AUTH_URL
        if (!url) throw new Error('Neon sign-in is not configured. Set VITE_NEON_AUTH_URL and rebuild the frontend.')
        const client = await createNeonAuth(url)
        if (cancelled) return
        setAuthClient(client)
        await loadIdentity(client)
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setBusy(false)
      }
    }
    start()
    return () => { cancelled = true; generation.current += 1; setTokenProvider(null) }
  }, [])

  const signOut = async () => {
    generation.current += 1
    setTokenProvider(null)
    setSession(null)
    setError('')
    try {
      const result = await authClient.signOut()
      if (result.error) throw new Error('Sign-out was not confirmed. Check your connection and retry.')
    } catch {
      setError('Sign-out was not confirmed. Check your connection and retry before leaving a shared device.')
    }
  }
  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (register) await registerNeon(authClient, name.trim(), email.trim(), password)
      else await signInNeon(authClient, email.trim(), password)
      setPassword('')
      if (!await loadIdentity(authClient)) setNotice('Check your email for a verification link, then sign in.')
    } catch (err) {
      setError(err.message)
    } finally { setBusy(false) }
  }
  if (session && (session.demo || Object.keys(session.workspaces).length || session.platform_admin)) {
    return children(session, signOut)
  }
  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24 }}>
      <section className="glass-card" style={{ width: '100%', maxWidth: 420 }}>
        <h1>AegisGraph AI</h1>
        <p style={{ color: 'var(--text-secondary)', margin: '16px 0' }}>{register ? 'Create your account. An administrator assigns workspace access.' : 'Sign in to your security workspace.'}</p>
        {busy && <p role="status">Checking your session…</p>}
        {notice && <p role="status">{notice}</p>}
        {error && <p role="alert" style={{ color: 'var(--accent-amber)', marginBottom: 16 }}>{error}</p>}
        {session && <>
          <p>Your account has no workspace access. Ask an administrator to assign a workspace, then reload.</p>
          <p style={{ margin: '12px 0', overflowWrap: 'anywhere' }}>Your user ID: <code>{session.uid}</code></p>
          <button className="btn-primary" onClick={signOut}>Sign out</button>
        </>}
        {!session && authClient && <form onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
          {register && <label>Name<input className="chat-input" style={{ width: '100%' }} autoComplete="name" required value={name} onChange={event => setName(event.target.value)} /></label>}
          <label>Email<input className="chat-input" style={{ width: '100%' }} type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)} /></label>
          <label>Password<input className="chat-input" style={{ width: '100%' }} type="password" minLength={register ? 8 : undefined} autoComplete={register ? 'new-password' : 'current-password'} required value={password} onChange={event => setPassword(event.target.value)} /></label>
          <button className="btn-primary" disabled={busy} type="submit">{busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'}</button>
          <button className="topic-chip" disabled={busy} type="button" onClick={() => { setRegister(!register); setError(''); setNotice('') }}>{register ? 'Already have an account? Sign in' : 'Create an account'}</button>
        </form>}
      </section>
    </main>
  )
}
