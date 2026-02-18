/**
 * HD key generation: BIP-39 mnemonic + BIP-44 derivation.
 * EVM: m/44'/60'/0'/0/0  (ethers.js HDNodeWallet)
 * Solana: m/44'/501'/0'/0' (ed25519-hd-key + tweetnacl)
 */

import * as bip39 from "bip39";
import { HDNodeWallet } from "ethers";
import { derivePath } from "ed25519-hd-key";
import nacl from "tweetnacl";
import { Keypair } from "@solana/web3.js";
import bs58 from "bs58";
import type { DecryptedVault } from "./types";

const EVM_PATH = "m/44'/60'/0'/0/0";
const SOLANA_PATH = "m/44'/501'/0'/0'";

/** Generate a new 12-word BIP-39 mnemonic */
export function generateMnemonic(): string {
  return bip39.generateMnemonic(128); // 128 bits = 12 words
}

/** Validate a mnemonic phrase */
export function validateMnemonic(mnemonic: string): boolean {
  return bip39.validateMnemonic(mnemonic.trim().toLowerCase());
}

/** Derive EVM and Solana keys from a mnemonic */
export async function deriveKeysFromMnemonic(
  mnemonic: string
): Promise<DecryptedVault> {
  // EVM derivation via ethers.js
  const evmWallet = HDNodeWallet.fromPhrase(mnemonic, undefined, EVM_PATH);

  // Solana derivation via ed25519-hd-key
  const seed = await bip39.mnemonicToSeed(mnemonic);
  const { key } = derivePath(SOLANA_PATH, Buffer.from(seed).toString("hex"));
  const solKeypair = nacl.sign.keyPair.fromSeed(key);
  const solanaKeypair = Keypair.fromSecretKey(solKeypair.secretKey);

  return {
    mnemonic,
    evmPrivateKey: evmWallet.privateKey,
    solanaPrivateKey: bs58.encode(solanaKeypair.secretKey),
    evmAddress: evmWallet.address,
    solanaAddress: solanaKeypair.publicKey.toBase58(),
  };
}

/** Import a wallet from a private key (EVM or Solana) */
export function importFromPrivateKey(
  key: string,
  type: "evm" | "solana"
): DecryptedVault {
  if (type === "evm") {
    const { Wallet } = require("ethers") as typeof import("ethers");
    const wallet = new Wallet(key);
    return {
      mnemonic: null,
      evmPrivateKey: wallet.privateKey,
      solanaPrivateKey: "",
      evmAddress: wallet.address,
      solanaAddress: "",
    };
  } else {
    const decoded = bs58.decode(key);
    const keypair = Keypair.fromSecretKey(decoded);
    return {
      mnemonic: null,
      evmPrivateKey: "",
      solanaPrivateKey: bs58.encode(keypair.secretKey),
      evmAddress: "",
      solanaAddress: keypair.publicKey.toBase58(),
    };
  }
}
