import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { getNodeAutoInstrumentations } from "@opentelemetry/auto-instrumentations-node";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { NodeSDK } from "@opentelemetry/sdk-node";

import type { ApiConfig } from "./config.js";

export type TelemetryRuntime = { shutdown(): Promise<void> };

const noOpRuntime: TelemetryRuntime = { shutdown: () => Promise.resolve() };

export function startTelemetry(config: ApiConfig): TelemetryRuntime {
  if (!config.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) return noOpRuntime;
  const sdk = new NodeSDK({
    resource: resourceFromAttributes({
      "service.name": config.OTEL_SERVICE_NAME,
      "service.version": "0.1.0",
      "deployment.environment.name": config.NODE_ENV,
    }),
    traceExporter: new OTLPTraceExporter({
      url: config.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT,
    }),
    instrumentations: [
      getNodeAutoInstrumentations({
        "@opentelemetry/instrumentation-fs": { enabled: false },
      }),
    ],
  });
  sdk.start();
  return { shutdown: () => sdk.shutdown() };
}
