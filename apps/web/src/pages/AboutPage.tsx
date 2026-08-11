export function AboutPage() {
  return (
    <div className="page narrow-page">
      <header className="page-intro">
        <span className="eyebrow">Built to be explained</span>
        <h1>How CourseMate works</h1>
        <p>
          No orchestration framework hides the important parts. Retrieval, citations, validation,
          and task mutations remain inspectable from request to database row.
        </p>
      </header>
      <div className="architecture-stack">
        <section className="architecture-block">
          <span className="architecture-index">A</span>
          <div>
            <h2>RAG, kept visible</h2>
            <p>
              Documents become located sections and paragraph-aware chunks. FTS5 keyword results
              and OpenAI embedding similarity are ranked separately, then fused by reciprocal rank.
            </p>
            <ol className="flow-steps" aria-label="RAG pipeline">
              <li>Parse</li>
              <li>Chunk</li>
              <li>Retrieve</li>
              <li>Stream + cite</li>
            </ol>
          </div>
        </section>
        <section className="architecture-block">
          <span className="architecture-index">B</span>
          <div>
            <h2>Agent, kept accountable</h2>
            <p>
              The Responses API selects one of five strict functions. Ajv validates every argument,
              an allow-listed executor performs parameterized SQLite work, and the result returns to
              the model for a plain-language confirmation.
            </p>
            <ol className="flow-steps" aria-label="Agent pipeline">
              <li>Interpret</li>
              <li>Validate</li>
              <li>Execute</li>
              <li>Confirm</li>
            </ol>
          </div>
        </section>
      </div>
    </div>
  );
}
