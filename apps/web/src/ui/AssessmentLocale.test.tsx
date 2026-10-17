import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { AssessmentWorkspace } from './pages.jsx';
import { LanguageControl, UiLocaleProvider } from './UiLocale';

class AssessmentHarness extends AssessmentWorkspace {
  componentDidMount() {}
  componentWillUnmount() {}
}

beforeEach(() => localStorage.clear());

it('switches assessment system copy without changing the assessment draft or question content', async () => {
  let workspace: AssessmentHarness | null = null;
  const question = Object.freeze({
    id: 'question-1', ordinal: 1, question_type: 'SHORT_TEXT', marks: 100,
    prompt: 'Original graph theory question', options: [],
  });
  render(<UiLocaleProvider><LanguageControl/><AssessmentHarness
    ref={value => { workspace = value; }}
    course={{ id: 'course-1', code: 'CS-ORIGINAL' }}
    node={{ id: 'node-1', title: 'Original topic title' }}
    onExit={() => undefined} toast={() => undefined}
  /></UiLocaleProvider>);

  await act(async () => workspace!.setState({
      view: { id: 'session-1', status: 'IN_PROGRESS', questions: [question] },
      setup: { minimum_questions: 1, maximum_questions: 2, policy_version: 'legacy' },
      slots: [{ slot_id: 'slot-1', question_type: 'SHORT_TEXT', task_form: 'analysis' }],
      answers: { 'question-1': 'Original student answer' },
    }));

  expect(screen.getByRole('dialog', { name: '测评工作区' })).toBeInTheDocument();
  expect(screen.getByText('Original graph theory question')).toBeInTheDocument();
  expect(screen.getByDisplayValue('Original student answer')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: 'English' }));

  expect(screen.getByRole('dialog', { name: 'Assessment workspace' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Submit answers' })).toBeInTheDocument();
  expect(screen.getByText('Original graph theory question')).toBeInTheDocument();
  expect(screen.getByDisplayValue('Original student answer')).toBeInTheDocument();
  expect((workspace as any).state.view.id).toBe('session-1');
  expect((workspace as any).state.answers['question-1']).toBe('Original student answer');
});
