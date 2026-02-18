/**
 * Multi-chain balance fetching.
 * EVM: ethers JsonRpcProvider for native + ERC20
 * Solana: Connection for SOL + SPL tokens
 */

import { JsonRpcProvider, Contract, formatUnits } from "ethers";
import { Connection, PublicKey } from "@solana/web3.js";
import { CHAINS, ALL_CHAIN_IDS, EVM_CHAIN_IDS } from "./chains";
import type { ChainId, TokenBalance, TokenConfig } from "./types";

// ERC20 minimal ABI
const ERC20_ABI = [
  "function balanceOf(address) view returns (uint256)",
];

// SPL Token program
const TOKEN_PROGRAM_ID = new PublicKey(
  "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
);

// Provider cache
const evmProviders = new Map<string, JsonRpcProvider>();
let solanaConnection: Connection | null = null;

function getEvmProvider(rpcUrl: string): JsonRpcProvider {
  let provider = evmProviders.get(rpcUrl);
  if (!provider) {
    provider = new JsonRpcProvider(rpcUrl);
    evmProviders.set(rpcUrl, provider);
  }
  return provider;
}

function getSolanaConnection(): Connection {
  if (!solanaConnection) {
    solanaConnection = new Connection(CHAINS.solana.rpcUrl, "confirmed");
  }
  return solanaConnection;
}

async function fetchEvmTokenBalance(
  provider: JsonRpcProvider,
  address: string,
  token: TokenConfig,
  chainId: ChainId
): Promise<TokenBalance> {
  try {
    let rawBalance: bigint;
    if (token.isNative) {
      rawBalance = await provider.getBalance(address);
    } else {
      const contract = new Contract(token.address, ERC20_ABI, provider);
      rawBalance = await contract.balanceOf(address);
    }

    const formatted = formatUnits(rawBalance, token.decimals);
    const floatVal = parseFloat(formatted);

    return {
      chainId,
      symbol: token.symbol,
      name: token.name,
      balance: rawBalance.toString(),
      decimals: token.decimals,
      formatted,
      usdValue: token.symbol.includes("USD") ? floatVal : 0, // simple: stablecoins = $1
      isNative: !!token.isNative,
    };
  } catch {
    return {
      chainId,
      symbol: token.symbol,
      name: token.name,
      balance: "0",
      decimals: token.decimals,
      formatted: "0",
      usdValue: 0,
      isNative: !!token.isNative,
    };
  }
}

async function fetchSolanaBalances(
  solanaAddress: string
): Promise<TokenBalance[]> {
  const results: TokenBalance[] = [];
  const connection = getSolanaConnection();
  const pubkey = new PublicKey(solanaAddress);

  // Native SOL
  try {
    const lamports = await connection.getBalance(pubkey);
    const solBalance = lamports / 1e9;
    results.push({
      chainId: "solana",
      symbol: "SOL",
      name: "Solana",
      balance: lamports.toString(),
      decimals: 9,
      formatted: solBalance.toString(),
      usdValue: 0, // no price feed yet
      isNative: true,
    });
  } catch {
    results.push({
      chainId: "solana",
      symbol: "SOL",
      name: "Solana",
      balance: "0",
      decimals: 9,
      formatted: "0",
      usdValue: 0,
      isNative: true,
    });
  }

  // SPL USDC
  try {
    const usdcMint = new PublicKey(CHAINS.solana.tokens[1].address);
    const tokenAccounts = await connection.getTokenAccountsByOwner(pubkey, {
      mint: usdcMint,
    });

    let totalUsdc = 0n;
    for (const { account } of tokenAccounts.value) {
      // Token account data: first 64 bytes are mint + owner, next 8 bytes are amount (little-endian u64)
      const data = account.data;
      const amount = data.readBigUInt64LE(64);
      totalUsdc += amount;
    }

    const formatted = Number(totalUsdc) / 1e6;
    results.push({
      chainId: "solana",
      symbol: "USDC",
      name: "USD Coin",
      balance: totalUsdc.toString(),
      decimals: 6,
      formatted: formatted.toString(),
      usdValue: formatted,
      isNative: false,
    });
  } catch {
    results.push({
      chainId: "solana",
      symbol: "USDC",
      name: "USD Coin",
      balance: "0",
      decimals: 6,
      formatted: "0",
      usdValue: 0,
      isNative: false,
    });
  }

  return results;
}

/**
 * Fetch balances across all (or selected) chains in parallel.
 */
export async function fetchAllBalances(
  evmAddress: string,
  solanaAddress: string,
  chainIds?: ChainId[]
): Promise<TokenBalance[]> {
  const targetChains = chainIds ?? ALL_CHAIN_IDS;
  const promises: Promise<TokenBalance[]>[] = [];

  // EVM chains
  for (const chainId of targetChains) {
    if (!EVM_CHAIN_IDS.includes(chainId)) continue;
    if (!evmAddress) continue;

    const chain = CHAINS[chainId];
    const provider = getEvmProvider(chain.rpcUrl);

    const chainPromise = Promise.all(
      chain.tokens.map((token) =>
        fetchEvmTokenBalance(provider, evmAddress, token, chainId)
      )
    );
    promises.push(chainPromise);
  }

  // Solana
  if (targetChains.includes("solana") && solanaAddress) {
    promises.push(fetchSolanaBalances(solanaAddress));
  }

  const results = await Promise.allSettled(promises);
  const balances: TokenBalance[] = [];

  for (const result of results) {
    if (result.status === "fulfilled") {
      balances.push(...result.value);
    }
  }

  return balances;
}
