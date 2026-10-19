import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { cleanValue, keyKind } from "./src/env";

export default defineConfig(({ mode }) => {
  // The key is compiled into the page, and every visitor can read it. A secret
  // one (service_role / sb_secret_) there would hand anyone the whole
  // database — so such a build stops here, and nothing is published.
  const env = loadEnv(mode, ".", "VITE_");
  if (keyKind(cleanValue(env.VITE_SUPABASE_ANON_KEY)) === "secret") {
    throw new Error(
      "VITE_SUPABASE_ANON_KEY holds a SECRET Supabase key (service_role / sb_secret_). " +
      "Only the public key may be built into the site: Supabase → Project Settings → " +
      "API Keys → the Publishable key (or the legacy anon key).",
    );
  }
  return {
    // relative asset paths: the same build serves from a site's root or from
    // under any path
    base: "./",
    plugins: [react(), tailwindcss()],
  };
});
