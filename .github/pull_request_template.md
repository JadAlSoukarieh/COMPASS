## Summary

Describe what changed and why.

## Validation

- [ ] `python -m pytest backend/tests -q`
- [ ] `python scripts/check_no_string_sql.py`
- [ ] Manual role/scope check if auth, catalog, retrieval, dashboard, or admin behavior changed

## Security Checklist

- [ ] No `.env`, API keys, tokens, passwords, or signing keys are included
- [ ] No proprietary documents or customer data are included
- [ ] LLM still cannot generate or execute raw SQL
- [ ] Backend scope enforcement is preserved
- [ ] New sensitive actions are audit logged
