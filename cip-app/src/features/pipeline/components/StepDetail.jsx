import { Bot, X } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/shared/ui/tabs';
import StatusBadge from '@/shared/components/StatusBadge';
import usePipelineStore, { nodeToStep } from '../store/usePipelineStore';
import StageReport from './StageReport';
import TestCasesTable from './TestCasesTable';

function Items({ rec, taskId }) {
    const items = rec.items || [];
    if (rec.item_type === 'tests') return <TestCasesTable items={items} taskId={taskId} />;
    if (rec.item_type === 'findings')
        return (
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>Severity</TableHead>
                        <TableHead>Finding</TableHead>
                        <TableHead>Where</TableHead>
                        <TableHead>Fix</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {items.map((f, i) => (
                        <TableRow key={i}>
                            <TableCell>
                                <StatusBadge
                                    status={
                                        ['CRITICAL', 'HIGH'].includes(f.severity)
                                            ? 'failed'
                                            : 'warning'
                                    }
                                    label={f.severity}
                                />
                            </TableCell>
                            <TableCell className="whitespace-normal">
                                {f.title}
                                {f.triage && (
                                    <div className="text-muted-foreground mt-1 text-xs">
                                        🤖 {f.triage.verdict}: {f.triage.explanation}
                                    </div>
                                )}
                            </TableCell>
                            <TableCell className="font-mono text-xs">
                                {f.file}
                                {f.line ? `:${f.line}` : ''}
                            </TableCell>
                            <TableCell className="max-w-xs text-xs whitespace-normal">
                                {f.triage?.fix || f.recommendation}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        );
    if (rec.item_type === 'checks')
        return (
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead>Check</TableHead>
                        <TableHead>Actual</TableHead>
                        <TableHead>Required</TableHead>
                        <TableHead>Result</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {items.map((c) => (
                        <TableRow key={c.name}>
                            <TableCell>{c.name}</TableCell>
                            <TableCell>{String(c.actual)}</TableCell>
                            <TableCell>{c.required}</TableCell>
                            <TableCell>
                                <StatusBadge
                                    status={c.passed ? 'passed' : 'failed'}
                                    label={c.passed ? 'PASS' : 'FAIL'}
                                />
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        );
    if (rec.item_type === 'components')
        return (
            <div className="grid gap-3 md:grid-cols-2">
                {items.map((c) => (
                    <div key={c.name} className="rounded-md border p-3 text-sm">
                        <div className="font-semibold">
                            {c.name}{' '}
                            <span className="text-muted-foreground text-xs">({c.path})</span>
                        </div>
                        <div className="text-muted-foreground text-xs">
                            {c.language} · {c.framework} · {c.kind}{' '}
                            {c.deployable && `· port ${c.port}`}
                        </div>
                        <div className="mt-2 font-mono text-xs">
                            build: {c.build_commands.join(' && ') || '–'}
                        </div>
                        <div className="font-mono text-xs">test: {c.test_command || '–'}</div>
                        {c.reasoning && (
                            <div className="text-muted-foreground mt-1 text-xs">
                                🤖 {c.reasoning}
                            </div>
                        )}
                    </div>
                ))}
            </div>
        );
    if (rec.item_type === 'services')
        return (
            <div className="space-y-2">
                {items.map((s) => (
                    <div key={s.component} className="rounded-md border p-3 text-sm">
                        <StatusBadge status={s.status} /> <b>{s.component}</b>{' '}
                        <a
                            className="text-primary underline"
                            href={s.url}
                            target="_blank"
                            rel="noreferrer"
                        >
                            {s.url}
                        </a>{' '}
                        <span className="text-muted-foreground text-xs">{s.message}</span>
                        {s.logs_tail && (
                            <pre className="bg-muted mt-2 max-h-48 overflow-auto rounded p-2 text-xs">
                                {s.logs_tail}
                            </pre>
                        )}
                    </div>
                ))}
            </div>
        );
    return <div className="text-muted-foreground text-sm">Nothing to list for this step.</div>;
}

export default function StepDetail() {
    const { run, events, selectedStep, selectStep, taskId } = usePipelineStore();
    if (!selectedStep) return null;
    const rec = run?.steps?.[selectedStep];
    const stepEvents = events.filter(
        (e) => nodeToStep(e.node) === selectedStep || e.node === selectedStep
    );
    return (
        <Card className="gap-3 py-4">
            <CardHeader className="flex flex-row items-start justify-between gap-3 px-4">
                <div>
                    <CardTitle className="flex items-center gap-2">
                        {rec && <StatusBadge status={rec.status} />} {rec?.name || selectedStep}
                        {rec?.component && (
                            <span className="text-muted-foreground text-sm font-normal">
                                {rec.component}
                            </span>
                        )}
                        {rec?.duration_s ? (
                            <span className="text-muted-foreground text-xs font-normal">
                                {rec.duration_s}s
                            </span>
                        ) : null}
                    </CardTitle>
                    {rec?.message && (
                        <p className="text-muted-foreground mt-1 text-sm whitespace-pre-wrap">
                            {rec.message}
                        </p>
                    )}
                </div>
                <Button variant="ghost" size="icon" onClick={() => selectStep(null)}>
                    <X className="size-4" />
                </Button>
            </CardHeader>
            <CardContent className="px-4">
                {!rec ? (
                    <div className="text-muted-foreground text-sm">
                        {stepEvents.length
                            ? 'Running – details appear when the run finishes. Live events:'
                            : 'This step has not run yet.'}
                        <div className="mt-2 font-mono text-xs">
                            {stepEvents.slice(-30).map((e) => (
                                <div key={e.id}>{e.message}</div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <Tabs
                        key={rec.id}
                        defaultValue={
                            rec.report ? 'report' : rec.items?.length ? 'items' : 'summary'
                        }
                    >
                        <TabsList className="flex-wrap">
                            {rec.report && <TabsTrigger value="report">Stage report</TabsTrigger>}
                            <TabsTrigger value="summary">Summary</TabsTrigger>
                            {rec.items?.length > 0 && (
                                <TabsTrigger value="items">
                                    Results ({rec.items.length})
                                </TabsTrigger>
                            )}
                            <TabsTrigger value="commands">
                                Commands ({rec.commands?.length || 0})
                            </TabsTrigger>
                            {rec.explanation && (
                                <TabsTrigger value="agent">Agent reasoning</TabsTrigger>
                            )}
                            <TabsTrigger value="events">Events ({stepEvents.length})</TabsTrigger>
                        </TabsList>
                        <TabsContent value="report" className="pt-3">
                            <StageReport report={rec.report} />
                        </TabsContent>
                        <TabsContent value="summary" className="pt-3">
                            <dl className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-3">
                                {Object.entries(rec.summary || {})
                                    .filter(
                                        ([, v]) => v !== null && v !== '' && typeof v !== 'object'
                                    )
                                    .map(([k, v]) => (
                                        <div key={k}>
                                            <dt className="text-muted-foreground text-xs uppercase">
                                                {k.replaceAll('_', ' ')}
                                            </dt>
                                            <dd className="font-medium break-words">{String(v)}</dd>
                                        </div>
                                    ))}
                            </dl>
                        </TabsContent>
                        <TabsContent value="items" className="max-h-[480px] overflow-auto pt-3">
                            <Items rec={rec} taskId={taskId} />
                        </TabsContent>
                        <TabsContent value="commands" className="space-y-2 pt-3">
                            {(rec.commands || []).map((c, i) => (
                                <details
                                    key={i}
                                    className="rounded-md border p-2"
                                    open={c.exit_code !== 0}
                                >
                                    <summary className="cursor-pointer font-mono text-xs">
                                        <StatusBadge
                                            status={c.exit_code === 0 ? 'passed' : 'failed'}
                                            label={`exit ${c.exit_code}`}
                                        />{' '}
                                        {c.command}{' '}
                                        <span className="text-muted-foreground">
                                            in {c.folder} · {c.seconds}s
                                        </span>
                                    </summary>
                                    <pre className="bg-muted mt-2 max-h-72 overflow-auto rounded p-2 text-xs whitespace-pre-wrap">
                                        {c.output_tail}
                                    </pre>
                                </details>
                            ))}
                            {!rec.commands?.length && (
                                <div className="text-muted-foreground text-sm">
                                    No commands for this step.
                                </div>
                            )}
                        </TabsContent>
                        <TabsContent value="agent" className="pt-3">
                            <div className="bg-muted/40 flex gap-2 rounded-md border p-3 text-sm whitespace-pre-wrap">
                                <Bot className="text-primary mt-0.5 size-4 shrink-0" />
                                {rec.explanation}
                            </div>
                        </TabsContent>
                        <TabsContent value="events" className="pt-3 font-mono text-xs">
                            {stepEvents.map((e) => (
                                <div key={e.id}>{e.message}</div>
                            ))}
                        </TabsContent>
                    </Tabs>
                )}
            </CardContent>
        </Card>
    );
}
