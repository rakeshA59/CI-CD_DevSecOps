import { useEffect, useMemo, useRef, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Download, Search } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card, CardContent } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import usePipelineStore, { nodeToStep } from '../store/usePipelineStore';
import { useStages } from './PipelineFlow';

/**
 * Logs view (modelled on the SDLC app's Logs page): every event of the run, live, with tabs
 * (All · Errors · HITL · Active), search, a Stage filter and a Step filter inside the chosen stage, and export.
 */

const BADGE = {
    SYSTEM_START: 'bg-blue-500/15 text-blue-500',
    START: 'bg-blue-500/15 text-blue-500',
    PROGRESS: 'bg-blue-500/15 text-blue-500',
    COMMAND: 'bg-slate-500/15 text-slate-500 dark:text-slate-300',
    END: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    SYSTEM_END: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400',
    ERROR: 'bg-red-500/15 text-red-500',
    SKIPPED: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
    SYSTEM_PAUSE: 'bg-amber-500/15 text-amber-600 dark:text-amber-400',
};
const HITL_NODES = ['questionnaire_agent', 'security_review', 'approval_gate'];

/** step id → { stage, label } for every step of the run's stages (lanes: "label – component"). */
function stepIndex(stages) {
    const idx = {};
    stages.forEach((st) =>
        st.lanes.forEach((l) =>
            l.steps.forEach(([id, label]) => {
                idx[id] = { stage: st.title, label: l.lane ? `${label} – ${l.lane}` : label };
            })
        )
    );
    return idx;
}

/** Which step an event belongs to. The security agent logs "<scanner>: …" for each scanner. */
function eventStep(e, idx) {
    if (e.node === 'security_agent') {
        const scanner = /^([\w-]+):/.exec(e.message || '')?.[1];
        return idx[`scan.${scanner}`] ? `scan.${scanner}` : null;
    }
    const id = nodeToStep(e.node);
    return idx[id] ? id : null;
}

function eventStage(e, idx, step) {
    if (step) return idx[step].stage;
    if (e.node === 'security_agent') return 'Security';
    return e.node === 'SYSTEM' ? 'System' : null;
}

export default function LogsView() {
    const { events, live, nodeStatus, logFocus, taskId } = usePipelineStore();
    const stages = useStages();
    const idx = useMemo(() => stepIndex(stages), [JSON.stringify(stages)]); // eslint-disable-line react-hooks/exhaustive-deps
    const [tab, setTab] = useState('all');
    const [query, setQuery] = useState('');
    const [stage, setStage] = useState(logFocus?.stage || 'all');
    const [step, setStep] = useState(logFocus?.step || 'all');
    const bottom = useRef(null);

    useEffect(() => {
        if (logFocus) {
            setStage(logFocus.stage || 'all');
            setStep(logFocus.step || 'all');
        }
    }, [logFocus]);

    const rows = events.map((e) => {
        const s = eventStep(e, idx);
        return { e, step: s, stage: eventStage(e, idx, s) };
    });
    const running = new Set(
        Object.entries(nodeStatus)
            .filter(([, v]) => v === 'running')
            .map(([k]) => k)
    );
    const isError = (e) => e.status === 'ERROR' || /\b(FAIL|failed|error)\b/.test(e.message || '');
    const isHitl = (e) => e.status === 'SYSTEM_PAUSE' || HITL_NODES.includes(e.node);
    const tabs = [
        ['all', 'All', rows.length],
        ['errors', 'Errors', rows.filter((r) => isError(r.e)).length],
        ['hitl', 'HITL', rows.filter((r) => isHitl(r.e)).length],
        ['active', 'Active', rows.filter((r) => r.step && running.has(r.step)).length],
    ];
    const shown = rows.filter(({ e, step: s, stage: g }) => {
        if (tab === 'errors' && !isError(e)) return false;
        if (tab === 'hitl' && !isHitl(e)) return false;
        if (tab === 'active' && !(s && running.has(s))) return false;
        if (stage !== 'all' && g !== stage) return false;
        if (step !== 'all' && s !== step) return false;
        return !query || `${e.node} ${e.message}`.toLowerCase().includes(query.toLowerCase());
    });
    const stageSteps = stages
        .find((st) => st.title === stage)
        ?.lanes.flatMap((l) => l.steps.map(([id]) => id));

    useEffect(() => {
        if (live && tab === 'all') bottom.current?.scrollIntoView({ block: 'nearest' });
    }, [events.length, live, tab]);

    const exportLogs = () => {
        const blob = new Blob(
            [
                JSON.stringify(
                    shown.map((r) => r.e),
                    null,
                    2
                ),
            ],
            {
                type: 'application/json',
            }
        );
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `${taskId}-logs.json`;
        a.click();
        URL.revokeObjectURL(a.href);
    };

    return (
        <Card className="gap-3 py-3">
            <CardContent className="space-y-3 px-4">
                <div className="flex flex-wrap items-center gap-2">
                    <div className="flex items-center gap-1">
                        {tabs.map(([id, label, n]) => (
                            <button
                                key={id}
                                type="button"
                                onClick={() => setTab(id)}
                                className={cn(
                                    'flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm',
                                    tab === id
                                        ? 'border-primary text-primary'
                                        : 'text-muted-foreground border-transparent'
                                )}
                            >
                                {label}
                                {n > 0 && (
                                    <span className="bg-muted rounded-full px-1.5 text-[10px]">
                                        {n > 99 ? '99+' : n}
                                    </span>
                                )}
                            </button>
                        ))}
                        {live && (
                            <span className="ml-1 flex items-center gap-1 text-xs text-emerald-500">
                                <span className="size-2 animate-pulse rounded-full bg-emerald-500" />{' '}
                                live
                            </span>
                        )}
                    </div>
                    <div className="relative min-w-52 flex-1">
                        <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-4" />
                        <Input
                            className="h-9 pl-8"
                            placeholder="Search logs…"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                    </div>
                    <select
                        className="bg-background h-9 rounded-md border px-2 text-sm"
                        value={stage}
                        onChange={(e) => {
                            setStage(e.target.value);
                            setStep('all');
                        }}
                    >
                        <option value="all">All stages</option>
                        {[...stages.map((s) => s.title), 'System'].map((t) => (
                            <option key={t} value={t}>
                                {t}
                            </option>
                        ))}
                    </select>
                    {stageSteps?.length > 1 && (
                        <select
                            className="bg-background h-9 rounded-md border px-2 text-sm"
                            value={step}
                            onChange={(e) => setStep(e.target.value)}
                        >
                            <option value="all">All steps</option>
                            {stageSteps.map((id) => (
                                <option key={id} value={id}>
                                    {idx[id]?.label || id}
                                </option>
                            ))}
                        </select>
                    )}
                    <Button size="sm" variant="outline" className="h-9 gap-2" onClick={exportLogs}>
                        <Download className="size-4" /> Export
                    </Button>
                </div>

                <div className="max-h-[640px] space-y-2 overflow-auto pr-1">
                    {shown.length === 0 && (
                        <div className="text-muted-foreground py-10 text-center text-sm">
                            {events.length ? 'No logs match your filters' : 'Waiting for events…'}
                        </div>
                    )}
                    {shown.map(({ e, step: s }, i) => {
                        const data =
                            e.data && typeof e.data === 'object'
                                ? Object.entries(e.data).filter(
                                      ([, v]) =>
                                          ['string', 'number'].includes(typeof v) &&
                                          String(v).length < 200
                                  )
                                : [];
                        return (
                            <div key={e.id || i} className="bg-card rounded-lg border px-4 py-2.5">
                                <div className="flex items-start gap-3">
                                    <span className="text-muted-foreground w-10 shrink-0 font-mono text-xs">
                                        #{e.id || i + 1}
                                    </span>
                                    <span
                                        className={cn(
                                            'shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase',
                                            BADGE[e.status] || 'bg-muted'
                                        )}
                                    >
                                        {String(e.status).replace('SYSTEM_', '')}
                                    </span>
                                    <span
                                        className={cn(
                                            'min-w-0 flex-1 text-sm break-words whitespace-pre-wrap',
                                            e.status === 'COMMAND' && 'font-mono text-xs'
                                        )}
                                    >
                                        {e.message}
                                    </span>
                                    <span className="bg-muted shrink-0 rounded border px-2 py-0.5 text-[11px] font-medium">
                                        {s ? idx[s].label : e.node}
                                    </span>
                                    {e.ts && (
                                        <span
                                            className="text-muted-foreground w-24 shrink-0 text-right text-[11px]"
                                            title={new Date(e.ts * 1000).toLocaleString()}
                                        >
                                            {formatDistanceToNow(new Date(e.ts * 1000), {
                                                addSuffix: true,
                                            })}
                                        </span>
                                    )}
                                </div>
                                {data.length > 0 && (
                                    <div className="text-muted-foreground mt-1 pl-[3.25rem] text-xs">
                                        {data.map(([k, v]) => (
                                            <span key={k} className="mr-4">
                                                <span className="font-semibold">
                                                    {k.replaceAll('_', ' ')}:
                                                </span>{' '}
                                                {String(v)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                    <div ref={bottom} />
                </div>
            </CardContent>
        </Card>
    );
}
