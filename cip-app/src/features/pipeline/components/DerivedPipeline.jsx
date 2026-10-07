import { useState } from 'react';
import { CheckCircle2, ChevronDown, ChevronRight, MinusCircle, Route } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import usePipelineStore from '../store/usePipelineStore';

/** Guided flow – the pipeline the designer derived from the code + answers: stages, tools, MCP server, why / why not. */
const KEY_ANSWERS = ['deploy_as', 'tests', 'uat'];

/** Collapsible: open while the run is live or waiting for you, collapsed for a finished run. */
export default function DerivedPipeline() {
    const { spec, run } = usePipelineStore();
    if (!spec?.length) return null;
    return <DerivedPipelineCard key={run?.task_id} spec={spec} run={run} />;
}

function Chips({ entries }) {
    return entries.map(([k, v]) => (
        <span
            key={k}
            className="text-muted-foreground rounded-full border px-2 py-0.5 text-[11px] font-normal"
        >
            {k.replaceAll('_', ' ')}:{' '}
            <b className="text-foreground">{Array.isArray(v) ? v.join(', ') : String(v)}</b>
        </span>
    ));
}

function DerivedPipelineCard({ spec, run }) {
    const live = ['RUNNING', 'WAITING_INPUT', 'WAITING_APPROVAL'].includes(run?.status);
    const [open, setOpen] = useState(live);
    const answers = run?.answers || {};
    const used = spec.filter((s) => s.included).length;
    return (
        <Card className="gap-3 py-4">
            <CardHeader className="px-4">
                <button
                    type="button"
                    onClick={() => setOpen((o) => !o)}
                    className="flex w-full flex-wrap items-center gap-2 text-left"
                >
                    {open ? (
                        <ChevronDown className="size-4" />
                    ) : (
                        <ChevronRight className="size-4" />
                    )}
                    <CardTitle className="flex items-center gap-2 text-sm">
                        <Route className="text-primary size-4" /> Derived pipeline · from the code
                        and your answers
                    </CardTitle>
                    <span className="text-muted-foreground text-xs">
                        {used} stages{spec.length > used ? ` · ${spec.length - used} left out` : ''}
                    </span>
                    {!open && (
                        <Chips
                            entries={Object.entries(answers).filter(([k]) =>
                                KEY_ANSWERS.includes(k)
                            )}
                        />
                    )}
                </button>
                {open && Object.keys(answers).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                        <Chips entries={Object.entries(answers)} />
                    </div>
                )}
            </CardHeader>
            {open && (
                <CardContent className="grid gap-2 px-4 md:grid-cols-2 xl:grid-cols-3">
                    {spec.map((s, i) => (
                        <div
                            key={s.id}
                            className={`rounded-md border p-3 text-sm ${s.included ? '' : 'border-dashed opacity-60'}`}
                        >
                            <div className="flex items-center gap-2 font-semibold">
                                {s.included ? (
                                    <CheckCircle2 className="size-4 text-emerald-500" />
                                ) : (
                                    <MinusCircle className="size-4 text-amber-500" />
                                )}
                                {i + 1}. {s.title}
                            </div>
                            {s.included ? (
                                <>
                                    <div className="text-muted-foreground mt-1 text-xs">
                                        {s.why}
                                    </div>
                                    <div className="mt-2 flex flex-wrap gap-1">
                                        {s.tools.slice(0, 12).map((t) => (
                                            <span
                                                key={t}
                                                className="bg-muted rounded px-1.5 py-0.5 text-[11px]"
                                            >
                                                {t}
                                            </span>
                                        ))}
                                    </div>
                                    <div className="text-primary mt-1 text-[11px]">
                                        MCP: {s.mcp}
                                    </div>
                                </>
                            ) : (
                                <div className="text-muted-foreground mt-1 text-xs">
                                    skipped – {s.reason}
                                </div>
                            )}
                        </div>
                    ))}
                </CardContent>
            )}
        </Card>
    );
}
