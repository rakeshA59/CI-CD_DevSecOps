import { cn } from '@/core/lib/utils';
import { CheckCircle2, CircleDashed, Loader2, MinusCircle, OctagonX, XCircle } from 'lucide-react';

export const STATUS_STYLE = {
    passed: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
    PASS: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
    COMPLETED: 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
    failed: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
    FAIL: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
    error: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
    ERROR: 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30',
    blocked: 'bg-red-500/10 text-red-500 dark:text-red-300 border-red-500/30 border-dashed',
    warning: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
    skipped: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
    INCOMPLETE: 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30',
    running: 'bg-primary/15 text-primary border-primary/30',
    RUNNING: 'bg-primary/15 text-primary border-primary/30',
    pending: 'bg-muted text-muted-foreground border-border',
};

const ICONS = {
    passed: CheckCircle2,
    failed: XCircle,
    error: XCircle,
    blocked: OctagonX,
    skipped: MinusCircle,
    warning: MinusCircle,
    running: Loader2,
    pending: CircleDashed,
};

export function StatusIcon({ status = 'pending', className }) {
    const Icon = ICONS[status] || CircleDashed;
    return <Icon className={cn('size-4 shrink-0', status === 'running' && 'animate-spin', className)} />;
}

export default function StatusBadge({ status = 'pending', label, className }) {
    return (
        <span
            className={cn(
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-semibold uppercase tracking-wide',
                STATUS_STYLE[status] || STATUS_STYLE.pending,
                className
            )}
        >
            {label || String(status).replace('_', ' ')}
        </span>
    );
}
