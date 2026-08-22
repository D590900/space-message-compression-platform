import { loadConfig } from "./config.js";
import { startTelemetry } from "./telemetry.js";

const config = loadConfig();
const telemetry = startTelemetry(config);
const { buildApp } = await import("./app.js");
const { app } = await buildApp(config);

const shutdown = async (signal: string) => {
  app.log.info({ signal }, "shutting down");
  await app.close();
  await telemetry.shutdown();
  process.exit(0);
};

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));

await app.listen({ host: config.HOST, port: config.PORT });
