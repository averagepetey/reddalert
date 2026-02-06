"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clearApiKey } from "@/lib/auth";

const links = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/keywords", label: "Keywords" },
  { href: "/subreddits", label: "Subreddits" },
  { href: "/webhooks", label: "Webhooks" },
  { href: "/matches", label: "Matches" },
  { href: "/settings", label: "Settings" },
];

export default function Navbar() {
  const pathname = usePathname();

  function handleLogout() {
    clearApiKey();
    window.location.href = "/";
  }

  return (
    <nav className="border-b border-neutral-800 bg-neutral-950 px-6 py-3">
      <div className="mx-auto flex max-w-7xl items-center justify-between">
        <Link href="/dashboard" className="text-lg font-bold text-white">
          Reddalert
        </Link>
        <div className="flex items-center gap-1">
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                pathname === link.href
                  ? "bg-neutral-800 text-white"
                  : "text-neutral-400 hover:text-white"
              }`}
            >
              {link.label}
            </Link>
          ))}
          <button
            onClick={handleLogout}
            className="ml-4 rounded px-3 py-1.5 text-sm text-neutral-400 hover:text-red-400 transition-colors"
          >
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}
