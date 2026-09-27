import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
// @ts-ignore delivered JSX module
import { Learn } from './ui/pages.jsx';

const api = vi.hoisted(() => ({
  requestExerciseHint: vi.fn(),
  submitPracticeAttempt: vi.fn(),
  createExercise: vi.fn(),
  getExercise: vi.fn(),
  configureLearningDiagnostic: vi.fn(),
  skipLearningDiagnostic: vi.fn(),
  markLearningDiagnosticUnsure: vi.fn(),
}));
vi.mock('./ui/api.js', async original => ({ ...await original<object>(), ...api }));

function page() {
  const instance = new Learn({
    course: { id: 'course-1' },
    toast: vi.fn(),
    config: { provider_mode: 'test', model: 'FAKE_TEST_ONLY' },
    user: { name: 'Student' },
  }) as any;
  instance.setState = (value: any, callback?: () => void) => {
    instance.state = {
      ...instance.state,
      ...(typeof value === 'function' ? value(instance.state) : value),
    };
    callback?.();
  };
  instance.state.pair = 'pair-1';
  return instance;
}

beforeEach(() => {
  api.requestExerciseHint.mockReset();
  api.submitPracticeAttempt.mockReset();
  api.createExercise.mockReset();
  api.getExercise.mockReset();
  api.configureLearningDiagnostic.mockReset();
  api.skipLearningDiagnostic.mockReset();
  api.markLearningDiagnosticUnsure.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

it('re-enables background reconciliation when StrictMode remounts the learning workspace', () => {
  const instance = page();
  instance.unmounted = true;
  instance.load = vi.fn();

  instance.componentDidMount();

  expect(instance.unmounted).toBe(false);
  expect(instance.load).toHaveBeenCalledTimes(1);
  instance.componentWillUnmount();
});

it('polls a saved asynchronous attempt until the canonical evaluation is projected', async () => {
  vi.useFakeTimers();
  const instance = page();
  instance.unmounted = false;
  const base = { id: 'exercise-1', latest_attempt: { status: 'PENDING' } };
  api.getExercise.mockResolvedValue({
    id: 'exercise-1',
    latest_attempt: { id: 'attempt-1', status: 'GRADED', feedback: 'Evaluated' },
  });

  const polling = instance.pollPracticeEvaluation('exercise-1', base);
  await vi.advanceTimersByTimeAsync(1000);
  await polling;

  expect(api.getExercise).toHaveBeenCalledWith('exercise-1');
  expect(instance.state.exercises['exercise-1'].latest_attempt).toMatchObject({
    status: 'GRADED', feedback: 'Evaluated',
  });
});

it('requests a real hint and submits a learner answer without touching the teaching lane', async () => {
  const instance = page();
  const base = {
    id: 'exercise-1', node: 'node-1', revealed: false, hint_count: 0,
    latest_hint: null, latest_attempt: null, steps: [],
  };
  instance.state.messages.teach = [{ id: 'teaching-kept', text: 'left pane stays here' }];
  instance.state.practiceAnswers = { 'exercise-1': 'My bounded answer' };
  api.requestExerciseHint.mockResolvedValue({
    id: 'hint-1', assistance: 'HINT', independent: false, hint: 'Start from the rule.',
    strategy: 'Write the first intermediate.',
  });
  api.submitPracticeAttempt.mockResolvedValue({
    id: 'attempt-1', verdict: 'PARTIAL', feedback: 'Connect the intermediate to the conclusion.',
    strengths: ['Relevant setup'], gaps: ['Missing conclusion'], next_step: 'Add the conclusion.',
    criteria: [], assistance: 'HINT', independent: false, status: 'GRADED',
  });

  await instance.requestPracticeHint('exercise-1', base);
  await instance.submitPracticeAnswer('exercise-1', base);

  expect(api.requestExerciseHint).toHaveBeenCalledWith('exercise-1');
  expect(api.submitPracticeAttempt).toHaveBeenCalledWith('exercise-1', 'My bounded answer');
  expect(instance.state.exercises['exercise-1'].latest_hint.id).toBe('hint-1');
  expect(instance.state.exercises['exercise-1'].latest_attempt.id).toBe('attempt-1');
  expect(instance.state.messages.teach).toEqual([{ id: 'teaching-kept', text: 'left pane stays here' }]);
});

it('renders accessible attempt, hint, reveal controls and re-practices the same node', async () => {
  const instance = page();
  const message: any = {
    exercise: 'exercise-1',
    exercise_state: {
      id: 'exercise-1', node: 'node-1', revealed: false, hint_count: 0,
      latest_hint: null, latest_attempt: null, steps: [],
    },
  };
  const first = render(instance.renderExercise(message));
  expect(screen.getByRole('textbox', { name: '练习答案' })).toBeVisible();
  expect(screen.getByRole('button', { name: '提交作答' })).toBeVisible();
  expect(screen.getByRole('button', { name: '给我提示' })).toBeVisible();
  expect(screen.getByRole('button', { name: '显示答案' })).toBeVisible();
  expect(first.container.textContent).not.toContain('LearningBridge');
  first.unmount();

  api.createExercise.mockResolvedValue({ id: 'run-2' });
  instance.watchExercise = vi.fn().mockResolvedValue(undefined);
  await instance.doExercise('node-1');
  expect(api.createExercise).toHaveBeenCalledWith('course-1', 'node-1', 'pair-1', null, null);
  instance.state.busy.problem = false;

  message.exercise_state.revealed = true;
  message.exercise_state.steps = [{ step_id: 'step-1', ordinal: 1, title: 'Apply', text: 'Result' }];
  render(instance.renderExercise(message));
  const again = screen.getByRole('button', { name: '再练同一目标' });
  fireEvent.click(again);
  await waitFor(() => expect(api.createExercise).toHaveBeenCalledTimes(2));
  expect(api.createExercise).toHaveBeenLastCalledWith('course-1', 'node-1', 'pair-1', null, null);
});

it('offers a skippable three-item diagnostic and records unsure without a formal grade', async () => {
  const instance = page();
  const base: any = {
    id: 'exercise-1', node: 'node-1', learning_cycle_id: 'cycle-1', revealed: false,
    evidence_card: {
      diagnostic: {
        status: 'NOT_STARTED', purpose: 'PRACTICE_NOT_FORMAL_ASSESSMENT',
        skippable: true, items: [],
      },
    },
  };
  const first = render(instance.renderExercise({ exercise: 'exercise-1', exercise_state: base }));
  expect(screen.getByRole('region', { name: '可选三题短诊断' })).toBeVisible();
  expect(screen.getByRole('button', { name: '开始短诊断' })).toBeVisible();
  expect(screen.getByRole('button', { name: '跳过' })).toBeVisible();
  first.unmount();

  const items = [1, 2, 3].map(index => ({
    id: `assignment-${index}`,
    question_revision_id: `question-${index}`,
    prompt: `Diagnostic ${index}`,
    response: null,
  }));
  api.configureLearningDiagnostic.mockResolvedValue({
    status: 'AVAILABLE', purpose: 'PRACTICE_NOT_FORMAL_ASSESSMENT',
    skippable: true, items,
  });
  await instance.startDiagnostic('exercise-1', base);
  expect(api.configureLearningDiagnostic).toHaveBeenCalledWith('course-1', 'cycle-1');
  expect(instance.state.exercises['exercise-1'].evidence_card.diagnostic.items).toHaveLength(3);

  const configured = instance.state.exercises['exercise-1'];
  api.markLearningDiagnosticUnsure.mockResolvedValue({
    status: 'AVAILABLE',
    responses: { 'question-1': 'UNSURE' },
    formal_assessment_changed: false,
  });
  await instance.diagnosticUnsure('exercise-1', configured, 'assignment-1');
  expect(api.markLearningDiagnosticUnsure).toHaveBeenCalledWith(
    'course-1', 'cycle-1', 'assignment-1',
  );
  expect(
    instance.state.exercises['exercise-1'].evidence_card.diagnostic.items[0].response,
  ).toBe('UNSURE');
});
