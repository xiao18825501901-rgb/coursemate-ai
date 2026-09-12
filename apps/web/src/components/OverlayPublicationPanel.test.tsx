import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TestAuthProvider } from "../auth/AuthProvider";
import {
  getCurrentOverlayPublication,
  getCurrentOverlayPublicationSnapshot,
  listOverlayPublicationCandidates,
  submitOverlayPublication,
  withdrawOverlayPublication,
} from "../services/ragApi";
import { OverlayPublicationPanel } from "./OverlayPublicationPanel";

vi.mock("../services/ragApi", () => ({
  getCurrentOverlayPublication: vi.fn(),
  getCurrentOverlayPublicationSnapshot: vi.fn(),
  listOverlayPublicationCandidates: vi.fn(),
  submitOverlayPublication: vi.fn(),
  withdrawOverlayPublication: vi.fn(),
}));

const candidates = {
  nodes: [
    { id: "node-selected", title: "My raster note", kind: "ATOMIC", specVersion: 2 },
    { id: "node-hidden", title: "Secret alternative", kind: "ATOMIC", specVersion: 1 },
  ],
  documents: [
    { id: "version-selected", documentId: "doc-selected", version: 2, filename: "selected.md", sha256: "a".repeat(64), byteSize: 100, status: "ready" },
    { id: "version-hidden", documentId: "doc-hidden", version: 1, filename: "hidden.md", sha256: "b".repeat(64), byteSize: 200, status: "ready" },
  ],
  artifacts: [
    { id: "artifact-selected", documentVersionId: "version-selected", kind: "PREVIEW_PDF", producerVersion: "1", sha256: "c".repeat(64), byteSize: 90 },
  ],
  evidence: [
    { id: "evidence-selected", nodeId: "node-selected", nodeTitle: "My raster note", nodeIsPrivate: true, documentVersionId: "version-selected", locatorType: "section", locatorValue: "2" },
  ],
};

describe("OverlayPublicationPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listOverlayPublicationCandidates).mockResolvedValue(candidates);
    vi.mocked(getCurrentOverlayPublication).mockResolvedValue(null);
    vi.mocked(getCurrentOverlayPublicationSnapshot).mockResolvedValue({
      id: "snapshot-1",
      subjectKind: "OVERLAY",
      requestId: "overlay-1",
      courseId: "cs3481",
      workspaceId: "workspace-1",
      contentHash: "d".repeat(64),
      createdAt: "2026-09-12T10:00:00Z",
      summary: {},
      resources: [{
        kind: "DOCUMENT_VERSION",
        id: "version-selected",
        version: "2",
        displayName: "selected.md",
        sourceScope: "WORKSPACE_PRIVATE",
        contentHash: "a".repeat(64),
        metadata: {},
      }],
    });
    vi.mocked(submitOverlayPublication).mockResolvedValue({
      id: "overlay-1",
      courseId: "cs3481",
      courseName: "Computer Graphics",
      workspaceId: "workspace-1",
      status: "pending",
      shareSelectedContentConsent: true,
      rightsConfirmation: true,
      consentVersion: "v1",
      consentedAt: "2026-09-12T10:00:00Z",
      submittedAt: "2026-09-12T10:00:00Z",
      reviewedAt: null,
      reviewNote: "",
      snapshotId: "snapshot-1",
      snapshotHash: "d".repeat(64),
      resourceCount: 4,
    });
  });

  it("submits only checked exact versions after dependency and consent checks", async () => {
    render(<TestAuthProvider token="owner-token"><OverlayPublicationPanel workspace="workspace-1" /></TestAuthProvider>);

    fireEvent.click(screen.getByText("Share selected private Overlay"));
    const submit = await screen.findByRole("button", { name: "Submit selected Overlay for review" });
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("Share derived PREVIEW_PDF for selected.md v2")).toBeDisabled();
    expect(screen.getByLabelText("Share evidence My raster note at section 2")).toBeDisabled();

    fireEvent.click(screen.getByLabelText("Share node My raster note"));
    fireEvent.click(screen.getByLabelText("Share document selected.md version 2"));
    fireEvent.click(screen.getByLabelText("Share derived PREVIEW_PDF for selected.md v2"));
    fireEvent.click(screen.getByLabelText("Share evidence My raster note at section 2"));
    fireEvent.click(screen.getByLabelText("I choose to share only the checked private resources"));
    fireEvent.click(screen.getByLabelText(/I confirm I have rights to share these exact versions/i));
    expect(screen.getByLabelText("Share node Secret alternative")).not.toBeChecked();
    expect(screen.getByLabelText("Share document hidden.md version 1")).not.toBeChecked();
    fireEvent.click(submit);

    await waitFor(() => expect(submitOverlayPublication).toHaveBeenCalledWith(
      expect.any(Function),
      "workspace-1",
      {
        nodeIds: ["node-selected"],
        documentVersionIds: ["version-selected"],
        artifactIds: ["artifact-selected"],
        evidenceIds: ["evidence-selected"],
        shareSelectedContentConsent: true,
        rightsConfirmation: true,
        consentVersion: "v1",
      },
    ));
    expect(await screen.findByText(/DOCUMENT_VERSION v2/)).toBeVisible();
  });

  it("withdraws an active package without claiming prior downloads can be recalled", async () => {
    vi.mocked(getCurrentOverlayPublication).mockResolvedValue({
      id: "overlay-live",
      courseId: "cs3481",
      courseName: "Computer Graphics",
      workspaceId: "workspace-1",
      status: "approved",
      shareSelectedContentConsent: true,
      rightsConfirmation: true,
      consentVersion: "v1",
      consentedAt: "2026-09-12T10:00:00Z",
      submittedAt: "2026-09-12T10:00:00Z",
      reviewedAt: "2026-09-12T11:00:00Z",
      reviewNote: "Approved",
      snapshotId: "snapshot-live",
      snapshotHash: "e".repeat(64),
      resourceCount: 3,
    });
    vi.mocked(withdrawOverlayPublication).mockResolvedValue();
    render(<TestAuthProvider token="owner-token"><OverlayPublicationPanel workspace="workspace-1" /></TestAuthProvider>);

    fireEvent.click(screen.getByText("Share selected private Overlay"));
    expect(await screen.findByText(/cannot recall copies that were already downloaded/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw shared Overlay" }));
    await waitFor(() => expect(withdrawOverlayPublication).toHaveBeenCalledWith(
      expect.any(Function),
      "workspace-1",
    ));
  });
});
