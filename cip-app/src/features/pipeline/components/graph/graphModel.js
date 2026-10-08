/**
 * Graph model of a run – the same stages as the Pipeline view, as nodes and edges.
 *
 * Parallel work becomes parallel branches that fork and join again (like the User Story / HLD branches of the SDLC
 * graph): the scanners of the Security stage and the component lanes. `level` = column (horizontal layout).
 */

export const NODE = { width: 240, height: 64 };
export const GAP = { x: 110, y: 46 };
export const PANEL_WIDTH = 270;

const DONE = ['passed', 'failed', 'error', 'warning', 'skipped', 'blocked'];

/**
 * Columns of the graph. What runs in parallel in the code becomes parallel nodes:
 *   - Security: one node per scanner (they run at the same time), joined by the human review (HITL) node
 *   - Build & test / Containerise: one node per component (component lanes run at the same time)
 * Everything else runs one after the other: one node per stage.
 */
function columns(stages) {
    const cols = [];
    stages.forEach((stage) => {
        const named = stage.lanes.filter((l) => l.lane);
        const base = { stage: stage.title, agent: stage.agent };
        if (named.length) {
            cols.push(
                named.map((l) => ({
                    ...base,
                    id: `${stage.title}:${l.lane}`,
                    title: `${stage.title} · ${l.lane}`,
                    lane: l.lane,
                    steps: l.steps,
                }))
            );
        } else if (stage.lanes.some((l) => l.group)) {
            const steps = stage.lanes.flatMap((l) => l.steps);
            const review = steps.filter(([id]) => id === 'security_gate');
            const scans = steps.filter(([id]) => id !== 'security_gate');
            if (scans.length)
                cols.push(
                    scans.map(([id, label]) => ({
                        ...base,
                        id,
                        title: label,
                        steps: [[id, label]],
                    }))
                );
            if (review.length)
                cols.push([
                    { ...base, id: `${stage.title}:review`, title: review[0][1], steps: review },
                ]);
        } else {
            cols.push([
                {
                    ...base,
                    id: stage.title,
                    title: stage.title,
                    steps: stage.lanes.flatMap((l) => l.steps),
                },
            ]);
        }
    });
    return cols;
}

export function buildGraph(stages) {
    const nodes = [];
    const edges = [];
    let open = []; // nodes of the previous columns that still need an outgoing edge
    columns(stages).forEach((current, level) => {
        current.forEach((n) => {
            n.level = level;
            const sameLane = n.lane && open.find((p) => p.lane === n.lane);
            (sameLane ? [sameLane] : open).forEach((p) => edges.push({ from: p.id, to: n.id }));
        });
        const lanes = new Set(current.map((n) => n.lane).filter(Boolean));
        // a component without a node in this column (e.g. a library that is not containerised) stays open
        open = current.some((n) => n.lane)
            ? [...current, ...open.filter((p) => p.lane && !lanes.has(p.lane))]
            : current;
        nodes.push(...current);
    });
    return { nodes, edges };
}

/** Status of a node from its steps: error > waiting for a human > processing > completed > waiting. */
export function nodeState(statuses) {
    const done = statuses.filter((s) => DONE.includes(s)).length;
    let state = 'waiting';
    if (statuses.some((s) => ['failed', 'error', 'blocked'].includes(s))) state = 'error';
    else if (statuses.includes('waiting')) state = 'review';
    else if (statuses.includes('running')) state = 'processing';
    else if (statuses.length && done === statuses.length) state = 'completed';
    else if (done > 0) state = 'processing';
    return { state, done, total: statuses.length };
}

/** x / y of every node: columns by level, nodes of one column spread symmetrically around the centre line. */
export function layout(nodes, vertical) {
    const byLevel = {};
    nodes.forEach((n) => (byLevel[n.level] = [...(byLevel[n.level] || []), n]));
    const pos = {};
    Object.values(byLevel).forEach((col) =>
        col.forEach((n, i) => {
            const offset = i - (col.length - 1) / 2;
            pos[n.id] = vertical
                ? { x: offset * (NODE.width + GAP.x), y: n.level * (NODE.height + GAP.y * 1.6) }
                : { x: n.level * (NODE.width + GAP.x), y: offset * (NODE.height + GAP.y * 2) };
        })
    );
    return pos;
}

export function formatDuration(s) {
    if (!s) return '';
    if (s < 60) return `${Math.round(s)}s`;
    const m = Math.floor(s / 60);
    return m < 60 ? `${m}m ${Math.round(s % 60)}s` : `${Math.floor(m / 60)}h ${m % 60}m`;
}
