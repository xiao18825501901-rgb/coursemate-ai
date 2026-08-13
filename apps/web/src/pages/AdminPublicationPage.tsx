import { useEffect, useState } from "react";

import { useCourseMateAuth } from "../auth/AuthProvider";
import { listDocuments, listPendingPublications, reviewPublication } from "../services/ragApi";
import type { PublicationRequest } from "../types/api";

export function AdminPublicationPage() {
  const { getToken } = useCourseMateAuth();
  const [requests, setRequests] = useState<PublicationRequest[]>([]);
  const [files, setFiles] = useState<Record<string, string[]>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    const page = await listPendingPublications(getToken);
    setRequests(page.items);
    const entries = await Promise.all(page.items.map(async (item) => [
      item.courseId,
      (await listDocuments(getToken, item.courseId)).items.map((document) => document.filename),
    ] as const));
    setFiles(Object.fromEntries(entries));
  }

  useEffect(() => {
    void refresh().catch((caught: unknown) => {
      setError(caught instanceof Error ? caught.message : "Publication queue could not load.");
    });
  }, [getToken]);

  async function decide(item: PublicationRequest, decision: "approve" | "reject") {
    try {
      await reviewPublication(getToken, item.id, decision, notes[item.id] ?? "");
      await refresh();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "Review failed.");
    }
  }

  return <div className="page narrow-page">
    <header className="page-intro compact-intro"><span className="eyebrow">Administrator</span><h1>Publication review</h1><p>Verify sharing consent, rights, files, and privacy before making a user course discoverable.</p></header>
    {error && <div className="alert alert-error" role="alert">{error}</div>}
    {requests.length === 0 ? <div className="empty-panel">No publication requests are pending.</div> : <div className="review-list">{requests.map((item) => <article className="settings-panel" key={item.id}>
      <div className="panel-heading"><h2>{item.courseName}</h2><span>{item.courseId}</span></div>
      <ul>{(files[item.courseId] ?? []).map((filename) => <li key={filename}>{filename}</li>)}</ul>
      <p><strong>Consent recorded:</strong> {item.consentedAt} ({item.consentVersion})</p>
      <label><span className="field-label">Review note</span><textarea onChange={(event) => setNotes({ ...notes, [item.id]: event.target.value })} rows={3} value={notes[item.id] ?? ""} /></label>
      <div className="form-actions"><button className="button danger-button" onClick={() => void decide(item, "reject")} type="button">Reject</button><button className="button button-primary" onClick={() => void decide(item, "approve")} type="button">Approve publication</button></div>
    </article>)}</div>}
  </div>;
}
