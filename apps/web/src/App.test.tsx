import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { AppRoutes } from "./App";
import { TestAuthProvider } from "./auth/AuthProvider";


describe("CourseMate application shell", () => {
  it("renders a content-first landing page with both real workflows", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { level: 1, name: /study from evidence/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /ask coursemate/i })).toHaveAttribute("href", "/qa");
    expect(screen.getByRole("link", { name: /plan my study/i })).toHaveAttribute(
      "href",
      "/tasks",
    );
    expect(screen.getByText(/hybrid retrieval/i)).toBeVisible();
    expect(screen.getByText("validated task tools")).toBeVisible();
  });

  it("marks the active navigation item and exposes a skip link", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(screen.getByRole("link", { name: "About" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("heading", { level: 1, name: /how coursemate works/i })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: /rag, kept visible/i })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: /agent, kept accountable/i })).toBeVisible();
  });

  it("offers recovery from an unknown route", () => {
    render(
      <MemoryRouter initialEntries={["/does-not-exist"]}>
        <AppRoutes />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { level: 1, name: /page not found/i })).toBeVisible();
    expect(screen.getByRole("link", { name: /return home/i })).toHaveAttribute("href", "/");
  });

  it("keeps private navigation and routes behind sign-in", () => {
    const { rerender } = render(
      <TestAuthProvider token={null}>
        <MemoryRouter initialEntries={["/tasks"]}>
          <AppRoutes />
        </MemoryRouter>
      </TestAuthProvider>,
    );

    expect(screen.getByRole("heading", { name: /sign in to continue/i })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Study plan" })).not.toBeInTheDocument();

    rerender(
      <TestAuthProvider token="token-a">
        <MemoryRouter initialEntries={["/about"]}>
          <AppRoutes />
        </MemoryRouter>
      </TestAuthProvider>,
    );
    expect(screen.getByRole("link", { name: "Study plan" })).toBeVisible();
    expect(screen.getByText("Test Student")).toBeVisible();
  });
});
