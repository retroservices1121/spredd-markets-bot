/** Chain family identifier */
export type ChainFamily = "evm" | "solana";

/** Supported chain identifiers */
export type ChainId =
  | "polygon"
  | "base"
  | "bsc"
  | "arbitrum"
  | "solana"
  | "abstract";

/** Chain configuration */
export interface ChainConfig {
  id: ChainId;
  name: string;
  family: ChainFamily;
  chainId: number; // EVM chain ID or 0 for Solana
  rpcUrl: string;
  explorerUrl: string;
  nativeSymbol: string;
  nativeDecimals: number;
  color: string;
  tokens: TokenConfig[];
}

/** Token configuration on a chain */
export interface TokenConfig {
  symbol: string;
  name: string;
  address: string; // Contract address or mint address
  decimals: number;
  isNative?: boolean;
}

/** Token balance for display */
export interface TokenBalance {
  chainId: ChainId;
  symbol: string;
  name: string;
  balance: string; // Raw balance as string
  decimals: number;
  formatted: string; // Human-readable formatted balance
  usdValue: number;
  isNative: boolean;
}

/** Public info for an account (no private keys) */
export interface AccountPublicInfo {
  evmAddress: string;
  solanaAddress: string;
}

/** Metadata stored alongside the encrypted vault */
export interface VaultMeta {
  version: number;
  createdAt: number;
  evmAddress: string;
  solanaAddress: string;
}

/** Decrypted vault contents held in memory */
export interface DecryptedVault {
  mnemonic: string | null; // null if imported via private key
  evmPrivateKey: string;
  solanaPrivateKey: string; // base58 encoded
  evmAddress: string;
  solanaAddress: string;
}

/** Messages between popup and background service worker */
export type MessageType =
  | "UNLOCK_VAULT"
  | "LOCK_VAULT"
  | "GET_SESSION"
  | "GET_VAULT_DATA"
  | "RESET_TIMER"
  | "SET_AUTO_LOCK"
  | "GET_AUTO_LOCK"
  // Trading via Bot API
  | "GET_TRADE_QUOTE"
  | "EXECUTE_TRADE"
  | "CHECK_WALLET_LINKED";

export interface Message {
  type: MessageType;
  payload?: unknown;
}

export interface MessageResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

/** User preferences */
export interface Preferences {
  selectedChain: ChainId | "all";
  autoLockMinutes: number;
}
