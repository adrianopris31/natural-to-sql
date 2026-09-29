import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryPreview } from "@/components/chat/query-preview";
import { mockPreviewQuery } from "./mocks/handlers";

describe("QueryPreview (approval gate)", () => {
  it("shows SQL and EXPLAIN summary, runs unchanged queries without overrides", async () => {
    const onRun = vi.fn();
    render(
      <QueryPreview
        queries={[mockPreviewQuery(0, "SELECT id, name FROM users LIMIT 10", "Users")]}
        onRun={onRun}
        onCancel={vi.fn()}
      />
    );

    expect(screen.getByText(/Nothing has run yet/)).toBeInTheDocument();
    expect(screen.getByLabelText("Query plan summary")).toHaveTextContent("EXPLAIN");
    expect(screen.getByText("index scan")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Run query/ }));
    expect(onRun).toHaveBeenCalledWith(undefined);
  });

  it("sends edited SQL only for edited queries", async () => {
    const onRun = vi.fn();
    render(
      <QueryPreview
        queries={[
          mockPreviewQuery(0, "SELECT id FROM users", "A"),
          mockPreviewQuery(1, "SELECT COUNT(*) FROM orders", "B"),
        ]}
        onRun={onRun}
        onCancel={vi.fn()}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "Edit query 2" }));
    const editor = screen.getByLabelText("SQL for query 2");
    await userEvent.clear(editor);
    await userEvent.type(editor, "SELECT COUNT(*) FROM orders WHERE id > 5");
    expect(screen.getByText("edited")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Run queries/ }));
    expect(onRun).toHaveBeenCalledWith([null, "SELECT COUNT(*) FROM orders WHERE id > 5"]);
  });

  it("disables Run while a blocked query is unedited, and cancel works", async () => {
    const onRun = vi.fn();
    const onCancel = vi.fn();
    render(
      <QueryPreview
        queries={[mockPreviewQuery(0, "SELECT a.id FROM orders a JOIN orders b", "Cross", true)]}
        onRun={onRun}
        onCancel={onCancel}
      />
    );

    expect(screen.getByText(/Blocked: Estimated cost/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run query/ })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    expect(onCancel).toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled();
  });

  it("shows the error from a rejected run attempt", () => {
    render(
      <QueryPreview
        queries={[mockPreviewQuery(0, "SELECT 1", "x")]}
        error="Query 1: SQL rejected for safety"
        onRun={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("rejected for safety");
  });
});

describe("QueryPreview risk flags", () => {
  const risky = mockPreviewQuery(0, "SELECT id FROM users WHERE id = 1", "User", false, {
    level: "high",
    flags: [
      {
        code: "UNSAFE_DRAFT_BLOCKED",
        severity: "high",
        message: "The model first generated a DELETE statement; it was blocked.",
      },
      { code: "WRITE_WORDING", severity: "medium", message: "Your question mentions 'delete'." },
    ],
  });

  it("red-flags high-risk queries and requires confirmation before running", async () => {
    const onRun = vi.fn();
    render(<QueryPreview queries={[risky]} onRun={onRun} onCancel={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent("Potentially dangerous");
    expect(screen.getByText(/first generated a DELETE/)).toBeInTheDocument();
    const run = screen.getByRole("button", { name: /Run anyway/ });
    expect(run).toBeDisabled();

    await userEvent.click(screen.getByLabelText(/I reviewed the flagged query/));
    expect(run).toBeEnabled();
    await userEvent.click(run);
    expect(onRun).toHaveBeenCalledWith(undefined);
  });

  it("shows no banner or confirmation for clean queries", () => {
    render(
      <QueryPreview queries={[mockPreviewQuery(0, "SELECT 1", "x")]} onRun={vi.fn()} onCancel={vi.fn()} />
    );
    expect(screen.queryByText(/Potentially dangerous/)).toBeNull();
    expect(screen.getByRole("button", { name: /Run query/ })).toBeEnabled();
  });
});
