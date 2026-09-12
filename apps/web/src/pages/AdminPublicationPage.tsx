import { useEffect, useState } from "react";

import { useCourseMateAuth } from "../auth/AuthProvider";
import {
  downloadPublicationDocument,
  getCoursePublicationSnapshot,
  getOfficialKnowledgePublicationSnapshot,
  getOverlayPublicationSnapshot,
  listActiveOfficialKnowledgePublications,
  listOfficialKnowledgeDrafts,
  listPendingOfficialKnowledgePublications,
  listPendingOverlayPublications,
  listPendingPublications,
  reviewOfficialKnowledgePublication,
  reviewOverlayPublication,
  reviewPublication,
  submitOfficialKnowledgePublication,
  withdrawOfficialKnowledgePublication,
} from "../services/ragApi";
import type {
  OfficialKnowledgeDraft,
  OfficialKnowledgePublicationRequest,
  OverlayPublicationRequest,
  PublicationRequest,
  PublicationSnapshot,
  PublicationSnapshotResource,
} from "../types/api";

type Decision = "approve" | "reject";

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 12)}…` : "Unavailable";
}

function SnapshotManifest({
  snapshot,
  onDownload,
}: {
  snapshot: PublicationSnapshot | undefined;
  onDownload: (resource: PublicationSnapshotResource) => void;
}) {
  if (!snapshot) return <p role="status">Exact review snapshot is unavailable.</p>;
  return <details className="review-snapshot" open>
    <summary>
      Exact review package · {snapshot.resources.length} resources · SHA-256 {shortHash(snapshot.contentHash)}
    </summary>
    <ul className="review-resource-list">
      {snapshot.resources.map((resource) => <li key={`${resource.kind}:${resource.id}:${resource.version}`}>
        <div className="review-resource-heading">
          <span><strong>{resource.displayName}</strong><small>{resource.kind} · v{resource.version} · {resource.sourceScope} · {shortHash(resource.contentHash)}</small></span>
          {resource.kind === "DOCUMENT_VERSION" && snapshot.subjectKind !== "OFFICIAL_KNOWLEDGE" && <button
            className="text-button"
            onClick={() => onDownload(resource)}
            type="button"
          >Download reviewed {resource.displayName}</button>}
        </div>
        <details className="review-resource-metadata" open>
          <summary>Inspect bound metadata</summary>
          <pre>{JSON.stringify(resource.metadata, null, 2)}</pre>
        </details>
      </li>)}
    </ul>
  </details>;
}

function ReviewNote({
  requestId,
  value,
  onChange,
}: {
  requestId: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `review-note-${requestId}`;
  return <label htmlFor={id}>
    <span className="field-label">Review note</span>
    <textarea id={id} maxLength={1000} onChange={(event) => onChange(event.target.value)} rows={3} value={value} />
  </label>;
}

export function AdminPublicationPage() {
  const { getToken } = useCourseMateAuth();
  const [courseRequests, setCourseRequests] = useState<PublicationRequest[]>([]);
  const [officialDrafts, setOfficialDrafts] = useState<OfficialKnowledgeDraft[]>([]);
  const [officialRequests, setOfficialRequests] = useState<OfficialKnowledgePublicationRequest[]>([]);
  const [activeOfficialRequests, setActiveOfficialRequests] = useState<OfficialKnowledgePublicationRequest[]>([]);
  const [overlayRequests, setOverlayRequests] = useState<OverlayPublicationRequest[]>([]);
  const [snapshots, setSnapshots] = useState<Record<string, PublicationSnapshot>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const [courses, drafts, official, activeOfficial, overlays] = await Promise.all([
      listPendingPublications(getToken),
      listOfficialKnowledgeDrafts(getToken),
      listPendingOfficialKnowledgePublications(getToken),
      listActiveOfficialKnowledgePublications(getToken),
      listPendingOverlayPublications(getToken),
    ]);
    const snapshotEntries = await Promise.all([
      ...courses.items.map(async (item) => [
        item.id,
        await getCoursePublicationSnapshot(getToken, item.id),
      ] as const),
      ...official.items.map(async (item) => [
        item.id,
        await getOfficialKnowledgePublicationSnapshot(getToken, item.id),
      ] as const),
      ...activeOfficial.items.map(async (item) => [
        item.id,
        await getOfficialKnowledgePublicationSnapshot(getToken, item.id),
      ] as const),
      ...overlays.items.map(async (item) => [
        item.id,
        await getOverlayPublicationSnapshot(getToken, item.id),
      ] as const),
    ]);
    setCourseRequests(courses.items);
    setOfficialDrafts(drafts.items);
    setOfficialRequests(official.items);
    setActiveOfficialRequests(activeOfficial.items);
    setOverlayRequests(overlays.items);
    setSnapshots(Object.fromEntries(snapshotEntries));
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    void refresh()
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Publication queues could not load.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [getToken]);

  async function run(key: string, action: () => Promise<unknown>) {
    setBusy((current) => new Set(current).add(key));
    setError(null);
    try {
      await action();
      await refresh();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Publication action failed.");
    } finally {
      setBusy((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  }

  async function download(
    subject: "COURSE" | "OVERLAY",
    requestId: string,
    resource: PublicationSnapshotResource,
  ) {
    const key = `download:${requestId}:${resource.id}`;
    await run(key, async () => {
      const blob = await downloadPublicationDocument(getToken, subject, requestId, resource.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = resource.displayName;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    });
  }

  function note(requestId: string) {
    return <ReviewNote
      requestId={requestId}
      value={notes[requestId] ?? ""}
      onChange={(value) => setNotes((current) => ({ ...current, [requestId]: value }))}
    />;
  }

  function actions(
    requestId: string,
    label: string,
    review: (decision: Decision, reviewNote: string) => Promise<unknown>,
  ) {
    return <div className="form-actions">
      <button
        aria-label={`Reject ${label}`}
        className="button danger-button"
        disabled={busy.has(requestId)}
        onClick={() => void run(requestId, () => review("reject", notes[requestId] ?? ""))}
        type="button"
      >Reject</button>
      <button
        aria-label={`Approve ${label}`}
        className="button button-primary"
        disabled={busy.has(requestId) || !snapshots[requestId]}
        onClick={() => void run(requestId, () => review("approve", notes[requestId] ?? ""))}
        type="button"
      >Approve exact snapshot</button>
    </div>;
  }

  return <div className="page publication-admin-page">
    <header className="page-intro compact-intro">
      <span className="eyebrow">Administrator · least-privilege review</span>
      <h1>Version-bound publication review</h1>
      <p>Course, official knowledge, and private Overlay releases use separate queues. Every decision binds the exact snapshot shown below; administrator status does not grant ambient access to private workspaces.</p>
    </header>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {loading && <p aria-live="polite">Loading scoped review packages…</p>}

    <section className="publication-queue" aria-labelledby="course-publication-heading">
      <div className="panel-heading"><h2 id="course-publication-heading">User course requests</h2><span>{courseRequests.length} pending</span></div>
      {!loading && courseRequests.length === 0 && <div className="empty-panel">No user course requests are pending.</div>}
      <div className="review-list">{courseRequests.map((item) => <article className="settings-panel" key={item.id}>
        <div className="panel-heading"><h3>{item.courseName}</h3><span>{item.courseId}</span></div>
        <p><strong>Explicit file-sharing consent:</strong> {item.consentedAt} ({item.consentVersion})</p>
        <SnapshotManifest snapshot={snapshots[item.id]} onDownload={(resource) => void download("COURSE", item.id, resource)} />
        {note(item.id)}
        {actions(item.id, item.courseName, (decision, reviewNote) => reviewPublication(getToken, item.id, decision, reviewNote))}
      </article>)}</div>
    </section>

    <section className="publication-queue" aria-labelledby="official-publication-heading">
      <div className="panel-heading"><h2 id="official-publication-heading">Official tree and Spec releases</h2><span>Independent review required</span></div>
      <p className="privacy-notice">Submitting and approving must be performed by different administrators. Publishing promotes only the exact tree, node, Spec, and official evidence versions in the snapshot.</p>
      <div className="official-draft-list">{officialDrafts.map((draft) => <article className="settings-panel compact-panel" key={draft.treeVersionId}>
        <div className="panel-heading"><h3>{draft.title}</h3><span>{draft.courseName} · tree v{draft.treeVersion}</span></div>
        <p>{draft.memberCount} members in draft · exact tree ID <code>{draft.treeVersionId}</code></p>
        <button
          aria-label={`Submit tree v${draft.treeVersion} for independent review`}
          className="button button-secondary"
          disabled={Boolean(draft.pendingRequestId) || busy.has(`draft:${draft.treeVersionId}`)}
          onClick={() => void run(`draft:${draft.treeVersionId}`, () => submitOfficialKnowledgePublication(getToken, draft.treeVersionId))}
          type="button"
        >{draft.pendingRequestId ? "Review pending" : "Submit exact draft"}</button>
      </article>)}</div>
      {!loading && officialDrafts.length === 0 && officialRequests.length === 0 && <div className="empty-panel">No official knowledge draft or review is pending.</div>}
      <div className="review-list">{officialRequests.map((item) => <article className="settings-panel" key={item.id}>
        <div className="panel-heading"><h3>{item.treeTitle}</h3><span>{item.courseName} · tree v{item.treeVersion}</span></div>
        <SnapshotManifest snapshot={snapshots[item.id]} onDownload={() => undefined} />
        {note(item.id)}
        {actions(item.id, item.treeTitle, (decision, reviewNote) => reviewOfficialKnowledgePublication(getToken, item.id, decision, reviewNote))}
      </article>)}</div>
      <div className="panel-heading publication-subheading"><h3>Published official releases</h3><span>{activeOfficialRequests.length} active</span></div>
      {activeOfficialRequests.length === 0 && !loading && <div className="empty-panel">No official knowledge release is active.</div>}
      <div className="review-list">{activeOfficialRequests.map((item) => <article className="settings-panel" key={item.id}>
        <div className="panel-heading"><h3>{item.treeTitle}</h3><span>{item.courseName} · tree v{item.treeVersion}</span></div>
        <p className="privacy-notice">Withdrawal retires this tree and ends future access. Previously cached or lawfully downloaded material cannot be recalled.</p>
        <SnapshotManifest snapshot={snapshots[item.id]} onDownload={() => undefined} />
        <button
          aria-label={`Withdraw published ${item.treeTitle}`}
          className="button danger-button"
          disabled={busy.has(`withdraw:${item.id}`)}
          onClick={() => void run(`withdraw:${item.id}`, () => withdrawOfficialKnowledgePublication(getToken, item.id))}
          type="button"
        >Withdraw published release</button>
      </article>)}</div>
    </section>

    <section className="publication-queue" aria-labelledby="overlay-publication-heading">
      <div className="panel-heading"><h2 id="overlay-publication-heading">Private Overlay requests</h2><span>{overlayRequests.length} pending</span></div>
      <p>Only owner-selected private versions appear here. Chats, grades, progress, problems, and unselected resources are outside the package.</p>
      {!loading && overlayRequests.length === 0 && <div className="empty-panel">No private Overlay requests are pending.</div>}
      <div className="review-list">{overlayRequests.map((item) => <article className="settings-panel" key={item.id}>
        <div className="panel-heading"><h3>Overlay for {item.courseName}</h3><span>{item.resourceCount} selected resources</span></div>
        <p><strong>Selected-content consent:</strong> {item.consentedAt} ({item.consentVersion})</p>
        <SnapshotManifest snapshot={snapshots[item.id]} onDownload={(resource) => void download("OVERLAY", item.id, resource)} />
        {note(item.id)}
        {actions(item.id, `Overlay for ${item.courseName}`, (decision, reviewNote) => reviewOverlayPublication(getToken, item.id, decision, reviewNote))}
      </article>)}</div>
    </section>
  </div>;
}
