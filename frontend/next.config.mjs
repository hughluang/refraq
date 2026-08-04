/** @type {import("next").NextConfig} */
const apiUpstream =
  process.env.REFRAQ_API_UPSTREAM || "http://127.0.0.1:8000";

const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Dev HMR is origin-locked; biztest/curl often use 127.0.0.1 while `next dev`
  // prints localhost — allow both so client hydration is not left half-broken.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  experimental: {
    useTypeScriptCli: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUpstream}/:path*`,
      },
    ];
  },
};

export default nextConfig;
