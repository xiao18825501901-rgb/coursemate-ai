import { fireEvent, render, screen } from "@testing-library/react";
import { useContext, useEffect, useState } from "react";
import { beforeEach, expect, test, vi } from "vitest";
import { UiLocaleContext, UiLocaleProvider, LanguageControl, dictionaryParity } from "./UiLocale";

beforeEach(() => localStorage.clear());

test("all supplied dictionary keys and interpolation fields match", () => {
  expect(dictionaryParity()).toEqual([]);
});

test("language switch preserves mounted answer editor, session identity and content", () => {
  const unmount = vi.fn();
  const calls = vi.fn();
  function Session() {
    const { t } = useContext(UiLocaleContext);
    const [answer, setAnswer] = useState("原始答案 DeepSeek");
    useEffect(() => { calls(); return unmount; }, []);
    return <><label htmlFor="answer">{t("assessment.answerPlaceholder")}</label>
      <input id="answer" value={answer} onChange={event => setAnswer(event.target.value)} />
      <div data-testid="session">pair-a/run-b/session-c/intent-d/revision-e</div>
      <p lang="zh-CN">原始教学 Qwen，不是系统型号标签。</p></>;
  }
  render(<UiLocaleProvider><LanguageControl /><Session /></UiLocaleProvider>);
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "草稿保持" } });
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByRole("textbox")).toBe(input);
  expect(input).toHaveValue("草稿保持");
  expect(screen.getByTestId("session")).toHaveTextContent("pair-a/run-b/session-c/intent-d/revision-e");
  expect(screen.getByText("原始教学 Qwen，不是系统型号标签。")).toHaveAttribute("lang", "zh-CN");
  expect(document.documentElement.lang).toBe("en");
  expect(calls).toHaveBeenCalledTimes(1);
  expect(unmount).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "true");
});

test("owner scopes are independent and explicit server preference wins", () => {
  function OwnerButtons() {
    const { setOwner, locale } = useContext(UiLocaleContext);
    return <><button onClick={() => setOwner("A")}>Owner A</button>
      <button onClick={() => setOwner("B")}>Owner B</button>
      <button onClick={() => setOwner("A", "zh-CN")}>Server A</button>
      <span data-testid="locale">{locale}</span></>;
  }
  render(<UiLocaleProvider><LanguageControl /><OwnerButtons /></UiLocaleProvider>);
  fireEvent.click(screen.getByRole("button", { name: "Owner A" }));
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  fireEvent.click(screen.getByRole("button", { name: "Owner B" }));
  expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
  fireEvent.click(screen.getByRole("button", { name: "Owner A" }));
  expect(screen.getByTestId("locale")).toHaveTextContent("en");
  fireEvent.click(screen.getByRole("button", { name: "Server A" }));
  expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
});
