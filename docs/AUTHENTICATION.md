# Firebase sign-in and workspace access

## Local versus hosted mode

Local, in-memory runs default to AUTH_MODE=demo and show a **Local demo · no login**
badge. Database credential configuration is disabled in demo mode. Firebase-backed
storage, Render deployments, and APP_ENV=production require AUTH_MODE=firebase;
explicitly selecting demo in these environments stops startup.

## Connect Firebase Authentication

1. Enable Email/Password sign-in in your Firebase project.
2. Create initial user accounts in Firebase Authentication. Public account signup
   is deliberately not included in this administrative application.
3. Configure the backend service account using HOSTED_SETUP.md. It needs Firebase
   Authentication access for token revocation/disabled-user checks and Firestore
   access for workspace membership lookup.
4. Set AUTH_MODE=firebase in the backend. Set these public frontend values before
   building with Node 20.19+ or 22.12+:

   ```env
   VITE_FIREBASE_API_KEY=your-public-web-api-key
   VITE_FIREBASE_PROJECT_ID=your-project-id
   VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
   ```

   Never put a service-account credential in frontend variables. Add the frontend
   domain to Firebase Authentication's authorized domains.
5. Give each user a workspace membership using the trusted backend/operator CLI:

   ```bash
   cd Phase4
   python -m backend.security.manage_access --uid FIREBASE_USER_UID --workspace security-team --role editor
   ```

   Roles are viewer, editor and admin. Viewers read/query; editors and workspace
   admins may upload, edit, delete, load fixtures and discover topics. Platform
   database administration requires the separate platform_admin flag. Grant it
   only to an operator using the explicit --platform-admin option. Revoke it with
   --revoke-platform-admin. Remove a workspace membership with --role remove.

## Enforcement

The backend verifies Firebase ID tokens with revocation checks. It reads current
membership records on every protected request; an old token does not preserve a
removed workspace role. Memberships are stored in aegis_users/{sha256(uid)}:

```json
{"uid":"firebase-uid", "workspaces":{"security-team":"editor"}, "platform_admin":false}
```

These are trusted server records, not editable user profile claims. Direct browser
Firestore access remains denied by firestore.rules. There is no public role-grant
endpoint. The operator CLI uses a Firestore transaction to preserve concurrent
membership changes.

Query bodies, workspace routes, chunk-source lookups, operation IDs and batch
status checks all enforce membership. Referencing an operation/source from another
workspace does not bypass access checks. Database status/configuration require a
platform administrator. Public endpoints are the UI, health and auth configuration.

The browser sends current Firebase tokens automatically and refreshes on an
authentication failure. It offers only assigned workspaces and hides write actions
for viewers. The API is authoritative even if a client changes its own controls.

For MCP in authenticated mode, set AEGISGRAPH_ID_TOKEN to a current Firebase user
ID token. It has the same workspace restrictions as the UI. Tokens expire; the
MCP launcher must supply a fresh token when necessary. No permanent admin bypass
key or unverified token mode is implemented.

## Ingestion limits

Requests are capped at 50 MiB. Batch requests accept at most 1000 uploaded files.
Archives are limited to 1000 entries and 50 MiB expanded content and reject traversal
paths or symbolic links. Source filenames are normalized to basenames and reject
control characters/Windows alternate streams. Client-supplied document/resource
IDs must use the restricted identifier alphabet.

## Verification boundary

Automated tests cover unsigned/expired/revoked identities, unavailable membership
storage, viewer/editor/platform permissions, cross-workspace evidence and operation
access, live membership removal, unsafe identifiers and archives. Tests substitute
identity verification and membership storage; an actual Firebase project and real
user sign-in still need verification after you connect your account.

Remaining security work includes audit trails, request-rate/concurrency limits,
virus/content scanning, account lifecycle UI and workspace invitation management.
Authentication and upload bounds do not constitute a complete security audit.

Existing persisted documents retain their previous extracted assertions. Edit or
re-ingest those documents to apply the revised extraction rules. Fresh extraction
uses a new cache version; old candidate caches are not reused.
