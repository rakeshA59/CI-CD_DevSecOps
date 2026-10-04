import apiRepository from '@/core/repositories/apiRepository';

export const getProviders = () => apiRepository.get('/llm/providers');
export const setDefaultProvider = (provider) => apiRepository.put('/llm/default', { provider });
export const testProvider = (provider) => apiRepository.post('/llm/test', { provider });
