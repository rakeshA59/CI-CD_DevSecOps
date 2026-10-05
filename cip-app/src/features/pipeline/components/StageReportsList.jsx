import { FileText } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import StatusBadge from '@/shared/components/StatusBadge';
import usePipelineStore from '../store/usePipelineStore';
import StageReport from './StageReport';

/** Every stage report of the run, in order – the "publish each stage" view (final report = RunHeader + PDF). */
export default function StageReportsList() {
    const { run, live } = usePipelineStore();
    const steps = Object.values(run?.steps || {}).filter((s) => s.report);
    if (live || !steps.length) return null;
    return (
        <Card className="gap-3 py-4">
            <CardHeader className="px-4">
                <CardTitle className="flex items-center gap-2 text-sm">
                    <FileText className="size-4" /> Stage reports ({steps.length}) · what · where ·
                    how · why · result · suggestions · blockers
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 px-4">
                {steps.map((s) => (
                    <details
                        key={s.id}
                        className="rounded-md border"
                        open={['failed', 'error'].includes(s.status)}
                    >
                        <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-3 py-2 text-sm">
                            <StatusBadge status={s.status} />
                            <b>{s.name}</b>
                            {s.component && (
                                <span className="text-muted-foreground">{s.component}</span>
                            )}
                            <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
                                {s.message}
                            </span>
                            {s.report.blockers?.length > 0 && (
                                <StatusBadge
                                    status="failed"
                                    label={`${s.report.blockers.length} blocker(s)`}
                                />
                            )}
                        </summary>
                        <div className="px-3 pb-3">
                            <StageReport report={s.report} />
                        </div>
                    </details>
                ))}
            </CardContent>
        </Card>
    );
}
