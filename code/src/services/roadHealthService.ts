import type { RoadHealthData, ContractorMessage } from '../types';
import { API_CONFIG } from '../constants/api';
import { API_BASE_URL } from '../config';

class RoadHealthService {
    private static instance: RoadHealthService;
    private baseURL: string;

    constructor() {
        this.baseURL = API_CONFIG.baseURL;
    }

    static getInstance(): RoadHealthService {
        if (!RoadHealthService.instance) {
            RoadHealthService.instance = new RoadHealthService();
        }
        return RoadHealthService.instance;
    }

    // RoutIQ JWT auto-refresh v1
    private async refreshAccessToken(): Promise<string | null> {
        const tokenPairs = [
            { accessKey: 'gov_auth_token', refreshKey: 'gov_refresh_token' },
            { accessKey: 'routiq_access_token', refreshKey: 'routiq_refresh_token' },
        ];

        for (const pair of tokenPairs) {
            const refresh = localStorage.getItem(pair.refreshKey);
            if (!refresh) continue;

            try {
                const response = await fetch(`${API_BASE_URL.replace(/\\/+$/, '')}/v1/auth/token/refresh/`, {
                    method: 'POST',
                    headers: {
                        Accept: 'application/json',
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ refresh }),
                });

                if (!response.ok) continue;

                const payload = await response.json() as {
                    access?: unknown;
                    refresh?: unknown;
                };

                if (typeof payload.access !== 'string' || !payload.access) continue;

                localStorage.setItem(pair.accessKey, payload.access);

                if (typeof payload.refresh === 'string' && payload.refresh) {
                    localStorage.setItem(pair.refreshKey, payload.refresh);
                }

                return payload.access;
            } catch {
                // Try the other known RoutIQ token pair.
            }
        }

        return null;
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<T> {
        const url = `${this.baseURL}${endpoint}`;

        const sendRequest = async (token: string | null): Promise<Response> => {
            const headers = new Headers(options.headers);
            headers.set('Accept', 'application/json');

            if (options.body && !(options.body instanceof FormData)) {
                if (!headers.has('Content-Type')) {
                    headers.set('Content-Type', 'application/json');
                }
            }

            if (token) {
                headers.set('Authorization', `Bearer ${token}`);
            } else {
                headers.delete('Authorization');
            }

            return fetch(url, {
                ...options,
                headers,
                credentials: 'include',
            });
        };

        try {
            // The legacy road-health API uses the government token namespace;
            // RoutIQ account tokens are also supported as a fallback.
            let token =
                localStorage.getItem('gov_auth_token') ||
                localStorage.getItem('routiq_access_token');

            let response = await sendRequest(token);

            if (response.status === 401) {
                const refreshed = await this.refreshAccessToken();

                if (refreshed) {
                    token = refreshed;
                    response = await sendRequest(token);
                }

                // If the other token namespace has a usable session, try it once.
                if (response.status === 401) {
                    const alternativeTokens = [
                        localStorage.getItem('routiq_access_token'),
                        localStorage.getItem('gov_auth_token'),
                    ].filter((value): value is string => Boolean(value));

                    for (const alternative of alternativeTokens) {
                        if (alternative === token) continue;

                        const alternativeResponse = await sendRequest(alternative);
                        response = alternativeResponse;
                        token = alternative;

                        if (response.ok || response.status !== 401) break;
                    }
                }
            }

            const raw = await response.text();
            let payload: unknown = null;

            try {
                payload = raw ? JSON.parse(raw) : null;
            } catch {
                payload = raw;
            }

            if (!response.ok) {
                const detail = typeof payload === 'string'
                    ? payload
                    : JSON.stringify(payload ?? {});

                if (
                    response.status === 401 &&
                    /token_not_valid|token.{0,30}expired|expired.{0,30}token/i.test(detail)
                ) {
                    throw new Error(
                        'Your session expired and could not be refreshed. Please sign out, sign in again, and retry. If it persists, the backend refresh-token response must be checked.'
                    );
                }

                throw new Error(
                    `API Error: HTTP ${response.status} at ${endpoint} - ${detail}`
                );
            }

            return payload as T;
        } catch (error) {
            console.error(`API Request failed: ${url}`, error);
            throw error;
        }
    }

    // Get road health data for all segments
    async getRoadHealthData(): Promise<RoadHealthData[]> {
        return this.request<RoadHealthData[]>('/road-health/');
    }

    // Send message to contractor
    async sendContractorMessage(data: {
        segment_id: number;
        message: string;
        message_type: 'auto' | 'manual';
    }): Promise<ContractorMessage> {
        return this.request<ContractorMessage>('/contractor-messages/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    // Get contractor message history
    async getContractorMessages(segment_id?: number): Promise<ContractorMessage[]> {
        const endpoint = segment_id
            ? `/contractor-messages/?segment_id=${segment_id}`
            : '/contractor-messages/';
        return this.request<ContractorMessage[]>(endpoint);
    }

    // Update road health after data upload
    async updateRoadHealthAfterUpload(): Promise<void> {
        return this.request<void>('/road-health/update/', {
            method: 'POST',
        });
    }

    // Refresh road health from current road segments
    async refreshFromSegments(): Promise<{
        message: string;
        updated_count: number;
        analytics: Record<string, unknown>;
    }> {
        return this.request<{
            message: string;
            updated_count: number;
            analytics: Record<string, unknown>;
        }>('/road-health/refresh_from_segments/', {
            method: 'POST',
        });
    }

    // Update all road health data
    async updateAll(): Promise<{
        message: string;
        updated_count: number;
    }> {
        return this.request<{
            message: string;
            updated_count: number;
        }>('/road-health/update_all/', {
            method: 'POST',
        });
    }

    // Get road health color based on status
    getRoadHealthColor(status: RoadHealthData['health_status']): string {
        const colors = {
            critical: '#dc2626',    // Red: >200 potholes, under warranty
            warning: '#ea580c',     // Orange: >200 potholes, not under warranty
            caution: '#eab308',     // Yellow: <200 potholes, under warranty
            good: '#16a34a'         // Green: <200 potholes, not under warranty
        };
        return colors[status];
    }

    // Determine road health status
    determineHealthStatus(potholeCount: number, isUnderWarranty: boolean): RoadHealthData['health_status'] {
        if (potholeCount >= 200) {
            return isUnderWarranty ? 'critical' : 'warning';
        } else {
            return isUnderWarranty ? 'caution' : 'good';
        }
    }

    // Check if automatic messaging should be triggered
    shouldTriggerAutoMessage(status: RoadHealthData['health_status']): boolean {
        return status === 'critical' || status === 'warning';
    }
}

export const roadHealthService = RoadHealthService.getInstance();
