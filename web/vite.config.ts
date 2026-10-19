import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  // relative asset paths: the same build serves from a site's root
  // (Cloudflare Pages) or from under any path
  base: "./",
  plugins: [react(), tailwindcss()],
});
