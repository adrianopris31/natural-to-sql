import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocsAnswer } from "@/components/chat/docs-answer";
import { Turn } from "@/lib/types";

describe("DocsAnswer Component", () => {
  const baseTurn: Turn = {
    id: "turn-docs-1",
    kind: "docs",
    question: "How do we deploy to production?",
    sql: null,
    columns: null,
    rows: null,
    row_count: null,
    truncated: null,
    queries: null,
    answer: "Follow the deployment steps in **Release Runbook**.",
    sources: [
      {
        id: "PROJ-123",
        source_type: "jira",
        title: "Deployment Checklist",
        url: "https://jira.example.com/browse/PROJ-123",
        score: 0.9,
      },
      {
        id: "DOC-45",
        source_type: "doc",
        title: "Production Runbook",
        url: "https://docs.example.com/runbook",
        score: 0.85,
      },
      {
        id: "SLACK-1",
        source_type: "slack",
        title: "#ops discussion",
        url: "https://slack.example.com/archives/C1/p1",
        score: 0.7,
      },
    ],
    status: "done",
    error: null,
    created_at: "2026-10-01T10:00:00Z",
  };

  it("renders markdown answer and source chips with external links", () => {
    render(<DocsAnswer turn={baseTurn} isStreaming={false} />);

    expect(screen.getByText(/Follow the deployment steps in/i)).toBeInTheDocument();
    expect(screen.getByText("Release Runbook")).toBeInTheDocument();
    expect(screen.getByText("Sources cited (3)")).toBeInTheDocument();

    const jiraLink = screen.getByRole("listitem", { name: /PROJ-123: Deployment Checklist/i });
    expect(jiraLink).toHaveAttribute("href", "https://jira.example.com/browse/PROJ-123");
    expect(jiraLink).toHaveAttribute("target", "_blank");
    expect(jiraLink).toHaveAttribute("rel", "noopener noreferrer");

    const docLink = screen.getByRole("listitem", { name: /DOC-45: Production Runbook/i });
    expect(docLink).toHaveAttribute("href", "https://docs.example.com/runbook");

    const slackLink = screen.getByRole("listitem", { name: /SLACK-1: #ops discussion/i });
    expect(slackLink).toHaveAttribute("href", "https://slack.example.com/archives/C1/p1");
  });

  it("renders 'Not found in the documents' card when answer is a refusal", () => {
    const refusedTurn: Turn = {
      ...baseTurn,
      answer: "The provided documents do not contain information to answer this question.",
      sources: [],
    };

    render(<DocsAnswer turn={refusedTurn} isStreaming={false} />);

    expect(screen.getByRole("region", { name: /not found in the documents/i })).toBeInTheDocument();
    expect(screen.getByText("Not found in the documents")).toBeInTheDocument();
    expect(
      screen.getByText("The provided documents do not contain information to answer this question.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/sources cited/i)).not.toBeInTheDocument();
  });
});
