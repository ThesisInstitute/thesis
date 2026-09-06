import { notFound } from "next/navigation";
import { AgentView } from "../../LabViews";
export const metadata = { title: "Agent" };
export default async function AgentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[0-9a-f]{64}$/.test(id)) notFound();
  return <AgentView id={id} />;
}
