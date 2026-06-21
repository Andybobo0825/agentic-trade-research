import { ConfigError } from './errors.js';

export const ORDER_CONFIRM_PHRASE = 'I_UNDERSTAND_LIVE_ORDER_RISK';

export function isOrderEnabled(env = process.env) {
  return env.TRADE_ORDER_ENABLED === '1' && env.TRADE_ORDER_CONFIRM === ORDER_CONFIRM_PHRASE;
}

export function assertOrderAllowed(env = process.env, action = 'order') {
  if (isOrderEnabled(env)) return true;
  throw new ConfigError(`${action} is disabled by default. Set TRADE_ORDER_ENABLED=1 and TRADE_ORDER_CONFIRM=${ORDER_CONFIRM_PHRASE} only when intentionally enabling live order paths.`);
}
