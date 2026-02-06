"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import EmptyState from "@/components/EmptyState";
import {
  getWebhooks,
  addWebhook,
  testWebhook,
  setPrimaryWebhook,
  deleteWebhook,
  type Webhook,
} from "@/lib/api";

export default function WebhooksPage() {
  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState("");
  const [formLoading, setFormLoading] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);

  useEffect(() => {
    loadWebhooks();
  }, []);

  function loadWebhooks() {
    getWebhooks()
      .then(setWebhooks)
      .catch(() => setError("Failed to load webhooks."));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setFormLoading(true);
    setError("");
    try {
      await addWebhook({ url: url.trim() });
      setUrl("");
      setShowForm(false);
      loadWebhooks();
    } catch {
      setError("Failed to add webhook.");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleTest(id: string) {
    setTestingId(id);
    setError("");
    try {
      const result = await testWebhook(id);
      if (!result.success) {
        setError("Webhook test failed. Check the URL.");
      }
      loadWebhooks();
    } catch {
      setError("Webhook test failed.");
    } finally {
      setTestingId(null);
    }
  }

  async function handleSetPrimary(id: string) {
    try {
      await setPrimaryWebhook(id);
      loadWebhooks();
    } catch {
      setError("Failed to set primary webhook.");
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteWebhook(id);
      loadWebhooks();
    } catch {
      setError("Failed to delete webhook.");
    }
  }

  return (
    <AuthGuard>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Webhooks</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          {showForm ? "Cancel" : "Add Webhook"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {showForm && (
        <form
          onSubmit={handleAdd}
          className="mt-6 space-y-4 rounded-lg border border-neutral-800 bg-neutral-900 p-6"
        >
          <div>
            <label className="block text-sm text-neutral-300 mb-1">Webhook URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              className="block w-full rounded-lg border border-neutral-700 bg-neutral-950 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={formLoading || !url.trim()}
            className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {formLoading ? "Adding..." : "Add Webhook"}
          </button>
        </form>
      )}

      <div className="mt-6">
        {webhooks.length === 0 ? (
          <EmptyState
            title="No webhooks"
            description="Add a Discord webhook to receive alerts."
            action={
              <button
                onClick={() => setShowForm(true)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                Add Webhook
              </button>
            }
          />
        ) : (
          <div className="space-y-3">
            {webhooks.map((wh) => (
              <div
                key={wh.id}
                className="rounded-lg border border-neutral-800 bg-neutral-900 p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm text-white">{wh.url}</p>
                      {wh.is_primary && (
                        <span className="shrink-0 rounded bg-blue-900 px-2 py-0.5 text-xs text-blue-300">
                          Primary
                        </span>
                      )}
                    </div>
                    {wh.last_tested_at && (
                      <p className="mt-1 text-xs text-neutral-600">
                        Last tested: {new Date(wh.last_tested_at).toLocaleString()}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      onClick={() => handleTest(wh.id)}
                      disabled={testingId === wh.id}
                      className="rounded bg-neutral-800 px-3 py-1 text-xs text-neutral-300 hover:bg-neutral-700 disabled:opacity-50"
                    >
                      {testingId === wh.id ? "Testing..." : "Test"}
                    </button>
                    {!wh.is_primary && (
                      <button
                        onClick={() => handleSetPrimary(wh.id)}
                        className="rounded bg-neutral-800 px-3 py-1 text-xs text-neutral-300 hover:bg-neutral-700"
                      >
                        Set Primary
                      </button>
                    )}
                    <button
                      onClick={() => handleDelete(wh.id)}
                      className="rounded px-3 py-1 text-xs text-red-400 hover:bg-red-900/30"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
