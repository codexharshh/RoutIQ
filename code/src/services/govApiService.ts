import type {
    GovUser,
    GovAuthCredentials,
    GovSignupData,
    RoadSegment,
    RoadSegmentForm
} from '../types';
import { GOV_API_BASE_URL } from '../config';

// Government API configuration - using separate database
const GOV_API_CONFIG = {
    baseURL: GOV_API_BASE_URL, // Uses PRE_URL from config
    headers: {
        'Content-Type': 'application/json',
    },
};

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

interface AuthResponse {
    user: unknown;
    access?: string;
    access_token?: string;
    refresh?: string;
    refresh_token?: string;
    tokens?: { access?: string; refresh?: string };
}

function isAuthResponse(value: unknown): value is AuthResponse {
    if (!isRecord(value) || !('user' in value)) return false;
    const tokens = isRecord(value.tokens) ? value.tokens : undefined;
    return Boolean(value.access || value.access_token || tokens?.access);
}

class GovApiService {
    private static instance: GovApiService;
    private baseURL: string;
    private authToken: string | null = null;
    private refreshToken: string | null = null;
    private readonly authTokenKey = 'gov_auth_token';
    private readonly refreshTokenKey = 'gov_refresh_token';
    private readonly userKey = 'gov_user';

    constructor() {
        this.baseURL = GOV_API_CONFIG.baseURL;
        this.hydrateAuthFromStorage();
    }

    static getInstance(): GovApiService {
        if (!GovApiService.instance) {
            GovApiService.instance = new GovApiService();
        }
        return GovApiService.instance;
    }

    private hydrateAuthFromStorage(): void {
        if (!this.authToken) {
            this.authToken = localStorage.getItem(this.authTokenKey);
        }
        if (!this.refreshToken) {
            this.refreshToken = localStorage.getItem(this.refreshTokenKey);
        }
    }

    private persistAuthSession(accessToken: string, refreshToken: string, user: GovUser): void {
        this.authToken = accessToken;
        this.refreshToken = refreshToken;
        localStorage.setItem(this.authTokenKey, accessToken);
        localStorage.setItem(this.refreshTokenKey, refreshToken);
        localStorage.setItem(this.userKey, JSON.stringify(user));
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<T> {
        this.hydrateAuthFromStorage();
        const url = `${this.baseURL}${endpoint}`;

        const config: RequestInit = {
            ...options,
            headers: {
                ...GOV_API_CONFIG.headers,
                ...(this.authToken && { Authorization: `Bearer ${this.authToken}` }),
                ...options.headers,
            },
        };

        console.log(`Making Government API request to: ${url}`);

        try {
            const response = await fetch(url, config);

            if (!response.ok) {
                const errorText = await response.text();
                console.error(`Government API request failed for ${endpoint}:`, {
                    status: response.status,
                    statusText: response.statusText,
                    error: errorText
                });
                throw new Error(`HTTP error! status: ${response.status} - ${errorText}`);
            }

            const data = await response.json();
            console.log(`Government API request successful for ${endpoint}:`, data);
            return data;
        } catch (error) {
            console.error(`Government API request failed for ${endpoint}:`, error);

            // Provide more helpful error messages
            if (error instanceof TypeError && error.message.includes('fetch')) {
                throw new Error(`Network error: Unable to connect to government backend. Please check if the service is running.`);
            }

            throw error;
        }
    }

    // Authentication methods
    async login(credentials: GovAuthCredentials): Promise<{ user: GovUser; access: string; refresh: string }> {
        const response: unknown = await this.request<unknown>('/auth/login/', {
            method: 'POST',
            body: JSON.stringify(credentials),
        });

        // Accept either a direct response or common API envelope formats.
        const responseRecord = isRecord(response) ? response : null;
        const responseData = responseRecord && isRecord(responseRecord.data) ? responseRecord.data : null;
        const candidates: unknown[] = [
            responseData && isRecord(responseData.data) ? responseData.data : undefined,
            responseData ?? undefined,
            responseRecord?.result,
            response,
        ];

        const authData = candidates.find(isAuthResponse);

        if (!authData) {
            const keys = response && typeof response === 'object'
                ? Object.keys(response).join(', ')
                : typeof response;

            throw new Error(
                `Login response did not contain a user and access token. Response fields: ${keys || 'none'}.`
            );
        }

        const access = authData.access ?? authData.access_token ?? authData.tokens?.access;
        const refresh = authData.refresh ?? authData.refresh_token ?? authData.tokens?.refresh;
        const user = authData.user as GovUser;

        if (!access || !refresh || !user) {
            const fields = Object.keys(authData).join(', ');
            throw new Error(
                `Login response is missing required authentication fields. Available fields: ${fields || 'none'}.`
            );
        }

        this.persistAuthSession(access, refresh, user);
        return { user, access, refresh };
    }

    async signup(data: GovSignupData): Promise<{ user: GovUser; message: string }> {
        const response = await this.request<{ data: { user: GovUser; message: string } }>('/auth/signup/', {
            method: 'POST',
            body: JSON.stringify(data),
        });

        return response.data;
    }

    async logout(): Promise<void> {
        try {
            await this.request('/auth/logout/', {
                method: 'POST',
            });
        } catch (error) {
            console.error('Logout error:', error);
        } finally {
            this.authToken = null;
            this.refreshToken = null;
            localStorage.removeItem(this.authTokenKey);
            localStorage.removeItem(this.refreshTokenKey);
            localStorage.removeItem(this.userKey);
        }
    }

    // Check if user is authenticated
    isAuthenticated(): boolean {
        this.hydrateAuthFromStorage();
        return Boolean(this.authToken);
    }

    // Get current user from localStorage
    getCurrentUser(): GovUser | null {
        const userStr = localStorage.getItem(this.userKey);
        return userStr ? JSON.parse(userStr) : null;
    }

    // Road segment methods
    async createRoadSegment(points: [number, number][], formData: RoadSegmentForm): Promise<RoadSegment> {
        const roadSegmentData = {
            points: points,
            contractor_id: formData.contractor_id,
            contractor_name: formData.contractor_name,
            contractor_email: formData.contractor_email,
            contractor_phone: formData.contractor_phone,
            road_creation_date: formData.road_creation_date,
            warranty_period: formData.warranty_period,
            money_sanctioned: formData.money_sanctioned,
        };

        return this.request<RoadSegment>('/road-segments/', {
            method: 'POST',
            body: JSON.stringify(roadSegmentData),
        });
    }

    async getRoadSegments(): Promise<RoadSegment[]> {
        return this.request<RoadSegment[]>('/road-segments/');
    }

    async updateRoadSegment(id: number, data: Partial<RoadSegment>): Promise<RoadSegment> {
        return this.request<RoadSegment>(`/road-segments/${id}/`, {
            method: 'PATCH',
            body: JSON.stringify(data),
        });
    }

    async deleteRoadSegment(id: number): Promise<void> {
        return this.request<void>(`/road-segments/${id}/`, {
            method: 'DELETE',
        });
    }

    // Verify token validity
    async verifyToken(): Promise<boolean> {
        this.hydrateAuthFromStorage();
        if (!this.authToken) return false;

        try {
            await this.request('/auth/verify/', {
                method: 'POST',
            });
            return true;
        } catch {
            this.logout();
            return false;
        }
    }
}

export const govApiService = GovApiService.getInstance();
