import path from 'path';
import { fileURLToPath } from 'url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// https://vite.dev/config/
export default defineConfig({
    plugins: [react(), tailwindcss()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
        },
    },
    server: {
        port: 5173,
        proxy: {
            // cip-api (FastAPI) – same /api prefix convention as sdlc-app
            '/api': {
                target: process.env.CIP_API_URL || 'http://127.0.0.1:8000',
                changeOrigin: true,
                rewrite: (p) => p.replace(/^\/api/, ''),
            },
        },
    },
});
