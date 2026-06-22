# Contract: Auth

All role/scope is derived from the JWT server-side. Never trust client-supplied role/scope.

## POST /auth/login
- **Body**: `{ "username": str, "password": str }`
- **200**: `{ "access_token": str, "token_type": "bearer", "role": str, "user_id": int }`
  - Token payload carries `user_id` and `role` (and, for mgr, enough to resolve direct reports).
- **401**: invalid credentials. Failed logins are audit-logged (`action_type=login`, result=refused).
- Rate-limited (brief §12e). Successful login audit-logged (result=success).

## GET /auth/me
- **Auth**: required.
- **200**: `{ "user_id": int, "role": str, "employee_id": int|null, "is_active": bool }`
- Used by the frontend to gate UI; UI gating is cosmetic only — backend guards are authoritative.

## Dependencies (server-side)
- `get_current_user` — decodes JWT, loads user + role + (mgr) direct-report ids.
- `require_roles("hr","superuser")` etc. — per-route role guard.
- `resolve_scope(user)` — returns self/team/company scope used by catalog + dashboards.
