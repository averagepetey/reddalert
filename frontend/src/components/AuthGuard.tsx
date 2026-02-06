"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getApiKey } from "@/lib/auth";
import Navbar from "./Navbar";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!getApiKey()) {
      router.replace("/");
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) return null;

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </>
  );
}
