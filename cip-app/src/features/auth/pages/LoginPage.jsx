import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, ShieldCheck, Workflow } from 'lucide-react';
import { login } from '@/core/lib/auth';

export default function LoginPage() {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPwd, setShowPwd] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        // small delay for visual feedback
        setTimeout(() => {
            if (login(username, password)) {
                navigate('/', { replace: true });
            } else {
                setError('Invalid credentials. Please try again.');
                setLoading(false);
            }
        }, 400);
    };

    return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-[#0a0e1a] px-4">
            {/* Logo */}
            <div className="mb-8 flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-lg bg-blue-600/20">
                    <Workflow className="size-6 text-blue-400" />
                </div>
                <span className="text-xl font-bold tracking-tight text-white">
                    DevSecOps Platform
                </span>
            </div>

            {/* Card */}
            <div className="w-full max-w-md rounded-xl border border-[#1e2a3a] bg-[#0f1623] p-8 shadow-2xl">
                <h1 className="mb-1 text-2xl font-bold text-white">Sign in to your account</h1>
                <p className="mb-6 text-sm text-slate-400">
                    Enter your credentials to access the platform.
                </p>

                <form onSubmit={handleSubmit} className="space-y-5">
                    {/* Username */}
                    <div>
                        <label className="mb-1.5 block text-sm font-medium text-slate-200">
                            Email or Username
                        </label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            placeholder="name@company.com"
                            autoComplete="username"
                            required
                            className="h-11 w-full rounded-lg border border-[#1e2a3a] bg-[#0a0e1a] px-3.5 text-sm text-white
                                       placeholder:text-slate-500 transition-colors
                                       focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
                        />
                    </div>

                    {/* Password */}
                    <div>
                        <div className="mb-1.5 flex items-center justify-between">
                            <label className="text-sm font-medium text-slate-200">Password</label>
                            <button type="button" className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                                Forgot password?
                            </button>
                        </div>
                        <div className="relative">
                            <input
                                type={showPwd ? 'text' : 'password'}
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="••••••••"
                                autoComplete="current-password"
                                required
                                className="h-11 w-full rounded-lg border border-[#1e2a3a] bg-[#0a0e1a] px-3.5 pr-10 text-sm text-white
                                           placeholder:text-slate-500 transition-colors
                                           focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
                            />
                            <button
                                type="button"
                                onClick={() => setShowPwd(!showPwd)}
                                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                            >
                                {showPwd ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                            </button>
                        </div>
                    </div>

                    {/* Error */}
                    {error && (
                        <p className="rounded-md bg-red-500/10 border border-red-500/20 px-3 py-2 text-sm text-red-400">
                            {error}
                        </p>
                    )}

                    {/* Submit */}
                    <button
                        type="submit"
                        disabled={loading}
                        className="h-11 w-full rounded-lg bg-blue-600 text-sm font-semibold text-white
                                   transition-colors hover:bg-blue-500 disabled:opacity-60 disabled:cursor-not-allowed"
                    >
                        {loading ? 'Signing in...' : 'Sign in'}
                    </button>
                </form>

                <p className="mt-5 text-center text-sm text-slate-500">
                    Don&apos;t have an account?{' '}
                    <span className="text-blue-400">Contact support</span>
                </p>

                {/* Secure badge */}
                <div className="mt-5 flex items-center justify-center gap-1.5 text-xs text-slate-600">
                    <ShieldCheck className="size-3.5" />
                    Secure enterprise environment
                </div>
            </div>

            {/* Footer */}
            <p className="mt-8 text-xs text-slate-600">
                &copy; {new Date().getFullYear()} Agentic DevSecOps Platform. All rights reserved.
            </p>
        </div>
    );
}
