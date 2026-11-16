"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { useLocale } from "@/lib/i18n";
import { localePath } from "@/lib/site";

/** A link to a page that exists in every language (a board, About), pointing at the reader's
 *  language's URL: "/" for English, "/ko" for a Korean reader. Prerendered (and hydrated) as
 *  the English URL. */
export function LocalizedLink({ path, ...props }: { path: string } & Omit<ComponentProps<typeof Link>, "href">) {
  return <Link href={localePath(useLocale(), path)} {...props} />;
}
