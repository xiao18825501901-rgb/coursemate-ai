import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";

import { RichText } from "./richtext.jsx";
import { LanguageControl, UiLocaleProvider } from "./UiLocale";

afterEach(() => {
  delete (window as any).CourseMateMath;
});

test("formula fallback help follows UI locale without rewriting the expression", () => {
  (window as any).CourseMateMath = { renderToString: () => { throw new Error("TEST_ONLY"); } };
  render(<UiLocaleProvider><LanguageControl/><RichText text="$x+y$" message={undefined} /></UiLocaleProvider>);
  expect(screen.getByTitle("公式未完整或暂不支持，显示原始表达式")).toHaveTextContent("x+y");

  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(screen.getByTitle("The formula is incomplete or unsupported; showing the original expression")).toHaveTextContent("x+y");
});

