import { useEffect, useRef, useState } from 'react';
import { GitBranch, ScrollText, Workflow } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import ApprovalCard from '../components/ApprovalCard';
import DerivedPipeline from '../components/DerivedPipeline';
import PipelineGraph from '../components/graph/PipelineGraph';
import LiveLogsPanel from '../components/LiveLogsPanel';
import LogsView from '../components/LogsView';
import PipelineFlow from '../components/PipelineFlow';
import QuestionnaireCard from '../components/QuestionnaireCard';
import RunHeader from '../components/RunHeader';
import StartRunCard from '../components/StartRunCard';
import StageReportsList from '../components/StageReportsList';
import StepDetail from '../components/StepDetail';
import usePipelineStore from '../store/usePipelineStore';

const VIEWS = [
    ['pipeline', 'Pipeline', Workflow],
    ['graph', 'Graph', GitBranch],
    ['logs', 'Logs', ScrollText],
];

const ASKS = {
    questionnaire: 'answer the questionnaire',
    security_review: 'review the security reports (HITL)',
    approval: 'approve or reject the UAT deploy',
};

/** When the run pauses for a person: scroll to the question / approval card, highlight it and say so. */
function useHumanStep() {
    const run = usePipelineStore((s) => s.run);
    const ref = useRef(null);
    const seen = useRef('');
    const [flash, setFlash] = useState(false);
    const type = String(run?.status).startsWith('WAITING') ? run?.pending?.type : '';
    useEffect(() => {
        const key = type && `${run.task_id}:${type}`;
        if (!key || seen.current === key) return undefined;
        seen.current = key;
        // after the card has rendered (and the page height settled): bring its top into view. No cleanup: the
        // `seen` guard already makes this run once per pause, and a cleared timer would never be re-scheduled.
        setTimeout(() => {
            const el = ref.current;
            if (el)
                window.scrollTo({
                    top: el.getBoundingClientRect().top + window.scrollY - 16,
                    behavior: 'smooth',
                });
        }, 500);
        toast(`Action needed: ${ASKS[type] || 'your input'}`, { icon: '✋', duration: 6000 });
        setFlash(true);
        setTimeout(() => setFlash(false), 4000);
    }, [type, run?.task_id]);
    return [ref, flash, type];
}

/** Pipeline · Graph · Logs – three views of the same run. */
function ViewSwitch({ view, setView, logs }) {
    return (
        <div className="flex justify-center">
            <div className="bg-card flex items-center gap-1 rounded-xl border p-1">
                {VIEWS.map(([id, label, Icon]) => (
                    <button
                        key={id}
                        type="button"
                        onClick={() => setView(id)}
                        className={cn(
                            'flex items-center gap-2 rounded-lg px-4 py-1.5 text-sm',
                            view === id
                                ? 'bg-muted text-foreground font-semibold'
                                : 'text-muted-foreground hover:text-foreground'
                        )}
                    >
                        <Icon className="size-4" /> {label}
                        {id === 'logs' && logs > 0 && (
                            <span className="bg-primary/15 text-primary rounded-full px-1.5 text-[10px]">
                                {logs > 99 ? '99+' : logs}
                            </span>
                        )}
                    </button>
                ))}
            </div>
        </div>
    );
}

export default function PipelinePage() {
    const { taskId } = useParams();
    const { open, reset, view, setView, events } = usePipelineStore();
    const current = taskId ? view : 'pipeline';
    const [humanRef, flash, waitingFor] = useHumanStep();

    useEffect(() => {
        if (taskId) open(taskId).catch((e) => toast.error(e.message));
        else reset();
        return () => reset();
    }, [taskId]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div className="w-full space-y-4">
            {!taskId && <StartRunCard />}
            {taskId && <RunHeader />}
            {taskId && waitingFor && (
                <div
                    ref={humanRef}
                    className={cn(
                        'scroll-mt-4 space-y-4 rounded-xl transition-shadow',
                        flash && 'ring-primary animate-pulse ring-2'
                    )}
                >
                    <QuestionnaireCard />
                    <ApprovalCard />
                </div>
            )}
            {taskId && <DerivedPipeline />}
            {taskId && <ViewSwitch view={current} setView={setView} logs={events.length} />}
            {current === 'pipeline' && (
                <Card className="gap-3 py-4">
                    <CardHeader className="px-4">
                        <CardTitle className="text-sm">
                            Pipeline · derived by the planner agent · click a step for its details
                        </CardTitle>
                    </CardHeader>
                    <CardContent className="px-4">
                        <PipelineFlow />
                    </CardContent>
                </Card>
            )}
            {current === 'graph' && <PipelineGraph />}
            {current === 'logs' && <LogsView />}
            {taskId && current !== 'logs' && <StepDetail />}
            {taskId && current === 'pipeline' && <StageReportsList />}
            {taskId && current === 'pipeline' && <LiveLogsPanel />}
        </div>
    );
}
