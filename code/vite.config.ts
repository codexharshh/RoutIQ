import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import { networkInterfaces } from 'os';

// The SPA is mounted at this path; API routes stay rooted at /api and /gov-api.
const APP_BASE_PATH = '/project/routiq';
const backendTarget = process.env.ROUTIQ_DJANGO_URL || 'http://127.0.0.1:8000';
const safeBackendTarget = (() => {
  try {
    return new URL(backendTarget).origin;
  } catch {
    return 'invalid URL';
  }
})();

const getNetworkIPs = (): string[] => {
  const nets = networkInterfaces();
  const ips: string[] = [];
  for (const entries of Object.values(nets)) {
    for (const entry of entries ?? []) {
      if (entry.family === 'IPv4' && !entry.internal && !ips.includes(entry.address)) {
        ips.push(entry.address);
      }
    }
  }
  return ips;
};

console.log(`RoutIQ network interfaces: ${getNetworkIPs().join(', ')}`);
console.log(`RoutIQ backend proxy origin: ${safeBackendTarget}`);

const backend = { target: backendTarget, changeOrigin: true, secure: false };

export default defineConfig({
  plugins: [react()],
  base: `${APP_BASE_PATH}/`,
  cacheDir: process.env.ROUTIQ_VITE_CACHE_DIR || undefined,
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('/node_modules/')) return undefined;
          if (/\/node_modules\/(leaflet|react-leaflet|react-leaflet-cluster|@react-leaflet)\//.test(id)) {
            return 'map-vendor';
          }
          if (/\/node_modules\/(react|react-dom|scheduler|loose-envify)\//.test(id)) {
            return 'react-vendor';
          }
          return undefined;
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': backend,
      '/gov-api': backend,
      '/accounts': backend,
      '/media': backend,
      '/static': backend,
    },
  },
});
