import { createHmac, randomUUID } from "node:crypto";

import { Agent, fetch } from "undici";

import type { Database, WebhookDeliveryClaim } from "./database.js";
import { SecretBox } from "./secret-box.js";
import { resolvePublicWebhookUrl } from "./webhook-url.js";

export interface WebhookDispatcherGateway {
  start(): void;
  close(): Promise<void>;
}

export function webhookSignature(
  secret: string,
  eventId: string,
  timestamp: string,
  body: string,
): string {
  return createHmac("sha256", secret)
    .update(`${eventId}.${timestamp}.${body}`)
    .digest("base64");
}

export class WebhookDispatcher implements WebhookDispatcherGateway {
  private timer: NodeJS.Timeout | undefined;
  private running = false;
  private readonly secretBox: SecretBox;

  public constructor(
    private readonly database: Database,
    encryptionKey: string,
    private readonly pollMilliseconds: number,
    private readonly maximumAttempts: number,
    private readonly timeoutMilliseconds: number,
  ) {
    this.secretBox = new SecretBox(encryptionKey);
  }

  public start(): void {
    if (this.timer) return;
    this.timer = setInterval(
      () =>
        void this.poll().catch((error: unknown) => {
          const errorCode =
            error instanceof Error ? error.name : "unknown_error";
          console.error("webhook dispatcher poll failed", { errorCode });
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
      await this.database.materializeWebhookDeliveries();
      const claimToken = randomUUID();
      const deliveries = await this.database.claimWebhookDeliveries(
        claimToken,
        25,
      );
      for (const delivery of deliveries)
        await this.deliver(delivery, claimToken);
    } finally {
      this.running = false;
    }
  }

  private async deliver(
    delivery: WebhookDeliveryClaim,
    claimToken: string,
  ): Promise<void> {
    let responseCode: number | null = null;
    try {
      const resolved = await resolvePublicWebhookUrl(delivery.url);
      const body = JSON.stringify(delivery.payload);
      const timestamp = Math.floor(Date.now() / 1_000).toString();
      const secret = this.secretBox.decrypt(delivery.secret_ciphertext);
      const signature = webhookSignature(
        secret,
        delivery.event_id,
        timestamp,
        body,
      );
      const dispatcher = new Agent({
        connect: {
          lookup: (_hostname, _options, callback) =>
            callback(null, resolved.address, resolved.family),
        },
      });
      try {
        const response = await fetch(resolved.url, {
          method: "POST",
          body,
          dispatcher,
          redirect: "manual",
          signal: AbortSignal.timeout(this.timeoutMilliseconds),
          headers: {
            "content-type": "application/json",
            "user-agent": "smcp-webhooks/0.1",
            "webhook-id": delivery.event_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": `v1,${signature}`,
          },
        });
        responseCode = response.status;
        await response.body?.cancel();
      } finally {
        await dispatcher.close();
      }
      if (responseCode < 200 || responseCode >= 300) {
        const responseError = new Error("non-success webhook response");
        responseError.name = `HTTP_${responseCode}`;
        throw responseError;
      }
      await this.database.completeWebhookDelivery(
        delivery.id,
        claimToken,
        responseCode,
      );
    } catch (error) {
      const errorCode = error instanceof Error ? error.name : "unknown_error";
      await this.database.failWebhookDelivery(
        delivery.id,
        claimToken,
        delivery.attempt,
        this.maximumAttempts,
        errorCode,
        responseCode,
      );
    }
  }
}
