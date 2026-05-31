import { ConfigError } from './errors.js';

export const DEFAULT_BASE_URL = 'https://api.financialdatasets.ai';

export function getFinancialDatasetsConfig(env = process.env) {
  const apiKey = env.FINANCIAL_DATASETS_API_KEY;
  if (!apiKey) {
    throw new ConfigError('FINANCIAL_DATASETS_API_KEY is required for live financial data. Copy env.example to .env or export it in your shell.');
  }
  return {
    apiKey,
    baseUrl: env.FINANCIAL_DATASETS_BASE_URL || DEFAULT_BASE_URL,
  };
}
