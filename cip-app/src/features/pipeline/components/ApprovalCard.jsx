import { useState } from 'react';
import toast from 'react-hot-toast';
import { Check, ShieldQuestion, X } from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card';
import { Input } from '@/shared/ui/input';
import StatusBadge from '@/shared/components/StatusBadge';
import usePipelineStore from '../store/usePipelineStore';

/** Guided flow – human in the loop: the run waits until a reviewer approves or rejects the UAT deploy. */
export default function ApprovalCard() {
    const { run, resume } = usePipelineStore();
    const [by, setBy] = useState('');
    const [comment, setComment] = useState('');
    const [sending, setSending] = useState(false);
    if (run?.status !== 'WAITING_APPROVAL' || run?.pending?.type !== 'approval') return null;
    const sm = run.pending.summary || {};

    const decide = async (decision) => {
        setSending(true);
        try {
            await resume('approval', { decision, by: by || 'reviewer', comment });
            toast.success(
                decision === 'approve'
                    ? 'Approved – deploying to UAT'
                    : 'Rejected – UAT deploy skipped'
            );
        } catch (e) {
            toast.error(e.message);
        } finally {
            setSending(false);
        }
    };

    return (
        <Card className="gap-3 border-amber-500/50 py-4">
            <CardHeader className="px-4">
                <CardTitle className="flex items-center gap-2">
                    <ShieldQuestion className="size-5 text-amber-500" /> Approval needed before{' '}
                    {String(run.pending.target).toUpperCase()}
                </CardTitle>
                <CardDescription>
                    Review the stage reports below, then approve or reject the deployment.
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 px-4 text-sm">
                <div className="flex flex-wrap gap-2">
                    {Object.entries(sm.gates || {}).map(([k, ok]) => (
                        <StatusBadge
                            key={k}
                            status={ok ? 'passed' : 'failed'}
                            label={`${k}: ${ok ? 'PASS' : 'FAIL'}`}
                        />
                    ))}
                    {Object.entries(sm.findings || {}).map(([k, n]) => (
                        <StatusBadge
                            key={k}
                            status={n ? 'warning' : 'passed'}
                            label={`${n} ${k.toLowerCase()}`}
                        />
                    ))}
                </div>
                {sm.failed_steps?.length > 0 && (
                    <div className="text-red-500">Failed steps: {sm.failed_steps.join(', ')}</div>
                )}
                {Object.keys(sm.released || {}).length > 0 && (
                    <div className="text-muted-foreground text-xs">
                        Released:{' '}
                        {Object.entries(sm.released)
                            .map(([k, v]) => `${k} → ${v}`)
                            .join(' · ')}
                    </div>
                )}
                <div className="grid gap-2 md:grid-cols-[200px_1fr]">
                    <Input
                        placeholder="Your name"
                        value={by}
                        onChange={(e) => setBy(e.target.value)}
                    />
                    <Input
                        placeholder="Comment (optional)"
                        value={comment}
                        onChange={(e) => setComment(e.target.value)}
                    />
                </div>
                <div className="flex gap-2">
                    <Button onClick={() => decide('approve')} disabled={sending} className="gap-2">
                        <Check className="size-4" /> Approve UAT deploy
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => decide('reject')}
                        disabled={sending}
                        className="gap-2"
                    >
                        <X className="size-4" /> Reject
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
}
