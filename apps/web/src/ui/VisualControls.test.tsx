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

  it('keeps every visual action disabled while a listed job is still processing', async () => {
    api.listMessageVisuals.mockResolvedValue({
      items: [{ id: 'job-active', action: 'visual', status: 'RENDERING', retry_count: 0, cache_hit: false, assets: [] }],
    });
    const { container } = render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-active' } as any}/>);

    await waitFor(() => expect(api.listMessageVisuals).toHaveBeenCalledWith('course-1', 'message-active'));
    await waitFor(() => {
      const actions = container.querySelector('.visual-actions');
      expect(actions).toHaveAttribute('aria-busy', 'true');
      if (actions == null) throw new Error('visual actions were not rendered');
      expect([...actions.querySelectorAll('button')].every(button => button.disabled)).toBe(true);
    });
    expect(api.createVisual).not.toHaveBeenCalled();
  });

  it('opens consent instead of submitting an image job while assistance is off', async () => {
    const requestAssistance = vi.fn();
    render(<VisualControls enabled assistanceEnabled={false} requestAssistance={requestAssistance} courseId="course-1" pairId="pair-1" message={{ id: 'message-1' } as any}/>);
    await waitFor(() => expect(api.listMessageVisuals).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: '生成图片' }));
    expect(requestAssistance).toHaveBeenCalledTimes(1);
    expect(api.createVisual).not.toHaveBeenCalled();
  });

  it('never starts an automatic job while assistance is off', async () => {
    render(<VisualControls enabled autoEnabled assistanceEnabled={false} courseId="course-1" pairId="pair-1" message={{ id: 'message-auto-off' } as any}/>);
    await waitFor(() => expect(api.listMessageVisuals).toHaveBeenCalled());
    expect(api.createVisual).not.toHaveBeenCalled();
  });

  it('starts one idempotent automatic job after text when assistance is enabled', async () => {
    api.createVisual.mockResolvedValue({ id: 'job-auto', status: 'COMPLETED', assets: [] });
    render(<VisualControls enabled autoEnabled assistanceEnabled courseId="course-1" pairId="pair-1" message={{ id: 'message-auto-on' } as any}/>);
    await waitFor(() => expect(api.createVisual).toHaveBeenCalledWith('course-1', 'message-auto-on', 'pair-1', 'auto', 'visual-auto-message-auto-on'));
    expect(api.createVisual).toHaveBeenCalledTimes(1);
  });

  it('shows only the newest result for each teaching action while retaining older jobs in storage', async () => {
    api.listMessageVisuals.mockResolvedValue({
      items: [
        { id: 'job-old', action: 'diagram', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-old', mime_type: 'image/svg+xml', alt_text: 'main concept', content_url: '/old' }] },
        { id: 'job-new', action: 'diagram', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-new', mime_type: 'image/svg+xml', alt_text: 'K-means assignments and SSE', content_url: '/new' }] },
      ],
    });
    render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-duplicate' } as any}/>);

    expect(await screen.findByText('K-means assignments and SSE')).toBeInTheDocument();
    expect(screen.queryByText('main concept')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '历史版本（1）' }));
    expect(screen.getByText('main concept')).toBeInTheDocument();
  });

  it('orders the newest result across teaching actions before older action results', async () => {
    api.listMessageVisuals.mockResolvedValue({
      items: [
        { id: 'job-old-animate', action: 'animate', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-old-animate', mime_type: 'image/svg+xml', alt_text: 'Old placeholder animation', content_url: '/old-animation' }] },
        { id: 'job-old-visual', action: 'visual', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-old-visual', mime_type: 'image/svg+xml', alt_text: 'Old placeholder image', content_url: '/old-image' }] },
        { id: 'job-new-diagram', action: 'diagram', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-new-diagram', mime_type: 'image/svg+xml', alt_text: 'K-means assignments and SSE', content_url: '/new-diagram' }] },
      ],
    });
    const { container } = render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-cross-action' } as any}/>);

    await waitFor(() => expect(container.querySelectorAll('.visual-job')).toHaveLength(3));
    const visibleText = [...container.querySelectorAll('.visual-job')].map(card => card.textContent);
    expect(visibleText).toEqual([
      expect.stringContaining('K-means assignments and SSE'),
      expect.stringContaining('Old placeholder image'),
      expect.stringContaining('Old placeholder animation'),
    ]);
  });

  it('moves legacy placeholder media into history instead of presenting it as current teaching', async () => {
    api.listMessageVisuals.mockResolvedValue({
      items: [
        { id: 'job-legacy-visual', action: 'visual', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-legacy-visual', mime_type: 'image/svg+xml', alt_text: 'Show the supported concept.', content_url: '/legacy-image' }] },
        { id: 'job-legacy-animate', action: 'animate', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-legacy-animate', mime_type: 'image/svg+xml', alt_text: 'Show the supported concept.', content_url: '/legacy-animation' }] },
        { id: 'job-grounded', action: 'diagram', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-grounded', mime_type: 'image/svg+xml', alt_text: 'K-means assignments and SSE', content_url: '/grounded' }] },
      ],
    });
    render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-legacy' } as any}/>);

    expect(await screen.findByText('K-means assignments and SSE')).toBeInTheDocument();
    expect(screen.queryByText('Show the supported concept.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '历史版本（2）' }));
    expect(screen.getAllByText('Show the supported concept.')).toHaveLength(2);
  });

  it('moves server-identified legacy placeholder bytes into history even when alt text is course-specific', async () => {
    api.listMessageVisuals.mockResolvedValue({
      items: [
        { id: 'job-legacy-v3', action: 'visual', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-legacy-v3', mime_type: 'image/svg+xml', alt_text: 'DBSCAN needs Eps and MinPts.', semantic_validation: 'PASS', legacy_placeholder: true, content_url: '/legacy-v3' }] },
        { id: 'job-grounded-v4', action: 'diagram', status: 'COMPLETED', retry_count: 0, cache_hit: false, assets: [{ id: 'asset-grounded-v4', mime_type: 'image/svg+xml', alt_text: 'DBSCAN core, border, and noise points', semantic_validation: 'PASS', legacy_placeholder: false, content_url: '/grounded-v4' }] },
      ],
    });
    render(<VisualControls enabled courseId="course-1" pairId="pair-1" message={{ id: 'message-legacy-v3' } as any}/>);

    expect(await screen.findByText('DBSCAN core, border, and noise points')).toBeInTheDocument();
    expect(screen.queryByText('DBSCAN needs Eps and MinPts.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '历史版本（1）' }));
    expect(screen.getByText('DBSCAN needs Eps and MinPts.')).toBeInTheDocument();
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

  it('offers a deterministic alternative beside a limited completed visual', () => {
    const onFallback = vi.fn();
    render(<VisualJobStatus
      job={{
        id: 'job-limited',
        status: 'COMPLETED',
        retry_count: 0,
        fallback_available: true,
        assets: [{
          id: 'asset-limited',
          mime_type: 'video/mp4',
          alt_text: 'actuator arm motion',
          semantic_validation: 'LIMITED',
          legacy_placeholder: false,
          content_url: '/limited-video',
        }],
      } as any}
      onCancel={vi.fn()}
      onRetry={vi.fn()}
      onFallback={onFallback}
    />);

    fireEvent.click(screen.getByRole('button', { name: '使用确定性图解' }));
    expect(onFallback).toHaveBeenCalledWith('job-limited');
  });

  it.each([
    ['QUEUED', '等待生成'],
    ['WAITING_FOR_RENDERER', '正在唤醒图片生成服务'],
    ['PLANNING', '正在规划'],
    ['RENDERING', '正在生成'],
    ['VALIDATING', '正在校验'],
    ['COMPLETED', '已完成'],
    ['UNKNOWN', '结果待确认'],
    ['CANCELLED', '已取消'],
    ['RETRYING', '正在重试'],
  ])('projects the %s state accessibly', (status, label) => {
    const { unmount } = render(<VisualJobStatus job={{ id: `job-${status}`, status, retry_count: 0, fallback_available: false, assets: [] } as any} onCancel={vi.fn()} onRetry={vi.fn()} onFallback={vi.fn()}/>);
    expect(screen.getByText(label)).toBeInTheDocument();
    const region = screen.getByText(label).closest('section');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toHaveAttribute('aria-busy', ['QUEUED', 'PLANNING', 'WAITING_FOR_RENDERER', 'RENDERING', 'VALIDATING', 'RETRYING'].includes(status) ? 'true' : 'false');
    unmount();
  });

  it('labels a completed cache hit without exposing infrastructure terms', () => {
    render(<VisualJobStatus job={{ id: 'job-cache', status: 'COMPLETED', retry_count: 0, cache_hit: true, fallback_available: false, assets: [] } as any} onCancel={vi.fn()} onRetry={vi.fn()} onFallback={vi.fn()}/>);
    expect(screen.getByText('已从安全缓存恢复')).toBeInTheDocument();
    expect(screen.queryByText(/workflow|checkpoint|KSampler|EAS/i)).not.toBeInTheDocument();
  });
});
