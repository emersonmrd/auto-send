import type { NextConfig } from "next";

const isExport = process.env.NEXT_EXPORT === "true";

const nextConfig: NextConfig = {
  output: isExport ? "export" : undefined,
  // No export (pacote portátil) o próprio backend serve a tela, em qualquer porta livre de 8000 a 8020:
  // a API fica na mesma origem, por caminho relativo (issue #65). Um NEXT_PUBLIC_API_URL explícito continua valendo.
  env: isExport ? { NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "" } : {},
  images: {
    unoptimized: true,
  },
  cacheComponents: !isExport,
  partialPrefetching: !isExport,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
