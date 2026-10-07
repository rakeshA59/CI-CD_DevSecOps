import apiRepository from '@/core/repositories/apiRepository';

export const getSettings = () => apiRepository.get('/settings');
export const saveInfra = (provider, values) =>
    apiRepository.put(`/settings/infra/${provider}`, { values });
export const deleteInfra = (provider) => apiRepository.delete(`/settings/infra/${provider}`);
export const saveEnvironment = (name, values) =>
    apiRepository.put(`/settings/environments/${name}`, { values });
export const saveSonarqube = (values) => apiRepository.put('/settings/sonarqube', { values });
export const getMcpHealth = () => apiRepository.get('/health/mcp');
export const repairScanner = (name) => apiRepository.post(`/pipelines/scanners/${name}/repair`, {});
