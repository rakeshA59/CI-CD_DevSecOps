import apiRepository from '@/core/repositories/apiRepository';

export const listRuns = async () => (await apiRepository.get('/pipelines')).runs;
