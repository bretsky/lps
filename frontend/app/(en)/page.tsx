import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";

export const generateMetadata = () => boardMetadata("en", null, "all");

export default function Page() {
  return <BoardRoute locale="en" asOf={null} view="all" />;
}
