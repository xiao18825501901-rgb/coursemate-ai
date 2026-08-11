import type { Citation } from "../types/api";


export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="citation-list" aria-label="Answer sources">
      <p className="citation-heading">Sources used</p>
      {citations.map((citation) => (
        <details className="citation" key={citation.chunkId}>
          <summary>
            <span className="source-label">{citation.sourceLabel}</span>
            <span>{citation.filename}</span>
            <small>
              {citation.locatorType} {citation.locatorValue}
            </small>
          </summary>
          <blockquote>{citation.excerpt}</blockquote>
          <p className="retrieval-channels">
            Found via {citation.channels.join(" + ") || "retrieval"}
          </p>
        </details>
      ))}
    </div>
  );
}
