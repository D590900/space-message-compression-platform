import { AlertTriangle, Check, Circle, LoaderCircle, X } from "lucide-react";
import type { CompressionStatus } from "../lib/types";

const running = new Set<CompressionStatus>([
  "PENDING",
  "VALIDATING",
  "ENCODING",
  "MEASURING",
  "SELECTING",
  "PACKAGING",
]);

export function Status({ value }: { value: CompressionStatus | string }) {
  const Icon =
    value === "COMPLETED"
      ? Check
      : value.startsWith("FAILED")
        ? AlertTriangle
        : value === "CANCELLED"
          ? X
          : running.has(value as CompressionStatus)
            ? LoaderCircle
            : Circle;
  const tone =
    value === "COMPLETED"
      ? "success"
      : value.startsWith("FAILED")
        ? "danger"
        : value === "CANCELLED"
          ? "muted"
          : "active";
  return (
    <span className={`status status-${tone}`}>
      <Icon size={14} aria-hidden="true" />
      {value.replaceAll("_", " ").toLowerCase()}
    </span>
  );
}
