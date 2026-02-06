"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setApiKey } from "@/lib/auth";
import { validateApiKey } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim()) return;
    setLoading(true);
    setError("");
    try {
      await validateApiKey(key.trim());
      setApiKey(key.trim());
      router.push("/dashboard");
    } catch {
      setError("Invalid API key. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-6">
      <div className="w-full max-w-md">
        <h1 className="text-4xl font-bold text-white text-center">Reddalert</h1>
        <p className="mt-2 text-center text-neutral-400">
          Reddit monitoring and alerting for Discord
        </p>

        <form onSubmit={handleConnect} className="mt-8 space-y-4">
          <div>
            <label htmlFor="apiKey" className="block text-sm font-medium text-neutral-300">
              API Key
            </label>
            <input
              id="apiKey"
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Enter your API key"
              className="mt-1 block w-full rounded-lg border border-neutral-700 bg-neutral-900 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
            />
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={loading || !key.trim()}
            className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Connecting..." : "Connect"}
          </button>
        </form>
      </div>
    </main>
  );
}
