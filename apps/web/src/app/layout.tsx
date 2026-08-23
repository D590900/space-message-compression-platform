import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "SMCP Console", template: "%s · SMCP" },
  description: "Operational evidence for deterministic message compression.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <ClerkProvider dynamic>{children}</ClerkProvider>
      </body>
    </html>
  );
}
