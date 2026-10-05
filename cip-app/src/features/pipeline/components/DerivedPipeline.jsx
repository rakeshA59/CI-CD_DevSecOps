import { CheckCircle2, MinusCircle, Route } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import usePipelineStore from '../store/usePipelineStore';

/** Guided flow – the pipeline the designer derived from the code + answers: stages, tools, MCP server, why / why not. */
export default function DerivedPipeline() {
    const { spec, run } = usePipelineStore();
    if (!spec?.length) return null;
    const answers = run?.answers || {};
    return (
        <Card className="gap-3 py-4">
            <CardHeader className="px-4">
                <CardTitle className="flex items-center gap-2 text-sm">
                    <Route className="text-primary size-4" /> Derived pipeline · from the code and
                    your answers
                </CardTitle>
                {Object.keys(answers).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                        {Object.entries(answers).map(([k, v]) => (
                            <span
                                key={k}
                                className="text-muted-foreground rounded-full border px-2 py-0.5 text-[11px]"
                            >
                                {k.replaceAll('_', ' ')}:{' '}
                                <b className="text-foreground">
                                    {Array.isArray(v) ? v.join(', ') : String(v)}
                                </b>
                            </span>
                        ))}
                    </div>
                )}
            </CardHeader>
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
                                <div className="text-muted-foreground mt-1 text-xs">{s.why}</div>
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
                                <div className="text-primary mt-1 text-[11px]">MCP: {s.mcp}</div>
                            </>
                        ) : (
                            <div className="text-muted-foreground mt-1 text-xs">
                                skipped – {s.reason}
                            </div>
                        )}
                    </div>
                ))}
            </CardContent>
        </Card>
    );
}
