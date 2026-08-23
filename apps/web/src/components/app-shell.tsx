"use client";

import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import {
  Archive,
  Boxes,
  Gauge,
  KeyRound,
  ListChecks,
  Plus,
  Settings,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const navigation = [
  ["Compressions", "/compressions", ListChecks],
  ["Artifacts", "/artifacts", Archive],
  ["Capsules", "/capsules", Boxes],
  ["Benchmarks", "/benchmarks", Gauge],
  ["API keys", "/api-keys", KeyRound],
  ["Settings", "/settings", Settings],
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="mobile-header">
        <Link href="/compressions" className="brand">
          <span>SM</span>
          <strong>SMCP</strong>
        </Link>
        <details className="mobile-menu">
          <summary>Menu</summary>
          <nav aria-label="Primary">
            {navigation.map(([label, href]) => (
              <Link key={href} href={href}>
                {label}
              </Link>
            ))}
          </nav>
        </details>
      </header>
      <aside className="rail">
        <Link href="/compressions" className="brand">
          <span>SM</span>
          <strong>SMCP</strong>
        </Link>
        <nav aria-label="Primary">
          {navigation.map(([label, href, Icon]) => {
            const active =
              pathname === href ||
              (href === "/compressions" &&
                pathname.startsWith("/compressions/"));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
              >
                <Icon size={18} />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="rail-account">
          <OrganizationSwitcher
            hidePersonal
            afterSelectOrganizationUrl="/compressions"
          />
          <UserButton showName />
        </div>
      </aside>
      <main id="main-content" className="workspace">
        {children}
      </main>
    </div>
  );
}
