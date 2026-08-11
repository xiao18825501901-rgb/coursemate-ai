import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { CitationList } from "../components/CitationList";
import { createTask } from "../services/agentApi";
import { listCourses, listDocuments, streamQa, uploadDocument } from "../services/ragApi";
import type { Citation, Course, CourseDocument } from "../types/api";


interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  question?: string;
  citations: Citation[];
}

function messageId(): string {
  return `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "CourseMate could not complete the request.";
}

export function QaPage() {
  const { courseId: routeCourseId } = useParams();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState(routeCourseId ?? "");
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planNotice, setPlanNotice] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    void listCourses()
      .then((page) => {
        if (!active) return;
        setCourses(page.items);
        const selected = page.items.some((course) => course.id === routeCourseId)
          ? (routeCourseId ?? "")
          : (page.items[0]?.id ?? "");
        setCourseId(selected);
        if (selected && selected !== routeCourseId) navigate(`/qa/${selected}`, { replace: true });
      })
      .catch((caught: unknown) => active && setError(errorMessage(caught)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
      abortRef.current?.abort();
    };
  }, [navigate, routeCourseId]);

  useEffect(() => {
    if (!courseId) {
      setDocuments([]);
      return;
    }
    void listDocuments(courseId)
      .then((page) => setDocuments(page.items))
      .catch((caught: unknown) => setError(errorMessage(caught)));
  }, [courseId]);

  const currentCourse = useMemo(
    () => courses.find((course) => course.id === courseId) ?? null,
    [courseId, courses],
  );

  async function ask(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || !courseId || streaming) return;
    const answerId = messageId();
    setMessages((items) => [
      ...items,
      { id: messageId(), role: "user", text: trimmed, citations: [] },
      { id: answerId, role: "assistant", text: "", question: trimmed, citations: [] },
    ]);
    setQuestion("");
    setError(null);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamQa(
        courseId,
        trimmed,
        {
          onDelta: (text) =>
            setMessages((items) =>
              items.map((item) => (item.id === answerId ? { ...item, text: item.text + text } : item)),
            ),
          onCitation: (citation) =>
            setMessages((items) =>
              items.map((item) =>
                item.id === answerId
                  ? { ...item, citations: [...item.citations, citation] }
                  : item,
              ),
            ),
        },
        controller.signal,
      );
    } catch (caught: unknown) {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  async function addToPlan(message: ChatMessage): Promise<void> {
    try {
      setError(null);
      const citation = message.citations[0];
      await createTask({
        title: `Review: ${(message.question ?? "Course answer").slice(0, 160)}`,
        notes: message.text.slice(0, 5_000),
        courseId,
        sourceCitation: citation
          ? {
              filename: citation.filename,
              locator: `${citation.locatorType} ${citation.locatorValue}`,
              excerpt: citation.excerpt,
            }
          : null,
      });
      setPlanNotice("Added this answer to your study plan.");
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function upload(file: File): Promise<void> {
    try {
      setError(null);
      await uploadDocument(courseId, file);
      const page = await listDocuments(courseId);
      setDocuments(page.items);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  return (
    <div className="page workspace-page">
      <header className="page-intro compact-intro">
        <span className="eyebrow">Course QA</span>
        <h1>Ask your material</h1>
        <p>Select a course, ask a focused question, and inspect every cited excerpt.</p>
      </header>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <p className="sr-only" aria-live="polite">{planNotice}</p>
      <div className="qa-workspace">
        <aside className="course-panel" aria-label="Course documents">
          <label className="field-label" htmlFor="course-select">Course</label>
          <select
            id="course-select"
            onChange={(event) => {
              setCourseId(event.target.value);
              navigate(`/qa/${event.target.value}`);
            }}
            value={courseId}
          >
            {courses.map((course) => <option key={course.id} value={course.id}>{course.name}</option>)}
          </select>
          <div className="course-summary">
            <strong>{currentCourse?.name ?? (loading ? "Loading courses…" : "No courses yet")}</strong>
            <span>{currentCourse?.description || "Import or create a course to begin."}</span>
          </div>
          <div className="panel-heading">
            <h2>Indexed sources</h2>
            <span>{documents.length}</span>
          </div>
          {documents.length === 0 ? (
            <p className="panel-empty">No indexed documents in this course.</p>
          ) : (
            <ul className="document-list">
              {documents.map((document) => (
                <li key={document.id}>
                  <span className={`status-dot status-${document.status}`} aria-hidden="true" />
                  <span><strong>{document.filename}</strong><small>{document.status} · {document.chunkCount} chunks</small></span>
                </li>
              ))}
            </ul>
          )}
          <label className={`upload-label ${!courseId ? "is-disabled" : ""}`}>
            <span>Upload a source</span>
            <input
              accept=".pdf,.md,.markdown,.txt,.docx,.pptx"
              disabled={!courseId}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
              type="file"
            />
          </label>
        </aside>

        <section className="chat-panel" aria-labelledby="qa-chat-title">
          <div className="chat-panel-header">
            <div><span className="online-indicator" />Grounded mode</div>
            <h2 id="qa-chat-title">Conversation</h2>
          </div>
          <div className="message-log" role="log" aria-live="polite" aria-relevant="additions text">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <span aria-hidden="true">?</span>
                <h3>Start with a specific question.</h3>
                <p>Try “What are the components of the Phong lighting model?”</p>
              </div>
            ) : (
              messages.map((message) => (
                <article className={`message message-${message.role}`} key={message.id}>
                  <span className="message-role">{message.role === "user" ? "You" : "CourseMate"}</span>
                  <p>{message.text || (streaming ? "Reading your sources…" : "No answer returned.")}</p>
                  <CitationList citations={message.citations} />
                  {message.role === "assistant" && message.text && !streaming && (
                    <button className="text-button" onClick={() => void addToPlan(message)}>
                      + Add to study plan
                    </button>
                  )}
                </article>
              ))
            )}
          </div>
          <form className="composer" onSubmit={(event) => void ask(event)}>
            <label className="sr-only" htmlFor="qa-question">Ask a course question</label>
            <textarea
              id="qa-question"
              maxLength={2_000}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask a question grounded in this course…"
              rows={2}
              value={question}
            />
            <button className="button button-primary" disabled={!courseId || !question.trim() || streaming}>
              {streaming ? "Answering…" : "Ask"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
