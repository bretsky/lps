import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LPS All-Time Rankings",
  description:
    "League of Legends esports all-time player rankings by CLR (Career Legend Rating).",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
