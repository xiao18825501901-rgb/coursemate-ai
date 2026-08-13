import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TestAuthProvider } from "../auth/AuthProvider";
import {
  createCourse,
  deleteCourse,
  deleteDocument,
  getIngestionJob,
  getCourse,
  listCourses,
  listDocuments,
  listTeachingProfiles,
  previewTeachingProfile,
  restoreTeachingProfile,
  saveTeachingProfile,
  submitPublicationRequest,
  updateCourse,
  uploadDocument,
  withdrawPublicationRequest,
} from "../services/ragApi";
import { CourseCenterPage } from "./CourseCenterPage";
import { CourseSettingsPage } from "./CourseSettingsPage";


vi.mock("../services/ragApi", () => ({
  createCourse: vi.fn(),
  deleteCourse: vi.fn(),
  deleteDocument: vi.fn(),
  getIngestionJob: vi.fn(),
  getCourse: vi.fn(),
  listCourses: vi.fn(),
  listDocuments: vi.fn(),
  listTeachingProfiles: vi.fn(),
  previewTeachingProfile: vi.fn(),
  restoreTeachingProfile: vi.fn(),
  saveTeachingProfile: vi.fn(),
  submitPublicationRequest: vi.fn(),
  updateCourse: vi.fn(),
  uploadDocument: vi.fn(),
  withdrawPublicationRequest: vi.fn(),
}));

const official = {
  id: "cs3481", name: "Computer Graphics", description: "Official notes",
  courseType: "official" as const, visibility: "public" as const,
  isOwner: false, canManage: false,
  publicationStatus: "published" as const, publishedAt: "2026-08-11T00:00:00Z",
  preferredLanguage: "auto" as const,
  createdAt: "2026-08-11T00:00:00Z", updatedAt: "2026-08-11T00:00:00Z",
};
const mine = {
  id: "my-course", name: "My Course", description: "Private notes",
  courseType: "user" as const, visibility: "private" as const,
  isOwner: true, canManage: true,
  publicationStatus: "private" as const, publishedAt: null,
  preferredLanguage: "auto" as const,
  createdAt: "2026-08-13T00:00:00Z", updatedAt: "2026-08-13T00:00:00Z",
};
const profile = {
  id: "profile_1", courseId: "my-course", version: 1,
  language: "zh-CN" as const, studentLevel: "beginner" as const, learningGoal: "Pass the exam",
  teachingStyles: ["intuition-first", "worked-examples"] as const, answerDepth: "detailed" as const,
  examplePreference: "worked" as const, exercisePolicy: "always" as const, examOrientation: true,
  citationPreference: "detailed" as const, mathDetailLevel: "full" as const,
  terminologyStyle: "bilingual" as const, customRequirements: "Explain why first",
  generatedPrompt: "Structured preview", createdAt: "2026-08-13T00:00:00Z",
  updatedAt: "2026-08-13T00:00:00Z",
};

function renderRoutes(initialEntry = "/courses") {
  return render(
    <TestAuthProvider token="token-a">
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<CourseCenterPage />} path="/courses" />
          <Route element={<CourseCenterPage createMode />} path="/courses/new" />
          <Route element={<CourseSettingsPage />} path="/courses/:courseId/settings" />
          <Route element={<div>Chat opened</div>} path="/qa/:courseId" />
        </Routes>
      </MemoryRouter>
    </TestAuthProvider>,
  );
}

describe("CourseCenterPage", () => {
  beforeEach(() => {
    vi.mocked(listCourses).mockResolvedValue({ items: [official, mine], page: 1, pageSize: 100, total: 2 });
    vi.mocked(listDocuments).mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
    vi.mocked(listTeachingProfiles).mockResolvedValue({ items: [] });
  });

  it("groups official and private courses and exposes owner settings", async () => {
    renderRoutes();

    expect(await screen.findByRole("heading", { name: "Official Courses" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "My Courses" })).toBeVisible();
    expect(screen.getByText("Private by default")).toBeVisible();
    expect(screen.getByRole("link", { name: /manage my course/i })).toHaveAttribute(
      "href", "/courses/my-course/settings",
    );
  });

  it("creates a private course without asking for visibility", async () => {
    vi.mocked(createCourse).mockResolvedValue(mine);
    renderRoutes("/courses/new");

    fireEvent.change(screen.getByLabelText("Course ID"), { target: { value: "my-course" } });
    fireEvent.change(screen.getByLabelText("Course name"), { target: { value: "My Course" } });
    fireEvent.click(screen.getByRole("button", { name: "Create private course" }));

    await waitFor(() => expect(createCourse).toHaveBeenCalledWith(
      expect.any(Function),
      { id: "my-course", name: "My Course", description: "" },
    ));
    expect(await screen.findByText("Chat opened")).toBeVisible();
  });
});

describe("CourseSettingsPage", () => {
  beforeEach(() => {
    vi.mocked(getCourse).mockResolvedValue(mine);
    vi.mocked(listDocuments).mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
    vi.mocked(updateCourse).mockResolvedValue({ ...mine, name: "Updated" });
    vi.mocked(deleteCourse).mockResolvedValue();
    vi.mocked(deleteDocument).mockResolvedValue();
    vi.mocked(uploadDocument).mockResolvedValue({
      document: {
        id: "doc_1", courseId: "my-course", filename: "notes.md", mediaType: "text/markdown",
        extension: ".md", sha256: "a".repeat(64), byteSize: 7, status: "pending", chunkCount: 0,
        errorMessage: null, createdAt: "2026-08-13T00:00:00Z", updatedAt: "2026-08-13T00:00:00Z",
      },
      job: {
        id: "job_1", documentId: "doc_1", status: "queued", processedChunks: 0,
        errorMessage: null, createdAt: "2026-08-13T00:00:00Z", updatedAt: "2026-08-13T00:00:00Z",
      },
    });
    vi.mocked(getIngestionJob).mockResolvedValue({
      id: "job_1", documentId: "doc_1", status: "completed", processedChunks: 1,
      errorMessage: null, createdAt: "2026-08-13T00:00:00Z", updatedAt: "2026-08-13T00:00:01Z",
    });
    vi.mocked(previewTeachingProfile).mockResolvedValue({
      language: "zh-CN", studentLevel: "beginner", learningGoal: "Pass the exam",
      teachingStyles: ["intuition-first", "worked-examples"], answerDepth: "detailed",
      examplePreference: "worked", exercisePolicy: "always", examOrientation: true,
      citationPreference: "detailed", mathDetailLevel: "full", terminologyStyle: "bilingual",
      customRequirements: "Explain why first", generatedPrompt: "Structured preview",
    });
    vi.mocked(saveTeachingProfile).mockResolvedValue({ ...profile, teachingStyles: [...profile.teachingStyles] });
    vi.mocked(restoreTeachingProfile).mockResolvedValue({
      id: "profile_3", courseId: "my-course", version: 3,
      language: "zh-CN", studentLevel: "beginner", learningGoal: "Earlier goal",
      teachingStyles: ["intuition-first"], answerDepth: "balanced",
      examplePreference: "when-helpful", exercisePolicy: "offer", examOrientation: false,
      citationPreference: "standard", mathDetailLevel: "standard", terminologyStyle: "bilingual",
      customRequirements: "", generatedPrompt: "Restored preview",
      createdAt: "2026-08-13T00:00:02Z", updatedAt: "2026-08-13T00:00:02Z",
    });
    vi.mocked(submitPublicationRequest).mockResolvedValue({
      id: "publication_1", courseId: "my-course", courseName: "My Course",
      status: "pending", shareMaterialsConsent: true, rightsConfirmation: true,
      consentVersion: "v1", consentedAt: "2026-08-13T00:00:00Z",
      submittedAt: "2026-08-13T00:00:00Z", reviewedAt: null, reviewNote: "",
    });
  });

  it("uploads a supported file and reports completed indexing", async () => {
    renderRoutes("/courses/my-course/settings");
    const input = await screen.findByLabelText("Upload course material");
    fireEvent.change(input, { target: { files: [new File(["# Notes"], "notes.md")] } });

    expect(await screen.findByText(/indexed 1 chunk/i)).toBeVisible();
    expect(uploadDocument).toHaveBeenCalled();
    expect(getIngestionJob).toHaveBeenCalledWith(expect.any(Function), "job_1");
  });

  it("previews and saves a versioned teaching profile", async () => {
    renderRoutes("/courses/my-course/settings");
    fireEvent.change(await screen.findByLabelText("Learning and teaching requirements"), {
      target: { value: "I am a beginner preparing for the exam" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Build profile preview" }));
    expect(await screen.findByText("Structured preview")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));

    await waitFor(() => expect(saveTeachingProfile).toHaveBeenCalled());
    expect(screen.getByText(/new conversations use v1/i)).toBeVisible();
  });

  it("restores a historical teaching profile as a new version", async () => {
    vi.mocked(listTeachingProfiles).mockResolvedValue({
      items: [
        { ...profile, teachingStyles: [...profile.teachingStyles], id: "profile_2", version: 2, learningGoal: "Latest goal" },
        { ...profile, teachingStyles: [...profile.teachingStyles], id: "profile_1", version: 1, learningGoal: "Earlier goal" },
      ],
    });
    renderRoutes("/courses/my-course/settings");

    fireEvent.click(await screen.findByRole("button", { name: "Restore as new version" }));

    await waitFor(() => expect(restoreTeachingProfile).toHaveBeenCalledWith(
      expect.any(Function), "my-course", 1,
    ));
    expect(screen.getByText(/new conversations use v3/i)).toBeVisible();
  });

  it("requires both publication confirmations before submission", async () => {
    renderRoutes("/courses/my-course/settings");
    const button = await screen.findByRole("button", { name: "Submit for admin review" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I want to publish and share/i));
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I confirm I have permission/i));
    fireEvent.click(button);

    await waitFor(() => expect(submitPublicationRequest).toHaveBeenCalledWith(
      expect.any(Function), "my-course",
    ));
  });

  it("allows the owner to withdraw a pending publication review", async () => {
    vi.mocked(withdrawPublicationRequest).mockResolvedValue();
    vi.mocked(getCourse)
      .mockResolvedValueOnce({ ...mine, publicationStatus: "pending" })
      .mockResolvedValueOnce(mine);
    renderRoutes("/courses/my-course/settings");

    fireEvent.click(await screen.findByRole("button", { name: "Withdraw publication request" }));

    await waitFor(() => expect(withdrawPublicationRequest).toHaveBeenCalledWith(
      expect.any(Function), "my-course",
    ));
    expect(await screen.findByRole("button", { name: "Submit for admin review" })).toBeVisible();
  });
});
