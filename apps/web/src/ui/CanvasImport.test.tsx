import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

// @ts-ignore delivered JSX component
import { CanvasImport } from './CanvasImport.jsx';
// @ts-ignore delivered JS client
import { connections, institutions, openTaskCredential, taskCourses } from './canvasImport.js';

vi.mock('./canvasImport.js', () => ({
  BRIDGE_STEPS: [], TOKEN_STEPS: [], TASK_CREDENTIAL_STEPS: [],
  TOKEN_WARNING: '', TASK_CREDENTIAL_WARNING: '',
  TASK_CREDENTIAL_POLICY_NOTE: 'Owner PAT policy', LOCAL_STATUS_LABELS: {},
  cancelImport: vi.fn(), cancelLocalSession: vi.fn(), connectUrl: vi.fn(),
  connections: vi.fn(), courses: vi.fn(), disconnect: vi.fn(), importStatus: vi.fn(),
  institutionForAddress: vi.fn(), institutions: vi.fn(), localBridgeCapability: vi.fn(),
  localSession: vi.fn(), openLocalSession: vi.fn(), outcomeFromSearch: vi.fn(() => ''),
  reasonFor: vi.fn(() => ''), selectLocalCourses: vi.fn(), setCanvasTokenGetter: vi.fn(),
  startImport: vi.fn(), bridgeCommand: vi.fn(() => ''), forgetTaskCredential: vi.fn(),
  needsCredentialMessage: vi.fn(() => ''), openTaskCredential: vi.fn(), taskCourses: vi.fn(),
  resumeTaskCredential: vi.fn(),
  taskCredentialOf: vi.fn((body) => body?.taskCredential || { available: false }),
  taskCredentialReasonFor: vi.fn(() => ''), taskCredentialState: vi.fn(),
  taskCredentialStateLabel: vi.fn(() => '使用中'), connectableInstitutions: vi.fn(() => []),
}));

describe('Canvas owner PAT import screen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(institutions).mockResolvedValue({
      institutions: [
        { key: 'cityu', label: 'CityU', origin: 'https://canvas.cityu.edu.hk', connectable: false },
        { key: 'cityu-dg', label: 'CityU(DG)', origin: 'https://cityu-dg.instructure.com', connectable: false },
      ],
      taskCredential: { available: true, ownerOnly: true, reason: '' },
    });
    vi.mocked(connections).mockResolvedValue({ connections: [] });
  });

  it('shows the school URL and one-time token as the primary two-field flow', async () => {
    render(<CanvasImport toast={vi.fn()} close={vi.fn()} onFinished={vi.fn()} />);

    expect(await screen.findByLabelText('学校 Canvas 地址')).toBeVisible();
    expect(screen.getByLabelText('本次 Access Token')).toBeVisible();
    expect(screen.getByRole('button', { name: '确认并选择课程' })).toBeVisible();
    expect(screen.queryByText('等待学校开通 Canvas 连接')).not.toBeInTheDocument();
    expect(screen.getByText('如何获取 Token')).toBeVisible();
  });

  it('groups the verified course list by semester and shows real import metadata', async () => {
    vi.mocked(openTaskCredential).mockResolvedValue({
      connectionId: 'connection-1', credentialRef: 'credential-1',
      canvasName: 'Owner', canvasUserId: '42', state: 'PRESENT_TRANSIENTLY',
    });
    vi.mocked(taskCourses).mockResolvedValue({ courses: [
      {
        id: '560', courseCode: 'CS2312', name: 'Programming', term: 'Semester B 2025/26',
        readable: true, fileCount: 2, expectedBytes: 3072,
        accessibility: 'READABLE', importStatus: 'NOT_IMPORTED',
      },
      {
        id: '240', courseCode: 'CS2204', name: 'Internet Apps', term: 'Semester A 2024/25',
        readable: true, fileCount: 0, expectedBytes: 0,
        accessibility: 'READABLE', importStatus: 'COMPLETED',
      },
    ] });
    render(<CanvasImport toast={vi.fn()} close={vi.fn()} onFinished={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText('学校 Canvas 地址'), {
      target: { value: 'https://canvas.cityu.edu.hk/profile/settings' },
    });
    fireEvent.change(screen.getByLabelText('本次 Access Token'), {
      target: { value: 'secret-never-rendered' },
    });
    fireEvent.click(screen.getByRole('button', { name: '确认并选择课程' }));

    expect(await screen.findByRole('heading', { name: 'Semester B 2025/26' })).toBeVisible();
    expect(screen.getByRole('heading', { name: 'Semester A 2024/25' })).toBeVisible();
    expect(screen.getByText(/CS2312 · Programming/)).toBeVisible();
    expect(screen.getByText(/2 个文件 · 3.0 KB · READABLE · NOT_IMPORTED/)).toBeVisible();
    expect(screen.queryByDisplayValue('secret-never-rendered')).not.toBeInTheDocument();
  });
});
