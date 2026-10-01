# VisualSpec 1.0 Contract

The authoritative executable schema is `services/rag-api/app/visual/spec.py`. All models forbid unknown fields.

## Required decisions

`VisualSpec` records:

- whether generation is pedagogically justified;
- visual type and renderer family;
- importance, timing, confidence and cost tier;
- immutable source grounding (`source_id`, `source_version`, locator and supported claim);
- exact labels/equations/code kept out of generative pixels;
- bounded style, duration, aspect ratio and cache policy;
- deterministic diagram nodes/edges and ordered animation steps when applicable;
- semantic precision and safe fallback renderer.

## Invariants

- A non-generated spec must use `NONE` type and renderer.
- A generated spec must use a concrete type and renderer.
- Generated video requires essential motion and a bounded duration.
- `COMFY_VIDEO` requires `VIDEO`; Comfy renderers cannot own `EXACT` semantics.
- Deterministic diagrams cannot claim merely illustrative precision.
- Diagram node IDs are unique; all edges and animation highlights reference existing nodes.
- Animation step order is unique and increasing.
- Every source/version in the spec must exist in the server-frozen evidence set.
- Lists and text fields have explicit size limits; duration is at most 15 seconds.

## Renderer policy

- Exact topology, labels, equations, code and ordered algorithms route to deterministic SVG/diagram/Manim families.
- Natural or conceptual scenes with bounded variation may route to `COMFY_IMAGE`.
- `COMFY_VIDEO` is reserved for essential motion and is disabled by default.
- Text-sufficient questions can return `NONE`; novelty alone is not a generation reason.

## Versioning

Phase A accepts only `visual_spec_version="1.0"`. Jobs persist the serialized spec, schema version and SHA-256. Cache keys also bind source snapshot, spec hash, prompt version, workflow/model versions, language and access scope. A future contract change must introduce a new version instead of mutating 1.0 semantics.
