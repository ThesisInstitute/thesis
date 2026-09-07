import { redirect } from "next/navigation";
import { snapshotEnabled } from "@/lib/published-lab";
export default function LabPage() {
  redirect(snapshotEnabled() ? "/lab/conditionals" : "/lab/forecasts");
}
