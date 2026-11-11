import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('./api.js', () => api);
import { VisualAssetCard } from './VisualAssetCard.jsx';
import { VisualJobStatus } from './VisualJobStatus.jsx';

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('private video asset', () => {
  it('renders a named native download link for authenticated media', async () => {
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:private-video');
      static revokeObjectURL = vi.fn();
    });
    api.request.mockResolvedValue({ blob: async () => new Blob(['transport-fixture'], { type: 'video/mp4' }) });

    const { unmount } = render(<VisualAssetCard
      asset={{ id: 'video-1', content_url: '/visual-assets/video-1/content', mime_type: 'video/mp4', alt_text: 'Course motion' } as any}
      t={(key: string) => key}
    />);
    await screen.findByLabelText('Course motion');

    const link = screen.getByRole('link', { name: 'visual.download' });
    expect(link).toHaveAttribute('href', 'blob:private-video');
    expect(link).toHaveAttribute('download', 'coursejesus-visual-video-1.mp4');
    unmount();
  });

  it('keeps trusted diagrams distinct for readable mobile sizing', async () => {
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:private-svg');
      static revokeObjectURL = vi.fn();
    });
    api.request.mockResolvedValue({ blob: async () => new Blob(['<svg/>'], { type: 'image/svg+xml' }) });
    const {unmount} = render(<VisualAssetCard asset={{ id:'diagram', content_url:'/visual-assets/diagram/content', mime_type:'image/svg+xml', alt_text:'K-means worked example' } as any}/>);
    expect(await screen.findByAltText('K-means worked example')).toHaveClass('visual-diagram');
    unmount();
  });
  it('shows deterministic VisualSpec labels as readable text below a raster image', async () => {
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:private-png');
      static revokeObjectURL = vi.fn();
    });
    api.request.mockResolvedValue({ blob: async () => new Blob(['png'], { type: 'image/png' }) });
    const {unmount} = render(<VisualAssetCard
      asset={{
        id: 'grounded-image',
        content_url: '/visual-assets/grounded-image/content',
        mime_type: 'image/png',
        alt_text: 'Motherboard components',
        labels: ['主板', 'CPU 插座／散热器区域'],
      } as any}
      t={(key: string) => key}
    />);

    expect(await screen.findByRole('list', {name: 'visual.labels'})).toHaveTextContent('主板');
    expect(screen.getByRole('list', {name: 'visual.labels'})).toHaveTextContent('CPU 插座／散热器区域');
    expect(screen.getByAltText('Motherboard components')).toHaveAttribute('src', 'blob:private-png');
    unmount();
  });
  it('explains a text-only completion without showing an empty asset', () => {
    const {unmount} = render(<VisualJobStatus job={{id:'no-structure', status:'COMPLETED', renderer:'NONE', assets:[]}} t={key => key} onCancel={vi.fn()} onRetry={vi.fn()} onFallback={vi.fn()}/>);
    expect(screen.getByText('visual.insufficientStructure')).toBeInTheDocument();
    unmount();
  });
  it('renders authenticated video bytes with native playback controls and no autoplay', async () => {
    const revoke = vi.fn();
    vi.stubGlobal('URL', class extends URL {
      static createObjectURL = vi.fn(() => 'blob:private-video');
      static revokeObjectURL = revoke;
    });
    api.request.mockResolvedValue({ blob: async () => new Blob(['transport-fixture'], { type: 'video/mp4' }) });
    const { unmount } = render(<VisualAssetCard asset={{ id: 'video-1', content_url: '/visual-assets/video-1/content', mime_type: 'video/mp4', alt_text: 'Course motion' } as any}/>);
    const video = await screen.findByLabelText('Course motion');
    expect(video.tagName).toBe('VIDEO');
    expect(video).toHaveAttribute('controls');
    expect(video).toHaveAttribute('playsinline');
    expect(video).not.toHaveAttribute('autoplay');
    expect(api.request).toHaveBeenCalledWith('/visual-assets/video-1/content', { raw: true });
    unmount();
    await waitFor(() => expect(revoke).toHaveBeenCalledWith('blob:private-video'));
  });
});
