"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import ChipInput from "@/components/ChipInput";
import EmptyState from "@/components/EmptyState";
import {
  getKeywords,
  createKeyword,
  updateKeyword,
  deleteKeyword,
  type Keyword,
} from "@/lib/api";

export default function KeywordsPage() {
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [phrases, setPhrases] = useState<string[]>([]);
  const [exclusions, setExclusions] = useState<string[]>([]);
  const [proximityWindow, setProximityWindow] = useState(15);
  const [requireOrder, setRequireOrder] = useState(false);
  const [useStemming, setUseStemming] = useState(false);
  const [formLoading, setFormLoading] = useState(false);

  useEffect(() => {
    loadKeywords();
  }, []);

  function loadKeywords() {
    getKeywords()
      .then(setKeywords)
      .catch(() => setError("Failed to load keywords."));
  }

  function resetForm() {
    setPhrases([]);
    setExclusions([]);
    setProximityWindow(15);
    setRequireOrder(false);
    setUseStemming(false);
    setShowForm(false);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (phrases.length === 0) return;
    setFormLoading(true);
    setError("");
    try {
      await createKeyword({
        phrases,
        exclusions: exclusions.length > 0 ? exclusions : undefined,
        proximity_window: proximityWindow,
        require_order: requireOrder,
        use_stemming: useStemming,
      });
      resetForm();
      loadKeywords();
    } catch {
      setError("Failed to create keyword.");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleToggle(kw: Keyword) {
    try {
      await updateKeyword(kw.id, { is_active: !kw.is_active });
      loadKeywords();
    } catch {
      setError("Failed to update keyword.");
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteKeyword(id);
      loadKeywords();
    } catch {
      setError("Failed to delete keyword.");
    }
  }

  return (
    <AuthGuard>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Keywords</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
        >
          {showForm ? "Cancel" : "Add Keyword"}
        </button>
      </div>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="mt-6 space-y-4 rounded-lg border border-neutral-800 bg-neutral-900 p-6"
        >
          <div>
            <label className="block text-sm text-neutral-300 mb-1">
              Phrases (press Enter to add)
            </label>
            <ChipInput
              values={phrases}
              onChange={setPhrases}
              placeholder="Type a phrase and press Enter"
            />
            {phrases.some((p) => !p.includes(" ")) && (
              <p className="mt-1 text-xs text-yellow-400">
                Warning: Single-word phrases may generate many matches.
              </p>
            )}
          </div>
          <div>
            <label className="block text-sm text-neutral-300 mb-1">Exclusions (optional)</label>
            <ChipInput
              values={exclusions}
              onChange={setExclusions}
              placeholder="Words to exclude"
            />
          </div>
          <div>
            <label className="block text-sm text-neutral-300 mb-1">
              Proximity Window: {proximityWindow} words
            </label>
            <input
              type="range"
              min={1}
              max={50}
              value={proximityWindow}
              onChange={(e) => setProximityWindow(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={requireOrder}
                onChange={(e) => setRequireOrder(e.target.checked)}
                className="rounded border-neutral-600"
              />
              Require word order
            </label>
            <label className="flex items-center gap-2 text-sm text-neutral-300">
              <input
                type="checkbox"
                checked={useStemming}
                onChange={(e) => setUseStemming(e.target.checked)}
                className="rounded border-neutral-600"
              />
              Enable stemming
            </label>
          </div>
          <button
            type="submit"
            disabled={formLoading || phrases.length === 0}
            className="rounded-lg bg-blue-600 px-6 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {formLoading ? "Creating..." : "Create Keyword"}
          </button>
        </form>
      )}

      <div className="mt-6">
        {keywords.length === 0 ? (
          <EmptyState
            title="No keywords"
            description="Add your first keyword to start monitoring."
            action={
              <button
                onClick={() => setShowForm(true)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                Add Keyword
              </button>
            }
          />
        ) : (
          <div className="space-y-3">
            {keywords.map((kw) => (
              <div
                key={kw.id}
                className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {kw.phrases.map((p, i) => (
                      <span
                        key={i}
                        className="rounded bg-neutral-800 px-2 py-0.5 text-sm text-white"
                      >
                        {p}
                      </span>
                    ))}
                    {!kw.is_active && (
                      <span className="text-xs text-neutral-500">(inactive)</span>
                    )}
                  </div>
                  {kw.exclusions.length > 0 && (
                    <p className="mt-1 text-xs text-neutral-500">
                      Excludes: {kw.exclusions.join(", ")}
                    </p>
                  )}
                  <p className="mt-1 text-xs text-neutral-600">
                    Window: {kw.proximity_window} | Order: {kw.require_order ? "yes" : "no"} | Stemming: {kw.use_stemming ? "on" : "off"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleToggle(kw)}
                    className={`rounded px-3 py-1 text-xs ${
                      kw.is_active
                        ? "bg-green-900 text-green-300 hover:bg-green-800"
                        : "bg-neutral-800 text-neutral-400 hover:bg-neutral-700"
                    }`}
                  >
                    {kw.is_active ? "Active" : "Inactive"}
                  </button>
                  <button
                    onClick={() => handleDelete(kw.id)}
                    className="rounded px-3 py-1 text-xs text-red-400 hover:bg-red-900/30"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AuthGuard>
  );
}
