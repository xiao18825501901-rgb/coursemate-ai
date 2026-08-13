import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useCourseMateAuth } from "../auth/AuthProvider";
import { deleteCourse, deleteDocument, getIngestionJob, listCourses, listDocuments, updateCourse, uploadDocument } from "../services/ragApi";
import type { Course, CourseDocument, IngestionJob } from "../types/api";


function message(error: unknown): string {
  return error instanceof Error ? error.message : "The course operation failed.";
}

export function CourseSettingsPage() {
  const { courseId = "" } = useParams();
  const { getToken } = useCourseMateAuth();
  const navigate = useNavigate();
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState("");

  async function refresh() {
    const [coursePage, documentPage] = await Promise.all([
      listCourses(getToken), listDocuments(getToken, courseId),
    ]);
    const found = coursePage.items.find((item) => item.id === courseId && item.canManage);
    if (!found) throw new Error("This course is not available for management.");
    setCourse(found); setName(found.name); setDescription(found.description); setDocuments(documentPage.items);
  }

  useEffect(() => { void refresh().catch((caught: unknown) => setError(message(caught))); }, [courseId, getToken]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try { setCourse(await updateCourse(getToken, courseId, { name: name.trim(), description: description.trim() })); }
    catch (caught: unknown) { setError(message(caught)); }
  }

  async function upload(file: File) {
    setError(null); setJob(null);
    try {
      const accepted = await uploadDocument(getToken, courseId, file);
      setJob(accepted.job);
      let current = accepted.job;
      for (let attempt = 0; attempt < 120 && ["queued", "processing"].includes(current.status); attempt += 1) {
        if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, 500));
        current = await getIngestionJob(getToken, accepted.job.id);
        setJob(current);
      }
      if (current.status === "failed") throw new Error(current.errorMessage ?? "Indexing failed.");
      if (current.status !== "completed") throw new Error("Indexing is still running. Refresh to check again.");
      await refresh();
    } catch (caught: unknown) { setError(message(caught)); }
  }

  return <div className="page narrow-page">
    <header className="page-intro compact-intro"><span className="eyebrow">Private course settings</span><h1>{course?.name ?? courseId}</h1><p>Manage course details and source files. This course is not visible to other students.</p></header>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    <div className="settings-grid">
      <section className="settings-panel"><h2>Course details</h2><form className="course-form" onSubmit={(event) => void save(event)}><label><span className="field-label">Course name</span><input onChange={(event) => setName(event.target.value)} required value={name} /></label><label><span className="field-label">Description</span><textarea onChange={(event) => setDescription(event.target.value)} rows={4} value={description} /></label><button className="button button-primary" type="submit">Save details</button></form></section>
      <section className="settings-panel"><div className="panel-heading"><h2>Course materials</h2><span>{documents.length}</span></div><label className="upload-label">Upload course material<input accept=".md,.markdown,.txt,.pdf,.docx,.pptx" aria-label="Upload course material" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} type="file" /></label>{job && <p className="ingestion-status" role="status">{job.status === "completed" ? `Indexed ${job.processedChunks} chunk${job.processedChunks === 1 ? "" : "s"}.` : `Indexing: ${job.status}…`}</p>}<ul className="settings-document-list">{documents.map((document) => <li key={document.id}><span><strong>{document.filename}</strong><small>{document.status} · {document.chunkCount} chunks</small></span><button className="text-button danger-text" onClick={() => void deleteDocument(getToken, courseId, document.id).then(refresh).catch((caught: unknown) => setError(message(caught)))} type="button">Delete</button></li>)}</ul></section>
      <section className="settings-panel danger-zone"><h2>Delete course</h2><p>This removes conversations, documents, chunks, and stored uploads for this course.</p><label><span className="field-label">Type {courseId} to confirm</span><input onChange={(event) => setConfirmId(event.target.value)} value={confirmId} /></label><button className="button danger-button" disabled={confirmId !== courseId} onClick={() => void deleteCourse(getToken, courseId).then(() => navigate("/courses")).catch((caught: unknown) => setError(message(caught)))} type="button">Delete course permanently</button></section>
    </div><div className="form-actions"><Link className="button button-secondary" to="/courses">Back to courses</Link><Link className="button button-primary" to={`/qa/${courseId}`}>Open tutor</Link></div>
  </div>;
}
