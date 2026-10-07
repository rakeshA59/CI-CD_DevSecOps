import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Bot, FolderGit2, Loader2, Play, Route, ShieldCheck, Zap } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select';
import { Switch } from '@/shared/ui/switch';
import { getProviders } from '@/features/settings/services/LlmService';
import { getScanners, startPipeline } from '../services/PipelineService';
import usePipelineStore from '../store/usePipelineStore';

const OPTIONS = [
    ['run_tests', 'Unit tests'],
    ['containerize', 'Containerise'],
    ['deploy', 'Deploy to dev + functional tests'],
    ['continue_on_fail', 'Continue when a gate fails'],
    ['security_review', 'Pause for security review (HITL)'],
];

export default function StartRunCard() {
    const navigate = useNavigate();
    const [source, setSource] = useState('');
    const [branch, setBranch] = useState('');
    const [providers, setProviders] = useState([]);
    const [provider, setProvider] = useState('');
    const [options, setOptions] = useState({
        run_tests: true,
        containerize: true,
        deploy: true,
        continue_on_fail: true,
        security_review: true,
    });
    const [starting, setStarting] = useState(false);
    const [scanners, setScanners] = useState([]);
    const [picked, setPicked] = useState(null); // null = automatic (by the repo's languages)
    const [mode, setMode] = useState('quick'); // quick = today's fixed flow · guided = Architect flow (questionnaire → derived pipeline)

    useEffect(() => {
        getScanners()
            .then((res) => setScanners(res.scanners))
            .catch(() => {});
        getProviders()
            .then((res) => {
                setProviders(res.providers);
                setProvider(res.default);
            })
            .catch((e) => toast.error(`cip-api not reachable: ${e.message}`));
    }, []);

    const start = async () => {
        if (!source.trim())
            return toast.error('Enter a GitHub URL, org/repo or a local folder path');
        setStarting(true);
        try {
            const res = await startPipeline(
                source.trim(),
                branch.trim(),
                provider,
                { ...options, scanners: picked },
                mode
            );
            toast.success('Pipeline started');
            navigate(`/runs/${res.task_id}`);
        } catch (e) {
            toast.error(e.message);
        } finally {
            setStarting(false);
        }
    };

    const selected = providers.find((p) => p.id === provider);

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <FolderGit2 className="text-primary size-5" /> Run the pipeline
                </CardTitle>
                <CardDescription>
                    The planner agent reads the repository and derives the stages; build, test,
                    scan, container and deploy agents do the rest.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                    <div className="inline-flex rounded-lg border p-1">
                        {[
                            ['quick', 'Quick run', Zap],
                            ['guided', 'Guided DevOps flow', Route],
                        ].map(([key, label, Icon]) => (
                            <button
                                key={key}
                                type="button"
                                onClick={() => {
                                    setMode(key);
                                    usePipelineStore.setState({ draftMode: key }); // the preview below follows
                                }}
                                className={cn(
                                    'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm',
                                    mode === key
                                        ? 'bg-primary text-primary-foreground'
                                        : 'text-muted-foreground hover:bg-muted'
                                )}
                            >
                                <Icon className="size-4" /> {label}
                            </button>
                        ))}
                    </div>
                    <span className="text-muted-foreground text-xs">
                        {mode === 'quick'
                            ? 'The current flow: fixed stages, options below.'
                            : 'Source → the agent reads the stack and asks a questionnaire → the pipeline (stages + tools) is derived from your answers → build, scan, package, containerise, release to the local registry, deploy, test, publish results → your approval → UAT.'}
                    </span>
                </div>
                <div className="grid gap-3 md:grid-cols-[1fr_200px]">
                    <div className="space-y-1.5">
                        <Label htmlFor="source">Repository</Label>
                        <Input
                            id="source"
                            placeholder="https://github.com/org/repo · org/repo · C:\path\to\local\repo"
                            value={source}
                            onChange={(e) => setSource(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && start()}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="branch">Branch (optional)</Label>
                        <Input
                            id="branch"
                            placeholder="main"
                            value={branch}
                            onChange={(e) => setBranch(e.target.value)}
                        />
                    </div>
                </div>
                <div className="grid gap-3 md:grid-cols-[320px_1fr] md:items-end">
                    <div className="space-y-1.5">
                        <Label className="flex items-center gap-1.5">
                            <Bot className="size-4" /> LLM provider for the agents
                        </Label>
                        <Select value={provider} onValueChange={setProvider}>
                            <SelectTrigger className="w-full">
                                <SelectValue placeholder="Choose a provider" />
                            </SelectTrigger>
                            <SelectContent>
                                {providers
                                    .filter((p) => p.configured || p.id === 'none')
                                    .map((p) => (
                                        <SelectItem
                                            key={p.id}
                                            value={p.id}
                                            disabled={!p.configured && p.id !== 'none'}
                                        >
                                            {p.label}
                                            {p.model ? ` · ${p.model}` : ''}
                                            {!p.configured && p.id !== 'none'
                                                ? ' (not configured)'
                                                : ''}
                                        </SelectItem>
                                    ))}
                            </SelectContent>
                        </Select>
                    </div>
                    <p className="text-muted-foreground text-xs">
                        {selected?.id === 'none'
                            ? 'Rules only: no agent reasoning – the planner uses file detection, failed builds are not investigated and no tests are written.'
                            : 'The agents plan the pipeline, investigate failed builds, write tests when a repo has none, triage findings and explain the result.'}
                    </p>
                </div>
                {mode === 'quick' && (
                    <div className="flex flex-wrap gap-x-6 gap-y-3">
                        {OPTIONS.map(([key, label]) => (
                            <label
                                key={key}
                                className="flex cursor-pointer items-center gap-2 text-sm"
                            >
                                <Switch
                                    checked={options[key]}
                                    onCheckedChange={(v) => setOptions((o) => ({ ...o, [key]: v }))}
                                />
                                {label}
                            </label>
                        ))}
                    </div>
                )}
                {mode === 'quick' && (
                    <div className="space-y-2 rounded-md border p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <Label className="flex items-center gap-1.5">
                                <ShieldCheck className="size-4" /> Security scanners
                            </Label>
                            <label className="flex cursor-pointer items-center gap-2 text-xs">
                                <Switch
                                    checked={picked === null}
                                    onCheckedChange={(auto) =>
                                        setPicked(
                                            auto
                                                ? null
                                                : scanners
                                                      .filter((s) => s.installed && s.configured)
                                                      .map((s) => s.name)
                                        )
                                    }
                                />
                                Automatic – by the repo&apos;s languages
                            </label>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                            {scanners.map((s) => {
                                const on = picked === null ? null : picked.includes(s.name);
                                const note = !s.configured
                                    ? 'not configured'
                                    : !s.installed
                                      ? 'not installed – Docker fallback'
                                      : '';
                                return (
                                    <button
                                        key={s.name}
                                        type="button"
                                        disabled={picked === null}
                                        title={`${s.category} · runs by default when: ${s.default_when}${note ? ` · ${note}` : ''}`}
                                        onClick={() =>
                                            setPicked((p) =>
                                                p.includes(s.name)
                                                    ? p.filter((n) => n !== s.name)
                                                    : [...p, s.name]
                                            )
                                        }
                                        className={`rounded-full border px-2.5 py-1 text-xs ${on ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground'} ${note ? 'border-dashed' : ''} disabled:cursor-default`}
                                    >
                                        {s.label}
                                        {note && <span className="ml-1 opacity-70">({note})</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}
                <Button onClick={start} disabled={starting} className="gap-2">
                    {starting ? (
                        <Loader2 className="size-4 animate-spin" />
                    ) : (
                        <Play className="size-4" />
                    )}
                    {mode === 'guided' ? 'Start guided flow' : 'Run pipeline'}
                </Button>
            </CardContent>
        </Card>
    );
}
