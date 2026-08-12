import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createTask } from "../services/agentApi";
import { listCourses, listDocuments, streamQa } from "../services/ragApi";
import { QaPage } from "./QaPage";


vi.mock("../services/agentApi", () => ({ createTask: vi.fn() }));
vi.mock("../services/ragApi", () => ({
  listCourses: vi.fn(),
  listDocuments: vi.fn(),
  streamQa: vi.fn(),
  uploadDocument: vi.fn(),
}));

const course = {
  id: "cs3481",
  name: "Computer Graphics",
  description: "CS3481 materials",
  createdAt: "2026-08-11T00:00:00Z",
};

const geCourse = {
  id: "ge2324",
  name: "Data Science as a Human Science",
  description: "GE2324 materials",
  createdAt: "2026-08-11T00:00:00Z",
};

describe("QaPage", () => {
  beforeEach(() => {
    vi.mocked(listCourses).mockResolvedValue({ items: [course, geCourse], page: 1, pageSize: 100, total: 2 });
    vi.mocked(listDocuments).mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
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
});
