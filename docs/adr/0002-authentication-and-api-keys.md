# ADR 0002: Clerk is the identity and API-key authority

- Status: Accepted
- Date: 2026-08-22

## Context

Dashboard sessions and programmatic credentials need organization ownership, expiry, scopes, rotation, revocation and audit without persisting raw secrets.

## Decision

Clerk is authoritative for users, organizations, memberships, sessions and API keys. Dashboard-only key-management routes require a verified session plus organization permission. Public API routes accept bearer credentials and perform server-side Clerk verification on every request.

Accepted API keys must contain the custom claim `smcp_issued: true`, a tenant subject and the endpoint's required scope. The application stores only Clerk key identifiers and non-secret audit metadata. Creation returns the secret exactly once. Rotation creates a distinct key, allows a bounded overlap and then revokes the predecessor through Clerk.

Tenant identity is derived from the verified credential, never accepted from request bodies. Database access always includes the tenant subject. Development-only authentication is explicit and cannot start when `NODE_ENV=production`.

## Consequences

Clerk availability is required to verify a fresh key. Short-lived positive verification caching may be added with revocation-aware TTL. E2E requires a real Clerk test instance; unit tests use injected verifier contracts rather than fake production endpoints.

