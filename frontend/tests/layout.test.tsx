import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
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

    // Integration Settings button opens settings dialog
    const settingsBtn = screen.getByRole("button", {
      name: /integration settings/i,
    });
    expect(settingsBtn).toBeInTheDocument();
    await userEvent.click(settingsBtn);

    expect(
      screen.getByRole("dialog", { name: "Integration Settings" })
    ).toBeInTheDocument();
  });

  it("hides settings gear button when settings_ui_enabled is explicitly false", async () => {
    server.use(
      http.get("/api/health", () => {
        return HttpResponse.json({
          db: "ok",
          ollama: "ok",
          model: "qwen2.5-coder:7b",
          db_version: "9.0.1",
          settings_ui_enabled: false,
        });
      })
    );

    render(
      <Providers>
        <Header sidebarOpen={false} onToggleSidebar={vi.fn()} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByText(/Connected/i)).toBeInTheDocument();
    });

    expect(
      screen.queryByRole("button", { name: /integration settings/i })
    ).not.toBeInTheDocument();
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

  it("toggles between Data and Docs mode and updates placeholder and empty state", async () => {
    render(
      <Providers>
        <ChatLayout />
      </Providers>
    );

    // Initial state is Data
    expect(screen.getByRole("radio", { name: /data mode/i })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByPlaceholderText(/Ask a question about your database/i)).toBeInTheDocument();
    expect(screen.getByText("Ask anything about your database")).toBeInTheDocument();

    // Switch to Docs mode
    const docsRadio = screen.getByRole("radio", { name: /^docs mode/i });
    await userEvent.click(docsRadio);

    expect(docsRadio).toHaveAttribute("aria-checked", "true");
    expect(screen.getByPlaceholderText(/Ask a question about Jira, Slack, or docs/i)).toBeInTheDocument();
    expect(screen.getByText("Ask anything about your team docs")).toBeInTheDocument();

    // Docs example prompt is present
    const docsPromptBtn = screen.getByRole("button", { name: "How do we deploy to production?" });
    expect(docsPromptBtn).toBeInTheDocument();
    await userEvent.click(docsPromptBtn);
    expect(screen.getByPlaceholderText(/Ask a question about Jira, Slack, or docs/i)).toHaveValue(
      "How do we deploy to production?"
    );
  });

  it("filters docs queries with source filter chips", async () => {
    render(
      <Providers>
        <ChatLayout />
      </Providers>
    );

    // Switch to Docs mode to reveal source chips
    await userEvent.click(screen.getByRole("radio", { name: /^docs mode/i }));

    const textarea = screen.getByPlaceholderText(/Ask a question about Jira, Slack, or docs/i);
    expect(textarea).toHaveValue("");

    // Click Jira filter
    const jiraBtn = screen.getByRole("button", { name: "Jira" });
    await userEvent.click(jiraBtn);
    expect(textarea).toHaveValue("jira: ");
    expect(jiraBtn).toHaveAttribute("aria-pressed", "true");

    // Click Slack filter
    const slackBtn = screen.getByRole("button", { name: "Slack" });
    await userEvent.click(slackBtn);
    expect(textarea).toHaveValue("slack: ");
    expect(slackBtn).toHaveAttribute("aria-pressed", "true");
    expect(jiraBtn).toHaveAttribute("aria-pressed", "false");

    // Click All filter
    const allBtn = screen.getByRole("button", { name: "All" });
    await userEvent.click(allBtn);
    expect(textarea).toHaveValue("");
    expect(allBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("disables Docs mode when knowledge-bot is unreachable", async () => {
    server.use(
      http.get("/api/health", () => {
        return HttpResponse.json({
          db: "ok",
          ollama: "ok",
          model: "qwen2.5-coder:7b",
          db_version: "9.0.1",
          knowledge_bot: {
            configured: true,
            reachable: false,
          },
        });
      })
    );

    render(
      <Providers>
        <ChatLayout />
      </Providers>
    );

    await waitFor(() => {
      const docsRadio = screen.getByRole("radio", { name: /docs mode/i });
      expect(docsRadio).toBeDisabled();
      expect(docsRadio).toHaveAttribute("title", "Knowledge Bot service is unreachable");
    });
  });
});
