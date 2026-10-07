import { useCallback, useEffect, useRef, useState } from 'react';
import {
    ArrowDown,
    ArrowRight,
    ChevronDown,
    ChevronRight,
    Clock,
    Maximize2,
    Minus,
    Plus,
    ScrollText,
} from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { StatusIcon } from '@/shared/components/StatusBadge';
import usePipelineStore from '../../store/usePipelineStore';
import { stepStatus, useStages } from '../PipelineFlow';
import { buildGraph, formatDuration, layout, NODE, nodeState, PANEL_WIDTH } from './graphModel';

/**
 * Graph view of a run (modelled on the SDLC app's pipeline graph): one node per stage – components as parallel
 * branches – with live status, sub-step panels, pan (drag), zoom (wheel / buttons), horizontal ↔ vertical layout
 * and fit-to-screen. Status comes from the same live events and step records as the Pipeline view.
 */

const COLOR = {
    completed: '#22c55e',
    processing: '#3b82f6',
    error: '#ef4444',
    waiting: '#6b7280',
    review: '#f59e0b',
};
const LEGEND = [
    ['processing', 'Processing'],
    ['completed', 'Completed'],
    ['error', 'Error'],
    ['review', 'Waiting for you'],
    ['waiting', 'Waiting'],
];
const ICON = {
    completed: 'passed',
    processing: 'running',
    error: 'failed',
    review: 'waiting',
    waiting: 'pending',
};
const STEP_DOT = (s) =>
    s === 'passed'
        ? COLOR.completed
        : ['failed', 'error', 'blocked'].includes(s)
          ? COLOR.error
          : s === 'running'
            ? COLOR.processing
            : ['warning', 'skipped', 'waiting'].includes(s)
              ? COLOR.review
              : COLOR.waiting;

function edgeStyle(from, to) {
    if (from === 'error') return { color: COLOR.error, dashed: false, flow: false };
    if (['processing', 'review'].includes(to))
        return { color: COLOR.processing, dashed: true, flow: true };
    if (from === 'completed') return { color: COLOR.completed, dashed: false, flow: false };
    return { color: COLOR.waiting, dashed: true, flow: false };
}

function edgePath(a, b, vertical) {
    if (vertical) {
        const [x1, y1, x2, y2] = [
            a.x + NODE.width / 2,
            a.y + NODE.height,
            b.x + NODE.width / 2,
            b.y,
        ];
        const c = (y2 - y1) / 2;
        return `M${x1},${y1} C${x1},${y1 + c} ${x2},${y2 - c} ${x2},${y2}`;
    }
    const [x1, y1, x2, y2] = [a.x + NODE.width, a.y + NODE.height / 2, b.x, b.y + NODE.height / 2];
    const c = (x2 - x1) / 2;
    return `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`;
}

/** Sub-steps of one stage node, with status, duration and an n/m progress bar (like the SDLC sub-agent panel). */
function StepPanel({ node, steps, done, style, above, onPick, onClose, selectedStep }) {
    const pct = steps.length ? Math.round((100 * done) / steps.length) : 0;
    return (
        <div
            className={cn(
                'bg-card absolute z-20 rounded-lg border shadow-xl',
                above && '-translate-y-full'
            )}
            style={{ width: PANEL_WIDTH, ...style }}
            onMouseDown={(e) => e.stopPropagation()}
        >
            <div className="flex items-center justify-between border-b px-3 py-2">
                <span className="text-muted-foreground truncate text-[11px] font-semibold uppercase">
                    {node.title}
                </span>
                <button
                    type="button"
                    className="text-muted-foreground hover:text-foreground text-xs"
                    onClick={onClose}
                >
                    ✕
                </button>
            </div>
            <div className="space-y-1 p-2">
                {steps.map(({ id, label, status, rec }) => (
                    <button
                        key={id}
                        type="button"
                        onClick={() => onPick(id)}
                        className={cn(
                            'bg-muted/40 hover:bg-muted flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[11px]',
                            selectedStep === id && 'ring-primary ring-1'
                        )}
                    >
                        <span
                            className={cn(
                                'size-2 shrink-0 rounded-full',
                                status === 'running' && 'animate-pulse'
                            )}
                            style={{ background: STEP_DOT(status) }}
                        />
                        <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
                        <span className="text-muted-foreground shrink-0">
                            {formatDuration(rec?.duration_s)}
                        </span>
                    </button>
                ))}
            </div>
            <div className="text-muted-foreground flex items-center gap-2 border-t px-3 py-2 text-[10px]">
                {done}/{steps.length} completed
                <span className="bg-muted ml-auto h-1 w-20 overflow-hidden rounded">
                    <span className="block h-full bg-blue-500" style={{ width: `${pct}%` }} />
                </span>
                {pct}%
            </div>
        </div>
    );
}

export default function PipelineGraph() {
    const { run, nodeStatus, live, selectStep, selectedStep, showLogs } = usePipelineStore();
    const stages = useStages();
    const { nodes, edges } = buildGraph(stages);
    const [vertical, setVertical] = useState(false);
    const [openPanels, setOpenPanels] = useState(() => new Set());
    const [view, setView] = useState({ x: 40, y: 260, k: 0.85 });
    const box = useRef(null);
    const drag = useRef(null);
    const pos = layout(nodes, vertical);
    const box2 = (() => {
        const ps = Object.values(pos);
        if (!ps.length) return { x: 0, y: 0, w: 1, h: 1 };
        const x = Math.min(...ps.map((p) => p.x)) - 40;
        const y = Math.min(...ps.map((p) => p.y)) - 40;
        return {
            x,
            y,
            w: Math.max(...ps.map((p) => p.x)) + NODE.width + 40 - x,
            h: Math.max(...ps.map((p) => p.y)) + NODE.height + 40 - y,
        };
    })();

    const info = Object.fromEntries(
        nodes.map((n) => {
            const steps = n.steps.map(([id, label]) => ({
                id,
                label,
                status: stepStatus(id, run, nodeStatus, live),
                rec: run?.steps?.[id],
            }));
            const st = nodeState(steps.map((s) => s.status));
            // scanners run in parallel (count the longest once); the other steps run one after the other
            const dur = (s) => s.rec?.duration_s || 0;
            const scans = steps.filter((s) => s.id.startsWith('scan.'));
            const secs =
                Math.max(0, ...scans.map(dur)) +
                steps.filter((s) => !s.id.startsWith('scan.')).reduce((t, s) => t + dur(s), 0);
            return [n.id, { ...st, steps, secs }];
        })
    );

    const fit = useCallback(
        (whole = false) => {
            const el = box.current;
            const ps = Object.values(pos);
            if (!el || !ps.length) return;
            const minX = Math.min(...ps.map((p) => p.x));
            const minY = Math.min(...ps.map((p) => p.y));
            const w = Math.max(...ps.map((p) => p.x)) + NODE.width - minX;
            const h = Math.max(...ps.map((p) => p.y)) + NODE.height - minY;
            const fitK = Math.min(1.1, (el.clientWidth - 80) / w, (el.clientHeight - 140) / h);
            // opening: never smaller than a readable 70 % – a long pipeline starts at the left, pan / ⤢ for the rest
            const k = whole ? fitK : Math.max(fitK, 0.7);
            setView({
                k,
                x: k > fitK ? 40 - minX * k : (el.clientWidth - w * k) / 2 - minX * k,
                y: (el.clientHeight - h * k) / 2 - minY * k - 20,
            });
        },
        [JSON.stringify(pos)]
    ); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        fit();
    }, [nodes.length, vertical]); // eslint-disable-line react-hooks/exhaustive-deps

    // wheel = zoom around the cursor (a non-passive listener, so the page does not scroll)
    useEffect(() => {
        const el = box.current;
        if (!el) return undefined;
        const onWheel = (e) => {
            e.preventDefault();
            const r = el.getBoundingClientRect();
            const mx = e.clientX - r.left;
            const my = e.clientY - r.top;
            setView((v) => {
                const k = Math.min(2, Math.max(0.3, v.k * (e.deltaY < 0 ? 1.1 : 0.9)));
                return { k, x: mx - ((mx - v.x) * k) / v.k, y: my - ((my - v.y) * k) / v.k };
            });
        };
        el.addEventListener('wheel', onWheel, { passive: false });
        return () => el.removeEventListener('wheel', onWheel);
    }, []);

    const zoomBy = (f) =>
        setView((v) => {
            const el = box.current;
            const k = Math.min(2, Math.max(0.3, v.k * f));
            const cx = el.clientWidth / 2;
            const cy = el.clientHeight / 2;
            return { k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k };
        });

    const togglePanel = (id) =>
        setOpenPanels((s) => {
            const n = new Set(s);
            n.has(id) ? n.delete(id) : n.add(id);
            return n;
        });

    if (!nodes.length)
        return <div className="text-muted-foreground p-6 text-sm">No pipeline yet.</div>;

    return (
        <div
            ref={box}
            className="relative h-[640px] cursor-grab overflow-hidden rounded-lg border bg-[radial-gradient(circle,rgba(127,127,127,0.18)_1px,transparent_1px)] [background-size:22px_22px] select-none active:cursor-grabbing"
            onMouseDown={(e) => {
                drag.current = { sx: e.clientX, sy: e.clientY, x: view.x, y: view.y };
            }}
            onMouseMove={(e) => {
                const d = drag.current;
                if (d)
                    setView((v) => ({
                        ...v,
                        x: d.x + e.clientX - d.sx,
                        y: d.y + e.clientY - d.sy,
                    }));
            }}
            onMouseUp={() => (drag.current = null)}
            onMouseLeave={() => (drag.current = null)}
        >
            <style>{'@keyframes cip-flow{to{stroke-dashoffset:-20}}'}</style>
            <div
                className="absolute top-0 left-0"
                style={{
                    transform: `translate(${view.x}px, ${view.y}px) scale(${view.k})`,
                    transformOrigin: '0 0',
                }}
            >
                {/* the SVG covers every node (a tiny overflowing SVG is not painted inside the zoomed canvas) */}
                <svg
                    className="pointer-events-none absolute"
                    style={{
                        left: box2.x,
                        top: box2.y,
                        width: box2.w,
                        height: box2.h,
                        maxWidth: 'none', // the app CSS caps every svg at 100 % of its (zero-width) parent
                    }}
                >
                    <g transform={`translate(${-box2.x} ${-box2.y})`}>
                        {edges.map((e) => {
                            const st = edgeStyle(info[e.from].state, info[e.to].state);
                            return (
                                <path
                                    key={`${e.from}>${e.to}`}
                                    d={edgePath(pos[e.from], pos[e.to], vertical)}
                                    fill="none"
                                    stroke={st.color}
                                    strokeWidth={2}
                                    strokeDasharray={st.dashed ? '6 5' : undefined}
                                    style={
                                        st.flow
                                            ? { animation: 'cip-flow 0.8s linear infinite' }
                                            : undefined
                                    }
                                    opacity={st.color === COLOR.waiting ? 0.6 : 0.95}
                                />
                            );
                        })}
                    </g>
                </svg>

                {nodes.map((n) => {
                    const p = pos[n.id];
                    const it = info[n.id];
                    const color = COLOR[it.state];
                    const isOpen = openPanels.has(n.id);
                    return (
                        <div
                            key={n.id}
                            title={`${n.title} – ${n.agent}`}
                            className="bg-card absolute z-10 flex items-center gap-2 rounded-xl border-2 px-2 shadow-md"
                            style={{
                                left: p.x,
                                top: p.y,
                                width: NODE.width,
                                height: NODE.height,
                                borderColor: color,
                                boxShadow:
                                    it.state === 'waiting' ? undefined : `0 0 14px ${color}55`,
                            }}
                            onMouseDown={(e) => e.stopPropagation()}
                        >
                            <span
                                className="flex size-8 shrink-0 items-center justify-center rounded-full border"
                                style={{ borderColor: `${color}88`, color }}
                            >
                                <StatusIcon status={ICON[it.state]} />
                            </span>
                            <div className="min-w-0 flex-1">
                                <div className="truncate text-xs font-semibold" style={{ color }}>
                                    {n.title}
                                </div>
                                <div className="text-muted-foreground mt-1 flex items-center gap-1.5 text-[10px]">
                                    <span className="bg-muted h-1 w-12 overflow-hidden rounded">
                                        <span
                                            className="block h-full"
                                            style={{
                                                width: `${it.total ? (100 * it.done) / it.total : 0}%`,
                                                background: color,
                                            }}
                                        />
                                    </span>
                                    {it.done}/{it.total}
                                    {it.secs > 0 && (
                                        <>
                                            <Clock className="size-3" />
                                            {formatDuration(it.secs)}
                                        </>
                                    )}
                                </div>
                            </div>
                            <button
                                type="button"
                                title="Logs of this stage"
                                className="text-muted-foreground hover:text-foreground"
                                onClick={() => showLogs(n.stage)}
                            >
                                <ScrollText className="size-4" />
                            </button>
                            <button
                                type="button"
                                title={isOpen ? 'Hide steps' : 'Show steps'}
                                className={cn(
                                    'flex size-6 items-center justify-center rounded-full',
                                    isOpen ? 'bg-blue-500 text-white' : 'text-muted-foreground'
                                )}
                                onClick={() => togglePanel(n.id)}
                            >
                                {isOpen ? (
                                    <ChevronDown className="size-4" />
                                ) : (
                                    <ChevronRight className="size-4" />
                                )}
                            </button>
                        </div>
                    );
                })}

                {nodes
                    .filter((n) => openPanels.has(n.id))
                    .map((n) => {
                        const p = pos[n.id];
                        const above = !vertical && p.y < 0;
                        const style = vertical
                            ? { left: p.x + NODE.width + 14, top: p.y }
                            : {
                                  left: p.x + (NODE.width - PANEL_WIDTH) / 2,
                                  top: above ? p.y - 12 : p.y + NODE.height + 12,
                              };
                        return (
                            <StepPanel
                                key={`panel-${n.id}`}
                                node={n}
                                steps={info[n.id].steps}
                                done={info[n.id].done}
                                style={style}
                                above={above}
                                selectedStep={selectedStep}
                                onPick={selectStep}
                                onClose={() => togglePanel(n.id)}
                            />
                        );
                    })}
            </div>

            <div
                className="bg-card/95 absolute bottom-3 left-3 rounded-lg border px-3 py-2 text-xs"
                onMouseDown={(e) => e.stopPropagation()}
            >
                <div className="text-muted-foreground mb-1 font-semibold uppercase">Status</div>
                {LEGEND.map(([k, label]) => (
                    <div key={k} className="flex items-center gap-2 py-0.5">
                        <span className="size-2.5 rounded-full" style={{ background: COLOR[k] }} />
                        {label}
                    </div>
                ))}
            </div>

            <div
                className="bg-card/95 absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-lg border px-2 py-1 text-sm"
                onMouseDown={(e) => e.stopPropagation()}
            >
                <button
                    type="button"
                    className="hover:bg-muted rounded p-1.5"
                    onClick={() => zoomBy(0.85)}
                    title="Zoom out"
                >
                    <Minus className="size-4" />
                </button>
                <span className="w-12 text-center font-mono text-xs">
                    {Math.round(view.k * 100)}%
                </span>
                <button
                    type="button"
                    className="hover:bg-muted rounded p-1.5"
                    onClick={() => zoomBy(1.15)}
                    title="Zoom in"
                >
                    <Plus className="size-4" />
                </button>
                <span className="bg-border mx-1 h-5 w-px" />
                <button
                    type="button"
                    className="hover:bg-muted rounded p-1.5 text-emerald-500"
                    onClick={() => setVertical((v) => !v)}
                    title={vertical ? 'Horizontal layout' : 'Vertical layout'}
                >
                    {vertical ? (
                        <ArrowDown className="size-4" />
                    ) : (
                        <ArrowRight className="size-4" />
                    )}
                </button>
                <button
                    type="button"
                    className="hover:bg-muted rounded p-1.5"
                    onClick={() => fit(true)}
                    title="Fit to screen"
                >
                    <Maximize2 className="size-4" />
                </button>
            </div>
        </div>
    );
}
