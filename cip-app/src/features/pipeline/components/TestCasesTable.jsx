import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table';
import StatusBadge from '@/shared/components/StatusBadge';
import { screenshotUrl } from '../services/PipelineService';

/** One labelled line of a test-case explanation. */
function Field({ label, children }) {
    if (!children || (Array.isArray(children) && !children.length)) return null;
    return (
        <div className="grid grid-cols-[110px_1fr] gap-2 text-xs">
            <div className="text-muted-foreground font-medium">{label}</div>
            <div className="whitespace-pre-wrap">{children}</div>
        </div>
    );
}

/** Plain explanation of a test case: what it is about, what it checks, how it ran, the result and why. */
function Explanation({ c, taskId }) {
    const how = Array.isArray(c.how) ? c.how : c.how ? [c.how] : [];
    return (
        <div className="bg-muted/40 space-y-1.5 rounded-md p-3">
            <Field label="What it is about">{c.purpose}</Field>
            <Field label="What it checks">{c.checks}</Field>
            {how.length > 0 && (
                <Field label="How">
                    <ol className="list-decimal pl-4">
                        {how.map((h, i) => (
                            <li key={i}>{h}</li>
                        ))}
                    </ol>
                </Field>
            )}
            <Field label="Expected">{c.expected}</Field>
            <Field label="Actual">{c.actual}</Field>
            <Field label={c.status === 'passed' ? 'Why it passed' : 'Why it did not pass'}>
                {c.why}
            </Field>
            {c.file && (
                <Field label="Test source">
                    <span className="font-mono">
                        {c.file}
                        {c.line ? `:${c.line}` : ''}
                    </span>
                </Field>
            )}
            {c.code && (
                <pre className="bg-background max-h-64 overflow-auto rounded border p-2 font-mono text-[11px]">
                    {c.code}
                </pre>
            )}
            {c.screenshot && taskId && (
                <a href={screenshotUrl(taskId, c.screenshot)} target="_blank" rel="noreferrer">
                    <img
                        src={screenshotUrl(taskId, c.screenshot)}
                        alt={`screenshot of ${c.id}`}
                        className="mt-1 max-h-72 rounded border"
                    />
                </a>
            )}
        </div>
    );
}

export default function TestCasesTable({ items, taskId }) {
    const [open, setOpen] = useState({});
    const toggle = (id) => setOpen((o) => ({ ...o, [id]: !o[id] }));
    return (
        <Table>
            <TableHeader>
                <TableRow>
                    <TableHead className="w-6" />
                    <TableHead>ID</TableHead>
                    <TableHead>Test case</TableHead>
                    <TableHead>Result</TableHead>
                    <TableHead>Message</TableHead>
                </TableRow>
            </TableHeader>
            <TableBody>
                {items.map((c, i) => {
                    const key = c.id || i;
                    const explained = c.purpose || c.how || c.screenshot;
                    return [
                        <TableRow
                            key={key}
                            className={explained ? 'cursor-pointer' : ''}
                            onClick={() => explained && toggle(key)}
                        >
                            <TableCell className="text-muted-foreground">
                                {explained &&
                                    (open[key] ? (
                                        <ChevronDown size={14} />
                                    ) : (
                                        <ChevronRight size={14} />
                                    ))}
                            </TableCell>
                            <TableCell className="font-mono text-xs">{c.id}</TableCell>
                            <TableCell className="whitespace-normal">
                                {c.name}
                                <div className="text-muted-foreground text-xs">
                                    {c.kind ? `${c.kind} test · ` : ''}
                                    {c.suite}{' '}
                                    {c.source === 'AI-generated' && '· written by the test agent'}
                                </div>
                            </TableCell>
                            <TableCell>
                                <StatusBadge status={c.status} />
                            </TableCell>
                            <TableCell className="text-muted-foreground max-w-md text-xs whitespace-pre-wrap">
                                {c.message?.slice(0, 600)}
                            </TableCell>
                        </TableRow>,
                        open[key] && (
                            <TableRow key={`${key}-x`}>
                                <TableCell />
                                <TableCell colSpan={4} className="whitespace-normal">
                                    <Explanation c={c} taskId={taskId} />
                                </TableCell>
                            </TableRow>
                        ),
                    ];
                })}
            </TableBody>
        </Table>
    );
}
