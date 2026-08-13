import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { CitationList } from "../components/CitationList";
import { ConversationSidebar } from "../components/ConversationSidebar";
import { useCourseMateAuth } from "../auth/AuthProvider";
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
import type {
  Citation,
  ConversationSummary,
  Course,
  CourseDocument,
  GroundingMode,
  QaStreamMeta,
} from "../types/api";


interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  question?: string;
  citations: Citation[];
  metadata?: QaStreamMeta;
}

function messageId(): string {
  return `message-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "CourseMate could not complete the request.";
}

function previousUserQuestion(
  messages: Array<{ role: "user" | "assistant"; content: string }>,
  beforeIndex: number,
): string | undefined {
  for (let index = beforeIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "user") return message.content;
  }
  return undefined;
}

const groundingLabels: Record<GroundingMode, { title: string; detail: string }> = {
  grounded: {
    title: "Course-material answer",
    detail: "Claims are limited to retrieved course evidence; citations identify that evidence.",
  },
  mixed: {
    title: "Course material + AI knowledge",
    detail: "Citations support only the course-material portion, not supplementary AI knowledge.",
  },
  general: {
    title: "General tutor conversation",
    detail: "No course-material claim or citation is implied for this response.",
  },
  metadata: {
    title: "Course information",
    detail: "This response uses trusted course and document metadata, not retrieved excerpts.",
  },
};

export function QaPage() {
  const { getToken } = useCourseMateAuth();
  const { courseId: routeCourseId, conversationId: routeConversationId } = useParams();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState(routeCourseId ?? "");
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [planNotice, setPlanNotice] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;
    abortRef.current?.abort();
    setMessages([]);
    setQuestion("");
    setPlanNotice("");
    setError(null);
    void listCourses(getToken)
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
  }, [getToken, navigate, routeCourseId]);

  useEffect(() => {
    if (!courseId) {
      setDocuments([]);
      return;
    }
    void listDocuments(getToken, courseId)
      .then((page) => setDocuments(page.items))
      .catch((caught: unknown) => setError(errorMessage(caught)));
  }, [courseId, getToken]);

  useEffect(() => {
    let active = true;
    if (!courseId) {
      setConversations([]);
      return;
    }
    setHistoryLoading(true);
    void listConversations(getToken, courseId)
      .then((page) => active && setConversations(page.items))
      .catch((caught: unknown) => active && setError(errorMessage(caught)))
      .finally(() => active && setHistoryLoading(false));
    return () => {
      active = false;
    };
  }, [courseId, getToken]);

  useEffect(() => {
    let active = true;
    // Navigating to the server-assigned id during an active SSE stream must not
    // replace the optimistic assistant message with a partial database snapshot.
    if (streaming) return;
    if (!routeConversationId) {
      setMessages([]);
      return;
    }
    void getConversation(getToken, routeConversationId)
      .then((conversation) => {
        if (!active) return;
        setMessages(conversation.messages.map((message, index) => {
          const question = message.role === "assistant"
            ? previousUserQuestion(conversation.messages, index)
            : undefined;
          return {
            id: message.id,
            role: message.role,
            text: message.content,
            citations: message.citations,
            ...(message.metadata === undefined ? {} : { metadata: message.metadata }),
            ...(question === undefined ? {} : { question }),
          };
        }));
      })
      .catch((caught: unknown) => active && setError(errorMessage(caught)));
    return () => {
      active = false;
    };
  }, [getToken, routeConversationId, streaming]);

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
        getToken,
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
          onMeta: (data) => {
            setMessages((items) => items.map((item) => (
              item.id === answerId ? { ...item, metadata: data } : item
            )));
            if (typeof data.conversationId !== "string" || routeConversationId) return;
            navigate(`/qa/${courseId}/${data.conversationId}`, { replace: true });
          },
          onDone: () => {
            void listConversations(getToken, courseId)
              .then((page) => setConversations(page.items))
              .catch(() => undefined);
          },
        },
        controller.signal,
        routeConversationId,
      );
    } catch (caught: unknown) {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  async function startNewChat(): Promise<void> {
    if (!courseId) return;
    try {
      setError(null);
      const created = await createConversation(getToken, courseId, "auto");
      setConversations((items) => [created, ...items]);
      navigate(`/qa/${courseId}/${created.id}`);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function renameHistory(conversation: ConversationSummary): Promise<void> {
    const title = window.prompt("Rename conversation", conversation.title)?.trim();
    if (!title || title === conversation.title) return;
    try {
      const updated = await renameConversation(getToken, conversation.id, title);
      setConversations((items) => items.map((item) => (
        item.id === updated.id ? updated : item
      )));
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function deleteHistory(conversation: ConversationSummary): Promise<void> {
    if (!window.confirm(`Delete “${conversation.title}” and all of its messages?`)) return;
    try {
      await deleteConversation(getToken, conversation.id);
      setConversations((items) => items.filter((item) => item.id !== conversation.id));
      if (routeConversationId === conversation.id) {
        setMessages([]);
        navigate(`/qa/${courseId}`, { replace: true });
      }
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    }
  }

  async function addToPlan(message: ChatMessage): Promise<void> {
    try {
      setError(null);
      const citation = message.citations[0];
      await createTask(getToken, {
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

  return (
    <div className="page workspace-page">
      <header className="page-intro compact-intro">
        <span className="eyebrow">Course QA</span>
        <h1>Ask your material</h1>
        <p>Select a course, ask a focused question, and inspect every cited excerpt.</p>
      </header>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <p className="sr-only" aria-live="polite">{planNotice}</p>
      <div className="qa-workspace qa-workspace-v2">
        <ConversationSidebar
          activeConversationId={routeConversationId}
          conversations={conversations}
          loading={historyLoading}
          onCreate={() => void startNewChat()}
          onDelete={(conversation) => void deleteHistory(conversation)}
          onOpen={(conversation) => navigate(`/qa/${conversation.courseId}/${conversation.id}`)}
          onRename={(conversation) => void renameHistory(conversation)}
        />
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
          {currentCourse?.canManage ? (
            <Link className="text-button" to={`/courses/${currentCourse.id}/settings`}>
              Manage course and sources
            </Link>
          ) : (
            <p className="managed-corpus-note">Official course sources are read-only.</p>
          )}
        </aside>

        <section className="chat-panel" aria-labelledby="qa-chat-title">
          <div className="chat-panel-header">
            <div><span className="online-indicator" />AI tutor</div>
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
                  {message.role === "assistant" && message.metadata?.groundingMode && (
                    <div
                      className={`grounding-banner grounding-${message.metadata.groundingMode}`}
                      role="status"
                    >
                      <strong>{groundingLabels[message.metadata.groundingMode].title}</strong>
                      <span>{groundingLabels[message.metadata.groundingMode].detail}</span>
                    </div>
                  )}
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
