import type { Metadata } from "next";
import { LabShell } from "./lab-ui";
import "./lab.css";

export const metadata: Metadata = {
  title: { default: "Forecast lab — Thesis", template: "%s — Thesis lab" },
  description:
    "Registered forecast experiments, original distributions and official outcomes.",
  robots: { index: false, follow: false },
};
export default function LabLayout({ children }: { children: React.ReactNode }) {
  return <LabShell>{children}</LabShell>;
}
