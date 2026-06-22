# Compass Golden Dataset

`compass_golden_v1.json` is the versioned golden set for offline metric checks.

It is designed around **stable identifiers**, not database-generated ids:

- Retrieval and grounded-answer cases use `doc_code` and `page`.
- Widget structured cases use `intent`, `catalog_id`, `scope_decision`, and support `doc_code`.
- Dashboard analysis cases use `dashboard_id`, `catalog_id`, and response scope.
- Safety cases use expected HTTP status and guardrail reason.

## Intended metrics

- `search_retrieval`: `hit@k`, `mrr`, `ndcg@k`, forbidden-doc leakage rate
- `search_answer`: grounded-answer rate, citation precision/recall by `doc_code`, refusal accuracy
- `widget`: intent accuracy, catalog accuracy, scope-decision accuracy, support-source accuracy
- `dashboard_analysis`: dashboard selection accuracy, scope accuracy, required-term coverage
- `safety`: guardrail block rate, correct block reason rate

## Fixture profiles

Cases are tied to controlled fixture profiles already present in the repo, not the mutable live Docker
database:

- `phase5_ready_corpus`
- `phase6_search_route`
- `phase8_widget_route`
- `phase9_dashboards`

That keeps the expected outcomes stable even when the dev database changes.
