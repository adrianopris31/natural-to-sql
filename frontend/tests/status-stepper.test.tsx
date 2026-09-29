import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusStepper } from "@/components/chat/status-stepper";

describe("StatusStepper Component", () => {
  it("renders active step when generating_sql", () => {
    render(<StatusStepper status="generating_sql" />);
    expect(screen.getByText("Generating SQL")).toBeInTheDocument();
    expect(screen.getByText("Validating")).toBeInTheDocument();
    expect(screen.getByText("Executing")).toBeInTheDocument();
    expect(screen.getByText("Answering")).toBeInTheDocument();
  });

  it("renders completed status when done", () => {
    render(<StatusStepper status="done" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders repairing step indicator", () => {
    render(<StatusStepper status="repairing" />);
    expect(screen.getByText("Repairing SQL")).toBeInTheDocument();
  });

  it("renders clarification and error states", () => {
    const { rerender } = render(<StatusStepper status="clarification" />);
    expect(screen.getByText("Clarification needed")).toBeInTheDocument();

    rerender(<StatusStepper status="error" />);
    expect(screen.getByText("Execution failed")).toBeInTheDocument();
  });
});
