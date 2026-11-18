import {
  buildPolicyEngineLedgerExport,
  loadPolicyEngineLedger,
  loadPolicyEngineLedgerRestatements,
} from "@/data/thesis-log";

export const dynamic = "force-static";

export async function GET() {
  return Response.json(
    buildPolicyEngineLedgerExport(
      await loadPolicyEngineLedger(),
      await loadPolicyEngineLedgerRestatements(),
    ),
  );
}
