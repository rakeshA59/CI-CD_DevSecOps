import apiRepository from '@/core/repositories/apiRepository';

export const getProviders = () => apiRepository.get('/llm/providers');
export const setDefaultProvider = (provider) => apiRepository.put('/llm/default', { provider });
export const testProvider = (provider) => apiRepository.post('/llm/test', { provider });
export const saveProvider = (provider, values) =>
    apiRepository.put(`/llm/providers/${provider}`, { values });
export const removeProvider = (provider) => apiRepository.delete(`/llm/providers/${provider}`);
