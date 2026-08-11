import { useEffect, useState } from "react";

import { listCourses, listDocuments, uploadDocument } from "../services/ragApi";
import type { Course, CourseDocument } from "../types/api";


interface CourseSources { course: Course; documents: CourseDocument[] }

export function DocumentsPage() {
  const [sources, setSources] = useState<CourseSources[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh(): Promise<void> {
    try {
      const courses = await listCourses();
      const rows = await Promise.all(courses.items.map(async (course) => ({
        course,
        documents: (await listDocuments(course.id)).items,
      })));
      setSources(rows);
      setError(null);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "The source library could not load.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function upload(courseId: string, file: File): Promise<void> {
    try {
      await uploadDocument(courseId, file);
      await refresh();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "The upload failed.");
    }
  }

  return (
    <div className="page narrow-page">
      <header className="page-intro"><span className="eyebrow">Source library</span><h1>Documents and indexing</h1><p>See what CourseMate can retrieve, where it belongs, and whether indexing completed.</p></header>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      {loading ? <div className="workspace-frame" aria-busy="true">Loading source inventory…</div> : sources.length === 0 ? <div className="empty-panel" role="status"><strong>No courses are configured.</strong><span>Run the course importer to create CS3481 and GE2324.</span></div> : (
        <div className="source-groups">
          {sources.map(({ course, documents }) => (
            <section className="source-group" key={course.id}>
              <header><div><span className="course-pill">{course.id.toUpperCase()}</span><h2>{course.name}</h2><p>{course.description}</p></div><label className="upload-label"><span>Add document</span><input accept=".pdf,.md,.markdown,.txt,.docx,.pptx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(course.id, file); event.target.value = ""; }} type="file" /></label></header>
              <div className="source-table" role="table" aria-label={`${course.name} documents`}>
                <div className="source-table-head" role="row"><span role="columnheader">Document</span><span role="columnheader">State</span><span role="columnheader">Chunks</span></div>
                {documents.length === 0 ? <p className="panel-empty">No documents yet.</p> : documents.map((document) => <div className="source-table-row" role="row" key={document.id}><span role="cell"><strong>{document.filename}</strong><small>{document.extension.toUpperCase()}</small></span><span role="cell" className={`status-text status-${document.status}`}>{document.status}</span><span role="cell">{document.chunkCount}</span></div>)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
