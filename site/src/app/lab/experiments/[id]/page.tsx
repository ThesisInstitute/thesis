import { notFound } from "next/navigation";
import { ExperimentView } from "../../LabViews";
export const metadata = { title: "Experiment" };
export default async function ExperimentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[0-9a-f]{64}$/.test(id)) notFound();
  return <ExperimentView id={id} />;
}
