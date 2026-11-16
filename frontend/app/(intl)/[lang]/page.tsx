import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";
import type { Locale } from "@/lib/i18n/config";

type Params = { params: Promise<{ lang: string }> };

export async function generateMetadata({ params }: Params) {
  return boardMetadata((await params).lang as Locale, null, "all");
}

export default async function Page({ params }: Params) {
  return <BoardRoute locale={(await params).lang as Locale} asOf={null} view="all" />;
}
