import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Header } from "@/components/chat/header";
import { ChatLayout } from "@/components/chat/chat-layout";
import { Providers } from "@/components/providers";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("Header Component", () => {
  it("renders title, connection badge, and theme toggle", async () => {
    const onToggleSidebar = vi.fn();

    render(
      <Providers>
        <Header sidebarOpen={false} onToggleSidebar={onToggleSidebar} />
      </Providers>
    );

    expect(screen.getByText("Natural to SQL")).toBeInTheDocument();

    // Health badge loads from MSW
    await waitFor(() => {
      expect(screen.getByText(/Connected/i)).toBeInTheDocument();
    });

    // Theme toggle button
    const themeBtn = screen.getByRole("button", { name: /switch to dark theme/i });
    expect(themeBtn).toBeInTheDocument();
    await userEvent.click(themeBtn);

    // After clicking, button flips aria-label to light theme
    expect(
      screen.getByRole("button", { name: /switch to light theme/i })
    ).toBeInTheDocument();
  });
});

describe("ChatLayout Component", () => {
  it("renders empty state with example prompts and populates input", async () => {
    render(
      <Providers>
        <ChatLayout />
      </Providers>
    );

    expect(screen.getByText("Ask anything about your database")).toBeInTheDocument();

    const promptBtn = screen.getByRole("button", {
      name: "Top 10 users by total spend",
    });
    expect(promptBtn).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/Ask a question about your database/i);
    expect(textarea).toHaveValue("");

    await userEvent.click(promptBtn);
    expect(textarea).toHaveValue("Top 10 users by total spend");
  });

  it("handles input typing and send button interaction", async () => {
    render(
      <Providers>
        <ChatLayout />
      </Providers>
    );

    const textarea = screen.getByPlaceholderText(/Ask a question about your database/i);
    const sendBtn = screen.getByRole("button", { name: /send message/i });

    // Send button disabled when empty
    expect(sendBtn).toBeDisabled();

    await userEvent.type(textarea, "Show me all products");
    expect(textarea).toHaveValue("Show me all products");
    expect(sendBtn).not.toBeDisabled();

    // Sending resets the input
    await userEvent.click(sendBtn);
    expect(textarea).toHaveValue("");
  });
});
