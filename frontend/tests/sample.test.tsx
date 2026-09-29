import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/ui/button";

describe("Sample Vitest Suite", () => {
  it("renders a button component correctly", () => {
    render(<Button>Click me</Button>);
    const button = screen.getByRole("button", { name: /click me/i });
    expect(button).toBeInTheDocument();
  });

  it("basic arithmetic assertion", () => {
    expect(1 + 1).toBe(2);
  });
});
