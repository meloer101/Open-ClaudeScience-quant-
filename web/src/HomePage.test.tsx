import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { HomePage } from "./HomePage";

test("renders the QuantBench homepage content", () => {
  render(<HomePage />);

  expect(screen.getAllByText("QuantBench")[0]).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /From idea to audited backtest\./i })).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: /Open the workbench|Open workbench/i }).length).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: /See how it works/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Discover & code factors/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Backtest with a Reviewer/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /Reproducible artifacts/i })).toBeInTheDocument();
});

test("all entry points into the workbench point at /app", () => {
  render(<HomePage />);

  const workbenchLinks = screen.getAllByRole("link", { name: /Open the workbench|Open workbench/i });
  for (const link of workbenchLinks) {
    expect(link).toHaveAttribute("href", "/app");
  }
});

test("lets visitors lightly spotlight the product preview", async () => {
  const user = userEvent.setup();
  render(<HomePage />);

  const tourButton = screen.getByRole("button", { name: /See how it works/i });
  expect(tourButton).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByLabelText("Backtest workspace preview")).not.toHaveAttribute("data-spotlight", "true");

  await user.click(tourButton);

  expect(tourButton).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByLabelText("Backtest workspace preview")).toHaveAttribute("data-spotlight", "true");
});

test("lets visitors switch the homepage between English and Chinese", async () => {
  const user = userEvent.setup();
  render(<HomePage />);

  expect(screen.getByRole("heading", { name: /From idea to audited backtest\./i })).toBeInTheDocument();

  const langButton = screen.getByRole("button", { name: /switch language/i });
  await user.click(langButton);

  expect(screen.getByRole("heading", { name: /从一个想法，到\s*经审查的回测。/ })).toBeInTheDocument();
  for (const link of screen.getAllByRole("link", { name: "打开工作台" })) {
    expect(link).toHaveAttribute("href", "/app");
  }

  await user.click(langButton);

  expect(screen.getByRole("heading", { name: /From idea to audited backtest\./i })).toBeInTheDocument();
});
