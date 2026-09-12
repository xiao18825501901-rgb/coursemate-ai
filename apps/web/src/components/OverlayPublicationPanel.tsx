import { useEffect, useMemo, useState } from "react";

import { useCourseMateAuth } from "../auth/AuthProvider";
import {
  getCurrentOverlayPublication,
  getCurrentOverlayPublicationSnapshot,
  listOverlayPublicationCandidates,
  submitOverlayPublication,
  withdrawOverlayPublication,
} from "../services/ragApi";
import type {
  OverlayPublicationCandidates,
  OverlayPublicationRequest,
  PublicationSnapshot,
} from "../types/api";

const emptyCandidates: OverlayPublicationCandidates = {
  nodes: [],
  documents: [],
  artifacts: [],
  evidence: [],
};

function toggleValue(current: Set<string>, value: string, checked: boolean) {
  const next = new Set(current);
  if (checked) next.add(value);
  else next.delete(value);
  return next;
}

function shortHash(value: string) {
  return `${value.slice(0, 12)}…`;
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function OverlayPublicationPanel({ workspace }: { workspace: string }) {
  const { getToken } = useCourseMateAuth();
  const [candidates, setCandidates] = useState(emptyCandidates);
  const [current, setCurrent] = useState<OverlayPublicationRequest | null>(null);
  const [currentSnapshot, setCurrentSnapshot] = useState<PublicationSnapshot | null>(null);
  const [nodeIds, setNodeIds] = useState<Set<string>>(() => new Set());
  const [documentVersionIds, setDocumentVersionIds] = useState<Set<string>>(() => new Set());
  const [artifactIds, setArtifactIds] = useState<Set<string>>(() => new Set());
  const [evidenceIds, setEvidenceIds] = useState<Set<string>>(() => new Set());
  const [shareConsent, setShareConsent] = useState(false);
  const [rightsConfirmation, setRightsConfirmation] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    const [available, active] = await Promise.all([
      listOverlayPublicationCandidates(getToken, workspace),
      getCurrentOverlayPublication(getToken, workspace),
    ]);
    const snapshot = active
      ? await getCurrentOverlayPublicationSnapshot(getToken, workspace)
      : null;
    setCandidates(available);
    setCurrent(active);
    setCurrentSnapshot(snapshot);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    void Promise.all([
      listOverlayPublicationCandidates(getToken, workspace),
      getCurrentOverlayPublication(getToken, workspace),
    ]).then(async ([available, request]) => {
      const snapshot = request
        ? await getCurrentOverlayPublicationSnapshot(getToken, workspace)
        : null;
      if (!active) return;
      setCandidates(available);
      setCurrent(request);
      setCurrentSnapshot(snapshot);
    }).catch((caught: unknown) => {
      if (active) setError(caught instanceof Error ? caught.message : "Private sharing options could not load.");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [getToken, workspace]);

  const documents = useMemo(
    () => new Map(candidates.documents.map((item) => [item.id, item])),
    [candidates.documents],
  );
  const selectedCount = nodeIds.size + documentVersionIds.size + artifactIds.size + evidenceIds.size;
  const activeRequest = current?.status === "pending" || current?.status === "approved";

  function toggleDocument(id: string, checked: boolean) {
    setDocumentVersionIds((values) => toggleValue(values, id, checked));
    if (!checked) {
      setArtifactIds((values) => new Set(
        [...values].filter((artifactId) => candidates.artifacts.find(
          (item) => item.id === artifactId,
        )?.documentVersionId !== id),
      ));
      setEvidenceIds((values) => new Set(
        [...values].filter((evidenceId) => candidates.evidence.find(
          (item) => item.id === evidenceId,
        )?.documentVersionId !== id),
      ));
    }
  }

  function toggleNode(id: string, checked: boolean) {
    setNodeIds((values) => toggleValue(values, id, checked));
    if (!checked) {
      setEvidenceIds((values) => new Set(
        [...values].filter((evidenceId) => {
          const evidence = candidates.evidence.find((item) => item.id === evidenceId);
          return !evidence?.nodeIsPrivate || evidence.nodeId !== id;
        }),
      ));
    }
  }

  async function submit() {
    if (selectedCount === 0 || !shareConsent || !rightsConfirmation) return;
    setBusy(true);
    setError("");
    try {
      const request = await submitOverlayPublication(getToken, workspace, {
        nodeIds: [...nodeIds].sort(),
        documentVersionIds: [...documentVersionIds].sort(),
        artifactIds: [...artifactIds].sort(),
        evidenceIds: [...evidenceIds].sort(),
        shareSelectedContentConsent: true,
        rightsConfirmation: true,
        consentVersion: "v1",
      });
      setCurrent(request);
      setCurrentSnapshot(await getCurrentOverlayPublicationSnapshot(getToken, workspace));
      setShareConsent(false);
      setRightsConfirmation(false);
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "The selected Overlay was not submitted.");
    } finally {
      setBusy(false);
    }
  }

  async function withdraw() {
    setBusy(true);
    setError("");
    try {
      await withdrawOverlayPublication(getToken, workspace);
      setCurrent(null);
      setCurrentSnapshot(null);
      await load();
    } catch (caught: unknown) {
      setError(caught instanceof Error ? caught.message : "The Overlay could not be withdrawn.");
    } finally {
      setBusy(false);
    }
  }

  return <details className="overlay-publication-panel">
    <summary>Share selected private Overlay</summary>
    <div className="overlay-publication-content">
      <p>Everything starts unchecked. Only the exact private versions you select enter the admin review snapshot. Chats, progress, grades, solutions, assessments, and all unselected content stay outside it.</p>
      <p className="privacy-notice"><strong>Private derivation rule:</strong> AI-generated descriptions and artifacts remain private unless their exact resource is checked here.</p>
      {error && <p className="alert alert-error" role="alert">{error}</p>}
      {loading && <p aria-live="polite">Loading your private publication candidates…</p>}
      {current && !activeRequest && <p role="status">Previous request: <strong>{current.status}</strong>{current.reviewNote ? ` · ${current.reviewNote}` : ""}. You may prepare a new exact snapshot.</p>}
      {activeRequest && current ? <section className="overlay-current-release" aria-label="Current Overlay publication">
        <div className="panel-heading"><h3>{current.courseName} Overlay</h3><span>{current.status}</span></div>
        <p>{current.resourceCount} resources · snapshot <code>{shortHash(current.snapshotHash)}</code></p>
        {currentSnapshot && <ul className="overlay-current-resources">{currentSnapshot.resources.map((resource) => <li key={`${resource.kind}:${resource.id}:${resource.version}`}>
          <strong>{resource.displayName}</strong> · {resource.kind} v{resource.version}
        </li>)}</ul>}
        <p>Withdrawal stops future access and invalidates the active release cache. It cannot recall copies that were already downloaded while access was lawful.</p>
        <button className="button danger-button" disabled={busy} onClick={() => void withdraw()} type="button">Withdraw shared Overlay</button>
      </section> : !loading && <>
        <fieldset>
          <legend>1. Private knowledge nodes and exact Teaching Specs</legend>
          {candidates.nodes.map((node) => <label className="publication-candidate" key={node.id}>
            <input
              aria-label={`Share node ${node.title}`}
              checked={nodeIds.has(node.id)}
              onChange={(event) => toggleNode(node.id, event.target.checked)}
              type="checkbox"
            />
            <span><strong>Share node {node.title}</strong><small>{node.kind} · exact Spec v{node.specVersion ?? "none"}</small></span>
          </label>)}
          {!candidates.nodes.length && <p>No private knowledge nodes are available.</p>}
        </fieldset>

        <fieldset>
          <legend>2. Private document versions</legend>
          {candidates.documents.map((document) => <label className="publication-candidate" key={document.id}>
            <input
              aria-label={`Share document ${document.filename} version ${document.version}`}
              checked={documentVersionIds.has(document.id)}
              disabled={document.status !== "ready"}
              onChange={(event) => toggleDocument(document.id, event.target.checked)}
              type="checkbox"
            />
            <span><strong>Share document {document.filename} version {document.version}</strong><small>{fileSize(document.byteSize)} · {document.status} · SHA-256 {shortHash(document.sha256)}</small></span>
          </label>)}
          {!candidates.documents.length && <p>No private document version is available.</p>}
        </fieldset>

        <fieldset>
          <legend>3. Private derived artifacts</legend>
          {candidates.artifacts.map((artifact) => {
            const document = documents.get(artifact.documentVersionId);
            const enabled = documentVersionIds.has(artifact.documentVersionId);
            return <label className="publication-candidate" key={artifact.id}>
              <input
                aria-label={`Share derived ${artifact.kind} for ${document?.filename ?? artifact.documentVersionId} v${document?.version ?? "?"}`}
                checked={artifactIds.has(artifact.id)}
                disabled={!enabled}
                onChange={(event) => setArtifactIds((values) => toggleValue(values, artifact.id, event.target.checked))}
                type="checkbox"
              />
              <span><strong>Share derived {artifact.kind} for {document?.filename ?? artifact.documentVersionId} v{document?.version ?? "?"}</strong><small>Select its exact source document first · producer v{artifact.producerVersion} · {fileSize(artifact.byteSize)}</small></span>
            </label>;
          })}
          {!candidates.artifacts.length && <p>No shareable private derived artifact is available.</p>}
        </fieldset>

        <fieldset>
          <legend>4. Private evidence links</legend>
          {candidates.evidence.map((evidence) => {
            const dependenciesSelected = documentVersionIds.has(evidence.documentVersionId)
              && (!evidence.nodeIsPrivate || nodeIds.has(evidence.nodeId));
            return <label className="publication-candidate" key={evidence.id}>
              <input
                aria-label={`Share evidence ${evidence.nodeTitle} at ${evidence.locatorType} ${evidence.locatorValue}`}
                checked={evidenceIds.has(evidence.id)}
                disabled={!dependenciesSelected}
                onChange={(event) => setEvidenceIds((values) => toggleValue(values, evidence.id, event.target.checked))}
                type="checkbox"
              />
              <span><strong>Share evidence {evidence.nodeTitle} at {evidence.locatorType} {evidence.locatorValue}</strong><small>Select the exact document{evidence.nodeIsPrivate ? " and private node" : ""} first.</small></span>
            </label>;
          })}
          {!candidates.evidence.length && <p>No private evidence link is available.</p>}
        </fieldset>

        <div className="publication-consent">
          <p><strong>Selected:</strong> {selectedCount} explicit resources. Required linked Specs are included only with their checked node.</p>
          <label><input checked={shareConsent} onChange={(event) => setShareConsent(event.target.checked)} type="checkbox" /> I choose to share only the checked private resources</label>
          <label><input checked={rightsConfirmation} onChange={(event) => setRightsConfirmation(event.target.checked)} type="checkbox" /> I confirm I have rights to share these exact versions and their selected derived content</label>
          <button
            className="button button-primary"
            disabled={busy || selectedCount === 0 || !shareConsent || !rightsConfirmation}
            onClick={() => void submit()}
            type="button"
          >Submit selected Overlay for review</button>
        </div>
      </>}
    </div>
  </details>;
}
