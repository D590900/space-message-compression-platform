import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { Status } from "./status";

afterEach(cleanup);

describe("Status", () => {
  it.each([
    ["COMPLETED", "completed", "status-success"],
    ["FAILED_TERMINAL", "failed terminal", "status-danger"],
    ["ENCODING", "encoding", "status-active"],
    ["CANCELLED", "cancelled", "status-muted"],
  ] as const)(
    "renders %s with explicit text and semantic tone",
    (value, label, className) => {
      render(createElement(Status, { value }));
      const status = screen.getByText(label);
      expect(status.classList.contains(className)).toBe(true);
      expect(status.querySelector("svg")?.getAttribute("aria-hidden")).toBe(
        "true",
      );
    },
  );
});
