// RoutIQ application and backend route configuration.
// Django PRE_URL is empty, so API calls must use root-level paths.
export const APP_BASE_PATH = (import.meta.env.VITE_APP_BASE_PATH || '/project/routiq').replace(/\/+$/, '') || '/';
export const PRE_URL = '';
// Production must use same-origin Vercel rewrites. This avoids browsers
// bypassing the proxy through a stale VITE_API_BASE_URL that points directly
// at Render. Local development can still opt into explicit backend URLs.
const configuredApiBase = import.meta.env.PROD
  ? '/api'
  : (import.meta.env.VITE_API_BASE_URL?.trim() || '/api');
const configuredGovApiBase = import.meta.env.PROD
  ? '/gov-api'
  : (import.meta.env.VITE_GOV_API_BASE_URL?.trim() || '/gov-api');

export const API_BASE_URL = configuredApiBase.replace(/\/+$/, '');
export const GOV_API_BASE_URL = configuredGovApiBase.replace(/\/+$/, '');