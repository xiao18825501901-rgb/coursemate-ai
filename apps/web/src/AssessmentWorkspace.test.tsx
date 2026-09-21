import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
// @ts-ignore delivered JSX component
import { AssessmentWorkspace } from './ui/pages.jsx';
// @ts-ignore delivered JS API
import { getAssessment, getAssessmentSession, loadAssessmentDraft, startAssessment } from './ui/api.js';

vi.mock('./ui/api.js', () => ({
  getAssessment: vi.fn(),
  startAssessment: vi.fn(),
  getAssessmentSession: vi.fn(),
  submitAssessment: vi.fn(),
  abandonAssessment: vi.fn(),
  saveAssessmentDraft: vi.fn(),
  loadAssessmentDraft: vi.fn(),
  cancelPreparation: vi.fn(),
  resumePreparation: vi.fn(),
  createAssessmentExplanation: vi.fn(),
  key: () => 'key-1',
}));

const questions = [
  { id: 'b1', ordinal: 1, marks: 10, question_type: 'NUMERIC', prompt: '计算 2 + 3', options: [], verification_method: 'DETERMINISTIC' },
  { id: 'b2', ordinal: 2, marks: 15, question_type: 'MCQ_SINGLE', prompt: '选择结果', options: ['5', '6'], verification_method: 'DETERMINISTIC' },
  { id: 'b3', ordinal: 3, marks: 20, question_type: 'SHORT_TEXT', prompt: '写出英文', options: [], verification_method: 'DETERMINISTIC' },
  { id: 'b4', ordinal: 4, marks: 25, question_type: 'NUMERIC', prompt: '计算 7 + 2', options: [], verification_method: 'AI_REVIEWED' },
  { id: 'b5', ordinal: 5, marks: 30, question_type: 'EXPLANATION', prompt: '解释原理', options: [], verification_method: 'AI_REVIEWED' },
];

describe('AssessmentWorkspace', () => {
  beforeEach(() => {
    vi.mocked(getAssessment).mockResolvedValue({ status: 'NOT_ASSESSED', session: null });
    vi.mocked(getAssessmentSession).mockResolvedValue({
      id: 's1',
      status: 'IN_PROGRESS',
      questions,
      raw_score: null,
      grade: { label: null },
      node_id: 'n1',
    });
    vi.mocked(loadAssessmentDraft).mockResolvedValue({ draft: null });
    vi.mocked(startAssessment).mockResolvedValue({ id: 's1', status: 'IN_PROGRESS' });
  });

  it('renders a fullscreen workspace with course, node, status and exit', async () => {
    render(<AssessmentWorkspace course={{ code: 'CS3481' }} node={{ title: 'DBSCAN' }} toast={vi.fn()} onExit={vi.fn()} />);
    expect(screen.getByRole('dialog', { name: '五题测评工作区' })).toBeVisible();
    expect(screen.getByText('CS3481')).toBeVisible();
    expect(screen.getByText(/DBSCAN/)).toBeVisible();
    expect(screen.getByRole('button', { name: '退出' })).toBeVisible();
    expect(await screen.findByRole('button', { name: '开始测评（5 题）' })).toBeVisible();
  });

  it('shows all five questions with marks and a single unified composer', async () => {
    vi.mocked(getAssessment).mockResolvedValue({ status: 'IN_PROGRESS', session: 's1' });
    render(<AssessmentWorkspace course={{ code: 'CS3481' }} node={{ title: 'DBSCAN' }} toast={vi.fn()} onExit={vi.fn()} />);
    expect(await screen.findByText('计算 2 + 3')).toBeVisible();
    expect(screen.getByText('选择结果')).toBeVisible();
    expect(screen.getByText('写出英文')).toBeVisible();
    expect(screen.getByText('解释原理')).toBeVisible();
    expect(screen.getByText(/10 分/)).toBeVisible();
    expect(screen.getByText(/30 分/)).toBeVisible();
    expect(screen.getByLabelText('统一答案')).toBeVisible();
    expect(screen.getByRole('button', { name: '保存草稿' })).toBeVisible();
    expect(screen.getByRole('button', { name: '提交答案' })).toBeVisible();
    // Reference solutions must not be rendered before submit.
    expect(screen.queryByText(/参考解/)).not.toBeInTheDocument();
  });

  it('marks AI-reviewed diagnostic questions without pretending an official grade', async () => {
    vi.mocked(getAssessment).mockResolvedValue({ status: 'IN_PROGRESS', session: 's1' });
    render(<AssessmentWorkspace course={{ code: 'CS3481' }} node={{ title: 'DBSCAN' }} toast={vi.fn()} onExit={vi.fn()} />);
    await screen.findByText('解释原理');
    expect(screen.getAllByText(/AI参考自测/).length).toBe(2);
  });

  it('shows raw score without a school grade mapping', async () => {
    vi.mocked(getAssessment).mockResolvedValue({ status: 'IN_PROGRESS', session: 's1' });
    vi.mocked(getAssessmentSession).mockResolvedValue({
      id: 's1',
      status: 'GRADED',
      questions,
      raw_score: 78,
      grade: { label: null, mapping_status: 'UNCONFIGURED', numeric_value: null, message: '评分映射待配置' },
      node_id: 'n1',
    });
    render(<AssessmentWorkspace course={{ code: 'CS3481' }} node={{ title: 'DBSCAN' }} toast={vi.fn()} onExit={vi.fn()} />);
    expect(await screen.findByText('原始分：78 / 100')).toBeVisible();
  });
});
