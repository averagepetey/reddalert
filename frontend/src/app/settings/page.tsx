"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import { getSettings, updateSettings, type ClientSettings } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<ClientSettings | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // Edit state
  const [pollingInterval, setPollingInterval] = useState(60);
  const [email, setEmail] = useState("");

  useEffect(() => {
    getSettings()
      .then((s) => {
        setSettings(s);
        setPollingInterval(s.polling_interval);
        setEmail(s.email);
      })
      .catch(() => setError("Failed to load settings."));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateSettings({
        polling_interval: pollingInterval,
        email,
      });
      setSettings(updated);
      setSuccess("Settings saved.");
    } catch {
      setError("Failed to save settings.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthGuard>
      <h1 className="text-2xl font-bold">Settings</h1>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
      {success && <p className="mt-4 text-sm text-green-400">{success}</p>}

      {settings && (
        <form onSubmit={handleSave} className="mt-6 max-w-lg space-y-6">
          <div>
            <label className="block text-sm font-medium text-neutral-300">
              Polling Interval (minutes)
            </label>
            <input
              type="number"
              min={5}
              max={1440}
              value={pollingInterval}
              onChange={(e) => setPollingInterval(Number(e.target.value))}
              className="mt-1 block w-full rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-white focus:border-blue-500 focus:outline-none"
            />
            <p className="mt-1 text-xs text-neutral-500">
              How often to check subreddits for new content (5-1440 minutes).
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-300">
              Backup Email
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="mt-1 block w-full rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
            />
            <p className="mt-1 text-xs text-neutral-500">
              Used for fallback alerts when webhooks fail.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-neutral-300">
              API Key
            </label>
            <div className="mt-1 rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-neutral-500">
              {settings.api_key_masked}
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Saving..." : "Save Settings"}
          </button>
        </form>
      )}
    </AuthGuard>
  );
}
