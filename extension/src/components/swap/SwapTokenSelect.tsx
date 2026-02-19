import { ChevronDown } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import type { TokenConfig, ChainId } from "@/core/types";
import { CHAINS } from "@/core/chains";
import { cn } from "@/lib/utils";

interface SwapTokenSelectProps {
  chainId: ChainId;
  selected: TokenConfig | null;
  onChange: (token: TokenConfig) => void;
  disabled?: boolean;
}

export function SwapTokenSelect({
  chainId,
  selected,
  onChange,
  disabled,
}: SwapTokenSelectProps) {
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

  const tokens = CHAINS[chainId]?.tokens ?? [];

  return (
    <div ref={ref} className="relative flex-1">
      <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
        Token
      </label>
      <button
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm",
          disabled && "opacity-50 cursor-not-allowed"
        )}
      >
        <span className="truncate">{selected?.symbol ?? "Select"}</span>
        <ChevronDown className="w-3.5 h-3.5 text-muted-foreground ml-auto shrink-0" />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 w-full bg-popover border border-border rounded-lg shadow-xl z-50 overflow-hidden max-h-48 overflow-y-auto">
          {tokens.map((token) => (
            <button
              key={token.address}
              onClick={() => {
                onChange(token);
                setOpen(false);
              }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-accent transition-colors",
                selected?.address === token.address && "text-spredd-orange"
              )}
            >
              <span>{token.symbol}</span>
              <span className="text-xs text-muted-foreground ml-auto">
                {token.name}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
