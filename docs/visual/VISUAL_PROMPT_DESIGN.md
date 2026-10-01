# Visual Planner and Compiler Prompt Design

## Versioned prompt assets

- `app/visual/prompts/visual_router_planner_v1.system`
- `app/visual/prompts/visual_prompt_compiler_v1.system`
- `app/visual/prompts/visual_validator_v1.system`

The planner prompt is loaded as a versioned artifact and its SHA-256 is persisted on every job. Phase A uses `MockVisualPlannerProvider`, so no LLM or billable call is made. The interface is ready for a later provider without changing the job or API contracts.

## Trust model

Student text, teaching answers, citations, filenames and retrieved course content are untrusted data. They cannot select workflows, providers, endpoints or credentials. Planner output must be one strict VisualSpec JSON object and must refer only to server-supplied evidence IDs and versions.

## Compiler

Compilation is deterministic code rather than a second LLM call. It converts a validated VisualSpec into renderer instructions, negative constraints and deterministic overlays. Exact labels, formulas and code are never delegated to a generative image model. Private source chunks are reduced to validated facts instead of being copied wholesale into renderer prompts.

## Validation

Phase A performs deterministic structural/media checks and labels the mock PNG `LIMITED`; it does not claim pixel-level semantic perfection. A future vision validator must return structured uncertainty and cannot upgrade unknown observations to `PASS`.

## Change control

Prompt text changes require a new prompt version/hash, routing cases and cache invalidation through the existing key material. Historical jobs retain their original prompt/spec/workflow identities.
