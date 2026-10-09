import { format } from 'date-fns';
import {
    Bot,
    Download,
    FileText,
    GitBranch,
    Route,
    Server,
    Square,
} from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent } from '@/shared/ui/card';
import StatusBadge from '@/shared/components/StatusBadge';
import { pdfUrl, testResultsUrl } from '../services/PipelineService';
import usePipelineStore from '../store/usePipelineStore';

/** Result of the run: overall, gates, PDF. */
export default function RunHeader() {
    const { run, live, taskId, stop } = usePipelineStore();
    const [stopping, setStopping] = useState(false);
    if (!run) return null;
    const canStop = live || run.status === 'RUNNING' || String(run.status).startsWith('WAITING');
    const onStop = async () => {
        if (
            !window.confirm(
                'Stop this pipeline? The current step is ended and its containers are removed.'
            )
        )
            return;
        setStopping(true);
        try {
            await stop();
        } finally {
            setStopping(false);
        }
    };
    const info = run.source_info || {};
    const report = run.report || {};
    const overall = live ? 'RUNNING' : run.overall || run.status;
    return (
        <Card className="gap-3 py-4">
            <CardContent className="space-y-3 px-4">
                <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge status={overall} className="px-3 py-1 text-sm" />
                    <h1 className="text-lg font-bold">
                        {run.pipeline_name || run.app_name || run.repo}
                    </h1>
                    {info.branch && (
                        <span className="text-muted-foreground flex items-center gap-1 text-xs">
                            <GitBranch className="size-3.5" /> {info.branch} @{' '}
                            {(info.commit || '').slice(0, 10)}
                        </span>
                    )}
                    <span className="text-muted-foreground flex items-center gap-1 text-xs">
                        <Bot className="size-3.5" /> {run.provider}
                    </span>
                    {run.created_at && (
                        <span className="text-muted-foreground text-xs">
                            {format(new Date(run.created_at), 'dd MMM yyyy, HH:mm')}
                        </span>
                    )}
                    {run.duration_s && (
                        <span className="text-muted-foreground text-xs">{run.duration_s}s</span>
                    )}
                    {run.mode === 'guided' && (
                        <span className="border-primary/40 text-primary flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">
                            <Route className="size-3.5" /> Pipeline
                        </span>
                    )}
                    <span className="ml-auto" />
                    {canStop && (
                        <Button
                            size="sm"
                            variant="destructive"
                            className="gap-2"
                            onClick={onStop}
                            disabled={stopping}
                        >
                            <Square className="size-3.5 fill-current" />{' '}
                            {stopping ? 'Stopping…' : 'Stop pipeline'}
                        </Button>
                    )}
                    {run.steps?.publish_tests?.status &&
                        run.steps.publish_tests.status !== 'skipped' && (
                            <Button asChild size="sm" variant="outline" className="gap-2">
                                <a
                                    href={testResultsUrl(taskId, 'test-report.html')}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    <FileText className="size-4" /> Test report
                                </a>
                            </Button>
                        )}
                    {report.pdf && (
                        <Button asChild size="sm" className="gap-2">
                            <a href={pdfUrl(taskId)} download>
                                <Download className="size-4" /> Download PDF report
                            </a>
                        </Button>
                    )}
                </div>
                {!live && run.app_urls?.length > 0 && (
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                        <Server className="size-4 text-emerald-500" />
                        <StatusBadge status="passed" label="App running" />
                        {run.app_urls.map((a) => (
                            <a
                                key={a.url}
                                href={a.url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-primary underline"
                            >
                                {a.name} {a.url}
                            </a>
                        ))}
                    </div>
                )}
                {!live && (
                    <div className="flex flex-wrap gap-2">
                        {Object.entries(run.gates || {}).map(([name, g]) => (
                            <StatusBadge
                                key={name}
                                status={g.blocked ? 'blocked' : g.passed ? 'passed' : 'failed'}
                                label={`${name} gate: ${g.blocked ? 'BLOCKED' : g.passed ? 'PASS' : 'FAIL'}`}
                            />
                        ))}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
