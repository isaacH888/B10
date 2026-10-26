const { businessRules } = require('../config/configLoader');

/**
 * Calculates heart-shaped popsicle surcharge.
 * @param {number} totalQty - Total popsicles ordered
 * @param {number} heartQty - Requested heart-shaped popsicles
 * @returns {number}
 */
function calculateHeartShapeSurcharge(totalQty, heartQty = 0) {
  if (heartQty < 0) {
    const error = new Error('Quantities cannot be negative.');
    error.statusCode = 422;
    error.code = 'ERR_INVALID_DATA_TYPE';
    error.field = 'heart_shaped_quantity';
    error.rejectedValue = heartQty;
    throw error;
  }

  if (heartQty > totalQty) {
    const error = new Error('Heart-shaped popsicle quantity cannot exceed total quantity.');
    error.statusCode = 400;
    error.code = 'ERR_HEART_EXCEEDS_TOTAL';
    error.field = 'heart_shaped_quantity';
    error.rejectedValue = heartQty;
    throw error;
  }

  const surcharge = businessRules.customizations?.heart_shaped_surcharge_per_unit ?? 0.50;
  return Number((heartQty * surcharge).toFixed(2));
}

/**
 * Calculates dry ice block fees.
 * @param {number} blocks - Number of dry ice blocks
 * @returns {number}
 */
function calculateDryIceFee(blocks = 0) {
  if (blocks < 0) {
    const error = new Error('Quantities cannot be negative.');
    error.statusCode = 422;
    error.code = 'ERR_INVALID_DATA_TYPE';
    error.field = 'dry_ice_blocks';
    error.rejectedValue = blocks;
    throw error;
  }

  const pricePerBlock = businessRules.logistics?.dry_ice?.price_per_block ?? 15.00;
  return Number((blocks * pricePerBlock).toFixed(2));
}

/**
 * Calculates delivery or full-service logistical fees.
 * @param {string} serviceType - 'DELIVERY', 'FULL_SERVICE', or 'PICKUP'
 * @param {number} distanceMiles - Distance in miles from origin facility
 * @returns {{ deliveryFee: number, fullServiceFee: number }}
 */
function calculateLogisticsFees(serviceType = 'PICKUP', distanceMiles = 0) {
  if (serviceType === 'PICKUP') {
    return { deliveryFee: 0.00, fullServiceFee: 0.00 };
  }

  if (serviceType === 'FULL_SERVICE') {
    const fullServiceFee = businessRules.logistics?.full_service?.flat_fee ?? 150.00;
    return {
      deliveryFee: 0.00,
      fullServiceFee: Number(fullServiceFee.toFixed(2))
    };
  }

  if (serviceType === 'DELIVERY') {
    const maxRadius = businessRules.logistics?.delivery?.max_radius_miles ?? 30.0;
    const baseFee = businessRules.logistics?.delivery?.base_fee ?? 25.00;
    const maxFee = businessRules.logistics?.delivery?.max_fee ?? 75.00;

    if (distanceMiles < 0 || distanceMiles > maxRadius) {
      const error = new Error(`Delivery distance must be between 0 and ${maxRadius} miles.`);
      error.statusCode = 400;
      error.code = 'ERR_DISTANCE_OUT_OF_RANGE';
      error.field = 'delivery_distance_miles';
      error.rejectedValue = distanceMiles;
      throw error;
    }

    const calculatedFee = baseFee + ((maxFee - baseFee) / maxRadius) * distanceMiles;
    return {
      deliveryFee: Number(calculatedFee.toFixed(2)),
      fullServiceFee: 0.00
    };
  }

  const error = new Error(`Invalid service type: ${serviceType}`);
  error.statusCode = 422;
  error.code = 'ERR_INVALID_DATA_TYPE';
  error.field = 'service_type';
  error.rejectedValue = serviceType;
  throw error;
}

module.exports = {
  calculateHeartShapeSurcharge,
  calculateDryIceFee,
  calculateLogisticsFees
};
