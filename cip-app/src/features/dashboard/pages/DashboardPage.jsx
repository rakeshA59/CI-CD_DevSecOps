import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import toast from 'react-hot-toast';
import { ArrowUpRight, LayoutDashboard, RefreshCw } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table';
import StatusBadge from '@/shared/components/StatusBadge';
import { getDashboard } from '@/features/pipeline/services/PipelineService';

const SOLID = {
    passed: 'bg-emerald-500 border-emerald-500',
    warning: 'bg-amber-400 border-amber-400',
    skipped: 'bg-amber-200 border-amber-300 dark:bg-amber-900 dark:border-amber-700',
    failed: 'bg-red-500 border-red-500',
    error: 'bg-red-500 border-red-500',
    blocked: 'bg-red-200 border-red-400 border-dashed dark:bg-red-950',
    running: 'bg-primary border-primary',
};

// Stages in pipeline order (the `stage` of every step record)
const STAGES = [
    ['checkout', 'Checkout'],
    ['discovery', 'Discover'],
    ['security', 'Scan'],
    ['build', 'Build'],
    ['unit tests', 'Unit tests'],
    ['package', 'Package'],
    ['containerize', 'Image'],
    ['release', 'Release'],
    ['deploy', 'Deploy'],
    ['functional tests', 'Functional'],
    ['ui tests', 'UI tests'],
    ['test results', 'Publish'],
    ['approval', 'Approval'],
    ['report', 'Report'],
];

function Tile({ label, value, sub, tone }) {
    return (
        <div className="bg-card rounded-lg border p-4">
            <div className="text-muted-foreground text-xs uppercase">{label}</div>
            <div className={cn('mt-1 text-2xl font-bold', tone)}>{value}</div>
            {sub && <div className="text-muted-foreground text-xs">{sub}</div>}
        </div>
    );
}

/** Common dashboard: every run of every repository, stage by stage, with the final result. */
export default function DashboardPage() {
    const navigate = useNavigate();
    const [data, setData] = useState(null);
    const load = () =>
        getDashboard()
            .then(setData)
            .catch((e) => toast.error(e.message));
    useEffect(() => {
        load();
    }, []);
    const t = data?.totals || {};
    const runs = data?.runs || [];
    return (
        <div className="mx-auto max-w-[1600px] space-y-4">
            <div className="flex items-center gap-2">
                <LayoutDashboard className="text-primary size-5" />
                <h1 className="text-lg font-bold">DevOps dashboard</h1>
                <Button variant="ghost" size="icon" onClick={load} title="Refresh">
                    <RefreshCw className="size-4" />
                </Button>
            </div>
            <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
                <Tile
                    label="Runs"
                    value={t.runs ?? '–'}
                    sub={`${t.repositories ?? 0} repositories`}
                />
                <Tile label="Passed" value={t.passed ?? '–'} tone="text-emerald-500" />
                <Tile label="Failed" value={t.failed ?? '–'} tone="text-red-500" />
                <Tile
                    label="Waiting for you"
                    value={t.waiting ?? '–'}
                    sub="questionnaire / approval"
                    tone="text-amber-500"
                />
                <Tile
                    label="Tests passed"
                    value={t.tests_total ? `${t.tests_passed}/${t.tests_total}` : '–'}
                />
                <Tile
                    label="Open critical / high"
                    value={
                        t.open_findings_latest
                            ? `${t.open_findings_latest.CRITICAL} / ${t.open_findings_latest.HIGH}`
                            : '–'
                    }
                    sub="latest run per repository"
                    tone={t.open_findings_latest?.CRITICAL ? 'text-red-500' : ''}
                />
            </div>
            <Card className="gap-3 py-4">
                <CardHeader className="px-4">
                    <CardTitle className="text-sm">
                        Runs · every stage at a glance · click a run for its stage reports and final
                        report
                    </CardTitle>
                </CardHeader>
                <CardContent className="overflow-x-auto px-4">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Result</TableHead>
                                <TableHead>App</TableHead>
                                <TableHead>Repository</TableHead>
                                <TableHead>Started</TableHead>
                                {STAGES.map(([, label]) => (
                                    <TableHead key={label} className="px-1 text-center text-[11px]">
                                        {label}
                                    </TableHead>
                                ))}
                                <TableHead>Tests</TableHead>
                                <TableHead>Crit / High</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {runs.map((r) => (
                                <TableRow
                                    key={r.task_id}
                                    className="cursor-pointer"
                                    onClick={() => navigate(`/runs/${r.task_id}`)}
                                >
                                    <TableCell>
                                        <StatusBadge
                                            status={r.active ? 'RUNNING' : r.overall || r.status}
                                        />
                                    </TableCell>
                                    <TableCell className="text-xs">
                                        {r.app_urls?.length ? (
                                            <a
                                                href={r.app_urls[0].url}
                                                target="_blank"
                                                rel="noreferrer"
                                                title={r.app_urls
                                                    .map((a) => `${a.name} ${a.url}`)
                                                    .join('\n')}
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                <StatusBadge status="passed" label="Running" />
                                            </a>
                                        ) : (
                                            <span className="text-muted-foreground">–</span>
                                        )}
                                    </TableCell>
                                    <TableCell>
                                        <div className="flex items-center gap-1 font-medium">
                                            {r.repo}
                                            <a
                                                href={`/runs/${r.task_id}`}
                                                target="_blank"
                                                rel="noreferrer"
                                                title="Open this run in a new tab"
                                                className="text-muted-foreground hover:text-primary"
                                                onClick={(e) => e.stopPropagation()}
                                            >
                                                <ArrowUpRight className="size-4" />
                                            </a>
                                        </div>
                                        <div className="text-muted-foreground text-xs">
                                            {r.mode === 'guided' ? 'guided flow' : 'quick run'} ·{' '}
                                            {r.source_type}
                                        </div>
                                    </TableCell>
                                    <TableCell className="text-xs">
                                        {r.created_at
                                            ? format(new Date(r.created_at), 'dd MMM, HH:mm')
                                            : ''}
                                    </TableCell>
                                    {STAGES.map(([key, label]) => {
                                        const st = r.stage_summary?.[key];
                                        return (
                                            <TableCell key={key} className="px-1 text-center">
                                                <span
                                                    title={`${label}: ${st || 'not run'}`}
                                                    className={cn(
                                                        'inline-block size-4 rounded-sm border',
                                                        st
                                                            ? SOLID[st] || 'bg-muted'
                                                            : 'border-dashed opacity-40'
                                                    )}
                                                />
                                            </TableCell>
                                        );
                                    })}
                                    <TableCell className="text-xs">
                                        {r.tests_summary?.total
                                            ? `${r.tests_summary.passed}/${r.tests_summary.total}`
                                            : '–'}
                                    </TableCell>
                                    <TableCell className="text-xs">
                                        {r.findings_by_severity
                                            ? `${r.findings_by_severity.CRITICAL} / ${r.findings_by_severity.HIGH}`
                                            : '–'}
                                    </TableCell>
                                </TableRow>
                            ))}
                            {runs.length === 0 && (
                                <TableRow>
                                    <TableCell
                                        colSpan={STAGES.length + 6}
                                        className="text-muted-foreground text-center"
                                    >
                                        No runs yet.
                                    </TableCell>
                                </TableRow>
                            )}
                        </TableBody>
                    </Table>
                    <div className="text-muted-foreground mt-3 flex flex-wrap gap-3 text-xs">
                        {['passed', 'warning', 'skipped', 'failed', 'blocked'].map((s) => (
                            <span key={s} className="flex items-center gap-1">
                                <span
                                    className={cn(
                                        'inline-block size-3 rounded-sm border',
                                        SOLID[s]
                                    )}
                                />{' '}
                                {s}
                            </span>
                        ))}
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}
