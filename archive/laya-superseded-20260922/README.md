# Laya archive (SUPERSEDED_BY_JEV_DECISION)

Created 2026-09-22 when the owner stopped the Laya direction ('阿里云当前可用服务器性能不适合部署 Laya').
The production architecture is DeepSeek (generation) + TypeSafe Jev (typed semantic decisions)
+ deterministic backend. Contents:

* `code/` - Laya-only source: `app-laya` (adapter/gateway/compiler), `services-laya-inference` (the private
  FastAPI service), `deploy-laya`, `fetch_laya_model.py`, the withdrawn migration 029.
* `docs/` - the Laya reports, each prefixed SUPERSEDED_BY_JEV_DECISION.
* `measurement/` - Laya-specific tests (adapter/gateway/compiler/zero-egress).

Reusable ideas already carrying over to Jev: the input-budget/provenance concept, the 12-row
call-site matrix, the typed-decision validation rules, and the A/B/C/D/E ablation + calibration
maths with the 310-sample judgment dataset (promoted under `benchmarks/jev-*`).

Also recorded: `LAYA_PRODUCTION_RESOURCE_CREATED = false` - no Alibaba Cloud instance, node,
port, DNS entry or billable resource was ever created for Laya. The only local artefacts are a
CPU-only venv at `D:\\AI\\laya-venv` and a 654 MB model snapshot at
`D:\\AI\\Models\\laya-multilingual\\1c5edc17...` (outside the repository, harmless, deletable).

