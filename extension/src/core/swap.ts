/**
 * Type definitions for swap and bridge features.
 */

export type SwapMode = "swap" | "bridge";

/** Response from POST /swap/quote */
export interface SwapQuoteData {
  chain: string;
  from_token: string;
  amount: string;
  output_amount: string;
  fee_amount: string;
  fee_percent: number;
  estimated_time: string;
  tool_name: string;
  available: boolean;
  error?: string | null;
}

/** Response from POST /bridge/quote */
export interface BridgeQuoteData {
  source_chain: string;
  dest_chain: string;
  amount: string;
  fast_bridge: {
    output_amount: string;
    fee_amount: string;
    fee_percent: number;
    estimated_time: string;
    available: boolean;
    error?: string | null;
  } | null;
  standard_bridge: {
    output_amount: string;
    fee_amount: string;
    fee_percent: number;
    estimated_time: string;
    available: boolean;
  } | null;
}

/** Chain info from GET /bridge/chains */
export interface BridgeChainInfo {
  id: string;
  name: string;
  balance: string;
  has_balance: boolean;
}

/** Response from GET /bridge/chains */
export interface BridgeChainsResponse {
  chains: BridgeChainInfo[];
  wallet_address: string | null;
  dest_chain: string;
}

/** Execution result for both swap and bridge */
export interface SwapBridgeResult {
  success: boolean;
  tx_hash?: string | null;
  message: string;
}

/** Normalized display-friendly quote for UI */
export interface SwapConfirmQuote {
  mode: SwapMode;
  fromChain: string;
  toChain: string;
  fromToken: string;
  toToken: string;
  inputAmount: string;
  outputAmount: string;
  feeAmount: string;
  feePercent: number;
  estimatedTime: string;
  toolName: string;
  bridgeMode?: "fast" | "standard";
}
