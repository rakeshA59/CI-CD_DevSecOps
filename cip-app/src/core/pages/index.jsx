import { Navigate, Route, Routes } from 'react-router-dom';
import AppLayout from '@/shared/components/AppLayout';
import PipelinePage from '@/features/pipeline/pages/PipelinePage';
import RunsPage from '@/features/runs/pages/RunsPage';
import DashboardPage from '@/features/dashboard/pages/DashboardPage';
import SettingsPage from '@/features/settings/pages/SettingsPage';

export default function AppRoutes() {
    return (
        <Routes>
            <Route element={<AppLayout />}>
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
