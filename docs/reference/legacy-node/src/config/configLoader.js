const fs = require('fs');
const path = require('path');

const configPath = path.resolve(__dirname, '../../pricing.config.json');

let businessRules = {
  moq: { minimum_order_quantity: 50 },
  volume_pricing_tiers: [
    { tier: 1, min_qty: 50, max_qty: 99, unit_price: 3.50 },
    { tier: 2, min_qty: 100, max_qty: 199, unit_price: 3.25 },
    { tier: 3, min_qty: 200, max_qty: null, unit_price: 3.00 }
  ],
  customizations: { heart_shaped_surcharge_per_unit: 0.50 },
  logistics: {
    dry_ice: { price_per_block: 15.00 },
    delivery: {
      base_fee: 25.00,
      max_fee: 75.00,
      max_radius_miles: 30.0
    },
    full_service: { flat_fee: 150.00 }
  },
  payments: { deposit_rate: 0.50 }
};

try {
  const fileData = fs.readFileSync(configPath, 'utf8');
  const parsed = JSON.parse(fileData);
  if (parsed && parsed.business_rules) {
    businessRules = parsed.business_rules;
  }
  console.log('[CONFIG] Successfully loaded pricing.config.json');
} catch (err) {
  console.warn('[CONFIG] Warning: Failed to read pricing.config.json, using default business rules:', err.message);
}

module.exports = { businessRules };