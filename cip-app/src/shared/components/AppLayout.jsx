import { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
    History,
    LayoutDashboard,
    LogOut,
    Moon,
    PanelLeftClose,
    PanelLeftOpen,
    Settings2,
    Sun,
    Workflow,
} from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { logout, getSession } from '@/core/lib/auth';
import { useTheme } from '@/shared/components/theme-provider';
import { Button } from '@/shared/ui/button';

const NAV = [
    { to: '/', label: 'Pipeline', icon: Workflow, end: true },
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/runs', label: 'Recent runs', icon: History },
    { to: '/settings', label: 'Settings', icon: Settings2 },
];

/** The sidebar remembers whether it is collapsed (per browser; works without storage too). */
function useCollapsed() {
    const [collapsed, setCollapsed] = useState(() => {
        try {
            return localStorage.getItem('devops.sidebar') === 'collapsed';
        } catch {
            return false;
        }
    });
    const toggle = () =>
        setCollapsed((c) => {
            try {
                localStorage.setItem('devops.sidebar', c ? 'open' : 'collapsed');
            } catch {
                /* storage not available */
            }
            return !c;
        });
    return [collapsed, toggle];
}

export default function AppLayout() {
    const { theme, setTheme } = useTheme();
    const [collapsed, toggle] = useCollapsed();
    const navigate = useNavigate();
    const session = getSession();
    const handleLogout = () => { logout(); navigate('/login', { replace: true }); };
    return (
        <div className="bg-background text-foreground flex min-h-screen">
            <aside
                className={cn(
                    'bg-sidebar sticky top-0 hidden h-screen shrink-0 flex-col border-r py-4 transition-[width] md:flex',
                    collapsed ? 'w-16 px-2' : 'w-60 px-3'
                )}
            >
                <div
                    className={cn('mb-6 flex items-center gap-2', collapsed ? 'flex-col' : 'px-2')}
                >
                    <div className="bg-primary/15 text-primary flex size-9 shrink-0 items-center justify-center rounded-lg">
                        <Workflow className="size-5" />
                    </div>
                    {!collapsed && (
                        <div>
                            <div className="text-sm font-bold">DevOps</div>
                            <div className="text-muted-foreground text-xs">Agentic CI/CD</div>
                        </div>
                    )}
                    <button
                        type="button"
                        onClick={toggle}
                        title={collapsed ? 'Expand the menu' : 'Collapse the menu'}
                        className={cn(
                            'text-muted-foreground hover:text-foreground rounded p-1',
                            !collapsed && 'ml-auto'
                        )}
                    >
                        {collapsed ? (
                            <PanelLeftOpen className="size-4" />
                        ) : (
                            <PanelLeftClose className="size-4" />
                        )}
                    </button>
                </div>
                <nav className="flex flex-col gap-1">
                    {NAV.map(({ to, label, icon: Icon, end }) => (
                        <NavLink
                            key={to}
                            to={to}
                            end={end}
                            title={collapsed ? label : undefined}
                            className={({ isActive }) =>
                                cn(
                                    'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex items-center gap-2 rounded-md py-2 text-sm font-medium',
                                    collapsed ? 'justify-center px-0' : 'px-3',
                                    isActive && 'bg-sidebar-accent text-sidebar-accent-foreground'
                                )
                            }
                        >
                            <Icon className="size-4 shrink-0" />
                            {!collapsed && label}
                        </NavLink>
                    ))}
                </nav>
                <div className="text-muted-foreground mt-auto px-2 text-xs">
                    {!collapsed && 'LangGraph agents · MCP tools'}
                    <Button
                        variant="ghost"
                        size="sm"
                        title={collapsed ? 'Switch theme' : undefined}
                        className={cn(
                            'mt-2 w-full gap-2',
                            collapsed ? 'justify-center px-0' : 'justify-start'
                        )}
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                    >
                        {theme === 'dark' ? (
                            <Sun className="size-4" />
                        ) : (
                            <Moon className="size-4" />
                        )}
                        {!collapsed && (theme === 'dark' ? 'Light mode' : 'Dark mode')}
                    </Button>
                    <Button
                        variant="ghost"
                        size="sm"
                        title={collapsed ? 'Sign out' : undefined}
                        className={cn(
                            'mt-1 w-full gap-2 text-red-400 hover:text-red-300 hover:bg-red-500/10',
                            collapsed ? 'justify-center px-0' : 'justify-start'
                        )}
                        onClick={handleLogout}
                    >
                        <LogOut className="size-4" />
                        {!collapsed && (session ? `Sign out (${session.username})` : 'Sign out')}
                    </Button>
                </div>
            </aside>
            <main className="min-w-0 flex-1 px-4 py-5 md:px-8">
                <div className="mb-4 flex gap-2 md:hidden">
                    {NAV.map(({ to, label }) => (
                        <NavLink key={to} to={to} className="rounded-md border px-3 py-1 text-sm">
                            {label}
                        </NavLink>
                    ))}
                </div>
                <Outlet />
            </main>
        </div>
    );
}
