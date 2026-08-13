import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTask } from "../services/agentApi";
import {
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  listCourses,
  listDocuments,
  renameConversation,
  streamQa,
} from "../services/ragApi";
import { QaPage } from "./QaPage";


vi.mock("../services/agentApi", () => ({ createTask: vi.fn() }));
vi.mock("../services/ragApi", () => ({
  listCourses: vi.fn(),
  listDocuments: vi.fn(),
  listConversations: vi.fn(),
  createConversation: vi.fn(),
  getConversation: vi.fn(),
  renameConversation: vi.fn(),
  deleteConversation: vi.fn(),
  streamQa: vi.fn(),
  uploadDocument: vi.fn(),
}));

const course = {
  id: "cs3481",
  name: "Computer Graphics",
  description: "CS3481 materials",
  courseType: "official" as const,
  visibility: "public" as const,
  isOwner: false,
  canManage: false,
  createdAt: "2026-08-11T00:00:00Z",
  updatedAt: "2026-08-11T00:00:00Z",
};

const geCourse = {
  id: "ge2324",
  name: "Data Science as a Human Science",
  description: "GE2324 materials",
  courseType: "official" as const,
  visibility: "public" as const,
  isOwner: false,
  canManage: false,
  createdAt: "2026-08-11T00:00:00Z",
  updatedAt: "2026-08-11T00:00:00Z",
};

describe("QaPage", () => {
  beforeEach(() => {
    vi.mocked(listCourses).mockResolvedValue({ items: [course, geCourse], page: 1, pageSize: 100, total: 2 });
    vi.mocked(listDocuments).mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
    vi.mocked(listConversations).mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
    vi.mocked(createConversation).mockResolvedValue({
      id: "conv_new",
      courseId: "cs3481",
      title: "New Conversation",
      preferredLanguage: "auto",
      messageCount: 0,
      createdAt: "2026-08-13T00:00:00Z",
      updatedAt: "2026-08-13T00:00:00Z",
    });
    vi.mocked(deleteConversation).mockResolvedValue();
    vi.mocked(createTask).mockResolvedValue({
      id: "task-1",
      title: "Review lighting",
      notes: null,
      courseId: "cs3481",
      status: "todo",
      priority: "medium",
      dueDate: null,
      sourceCitation: null,
      createdAt: "2026-08-11T00:00:00Z",
      updatedAt: "2026-08-11T00:00:00Z",
      completedAt: null,
    });
  });

  it("streams an answer, renders its citation, and saves it as a task", async () => {
    vi.mocked(streamQa).mockImplementation(async (_getToken, _courseId, _question, callbacks) => {
      callbacks.onMeta?.({
        queryIntent: "COURSE_TUTORING",
        groundingMode: "mixed",
        retrievedChunks: 1,
      });
      callbacks.onDelta("The Phong model combines ambient, diffuse, and specular terms.");
      callbacks.onCitation({
        sourceLabel: "S1",
        courseId: "cs3481",
        documentId: "doc-1",
        chunkId: "chunk-1",
        filename: "lecture-07.pdf",
        locatorType: "page",
        locatorValue: "12",
        section: "Lighting",
        excerpt: "Phong illumination contains three reflected-light components.",
        channels: ["keyword", "vector"],
      });
    });

    render(
      <MemoryRouter initialEntries={["/qa/cs3481"]}>
        <Routes><Route path="/qa/:courseId" element={<QaPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "Computer Graphics" })).toBeVisible();
    fireEvent.change(screen.getByLabelText(/ask a course question/i), {
      target: { value: "What is the Phong model?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/ambient, diffuse, and specular/i)).toBeVisible();
    expect(screen.getByText("Course material + AI knowledge")).toBeVisible();
    expect(screen.getByText(/citations support only the course-material portion/i)).toBeVisible();
    expect(screen.getByText("lecture-07.pdf")).toBeVisible();
    fireEvent.click(screen.getByText("lecture-07.pdf"));
    expect(screen.getByText(/keyword \+ vector/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /add to study plan/i }));
    await waitFor(() => expect(createTask).toHaveBeenCalledWith(
      expect.any(Function),
      expect.objectContaining({
        courseId: "cs3481",
        sourceCitation: expect.objectContaining({ filename: "lecture-07.pdf" }),
      }),
    ));
  });

  it("starts a fresh conversation when the selected course changes", async () => {
    vi.mocked(streamQa).mockImplementation(async (_getToken, _courseId, _question, callbacks) => {
      callbacks.onDelta("A CS3481-only DBSCAN answer.");
    });

    render(
      <MemoryRouter initialEntries={["/qa/cs3481"]}>
        <Routes><Route path="/qa/:courseId" element={<QaPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "Computer Graphics" })).toBeVisible();
    fireEvent.change(screen.getByLabelText(/ask a course question/i), {
      target: { value: "How does DBSCAN identify a core point?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/CS3481-only DBSCAN answer/i)).toBeVisible();

    fireEvent.change(screen.getByLabelText("Course"), { target: { value: "ge2324" } });

    await waitFor(() => {
      expect(screen.queryByText(/CS3481-only DBSCAN answer/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/Start with a specific question/i)).toBeVisible();
  });

  it("labels a general tutor conversation without implying course grounding", async () => {
    vi.mocked(streamQa).mockImplementation(async (_getToken, _courseId, _question, callbacks) => {
      callbacks.onMeta?.({
        queryIntent: "GENERAL_CONVERSATION",
        groundingMode: "general",
        retrievedChunks: 0,
      });
      callbacks.onDelta("Hi! Let's make today's study plan manageable.");
    });

    render(
      <MemoryRouter initialEntries={["/qa/cs3481"]}>
        <Routes><Route path="/qa/:courseId" element={<QaPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "Computer Graphics" })).toBeVisible();
    fireEvent.change(screen.getByLabelText(/ask a course question/i), {
      target: { value: "Hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText(/make today's study plan manageable/i)).toBeVisible();
    expect(screen.getByText("General tutor conversation")).toBeVisible();
    expect(screen.getByText(/No course-material claim or citation is implied/i)).toBeVisible();
  });

  it("does not overwrite a live stream when the server assigns its conversation route", async () => {
    let finishStream: (() => void) | undefined;
    vi.mocked(getConversation).mockResolvedValue({
      id: "conv_stream",
      courseId: "cs3481",
      title: "Streaming answer",
      preferredLanguage: "auto",
      createdAt: "2026-08-13T00:00:00Z",
      updatedAt: "2026-08-13T00:01:00Z",
      messages: [
        { id: "m1", role: "user", content: "Explain lighting.", citations: [], createdAt: "2026-08-13T00:00:00Z" },
        { id: "m2", role: "assistant", content: "Complete streamed answer.", citations: [], createdAt: "2026-08-13T00:01:00Z" },
      ],
    });
    vi.mocked(streamQa).mockImplementation(async (_getToken, _courseId, _question, callbacks) => {
      callbacks.onMeta?.({ conversationId: "conv_stream" });
      await new Promise<void>((resolve) => {
        finishStream = resolve;
      });
      callbacks.onDelta("Complete streamed answer.");
      callbacks.onDone?.();
    });

    render(
      <MemoryRouter initialEntries={["/qa/cs3481"]}>
        <Routes>
          <Route path="/qa/:courseId" element={<QaPage />} />
          <Route path="/qa/:courseId/:conversationId" element={<QaPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("option", { name: "Computer Graphics" })).toBeVisible();
    fireEvent.change(screen.getByLabelText(/ask a course question/i), {
      target: { value: "Explain lighting." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(finishStream).toBeTypeOf("function"));
    expect(getConversation).not.toHaveBeenCalled();

    await act(async () => finishStream?.());
    expect(await screen.findByText("Complete streamed answer.")).toBeVisible();
    await waitFor(() => expect(getConversation).toHaveBeenCalledWith(
      expect.any(Function),
      "conv_stream",
    ));
  });

  it("restores an old conversation from the route and can continue it", async () => {
    vi.mocked(listConversations).mockResolvedValue({
      items: [{
        id: "conv_123",
        courseId: "cs3481",
        title: "DBSCAN Core Point",
        preferredLanguage: "zh-CN",
        messageCount: 2,
        createdAt: "2026-08-13T00:00:00Z",
        updatedAt: "2026-08-13T00:01:00Z",
      }],
      page: 1,
      pageSize: 100,
      total: 1,
    });
    vi.mocked(getConversation).mockResolvedValue({
      id: "conv_123",
      courseId: "cs3481",
      title: "DBSCAN Core Point",
      preferredLanguage: "zh-CN",
      createdAt: "2026-08-13T00:00:00Z",
      updatedAt: "2026-08-13T00:01:00Z",
      messages: [
        { id: "m1", role: "user", content: "什么是核心点？", citations: [], createdAt: "2026-08-13T00:00:00Z" },
        {
          id: "m2",
          role: "assistant",
          content: "核心点（core point）…",
          citations: [],
          metadata: { queryIntent: "COURSE_TUTORING", groundingMode: "mixed" },
          createdAt: "2026-08-13T00:01:00Z",
        },
      ],
    });
    vi.mocked(streamQa).mockImplementation(async (
      _getToken,
      _courseId,
      _question,
      callbacks,
    ) => callbacks.onDelta("换一种解释。"));

    render(
      <MemoryRouter initialEntries={["/qa/cs3481/conv_123"]}>
        <Routes><Route path="/qa/:courseId/:conversationId" element={<QaPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("核心点（core point）…")).toBeVisible();
    expect(screen.getByText("Course material + AI knowledge")).toBeVisible();
    fireEvent.change(screen.getByLabelText(/ask a course question/i), {
      target: { value: "我还是没听懂" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));

    expect(await screen.findByText("换一种解释。")).toBeVisible();
    expect(streamQa).toHaveBeenLastCalledWith(
      expect.any(Function),
      "cs3481",
      "我还是没听懂",
      expect.any(Object),
      expect.any(AbortSignal),
      "conv_123",
    );
  });

  it("creates, renames, and deletes conversations from the history sidebar", async () => {
    vi.mocked(listConversations).mockResolvedValue({
      items: [{
        id: "conv_123",
        courseId: "cs3481",
        title: "Old title",
        preferredLanguage: "auto",
        messageCount: 2,
        createdAt: "2026-08-13T00:00:00Z",
        updatedAt: "2026-08-13T00:01:00Z",
      }],
      page: 1,
      pageSize: 100,
      total: 1,
    });
    vi.mocked(renameConversation).mockResolvedValue({
      id: "conv_123",
      courseId: "cs3481",
      title: "DBSCAN tutorial",
      preferredLanguage: "auto",
      messageCount: 2,
      createdAt: "2026-08-13T00:00:00Z",
      updatedAt: "2026-08-13T00:02:00Z",
    });
    vi.spyOn(window, "prompt").mockReturnValue("DBSCAN tutorial");
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <MemoryRouter initialEntries={["/qa/cs3481"]}>
        <Routes>
          <Route path="/qa/:courseId" element={<QaPage />} />
          <Route path="/qa/:courseId/:conversationId" element={<QaPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "Open Old title" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: /new chat/i }));
    await waitFor(() => expect(createConversation).toHaveBeenCalledWith(
      expect.any(Function),
      "cs3481",
      "auto",
    ));

    fireEvent.click(screen.getByRole("button", { name: "Rename Old title" }));
    await waitFor(() => expect(renameConversation).toHaveBeenCalledWith(
      expect.any(Function),
      "conv_123",
      "DBSCAN tutorial",
    ));

    fireEvent.click(screen.getByRole("button", { name: "Delete DBSCAN tutorial" }));
    await waitFor(() => expect(deleteConversation).toHaveBeenCalledWith(
      expect.any(Function),
      "conv_123",
    ));
  });
});
