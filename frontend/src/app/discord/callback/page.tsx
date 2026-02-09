"use client";

import { useEffect, useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { sendDiscordGuild } from "@/lib/api";

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    const guild_id = searchParams.get("guild_id");
    const permissions = searchParams.get("permissions");
    const state = searchParams.get("state");
    const savedState = localStorage.getItem("discord_oauth_state");

    if (!guild_id || !state) {
      setError("Missing guild ID or state parameter.");
      return;
    }

    if (state !== savedState) {
      setError("State mismatch. This may be a CSRF attack. Please try again.");
      return;
    }

    sendDiscordGuild(guild_id, permissions || "", state)
      .then(() => {
        if (cancelled) return;
        localStorage.removeItem("discord_oauth_state");
        localStorage.setItem("discord_oauth_result", "success");
        // If opened as popup, close it; otherwise redirect
        if (window.opener) {
          window.close();
        } else {
          router.replace("/onboarding?discord=success");
        }
      })
      .catch(() => {
        if (cancelled) return;
        // Don't overwrite a success from a prior call (React strict mode double-fire)
        if (localStorage.getItem("discord_oauth_result") === "success") return;
        localStorage.setItem("discord_oauth_result", "error");
        if (window.opener) {
          window.close();
        } else {
          setError("Failed to connect Discord. Please try again.");
        }
      });

    return () => { cancelled = true; };
  }, [searchParams, router]);

  if (error) {
    return (
      <div className="mx-auto max-w-md mt-20 text-center">
        <h1 className="text-xl font-bold text-red-400">Connection Failed</h1>
        <p className="mt-4 text-sm text-neutral-400">{error}</p>
        <a
          href="/onboarding"
          className="mt-6 inline-block rounded-lg bg-neutral-800 px-6 py-2 text-sm text-white hover:bg-neutral-700"
        >
          Back to Setup
        </a>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-md mt-20 text-center">
      <h1 className="text-xl font-bold">Connecting Discord...</h1>
      <p className="mt-4 text-sm text-neutral-400">
        Please wait while we complete the connection.
      </p>
    </div>
  );
}

export default function DiscordCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-md mt-20 text-center">
          <h1 className="text-xl font-bold">Loading...</h1>
        </div>
      }
    >
      <CallbackHandler />
    </Suspense>
  );
}
