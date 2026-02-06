const statusColors: Record<string, string> = {
  active: "bg-green-900 text-green-300",
  inaccessible: "bg-red-900 text-red-300",
  private: "bg-yellow-900 text-yellow-300",
  pending: "bg-yellow-900 text-yellow-300",
  sent: "bg-green-900 text-green-300",
  failed: "bg-red-900 text-red-300",
};

export default function StatusBadge({ status }: { status: string }) {
  const color = statusColors[status] || "bg-neutral-800 text-neutral-300";
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {status}
    </span>
  );
}
