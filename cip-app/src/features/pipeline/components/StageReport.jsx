const ROWS = [
    ['what', 'What it did'],
    ['where', 'Where'],
    ['how', 'How'],
    ['why', 'Why'],
    ['result', 'Result'],
    ['suggestions', 'Suggestions'],
    ['blockers', 'Blockers'],
];

/** The fixed-shape report of one stage: what · where · how · why · result · suggestions · blockers. */
export default function StageReport({ report }) {
    if (!report)
        return (
            <div className="text-muted-foreground text-sm">
                The report is written when the step has finished.
            </div>
        );
    return (
        <dl className="divide-y rounded-md border text-sm">
            {ROWS.map(([key, label]) => {
                const v = report[key];
                const list = Array.isArray(v) ? v : v ? [v] : [];
                return (
                    <div key={key} className="grid gap-1 px-3 py-2 md:grid-cols-[140px_1fr]">
                        <dt
                            className={`text-xs font-semibold uppercase ${key === 'blockers' && list.length ? 'text-red-500' : 'text-muted-foreground'}`}
                        >
                            {label}
                        </dt>
                        <dd className="min-w-0 break-words">
                            {list.length === 0 && (
                                <span className="text-muted-foreground">
                                    {key === 'blockers' ? 'none' : '–'}
                                </span>
                            )}
                            {list.length === 1 && (
                                <span className="whitespace-pre-wrap">{list[0]}</span>
                            )}
                            {list.length > 1 && (
                                <ul className="list-disc space-y-0.5 pl-4">
                                    {list.map((x, i) => (
                                        <li
                                            key={i}
                                            className={
                                                key === 'how' || key === 'where'
                                                    ? 'font-mono text-xs'
                                                    : ''
                                            }
                                        >
                                            {x}
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </dd>
                    </div>
                );
            })}
        </dl>
    );
}
