# P0 Parallel Task Isolation Report

## Current heads re-read on 2026-10-02

- Production/current and NanoJev code base: `d854b0e`.
- P0 feature branch: `c9ff3ca` before release reconstruction.
- Visual/ComfyUI working line: `feature/learning-loop-20260928` at `71c2f05e`.
- NanoJev working line: `research/nanojev-shadow-20260930` at `d854b0e`; separate long-running training processes remained alive.

## Isolation action

The P0 feature branch was initially based on `cfc4f3e`, which already contained 66 Visual/ComfyUI files. Those files were not approved for this release. A clean release candidate branch, `release/p0-do-one-private-tree-20261002`, was therefore created from production `d854b0e` and only the eight P0 commits were cherry-picked in order.

The only source overlap with the Visual line was `services/rag-api/app/main.py`. Cherry-pick merged without conflict; review confirmed that the release candidate adds only event-only auto-map reconciliation and contains none of the Visual service, workflow, migration, dependency or UI files.

No other worktree was reset, cleaned, stashed or written. No GPU process, NanoJev process, ComfyUI process, port 8765/8766, cache, model, receipt, lock or artifact was stopped or modified.

## Release comparison gate

The release package must be created from the committed release-candidate Git object, not the working directory. This excludes both unrelated worktree data and a semantic-no-op `config.py` line-ending discrepancy observed after switching bases.

