import { AboutRoute, aboutMetadata } from "@/components/routes/AboutRoute";
import type { Locale } from "@/lib/i18n/config";

type Params = { params: Promise<{ lang: string }> };

export async function generateMetadata({ params }: Params) {
  return aboutMetadata((await params).lang as Locale);
}

export default function AboutPage() {
  return <AboutRoute />;
}
