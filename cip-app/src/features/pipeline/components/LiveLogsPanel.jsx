import { useEffect, useRef, useState } from 'react';
import { Terminal } from 'lucide-react';
import { cn } from '@/core/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import usePipelineStore from '../store/usePipelineStore';

const COLOR = {
    START: 'text-primary',
    END: 'text-emerald-500',
    ERROR: 'text-red-500',
    SKIPPED: 'text-amber-500',
    COMMAND: 'text-muted-foreground',
    SYSTEM_START: 'text-primary font-semibold',
    SYSTEM_END: 'font-semibold',
    SYSTEM_PAUSE: 'text-amber-500 font-semibold',
};

/** Every agent event of the run, as it happens (SSE). */
export default function LiveLogsPanel() {
    const { events, live } = usePipelineStore();
    const [filter, setFilter] = useState('');
    const bottom = useRef(null);
    const shown = events.filter(
        (e) => !filter || `${e.node} ${e.message}`.toLowerCase().includes(filter.toLowerCase())
    );

    useEffect(() => {
        if (live) bottom.current?.scrollIntoView({ block: 'nearest' });
    }, [events.length, live]);

    return (
        <Card className="gap-3 py-4">
            <CardHeader className="flex flex-row items-center justify-between gap-3 px-4">
                <CardTitle className="flex items-center gap-2 text-sm">
                    <Terminal className="size-4" /> Live agent log{' '}
                    {live && <span className="size-2 animate-pulse rounded-full bg-emerald-500" />}
                </CardTitle>
                <Input
                    className="h-8 max-w-56 text-xs"
                    placeholder="Filter…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                />
            </CardHeader>
            <CardContent className="px-4">
                <div className="bg-muted/50 max-h-80 overflow-auto rounded-md p-3 font-mono text-[12px] leading-5">
                    {shown.length === 0 && (
                        <div className="text-muted-foreground">Waiting for events…</div>
                    )}
                    {shown.map((e, i) => (
                        <div key={e.id || i} className="flex gap-3 whitespace-pre-wrap">
                            <span className="text-muted-foreground w-40 shrink-0 truncate">
                                {e.node}
                            </span>
                            <span className={cn('min-w-0 break-words', COLOR[e.status])}>
                                {e.message}
                            </span>
                        </div>
                    ))}
                    <div ref={bottom} />
                </div>
            </CardContent>
        </Card>
    );
}
