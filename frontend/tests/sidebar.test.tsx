import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sidebar } from "@/components/chat/sidebar";
import { Providers } from "@/components/providers";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("Sidebar Component", () => {
  it("renders New Chat button and handles click", async () => {
    const onNewChat = vi.fn();
    const onSelectConversation = vi.fn();

    render(
      <Providers>
        <Sidebar
          onNewChat={onNewChat}
          onSelectConversation={onSelectConversation}
        />
      </Providers>
    );

    const newChatBtn = screen.getByRole("button", { name: /new chat/i });
    expect(newChatBtn).toBeInTheDocument();

    await userEvent.click(newChatBtn);
    expect(onNewChat).toHaveBeenCalledTimes(1);
  });

  it("renders conversation list from API and allows selecting", async () => {
    const onNewChat = vi.fn();
    const onSelectConversation = vi.fn();

    render(
      <Providers>
        <Sidebar
          activeConversationId="conv-1"
          onNewChat={onNewChat}
          onSelectConversation={onSelectConversation}
        />
      </Providers>
    );

    // Wait for conversations to load from MSW
    await waitFor(() => {
      expect(screen.getByText("Top 10 users by total spend")).toBeInTheDocument();
    });

    expect(screen.getByText("Monthly revenue in 2025")).toBeInTheDocument();

    // Select second conversation
    const secondConvBtn = screen.getByText("Monthly revenue in 2025");
    await userEvent.click(secondConvBtn);
    expect(onSelectConversation).toHaveBeenCalledWith("conv-2");
  });

  it("renders SchemaBrowser with tables and expands columns", async () => {
    render(
      <Providers>
        <Sidebar
          onNewChat={vi.fn()}
          onSelectConversation={vi.fn()}
        />
      </Providers>
    );

    // Wait for schema to load
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
      expect(screen.getByText("products")).toBeInTheDocument();
      expect(screen.getByText("orders")).toBeInTheDocument();
    });

    // Expand "users" table
    const usersTableBtn = screen.getByRole("button", { name: /^users/i });
    await userEvent.click(usersTableBtn);

    // Should display columns of users table
    expect(screen.getByText("email")).toBeInTheDocument();
  });
});
