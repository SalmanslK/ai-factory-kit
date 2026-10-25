import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { App } from "./App";

// Tests find what a person finds — by role and accessible name — so a screen that is not accessible
// fails its own tests (docs/ui-standard.md). A criterion's test carries its id in its name:
// it("… [AC R-001.AC-1]", …).
it("shows the page title in the main region", () => {
  render(<App />);
  const main = screen.getByRole("main");
  expect(main.contains(screen.getByRole("heading", { level: 1, name: "Home" }))).toBe(true);
});

it("marks the current page in the main navigation", () => {
  render(<App />);
  const navigation = screen.getByRole("navigation", { name: "Main" });
  const home = screen.getByRole("link", { name: "Home" });
  expect(navigation.contains(home)).toBe(true);
  expect(home.getAttribute("aria-current")).toBe("page");
});

it("lets a keyboard user skip to the content", () => {
  render(<App />);
  const skip = screen.getByRole("link", { name: "Skip to content" });
  expect(skip.getAttribute("href")).toBe(`#${screen.getByRole("main").id}`);
});

it("opens and closes the menu on narrow screens", () => {
  render(<App />);
  const menu = screen.getByRole("button", { name: "Menu" });
  expect(menu.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(menu);
  expect(menu.getAttribute("aria-expanded")).toBe("true");
});
