const { businessRules } = require('../config/configLoader');
const {
  calculateHeartShapeSurcharge,
  calculateDryIceFee,
  calculateLogisticsFees
} = require('./feeCalculator');

/**
 * Executes full pricing calculation and validation.
 * @param {Object} payload
 * @returns {Object} Quotation response object matching API schema
 */
function calculateOrderQuote(payload) {
  // NOTE: Input validation (MOQ, negative values, flavor sum integrity, etc.)
  // is performed upstream by `validateQuotePayload` (src/validators/quoteValidator.js)
  // before this function is called. `payload` is assumed to already be sanitized.
  const {
    total_quantity,
    heart_shaped_quantity = 0,
    service_type = 'PICKUP',
    delivery_distance_miles = 0,
    dry_ice_blocks = 0,
    flavors = null
  } = payload;

  // 1. Volume tier mapping
  let unitPrice = 3.50;
  let tierName = 'Tier 1 (50-99)';
  if (total_quantity >= 200) {
    unitPrice = 3.00;
    tierName = 'Tier 3 (200+)';
  } else if (total_quantity >= 100) {
    unitPrice = 3.25;
    tierName = 'Tier 2 (100-199)';
  }

  const basePopsiclesAmount = Number((total_quantity * unitPrice).toFixed(2));

  // 2. Calculate add-on and logistical fees
  const heartShapedFee = calculateHeartShapeSurcharge(total_quantity, heart_shaped_quantity);
  const dryIceFee = calculateDryIceFee(dry_ice_blocks);
  const { deliveryFee, fullServiceFee } = calculateLogisticsFees(service_type, delivery_distance_miles);

  // 3. Compute totals and deposit rounding
  const depositRate = businessRules.payments?.deposit_rate ?? 0.50;
  const totalAmount = Number((basePopsiclesAmount + heartShapedFee + dryIceFee + deliveryFee + fullServiceFee).toFixed(2));
  const depositDue = Number((Math.ceil(totalAmount * depositRate * 100) / 100).toFixed(2));
  const balanceDue = Number((totalAmount - depositDue).toFixed(2));

  return {
    tier_applied: {
      name: tierName,
      unit_price: unitPrice
    },
    breakdown: {
      base_popsicles_amount: basePopsiclesAmount,
      heart_shaped_surcharge: heartShapedFee,
      dry_ice_amount: dryIceFee,
      delivery_fee: deliveryFee,
      full_service_fee: fullServiceFee
    },
    pricing_summary: {
      subtotal: totalAmount,
      total_amount: totalAmount,
      deposit_due_now: depositDue,
      balance_due_later: balanceDue
    },
    currency: 'USD'
  };
}

module.exports = { calculateOrderQuote };
