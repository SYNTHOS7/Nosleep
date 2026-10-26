// Keep SDK interactions separate from UI state and test them without an account.
export async function createNeonAuth(url) {
  const [{ createAuthClient }, { BetterAuthVanillaAdapter }] = await Promise.all([
    import('@neondatabase/auth'), import('@neondatabase/auth/vanilla/adapters'),
  ])
  return createAuthClient(url, {
    adapter: BetterAuthVanillaAdapter({ fetchOptions: { credentials: 'include' } }),
  })
}

export async function getNeonSession(client) {
  const result = await client.getSession()
  if (result.error) throw new Error('Your Neon session could not be checked.')
  return result.data?.user || null
}

export async function getNeonToken(client) {
  const result = await client.token()
  if (result.error || !result.data?.token) throw new Error('Your session has expired. Sign in again.')
  return result.data.token
}

export async function signInNeon(client, email, password) {
  const result = await client.signIn.email({ email, password })
  if (result.error) throw new Error('Sign-in failed. Check your credentials and account status.')
  return result.data
}

export async function registerNeon(client, name, email, password) {
  const result = await client.signUp.email({ name, email, password })
  if (result.error) throw new Error('The account could not be created. Check your details or sign in.')
  return result.data
}
