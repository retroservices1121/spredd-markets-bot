import { useState } from "react";
import { Copy, Check, Eye, EyeOff } from "lucide-react";
import { shortenAddress, copyToClipboard } from "@/lib/utils";

interface AddressBannerProps {
  address: string;
  label?: string;
}

export function AddressBanner({ address, label }: AddressBannerProps) {
  const [copied, setCopied] = useState(false);
  const [revealed, setRevealed] = useState(false);

  async function handleCopy() {
    const ok = await copyToClipboard(address);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => setRevealed(!revealed)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-secondary/50 hover:bg-secondary transition-colors text-xs"
      >
        {label && (
          <span className="text-muted-foreground">{label}</span>
        )}
        <span className="font-mono text-foreground">
          {revealed ? shortenAddress(address) : "••••••••••"}
        </span>
        {revealed ? (
          <EyeOff className="w-3 h-3 text-muted-foreground" />
        ) : (
          <Eye className="w-3 h-3 text-muted-foreground" />
        )}
      </button>
      {revealed && (
        <button
          onClick={handleCopy}
          className="p-1.5 rounded-md hover:bg-secondary transition-colors"
          title="Copy address"
        >
          {copied ? (
            <Check className="w-3 h-3 text-spredd-green" />
          ) : (
            <Copy className="w-3 h-3 text-muted-foreground" />
          )}
        </button>
      )}
    </div>
  );
}
