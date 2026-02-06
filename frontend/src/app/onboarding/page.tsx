"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import AuthGuard from "@/components/AuthGuard";
import StepIndicator from "@/components/StepIndicator";
import ChipInput from "@/components/ChipInput";
import {
  addWebhook,
  testWebhook,
  deleteWebhook,
  addSubreddit,
  createKeyword,
  getDiscordAuthUrl,
  getWebhooks,
} from "@/lib/api";

const STEPS = ["Webhook", "Subreddits", "Keywords", "Confirm"];

function OnboardingContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [step, setStep] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Step 1: Webhook
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookTested, setWebhookTested] = useState(false);
  const [webhookId, setWebhookId] = useState<string | null>(null);

  // Discord OAuth state
  const [discordConnected, setDiscordConnected] = useState(false);
  const [discordAvailable, setDiscordAvailable] = useState(true);

  // Step 2: Subreddits
  const [subredditName, setSubredditName] = useState("");
  const [subreddits, setSubreddits] = useState<string[]>([]);

  // Step 3: Keywords
  const [phrases, setPhrases] = useState<string[]>([]);
  const [exclusions, setExclusions] = useState<string[]>([]);

  // Check if returning from Discord OAuth
  useEffect(() => {
    if (searchParams.get("discord") === "success") {
      getWebhooks()
        .then((webhooks) => {
          const primary = webhooks.find((w) => w.is_primary) || webhooks[0];
          if (primary) {
            setWebhookUrl(primary.url);
            setWebhookId(primary.id);
            setWebhookTested(true);
            setDiscordConnected(true);
          }
        })
        .catch(() => {
          // Silently fail - user can still use manual flow
        });
    }
  }, [searchParams]);

  async function handleConnectDiscord() {
    setLoading(true);
    setError("");
    try {
      const { auth_url, state } = await getDiscordAuthUrl();
      localStorage.setItem("discord_oauth_state", state);
      window.location.href = auth_url;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "";
      if (message.includes("503") || message.includes("not configured")) {
        setDiscordAvailable(false);
      } else {
        setError("Failed to start Discord connection. Try pasting manually.");
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleTestWebhook() {
    setLoading(true);
    setError("");
    try {
      // Delete previously created webhook to avoid duplicates
      if (webhookId) {
        await deleteWebhook(webhookId).catch(() => {});
        setWebhookId(null);
      }
      const wh = await addWebhook({ url: webhookUrl, is_primary: true });
      setWebhookId(wh.id);
      await testWebhook(wh.id);
      setWebhookTested(true);
    } catch {
      setError("Failed to add or test webhook. Check the URL.");
    } finally {
      setLoading(false);
    }
  }

  function handleAddSubreddit() {
    const name = subredditName.trim().replace(/^r\//, "");
    if (name && !subreddits.includes(name)) {
      setSubreddits([...subreddits, name]);
    }
    setSubredditName("");
  }

  async function handleFinish() {
    setLoading(true);
    setError("");
    try {
      // Add subreddits
      for (const name of subreddits) {
        await addSubreddit({ name });
      }
      // Add keyword
      if (phrases.length > 0) {
        await createKeyword({
          phrases,
          exclusions: exclusions.length > 0 ? exclusions : undefined,
        });
      }
      router.push("/dashboard");
    } catch {
      setError("Setup failed. Some items may have been partially saved.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthGuard>
      <div className="mx-auto max-w-2xl">
        <h1 className="text-2xl font-bold">Setup Wizard</h1>
        <div className="mt-6">
          <StepIndicator steps={STEPS} current={step} />
        </div>

        {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

        <div className="mt-8">
          {/* Step 1: Webhook */}
          {step === 0 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Add Discord Webhook</h2>
              <p className="text-sm text-neutral-400">
                Connect your Discord server or paste a webhook URL manually.
              </p>

              {discordConnected ? (
                <div className="rounded-lg border border-green-700 bg-green-900/30 px-4 py-3">
                  <p className="text-sm font-medium text-green-400">
                    Discord webhook connected!
                  </p>
                  <p className="mt-1 text-xs text-neutral-400 truncate">
                    {webhookUrl}
                  </p>
                </div>
              ) : (
                <>
                  {discordAvailable && (
                    <>
                      <button
                        onClick={handleConnectDiscord}
                        disabled={loading}
                        className="w-full rounded-lg px-4 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                        style={{ backgroundColor: "#5865F2" }}
                      >
                        {loading ? "Connecting..." : "Connect to Discord"}
                      </button>

                      <div className="flex items-center gap-3">
                        <div className="flex-1 border-t border-neutral-700" />
                        <span className="text-xs text-neutral-500">or paste manually</span>
                        <div className="flex-1 border-t border-neutral-700" />
                      </div>
                    </>
                  )}

                  <input
                    type="url"
                    value={webhookUrl}
                    onChange={(e) => {
                      setWebhookUrl(e.target.value);
                      setWebhookTested(false);
                    }}
                    placeholder="https://discord.com/api/webhooks/..."
                    className="block w-full rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
                  />
                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleTestWebhook}
                      disabled={loading || !webhookUrl.trim()}
                      className="rounded-lg bg-neutral-800 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50"
                    >
                      {loading ? "Testing..." : "Test Webhook"}
                    </button>
                    {webhookTested && (
                      <span className="text-sm text-green-400">Webhook verified!</span>
                    )}
                  </div>
                </>
              )}

              <div className="pt-4">
                <button
                  onClick={() => setStep(1)}
                  disabled={!webhookTested}
                  className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Subreddits */}
          {step === 1 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Add Subreddits</h2>
              <p className="text-sm text-neutral-400">
                Enter subreddit names to monitor (without r/ prefix).
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={subredditName}
                  onChange={(e) => setSubredditName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), handleAddSubreddit())}
                  placeholder="e.g. sportsbook"
                  className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
                />
                <button
                  onClick={handleAddSubreddit}
                  className="rounded-lg bg-neutral-800 px-4 py-2 text-sm text-white hover:bg-neutral-700"
                >
                  Add
                </button>
              </div>
              {subreddits.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {subreddits.map((s, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1 rounded bg-neutral-800 px-3 py-1 text-sm text-white"
                    >
                      r/{s}
                      <button
                        onClick={() => setSubreddits(subreddits.filter((_, j) => j !== i))}
                        className="text-neutral-400 hover:text-red-400"
                      >
                        x
                      </button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => setStep(0)}
                  className="rounded-lg bg-neutral-800 px-6 py-2 text-sm text-white hover:bg-neutral-700"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(2)}
                  disabled={subreddits.length === 0}
                  className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {/* Step 3: Keywords */}
          {step === 2 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Add Keywords</h2>
              <p className="text-sm text-neutral-400">
                Type a phrase and press Enter to add. These phrases form an OR group.
              </p>
              <div>
                <label className="block text-sm text-neutral-300 mb-1">Phrases</label>
                <ChipInput
                  values={phrases}
                  onChange={setPhrases}
                  placeholder="Type a phrase and press Enter"
                />
              </div>
              <div>
                <label className="block text-sm text-neutral-300 mb-1">Exclusions (optional)</label>
                <ChipInput
                  values={exclusions}
                  onChange={setExclusions}
                  placeholder="Words to exclude"
                />
              </div>
              {phrases.some((p) => !p.includes(" ")) && (
                <p className="text-sm text-yellow-400">
                  Warning: Single-word phrases may generate many matches.
                </p>
              )}
              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => setStep(1)}
                  className="rounded-lg bg-neutral-800 px-6 py-2 text-sm text-white hover:bg-neutral-700"
                >
                  Back
                </button>
                <button
                  onClick={() => setStep(3)}
                  disabled={phrases.length === 0}
                  className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}

          {/* Step 4: Confirm */}
          {step === 3 && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Confirm Setup</h2>
              <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 space-y-3">
                <div>
                  <p className="text-xs text-neutral-500">Webhook</p>
                  <p className="text-sm text-white truncate">{webhookUrl}</p>
                </div>
                <div>
                  <p className="text-xs text-neutral-500">Subreddits</p>
                  <p className="text-sm text-white">{subreddits.map((s) => `r/${s}`).join(", ")}</p>
                </div>
                <div>
                  <p className="text-xs text-neutral-500">Keywords</p>
                  <p className="text-sm text-white">{phrases.join(", ")}</p>
                  {exclusions.length > 0 && (
                    <p className="text-xs text-neutral-400 mt-1">
                      Excluding: {exclusions.join(", ")}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => setStep(2)}
                  className="rounded-lg bg-neutral-800 px-6 py-2 text-sm text-white hover:bg-neutral-700"
                >
                  Back
                </button>
                <button
                  onClick={handleFinish}
                  disabled={loading}
                  className="rounded-lg bg-green-600 px-6 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
                >
                  {loading ? "Setting up..." : "Start Monitoring"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </AuthGuard>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-2xl mt-10 text-center text-neutral-400">Loading...</div>}>
      <OnboardingContent />
    </Suspense>
  );
}
