interface EmptyStateProps {
  title: string;
  description: string;
  action?: React.ReactNode;
}

export default function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-neutral-700 py-16 text-center">
      <h3 className="text-lg font-medium text-neutral-300">{title}</h3>
      <p className="mt-1 text-sm text-neutral-500">{description}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
