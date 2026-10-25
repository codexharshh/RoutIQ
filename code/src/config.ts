// RoutIQ application and backend route configuration.
// Django PRE_URL is empty, so API calls must use root-level paths.
export const APP_BASE_PATH = (import.meta.env.VITE_APP_BASE_PATH || '/project/routiq').replace(/\/+$/, '') || '/';
export const PRE_URL = '';
export const API_BASE_URL = '/api';
export const GOV_API_BASE_URL = '/gov-api';