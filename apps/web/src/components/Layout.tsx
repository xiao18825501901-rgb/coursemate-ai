import { NavLink, Outlet } from "react-router-dom";

import { SignedInAccount, SignedOutActions, useCourseMateAuth } from "../auth/AuthProvider";


const homeNavigation = { to: "/", label: "Home", end: true };
const aboutNavigation = { to: "/about", label: "About", end: true };
const publicNavigation = [homeNavigation, aboutNavigation];
const privateNavigation = [
  { to: "/qa", label: "Course QA", end: false },
  { to: "/tasks", label: "Study plan", end: false },
  { to: "/documents", label: "Documents", end: false },
];

function BrandMark() {
  return (
    <svg aria-hidden="true" className="brand-mark" viewBox="0 0 40 40">
      <path d="M7 9.5 20 4l13 5.5v19L20 36 7 28.5Z" />
      <path d="m12 17 8-3.5 8 3.5-8 3.5Z" />
      <path d="M14.5 20v5.5c3.5 2.2 7.5 2.2 11 0V20" />
    </svg>
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
        <NavLink aria-label="CourseMate AI home" className="brand" to="/">
          <BrandMark />
          <span>
            <strong>CourseMate</strong>
            <small>AI study desk</small>
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
          {auth.isSignedIn ? <SignedInAccount /> : <SignedOutActions />}
        </div>
      </header>
      <main id="main-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>CourseMate AI</span>
        <span>Grounded answers. Accountable actions.</span>
      </footer>
    </div>
  );
}
