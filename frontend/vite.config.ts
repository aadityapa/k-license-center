import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Node's process (no @types/node in this project).
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on all interfaces so other devices on the LAN can open the UI
    port: 5173,
    proxy: {
      // '/api/' (with the slash): the portal's own /api-clients and /api-logs pages must not be proxied.
      '/api/': {
        // KLC_API_TARGET lets a second copy of the API (tests, previews) be used instead.
        target: process.env.KLC_API_TARGET || 'http://localhost:3001',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
