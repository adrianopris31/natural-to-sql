import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { SettingsDialog } from "@/components/chat/settings-dialog";
import { Providers } from "@/components/providers";
import { server } from "./mocks/server";
import {
  lastDeletedSource,
  lastSavedJira,
  lastSavedSlack,
  lastTestedSource,
  refreshDocumentsCalled,
} from "./mocks/handlers";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  lastSavedJira.body = null;
  lastSavedSlack.body = null;
  lastTestedSource.source = null;
  lastTestedSource.body = null;
  lastDeletedSource.source = null;
  refreshDocumentsCalled.count = 0;
});
afterAll(() => server.close());

describe("SettingsDialog Component", () => {
  it("renders Jira and Slack settings with origin badges and refresh status", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    // Dialog title
    expect(
      screen.getByRole("dialog", { name: "Integration Settings" })
    ).toBeInTheDocument();

    // Both Jira and Slack sections are present
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Slack" })
      ).toBeInTheDocument();
    });

    // Origin badges
    expect(screen.getByText("Stored")).toBeInTheDocument();
    expect(screen.getByText("From .env")).toBeInTheDocument();

    // Check pre-populated non-secret fields for Jira
    expect(screen.getByLabelText(/base url/i)).toHaveValue(
      "https://mycompany.atlassian.net"
    );
    expect(screen.getByLabelText(/email/i)).toHaveValue("admin@mycompany.com");
    expect(screen.getByLabelText(/project key/i)).toHaveValue("PROJ");

    // Check pre-populated non-secret fields for Slack
    expect(screen.getByLabelText(/channels/i)).toHaveValue("general, eng");
    expect(screen.getByLabelText(/days back/i)).toHaveValue(14);
    expect(screen.getByLabelText(/max threads/i)).toHaveValue(50);
  });

  it("ensures secret fields are write-only and never pre-filled", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    // Neither real Jira token nor real Slack token should appear in input values or page text
    expect(screen.queryByDisplayValue("tok_secret_12345")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("xoxb-real-secret")).not.toBeInTheDocument();

    // Masked inputs are shown when configured
    const replaceButtons = screen.getAllByRole("button", {
      name: /replace secret/i,
    });
    expect(replaceButtons).toHaveLength(2); // One for Jira, one for Slack

    // Click "Replace secret" on Jira
    await userEvent.click(replaceButtons[0]);

    // An empty password input is now revealed
    const jiraPasswordInput = screen.getByPlaceholderText(
      "Enter new API token"
    );
    expect(jiraPasswordInput).toBeInTheDocument();
    expect(jiraPasswordInput).toHaveValue("");
    expect(jiraPasswordInput).toHaveAttribute("type", "password");
  });

  it("triggers API call and displays inline result on 'Test connection'", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    const testButtons = screen.getAllByRole("button", {
      name: /test connection/i,
    });
    // Click Jira test button (first one)
    await userEvent.click(testButtons[0]);

    await waitFor(() => {
      expect(lastTestedSource.source).toBe("jira");
      expect(
        screen.getByText(/Jira connection verified successfully/i)
      ).toBeInTheDocument();
    });

    // Click Slack test button (second one)
    await userEvent.click(testButtons[1]);

    await waitFor(() => {
      expect(lastTestedSource.source).toBe("slack");
      expect(
        screen.getByText(/Slack connection verified successfully/i)
      ).toBeInTheDocument();
    });
  });

  it("handles test connection failure with error message", async () => {
    server.use(
      http.post("/api/settings/sources/jira/test", () => {
        return HttpResponse.json({
          ok: false,
          message: "Invalid credentials or unauthorized (401)",
        });
      })
    );

    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    const testButtons = screen.getAllByRole("button", {
      name: /test connection/i,
    });
    await userEvent.click(testButtons[0]);

    await waitFor(() => {
      expect(
        screen.getByText("Invalid credentials or unauthorized (401)")
      ).toBeInTheDocument();
    });
  });

  it("triggers PUT on Save and omits secret if left blank", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    // Edit project key
    const projectKeyInput = screen.getByLabelText(/project key/i);
    await userEvent.clear(projectKeyInput);
    await userEvent.type(projectKeyInput, "NEWPROJ");

    // Click Jira Save button
    const saveButtons = screen.getAllByRole("button", { name: /^save$/i });
    await userEvent.click(saveButtons[0]);

    await waitFor(() => {
      expect(lastSavedJira.body).not.toBeNull();
      expect(lastSavedJira.body?.project_key).toBe("NEWPROJ");
      // Secret was not replaced, so api_token must be omitted/undefined
      expect(lastSavedJira.body?.api_token).toBeUndefined();
      expect(
        screen.getByText(/Jira settings saved successfully/i)
      ).toBeInTheDocument();
    });

    // Now test Slack Save with replaced secret
    const replaceButtons = screen.getAllByRole("button", {
      name: /replace secret/i,
    });
    await userEvent.click(replaceButtons[1]); // Slack's replace button

    const botTokenInput = screen.getByPlaceholderText(
      "Enter new bot token (xoxb-...)"
    );
    await userEvent.type(botTokenInput, "xoxb-new-token-1234");

    await userEvent.click(saveButtons[1]);

    await waitFor(() => {
      expect(lastSavedSlack.body).not.toBeNull();
      expect(lastSavedSlack.body?.bot_token).toBe("xoxb-new-token-1234");
      expect(
        screen.getByText(/Slack settings saved successfully/i)
      ).toBeInTheDocument();
    });
  });

  it("triggers DELETE on Disconnect", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    const disconnectButtons = screen.getAllByRole("button", {
      name: /disconnect/i,
    });
    // Jira has configured: true and origin: stored
    await userEvent.click(disconnectButtons[0]);

    await waitFor(() => {
      expect(lastDeletedSource.source).toBe("jira");
    });
  });

  it("triggers refreshDocuments on Refresh all documents", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Jira" })).toBeInTheDocument();
    });

    const refreshAllBtn = screen.getByRole("button", {
      name: /refresh all documents/i,
    });
    await userEvent.click(refreshAllBtn);

    await waitFor(() => {
      expect(refreshDocumentsCalled.count).toBe(1);
      expect(
        screen.getByText("Knowledge base documents re-indexed successfully.")
      ).toBeInTheDocument();
    });
  });

  it("closes dialog on Escape key and close button", async () => {
    const onClose = vi.fn();
    render(
      <Providers>
        <SettingsDialog open={true} onClose={onClose} />
      </Providers>
    );

    const closeBtn = screen.getByRole("button", { name: /close settings/i });
    await userEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
