import { cn } from "@/lib/utils";

interface ProgressBarProps {
  yesPercent: number;
  showLabels?: boolean;
  className?: string;
}

export function ProgressBar({ yesPercent, showLabels = true, className }: ProgressBarProps) {
  const noPercent = 100 - yesPercent;

  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-white/5">
        <div
          className="bg-spredd-green transition-all duration-500 rounded-l-full"
          style={{ width: `${yesPercent}%` }}
        />
        <div
          className="bg-spredd-red transition-all duration-500 rounded-r-full"
          style={{ width: `${noPercent}%` }}
        />
      </div>
      {showLabels && (
        <div className="flex justify-between text-xs">
          <span className="text-spredd-green font-medium">Yes {Math.round(yesPercent)}%</span>
          <span className="text-spredd-red font-medium">No {Math.round(noPercent)}%</span>
        </div>
      )}
    </div>
  );
}
