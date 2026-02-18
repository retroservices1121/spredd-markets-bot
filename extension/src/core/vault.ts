/**
 * AES-256-GCM vault encryption/decryption using Web Crypto API.
 * Mirrors the layout from src/utils/encryption.py:
 *   hex(salt[16] + nonce[12] + ciphertext)
 * Key derivation: PBKDF2-SHA256 with 100k iterations.
 */

const SALT_LENGTH = 16;
const NONCE_LENGTH = 12;
const KEY_LENGTH = 32;
const ITERATIONS = 100_000;

function hexToBytes(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function deriveKey(
  password: string,
  salt: Uint8Array
): Promise<CryptoKey> {
  const encoder = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveKey"]
  );

  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt,
      iterations: ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: KEY_LENGTH * 8 },
    false,
    ["encrypt", "decrypt"]
  );
}

/**
 * Encrypt plaintext string with a password.
 * Returns hex string: salt(16) + nonce(12) + ciphertext.
 */
export async function encryptVault(
  plaintext: string,
  password: string
): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(SALT_LENGTH));
  const nonce = crypto.getRandomValues(new Uint8Array(NONCE_LENGTH));
  const key = await deriveKey(password, salt);

  const encoder = new TextEncoder();
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: nonce },
    key,
    encoder.encode(plaintext)
  );

  const result = new Uint8Array(
    SALT_LENGTH + NONCE_LENGTH + ciphertext.byteLength
  );
  result.set(salt, 0);
  result.set(nonce, SALT_LENGTH);
  result.set(new Uint8Array(ciphertext), SALT_LENGTH + NONCE_LENGTH);

  return bytesToHex(result);
}

/**
 * Decrypt hex-encoded vault data with a password.
 * Expects format: hex(salt[16] + nonce[12] + ciphertext).
 * Throws on wrong password or corrupted data.
 */
export async function decryptVault(
  encryptedHex: string,
  password: string
): Promise<string> {
  const encrypted = hexToBytes(encryptedHex);

  const salt = encrypted.slice(0, SALT_LENGTH);
  const nonce = encrypted.slice(SALT_LENGTH, SALT_LENGTH + NONCE_LENGTH);
  const ciphertext = encrypted.slice(SALT_LENGTH + NONCE_LENGTH);

  const key = await deriveKey(password, salt);

  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: nonce },
    key,
    ciphertext
  );

  return new TextDecoder().decode(plaintext);
}
