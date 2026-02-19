import { ChevronDown } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { CHAINS, ALL_CHAIN_IDS } from "@/core/chains";
import type { ChainId } from "@/core/types";
import { cn } from "@/lib/utils";

interface SwapChainSelectProps {
  label: string;
  selected: ChainId;
  onChange: (chain: ChainId) => void;
  disabled?: boolean;
}

export function SwapChainSelect({
  label,
  selected,
  onChange,
  disabled,
}: SwapChainSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const chain = CHAINS[selected];

  return (
    <div ref={ref} className="relative flex-1">
      <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
        {label}
      </label>
      <button
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <div
          className="w-2.5 h-2.5 rounded-full shrink-0"
          style={{ backgroundColor: chain.color }}
        />
        <span className="truncate">{chain.name}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground ml-auto shrink-0" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-full bg-popover border border-border rounded-lg shadow-xl z-50 overflow-hidden max-h-48 overflow-y-auto">
          {ALL_CHAIN_IDS.map((id) => {
            const c = CHAINS[id];
            return (
              <button
                key={id}
                onClick={() => {
                  onChange(id);
                  setOpen(false);
                }}
                className={cn(
                  "w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-accent transition-colors",
                  selected === id && "text-spredd-orange"
                )}
              >
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: c.color }}
                />
                {c.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
