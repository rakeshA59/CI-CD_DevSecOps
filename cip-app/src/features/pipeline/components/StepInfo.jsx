import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ExternalLink, Info } from 'lucide-react';
import StatusBadge from '@/shared/components/StatusBadge';
import { getStepDocs, stepReportUrl } from '../services/PipelineService';
import usePipelineStore from '../store/usePipelineStore';

/**
 * ⓘ next to a pipeline step: hover = a summary card (what it is, why, tool, how, expected, result, key numbers);
 * click = the full step report (HTML page in a new tab). The card is rendered in a portal so the scrolling
 * pipeline row does not clip it.
 */

let docsCache = null;
let docsPromise = null;
function useStepDocs() {
    const [docs, setDocs] = useState(docsCache);
    useEffect(() => {
        if (docsCache) return;
        docsPromise ||= getStepDocs().then((d) => (docsCache = d));
        docsPromise.then(setDocs).catch(() => {});
    }, []);
    return docs;
}

function docFor(docs, id) {
    if (!docs) return {};
    const [kind, rest] = id.split(/\.(.+)/);
    if (kind === 'scan')
        return { ...docs.scanners?.[rest], expected: 'No critical or high findings.' };
    return docs.steps?.[kind] || {};
}

const ROWS = [
    ['What it is', 'what'],
    ['Why', 'why'],
    ['Tool', 'tool'],
    ['How', 'how'],
    ['Expected', 'expected'],
];

// colour of the ⓘ = what the step found (quality checks + findings); the box colour = did the step work
const QUALITY = {
    clean: ['text-emerald-500', 'no findings'],
    warning: ['text-amber-500', 'warnings – e.g. findings, coverage below target'],
    critical: ['text-red-500', 'critical / high findings, CVEs or failed tests'],
};

export default function StepInfo({ id, label }) {
    const { run, taskId } = usePipelineStore();
    const docs = useStepDocs();
    const [at, setAt] = useState(null);
    const icon = useRef(null);
    const hide = useRef(null);
    const rec = run?.steps?.[id];
    const doc = docFor(docs, id);
    const [tone, toneText] = QUALITY[rec?.quality] || ['text-muted-foreground', ''];
    const checks = rec?.gate?.checks || [];
    const facts = Object.entries(rec?.summary || {})
        .filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
        .slice(0, 6);

    const show = () => {
        clearTimeout(hide.current);
        const r = icon.current.getBoundingClientRect();
        const left = Math.min(r.left, window.innerWidth - 400);
        setAt(
            r.bottom + 380 > window.innerHeight
                ? { left, bottom: window.innerHeight - r.top + 6 }
                : { left, top: r.bottom + 6 }
        );
    };
    const leave = () => {
        hide.current = setTimeout(() => setAt(null), 150);
    };
    const open = (e) => {
        e.stopPropagation();
        if (taskId) window.open(stepReportUrl(taskId, id), '_blank', 'noopener');
    };

    return (
        <>
            <span
                ref={icon}
                role="button"
                tabIndex={0}
                title={toneText ? `Findings: ${toneText}` : 'Details of this step'}
                className={`${tone} hover:text-primary ml-auto shrink-0`}
                onMouseEnter={show}
                onMouseLeave={leave}
                onClick={open}
                onKeyDown={(e) => e.key === 'Enter' && open(e)}
            >
                <Info className="size-3.5" />
            </span>
            {at &&
                createPortal(
                    <div
                        className="bg-popover text-popover-foreground fixed z-50 w-96 rounded-lg border p-3 text-xs shadow-xl"
                        style={at}
                        onMouseEnter={() => clearTimeout(hide.current)}
                        onMouseLeave={leave}
                    >
                        <div className="mb-2 flex items-center gap-2">
                            {rec && <StatusBadge status={rec.status} />}
                            {toneText && (
                                <span className={`text-[11px] font-medium ${tone}`}>
                                    findings: {rec.quality}
                                </span>
                            )}
                            <span className="text-sm font-semibold">{label}</span>
                            {rec?.duration_s ? (
                                <span className="text-muted-foreground ml-auto">
                                    {rec.duration_s}s
                                </span>
                            ) : null}
                        </div>
                        <dl className="grid grid-cols-[72px_1fr] gap-x-2 gap-y-1">
                            {ROWS.filter(([, k]) => doc[k]).map(([t, k]) => (
                                <div key={k} className="contents">
                                    <dt className="text-muted-foreground font-medium">{t}</dt>
                                    <dd>{doc[k]}</dd>
                                </div>
                            ))}
                            <dt className="text-muted-foreground font-medium">Result</dt>
                            <dd>{rec ? rec.message || rec.status : 'not run yet'}</dd>
                        </dl>
                        {checks.length > 0 && (
                            <div className="mt-2">
                                <div className="text-muted-foreground mb-1 font-medium">
                                    Quality checks (do not stop the pipeline)
                                </div>
                                {checks.map((c) => (
                                    <div key={c.name} className="flex gap-2">
                                        <span
                                            className={
                                                c.passed ? 'text-emerald-500' : 'text-amber-500'
                                            }
                                        >
                                            {c.passed ? '✓' : '!'}
                                        </span>
                                        <span>
                                            {c.name}: <b>{String(c.actual)}</b> (needs {c.required})
                                        </span>
                                    </div>
                                ))}
                            </div>
                        )}
                        {facts.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1">
                                {facts.map(([k, v]) => (
                                    <span key={k} className="bg-muted rounded px-1.5 py-0.5">
                                        {k.replaceAll('_', ' ')}: <b>{String(v)}</b>
                                    </span>
                                ))}
                            </div>
                        )}
                        {taskId && (
                            <button
                                type="button"
                                onClick={open}
                                className="text-primary mt-2 flex items-center gap-1 font-medium"
                            >
                                Open the full report <ExternalLink className="size-3" />
                            </button>
                        )}
                    </div>,
                    document.body
                )}
        </>
    );
}
