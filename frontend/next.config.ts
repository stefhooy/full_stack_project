import type { NextConfig } from "next";

// Touched deliberately to give .github/workflows/frontend-ci.yml (path-
// filtered to frontend/**) its first real trigger since it was added --
// confirming it fires on an actual push, not just that GitHub accepted
// the YAML. See DOCEXP.md's Slice 33 entry.
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
