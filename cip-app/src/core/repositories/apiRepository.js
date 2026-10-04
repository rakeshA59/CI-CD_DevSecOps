import axios from 'axios';

/**
 * API repository – one axios instance for cip-api (same pattern as sdlc-app's apiRepository).
 * Requests go to /api/... and the Vite dev server proxies them to FastAPI.
 */
export const API_BASE = import.meta.env.VITE_API_URL || '/api';

const http = axios.create({ baseURL: API_BASE, timeout: 60000 });

http.interceptors.response.use(
    (response) => response,
    (error) => {
        const message = error?.response?.data?.detail || error.message || 'Request failed';
        return Promise.reject(new Error(typeof message === 'string' ? message : JSON.stringify(message)));
    }
);

const apiRepository = {
    get: async (url, params) => (await http.get(url, { params })).data,
    post: async (url, body) => (await http.post(url, body)).data,
    put: async (url, body) => (await http.put(url, body)).data,
};

export default apiRepository;
