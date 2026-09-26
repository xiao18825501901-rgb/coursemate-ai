import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Learn } from './ui/pages.jsx';


function page(status: string, message = ''): any {
  const instance = new Learn({
    course: { id: 'private-course', code: 'PRIVATE', name: 'Private course' },
    toast: vi.fn(),
  }) as any;
  instance.state = {
    ...instance.state,
    knowledgeBuild: { status, message },
  };
  return instance;
}


describe('automatic knowledge-map status', () => {
  it('shows the batch/build state instead of a manual generation instruction', () => {
    render(page('BUILDING').knowledgeEmptyState());

    expect(screen.getByText('正在整理课程知识点')).toBeInTheDocument();
    expect(screen.getByText(/冻结的课程资料/)).toBeInTheDocument();
    expect(screen.queryByText(/手动生成/)).not.toBeInTheDocument();
  });

  it('reports unreadable or empty courses accurately without fake chapters', () => {
    render(page('WAITING_SOURCE').knowledgeEmptyState());

    expect(screen.getByText('还没有可读的课程资料')).toBeInTheDocument();
    expect(screen.getByText(/自动生成/)).toBeInTheDocument();
    expect(screen.queryByText('第一章')).not.toBeInTheDocument();
  });

  it('makes an uncertain paid-operation state explicit', () => {
    render(page('UNKNOWN').knowledgeEmptyState());

    expect(screen.getByText('生成状态需要人工核对')).toBeInTheDocument();
    expect(screen.getByText(/不会自动重复收费/)).toBeInTheDocument();
  });
});
