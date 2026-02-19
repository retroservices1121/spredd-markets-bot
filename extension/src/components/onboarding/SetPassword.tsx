import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft, Loader2 } from "lucide-react";
import { deriveKeysFromMnemonic } from "@/core/keychain";
import { encryptVault } from "@/core/vault";
import type { DecryptedVault, VaultMeta } from "@/core/types";

interface SetPasswordProps {
  mnemonic: string | null;
  evmPrivateKey?: string;
  solanaPrivateKey?: string;
  /** @deprecated Use evmPrivateKey/solanaPrivateKey instead */
  privateKey?: string;
  onComplete: () => void;
  onBack: () => void;
}

export function SetPassword({
  mnemonic,
  evmPrivateKey,
  solanaPrivateKey,
  privateKey,
  onComplete,
  onBack,
}: SetPasswordProps) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit() {
    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match");
      return;
    }

    setLoading(true);
    setError("");

    try {
      let vault: DecryptedVault;

      if (mnemonic) {
        vault = await deriveKeysFromMnemonic(mnemonic);
      } else {
        // Handle separate EVM and Solana keys
        const evm = evmPrivateKey || privateKey;
        const sol = solanaPrivateKey;

        let evmAddr = "";
        let evmPk = "";
        let solAddr = "";
        let solPk = "";

        if (evm) {
          const isEvmKey = /^(0x)?[0-9a-fA-F]{64}$/.test(evm);
          if (isEvmKey) {
            const { Wallet } = await import("ethers");
            const wallet = new Wallet(
              evm.startsWith("0x") ? evm : `0x${evm}`
            );
            evmPk = wallet.privateKey;
            evmAddr = wallet.address;
          } else if (!sol) {
            // Legacy: single key that's Solana
            const { Keypair } = await import("@solana/web3.js");
            const bs58 = (await import("bs58")).default;
            const decoded = bs58.decode(evm);
            const keypair = Keypair.fromSecretKey(decoded);
            solPk = bs58.encode(keypair.secretKey);
            solAddr = keypair.publicKey.toBase58();
          }
        }

        if (sol) {
          const { Keypair } = await import("@solana/web3.js");
          const bs58 = (await import("bs58")).default;
          const decoded = bs58.decode(sol);
          const keypair = Keypair.fromSecretKey(decoded);
          solPk = bs58.encode(keypair.secretKey);
          solAddr = keypair.publicKey.toBase58();
        }

        if (!evmAddr && !solAddr) {
          throw new Error("No valid keys provided");
        }

        vault = {
          mnemonic: null,
          evmPrivateKey: evmPk,
          solanaPrivateKey: solPk,
          evmAddress: evmAddr,
          solanaAddress: solAddr,
        };
      }

      // Encrypt and store
      const encrypted = await encryptVault(JSON.stringify(vault), password);
      const meta: VaultMeta = {
        version: 1,
        createdAt: Date.now(),
        evmAddress: vault.evmAddress,
        solanaAddress: vault.solanaAddress,
      };

      await chrome.storage.local.set({
        vault_encrypted: encrypted,
        vault_meta: meta,
      });

      // Auto-unlock after creation
      chrome.runtime.sendMessage({
        type: "UNLOCK_VAULT",
        payload: { password },
      });

      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create wallet");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col h-full p-4">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      <h2 className="text-lg font-bold text-foreground mb-1">
        Set Password
      </h2>
      <p className="text-xs text-muted-foreground mb-6">
        This password encrypts your wallet on this device. You'll need it to
        unlock the extension.
      </p>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">
            Password
          </label>
          <Input
            type="password"
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setError("");
            }}
            placeholder="At least 8 characters"
            autoFocus
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">
            Confirm Password
          </label>
          <Input
            type="password"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              setError("");
            }}
            placeholder="Confirm password"
          />
        </div>
      </div>

      {error && <p className="text-xs text-spredd-red mt-2">{error}</p>}

      <div className="mt-auto pt-4">
        <Button
          className="w-full"
          disabled={loading || !password || !confirm}
          onClick={handleSubmit}
        >
          {loading ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Encrypting...
            </>
          ) : (
            "Create Wallet"
          )}
        </Button>
      </div>
    </div>
  );
}
