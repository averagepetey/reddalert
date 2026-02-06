import type { Match } from "@/lib/api";
import StatusBadge from "./StatusBadge";

export default function MatchCard({ match }: { match: Match }) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm">
            <span className="font-medium text-blue-400">r/{match.subreddit}</span>
            <span className="text-neutral-600">|</span>
            <span className="text-neutral-400">{match.content_type}</span>
            <StatusBadge status={match.alert_status} />
          </div>
          <p className="mt-1 text-sm text-neutral-300">{match.snippet}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
            <span>Matched: <span className="text-yellow-400">{match.matched_phrase}</span></span>
            {match.also_matched.length > 0 && (
              <span>Also: {match.also_matched.join(", ")}</span>
            )}
            <span>by u/{match.reddit_author}</span>
            <span>{new Date(match.detected_at).toLocaleString()}</span>
          </div>
        </div>
        <a
          href={match.reddit_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 rounded bg-neutral-800 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-700 transition-colors"
        >
          View on Reddit
        </a>
      </div>
    </div>
  );
}
