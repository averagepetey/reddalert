interface StepIndicatorProps {
  steps: string[];
  current: number;
}

export default function StepIndicator({ steps, current }: StepIndicatorProps) {
  return (
    <div className="flex items-center gap-2">
      {steps.map((label, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-medium ${
              i < current
                ? "bg-green-600 text-white"
                : i === current
                ? "bg-blue-600 text-white"
                : "bg-neutral-800 text-neutral-500"
            }`}
          >
            {i < current ? "\u2713" : i + 1}
          </div>
          <span
            className={`text-sm ${
              i <= current ? "text-white" : "text-neutral-500"
            }`}
          >
            {label}
          </span>
          {i < steps.length - 1 && (
            <div
              className={`h-px w-8 ${
                i < current ? "bg-green-600" : "bg-neutral-700"
              }`}
            />
          )}
        </div>
      ))}
    </div>
  );
}
