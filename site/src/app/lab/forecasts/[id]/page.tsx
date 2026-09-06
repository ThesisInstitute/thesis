import { Suspense } from "react";
import { notFound } from "next/navigation";
import { ForecastView } from "../../LabViews";
export const metadata = { title: "Forecast" };
export default async function ForecastPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[0-9a-f]{64}$/.test(id)) notFound();
  return (
    <Suspense fallback={<p role="status">Reading forecast…</p>}>
      <ForecastView id={id} />
    </Suspense>
  );
}
