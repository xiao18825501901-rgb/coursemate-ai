import { Link } from "react-router-dom";


export function HomePage() {
  return (
    <div className="page home-page">
      <section className="hero" aria-labelledby="home-title">
        <div className="eyebrow">Your courses, made navigable</div>
        <h1 id="home-title">Study from evidence. Plan with intent.</h1>
        <p className="hero-copy">
          CourseMate turns your own lecture material into cited answers, then helps you turn
          the important parts into a study plan you can actually finish.
        </p>
        <div className="hero-actions">
          <Link className="button button-primary" to="/qa">
            Ask CourseMate
            <span aria-hidden="true">→</span>
          </Link>
          <Link className="button button-secondary" to="/tasks">
            Plan my study
          </Link>
        </div>
        <dl className="proof-strip" aria-label="Product capabilities">
          <div>
            <dt>2</dt>
            <dd>course spaces</dd>
          </div>
          <div>
            <dt>Hybrid</dt>
            <dd>keyword + vector search</dd>
          </div>
          <div>
            <dt>5</dt>
            <dd>validated task tools</dd>
          </div>
        </dl>
      </section>

      <section className="workflow-section" aria-labelledby="workflows-title">
        <div className="section-heading">
          <span className="eyebrow">One desk, two modes</span>
          <h2 id="workflows-title">Move from “what?” to “what next?”</h2>
        </div>
        <div className="workflow-list">
          <article className="workflow-row">
            <span className="workflow-number">01</span>
            <div>
              <p className="workflow-kicker">Course QA</p>
              <h3>Trace every answer back to the source.</h3>
              <p>
                Hybrid retrieval finds relevant pages, slides, and sections. The answer streams
                in with excerpts you can open and verify.
              </p>
            </div>
            <Link aria-label="Open Course QA" className="circle-link" to="/qa">
              ↗
            </Link>
          </article>
          <article className="workflow-row">
            <span className="workflow-number">02</span>
            <div>
              <p className="workflow-kicker">Study agent</p>
              <h3>Turn natural language into visible, editable tasks.</h3>
              <p>
                The assistant can create, find, update, complete, and delete through validated
                task tools—not hidden SQL or guesswork.
              </p>
            </div>
            <Link aria-label="Open Study plan" className="circle-link" to="/tasks">
              ↗
            </Link>
          </article>
        </div>
      </section>
    </div>
  );
}
