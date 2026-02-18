import { ChevronDown } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { CHAINS, ALL_CHAIN_IDS } from "@/core/chains";
import type { ChainId } from "@/core/types";
import { cn } from "@/lib/utils";

interface ChainSelectorProps {
  selected: ChainId | "all";
  onChange: (chain: ChainId | "all") => void;
}

export function ChainSelector({ selected, onChange }: ChainSelectorProps) {
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

  const selectedChain = selected === "all" ? null : CHAINS[selected];
  const label = selected === "all" ? "All Chains" : selectedChain?.name ?? "";

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm"
      >
        {selectedChain && (
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{ backgroundColor: selectedChain.color }}
          />
        )}
        <span>{label}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-48 bg-popover border border-border rounded-lg shadow-xl z-50 overflow-hidden">
          <button
            onClick={() => {
              onChange("all");
              setOpen(false);
            }}
            className={cn(
              "w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-accent transition-colors",
              selected === "all" && "text-spredd-orange"
            )}
          >
            All Chains
          </button>
          {ALL_CHAIN_IDS.map((id) => {
            const chain = CHAINS[id];
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
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: chain.color }}
                />
                {chain.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
