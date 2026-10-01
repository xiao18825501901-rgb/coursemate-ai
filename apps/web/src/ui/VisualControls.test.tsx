import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  listMessageVisuals: vi.fn(),
  createVisual: vi.fn(),
  getVisualJob: vi.fn(),
  cancelVisualJob: vi.fn(),
  retryVisualJob: vi.fn(),
  fallbackVisualJob: vi.fn(),
}));

vi.mock('./api.js', async () => ({ ...api }));

import { VisualControls } from './VisualControls.jsx';
import { VisualJobStatus } from './VisualJobStatus.jsx';

describe('Visual Learning controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listMessageVisuals.mockResolvedValue({ items: [] });
  });

  it('creates only an action request bound to the current course, pair and message', async () => {
    api.createVisual.mockResolvedValue({
      id: 'job-1', status: 'COMPLETED', assets: [], retry_count: 0, cache_hit: false,
    });
    render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-1' } as any}/>);
    await waitFor(() => expect(api.listMessageVisuals).toHaveBeenCalledWith('course-1', 'message-1'));
    fireEvent.click(screen.getByRole('button', { name: '显示图解' }));
    await waitFor(() => expect(api.createVisual).toHaveBeenCalledWith('course-1', 'message-1', 'pair-1', 'diagram'));
    expect(screen.queryByText(/workflow|checkpoint|KSampler/i)).not.toBeInTheDocument();
  });

  it('keeps the text usable while exposing safe retry and deterministic fallback', () => {
    const onRetry = vi.fn();
    const onFallback = vi.fn();
    render(<VisualJobStatus job={{ id: 'job-1', status: 'FAILED', error_code: 'PROVIDER_TIMEOUT', retry_count: 0, fallback_available: true, assets: [] } as any} onCancel={vi.fn()} onRetry={onRetry} onFallback={onFallback}/>);
    expect(screen.getByText(/文字回答仍可正常使用/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetry).toHaveBeenCalledWith('job-1');
    fireEvent.click(screen.getByRole('button', { name: '使用确定性图解' }));
    expect(onFallback).toHaveBeenCalledWith('job-1');
  });

  it.each([
    ['QUEUED', '等待生成'],
    ['PLANNING', '正在规划'],
    ['RENDERING', '正在生成'],
    ['VALIDATING', '正在校验'],
    ['COMPLETED', '已完成'],
    ['CANCELLED', '已取消'],
    ['RETRYING', '正在重试'],
  ])('projects the %s state accessibly', (status, label) => {
    const { unmount } = render(<VisualJobStatus job={{ id: `job-${status}`, status, retry_count: 0, fallback_available: false, assets: [] } as any} onCancel={vi.fn()} onRetry={vi.fn()} onFallback={vi.fn()}/>);
    expect(screen.getByText(label)).toBeInTheDocument();
    const region = screen.getByText(label).closest('section');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-busy', ['QUEUED', 'PLANNING', 'RENDERING', 'VALIDATING', 'RETRYING'].includes(status) ? 'true' : 'false');
    unmount();
  });

  it('labels a completed cache hit without exposing infrastructure terms', () => {
    render(<VisualJobStatus job={{ id: 'job-cache', status: 'COMPLETED', retry_count: 0, cache_hit: true, fallback_available: false, assets: [] } as any} onCancel={vi.fn()} onRetry={vi.fn()} onFallback={vi.fn()}/>);
    expect(screen.getByText('已从安全缓存恢复')).toBeInTheDocument();
    expect(screen.queryByText(/workflow|checkpoint|KSampler|EAS/i)).not.toBeInTheDocument();
  });
});
