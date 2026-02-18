import { useState } from "react";
import type { TokenBalance } from "@/core/types";
import { CHAINS } from "@/core/chains";
import { formatTokenAmount, formatUSD } from "@/lib/utils";

interface TokenRowProps {
  token: TokenBalance;
}

export function TokenRow({ token }: TokenRowProps) {
  const chain = CHAINS[token.chainId];
  const tokenConfig = chain?.tokens.find((t) => t.symbol === token.symbol);
  const logoUrl = tokenConfig?.logo;
  const [imgError, setImgError] = useState(false);

  return (
    <div className="flex items-center justify-between py-3 px-1">
      <div className="flex items-center gap-3">
        {/* Token icon: logo image with fallback to colored circle */}
        {logoUrl && !imgError ? (
          <img
            src={logoUrl}
            alt={token.symbol}
            className="w-9 h-9 rounded-full object-cover"
            onError={() => setImgError(true)}
          />
        ) : (
          <div
            className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white"
            style={{ backgroundColor: chain?.color ?? "#666" }}
          >
            {token.symbol.slice(0, 2)}
          </div>
        )}
        <div>
          <p className="text-sm font-medium text-foreground">{token.symbol}</p>
          <p className="text-xs text-muted-foreground">{chain?.name}</p>
        </div>
      </div>
      <div className="text-right">
        <p className="text-sm font-medium text-foreground">
          {formatTokenAmount(token.formatted)}
        </p>
        <p className="text-xs text-muted-foreground">
          {formatUSD(token.usdValue)}
        </p>
      </div>
    </div>
  );
}
