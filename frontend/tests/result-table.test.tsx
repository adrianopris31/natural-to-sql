import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ResultTable } from "@/components/chat/result-table";

describe("ResultTable Component", () => {
  it("renders empty state when rows are empty", () => {
    render(<ResultTable columns={["id", "name"]} rows={[]} />);
    expect(screen.getByText("Query returned no rows")).toBeInTheDocument();
  });

  it("renders columns and row values correctly", () => {
    const columns = ["id", "customer_name", "total_spent", "notes"];
    const rows = [
      [1, "Alice Smith", 1250.5, "VIP customer"],
      [2, "Bob Jones", 450, null],
    ];

    render(<ResultTable columns={columns} rows={rows} rowCount={2} />);

    expect(screen.getByText("customer_name")).toBeInTheDocument();
    expect(screen.getByText("Alice Smith")).toBeInTheDocument();
    expect(screen.getByText("VIP customer")).toBeInTheDocument();

    // Verify NULL rendered with muted style
    const nullCell = screen.getByText("NULL");
    expect(nullCell).toBeInTheDocument();
    expect(nullCell).toHaveClass("italic");

    // Verify number formatted
    expect(screen.getByText("1,250.50")).toBeInTheDocument();
    expect(screen.getByText("450")).toBeInTheDocument();
  });

  it("displays truncated notice when truncated is true", () => {
    const columns = ["id", "name"];
    const rows = [
      [1, "Item 1"],
      [2, "Item 2"],
    ];

    render(
      <ResultTable
        columns={columns}
        rows={rows}
        rowCount={500}
        truncated={true}
      />
    );

    expect(screen.getByText(/Showing 2 of 500 \(truncated\)/i)).toBeInTheDocument();
  });

  it("triggers CSV export when export button is clicked", async () => {
    // Mock URL.createObjectURL and URL.revokeObjectURL
    const createObjectURLMock = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURLMock = vi.fn();
    window.URL.createObjectURL = createObjectURLMock;
    window.URL.revokeObjectURL = revokeObjectURLMock;

    const columns = ["id", "name"];
    const rows = [
      [1, "Alice"],
      [2, "Bob"],
    ];

    render(<ResultTable columns={columns} rows={rows} />);

    const exportBtn = screen.getByRole("button", { name: /export results as csv/i });
    expect(exportBtn).toBeInTheDocument();

    await userEvent.click(exportBtn);

    expect(createObjectURLMock).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledTimes(1);
  });
});
