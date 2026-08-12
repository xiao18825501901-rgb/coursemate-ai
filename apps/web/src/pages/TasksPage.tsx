import { type FormEvent, useCallback, useEffect, useState } from "react";

import { TaskBoard } from "../components/TaskBoard";
import { useCourseMateAuth } from "../auth/AuthProvider";
import { chatWithAgent, createTask, deleteTask, listTasks, updateTask } from "../services/agentApi";
import type { Task, TaskStatus, UpdateTaskInput } from "../types/api";


function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The study plan could not be updated.";
}

export function TasksPage() {
  const { getToken } = useCourseMateAuth();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<TaskStatus | "">("");
  const [courseId, setCourseId] = useState("");
  const [query, setQuery] = useState("");
  const [quickTitle, setQuickTitle] = useState("");
  const [agentMessage, setAgentMessage] = useState("");
  const [agentReply, setAgentReply] = useState("Tell me what you want to study or change.");
  const [agentBusy, setAgentBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const page = await listTasks(getToken, {
        ...(status ? { status } : {}),
        ...(courseId ? { courseId } : {}),
        ...(query ? { query } : {}),
      });
      setTasks(page.items);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [courseId, getToken, query, status]);

  useEffect(() => { void refresh(); }, [refresh]);

  async function quickAdd(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const title = quickTitle.trim();
    if (!title) return;
    try {
      await createTask(getToken, { title, ...(courseId ? { courseId } : {}) });
      setQuickTitle("");
      await refresh();
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function talkToAgent(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const message = agentMessage.trim();
    if (!message || agentBusy) return;
    setAgentBusy(true);
    setError(null);
    try {
      const response = await chatWithAgent(getToken, message);
      setAgentReply(response.message);
      setAgentMessage("");
      await refresh();
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setAgentBusy(false);
    }
  }

  async function patch(taskId: string, input: UpdateTaskInput): Promise<void> {
    try {
      await updateTask(getToken, taskId, input);
      await refresh();
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function remove(taskId: string): Promise<void> {
    try {
      await deleteTask(getToken, taskId);
      await refresh();
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  return (
    <div className="page workspace-page">
      <header className="page-intro compact-intro task-intro">
        <div><span className="eyebrow">Study plan</span><h1>Make the next step obvious</h1></div>
        <form className="quick-add" onSubmit={(event) => void quickAdd(event)}>
          <label htmlFor="quick-task">Quick add</label>
          <div><input id="quick-task" maxLength={200} onChange={(event) => setQuickTitle(event.target.value)} placeholder="e.g. Review lecture 7" value={quickTitle} /><button className="button button-primary">Add</button></div>
        </form>
      </header>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <section className="agent-bar" aria-labelledby="agent-heading">
        <div className="agent-identity"><span aria-hidden="true">CM</span><div><h2 id="agent-heading">Study agent</h2><p aria-live="polite">{agentReply}</p></div></div>
        <form onSubmit={(event) => void talkToAgent(event)}>
          <label className="sr-only" htmlFor="agent-message">Message the study agent</label>
          <input id="agent-message" maxLength={2_000} onChange={(event) => setAgentMessage(event.target.value)} placeholder="Create, find, update, complete, or delete a task…" value={agentMessage} />
          <button className="button button-secondary" disabled={!agentMessage.trim() || agentBusy}>{agentBusy ? "Working…" : "Send"}</button>
        </form>
      </section>
      <section className="task-controls" aria-label="Task filters">
        <label>Course<select onChange={(event) => setCourseId(event.target.value)} value={courseId}><option value="">All courses</option><option value="cs3481">CS3481</option><option value="ge2324">GE2324</option></select></label>
        <label>Status<select onChange={(event) => setStatus(event.target.value as TaskStatus | "")} value={status}><option value="">All statuses</option><option value="todo">To do</option><option value="in_progress">In progress</option><option value="completed">Completed</option></select></label>
        <label className="task-search">Search<input onChange={(event) => setQuery(event.target.value)} placeholder="Filter task titles" type="search" value={query} /></label>
        <span className="task-count">{tasks.length} shown</span>
      </section>
      {loading ? <div className="loading-grid" aria-busy="true" aria-label="Loading tasks"><span /><span /><span /></div> : <TaskBoard tasks={tasks} onDelete={remove} onUpdate={patch} />}
    </div>
  );
}
