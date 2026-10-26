// RoutIQ application and backend route configuration.
// Django PRE_URL is empty, so API calls must use root-level paths.
export const APP_BASE_PATH = (import.meta.env.VITE_APP_BASE_PATH || '/project/routiq').replace(/\/+$/, '') || '/';
export const PRE_URL = '';
// On hosted builds, use same-origin Vercel rewrites to avoid browser CORS failures.
// Local builds may still use explicit backend URLs from the developer environment.
const configuredApiBase = import.meta.env.PROD ? '/api' : (import.meta.env.VITE_API_BASE_URL?.trim() || '/api');
const configuredGovApiBase = import.meta.env.PROD ? '/gov-api' : (import.meta.env.VITE_GOV_API_BASE_URL?.trim() || '/gov-api');

export const API_BASE_URL = configuredApiBase.replace(/\/+$/, '');
export const GOV_API_BASE_URL = configuredGovApiBase.replace(/\/+$/, '');