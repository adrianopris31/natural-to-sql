import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { HealthBanner } from "@/components/chat/health-banner";
import { Providers } from "@/components/providers";
import { server } from "./mocks/server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("HealthBanner Component", () => {
  it("renders nothing when all services are healthy", async () => {
    const { container } = render(
      <Providers>
        <HealthBanner />
      </Providers>
    );

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    });
    expect(container.firstChild).toBeNull();
  });

  it("renders warning notice when knowledge-bot is configured but unreachable", async () => {
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
        <HealthBanner />
      </Providers>
    );

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
      expect(alert).toHaveTextContent(/Knowledge Bot unreachable \(Docs Q&A unavailable\)/i);
    });
  });

  it("renders warning notice when target DB is down", async () => {
    server.use(
      http.get("/api/health", () => {
        return HttpResponse.json({
          db: "error",
          ollama: "ok",
          model: "qwen2.5-coder:7b",
          db_version: null,
          knowledge_bot: {
            configured: true,
            reachable: true,
          },
        });
      })
    );

    render(
      <Providers>
        <HealthBanner />
      </Providers>
    );

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
      expect(alert).toHaveTextContent(/Target Database unreachable/i);
    });
  });
});
