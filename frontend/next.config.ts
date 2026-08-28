import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Steam's own CDN, serving each game's official cover art (the same
    // asset its own store page uses) -- verified live before adding this
    // (curl -I against a real appid) rather than assumed from memory.
    // The one remote-image source in this app; everything else is either
    // hand-authored code or a locally committed asset.
    remotePatterns: [
      {
        protocol: "https",
        hostname: "cdn.cloudflare.steamstatic.com",
        pathname: "/steam/apps/**",
      },
    ],
  },
};

export default nextConfig;
