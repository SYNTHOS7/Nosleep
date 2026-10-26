import test from 'node:test'
import assert from 'node:assert/strict'
import { createNeonAuth, getNeonSession, getNeonToken, signInNeon, registerNeon } from './neonAuth.js'

test('Neon token failures never become anonymous API access', async () => {
  assert.equal(await getNeonToken({ token: async () => ({ data: { token: 'signed-token' } }) }), 'signed-token')
  await assert.rejects(getNeonToken({ token: async () => ({ data: {} }) }), /expired/)
  await assert.rejects(getNeonToken({ token: async () => ({ error: { message: 'private upstream details' } }) }), /expired/)
})

test('session and password forms use the managed SDK contract', async () => {
  const calls = []
  const client = {
    getSession: async () => ({ data: { user: { id: 'user-1' } } }),
    signIn: { email: async value => calls.push(value) || { data: { ok: true } } },
    signUp: { email: async value => calls.push(value) || { data: { ok: true } } },
  }
  assert.equal((await getNeonSession(client)).id, 'user-1')
  await signInNeon(client, 'user@example.com', 'password')
  await registerNeon(client, 'User', 'user@example.com', 'password')
  assert.deepEqual(calls, [
    { email: 'user@example.com', password: 'password' },
    { name: 'User', email: 'user@example.com', password: 'password' },
  ])
  await assert.rejects(signInNeon({ signIn: { email: async () => ({ error: {} }) } }, '', ''), /Sign-in failed/)
})

test('installed Neon SDK includes session cookies on cross-origin requests', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url: String(url), credentials: options.credentials })
    return new Response(JSON.stringify({ user: { id: 'sdk-user' }, session: { id: 's', token: 'session', expiresAt: new Date(Date.now() + 60000).toISOString() } }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    const client = await createNeonAuth('https://auth.example.invalid/neondb/auth')
    const user = await getNeonSession(client)
    assert.equal(user.id, 'sdk-user')
    assert.equal(calls[0].credentials, 'include')
    assert.ok(calls[0].url.includes('/get-session'))
  } finally { globalThis.fetch = original }
})
