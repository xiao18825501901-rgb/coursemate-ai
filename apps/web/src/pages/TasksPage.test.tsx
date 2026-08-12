import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { chatWithAgent, createTask, listTasks, updateTask } from "../services/agentApi";
import { TasksPage } from "./TasksPage";


vi.mock("../services/agentApi", () => ({
  chatWithAgent: vi.fn(),
  createTask: vi.fn(),
  deleteTask: vi.fn(),
  listTasks: vi.fn(),
  updateTask: vi.fn(),
}));

const task = {
  id: "task-1",
  title: "Review lecture seven",
  notes: "Focus on the lighting equations.",
  courseId: "cs3481",
  status: "todo" as const,
  priority: "high" as const,
  dueDate: null,
  sourceCitation: null,
  createdAt: "2026-08-11T00:00:00Z",
  updatedAt: "2026-08-11T00:00:00Z",
  completedAt: null,
};

describe("TasksPage", () => {
  beforeEach(() => {
    vi.mocked(listTasks).mockResolvedValue({ items: [task], page: 1, pageSize: 100, total: 1 });
    vi.mocked(createTask).mockResolvedValue(task);
    vi.mocked(updateTask).mockResolvedValue({ ...task, status: "completed" });
    vi.mocked(chatWithAgent).mockResolvedValue({ message: "Created one study task.", toolResults: [] });
  });

  it("supports direct task updates and natural-language agent actions", async () => {
    render(<TasksPage />);

    expect(await screen.findByRole("heading", { level: 3, name: task.title })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Mark complete" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledWith(
      expect.any(Function),
      "task-1",
      { status: "completed" },
    ));

    fireEvent.change(screen.getByLabelText(/message the study agent/i), {
      target: { value: "Create a high-priority task for GE2324" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(chatWithAgent).toHaveBeenCalledWith(
      expect.any(Function),
      "Create a high-priority task for GE2324",
    ));
    expect(await screen.findByText("Created one study task.")).toBeVisible();
  });
});
