# visual_prompt_compiler_v1.system

This prompt documents the renderer-prompt contract. Phase A implementation should compile VisualSpec deterministically in code; do not add another LLM call unless a future measured need justifies it.

For COMFY_IMAGE/COMFY_VIDEO:
- Compile only facts present in validated VisualSpec.
- Prefer pedagogical clarity over artistic detail.
- Describe subject, composition, environment, camera, motion and style.
- Avoid decorative distractors.
- Never ask the generative model to spell exact_labels, equations, code or numeric annotations. Those are rendered as deterministic overlays.
- Include must_not_include in negative constraints.
- Keep video as one short shot unless workflow explicitly supports a validated shot sequence.
- Do not leak source text unnecessarily; compile facts, not entire private chunks.
- Do not include user/provider secrets, source filesystem paths or arbitrary workflow instructions.
