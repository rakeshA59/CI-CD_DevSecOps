import { Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from '@/shared/components/AppLayout';
import ProtectedRoute from '@/shared/components/ProtectedRoute';
import LoginPage from '@/features/auth/pages/LoginPage';
import PipelinePage from '@/features/pipeline/pages/PipelinePage';
import RunsPage from '@/features/runs/pages/RunsPage';
import DashboardPage from '@/features/dashboard/pages/DashboardPage';
import SettingsPage from '@/features/settings/pages/SettingsPage';

export default function AppRoutes() {
    return (
        <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<ProtectedRoute><AppLayout /></ProtectedRoute>}>
                <Route path="/" element={<PipelinePage />} />
                <Route path="/dashboard" element={<DashboardPage />} />
                <Route path="/runs" element={<RunsPage />} />
                <Route path="/runs/:taskId" element={<PipelinePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
        </Routes>
    );
}
