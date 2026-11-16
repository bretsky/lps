import { AboutRoute, aboutMetadata } from "@/components/routes/AboutRoute";

export const metadata = aboutMetadata("en");

export default function AboutPage() {
  return <AboutRoute />;
}
