import { OrganizationSwitcher } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AppShell } from "../../components/app-shell";

export default async function ConsoleLayout({
  children,
}: {
  children: ReactNode;
}) {
  const session = await auth();
  if (!session.userId) redirect("/sign-in");
  if (!session.orgId) {
    return (
      <main className="organization-gate">
        <p className="eyebrow">Organization required</p>
        <h1>Select an operating organization</h1>
        <p>
          Projects, jobs, credentials, and evidence are isolated by
          organization.
        </p>
        <OrganizationSwitcher
          hidePersonal
          afterSelectOrganizationUrl="/compressions"
        />
      </main>
    );
  }
  return <AppShell>{children}</AppShell>;
}
