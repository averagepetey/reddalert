"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import AuthGuard from "@/components/AuthGuard";
import StatusBadge from "@/components/StatusBadge";
import EmptyState from "@/components/EmptyState";
import {
  getSubreddits,
  addSubreddit,
  updateSubreddit,
  deleteSubreddit,
  searchSubreddits,
  type Subreddit,
  type SubredditSuggestion,
} from "@/lib/api";

export default function SubredditsPage() {
  const [subs, setSubs] = useState<Subreddit[]>([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [includeMedia, setIncludeMedia] = useState(true);
  const [dedupeCross, setDedupeCross] = useState(true);
  const [filterBots, setFilterBots] = useState(false);
  const [formLoading, setFormLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<SubredditSuggestion[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchSuggestions = useCallback((query: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const results = await searchSubreddits(query);
        setSuggestions(results);
        setShowSuggestions(results.length > 0);
      } catch {
        setSuggestions([]);
      }
    }, 300);
  }, []);

  useEffect(() => {
    loadSubs();
  }, []);

  function loadSubs() {
    getSubreddits()
      .then(setSubs)
      .catch(() => setError("Failed to load subreddits."));
  }

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    const clean = name.trim().replace(/^r\//, "");
    if (!clean) return;
    setFormLoading(true);
    setError("");
    try {
      await addSubreddit({
        name: clean,
        include_media_posts: includeMedia,
        dedupe_crossposts: dedupeCross,
        filter_bots: filterBots,
      });
      setName("");
      setShowForm(false);
      loadSubs();
    } catch {
      setError("Failed to add subreddit.");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleToggleSetting(
    sub: Subreddit,
    field: "include_media_posts" | "dedupe_crossposts" | "filter_bots"
  ) {
    try {
      await updateSubreddit(sub.id, { [field]: !sub[field] });
      loadSubs();
    } catch {
      setError("Failed to update subreddit.");
    }
  }

  async function handleRemove(id: string) {
    try {
      await deleteSubreddit(id);
      loadSubs();
    } catch {
      setError("Failed to remove subreddit.");
    }
  }

  return (
    <AuthGuard>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Subreddits</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          {showForm ? "Cancel" : "Add Subreddit"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {showForm && (
        <form
          onSubmit={handleAdd}
          className="mt-6 space-y-4 rounded-lg border border-neutral-800 bg-neutral-900 p-6"
        >
          <div>
            <label className="block text-sm text-neutral-300 mb-1">Subreddit name</label>
            <div className="relative">
              <input
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  fetchSuggestions(e.target.value.replace(/^r\//, ""));
                }}
                onBlur={() => {
                  setTimeout(() => setShowSuggestions(false), 200);
                }}
                onFocus={() => {
                  if (suggestions.length > 0) setShowSuggestions(true);
                }}
                placeholder="e.g. sportsbook"
                className="block w-full rounded-lg border border-neutral-700 bg-neutral-950 px-4 py-2.5 text-white placeholder:text-neutral-500 focus:border-blue-500 focus:outline-none"
              />
              {showSuggestions && suggestions.length > 0 && (
                <div className="absolute z-10 mt-1 w-full rounded-lg border border-neutral-700 bg-neutral-900 shadow-lg max-h-60 overflow-y-auto">
                  {suggestions.map((s) => (
                    <button
                      key={s.name}
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        setName(s.name);
                        setSuggestions([]);
                        setShowSuggestions(false);
                      }}
                      className="w-full px-4 py-2 text-left hover:bg-neutral-800 flex items-center justify-between"
                    >
                      <span className="text-sm text-white">r/{s.name}</span>
                      <span className="text-xs text-neutral-500">
                        {s.subscribers >= 1_000_000
                          ? `${(s.subscribers / 1_000_000).toFixed(1)}M`
                          : s.subscribers >= 1_000
                          ? `${(s.subscribers / 1_000).toFixed(0)}K`
                          : s.subscribers}{" "}
                        members
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={includeMedia}
                onChange={(e) => setIncludeMedia(e.target.checked)}
                className="rounded border-neutral-600"
              />
              Include media posts
            </label>
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={dedupeCross}
                onChange={(e) => setDedupeCross(e.target.checked)}
                className="rounded border-neutral-600"
              />
              Dedupe crossposts
            </label>
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={filterBots}
                onChange={(e) => setFilterBots(e.target.checked)}
                className="rounded border-neutral-600"
              />
              Filter bots
            </label>
          </div>
          <button
            type="submit"
            disabled={formLoading || !name.trim()}
            className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {formLoading ? "Adding..." : "Add Subreddit"}
          </button>
        </form>
      )}

      <div className="mt-6">
        {subs.length === 0 ? (
          <EmptyState
            title="No subreddits"
            description="Add subreddits to start monitoring."
            action={
              <button
                onClick={() => setShowForm(true)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                Add Subreddit
              </button>
            }
          />
        ) : (
          <div className="space-y-3">
            {subs.map((sub) => (
              <div
                key={sub.id}
                className="rounded-lg border border-neutral-800 bg-neutral-900 p-4"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-white">r/{sub.name}</span>
                    <StatusBadge status={sub.status} />
                  </div>
                  <button
                    onClick={() => handleRemove(sub.id)}
                    className="rounded px-3 py-1 text-xs text-red-400 hover:bg-red-900/30"
                  >
                    Remove
                  </button>
                </div>
                <div className="mt-3 flex flex-wrap gap-4 text-xs">
                  <button
                    onClick={() => handleToggleSetting(sub, "include_media_posts")}
                    className={`rounded px-2 py-1 ${
                      sub.include_media_posts
                        ? "bg-blue-900/50 text-blue-300"
                        : "bg-neutral-800 text-neutral-500"
                    }`}
                  >
                    Media: {sub.include_media_posts ? "on" : "off"}
                  </button>
                  <button
                    onClick={() => handleToggleSetting(sub, "dedupe_crossposts")}
                    className={`rounded px-2 py-1 ${
                      sub.dedupe_crossposts
                        ? "bg-blue-900/50 text-blue-300"
                        : "bg-neutral-800 text-neutral-500"
                    }`}
                  >
                    Dedupe: {sub.dedupe_crossposts ? "on" : "off"}
                  </button>
                  <button
                    onClick={() => handleToggleSetting(sub, "filter_bots")}
                    className={`rounded px-2 py-1 ${
                      sub.filter_bots
                        ? "bg-blue-900/50 text-blue-300"
                        : "bg-neutral-800 text-neutral-500"
                    }`}
                  >
                    Bot filter: {sub.filter_bots ? "on" : "off"}
                  </button>
                </div>
                {sub.last_polled_at && (
                  <p className="mt-2 text-xs text-neutral-600">
                    Last polled: {new Date(sub.last_polled_at).toLocaleString()}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
