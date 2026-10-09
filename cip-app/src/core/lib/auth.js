/** Simple localStorage auth gate – demo only, not real security. */

const SESSION_KEY = 'cip.session';

/** Default demo credentials. */
export const DEMO_USER = { username: 'admin', password: '1234', role: 'admin' };

export function login(username, password) {
    if (username === DEMO_USER.username && password === DEMO_USER.password) {
        const session = { username, role: DEMO_USER.role, loggedInAt: Date.now() };
        try { localStorage.setItem(SESSION_KEY, JSON.stringify(session)); } catch { /* noop */ }
        return true;
    }
    return false;
}

export function getSession() {
    try {
        const raw = localStorage.getItem(SESSION_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch { return null; }
}

export function isLoggedIn() {
    return !!getSession();
}

export function logout() {
    try { localStorage.removeItem(SESSION_KEY); } catch { /* noop */ }
}
