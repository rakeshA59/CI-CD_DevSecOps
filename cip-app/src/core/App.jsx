import { BrowserRouter as Router } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import AppRoutes from './pages';
import { ThemeProvider } from '@/shared/components/theme-provider';
import { TooltipProvider } from '@/shared/ui/tooltip';

export default function App() {
    return (
        <Router>
            <ThemeProvider defaultTheme="dark" storageKey="cip-ui-theme">
                <TooltipProvider delayDuration={200}>
                    <AppRoutes />
                </TooltipProvider>
                <Toaster
                    position="top-right"
                    toastOptions={{
                        duration: 3000,
                        style: { background: '#363636', color: '#fff' },
                        success: { style: { background: '#10B981', color: '#fff' } },
                        error: { style: { background: '#EF4444', color: '#fff' } },
                    }}
                />
            </ThemeProvider>
        </Router>
    );
}
