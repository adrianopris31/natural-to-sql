import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SqlBlock } from "@/components/chat/sql-block";

describe("SqlBlock Component", () => {
  it("renders SQL query and collapses when isComplete is true", async () => {
    const sql = "SELECT * FROM users WHERE active = 1 LIMIT 10";

    const { rerender } = render(<SqlBlock sql={sql} isComplete={false} />);

    // Initially open when isComplete is false
    expect(screen.getByText(/users/i)).toBeInTheDocument();
    expect(screen.getByText("(Click to collapse)")).toBeInTheDocument();

    // Rerender as complete -> collapsed by default
    rerender(<SqlBlock sql={sql} isComplete={true} />);
    expect(screen.getByText("(Click to view)")).toBeInTheDocument();

    // Click to expand again
    const headerBtn = screen.getByRole("button", { name: /sql query/i });
    await userEvent.click(headerBtn);
    expect(screen.getByText("(Click to collapse)")).toBeInTheDocument();
    expect(screen.getByText(/users/i)).toBeInTheDocument();
  });

  it("handles copy to clipboard", async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    const sql = "SELECT count(*) FROM orders";
    render(<SqlBlock sql={sql} isComplete={false} />);

    const copyBtn = screen.getByRole("button", { name: /copy sql/i });
    await userEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith(sql);
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });
});
