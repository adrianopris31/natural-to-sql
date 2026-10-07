import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DatabaseSelector } from "@/components/chat/database-selector";
import { Providers } from "@/components/providers";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("DatabaseSelector Component", () => {
  it("renders database switcher button and displays active database", async () => {
    render(
      <Providers>
        <DatabaseSelector currentDatabase="default_db" />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /select database/i })).toBeInTheDocument();
    });

    expect(screen.getByText("default_db")).toBeInTheDocument();
  });

  it("automatically initializes default database when currentDatabase is null", async () => {
    const onSelectDatabase = vi.fn();

    render(
      <Providers>
        <DatabaseSelector currentDatabase={null} onSelectDatabase={onSelectDatabase} />
      </Providers>
    );

    await waitFor(() => {
      expect(onSelectDatabase).toHaveBeenCalledWith("default_db");
    });
  });

  it("opens dropdown on click, displays available databases with badges, and switches database", async () => {
    const onSelectDatabase = vi.fn();

    render(
      <Providers>
        <DatabaseSelector currentDatabase="default_db" onSelectDatabase={onSelectDatabase} />
      </Providers>
    );

    const trigger = await screen.findByRole("button", { name: /select database/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    const listbox = screen.getByRole("listbox", { name: /database list/i });
    expect(listbox).toBeInTheDocument();

    // Default badge should be present
    expect(screen.getAllByText("Default").length).toBeGreaterThan(0);

    // Option for analytics_db should be present
    const analyticsOption = screen.getByRole("option", { name: /analytics_db/i });
    expect(analyticsOption).toBeInTheDocument();

    // Click analytics_db option
    await userEvent.click(analyticsOption);

    expect(onSelectDatabase).toHaveBeenCalledWith("analytics_db");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("closes dropdown on Escape key", async () => {
    render(
      <Providers>
        <DatabaseSelector currentDatabase="default_db" />
      </Providers>
    );

    const trigger = await screen.findByRole("button", { name: /select database/i });
    await userEvent.click(trigger);

    expect(screen.getByRole("listbox")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
