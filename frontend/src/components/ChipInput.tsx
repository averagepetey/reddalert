"use client";

import { useState, KeyboardEvent } from "react";

interface ChipInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
}

export default function ChipInput({ values, onChange, placeholder }: ChipInputProps) {
  const [input, setInput] = useState("");

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && input.trim()) {
      e.preventDefault();
      const val = input.trim();
      if (!values.includes(val)) {
        onChange([...values, val]);
      }
      setInput("");
    } else if (e.key === "Backspace" && !input && values.length > 0) {
      onChange(values.slice(0, -1));
    }
  }

  function remove(idx: number) {
    onChange(values.filter((_, i) => i !== idx));
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 focus-within:border-blue-500">
      {values.map((v, i) => (
        <span
          key={i}
          className="flex items-center gap-1 rounded bg-neutral-700 px-2 py-0.5 text-sm text-white"
        >
          {v}
          <button
            type="button"
            onClick={() => remove(i)}
            className="text-neutral-400 hover:text-red-400"
          >
            x
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={values.length === 0 ? placeholder : ""}
        className="flex-1 bg-transparent text-sm text-white outline-none placeholder:text-neutral-500 min-w-[100px]"
      />
    </div>
  );
}
