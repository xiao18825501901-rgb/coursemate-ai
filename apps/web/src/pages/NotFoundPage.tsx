import { Link } from "react-router-dom";


export function NotFoundPage() {
  return (
    <div className="page centered-state">
      <span className="state-code">404</span>
      <h1>Page not found</h1>
      <p>The study path you followed does not exist.</p>
      <Link className="button button-primary" to="/">
        Return home
      </Link>
    </div>
  );
}
