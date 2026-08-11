import { useState } from "react";

import type { Task, TaskPriority, TaskStatus, UpdateTaskInput } from "../types/api";


interface TaskBoardProps {
  tasks: Task[];
  onUpdate: (taskId: string, input: UpdateTaskInput) => Promise<void>;
  onDelete: (taskId: string) => Promise<void>;
}

const columns: Array<{ status: TaskStatus; label: string }> = [
  { status: "todo", label: "To do" },
  { status: "in_progress", label: "In progress" },
  { status: "completed", label: "Completed" },
];

function TaskCard({
  task,
  onUpdate,
  onDelete,
}: {
  task: Task;
  onUpdate: TaskBoardProps["onUpdate"];
  onDelete: TaskBoardProps["onDelete"];
}) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const nextStatus: TaskStatus = task.status === "completed" ? "todo" : "completed";
  return (
    <article className={`task-card task-${task.priority}`}>
      <div className="task-card-topline">
        <span className="priority-label">{task.priority} priority</span>
        {task.courseId && <span className="course-pill">{task.courseId.toUpperCase()}</span>}
      </div>
      <h3>{task.title}</h3>
      {task.notes && <p>{task.notes}</p>}
      {task.sourceCitation && (
        <details className="task-source">
          <summary>Source: {task.sourceCitation.filename}</summary>
          <p>{task.sourceCitation.excerpt}</p>
        </details>
      )}
      <div className="task-fields">
        <label>
          <span>Due</span>
          <input
            aria-label={`Due date for ${task.title}`}
            onChange={(event) => void onUpdate(task.id, { dueDate: event.target.value || null })}
            type="date"
            value={task.dueDate ?? ""}
          />
        </label>
        <label>
          <span>Priority</span>
          <select
            aria-label={`Priority for ${task.title}`}
            onChange={(event) =>
              void onUpdate(task.id, { priority: event.target.value as TaskPriority })
            }
            value={task.priority}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </label>
      </div>
      <div className="task-actions">
        <button
          className="text-button"
          onClick={() => void onUpdate(task.id, { status: nextStatus })}
          type="button"
        >
          {task.status === "completed" ? "Reopen" : "Mark complete"}
        </button>
        {confirmDelete ? (
          <span className="delete-confirm" role="group" aria-label={`Delete ${task.title}?`}>
            <button className="text-button danger-text" onClick={() => void onDelete(task.id)} type="button">
              Confirm delete
            </button>
            <button className="text-button" onClick={() => setConfirmDelete(false)} type="button">
              Cancel
            </button>
          </span>
        ) : (
          <button className="text-button danger-text" onClick={() => setConfirmDelete(true)} type="button">
            Delete
          </button>
        )}
      </div>
    </article>
  );
}

export function TaskBoard({ tasks, onUpdate, onDelete }: TaskBoardProps) {
  if (tasks.length === 0) {
    return (
      <div className="empty-panel" role="status">
        <strong>No tasks match these filters.</strong>
        <span>Use quick add or tell the agent what you want to study.</span>
      </div>
    );
  }
  return (
    <div className="task-board">
      {columns.map((column) => {
        const items = tasks.filter((task) => task.status === column.status);
        return (
          <section className="task-column" key={column.status} aria-labelledby={`column-${column.status}`}>
            <header>
              <h2 id={`column-${column.status}`}>{column.label}</h2>
              <span aria-label={`${items.length} tasks`}>{items.length}</span>
            </header>
            <div className="task-column-list">
              {items.length === 0 ? (
                <p className="empty-column">Nothing here</p>
              ) : (
                items.map((task) => (
                  <TaskCard key={task.id} task={task} onDelete={onDelete} onUpdate={onUpdate} />
                ))
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}
