import { notFound } from "next/navigation";
import { ConditionalView } from "../../ConditionalViews";
import { LAB_DIGEST } from "@/lib/lab-paths";
export const metadata = { title: "Conditional comparison" };
export default async function ConditionalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!LAB_DIGEST.test(id)) notFound();
  return <ConditionalView id={id} />;
}
