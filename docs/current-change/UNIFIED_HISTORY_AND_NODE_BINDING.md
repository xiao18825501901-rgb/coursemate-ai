# UNIFIED_HISTORY_AND_NODE_BINDING

## Model

- `cmui_pairs` (schema 6): one unified dual-pane session per `(owner, course)` pair-row.
  Columns: id, owner, course, teach_conversation, problem_conversation, title,
  bound_node, created_at, updated_at.
  - `teach_conversation`/`problem_conversation` point at the two lane conversations
    (either may be NULL → empty pane, no fake messages).
  - One title shared by both panes; rename updates both lane rows.
- Node binding uniqueness: partial unique index
  `cmui_pairs_node_binding ON (owner, course, bound_node) WHERE bound_node IS NOT NULL`
  — enforced by the database, not the UI. Binding changes are transactional
  (`POST /pairs/{id}/bind {node|null}`): conflict → 409 `NODE_ALREADY_BOUND` with the
  owning pair; unbind never deletes chats or fakes progress regression.
- Pane layout (ratio/active node) remains in `cmui_layout` (unchanged).

## Behaviour

- 新对话 → `POST /pairs` creates a new dual-pane session (both panes reset).
- History modal (both panes) lists the same pairs (`GET /pairs?course_id=`); selecting
  one restores BOTH panes (`GET /pairs/{id}`), including an in-flight run resume.
- Per-pair ⋯ menu: 绑定知识点 / 更换绑定 / 解除绑定 with a hierarchical searchable
  node picker (current course only).
- First teaching on a node binding is automatically Thinking (exactly once): the run
  endpoint performs an atomic claim (`UPDATE … WHERE bound_node IS NULL`) so parallel
  clicks/refreshes cannot double-bind or double-charge. Later runs on the binding
  restore without forcing Thinking.
- Failed first teaching keeps the pair + failure state; re-clicking the node restores
  (retry is explicit, never auto-billed).

## Migration (schema 6, one-time, idempotent)

`Database._migrate_pairs`: `cmui_layout` rows (evidence-backed pairing) become pairs with
`bound_node = active_node`; leftover conversations without layout evidence become
single-lane pairs (other lane NULL). No time-proximity guessing. V3 legacy records stay
reachable through the existing read-only legacy-conversation routes.
