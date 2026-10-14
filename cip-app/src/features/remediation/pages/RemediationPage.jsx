import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import {
    ArrowRight,
    ChevronDown,
    ChevronRight,
    Clock,
    FileSearch,
    Loader2,
    Sparkles,
} from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent } from '@/shared/ui/card';
import {
    getDashboard,
    getRemediation,
    getRemediationHistory,
} from '@/features/pipeline/services/PipelineService';

export default function RemediationPage() {
    const [runs, setRuns] = useState([]);
    const [selectedRun, setSelectedRun] = useState('');
    const [loading, setLoading] = useState(false);

    // Recent specs
    const [recentSpecs, setRecentSpecs] = useState([]);
    const [recentOpen, setRecentOpen] = useState(false);
    const [loadingRecent, setLoadingRecent] = useState(false);

    useEffect(() => {
        getDashboard()
            .then((d) => setRuns(d.runs || []))
            .catch((e) => toast.error(e.message));
        // Auto-load recent specs on mount
        loadRecentSpecs();
    }, []);

    const generate = async () => {
        if (!selectedRun) return toast.error('Select a pipeline run first');
        setLoading(true);
        try {
            const res = await getRemediation(selectedRun);
            const name = res.pipeline_name || '';
            toast.success(`Spec generated for ${name || 'pipeline'}`);
            // Reset form so user can pick the next run
            setSelectedRun('');
            // Refresh recent specs & auto-open
            await loadRecentSpecs();
            setRecentOpen(true);
            // Open the detail page in a new tab (like dashboard run rows)
            window.open(`/remediation/${encodeURIComponent(res.task_id)}`, '_blank');
        } catch (e) {
            toast.error(e?.response?.data?.detail || e.message);
        } finally {
            setLoading(false);
        }
    };

    const loadRecentSpecs = async () => {
        setLoadingRecent(true);
        try {
            const res = await getRemediationHistory();
            setRecentSpecs(res.specs || []);
        } catch (e) {
            toast.error(e.message);
        } finally {
            setLoadingRecent(false);
        }
    };

    const toggleRecentSection = () => {
        if (!recentOpen && recentSpecs.length === 0) loadRecentSpecs();
        setRecentOpen((v) => !v);
    };

    const fmtDate = (iso) => {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleString(undefined, {
                month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
            });
        } catch { return iso; }
    };

    return (
        <div className="w-full space-y-4">
            <div className="flex items-center gap-2">
                <FileSearch className="text-primary size-5" />
                <h1 className="text-lg font-bold">Remediation Specs</h1>
            </div>

            {/* ─── Generate card ─── */}
            <Card className="gap-3 py-4">
                <CardContent className="flex flex-wrap items-end gap-3 px-4">
                    <div className="min-w-[280px] flex-1">
                        <label className="text-muted-foreground mb-1 block text-xs uppercase">
                            Select pipeline run
                        </label>
                        <select
                            value={selectedRun}
                            onChange={(e) => setSelectedRun(e.target.value)}
                            className="bg-background border-input w-full rounded-md border px-3 py-2 text-sm"
                        >
                            <option value="">— choose a run —</option>
                            {runs.map((r) => (
                                <option key={r.task_id} value={r.task_id}>
                                    {r.pipeline_name || r.app_name || r.repo} — {r.status}
                                </option>
                            ))}
                        </select>
                    </div>
                    <Button onClick={generate} disabled={loading || !selectedRun} className="gap-2">
                        {loading ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
                        {loading ? 'Analyzing…' : 'Generate'}
                    </Button>
                </CardContent>
            </Card>

            {loading && (
                <div className="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm">
                    <Loader2 className="size-5 animate-spin" />
                    Analyzing pipeline logs, findings and test results…
                </div>
            )}

            {/* ─── Recent Specs ─── */}
            <Card className="gap-0 py-0 overflow-hidden">
                <button
                    type="button"
                    onClick={toggleRecentSection}
                    className="hover:bg-muted/50 flex w-full items-center gap-3 px-4 py-3 text-left"
                >
                    {recentOpen ? (
                        <ChevronDown className="text-muted-foreground size-4 shrink-0" />
                    ) : (
                        <ChevronRight className="text-muted-foreground size-4 shrink-0" />
                    )}
                    <Clock className="text-primary size-4 shrink-0" />
                    <span className="text-sm font-bold">Recent Specs</span>
                    {recentSpecs.length > 0 && (
                        <span className="bg-muted text-muted-foreground rounded-full px-2 py-0.5 text-xs">
                            {recentSpecs.length}
                        </span>
                    )}
                </button>

                {recentOpen && (
                    <div className="border-t">
                        {loadingRecent && (
                            <div className="text-muted-foreground flex items-center gap-2 px-4 py-6 text-sm">
                                <Loader2 className="size-4 animate-spin" /> Loading…
                            </div>
                        )}

                        {!loadingRecent && recentSpecs.length === 0 && (
                            <div className="text-muted-foreground px-4 py-6 text-center text-sm">
                                No saved specs yet. Generate one above to get started.
                            </div>
                        )}

                        {!loadingRecent && recentSpecs.map((spec) => {
                            const href = `/remediation/${encodeURIComponent(spec.task_id)}`;
                            return (
                                <a
                                    key={spec.task_id}
                                    href={href}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="hover:bg-muted/30 flex w-full items-center gap-3 border-b px-5 py-3 text-left last:border-b-0 no-underline text-inherit"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-semibold">
                                            {spec.pipeline_name || spec.task_id}
                                        </div>
                                        <div className="text-muted-foreground text-xs mt-0.5">
                                            {spec.overall}
                                            {spec.generated_at && (
                                                <span className="ml-2">&middot; {fmtDate(spec.generated_at)}</span>
                                            )}
                                        </div>
                                    </div>
                                    <ArrowRight className="text-muted-foreground size-4 shrink-0" />
                                </a>
                            );
                        })}
                    </div>
                )}
            </Card>
        </div>
    );
}
