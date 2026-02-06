interface StatCardProps {
  label: string;
  value: number | string;
}

export default function StatCard({ label, value }: StatCardProps) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-5">
      <p className="text-sm text-neutral-400">{label}</p>
      <p className="mt-1 text-3xl font-bold text-white">{value}</p>
    </div>
  );
}
