# Authentication and workspace access

Hosted mode uses Neon managed Auth (Better Auth). The browser SDK signs users in and obtains short-lived JWTs. The API verifies EdDSA signatures through the configured Auth endpoint's JWKS, requires expiration/issued-at/subject claims, and checks issuer and audience against that endpoint's origin. Arbitrary client-supplied identity fields are never trusted.

Set AUTH_MODE=neon and NEON_AUTH_URL on the API, and VITE_NEON_AUTH_URL at frontend build time. Missing configuration or invalid tokens fail closed. Public signup grants no workspace permissions. Database credentials stay on the backend. The application stores its authorization records in private `aegis.users` and `aegis.memberships` tables; Neon Auth owns passwords and sessions.

From Phase4, operators can grant or remove access using DATABASE_URL:

```powershell
python -m backend.security.manage_access --uid USER_ID --workspace security-team --role viewer
python -m backend.security.manage_access --uid USER_ID --workspace security-team --role editor
python -m backend.security.manage_access --uid USER_ID --workspace security-team --role admin --platform-admin
python -m backend.security.manage_access --uid USER_ID --workspace security-team --role remove --revoke-platform-admin
```

Use the exact user ID displayed by the signed-in app. Viewer can read/query, editor can ingest/edit/delete, and workspace admin can administer that workspace. Platform administration is an explicit separate grant. Every protected request reads current memberships; database failure denies access. Setting `aegis.users.disabled=true` denies that user's application access immediately.

Neon JWTs normally expire after 15 minutes. Signing out removes the browser session; do not assume an already issued token is instantly revoked at the provider. Application membership removal and the disabled flag are checked live. The frontend fetches a token for API requests; MCP clients must supply and refresh their own bearer token.

Local AUTH_MODE=demo is deliberately unauthenticated and labeled in the UI. It is rejected when running hosted or using Neon storage. Configure trusted frontend origins in Neon Auth and matching API CORS origins. Session requests include credentials; restrictive cross-site cookie policies may require a supported same-site proxy/domain setup.

See HOSTED_SETUP.md for schema setup and first-account onboarding. Live provider integration remains pending your account configuration.
