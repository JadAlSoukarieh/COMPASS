# Contract: Dashboards

Role-scoped: emp minimal/self, mgr team-scoped (direct reports), hr/superuser company-wide.
Dashboard rows are cached per `(catalog_id, scope, params)` (short TTL), busted on relevant writes.

## GET /dashboards
- **Auth**: required.
- **200**: the set of dashboards the user's role permits, with metadata for rendering.
  - emp: own leave summary only (or none).
  - mgr: team headcount, team salary summary, team leave calendar (direct reports only).
  - hr/superuser: salary distribution, headcount by dept, turnover, contracts expiring.

## GET /dashboards/{dashboard_id}/data
- **Auth**: required; backend enforces the user's scope on the underlying catalog query(ies).
- **Behaviour**: run the scoped catalog query(ies); cache rows under `dash:<catalog_id>:<scope>:<hash(params)>`.
- **200**: `{ "dashboard_id": str, "rows": [ ... ], "scope": "self|team|company", "cached": bool }`.
- A mgr never receives data outside their direct reports; out-of-scope dashboards are not returned.

## POST /dashboards/{dashboard_id}/analyze  (widget mode 6b)
- **Auth**: required.
- **Behaviour**: backend fetches the scoped rows (as above), passes ONLY those rows (fenced as data)
  to the LLM with an analysis prompt; `output_guard()` applied; returns a written summary (trends,
  outliers, retention/approval signals). The LLM never queries on its own.
- **200**: `{ "dashboard_id": str, "analysis_markdown": str, "scope": str }`.
- Audit-logged (`action_type=data_analysis`, detail: dashboard_id, scope, latency_ms).

## Cache invalidation
Writes that change underlying data (employee/leave updates) bust the related `dash:` keys.
