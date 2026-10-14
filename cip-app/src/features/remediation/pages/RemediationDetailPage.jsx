import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
    AlertTriangle,
    ArrowLeft,
    ChevronDown,
    ChevronRight,
    Loader2,
    Search,
    ShieldAlert,
    Wrench,
} from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Button } from '@/shared/ui/button';
import { Card } from '@/shared/ui/card';
import { getRemediationSaved } from '@/features/pipeline/services/PipelineService';

/** Render markdown-ish text with bold, code, bullets, and code blocks. */
function RenderBody({ text }) {
    if (!text) return null;
    const lines = text.split('\n');
    const elements = [];
    let inCodeBlock = false;
    let codeLines = [];
    let codeKey = 0;

    for (let i = 0; i < lines.length; i++) {
        const trimmed = lines[i].trim();
        if (trimmed.startsWith('```')) {
            if (inCodeBlock) {
                elements.push(
                    <pre key={`code-${codeKey++}`} className="bg-muted/60 my-2 overflow-x-auto rounded-md border px-3 py-2 text-xs leading-relaxed">
                        <code>{codeLines.join('\n')}</code>
                    </pre>
                );
                codeLines = [];
                inCodeBlock = false;
            } else {
                inCodeBlock = true;
            }
            continue;
        }
        if (inCodeBlock) { codeLines.push(lines[i]); continue; }
        if (!trimmed) { elements.push(<div key={i} className="h-1.5" />); continue; }
        if (trimmed.startsWith('####')) continue;
        if (trimmed === '---') continue;

        const rendered = trimmed
            .replace(/\*\*\[([A-Z]+)\]\*\*/g, '<span class="remediation-severity remediation-sev-$1">[$1]</span>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/`(.+?)`/g, '<code class="bg-muted rounded px-1 py-0.5 text-xs font-mono">$1</code>');
        const isBullet = trimmed.startsWith('- ') || trimmed.startsWith('* ');
        const isNumbered = /^\d+\.\s/.test(trimmed);
        elements.push(
            <div key={i} className={cn('text-sm leading-relaxed', isBullet && 'pl-4', isNumbered && 'pl-4')}
                dangerouslySetInnerHTML={{ __html: rendered }} />
        );
    }
    if (inCodeBlock && codeLines.length > 0) {
        elements.push(
            <pre key={`code-${codeKey}`} className="bg-muted/60 my-2 overflow-x-auto rounded-md border px-3 py-2 text-xs leading-relaxed">
                <code>{codeLines.join('\n')}</code>
            </pre>
        );
    }
    return <div className="space-y-0.5">{elements}</div>;
}

function SubSection({ icon: Icon, title, color, text }) {
    if (!text) return null;
    const borderColor = { red: 'border-l-red-500', amber: 'border-l-amber-500', green: 'border-l-emerald-500' }[color] || 'border-l-border';
    return (
        <div className={cn('border-l-[3px] rounded-r-md bg-muted/20 pl-4 pr-3 py-3 mb-3', borderColor)}>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <Icon className="size-3.5" /> {title}
            </div>
            <RenderBody text={text} />
        </div>
    );
}

/** Parse a scanner block within a stage into { name, issues, rootCause, remediation } */
function parseScannerBlock(name, body) {
    const issuesMatch = body.match(/####\s*Issues\s*Found?\s*\n([\s\S]*?)(?=####|---|$)/i);
    const rootMatch = body.match(/####\s*Root\s*Cause\s*\n([\s\S]*?)(?=####|---|$)/i);
    const remMatch = body.match(/####\s*Remediation\s*\n([\s\S]*?)(?=####|---|$)/i);
    const subSections = (issuesMatch || rootMatch || remMatch)
        ? { issues: (issuesMatch?.[1] || '').trim(), rootCause: (rootMatch?.[1] || '').trim(), remediation: (remMatch?.[1] || '').trim() }
        : null;
    return { name, body, subSections };
}

function parseSections(text) {
    const sections = [];
    const regex = /###\s*STAGE:\s*(.+)/gi;
    let match;
    const indices = [];
    while ((match = regex.exec(text)) !== null) {
        indices.push({ index: match.index, name: match[1].trim() });
    }
    for (let i = 0; i < indices.length; i++) {
        const start = indices[i].index;
        const end = i + 1 < indices.length ? indices[i + 1].index : text.length;
        const body = text.slice(start, end).replace(/^###\s*STAGE:\s*.+/i, '').trim();

        // Check if this stage has per-scanner sub-sections (e.g. **Scanner: Semgrep SAST**)
        const scannerRegex = /\*\*Scanner:\s*(.+?)\*\*/gi;
        const scannerIndices = [];
        let sm;
        while ((sm = scannerRegex.exec(body)) !== null) {
            scannerIndices.push({ index: sm.index, name: sm[1].trim() });
        }

        if (scannerIndices.length > 0) {
            // Multiple scanners within this stage — parse each separately
            const scanners = [];
            for (let j = 0; j < scannerIndices.length; j++) {
                const sStart = scannerIndices[j].index;
                const sEnd = j + 1 < scannerIndices.length ? scannerIndices[j + 1].index : body.length;
                const sBody = body.slice(sStart, sEnd).replace(/^\*\*Scanner:\s*.+?\*\*/i, '').trim();
                scanners.push(parseScannerBlock(scannerIndices[j].name, sBody));
            }
            sections.push({ name: indices[i].name, body, subSections: null, scanners });
        } else {
            // Single scanner or no scanner heading — parse as before
            const parsed = parseScannerBlock(indices[i].name, body);
            sections.push({ name: indices[i].name, body: parsed.body, subSections: parsed.subSections, scanners: null });
        }
    }
    if (sections.length === 0 && text.trim()) {
        sections.push({ name: 'Analysis', body: text.trim(), subSections: null, scanners: null });
    }
    return sections;
}

export default function RemediationDetailPage() {
    const { taskId } = useParams();
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [pipelineName, setPipelineName] = useState('');
    const [overall, setOverall] = useState('');
    const [generatedAt, setGeneratedAt] = useState('');
    const [sections, setSections] = useState([]);
    const [expanded, setExpanded] = useState({});

    useEffect(() => {
        setLoading(true);
        getRemediationSaved(taskId)
            .then((res) => {
                setPipelineName(res.pipeline_name || '');
                setOverall(res.overall || '');
                setGeneratedAt(res.generated_at || '');
                const parsed = parseSections(res.remediation || '');
                setSections(parsed);
                const exp = {};
                parsed.forEach((_, i) => { exp[i] = true; });
                setExpanded(exp);
            })
            .catch((e) => toast.error(e?.response?.data?.detail || e.message))
            .finally(() => setLoading(false));
    }, [taskId]);

    const toggle = (i) => setExpanded((prev) => ({ ...prev, [i]: !prev[i] }));

    const fmtDate = (iso) => {
        if (!iso) return '';
        try {
            return new Date(iso).toLocaleString(undefined, {
                month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit',
            });
        } catch { return iso; }
    };

    return (
        <div className="w-full space-y-4">
            <style>{`
                .remediation-severity { font-weight: 700; font-size: 0.7rem; padding: 1px 5px; border-radius: 4px; }
                .remediation-sev-CRITICAL { background: #dc2626; color: #fff; }
                .remediation-sev-HIGH { background: #ea580c; color: #fff; }
                .remediation-sev-MEDIUM { background: #d97706; color: #fff; }
                .remediation-sev-LOW { background: #2563eb; color: #fff; }
                .remediation-sev-FAIL { background: #dc2626; color: #fff; }
                .remediation-sev-INFO { background: #6b7280; color: #fff; }
            `}</style>

            {/* Back button + header */}
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="icon" onClick={() => navigate('/remediation')} title="Back to Remediation Specs">
                    <ArrowLeft className="size-4" />
                </Button>
                <ShieldAlert className="text-primary size-5" />
                <h1 className="text-lg font-bold">Remediation Spec</h1>
            </div>

            {loading && (
                <div className="text-muted-foreground flex items-center justify-center gap-2 py-12 text-sm">
                    <Loader2 className="size-5 animate-spin" /> Loading spec…
                </div>
            )}

            {!loading && sections.length > 0 && (
                <div className="space-y-3">
                    {/* Pipeline banner */}
                    <div className="bg-muted/40 rounded-lg border px-4 py-3">
                        <div className="text-base font-bold tracking-tight">{pipelineName || 'Pipeline'}</div>
                        <div className="text-muted-foreground mt-0.5 text-sm">
                            <span className="text-foreground font-semibold">{overall}</span>
                            <span className="ml-2">&middot; {sections.length} stage{sections.length !== 1 ? 's' : ''} with issues</span>
                            {generatedAt && (
                                <span className="ml-2">&middot; Generated {fmtDate(generatedAt)}</span>
                            )}
                        </div>
                    </div>

                    {/* Stage cards */}
                    <div className="ml-4 space-y-2">
                        {sections.map((s, i) => (
                            <Card key={i} className="gap-0 py-0 overflow-hidden border-l-[3px] border-l-primary/60">
                                <button type="button" onClick={() => toggle(i)}
                                    className="hover:bg-muted/50 flex w-full items-center gap-3 px-4 py-3 text-left">
                                    {expanded[i]
                                        ? <ChevronDown className="text-primary size-4 shrink-0" />
                                        : <ChevronRight className="text-muted-foreground size-4 shrink-0" />}
                                    <ShieldAlert className="text-primary/70 size-4 shrink-0" />
                                    <span className="text-sm font-bold text-primary">{s.name}</span>
                                </button>
                                {expanded[i] && (
                                    <div className="border-t px-5 py-4">
                                        {s.scanners ? (
                                            /* Multiple scanners within this stage */
                                            <div className="space-y-4">
                                                {s.scanners.map((sc, j) => (
                                                    <div key={j} className="rounded-md border bg-muted/10 p-4">
                                                        <div className="mb-3 flex items-center gap-2 text-sm font-bold text-primary">
                                                            <ShieldAlert className="size-4" />
                                                            {sc.name}
                                                        </div>
                                                        {sc.subSections ? (
                                                            <>
                                                                <SubSection icon={Search} title="Issues Found" color="red" text={sc.subSections.issues} />
                                                                <SubSection icon={AlertTriangle} title="Root Cause" color="amber" text={sc.subSections.rootCause} />
                                                                <SubSection icon={Wrench} title="Remediation" color="green" text={sc.subSections.remediation} />
                                                            </>
                                                        ) : (
                                                            <RenderBody text={sc.body} />
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        ) : s.subSections ? (
                                            <>
                                                <SubSection icon={Search} title="Issues Found" color="red" text={s.subSections.issues} />
                                                <SubSection icon={AlertTriangle} title="Root Cause" color="amber" text={s.subSections.rootCause} />
                                                <SubSection icon={Wrench} title="Remediation" color="green" text={s.subSections.remediation} />
                                            </>
                                        ) : (
                                            <RenderBody text={s.body} />
                                        )}
                                    </div>
                                )}
                            </Card>
                        ))}
                    </div>
                </div>
            )}

            {!loading && sections.length === 0 && (
                <div className="text-muted-foreground px-4 py-6 text-center text-sm">
                    No remediation spec found for this run.
                </div>
            )}
        </div>
    );
}
