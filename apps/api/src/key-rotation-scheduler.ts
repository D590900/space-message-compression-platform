import { randomUUID } from "node:crypto";

import type { ClerkGateway } from "./auth.js";
import type { Database } from "./database.js";

export interface KeyRotationSchedulerGateway {
  start(): void;
  close(): Promise<void>;
}

export class KeyRotationScheduler implements KeyRotationSchedulerGateway {
  private timer: NodeJS.Timeout | undefined;
  private running = false;

  public constructor(
    private readonly database: Database,
    private readonly clerk: ClerkGateway,
    private readonly pollMilliseconds: number,
  ) {}

  public start(): void {
    if (this.timer) return;
    this.timer = setInterval(
      () =>
        void this.poll().catch((error: unknown) => {
          const errorCode =
            error instanceof Error ? error.name : "unknown_error";
          console.error("key rotation scheduler poll failed", { errorCode });
        }),
      this.pollMilliseconds,
    );
    this.timer.unref();
  }

  public async close(): Promise<void> {
    if (this.timer) clearInterval(this.timer);
    this.timer = undefined;
    while (this.running)
      await new Promise((resolve) => setTimeout(resolve, 10));
  }

  public async poll(): Promise<void> {
    if (this.running) return;
    this.running = true;
    try {
      const claimToken = randomUUID();
      const rotations = await this.database.claimDueApiKeyRotations(
        claimToken,
        25,
      );
      for (const rotation of rotations) {
        try {
          await this.clerk.revokeApiKey(
            rotation.old_key_id,
            `Rotated to ${rotation.new_key_id}`,
          );
          await this.database.completeApiKeyRotation(rotation.id, claimToken);
        } catch (error) {
          const message = error instanceof Error ? error.name : "unknown_error";
          await this.database.retryApiKeyRotation(
            rotation.id,
            claimToken,
            message,
          );
        }
      }
    } finally {
      this.running = false;
    }
  }
}
