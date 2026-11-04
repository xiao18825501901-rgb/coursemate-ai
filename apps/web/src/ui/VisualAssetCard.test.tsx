import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('./api.js', () => api);
import { VisualAssetCard } from './VisualAssetCard.jsx';

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('private video asset', () => {
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
