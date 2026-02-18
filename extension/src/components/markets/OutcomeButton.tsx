import { cn } from "@/lib/utils";
import type { OutcomeSelection } from "@/core/markets";

interface OutcomeButtonProps {
  outcome: OutcomeSelection;
  price: number;
  selected: boolean;
  onClick: () => void;
}

export function OutcomeButton({
  outcome,
  price,
  selected,
  onClick,
}: OutcomeButtonProps) {
  const isYes = outcome === "yes";
  const pct = Math.round(price * 100);

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex-1 flex flex-col items-center gap-1 py-3 rounded-xl border-2 transition-all",
        isYes
          ? selected
            ? "border-spredd-green bg-spredd-green/15 text-spredd-green"
            : "border-border hover:border-spredd-green/50 text-muted-foreground hover:text-spredd-green"
          : selected
            ? "border-spredd-red bg-spredd-red/15 text-spredd-red"
            : "border-border hover:border-spredd-red/50 text-muted-foreground hover:text-spredd-red"
      )}
    >
      <span className="text-xs font-medium uppercase">
        {isYes ? "Yes" : "No"}
      </span>
      <span className="text-lg font-bold">{pct}¢</span>
    </button>
  );
}
