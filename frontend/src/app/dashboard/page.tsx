"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import StatCard from "@/components/StatCard";
import MatchCard from "@/components/MatchCard";
import EmptyState from "@/components/EmptyState";
import { getStats, getMatches, type DashboardStats, type Match } from "@/lib/api";

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentMatches, setRecentMatches] = useState<Match[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => setError("Failed to load dashboard data."));
    getMatches({ per_page: 10, page: 1 })
      .then((data) => setRecentMatches(data.items))
      .catch(() => {});
  }, []);

  return (
    <AuthGuard>
      <h1 className="text-2xl font-bold">Dashboard</h1>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {stats && (
        <>
          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <StatCard label="Total Matches" value={stats.total_matches} />
            <StatCard label="Matches (24h)" value={stats.matches_last_24h} />
            <StatCard label="Matches (7d)" value={stats.matches_last_7d} />
          </div>

          {stats.top_keywords.length > 0 && (
            <div className="mt-8">
              <h2 className="text-lg font-semibold">Top Keywords</h2>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {stats.top_keywords.map((k) => (
                  <div
                    key={k.keyword_id}
                    className="rounded-lg border border-neutral-800 bg-neutral-900 p-3"
                  >
                    <p className="text-sm text-white">{k.phrases.join(", ")}</p>
                    <p className="mt-1 text-xs text-neutral-500">{k.match_count} matches</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {stats.top_subreddits.length > 0 && (
            <div className="mt-6">
              <h2 className="text-lg font-semibold">Top Subreddits</h2>
              <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {stats.top_subreddits.map((s) => (
                  <div
                    key={s.subreddit}
                    className="rounded-lg border border-neutral-800 bg-neutral-900 p-3"
                  >
                    <p className="text-sm text-blue-400">r/{s.subreddit}</p>
                    <p className="mt-1 text-xs text-neutral-500">{s.match_count} matches</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="mt-8 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Recent Matches</h2>
            <Link href="/matches" className="text-sm text-blue-400 hover:underline">
              View all
            </Link>
          </div>

          {recentMatches.length === 0 ? (
            <div className="mt-4">
              <EmptyState
                title="No matches yet"
                description="Matches will appear here once your keywords are detected in monitored subreddits."
                action={
                  <Link
                    href="/onboarding"
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
                  >
                    Set up monitoring
                  </Link>
                }
              />
            </div>
          ) : (
            <div className="mt-4 space-y-3">
              {recentMatches.map((m) => (
                <MatchCard key={m.id} match={m} />
              ))}
            </div>
          )}

          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <Link
              href="/keywords"
              className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-center text-sm text-neutral-300 hover:border-neutral-600 transition-colors"
            >
              Manage Keywords
            </Link>
            <Link
              href="/subreddits"
              className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-center text-sm text-neutral-300 hover:border-neutral-600 transition-colors"
            >
              Manage Subreddits
            </Link>
            <Link
              href="/webhooks"
              className="rounded-lg border border-neutral-800 bg-neutral-900 p-4 text-center text-sm text-neutral-300 hover:border-neutral-600 transition-colors"
            >
              Manage Webhooks
            </Link>
          </div>
        </>
      )}
    </AuthGuard>
  );
}
