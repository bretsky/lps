import { RankingsPage } from "@/components/board/RankingsPage";
import { loadBoardPage, loadMeta } from "@/lib/data";

export default async function Page() {
  const [data, meta] = await Promise.all([loadBoardPage(null), loadMeta()]);
  return <RankingsPage data={data} meta={meta} asOf={null} />;
}
