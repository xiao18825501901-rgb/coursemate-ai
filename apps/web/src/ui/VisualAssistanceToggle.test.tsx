import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { VisualAssistanceConsent, VisualAssistanceToggle } from './VisualAssistanceToggle.jsx';

describe('visual assistance consent', () => {
  it('renders the server state accessibly and requests confirmation only while off', () => {
    const onEnableRequest = vi.fn();
    const onDisable = vi.fn();
    const { rerender } = render(
      <VisualAssistanceToggle enabled={false} busy={false} onEnableRequest={onEnableRequest} onDisable={onDisable}/>,
    );
    const off = screen.getByRole('button', { name: '图片/视频辅助 · 关闭' });
    expect(off).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(off);
    expect(onEnableRequest).toHaveBeenCalledTimes(1);
    expect(onDisable).not.toHaveBeenCalled();

    rerender(<VisualAssistanceToggle enabled busy={false} onEnableRequest={onEnableRequest} onDisable={onDisable}/>);
    const on = screen.getByRole('button', { name: '图片/视频辅助 · 已启用' });
    expect(on).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(on);
    expect(onDisable).toHaveBeenCalledTimes(1);
  });

  it('uses the exact product copy and never mentions provider infrastructure', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<VisualAssistanceConsent onConfirm={onConfirm} onCancel={onCancel} busy={false}/>);
    expect(screen.getByText(/启用后，CourseJesus 会在课程学习中按需生成/)).toBeInTheDocument();
    expect(screen.getByText(/文字回答仍会优先显示/)).toBeInTheDocument();
    expect(screen.queryByText(/ComfyUI|GPU|EAS|checkpoint|阿里云|CFG|KSampler/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '暂不启用' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: '确认启用' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
