import { fireEvent, render, screen } from "@testing-library/react";
import React, { useState } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Inbox } from "./pages.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

test("inbox accepts loaded rows after a StrictMode remount", () => {
  const load = vi.spyOn(Inbox.prototype, "load").mockResolvedValue(undefined);
  const instance: any = new (Inbox as any)({});
  instance.unmounted = true;

  instance.componentDidMount();

  expect(instance.unmounted).toBe(false);
  expect(load).toHaveBeenCalledOnce();
  instance.componentWillUnmount();
});

test("inbox chrome translates without changing paging, tab, selection, or reply draft", () => {
  vi.spyOn(Inbox.prototype, "componentDidMount").mockImplementation(function (this: any) {
    this.setState({
      inboxPage: 1,
      tab: "all",
      selected: {
        id: "TEST_ONLY-thread",
        kind: "thread",
        peer: { id: "TEST_ONLY-peer", name: "用户联系人 Qwen", handle: "user-contact" },
      },
      messages: [],
      reply: "保留未发送私信草稿",
    });
  });
  let instance: any;
  const fetchSpy = vi.spyOn(globalThis, "fetch");
  render(<UiLocaleProvider><LanguageControl/><Inbox
    ref={value => { instance = value; }}
    user={{ id: "TEST_ONLY-user" }}
    config={{ student_verification_required_for_campus: true }}
    toast={vi.fn()} modal={vi.fn()} closeModal={vi.fn()} onRead={vi.fn()}
  /></UiLocaleProvider>);

  const replyDraft = screen.getByDisplayValue("保留未发送私信草稿");
  fireEvent.click(screen.getByRole("button", { name: "English" }));

  expect(screen.getByRole("heading", { name: "Inbox" })).toBeVisible();
  expect(screen.getByText("Replies and conversations related to your courses.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Share course" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Compose" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "Inbox pagination" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Previous notifications and shares" })).toBeVisible();
  expect(screen.getByText("Page 2")).toBeVisible();
  expect(screen.getByRole("button", { name: "Next notifications and shares" })).toBeVisible();
  expect(screen.getByRole("button", { name: "All" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Comment replies" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Direct messages" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Shared" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Block this contact" })).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Direct-message reply" })).toHaveValue("保留未发送私信草稿");
  expect(screen.getByRole("button", { name: "Send reply" })).toBeVisible();
  expect(screen.getByText("用户联系人 Qwen")).toBeVisible();
  expect(replyDraft).toBeInTheDocument();
  expect(instance.state.inboxPage).toBe(1);
  expect(instance.state.selected.id).toBe("TEST_ONLY-thread");
  expect(fetchSpy).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Shared" }));
  expect(screen.getByRole("button", { name: "Received" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Sent" })).toBeVisible();
  expect(screen.getByText("No shared courses yet")).toBeVisible();
  expect(instance.state.reply).toBe("保留未发送私信草稿");
});

test("compose and sharing dialogs use the current interface language", async () => {
  vi.spyOn(Inbox.prototype, "componentDidMount").mockImplementation(() => undefined);
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify([]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));

  function Harness() {
    const [dialog, setDialog] = useState<{ title: string; body: React.ReactNode } | null>(null);
    return <UiLocaleProvider>
      <LanguageControl/>
      <Inbox
        user={{ id: "TEST_ONLY-user" }}
        config={{ student_verification_required_for_campus: true }}
        toast={vi.fn()}
        modal={(title: string, body: React.ReactNode) => setDialog({ title, body })}
        closeModal={() => setDialog(null)}
        onRead={vi.fn()}
      />
      {dialog && <section aria-label="test dialog"><h2>{dialog.title}</h2>{dialog.body}</section>}
    </UiLocaleProvider>;
  }

  render(<Harness/>);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByRole("button", { name: "Compose" }));
  expect(screen.getByRole("heading", { name: "Compose" })).toBeVisible();
  expect(screen.getByText("Recipient")).toBeVisible();
  expect(screen.getByText("Message")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "Find users" })).toHaveAttribute("placeholder", "Browse users or search by name or username");
  expect(screen.getByRole("button", { name: "Previous users" })).toBeVisible();
  expect(screen.getByRole("button", { name: "Next users" })).toBeVisible();
  expect(screen.getByText("Only discoverable users are shown; email addresses and phone numbers stay private.")).toBeVisible();

  fireEvent.click(screen.getByRole("button", { name: "Share course" }));
  expect(screen.getByRole("heading", { name: "Share course" })).toBeVisible();
  expect(await screen.findByRole("heading", { name: "1. Choose a course to share" })).toBeVisible();
  expect(screen.getByText("No courses available to share")).toBeVisible();
});

