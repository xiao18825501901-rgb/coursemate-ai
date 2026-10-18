import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { LanguageControl, UiLocaleProvider } from './UiLocale';
import { PointAssessmentSetup } from './PointAssessmentSetup.jsx';

beforeEach(() => localStorage.clear());

it('allows an explicit question-language choice without invoking point preparation', () => {
  const choose = vi.fn(), prepare = vi.fn();
  render(<UiLocaleProvider><PointAssessmentSetup
    setup={{status: 'ASSESSMENT_POINTS_NOT_READY', points: [], content_language: 'zh-CN',
      next_action: 'release_qualification_required', candidate_target_count: 4}}
    slots={[]} course={{code: 'TEST_ONLY'}} node={{title: 'Original topic'}} busy={false}
    formsFor={() => []} onPrepare={prepare} onChooseLanguage={choose}
    onType={vi.fn()} onForm={vi.fn()} onPurpose={vi.fn()} onAdd={vi.fn()}
    onRemove={vi.fn()} onStart={vi.fn()} prepareUncertain={false}
  /></UiLocaleProvider>);
  const language = screen.getByRole('combobox', {name: '本次题目语言'});
  expect(language).toHaveValue('zh-CN');
  fireEvent.change(language, {target: {value: 'en'}});
  expect(choose).toHaveBeenCalledWith('en');
  expect(prepare).not.toHaveBeenCalled();
});

function view(nextAction: string) {
  const prepare = vi.fn();
  const setup = Object.freeze({ status: 'ASSESSMENT_POINTS_NOT_READY', points: [],
    next_action: nextAction, content_language: 'en', point_count: null, candidate_target_count: 4 });
  render(<UiLocaleProvider><LanguageControl/><PointAssessmentSetup
    setup={setup} slots={[]} course={{ code: 'TEST_ONLY' }} node={{ title: 'Original topic' }}
    busy={false} formsFor={() => []} onPrepare={prepare}
    onType={vi.fn()} onForm={vi.fn()} onPurpose={vi.fn()} onAdd={vi.fn()}
    onRemove={vi.fn()} onStart={vi.fn()} prepareUncertain={false}
  /></UiLocaleProvider>);
  return { prepare, setup };
}

it('does not preserve the retired formal-qualification gate in either UI language', () => {
  const { prepare, setup } = view('release_qualification_required');
  expect(screen.getByRole('status').textContent).toContain('依据当前课程资料准备');
  expect(screen.getByRole('status').textContent).not.toContain('质量验证');
  expect(screen.getByText('考点数待确认')).toBeInTheDocument();
  expect(screen.getByText('4 项待确认目标')).toBeInTheDocument();
  expect(screen.queryByText('0 个考点')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '准备考点' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'English' }));
  expect(screen.getByRole('status').textContent).toContain('current course sources');
  expect(screen.getByRole('status').textContent).not.toContain('quality verification');
  expect(screen.getByText('Assessable point count: pending confirmation')).toBeInTheDocument();
  expect(screen.getByText('4 targets awaiting confirmation')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Prepare assessable points' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Prepare assessable points' }));
  expect(prepare).toHaveBeenCalledTimes(1);
  expect(setup.content_language).toBe('en');
});

it('does not advertise a fresh prepare for an uncertain original request', () => {
  const { prepare } = view('reconcile_original_request');
  expect(screen.getByRole('status').textContent).toContain('不会重复发送请求');
  expect(screen.getByRole('button', { name: '准备考点' })).toBeDisabled();
  expect(prepare).not.toHaveBeenCalled();
});

