/**
 * Graph model of a run – the same stages as the Pipeline view, as nodes and edges.
 *
 * One node per stage; a stage with one lane per component (Build & test, Containerise) becomes one node per
 * component, so the components run as parallel branches that fork after Security and join again at the next
 * shared stage (like the User Story / HLD branches of the SDLC graph). `level` = column (horizontal layout).
 */

export const NODE = { width: 240, height: 64 };
export const GAP = { x: 110, y: 46 };
export const PANEL_WIDTH = 270;

const DONE = ['passed', 'failed', 'error', 'warning', 'skipped', 'blocked'];

export function buildGraph(stages) {
    const nodes = [];
    const edges = [];
    let open = []; // nodes of the previous columns that still need an outgoing edge
    stages.forEach((stage, level) => {
        const named = stage.lanes.filter((l) => l.lane);
        const current = named.length
            ? named.map((l) => ({
                  id: `${stage.title}:${l.lane}`,
                  stage: stage.title,
                  title: `${stage.title} · ${l.lane}`,
                  agent: stage.agent,
                  lane: l.lane,
                  steps: l.steps,
                  level,
              }))
            : [
                  {
                      id: stage.title,
                      stage: stage.title,
                      title: stage.title,
                      agent: stage.agent,
                      steps: stage.lanes.flatMap((l) => l.steps),
                      level,
                  },
              ];
        current.forEach((n) => {
            const sameLane = n.lane && open.find((p) => p.lane === n.lane);
            (sameLane ? [sameLane] : open).forEach((p) => edges.push({ from: p.id, to: n.id }));
        });
        const lanes = new Set(current.map((n) => n.lane).filter(Boolean));
        // a component without a node in this column (e.g. a library that is not containerised) stays open
        open = named.length
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
