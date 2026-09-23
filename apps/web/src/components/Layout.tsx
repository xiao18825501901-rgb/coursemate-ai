import { NavLink, Outlet } from "react-router-dom";

import { SignedInAccount, SignedOutActions, useCourseMateAuth } from "../auth/AuthProvider";
import { BRAND } from "../brand";


const homeNavigation = { to: "/", label: "Home", end: true };
const aboutNavigation = { to: "/about", label: "About", end: true };
const publicNavigation = [homeNavigation, aboutNavigation];
const privateNavigation = [
  { to: "/courses", label: "Courses", end: false },
  { to: "/qa", label: "Course QA", end: false },
  { to: "/tasks", label: "Study plan", end: false },
  { to: "/documents", label: "Documents", end: false },
];

/**
 * The brand mark: the owner's own artwork, not a drawing of it.
 *
 * The mark is served from `public/brand/` in the sizes derived from the supplied original (see
 * `brand.ts` and `docs/coursejesus/LOGO_ASSET_MANIFEST.md`). It is declared with its real dimensions
 * so the header does not shift while it loads, and its alternative text names the product, because a
 * logo that is only a background image leaves a screen reader with nothing.
 */
function BrandMark() {
  return (
    <img
      alt={BRAND.logoAlt}
      className="brand-mark"
      decoding="async"
      height={40}
      src={BRAND.logoPath}
      width={40}
    />
  );
}

export function Layout() {
  const auth = useCourseMateAuth();
  const navigation = auth.isSignedIn
    ? [homeNavigation, ...privateNavigation, aboutNavigation]
    : publicNavigation;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <NavLink aria-label={`${BRAND.name} home`} className="brand" to="/">
          <BrandMark />
          <span>
            <strong>{BRAND.name}</strong>
            <small>{BRAND.nameZh} · AI study desk</small>
          </span>
        </NavLink>
        <nav aria-label="Primary navigation" className="primary-nav">
          {navigation.map((item) => (
            <NavLink
              className={({ isActive }) => (isActive ? "nav-link nav-link-active" : "nav-link")}
              end={item.end}
              key={item.to}
              to={item.to}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="header-auth">
          {/* The refreshed shell is now the default entry at "/". This is a full
              document link, not a client route, because the two apps keep
              separate documents. */}
          <a className="nav-link" href="/">
            学习空间
          </a>
          {auth.isSignedIn ? <SignedInAccount /> : <SignedOutActions />}
        </div>
      </header>
      <main id="main-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>{BRAND.name}</span>
        <span>{BRAND.tagline}</span>
      </footer>
    </div>
  );
}
