import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { useCourseMateAuth } from "../auth/AuthProvider";
import {
  deleteCourse,
  deleteDocument,
  getIngestionJob,
  listCourses,
  listDocuments,
  listTeachingProfiles,
  previewTeachingProfile,
  restoreTeachingProfile,
  saveTeachingProfile,
  submitPublicationRequest,
  updateCourse,
  uploadDocument,
  withdrawPublicationRequest,
} from "../services/ragApi";
import type {
  Course,
  CourseDocument,
  IngestionJob,
  TeachingProfile,
  TeachingProfilePreview,
} from "../types/api";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The course operation failed.";
}

export function CourseSettingsPage() {
  const { courseId = "" } = useParams();
  const { getToken } = useCourseMateAuth();
  const navigate = useNavigate();
  const [course, setCourse] = useState<Course | null>(null);
  const [documents, setDocuments] = useState<CourseDocument[]>([]);
  const [profiles, setProfiles] = useState<TeachingProfile[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState("");
  const [profileRequirement, setProfileRequirement] = useState("");
  const [profilePreview, setProfilePreview] = useState<TeachingProfilePreview | null>(null);
  const [shareConsent, setShareConsent] = useState(false);
  const [rightsConfirmation, setRightsConfirmation] = useState(false);

  async function refresh() {
    const [coursePage, documentPage, profilePage] = await Promise.all([
      listCourses(getToken),
      listDocuments(getToken, courseId),
      listTeachingProfiles(getToken, courseId),
    ]);
    const found = coursePage.items.find((item) => item.id === courseId && item.canManage);
    if (!found) throw new Error("This course is not available for management.");
    setCourse(found);
    setName(found.name);
    setDescription(found.description);
    setDocuments(documentPage.items);
    setProfiles(profilePage.items);
  }

  useEffect(() => {
    void refresh().catch((caught: unknown) => setError(message(caught)));
  }, [courseId, getToken]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      setCourse(await updateCourse(getToken, courseId, {
        name: name.trim(), description: description.trim(),
      }));
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function upload(file: File) {
    setError(null);
    setJob(null);
    try {
      const accepted = await uploadDocument(getToken, courseId, file);
      setJob(accepted.job);
      let current = accepted.job;
      for (
        let attempt = 0;
        attempt < 120 && ["queued", "processing"].includes(current.status);
        attempt += 1
      ) {
        if (attempt > 0) await new Promise((resolve) => setTimeout(resolve, 500));
        current = await getIngestionJob(getToken, accepted.job.id);
        setJob(current);
      }
      if (current.status === "failed") {
        throw new Error(current.errorMessage ?? "Indexing failed.");
      }
      if (current.status !== "completed") {
        throw new Error("Indexing is still running. Refresh to check again.");
      }
      await refresh();
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function buildProfile() {
    try {
      setProfilePreview(await previewTeachingProfile(getToken, profileRequirement));
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function saveProfile() {
    if (!profilePreview) return;
    try {
      const saved = await saveTeachingProfile(getToken, courseId, profilePreview);
      setProfiles((current) => [saved, ...current]);
      setProfilePreview(null);
      setProfileRequirement("");
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function restoreProfile(version: number) {
    try {
      const restored = await restoreTeachingProfile(getToken, courseId, version);
      setProfiles((current) => [restored, ...current]);
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function requestPublication() {
    try {
      await submitPublicationRequest(getToken, courseId);
      await refresh();
    } catch (caught: unknown) { setError(message(caught)); }
  }

  async function withdrawPublication() {
    try {
      await withdrawPublicationRequest(getToken, courseId);
      await refresh();
    } catch (caught: unknown) { setError(message(caught)); }
  }

  return <div className="page narrow-page">
    <header className="page-intro compact-intro">
      <span className="eyebrow">Private course settings</span>
      <h1>{course?.name ?? courseId}</h1>
      <p>Manage course details and source files. This course is not visible to other students.</p>
    </header>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    <div className="settings-grid">
      <section className="settings-panel">
        <h2>Course details</h2>
        <form className="course-form" onSubmit={(event) => void save(event)}>
          <label><span className="field-label">Course name</span><input onChange={(event) => setName(event.target.value)} required value={name} /></label>
          <label><span className="field-label">Description</span><textarea onChange={(event) => setDescription(event.target.value)} rows={4} value={description} /></label>
          <button className="button button-primary" type="submit">Save details</button>
        </form>
      </section>
      <section className="settings-panel">
        <div className="panel-heading"><h2>Course materials</h2><span>{documents.length}</span></div>
        <label className="upload-label">Upload course material<input accept=".md,.markdown,.txt,.pdf,.docx,.pptx" aria-label="Upload course material" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} type="file" /></label>
        {job && <p className="ingestion-status" role="status">{job.status === "completed" ? `Indexed ${job.processedChunks} chunk${job.processedChunks === 1 ? "" : "s"}.` : `Indexing: ${job.status}…`}</p>}
        <ul className="settings-document-list">{documents.map((document) => <li key={document.id}><span><strong>{document.filename}</strong><small>{document.status} · {document.chunkCount} chunks</small></span><button className="text-button danger-text" onClick={() => void deleteDocument(getToken, courseId, document.id).then(refresh).catch((caught: unknown) => setError(message(caught)))} type="button">Delete</button></li>)}</ul>
      </section>
      <section className="settings-panel teaching-profile-panel">
        <div className="panel-heading"><h2>AI teaching profile</h2><span>{profiles[0] ? `v${profiles[0].version}` : "Default"}</span></div>
        <p>Describe how you want CourseMate to teach. Review the structured profile before saving.</p>
        <label><span className="field-label">Learning and teaching requirements</span><textarea onChange={(event) => setProfileRequirement(event.target.value)} placeholder="I am a beginner preparing for the exam. Explain why first, then show a worked example." rows={4} value={profileRequirement} /></label>
        <button className="button button-secondary" disabled={profileRequirement.trim().length < 3} onClick={() => void buildProfile()} type="button">Build profile preview</button>
        {profilePreview && <div className="profile-preview" aria-label="Teaching profile preview">
          <label><span className="field-label">Learning goal</span><input onChange={(event) => setProfilePreview({ ...profilePreview, learningGoal: event.target.value })} value={profilePreview.learningGoal} /></label>
          <label><span className="field-label">Answer depth</span><select onChange={(event) => setProfilePreview({ ...profilePreview, answerDepth: event.target.value as TeachingProfilePreview["answerDepth"] })} value={profilePreview.answerDepth}><option value="concise">Concise</option><option value="balanced">Balanced</option><option value="detailed">Detailed</option></select></label>
          <pre>{profilePreview.generatedPrompt}</pre>
          <button className="button button-primary" onClick={() => void saveProfile()} type="button">Save as new version</button>
        </div>}
        {profiles[0] && <>
          <p className="profile-version-note">New conversations use v{profiles[0].version}; existing conversations retain the version they started with.</p>
          <ul className="settings-document-list" aria-label="Teaching profile version history">
            {profiles.map((profile, index) => <li key={profile.id}>
              <span><strong>Version {profile.version}</strong><small>{profile.learningGoal}</small></span>
              {index > 0 && <button className="text-button" onClick={() => void restoreProfile(profile.version)} type="button">Restore as new version</button>}
            </li>)}
          </ul>
        </>}
      </section>
      <section className="settings-panel publication-panel">
        <div className="panel-heading"><h2>Publication</h2><span>{course?.publicationStatus ?? "private"}</span></div>
        <p>Publication exposes the course title, description, source files, derived chunks, and teaching profile to every signed-in user. Your account identifier is not displayed.</p>
        {course?.publicationStatus === "pending" ? <div className="privacy-notice"><strong>Review pending</strong><span>The course remains private until an administrator approves it.</span><button className="text-button danger-text" onClick={() => void withdrawPublication()} type="button">Withdraw publication request</button></div> : <>
          <label className="consent-row"><input checked={shareConsent} onChange={(event) => setShareConsent(event.target.checked)} type="checkbox" /><span>I want to publish and share this course, including its materials and derived teaching data.</span></label>
          <label className="consent-row"><input checked={rightsConfirmation} onChange={(event) => setRightsConfirmation(event.target.checked)} type="checkbox" /><span>I confirm I have permission to share these materials and have checked them for private information.</span></label>
          <button className="button button-secondary" disabled={!shareConsent || !rightsConfirmation} onClick={() => void requestPublication()} type="button">Submit for admin review</button>
        </>}
      </section>
      <section className="settings-panel danger-zone">
        <h2>Delete course</h2>
        <p>This removes conversations, documents, chunks, and stored uploads for this course.</p>
        <label><span className="field-label">Type {courseId} to confirm</span><input onChange={(event) => setConfirmId(event.target.value)} value={confirmId} /></label>
        <button className="button danger-button" disabled={confirmId !== courseId} onClick={() => void deleteCourse(getToken, courseId).then(() => navigate("/courses")).catch((caught: unknown) => setError(message(caught)))} type="button">Delete course permanently</button>
      </section>
    </div>
    <div className="form-actions"><Link className="button button-secondary" to="/courses">Back to courses</Link><Link className="button button-primary" to={`/qa/${courseId}`}>Open tutor</Link></div>
  </div>;
}
