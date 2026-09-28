import { beforeEach, expect, it, vi } from 'vitest';

// @ts-ignore delivered JSX module
import { Learn } from './ui/pages.jsx';

const api = vi.hoisted(() => ({
  request: vi.fn(),
  streamEvents: vi.fn(),
}));

vi.mock('./ui/api.js', async original => ({
  ...await original<object>(),
  ...api,
}));

beforeEach(() => {
  api.request.mockReset();
  api.streamEvents.mockReset();
});

it('recovers the same completed exercise run after SSE disconnect without a new POST', async () => {
  api.streamEvents.mockRejectedValueOnce(new Error('stream disconnected'));
  api.request.mockImplementation(async (path: string) => {
    if (path === '/runs/run-exercise-1') {
      return {
        id: 'run-exercise-1',
        status: 'completed',
        conversation: 'problem-conversation-1',
        partial_text: 'question text',
      };
    }
    if (path === '/conversations/problem-conversation-1') {
      return {
        messages: [{ id: 'message-1', role: 'assistant', text: 'question text' }],
      };
    }
    throw new Error(`unexpected GET ${path}`);
  });

  const page: any = new Learn({ course: { id: 'private-course-1' }, toast: vi.fn() });
  page.state = {
    ...page.state,
    pair: 'pair-1',
    run: { ...page.state.run, problem: 'run-exercise-1' },
    busy: { ...page.state.busy, problem: true },
  };
  page.setState = (value: any, callback?: () => void) => {
    const patch = typeof value === 'function' ? value(page.state) : value;
    page.state = { ...page.state, ...patch };
    callback?.();
  };

  await page.watchExercise('run-exercise-1', {
    courseId: 'private-course-1',
    pairId: 'pair-1',
  });

  expect(api.request).toHaveBeenCalledWith('/runs/run-exercise-1');
  expect(api.request).toHaveBeenCalledWith('/conversations/problem-conversation-1');
  expect(page.state.messages.problem).toEqual([
    { id: 'message-1', role: 'assistant', text: 'question text' },
  ]);
  expect(page.state.busy.problem).toBe(false);
  expect(page.state.run.problem).toBeNull();
});

it('does not project a completed exercise into a different Pair', async () => {
  api.streamEvents.mockRejectedValueOnce(new Error('stream disconnected'));
  let page: any;
  api.request.mockImplementation(async (path: string) => {
    if (path === '/runs/run-exercise-1') {
      page.state = { ...page.state, pair: 'pair-2' };
      return {
        id: 'run-exercise-1',
        status: 'completed',
        conversation: 'old-problem-conversation',
      };
    }
    throw new Error(`unexpected GET ${path}`);
  });

  page = new Learn({ course: { id: 'private-course-1' }, toast: vi.fn() });
  page.state = {
    ...page.state,
    pair: 'pair-1',
    messages: { ...page.state.messages, problem: [{ id: 'new-pair', text: 'keep me' }] },
    run: { ...page.state.run, problem: 'run-exercise-1' },
    busy: { ...page.state.busy, problem: true },
  };
  page.setState = (value: any, callback?: () => void) => {
    const patch = typeof value === 'function' ? value(page.state) : value;
    page.state = { ...page.state, ...patch };
    callback?.();
  };

  await page.watchExercise('run-exercise-1', {
    courseId: 'private-course-1',
    pairId: 'pair-1',
  });

  expect(api.request).not.toHaveBeenCalledWith('/conversations/old-problem-conversation');
  expect(page.state.messages.problem).toEqual([{ id: 'new-pair', text: 'keep me' }]);
});
