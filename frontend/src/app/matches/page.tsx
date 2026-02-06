"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import MatchCard from "@/components/MatchCard";
import EmptyState from "@/components/EmptyState";
import { getMatches, getKeywords, getSubreddits, type Match, type Keyword, type Subreddit } from "@/lib/api";

export default function MatchesPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const perPage = 20;
  const [error, setError] = useState("");

  // Filters
  const [subredditFilter, setSubredditFilter] = useState("");
  const [keywordFilter, setKeywordFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Filter options
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [subreddits, setSubreddits] = useState<Subreddit[]>([]);

  useEffect(() => {
    getKeywords().then(setKeywords).catch(() => {});
    getSubreddits().then(setSubreddits).catch(() => {});
  }, []);

  useEffect(() => {
    loadMatches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, subredditFilter, keywordFilter, startDate, endDate]);

  function loadMatches() {
    getMatches({
      subreddit: subredditFilter || undefined,
      keyword_id: keywordFilter || undefined,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      page,
      per_page: perPage,
    })
      .then((data) => {
        setMatches(data.items);
        setTotal(data.total);
      })
      .catch(() => setError("Failed to load matches."));
  }

  const totalPages = Math.ceil(total / perPage);

  return (
    <AuthGuard>
      <h1 className="text-2xl font-bold">Match History</h1>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      <div className="mt-6 flex flex-wrap gap-3">
        <select
          value={subredditFilter}
          onChange={(e) => { setSubredditFilter(e.target.value); setPage(1); }}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
        >
          <option value="">All subreddits</option>
          {subreddits.map((s) => (
            <option key={s.id} value={s.name}>
              r/{s.name}
            </option>
          ))}
        </select>
        <select
          value={keywordFilter}
          onChange={(e) => { setKeywordFilter(e.target.value); setPage(1); }}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
        >
          <option value="">All keywords</option>
          {keywords.map((k) => (
            <option key={k.id} value={k.id}>
              {k.phrases.join(", ")}
            </option>
          ))}
        </select>
        <input
          type="date"
          value={startDate}
          onChange={(e) => { setStartDate(e.target.value); setPage(1); }}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
          placeholder="Start date"
        />
        <input
          type="date"
          value={endDate}
          onChange={(e) => { setEndDate(e.target.value); setPage(1); }}
          className="rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-white"
          placeholder="End date"
        />
      </div>

      <div className="mt-6">
        {matches.length === 0 ? (
          <EmptyState
            title="No matches found"
            description="Adjust your filters or wait for new matches to arrive."
          />
        ) : (
          <>
            <p className="mb-4 text-sm text-neutral-400">
              Showing {(page - 1) * perPage + 1}-{Math.min(page * perPage, total)} of {total} matches
            </p>
            <div className="space-y-3">
              {matches.map((m) => (
                <MatchCard key={m.id} match={m} />
              ))}
            </div>
            {totalPages > 1 && (
              <div className="mt-6 flex items-center justify-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded bg-neutral-800 px-3 py-1.5 text-sm text-white disabled:opacity-50 hover:bg-neutral-700"
                >
                  Previous
                </button>
                <span className="text-sm text-neutral-400">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded bg-neutral-800 px-3 py-1.5 text-sm text-white disabled:opacity-50 hover:bg-neutral-700"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </AuthGuard>
  );
}
