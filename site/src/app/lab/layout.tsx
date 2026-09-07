import type { Metadata } from "next";
import { LabShell } from "./lab-ui";
import { publicationNotice, snapshotEnabled } from "@/lib/published-lab";
import "./lab.css";

export const metadata: Metadata = {
  title: { default: "Forecast lab — Thesis", template: "%s — Thesis lab" },
  description:
    "Registered forecast experiments, original distributions and official outcomes.",
  robots: { index: false, follow: false },
};
export default async function LabLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const publication = await publicationNotice();
  return (
    <LabShell snapshot={snapshotEnabled()} publication={publication}>
      {children}
    </LabShell>
  );
}
