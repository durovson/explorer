import { operatorConfig } from './operator-config.js';

// Local configure generates this private module. The SDK supplies the bot token.
export const config = operatorConfig;

export function requireSales() {
  if (!config.salesEnabled || !config.pricingVerified) {
    throw new Error('Продажи временно закрыты. Цены и реквизиты уточняются.');
  }
}
