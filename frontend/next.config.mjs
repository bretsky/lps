/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Every route is prerendered, so `next build` writes the whole site to out/ as plain files
  // (deployed to Cloudflare Pages by scripts/deploy.mjs). No server runs in production.
  // Note: with output "export", a custom distDir only renames out/ -- the build itself always
  // uses .next/, which is why deploy.mjs builds in a copy (.build/) instead of here.
  output: "export",
};

export default nextConfig;
