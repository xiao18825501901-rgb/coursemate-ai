import { expect, it, vi, beforeEach } from 'vitest';
// @ts-ignore delivered JSX module
import { Learn } from './ui/pages.jsx';

/**
 * The answer-visibility contract, pinned.
 *
 * The defect class this file exists for: the server commits the assistant message and the
 * browser never shows it, so the learner has to reload. `reload` finds history; it is not how
 * a first answer is supposed to become visible, and the browser suite used to accept a reload
 * as a pass (`tests/e2e/jev-structured.spec.ts` reloaded once before asserting).
 *
 * The fix is a bounded, model-free reconciliation against the canonical conversation record
 * (`Learn.reconcile`), reached from the three paths that used to lose the answer: the send
 * whose pane moved mid-request, a stream that ended without a terminal reconcile, and a stream
 * that was cut. These tests drive the real component methods with the API mocked, so they fail
 * if the guards are loosened again.
 */
const api = vi.hoisted(() => ({
  request: vi.fn(), getPair: vi.fn(), listPairs: vi.fn(), send: vi.fn(),
  createPair: vi.fn(), streamEvents: vi.fn(),
}));
vi.mock('./ui/api.js', async original => ({ ...await original<object>(), ...api }));

const ANSWER = 'DBSCAN 把密度相连的点归为一簇。';

function page() {
  // The delivered JSX component's `state` field is inferred with literal nulls (its initial
  // value), so an assignment of a real id does not type-check. The component is plain JS; the
  // assertion surface here is its behaviour, and the existing suite in the same directory uses
  // the same escape (`@ts-ignore` on the import).
  const instance = new Learn({ course: { id: 'course' }, toast: vi.fn() }) as any;
  instance.setState = (value: any, callback?: () => void) => {
    instance.state = { ...instance.state, ...(typeof value === 'function' ? value(instance.state) : value) };
    callback?.();
  };
  return instance;
}

function conversation(messages: object[], active: object | null = null) {
  return { messages, active_run: active };
}

beforeEach(() => {
  api.request.mockReset();
  api.send.mockReset();
  api.streamEvents.mockReset();
  api.streamEvents.mockResolvedValue(undefined);
});

it('shows the first answer without a reload when the pane moves while the run is being created', async () => {
  const instance = page();
  instance.state.conv.teach = 'conv-1';
  instance.pairRevision = 0;
  api.send.mockImplementation(async (path: string) => {
    // A node binding (or a history selection) lands between the POST and its answer: this is
    // the race that made round 93 add `pendingBinding`; it can still happen *after* the send.
    if (path === '/conversations/conv-1/runs') {
      instance.pairRevision = 1;
      return { id: 'run-1' };
    }
    return {};
  });
  api.request.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1')
      return conversation([{ id: 'm1', role: 'user', content: '什么是 DBSCAN？' },
        { id: 'm2', role: 'assistant', content: ANSWER }]);
    if (path === '/runs/run-1')
      return { status: 'completed', partial_text: '', coverage: null };
    return {};
  });

  await instance.ask('teach', '什么是 DBSCAN？');

  expect(instance.state.messages.teach.map((m: any) => m.content)).toContain(ANSWER);
  expect(instance.state.busy.teach).toBe(false);
  expect(instance.state.run.teach).toBe(null);
  expect(api.streamEvents).toHaveBeenCalledWith('run-1', expect.any(Function), expect.anything());
});

it('says where the answer went when the pane has already moved to another conversation', async () => {
  const instance = page();
  instance.state.conv.teach = 'conv-1';
  api.send.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1/runs') {
      // A Pair binding: `_restorePair` moves this lane to the Pair's own conversation **and**
      // bumps the revision, so both of the guards in `ask` have to hold for the pane to be
      // written into.
      instance.pairRevision = 1;
      instance.state.conv.teach = 'conv-2';
      return { id: 'run-1' };
    }
    return {};
  });
  api.request.mockResolvedValue({ messages: [{ id: 'm2', role: 'assistant', content: 'conv-1 的回答' }] });

  await instance.ask('teach', '什么是 DBSCAN？');

  // The other conversation's messages are never overwritten, the composer is released, and the
  // learner is told which control finds the answer instead of being left with a dead send button.
  expect(instance.state.messages.teach).toEqual([]);
  expect(instance.state.busy.teach).toBe(false);
  expect(instance.state.status.teach).toContain('历史对话');
});

it('does not write one conversation over a pane that moved without a Pair revision', async () => {
  // `restore()` switches `conv` without bumping `pairRevision`. Before this was checked
  // separately, that window let a reply to the old conversation be rendered into the new one.
  const instance = page();
  instance.state.conv.teach = 'conv-1';
  instance.state.messages.teach = [{ id: 'newer', role: 'assistant', content: '新对话的回答' }];
  api.send.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1/runs') {
      instance.state.conv.teach = 'conv-2'; // a layout/history restore, revision untouched
      return { id: 'run-1' };
    }
    return {};
  });
  api.request.mockResolvedValue({ messages: [{ id: 'old', role: 'assistant', content: '旧对话的回答' }] });

  await instance.ask('teach', '什么是 DBSCAN？');

  expect(instance.state.messages.teach).toEqual([{ id: 'newer', role: 'assistant', content: '新对话的回答' }]);
  expect(instance.state.status.teach).toContain('历史对话');
  expect(instance.state.busy.teach).toBe(false);
});

it('reconciles once when the stream is cut, without a second model call', async () => {
  const instance = page();
  instance.state.conv.teach = 'conv-1';
  instance.setLane('busy', 'teach', true);
  instance.setLane('run', 'teach', 'run-1');
  api.streamEvents.mockImplementation(async () => {
    throw Object.assign(new Error('socket closed'), { name: 'NetworkError' });
  });
  api.request.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1')
      return conversation([{ id: 'm2', role: 'assistant', content: ANSWER }]);
    if (path === '/runs/run-1')
      return { status: 'completed', partial_text: '', coverage: null };
    return {};
  });

  await instance.watch('teach', 'run-1', 'conv-1', false);

  expect(instance.state.messages.teach.map((m: any) => m.content)).toContain(ANSWER);
  expect(instance.state.busy.teach).toBe(false);
  // One reconnect attempt and no more: the retry budget is per run, so an outage cannot turn
  // into an unbounded loop (and the answer was never regenerated — nothing here calls a model).
  expect(api.streamEvents).toHaveBeenCalledTimes(2);
});

it('never overwrites the conversation the learner has moved to', async () => {
  const instance = page();
  instance.state.conv.teach = 'conv-2';
  instance.state.messages.teach = [{ id: 'other', role: 'assistant', content: '另一段对话的回答' }];
  instance.setLane('busy', 'teach', true);
  api.request.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1')
      return conversation([{ id: 'm2', role: 'assistant', content: ANSWER }]);
    if (path === '/runs/run-1')
      return { status: 'completed', partial_text: '', coverage: null };
    return {};
  });

  await instance.watch('teach', 'run-1', 'conv-1', false);

  expect(instance.state.messages.teach).toEqual([{ id: 'other', role: 'assistant', content: '另一段对话的回答' }]);
  expect(instance.state.status.teach).toContain('历史对话');
  expect(instance.state.busy.teach).toBe(false);
});

it('a superseded watcher cannot clear a newer run and reconcile is idempotent', async () => {
  const instance = page();
  instance.state.conv.teach = 'conv-1';
  instance.state.inputs.teach = '草稿不能丢';
  instance.state.attachments.teach = [{ id: 'a1' }];
  instance.state.pair = 'pair-1';
  api.request.mockImplementation(async (path: string) => {
    if (path === '/conversations/conv-1')
      return conversation([{ id: 'm2', role: 'assistant', content: ANSWER }]);
    if (path === '/runs/run-1')
      return { status: 'completed', partial_text: '', coverage: null };
    return {};
  });

  const first = await instance.reconcile('teach', 'conv-1', 'run-1');
  const second = await instance.reconcile('teach', 'conv-1', 'run-1');
  expect([first, second]).toEqual([true, true]);
  expect(instance.state.messages.teach.map((m: any) => m.content)).toEqual([ANSWER]);
  // The composer, its attachments and the Pair binding are never touched by a reconcile.
  expect(instance.state.inputs.teach).toBe('草稿不能丢');
  expect(instance.state.attachments.teach).toEqual([{ id: 'a1' }]);
  expect(instance.state.pair).toBe('pair-1');

  // A newer run owns the lane: the late one must not write into it.
  instance.state.run.teach = 'run-2';
  instance.state.messages.teach = [{ id: 'newer', role: 'assistant', content: '新的回答' }];
  const refused = await instance.reconcile('teach', 'conv-1', 'run-1');
  expect(refused).toBe(false);
  expect(instance.state.messages.teach).toEqual([{ id: 'newer', role: 'assistant', content: '新的回答' }]);

  // A stale controller is refused too, so an aborted watcher cannot clear a live one's busy.
  instance.state.run.teach = null;
  instance.state.busy.teach = true;
  instance.controllers.teach = 'current';
  instance.recoverOrphanedAnswer('teach', 'conv-1', 'stale');
  expect(instance.state.busy.teach).toBe(true);
  instance.recoverOrphanedAnswer('teach', 'conv-1', 'current');
  expect(instance.state.busy.teach).toBe(false);
});
