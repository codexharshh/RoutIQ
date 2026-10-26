// RoutIQ application and backend route configuration.
// Django PRE_URL is empty, so API calls must use root-level paths.
export const APP_BASE_PATH = (import.meta.env.VITE_APP_BASE_PATH || '/project/routiq').replace(/\/+$/, '') || '/';
export const PRE_URL = '';
// Prefer the explicitly configured hosted backend when supplied.
// Fall back to same-origin Vercel rewrites when no backend URL is configured.
const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim() || '/api';
const configuredGovApiBase = import.meta.env.VITE_GOV_API_BASE_URL?.trim() || '/gov-api';

export const API_BASE_URL = configuredApiBase.replace(/\/+$/, '');
export const GOV_API_BASE_URL = configuredGovApiBase.replace(/\/+$/, '');