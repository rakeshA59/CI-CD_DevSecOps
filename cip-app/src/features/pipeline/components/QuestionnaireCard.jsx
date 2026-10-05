import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { ClipboardList, Loader2, Search, Send } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Switch } from '@/shared/ui/switch';
import usePipelineStore from '../store/usePipelineStore';

function Chip({ active, later, onClick, children }) {
    return (
        <button
            type="button"
            onClick={onClick}
            className={cn(
                'rounded-full border px-3 py-1 text-xs',
                active
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:bg-muted',
                later && 'border-dashed'
            )}
        >
            {children}
            {later && <span className="ml-1 opacity-70">(later)</span>}
        </button>
    );
}

/** Guided flow – the run waits here: what the agent learned from the code + the questions it could not answer. */
export default function QuestionnaireCard() {
    const { run, resume } = usePipelineStore();
    const pending = run?.pending;
    const [answers, setAnswers] = useState({});
    const [sending, setSending] = useState(false);

    useEffect(() => {
        if (pending?.questions)
            setAnswers(Object.fromEntries(pending.questions.map((q) => [q.id, q.value])));
    }, [pending]);

    if (run?.status !== 'WAITING_INPUT' || pending?.type !== 'questionnaire') return null;
    const d = pending.detected || {};
    const set = (id, v) => setAnswers((a) => ({ ...a, [id]: v }));

    const submit = async () => {
        setSending(true);
        try {
            await resume('answers', answers);
            toast.success('Answers sent – deriving the pipeline');
        } catch (e) {
            toast.error(e.message);
        } finally {
            setSending(false);
        }
    };

    return (
        <Card className="border-primary/40 gap-3 py-4">
            <CardHeader className="px-4">
                <CardTitle className="flex items-center gap-2">
                    <ClipboardList className="text-primary size-5" /> Questionnaire – the agent
                    needs a few answers
                </CardTitle>
                <CardDescription>
                    The pipeline is derived from what the code tells and from these answers. Values
                    are pre-filled from the code; options marked <i>later</i> are recorded and run
                    locally in this version.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 px-4">
                <div className="bg-muted/40 rounded-md border p-3 text-sm">
                    <div className="mb-1 flex items-center gap-1.5 font-semibold">
                        <Search className="size-4" /> What the agent found in the code
                    </div>
                    <div className="grid gap-x-6 gap-y-1 text-xs md:grid-cols-2">
                        {(d.components || []).map((c) => (
                            <div key={c.name}>
                                <b>{c.name}</b> – {c.language} {c.framework} ({c.kind})
                                {c.deployable ? ' · server' : ''}
                                {c.has_tests ? ' · has tests' : ' · no tests'}
                            </div>
                        ))}
                        <div>
                            Dockerfiles:{' '}
                            {d.dockerfiles?.length
                                ? d.dockerfiles.join(', ')
                                : 'none (CIP writes one)'}
                        </div>
                        <div>CI files: {d.ci_files?.length ? d.ci_files.join(', ') : 'none'}</div>
                        <div>
                            Kubernetes files: {d.kubernetes_files?.length || 0} · Terraform files:{' '}
                            {d.terraform_files?.length || 0}
                        </div>
                    </div>
                </div>
                <div className="space-y-3">
                    {pending.questions.map((q) => (
                        <div
                            key={q.id}
                            className="grid gap-1.5 md:grid-cols-[300px_1fr] md:items-start"
                        >
                            <div className="text-sm font-medium">
                                {q.label}
                                {q.note && (
                                    <div className="text-muted-foreground text-xs font-normal">
                                        {q.note}
                                    </div>
                                )}
                            </div>
                            <div className="flex flex-wrap gap-1.5">
                                {q.type === 'single' &&
                                    q.options.map((o) => (
                                        <Chip
                                            key={o.value}
                                            active={answers[q.id] === o.value}
                                            later={o.runs === false}
                                            onClick={() => set(q.id, o.value)}
                                        >
                                            {o.label}
                                        </Chip>
                                    ))}
                                {q.type === 'multi' &&
                                    q.options.map((o) => {
                                        const on = (answers[q.id] || []).includes(o.value);
                                        return (
                                            <Chip
                                                key={o.value}
                                                active={on}
                                                later={o.runs === false}
                                                onClick={() =>
                                                    set(
                                                        q.id,
                                                        on
                                                            ? answers[q.id].filter(
                                                                  (x) => x !== o.value
                                                              )
                                                            : [...(answers[q.id] || []), o.value]
                                                    )
                                                }
                                            >
                                                {o.label}
                                            </Chip>
                                        );
                                    })}
                                {q.type === 'bool' && (
                                    <Switch
                                        checked={!!answers[q.id]}
                                        onCheckedChange={(v) => set(q.id, v)}
                                    />
                                )}
                                {q.type === 'number' && (
                                    <Input
                                        type="number"
                                        min={q.min}
                                        max={q.max}
                                        className="h-8 w-24"
                                        value={answers[q.id] ?? ''}
                                        onChange={(e) => set(q.id, Number(e.target.value))}
                                    />
                                )}
                            </div>
                        </div>
                    ))}
                </div>
                <Button onClick={submit} disabled={sending} className="gap-2">
                    {sending ? (
                        <Loader2 className="size-4 animate-spin" />
                    ) : (
                        <Send className="size-4" />
                    )}{' '}
                    Derive the pipeline and run it
                </Button>
            </CardContent>
        </Card>
    );
}
