import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ErrorState } from "./ErrorState";
import { Field } from "./Field";
import { Loading } from "./Loading";

it("ties a field's label, hint and error to its input", () => {
  render(<Field label="Email" type="email" required hint="We send the receipt here." error="Enter an email like name@example.com" />);
  const input = screen.getByRole("textbox", {
    name: "Email (required)",
    description: "We send the receipt here. Enter an email like name@example.com",
  });
  expect(input.getAttribute("aria-invalid")).toBe("true");
});

it("announces an error and offers to try again", () => {
  const retry = vi.fn();
  render(<ErrorState onRetry={retry}>We could not load the list. Try again in a moment.</ErrorState>);
  expect(screen.getByRole("alert").textContent).toContain("We could not load the list.");
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(retry).toHaveBeenCalledTimes(1);
});

it("announces loading with a label", () => {
  render(<Loading label="Loading invoices…" />);
  expect(screen.getByRole("status").textContent).toBe("Loading invoices…");
});
