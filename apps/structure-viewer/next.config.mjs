/**
 * Next.js config for the Structure Viewer App.
 *
 * The platform's runtime proxy strips the `/api/v1/apps/runtime/{slug}/`
 * prefix before forwarding, so the container itself serves all routes
 * (including `/healthz` for the platform's health probe) at root. We use
 * `assetPrefix` — not `basePath` — so the HTML the app emits still points
 * the browser at the prefixed URL for static assets, which the proxy then
 * forwards back to the container.
 *
 * APP_BASE_PATH is read at build time and baked into the asset URLs.
 */

const basePath = process.env.APP_BASE_PATH || "";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  assetPrefix: basePath || undefined,
  reactStrictMode: true,
  // Ketcher's standalone build ships a WebWorker; allow Next to serve it.
  // Ketcher 3.x also pulls in `paper` (vector graphics), whose dist
  // includes a node-only entry that requires `jsdom`. Browser builds
  // don't need that branch — short-circuit it via webpack fallback.
  webpack: (config) => {
    config.module.rules.push({
      test: /\.worker\.js$/i,
      use: { loader: "worker-loader", options: { inline: "no-fallback" } },
    });
    config.resolve.fallback = {
      ...(config.resolve.fallback || {}),
      jsdom: false,
      canvas: false,
    };
    return config;
  },
};

export default nextConfig;
