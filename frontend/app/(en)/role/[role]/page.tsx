// Today's board for one role ("Greatest ADCs of all time"). Same page as `/` with that role's
// tab open; the tab switches in place (the URL follows), so these exist mostly as entry points
// a search engine can index and a reader can share.
import { notFound } from "next/navigation";
import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";
import { LANES, ROLE_SLUGS, laneFromSlug } from "@/lib/site";

export const dynamicParams = false;

export function generateStaticParams() {
  return LANES.map((l) => ({ role: ROLE_SLUGS[l] }));
}

export async function generateMetadata({ params }: { params: Promise<{ role: string }> }) {
  const lane = laneFromSlug((await params).role);
  return lane ? boardMetadata("en", null, lane) : {};
}

export default async function RolePage({ params }: { params: Promise<{ role: string }> }) {
  const lane = laneFromSlug((await params).role);
  if (!lane) notFound();
  return <BoardRoute locale="en" asOf={null} view={lane} />;
}
