import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

const VERSION = 1;
const NONCE_BYTES = 12;
const TAG_BYTES = 16;

export class SecretBox {
  private readonly key: Buffer;

  public constructor(base64Key: string) {
    this.key = Buffer.from(base64Key, "base64");
    if (this.key.length !== 32)
      throw new Error("webhook encryption key must be 32 bytes");
  }

  public encrypt(value: string): Buffer {
    const nonce = randomBytes(NONCE_BYTES);
    const cipher = createCipheriv("aes-256-gcm", this.key, nonce);
    const ciphertext = Buffer.concat([
      cipher.update(value, "utf8"),
      cipher.final(),
    ]);
    return Buffer.concat([
      Buffer.from([VERSION]),
      nonce,
      cipher.getAuthTag(),
      ciphertext,
    ]);
  }

  public decrypt(envelope: Uint8Array): string {
    const bytes = Buffer.from(envelope);
    if (bytes.length < 1 + NONCE_BYTES + TAG_BYTES || bytes[0] !== VERSION)
      throw new Error("invalid encrypted secret envelope");
    const nonce = bytes.subarray(1, 1 + NONCE_BYTES);
    const tag = bytes.subarray(1 + NONCE_BYTES, 1 + NONCE_BYTES + TAG_BYTES);
    const ciphertext = bytes.subarray(1 + NONCE_BYTES + TAG_BYTES);
    const decipher = createDecipheriv("aes-256-gcm", this.key, nonce);
    decipher.setAuthTag(tag);
    return (
      decipher.update(ciphertext, undefined, "utf8") + decipher.final("utf8")
    );
  }
}
