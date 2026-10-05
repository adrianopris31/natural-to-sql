"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  KeyRound,
  RefreshCw,
  X,
  Layers,
  MessageSquare,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  deleteSource,
  fetchSources,
  refreshDocuments,
  saveJiraSource,
  saveSlackSource,
  testSource,
} from "@/lib/api";
import {
  JiraSourceForm,
  SlackSourceForm,
  SourceItem,
  SourceOrigin,
  SourceTestResult,
} from "@/lib/types";

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

function OriginBadge({ origin }: { origin: SourceOrigin }) {
  if (origin === "stored") {
    return (
      <span className="inline-flex items-center rounded-md border border-emerald-500/30 bg-emerald-500/15 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
        Stored
      </span>
    );
  }
  if (origin === "env") {
    return (
      <span className="inline-flex items-center rounded-md border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-300">
        From .env
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md border border-border bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
      Not set
    </span>
  );
}

interface JiraCardProps {
  sourceItem: SourceItem;
  onSaved: () => void;
  onTriggerRefresh: () => void;
  isRefreshing: boolean;
}

function JiraCard({
  sourceItem,
  onSaved,
  onTriggerRefresh,
  isRefreshing,
}: JiraCardProps) {
  const [baseUrl, setBaseUrl] = useState(
    (sourceItem.fields.base_url as string) || ""
  );
  const [browseUrl, setBrowseUrl] = useState(
    (sourceItem.fields.browse_url as string) || ""
  );
  const [authMode, setAuthMode] = useState<"token" | "bearer">(
    (sourceItem.fields.auth_mode as "token" | "bearer") || "token"
  );
  const [email, setEmail] = useState((sourceItem.fields.email as string) || "");
  const [projectKey, setProjectKey] = useState(
    (sourceItem.fields.project_key as string) || ""
  );
  const [jql, setJql] = useState((sourceItem.fields.jql as string) || "");
  const [maxIssues, setMaxIssues] = useState(
    sourceItem.fields.max_issues !== undefined &&
      sourceItem.fields.max_issues !== null
      ? String(sourceItem.fields.max_issues)
      : ""
  );
  const [apiToken, setApiToken] = useState("");
  const [isReplacing, setIsReplacing] = useState(!sourceItem.configured);

  const [testResult, setTestResult] = useState<SourceTestResult | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setBaseUrl((sourceItem.fields.base_url as string) || "");
    setBrowseUrl((sourceItem.fields.browse_url as string) || "");
    setAuthMode(
      (sourceItem.fields.auth_mode as "token" | "bearer") || "token"
    );
    setEmail((sourceItem.fields.email as string) || "");
    setProjectKey((sourceItem.fields.project_key as string) || "");
    setJql((sourceItem.fields.jql as string) || "");
    setMaxIssues(
      sourceItem.fields.max_issues !== undefined &&
        sourceItem.fields.max_issues !== null
        ? String(sourceItem.fields.max_issues)
        : ""
    );
    setApiToken("");
    setIsReplacing(!sourceItem.configured);
  }, [sourceItem]);

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const payload: JiraSourceForm = {
        base_url: baseUrl.trim(),
        browse_url: browseUrl.trim() || undefined,
        auth_mode: authMode,
        email: email.trim() || undefined,
        project_key: projectKey.trim() || undefined,
        jql: jql.trim() || undefined,
        max_issues: maxIssues ? Number(maxIssues) : undefined,
      };
      if (isReplacing && apiToken.trim()) {
        payload.api_token = apiToken.trim();
      }
      const res = await testSource("jira", payload);
      setTestResult(res);
    } catch (err) {
      setTestResult({
        ok: false,
        message: err instanceof Error ? err.message : "Test request failed",
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isSaving) return;
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const payload: JiraSourceForm = {
        base_url: baseUrl.trim(),
        browse_url: browseUrl.trim() || undefined,
        auth_mode: authMode,
        email: email.trim() || undefined,
        project_key: projectKey.trim() || undefined,
        jql: jql.trim() || undefined,
        max_issues: maxIssues ? Number(maxIssues) : undefined,
      };
      if (isReplacing && apiToken.trim()) {
        payload.api_token = apiToken.trim();
      }
      await saveJiraSource(payload);
      setSaveSuccess(true);
      setApiToken("");
      setIsReplacing(false);
      onSaved();
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save Jira settings"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDeleting(true);
    try {
      await deleteSource("jira");
      setSaveSuccess(false);
      onSaved();
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to disconnect Jira"
      );
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-400">
            <Layers className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Jira</h3>
              <OriginBadge origin={sourceItem.origin} />
            </div>
            <p className="text-xs text-muted-foreground">
              Search and index tickets, bugs, and project documents.
            </p>
          </div>
        </div>

        <div className="text-right text-[11px] text-muted-foreground">
          <div>
            <span className="font-medium text-foreground">Last refresh: </span>
            <span>
              {sourceItem.last_refresh
                ? new Date(sourceItem.last_refresh).toLocaleString()
                : "Never"}
            </span>
          </div>
          {sourceItem.last_status && (
            <div className="truncate max-w-[240px]">
              <span className="font-medium text-foreground">Status: </span>
              <span title={sourceItem.last_status}>
                {sourceItem.last_status}
              </span>
            </div>
          )}
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-3.5">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label
              htmlFor="jira_base_url"
              className="text-xs font-medium text-foreground"
            >
              Base URL *
            </label>
            <input
              id="jira_base_url"
              name="jira_base_url"
              type="text"
              required
              placeholder="https://company.atlassian.net"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="jira_browse_url"
              className="text-xs font-medium text-foreground"
            >
              Browse URL (optional)
            </label>
            <input
              id="jira_browse_url"
              name="jira_browse_url"
              type="text"
              placeholder="https://company.atlassian.net/browse"
              value={browseUrl}
              onChange={(e) => setBrowseUrl(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label
              htmlFor="jira_auth_mode"
              className="text-xs font-medium text-foreground"
            >
              Authentication Mode
            </label>
            <select
              id="jira_auth_mode"
              name="jira_auth_mode"
              value={authMode}
              onChange={(e) =>
                setAuthMode(e.target.value as "token" | "bearer")
              }
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="token">API Token (Atlassian Cloud)</option>
              <option value="bearer">Bearer / PAT (Data Center / Server)</option>
            </select>
          </div>

          <div className="space-y-1">
            <label
              htmlFor="jira_email"
              className="text-xs font-medium text-foreground"
            >
              Email {authMode === "token" && "*"}
            </label>
            <input
              id="jira_email"
              name="jira_email"
              type="email"
              placeholder="user@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        </div>

        {/* Secret Field: Write-only */}
        <div className="space-y-1">
          <label
            htmlFor={isReplacing ? "jira_api_token" : "jira_api_token_masked"}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground"
          >
            <KeyRound className="size-3 text-muted-foreground" />
            <span>API Token / Secret</span>
          </label>
          {sourceItem.configured && !isReplacing ? (
            <div className="flex gap-2">
              <input
                id="jira_api_token_masked"
                type="text"
                readOnly
                disabled
                value={
                  sourceItem.secret_hint
                    ? `•••••••••••• (${sourceItem.secret_hint})`
                    : "••••••••••••"
                }
                className="h-8 flex-1 rounded-md border border-input bg-muted px-2.5 font-mono text-xs text-muted-foreground select-none"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setIsReplacing(true);
                  setApiToken("");
                }}
              >
                Replace secret
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                id="jira_api_token"
                name="jira_api_token"
                type="password"
                placeholder={
                  sourceItem.configured
                    ? "Enter new API token"
                    : "Enter API token"
                }
                value={apiToken}
                onChange={(e) => setApiToken(e.target.value)}
                className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              {sourceItem.configured && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setIsReplacing(false);
                    setApiToken("");
                  }}
                >
                  Keep existing
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="space-y-1">
            <label
              htmlFor="jira_project_key"
              className="text-xs font-medium text-foreground"
            >
              Project Key
            </label>
            <input
              id="jira_project_key"
              name="jira_project_key"
              type="text"
              placeholder="PROJ"
              value={projectKey}
              onChange={(e) => setProjectKey(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="jira_jql"
              className="text-xs font-medium text-foreground"
            >
              JQL Filter
            </label>
            <input
              id="jira_jql"
              name="jira_jql"
              type="text"
              placeholder="ORDER BY updated DESC"
              value={jql}
              onChange={(e) => setJql(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="jira_max_issues"
              className="text-xs font-medium text-foreground"
            >
              Max Issues
            </label>
            <input
              id="jira_max_issues"
              name="jira_max_issues"
              type="number"
              min="1"
              placeholder="500"
              value={maxIssues}
              onChange={(e) => setMaxIssues(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        </div>

        {/* Test Result Message */}
        {testResult && (
          <div
            className={cn(
              "flex items-center gap-2 rounded-md p-2 text-xs",
              testResult.ok
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20"
                : "bg-destructive/10 text-destructive border border-destructive/20"
            )}
          >
            {testResult.ok ? (
              <CheckCircle2 className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertCircle className="size-4 shrink-0" />
            )}
            <span>{testResult.message}</span>
          </div>
        )}

        {/* Save error message */}
        {saveError && (
          <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-2 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{saveError}</span>
          </div>
        )}

        {/* Save success message with inline Refresh now */}
        {saveSuccess && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 className="size-4 shrink-0" />
              <span>Jira settings saved successfully.</span>
            </div>
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={onTriggerRefresh}
              disabled={isRefreshing}
              className="gap-1 border-emerald-500/40 text-emerald-800 hover:bg-emerald-500/20 dark:text-emerald-200"
            >
              <RefreshCw
                className={cn("size-3", isRefreshing && "animate-spin")}
              />
              <span>Refresh now</span>
            </Button>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleTest}
              disabled={isTesting || !baseUrl.trim()}
            >
              {isTesting ? (
                <>
                  <RefreshCw className="size-3.5 animate-spin" />
                  <span>Testing…</span>
                </>
              ) : (
                <span>Test connection</span>
              )}
            </Button>

            {sourceItem.configured && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleDisconnect}
                disabled={isDeleting}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                {isDeleting ? "Disconnecting…" : "Disconnect"}
              </Button>
            )}
          </div>

          <Button
            type="submit"
            size="sm"
            disabled={isSaving || !baseUrl.trim()}
          >
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </div>
  );
}

interface SlackCardProps {
  sourceItem: SourceItem;
  onSaved: () => void;
  onTriggerRefresh: () => void;
  isRefreshing: boolean;
}

function SlackCard({
  sourceItem,
  onSaved,
  onTriggerRefresh,
  isRefreshing,
}: SlackCardProps) {
  const [channels, setChannels] = useState(
    Array.isArray(sourceItem.fields.channels)
      ? (sourceItem.fields.channels as string[]).join(", ")
      : (sourceItem.fields.channels as string) || ""
  );
  const [daysBack, setDaysBack] = useState(
    sourceItem.fields.days_back !== undefined &&
      sourceItem.fields.days_back !== null
      ? String(sourceItem.fields.days_back)
      : ""
  );
  const [maxThreads, setMaxThreads] = useState(
    sourceItem.fields.max_threads !== undefined &&
      sourceItem.fields.max_threads !== null
      ? String(sourceItem.fields.max_threads)
      : ""
  );
  const [botToken, setBotToken] = useState("");
  const [isReplacing, setIsReplacing] = useState(!sourceItem.configured);

  const [testResult, setTestResult] = useState<SourceTestResult | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    setChannels(
      Array.isArray(sourceItem.fields.channels)
        ? (sourceItem.fields.channels as string[]).join(", ")
        : (sourceItem.fields.channels as string) || ""
    );
    setDaysBack(
      sourceItem.fields.days_back !== undefined &&
        sourceItem.fields.days_back !== null
        ? String(sourceItem.fields.days_back)
        : ""
    );
    setMaxThreads(
      sourceItem.fields.max_threads !== undefined &&
        sourceItem.fields.max_threads !== null
        ? String(sourceItem.fields.max_threads)
        : ""
    );
    setBotToken("");
    setIsReplacing(!sourceItem.configured);
  }, [sourceItem]);

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const channelList = channels
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean);
      const payload: SlackSourceForm = {
        channels: channelList,
        days_back: daysBack ? Number(daysBack) : undefined,
        max_threads: maxThreads ? Number(maxThreads) : undefined,
      };
      if (isReplacing && botToken.trim()) {
        payload.bot_token = botToken.trim();
      }
      const res = await testSource("slack", payload);
      setTestResult(res);
    } catch (err) {
      setTestResult({
        ok: false,
        message: err instanceof Error ? err.message : "Test request failed",
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSave = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isSaving) return;
    setIsSaving(true);
    setSaveSuccess(false);
    setSaveError(null);
    try {
      const channelList = channels
        .split(",")
        .map((c) => c.trim())
        .filter(Boolean);
      const payload: SlackSourceForm = {
        channels: channelList,
        days_back: daysBack ? Number(daysBack) : undefined,
        max_threads: maxThreads ? Number(maxThreads) : undefined,
      };
      if (isReplacing && botToken.trim()) {
        payload.bot_token = botToken.trim();
      }
      await saveSlackSource(payload);
      setSaveSuccess(true);
      setBotToken("");
      setIsReplacing(false);
      onSaved();
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to save Slack settings"
      );
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisconnect = async () => {
    setIsDeleting(true);
    try {
      await deleteSource("slack");
      setSaveSuccess(false);
      onSaved();
    } catch (err) {
      setSaveError(
        err instanceof Error ? err.message : "Failed to disconnect Slack"
      );
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
            <MessageSquare className="size-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold text-foreground">Slack</h3>
              <OriginBadge origin={sourceItem.origin} />
            </div>
            <p className="text-xs text-muted-foreground">
              Index public and shared channel conversations.
            </p>
          </div>
        </div>

        <div className="text-right text-[11px] text-muted-foreground">
          <div>
            <span className="font-medium text-foreground">Last refresh: </span>
            <span>
              {sourceItem.last_refresh
                ? new Date(sourceItem.last_refresh).toLocaleString()
                : "Never"}
            </span>
          </div>
          {sourceItem.last_status && (
            <div className="truncate max-w-[240px]">
              <span className="font-medium text-foreground">Status: </span>
              <span title={sourceItem.last_status}>
                {sourceItem.last_status}
              </span>
            </div>
          )}
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-3.5">
        <div className="space-y-1">
          <label
            htmlFor="slack_channels"
            className="text-xs font-medium text-foreground"
          >
            Channels (comma-separated) *
          </label>
          <input
            id="slack_channels"
            name="slack_channels"
            type="text"
            required
            placeholder="general, dev, support"
            value={channels}
            onChange={(e) => setChannels(e.target.value)}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>

        {/* Secret Field: Write-only */}
        <div className="space-y-1">
          <label
            htmlFor={isReplacing ? "slack_bot_token" : "slack_bot_token_masked"}
            className="flex items-center gap-1.5 text-xs font-medium text-foreground"
          >
            <KeyRound className="size-3 text-muted-foreground" />
            <span>Bot Token (xoxb-...)</span>
          </label>
          {sourceItem.configured && !isReplacing ? (
            <div className="flex gap-2">
              <input
                id="slack_bot_token_masked"
                type="text"
                readOnly
                disabled
                value={
                  sourceItem.secret_hint
                    ? `•••••••••••• (${sourceItem.secret_hint})`
                    : "••••••••••••"
                }
                className="h-8 flex-1 rounded-md border border-input bg-muted px-2.5 font-mono text-xs text-muted-foreground select-none"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setIsReplacing(true);
                  setBotToken("");
                }}
              >
                Replace secret
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <input
                id="slack_bot_token"
                name="slack_bot_token"
                type="password"
                placeholder={
                  sourceItem.configured
                    ? "Enter new bot token (xoxb-...)"
                    : "Enter bot token (xoxb-...)"
                }
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              {sourceItem.configured && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setIsReplacing(false);
                    setBotToken("");
                  }}
                >
                  Keep existing
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <label
              htmlFor="slack_days_back"
              className="text-xs font-medium text-foreground"
            >
              Days Back
            </label>
            <input
              id="slack_days_back"
              name="slack_days_back"
              type="number"
              min="1"
              placeholder="30"
              value={daysBack}
              onChange={(e) => setDaysBack(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="slack_max_threads"
              className="text-xs font-medium text-foreground"
            >
              Max Threads
            </label>
            <input
              id="slack_max_threads"
              name="slack_max_threads"
              type="number"
              min="1"
              placeholder="100"
              value={maxThreads}
              onChange={(e) => setMaxThreads(e.target.value)}
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
          </div>
        </div>

        {/* Test Result Message */}
        {testResult && (
          <div
            className={cn(
              "flex items-center gap-2 rounded-md p-2 text-xs",
              testResult.ok
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20"
                : "bg-destructive/10 text-destructive border border-destructive/20"
            )}
          >
            {testResult.ok ? (
              <CheckCircle2 className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
            ) : (
              <AlertCircle className="size-4 shrink-0" />
            )}
            <span>{testResult.message}</span>
          </div>
        )}

        {/* Save error message */}
        {saveError && (
          <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/10 p-2 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{saveError}</span>
          </div>
        )}

        {/* Save success message with inline Refresh now */}
        {saveSuccess && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 className="size-4 shrink-0" />
              <span>Slack settings saved successfully.</span>
            </div>
            <Button
              type="button"
              size="xs"
              variant="outline"
              onClick={onTriggerRefresh}
              disabled={isRefreshing}
              className="gap-1 border-emerald-500/40 text-emerald-800 hover:bg-emerald-500/20 dark:text-emerald-200"
            >
              <RefreshCw
                className={cn("size-3", isRefreshing && "animate-spin")}
              />
              <span>Refresh now</span>
            </Button>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleTest}
              disabled={isTesting || !channels.trim()}
            >
              {isTesting ? (
                <>
                  <RefreshCw className="size-3.5 animate-spin" />
                  <span>Testing…</span>
                </>
              ) : (
                <span>Test connection</span>
              )}
            </Button>

            {sourceItem.configured && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={handleDisconnect}
                disabled={isDeleting}
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              >
                {isDeleting ? "Disconnecting…" : "Disconnect"}
              </Button>
            )}
          </div>

          <Button
            type="submit"
            size="sm"
            disabled={isSaving || !channels.trim()}
          >
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </div>
  );
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const queryClient = useQueryClient();
  const [isRefreshingAll, setIsRefreshingAll] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["settings-sources"],
    queryFn: fetchSources,
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const defaultJira: SourceItem = {
    source: "jira",
    configured: false,
    origin: "none",
    fields: {},
    secret_hint: null,
    last_refresh: null,
    last_status: null,
  };

  const defaultSlack: SourceItem = {
    source: "slack",
    configured: false,
    origin: "none",
    fields: {},
    secret_hint: null,
    last_refresh: null,
    last_status: null,
  };

  const jiraItem =
    data?.sources?.find((s) => s.source === "jira") ?? defaultJira;
  const slackItem =
    data?.sources?.find((s) => s.source === "slack") ?? defaultSlack;

  const handleGlobalRefresh = async () => {
    setIsRefreshingAll(true);
    setRefreshMessage(null);
    try {
      const res = await refreshDocuments();
      setRefreshMessage(res.message || "Document refresh started successfully.");
      await refetch();
      await queryClient.invalidateQueries({ queryKey: ["settings-sources"] });
    } catch (err) {
      setRefreshMessage(
        err instanceof Error ? err.message : "Failed to trigger refresh"
      );
    } finally {
      setIsRefreshingAll(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-xs transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Dialog */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Integration Settings"
        className="relative flex max-h-[90vh] w-full max-w-2xl flex-col rounded-xl border border-border bg-background shadow-2xl"
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              Integration Settings
            </h2>
            <p className="text-xs text-muted-foreground">
              Configure Jira and Slack credentials for knowledge base document
              indexing.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleGlobalRefresh}
              disabled={isRefreshingAll}
              className="gap-1.5 text-xs"
              title="Trigger a full re-indexing of all configured sources"
            >
              <RefreshCw
                className={cn("size-3.5", isRefreshingAll && "animate-spin")}
              />
              <span className="hidden sm:inline">Refresh all documents</span>
              <span className="sm:hidden">Refresh</span>
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onClose}
              aria-label="Close settings"
            >
              <X className="size-4" />
            </Button>
          </div>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {refreshMessage && (
            <div className="flex items-center justify-between gap-2 rounded-md border border-border bg-muted/60 px-3 py-2 text-xs">
              <span>{refreshMessage}</span>
              <button
                type="button"
                onClick={() => setRefreshMessage(null)}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </button>
            </div>
          )}

          {isLoading && (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Loading settings…
            </p>
          )}

          {isError && (
            <p className="py-6 text-center text-xs text-destructive">
              Could not load integration settings.
            </p>
          )}

          {!isLoading && !isError && (
            <>
              <JiraCard
                sourceItem={jiraItem}
                onSaved={refetch}
                onTriggerRefresh={handleGlobalRefresh}
                isRefreshing={isRefreshingAll}
              />
              <SlackCard
                sourceItem={slackItem}
                onSaved={refetch}
                onTriggerRefresh={handleGlobalRefresh}
                isRefreshing={isRefreshingAll}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
