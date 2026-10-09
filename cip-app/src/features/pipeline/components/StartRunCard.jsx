import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
    ArrowLeft,
    ArrowRight,
    Bot,
    Check,
    FolderGit2,
    GitBranch,
    Loader2,
    Play,
    Tag,
} from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import { Label } from '@/shared/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/ui/select';
import { getProviders } from '@/features/settings/services/LlmService';
import { startPipeline } from '../services/PipelineService';

const STEPS = [
    { label: 'Pipeline name', icon: Tag },
    { label: 'Repository', icon: FolderGit2 },
    { label: 'LLM provider', icon: Bot },
    { label: 'Start pipeline', icon: Play },
];

export default function StartRunCard() {
    const navigate = useNavigate();
    const [step, setStep] = useState(0);
    const [pipelineName, setPipelineName] = useState('');
    const [source, setSource] = useState('');
    const [branch, setBranch] = useState('');
    const [providers, setProviders] = useState([]);
    const [provider, setProvider] = useState('');
    const [starting, setStarting] = useState(false);

    useEffect(() => {
        getProviders()
            .then((res) => {
                setProviders(res.providers);
                setProvider(res.default);
            })
            .catch((e) => toast.error(`cip-api not reachable: ${e.message}`));
    }, []);

    const canNext = () => {
        if (step === 0) return pipelineName.trim().length > 0;
        if (step === 1) return source.trim().length > 0;
        if (step === 2) return !!provider;
        return true;
    };

    const next = () => {
        if (!canNext()) return;
        if (step < STEPS.length - 1) setStep(step + 1);
    };

    const prev = () => {
        if (step > 0) setStep(step - 1);
    };

    const start = async () => {
        if (!source.trim())
            return toast.error('Enter a GitHub URL, org/repo or a local folder path');
        setStarting(true);
        try {
            const res = await startPipeline(
                source.trim(),
                branch.trim(),
                provider,
                { pipeline_name: pipelineName.trim() },
                'guided'
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
                    <FolderGit2 className="text-primary size-5" /> New Pipeline Run
                </CardTitle>
                <CardDescription>
                    Configure your pipeline step by step. The planner agent reads the repository and
                    derives the stages; build, test, scan, container and deploy agents do the rest.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
                {/* Step indicator */}
                <div className="flex items-center gap-1">
                    {STEPS.map(({ label, icon: Icon }, i) => (
                        <div key={label} className="flex items-center gap-1">
                            <button
                                type="button"
                                onClick={() => i < step && setStep(i)}
                                disabled={i > step}
                                className={cn(
                                    'flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors',
                                    i === step
                                        ? 'bg-primary text-primary-foreground'
                                        : i < step
                                          ? 'bg-primary/15 text-primary cursor-pointer hover:bg-primary/25'
                                          : 'bg-muted text-muted-foreground cursor-default'
                                )}
                            >
                                {i < step ? (
                                    <Check className="size-3.5" />
                                ) : (
                                    <Icon className="size-3.5" />
                                )}
                                <span className="hidden sm:inline">{label}</span>
                                <span className="sm:hidden">{i + 1}</span>
                            </button>
                            {i < STEPS.length - 1 && (
                                <div
                                    className={cn(
                                        'mx-1 h-px w-6 sm:w-10',
                                        i < step ? 'bg-primary/40' : 'bg-muted'
                                    )}
                                />
                            )}
                        </div>
                    ))}
                </div>

                {/* Step 1: Pipeline name */}
                {step === 0 && (
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="pipeline-name" className="flex items-center gap-1.5">
                                <Tag className="size-4" /> Pipeline name
                            </Label>
                            <Input
                                id="pipeline-name"
                                placeholder="e.g. Customer Portal Release, API Gateway Build"
                                value={pipelineName}
                                onChange={(e) => setPipelineName(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && next()}
                                autoFocus
                                className="text-base"
                            />
                            <p className="text-muted-foreground text-xs">
                                Give this pipeline run a descriptive name to identify it later.
                            </p>
                        </div>
                    </div>
                )}

                {/* Step 2: Repository + Branch */}
                {step === 1 && (
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="source" className="flex items-center gap-1.5">
                                <FolderGit2 className="size-4" /> Repository or local path
                            </Label>
                            <Input
                                id="source"
                                placeholder="https://github.com/org/repo  or  C:\path\to\local\repo"
                                value={source}
                                onChange={(e) => setSource(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && next()}
                                autoFocus
                                className="border-primary/50 bg-primary/5 text-base font-medium placeholder:font-normal placeholder:text-muted-foreground"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="branch" className="flex items-center gap-1.5">
                                <GitBranch className="size-4" /> Branch (optional)
                            </Label>
                            <Input
                                id="branch"
                                placeholder="main"
                                value={branch}
                                onChange={(e) => setBranch(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && next()}
                            />
                        </div>
                    </div>
                )}

                {/* Step 3: LLM provider */}
                {step === 2 && (
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label className="flex items-center gap-1.5">
                                <Bot className="size-4" /> LLM provider for the agents
                            </Label>
                            <Select value={provider} onValueChange={setProvider}>
                                <SelectTrigger className="w-full max-w-md">
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
                                                {p.model ? ` \u00b7 ${p.model}` : ''}
                                                {!p.configured && p.id !== 'none'
                                                    ? ' (not configured)'
                                                    : ''}
                                            </SelectItem>
                                        ))}
                                </SelectContent>
                            </Select>
                            <p className="text-muted-foreground text-xs">
                                {selected?.id === 'none'
                                    ? 'Rules only: no agent reasoning \u2013 the planner uses file detection, failed builds are not investigated and no tests are written.'
                                    : 'The agents plan the pipeline, investigate failed builds, write tests when a repo has none, triage findings and explain the result.'}
                            </p>
                        </div>
                    </div>
                )}

                {/* Step 4: Summary + Start */}
                {step === 3 && (
                    <div className="space-y-3">
                        <div className="bg-muted/50 rounded-lg border p-4">
                            <h3 className="mb-3 text-sm font-semibold">Pipeline summary</h3>
                            <div className="grid gap-2 text-sm sm:grid-cols-2">
                                <div>
                                    <span className="text-muted-foreground">Name:</span>{' '}
                                    <span className="font-medium">{pipelineName}</span>
                                </div>
                                <div>
                                    <span className="text-muted-foreground">Repository:</span>{' '}
                                    <span className="font-medium">{source}</span>
                                </div>
                                {branch && (
                                    <div>
                                        <span className="text-muted-foreground">Branch:</span>{' '}
                                        <span className="font-medium">{branch}</span>
                                    </div>
                                )}
                                <div>
                                    <span className="text-muted-foreground">LLM:</span>{' '}
                                    <span className="font-medium">
                                        {selected?.label || provider}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <p className="text-muted-foreground text-xs">
                            The planner agent will read the repository, ask a questionnaire to
                            understand the stack, derive the pipeline stages, and then build, scan,
                            package, containerise, deploy, test, and publish results.
                        </p>
                    </div>
                )}

                {/* Navigation buttons */}
                <div className="flex items-center gap-2">
                    {step > 0 && (
                        <Button variant="outline" onClick={prev} className="gap-2">
                            <ArrowLeft className="size-4" /> Back
                        </Button>
                    )}
                    <span className="flex-1" />
                    {step < STEPS.length - 1 && (
                        <Button onClick={next} disabled={!canNext()} className="gap-2">
                            Next <ArrowRight className="size-4" />
                        </Button>
                    )}
                    {step === STEPS.length - 1 && (
                        <Button onClick={start} disabled={starting} className="gap-2">
                            {starting ? (
                                <Loader2 className="size-4 animate-spin" />
                            ) : (
                                <Play className="size-4" />
                            )}
                            Start pipeline
                        </Button>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
