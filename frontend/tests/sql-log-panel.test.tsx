import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SqlLogPanel } from "@/components/chat/sql-log-panel";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(open: boolean, onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SqlLogPanel open={open} onClose={onClose} />
    </QueryClientProvider>
  );
  return onClose;
}

describe("SqlLogPanel", () => {
  it("lists every SQL event with its stage", async () => {
    renderPanel(true);
    expect(await screen.findByText("Executed")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("DELETE FROM users WHERE id = 1")).toBeInTheDocument();
    expect(screen.getByText(/Forbidden statement type/)).toBeInTheDocument();
    expect(screen.getByText("1 rows")).toBeInTheDocument();
  });

  it("renders nothing when closed", () => {
    renderPanel(false);
    expect(screen.queryByRole("dialog", { name: "SQL log" })).toBeNull();
  });

  it("closes on Escape", async () => {
    const onClose = renderPanel(true);
    await screen.findByText("Executed");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
