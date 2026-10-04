import { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import LiveLogsPanel from '../components/LiveLogsPanel';
import PipelineFlow from '../components/PipelineFlow';
import RunHeader from '../components/RunHeader';
import StartRunCard from '../components/StartRunCard';
import StepDetail from '../components/StepDetail';
import usePipelineStore from '../store/usePipelineStore';

export default function PipelinePage() {
    const { taskId } = useParams();
    const { open, reset } = usePipelineStore();

    useEffect(() => {
        if (taskId) open(taskId).catch((e) => toast.error(e.message));
        else reset();
        return () => reset();
    }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="mx-auto max-w-[1600px] space-y-4">
            {!taskId && <StartRunCard />}
            {taskId && <RunHeader />}
            <Card className="gap-3 py-4">
                <CardHeader className="px-4">
                    <CardTitle className="text-sm">Pipeline · derived by the planner agent · click a step for its details</CardTitle>
                </CardHeader>
                <CardContent className="px-4">
                    <PipelineFlow />
                </CardContent>
            </Card>
            {taskId && <StepDetail />}
            {taskId && <LiveLogsPanel />}
        </div>
    );
}
