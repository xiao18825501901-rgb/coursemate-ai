import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TestAuthProvider } from "../auth/AuthProvider";
import {
  getCoursePublicationSnapshot,
  getOfficialKnowledgePublicationSnapshot,
  getOverlayPublicationSnapshot,
  listDocuments,
  listActiveOfficialKnowledgePublications,
  listOfficialKnowledgeDrafts,
  listPendingOfficialKnowledgePublications,
  listPendingOverlayPublications,
  listPendingPublications,
  reviewOfficialKnowledgePublication,
  reviewOverlayPublication,
  reviewPublication,
  submitOfficialKnowledgePublication,
  withdrawOfficialKnowledgePublication,
} from "../services/ragApi";
import { AdminPublicationPage } from "./AdminPublicationPage";

vi.mock("../services/ragApi", () => ({
  downloadPublicationDocument: vi.fn(),
  getCoursePublicationSnapshot: vi.fn(),
  getOfficialKnowledgePublicationSnapshot: vi.fn(),
  getOverlayPublicationSnapshot: vi.fn(),
  listDocuments: vi.fn(),
  listActiveOfficialKnowledgePublications: vi.fn(),
  listOfficialKnowledgeDrafts: vi.fn(),
  listPendingOfficialKnowledgePublications: vi.fn(),
  listPendingOverlayPublications: vi.fn(),
  listPendingPublications: vi.fn(),
  reviewOfficialKnowledgePublication: vi.fn(),
  reviewOverlayPublication: vi.fn(),
  reviewPublication: vi.fn(),
  submitOfficialKnowledgePublication: vi.fn(),
  withdrawOfficialKnowledgePublication: vi.fn(),
}));

const courseRequest = {
  id: "course-request-1",
  courseId: "private-course",
  courseName: "Owner Course",
  status: "pending" as const,
  shareMaterialsConsent: true,
  rightsConfirmation: true,
  consentVersion: "v1",
  consentedAt: "2026-09-12T10:00:00Z",
  submittedAt: "2026-09-12T10:00:00Z",
  reviewedAt: null,
  reviewNote: "",
  snapshotId: "course-snapshot-1",
  snapshotHash: "a".repeat(64),
  resourceCount: 2,
};

const officialRequest = {
  id: "official-request-1",
  courseId: "cs3481",
  courseName: "Computer Graphics",
  treeVersionId: "tree-v2",
  treeVersion: 2,
  treeTitle: "Reviewed graphics map",
  status: "pending" as const,
  submittedAt: "2026-09-12T10:00:00Z",
  reviewedAt: null,
  reviewNote: "",
  snapshotId: "official-snapshot-1",
  snapshotHash: "b".repeat(64),
  resourceCount: 3,
};

const activeOfficialRequest = {
  ...officialRequest,
  id: "official-release-1",
  status: "approved" as const,
  reviewedAt: "2026-09-12T10:10:00Z",
  reviewNote: "Independent review passed.",
};

const overlayRequest = {
  id: "overlay-request-1",
  courseId: "cs3481",
  courseName: "Computer Graphics",
  workspaceId: "workspace-private",
  status: "pending" as const,
  shareSelectedContentConsent: true,
  rightsConfirmation: true,
  consentVersion: "v1",
  consentedAt: "2026-09-12T10:00:00Z",
  submittedAt: "2026-09-12T10:00:00Z",
  reviewedAt: null,
  reviewNote: "",
  snapshotId: "overlay-snapshot-1",
  snapshotHash: "c".repeat(64),
  resourceCount: 2,
};

function snapshot(
  subjectKind: "COURSE" | "OFFICIAL_KNOWLEDGE" | "OVERLAY",
  requestId: string,
  displayName: string,
) {
  return {
    id: `${requestId}-snapshot`,
    subjectKind,
    requestId,
    courseId: "cs3481",
    workspaceId: subjectKind === "OVERLAY" ? "workspace-private" : null,
    contentHash: "d".repeat(64),
    createdAt: "2026-09-12T10:00:00Z",
    summary: {},
    resources: [{
      kind: subjectKind === "OFFICIAL_KNOWLEDGE" ? "TEACHING_SPEC" : "DOCUMENT_VERSION",
      id: `${requestId}-resource`,
      version: "2",
      displayName,
      sourceScope: subjectKind === "OVERLAY" ? "WORKSPACE_PRIVATE" : "OFFICIAL",
      contentHash: "e".repeat(64),
      metadata: subjectKind === "OFFICIAL_KNOWLEDGE"
        ? { items: [{ objective: "Explain exact raster pipeline" }] }
        : {},
    }],
  };
}

describe("AdminPublicationPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listPendingPublications).mockResolvedValue({ items: [courseRequest] });
    vi.mocked(listOfficialKnowledgeDrafts).mockResolvedValue({
      items: [{
        treeVersionId: "tree-v3",
        courseId: "cs3481",
        courseName: "Computer Graphics",
        treeVersion: 3,
        title: "Next graphics map",
        memberCount: 8,
        pendingRequestId: null,
      }],
    });
    vi.mocked(listPendingOfficialKnowledgePublications).mockResolvedValue({
      items: [officialRequest],
    });
    vi.mocked(listActiveOfficialKnowledgePublications).mockResolvedValue({
      items: [activeOfficialRequest],
    });
    vi.mocked(listPendingOverlayPublications).mockResolvedValue({ items: [overlayRequest] });
    vi.mocked(getCoursePublicationSnapshot).mockResolvedValue(
      snapshot("COURSE", courseRequest.id, "exact-private-v2.pdf"),
    );
    vi.mocked(getOfficialKnowledgePublicationSnapshot).mockResolvedValue(
      snapshot("OFFICIAL_KNOWLEDGE", officialRequest.id, "Rasterization Spec v2"),
    );
    vi.mocked(getOverlayPublicationSnapshot).mockResolvedValue(
      snapshot("OVERLAY", overlayRequest.id, "selected-note-v1.md"),
    );
  });

  it("loads all three queues through least-privilege snapshots", async () => {
    render(<TestAuthProvider token="admin-token"><AdminPublicationPage /></TestAuthProvider>);

    expect(await screen.findByRole("heading", { name: "User course requests" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Official tree and Spec releases" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Private Overlay requests" })).toBeVisible();
    expect(await screen.findByText("exact-private-v2.pdf")).toBeVisible();
    expect(screen.getAllByText("Rasterization Spec v2")).toHaveLength(2);
    expect(screen.getAllByText(/Explain exact raster pipeline/)).toHaveLength(2);
    expect(screen.getByText("selected-note-v1.md")).toBeVisible();
    expect(screen.getByRole("button", { name: "Withdraw published Reviewed graphics map" })).toBeVisible();
    expect(listDocuments).not.toHaveBeenCalled();
  });

  it("submits exact drafts and routes each decision to its distinct workflow", async () => {
    vi.mocked(submitOfficialKnowledgePublication).mockResolvedValue(officialRequest);
    vi.mocked(reviewPublication).mockResolvedValue(courseRequest);
    vi.mocked(reviewOfficialKnowledgePublication).mockResolvedValue(officialRequest);
    vi.mocked(reviewOverlayPublication).mockResolvedValue(overlayRequest);
    render(<TestAuthProvider token="admin-token"><AdminPublicationPage /></TestAuthProvider>);

    fireEvent.click(await screen.findByRole("button", { name: "Submit tree v3 for independent review" }));
    await waitFor(() => expect(submitOfficialKnowledgePublication).toHaveBeenCalledWith(
      expect.any(Function),
      "tree-v3",
    ));

    fireEvent.click(screen.getByRole("button", { name: "Approve Owner Course" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve Reviewed graphics map" }));
    fireEvent.click(screen.getByRole("button", { name: "Approve Overlay for Computer Graphics" }));

    await waitFor(() => {
      expect(reviewPublication).toHaveBeenCalledWith(
        expect.any(Function), courseRequest.id, "approve", "",
      );
      expect(reviewOfficialKnowledgePublication).toHaveBeenCalledWith(
        expect.any(Function), officialRequest.id, "approve", "",
      );
      expect(reviewOverlayPublication).toHaveBeenCalledWith(
        expect.any(Function), overlayRequest.id, "approve", "",
      );
    });
  });

  it("withdraws a discoverable approved official release", async () => {
    vi.mocked(withdrawOfficialKnowledgePublication).mockResolvedValue();
    render(<TestAuthProvider token="admin-token"><AdminPublicationPage /></TestAuthProvider>);

    fireEvent.click(await screen.findByRole("button", {
      name: "Withdraw published Reviewed graphics map",
    }));

    await waitFor(() => expect(withdrawOfficialKnowledgePublication).toHaveBeenCalledWith(
      expect.any(Function), activeOfficialRequest.id,
    ));
  });
});
