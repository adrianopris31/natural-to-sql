import { test, expect } from "@playwright/test";

test.describe("Chat & Approval Flow E2E", () => {
  test.beforeEach(async ({ page }) => {
    // Mock health check
    await page.route("**/api/health", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          db: "ok",
          ollama: "ok",
          model: "qwen2.5-coder:7b",
          db_version: "9.0.1",
        }),
      });
    });

    // Mock schema
    await page.route("**/api/schema", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          tables: [
            {
              name: "users",
              columns: [
                { name: "id", type: "int", is_pk: true },
                { name: "name", type: "varchar(100)" },
              ],
            },
          ],
        }),
      });
    });

    // Mock conversations
    await page.route("**/api/conversations", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([]),
        });
      } else {
        await route.continue();
      }
    });
  });

  test("submits question, previews query, and runs on approval", async ({ page }) => {
    // Mock chat generation -> preview
    await page.route("**/api/chat", async (route) => {
      if (route.request().method() === "POST") {
        const sseData = [
          "event: status",
          "data: generating_sql",
          "",
          "event: status",
          "data: validating",
          "",
          "event: status",
          "data: explaining",
          "",
          "event: preview",
          JSON.stringify({
            conversation_id: "conv-e2e-1",
            turn_id: "turn-e2e-1",
            queries: [
              {
                index: 0,
                purpose: "Active users list",
                sql: "SELECT id, name FROM users WHERE status = 'active' LIMIT 10",
                risk: { level: "none", flags: [] },
                explain: {
                  cost: 15.5,
                  estimated_rows: 10,
                  tables: [
                    {
                      table: "users",
                      access_type: "index",
                      key: "PRIMARY",
                      rows_examined: 10,
                      rows_produced: 10,
                    },
                  ],
                  warnings: [],
                  blocked: false,
                  block_reason: null,
                },
                columns: null,
                rows: null,
                row_count: null,
                truncated: null,
                error: null,
              },
            ],
          }),
          "",
        ].join("\n");

        await route.fulfill({
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            Connection: "keep-alive",
          },
          body: sseData,
        });
      }
    });

    // Mock /run endpoint
    await page.route("**/api/chat/turn-e2e-1/run", async (route) => {
      const sseRunData = [
        "event: status",
        "data: executing",
        "",
        "event: result",
        JSON.stringify({
          index: 0,
          sql: "SELECT id, name FROM users WHERE status = 'active' LIMIT 10",
          columns: ["id", "name"],
          rows: [
            [1, "Alice"],
            [2, "Bob"],
          ],
          row_count: 2,
          truncated: false,
          error: null,
        }),
        "",
        "event: status",
        "data: answering",
        "",
        "event: answer_delta",
        "data: Found 2 active ",
        "",
        "event: answer_delta",
        "data:users: Alice and Bob.",
        "",
        "event: done",
        JSON.stringify({
          conversation_id: "conv-e2e-1",
          turn_id: "turn-e2e-1",
        }),
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
        },
        body: sseRunData,
      });
    });

    await page.goto("/");

    // Check textarea is present and input question
    const inputArea = page.getByRole("textbox", { name: "Ask a question" });
    await expect(inputArea).toBeVisible();
    await inputArea.fill("Show active users");
    await inputArea.press("Enter");

    // Preview card should appear
    await expect(page.getByText("Review the query before running")).toBeVisible();
    await expect(page.getByText("SELECT id, name FROM users WHERE status = 'active' LIMIT 10")).toBeVisible();
    await expect(page.getByText("Active users list")).toBeVisible();

    // Click "Run query"
    const runBtn = page.getByRole("button", { name: /Run query/i });
    await expect(runBtn).toBeVisible();
    await runBtn.click();

    // Results table and natural language answer should appear
    await expect(page.getByText("Found 2 active users: Alice and Bob.")).toBeVisible();
    await expect(page.getByRole("cell", { name: "Alice" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Bob" })).toBeVisible();
  });

  test("allows editing SQL in preview before running", async ({ page }) => {
    let capturedRunBody: { queries?: (string | null)[] } | null = null;

    await page.route("**/api/chat", async (route) => {
      const sseData = [
        "event: preview",
        JSON.stringify({
          conversation_id: "conv-e2e-2",
          turn_id: "turn-e2e-2",
          queries: [
            {
              index: 0,
              purpose: "Top users",
              sql: "SELECT id, name FROM users LIMIT 10",
              risk: { level: "none", flags: [] },
              explain: {
                cost: 10,
                estimated_rows: 10,
                tables: [],
                warnings: [],
                blocked: false,
                block_reason: null,
              },
              columns: null,
              rows: null,
            },
          ],
        }),
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: sseData,
      });
    });

    await page.route("**/api/chat/turn-e2e-2/run", async (route) => {
      capturedRunBody = JSON.parse(route.request().postData() || "{}");
      const sseRunData = [
        "event: result",
        JSON.stringify({
          index: 0,
          sql: "SELECT id, name FROM users WHERE id = 1",
          columns: ["id", "name"],
          rows: [[1, "Alice"]],
          row_count: 1,
          truncated: false,
          error: null,
        }),
        "",
        "event: answer_delta",
        "data: User with ID 1 is Alice.",
        "",
        "event: done",
        JSON.stringify({ conversation_id: "conv-e2e-2", turn_id: "turn-e2e-2" }),
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: sseRunData,
      });
    });

    await page.goto("/");

    const inputArea = page.getByRole("textbox", { name: "Ask a question" });
    await inputArea.fill("Show top users");
    await inputArea.press("Enter");

    await expect(page.getByText("Review the query before running")).toBeVisible();

    // Click "Edit"
    const editBtn = page.getByRole("button", { name: "Edit query 1" });
    await expect(editBtn).toBeVisible();
    await editBtn.click();

    // Textarea for editing query 1
    const sqlTextarea = page.getByRole("textbox", { name: "SQL for query 1" });
    await expect(sqlTextarea).toBeVisible();
    await sqlTextarea.fill("SELECT id, name FROM users WHERE id = 1");

    // Click "Done"
    await page.getByRole("button", { name: "Stop editing query 1" }).click();

    // "edited" badge should be shown
    await expect(page.getByText("edited")).toBeVisible();

    // Run the edited query
    const runBtn = page.getByRole("button", { name: /Run query/i });
    await runBtn.click();

    // Verify edited SQL was sent in run request payload
    expect(capturedRunBody).toEqual({ queries: ["SELECT id, name FROM users WHERE id = 1"] });
    await expect(page.getByText("User with ID 1 is Alice.")).toBeVisible();
  });

  test("cancelling a previewed turn dismisses the preview", async ({ page }) => {
    let cancelCalled = false;

    await page.route("**/api/chat", async (route) => {
      const sseData = [
        "event: preview",
        JSON.stringify({
          conversation_id: "conv-e2e-3",
          turn_id: "turn-e2e-3",
          queries: [
            {
              index: 0,
              purpose: "All users",
              sql: "SELECT * FROM users",
              risk: { level: "none", flags: [] },
              explain: { cost: 10, estimated_rows: 5, tables: [], warnings: [], blocked: false, block_reason: null },
            },
          ],
        }),
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: sseData,
      });
    });

    await page.route("**/api/chat/turn-e2e-3/cancel", async (route) => {
      cancelCalled = true;
      await route.fulfill({ status: 204 });
    });

    await page.goto("/");

    const inputArea = page.getByRole("textbox", { name: "Ask a question" });
    await inputArea.fill("Cancel me");
    await inputArea.press("Enter");

    await expect(page.getByText("Review the query before running")).toBeVisible();

    // Click "Cancel"
    const cancelBtn = page.getByRole("button", { name: /Cancel/i });
    await expect(cancelBtn).toBeVisible();
    await cancelBtn.click();

    expect(cancelCalled).toBe(true);
    await expect(page.getByText("Review the query before running")).not.toBeVisible();
  });

  test("refuses write requests with read-only banner and no Run button", async ({ page }) => {
    await page.route("**/api/chat", async (route) => {
      const sseData = [
        "event: refused",
        JSON.stringify({
          conversation_id: "conv-e2e-4",
          turn_id: "turn-e2e-4",
          message: "Not performed: this assistant is read-only and cannot delete, change or add data.",
        }),
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
        body: sseData,
      });
    });

    await page.goto("/");

    const inputArea = page.getByRole("textbox", { name: "Ask a question" });
    await inputArea.fill("DROP TABLE users");
    await inputArea.press("Enter");

    // "Not performed (read-only)" banner should be visible
    await expect(page.getByText("Not performed (read-only)")).toBeVisible();
    await expect(
      page.getByText("Not performed: this assistant is read-only and cannot delete, change or add data.")
    ).toBeVisible();

    // No Run button should exist
    await expect(page.getByRole("button", { name: /Run query/i })).not.toBeVisible();
  });
});
