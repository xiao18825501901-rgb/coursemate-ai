import { type FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useCourseMateAuth } from "../auth/AuthProvider";
import { createCourse, listCourses } from "../services/ragApi";
import type { Course } from "../types/api";

const indexLabels = { empty: "Empty", indexing: "Indexing", indexed: "Indexed", failed: "Failed" };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Courses could not load.";
}

export function CourseCenterPage({ createMode = false }: { createMode?: boolean }) {
  const { getToken } = useCourseMateAuth();
  const navigate = useNavigate();
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(!createMode);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  useEffect(() => {
    if (createMode) return;
    let active = true;
    void listCourses(getToken)
      .then((page) => {
        if (!active) return;
        setCourses(page.items);
      })
      .catch((caught: unknown) => active && setError(errorMessage(caught)))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [createMode, getToken]);

  const official = useMemo(
    () => courses.filter((course) => course.courseType !== "user"),
    [courses],
  );
  const mine = useMemo(
    () => courses.filter((course) => course.courseType === "user" && course.canManage),
    [courses],
  );
  const community = useMemo(
    () => courses.filter((course) => course.courseType === "user" && !course.canManage),
    [courses],
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const course = await createCourse(getToken, {
        id: id.trim(), name: name.trim(), description: description.trim(),
      });
      navigate(`/qa/${course.id}`);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  }

  if (createMode) {
    return <div className="page narrow-page">
      <header className="page-intro compact-intro"><span className="eyebrow">My Courses</span><h1>Create a private course</h1><p>Your course, files, chunks, and conversations are visible only to you and administrators.</p></header>
      {error && <div className="alert alert-error" role="alert">{error}</div>}
      <form className="course-form" onSubmit={(event) => void submit(event)}>
        <label><span className="field-label">Course ID</span><input autoComplete="off" onChange={(event) => setId(event.target.value.toLowerCase())} pattern="[a-z0-9](?:[a-z0-9]|-){1,49}" required value={id} /></label>
        <label><span className="field-label">Course name</span><input maxLength={120} onChange={(event) => setName(event.target.value)} required value={name} /></label>
        <label><span className="field-label">Description</span><textarea maxLength={1000} onChange={(event) => setDescription(event.target.value)} rows={5} value={description} /></label>
        <div className="privacy-notice"><strong>Private by default</strong><span>Publishing requires a separate consent and admin review workflow.</span></div>
        <div className="form-actions"><Link className="button button-secondary" to="/courses">Cancel</Link><button className="button button-primary" disabled={saving} type="submit">{saving ? "Creating…" : "Create private course"}</button></div>
      </form>
    </div>;
  }

  const section = (title: string, items: Course[], empty: string) => <section className="course-collection" aria-labelledby={`${title.replaceAll(" ", "-")}-title`}>
    <header><h2 id={`${title.replaceAll(" ", "-")}-title`}>{title}</h2><span>{items.length}</span></header>
    {items.length === 0 ? <div className="empty-panel">{empty}</div> : <div className="course-card-grid">{items.map((course) => <article className="course-card" key={course.id}>
      <div className="course-card-topline"><span className="course-pill">{course.id}</span><span className={`visibility-badge visibility-${course.visibility}`}>{course.visibility === "private" ? "Private by default" : course.courseType === "official" ? "Official" : "Community"}</span></div>
      <h3>{course.name}</h3><p>{course.description || "No description yet."}</p>
      <small>{course.documentCount ?? 0} files · {indexLabels[course.indexStatus ?? "empty"]} · Updated {new Date(course.updatedAt).toLocaleDateString()}</small>
      <div className="course-card-actions"><Link className="button button-primary" to={`/qa/${course.id}`}>Open tutor</Link>{course.canManage && <Link aria-label={`Manage ${course.name}`} className="button button-secondary" to={`/courses/${course.id}/settings`}>Settings</Link>}</div>
    </article>)}</div>}
  </section>;

  return <div className="page">
    <header className="page-intro course-center-intro"><div><span className="eyebrow">Course spaces</span><h1>Your learning library</h1><p>Official material stays shared. Courses you create remain private until a reviewed publication request succeeds.</p></div><Link className="button button-primary" to="/courses/new">Create Course</Link></header>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {loading ? <div className="workspace-frame" aria-busy="true">Loading courses…</div> : <div className="course-collections">
      {section("Official Courses", official, "No official courses are available.")}
      {section("My Courses", mine, "Create your first private course to upload and teach from your own material.")}
      {section("Community Courses", community, "No reviewed community courses are available yet.")}
    </div>}
  </div>;
}
