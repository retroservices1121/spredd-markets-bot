import { cn } from "@/lib/utils";

interface PriceBarProps {
  yesPrice: number;
  className?: string;
}

export function PriceBar({ yesPrice, className }: PriceBarProps) {
  const yesPct = Math.round(yesPrice * 100);
  const noPct = 100 - yesPct;

  return (
    <div className={cn("flex items-center gap-2 text-xs", className)}>
      <span className="text-spredd-green font-medium w-10 text-right">
        {yesPct}%
      </span>
      <div className="flex-1 h-2 rounded-full overflow-hidden bg-spredd-red/30">
        <div
          className="h-full rounded-full bg-spredd-green transition-all duration-300"
          style={{ width: `${yesPct}%` }}
        />
      </div>
      <span className="text-spredd-red font-medium w-10">{noPct}%</span>
    </div>
  );
}
