import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import toast from 'react-hot-toast';
import { History } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/shared/ui/table';
import StatusBadge from '@/shared/components/StatusBadge';
import { listRuns } from '../services/RunsService';

export default function RunsPage() {
    const navigate = useNavigate();
    const [runs, setRuns] = useState([]);

    useEffect(() => {
        listRuns()
            .then(setRuns)
            .catch((e) => toast.error(e.message));
    }, []);

    return (
        <Card className="w-full">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <History className="text-primary size-5" /> Recent runs
                </CardTitle>
            </CardHeader>
            <CardContent>
                <Table>
                    <TableHeader>
                        <TableRow>
                            <TableHead>Result</TableHead>
                            <TableHead>Repository</TableHead>
                            <TableHead>Source</TableHead>
                            <TableHead>Started</TableHead>
                            <TableHead>Duration</TableHead>
                            <TableHead>LLM</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {runs.map((r) => (
                            <TableRow
                                key={r.task_id}
                                className="cursor-pointer"
                                onClick={() => navigate(`/runs/${r.task_id}`)}
                            >
                                <TableCell>
                                    <StatusBadge
                                        status={r.active ? 'RUNNING' : r.overall || r.status}
                                    />
                                </TableCell>
                                <TableCell>
                                    <div className="font-medium">{r.repo}</div>
                                    <div className="text-muted-foreground max-w-sm truncate text-xs">
                                        {r.source}
                                    </div>
                                </TableCell>
                                <TableCell>
                                    <StatusBadge status="pending" label={r.source_type} />{' '}
                                    <StatusBadge
                                        status="pending"
                                        label={r.mode === 'guided' ? 'guided flow' : 'quick run'}
                                    />
                                    {r.source_info?.branch && (
                                        <div className="text-muted-foreground text-xs">
                                            {r.source_info.branch} @{' '}
                                            {(r.source_info.commit || '').slice(0, 10)}
                                        </div>
                                    )}
                                </TableCell>
                                <TableCell>
                                    {r.created_at
                                        ? format(new Date(r.created_at), 'dd MMM yyyy, HH:mm:ss')
                                        : ''}
                                </TableCell>
                                <TableCell>
                                    {r.duration_s ? `${r.duration_s}s` : r.active ? 'running' : ''}
                                </TableCell>
                                <TableCell className="text-xs">{r.provider}</TableCell>
                            </TableRow>
                        ))}
                        {runs.length === 0 && (
                            <TableRow>
                                <TableCell
                                    colSpan={6}
                                    className="text-muted-foreground text-center"
                                >
                                    No runs yet.
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </CardContent>
        </Card>
    );
}
