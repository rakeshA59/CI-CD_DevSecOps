import { format } from 'date-fns';
import { Bot, Download, FolderGit2, GitBranch } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent } from '@/shared/ui/card';
import StatusBadge from '@/shared/components/StatusBadge';
import { pdfUrl } from '../services/PipelineService';
import usePipelineStore from '../store/usePipelineStore';

/** Result of the run: overall, gates, root cause, PDF. */
export default function RunHeader() {
    const { run, live, taskId } = usePipelineStore();
    if (!run) return null;
    const info = run.source_info || {};
    const report = run.report || {};
    const overall = live ? 'RUNNING' : run.overall || run.status;
    return (
        <Card className="gap-3 py-4">
            <CardContent className="space-y-3 px-4">
                <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge status={overall} className="px-3 py-1 text-sm" />
                    <h1 className="text-lg font-bold">{run.repo}</h1>
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <FolderGit2 className="size-3.5" /> {run.source_type} · {run.source}
                    </span>
                    {info.branch && (
                        <span className="flex items-center gap-1 text-xs text-muted-foreground">
                            <GitBranch className="size-3.5" /> {info.branch} @ {(info.commit || '').slice(0, 10)}
                        </span>
                    )}
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Bot className="size-3.5" /> {run.provider}
                    </span>
                    {run.created_at && <span className="text-xs text-muted-foreground">{format(new Date(run.created_at), 'dd MMM yyyy, HH:mm')}</span>}
                    {run.duration_s && <span className="text-xs text-muted-foreground">{run.duration_s}s</span>}
                    {report.pdf && (
                        <Button asChild size="sm" className="ml-auto gap-2">
                            <a href={pdfUrl(taskId)} download>
                                <Download className="size-4" /> Download PDF report
                            </a>
                        </Button>
                    )}
                </div>
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
                {!live && report.root_cause?.length > 0 && (
                    <div className="rounded-md border border-l-4 border-l-red-500 bg-red-500/5 p-3 text-sm">
                        <div className="mb-1 font-semibold">Why it did not pass – root cause first</div>
                        <ol className="list-decimal space-y-0.5 pl-5">
                            {report.root_cause.map((l) => (
                                <li key={l}>{l}</li>
                            ))}
                        </ol>
                        {report.explanation && (
                            <div className="mt-2 flex gap-2 text-muted-foreground">
                                <Bot className="mt-0.5 size-4 shrink-0" />
                                {report.explanation}
                            </div>
                        )}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}
