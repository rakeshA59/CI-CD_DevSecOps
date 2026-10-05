import { NavLink, Outlet } from 'react-router-dom';
import { History, LayoutDashboard, Moon, Settings2, Sun, Workflow } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { useTheme } from '@/shared/components/theme-provider';
import { Button } from '@/shared/ui/button';

const NAV = [
    { to: '/', label: 'Pipeline', icon: Workflow, end: true },
    { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { to: '/runs', label: 'Recent runs', icon: History },
    { to: '/settings', label: 'LLM settings', icon: Settings2 },
];

export default function AppLayout() {
    const { theme, setTheme } = useTheme();
    return (
        <div className="bg-background text-foreground flex min-h-screen">
            <aside className="bg-sidebar sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r px-3 py-4 md:flex">
                <div className="mb-6 flex items-center gap-2 px-2">
                    <div className="bg-primary/15 text-primary flex size-9 items-center justify-center rounded-lg">
                        <Workflow className="size-5" />
                    </div>
                    <div>
                        <div className="text-sm font-bold">CIP</div>
                        <div className="text-muted-foreground text-xs">Agentic CI/CD</div>
                    </div>
                </div>
                <nav className="flex flex-col gap-1">
                    {NAV.map(({ to, label, icon: Icon, end }) => (
                        <NavLink
                            key={to}
                            to={to}
                            end={end}
                            className={({ isActive }) =>
                                cn(
                                    'text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium',
                                    isActive && 'bg-sidebar-accent text-sidebar-accent-foreground'
                                )
                            }
                        >
                            <Icon className="size-4" />
                            {label}
                        </NavLink>
                    ))}
                </nav>
                <div className="text-muted-foreground mt-auto px-2 text-xs">
                    LangGraph agents · MCP tools
                    <Button
                        variant="ghost"
                        size="sm"
                        className="mt-2 w-full justify-start gap-2"
                        onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                    >
                        {theme === 'dark' ? (
                            <Sun className="size-4" />
                        ) : (
                            <Moon className="size-4" />
                        )}
                        {theme === 'dark' ? 'Light mode' : 'Dark mode'}
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
