const { businessRules } = require('../config/configLoader');

const VALID_SERVICE_TYPES = ['DELIVERY', 'FULL_SERVICE', 'PICKUP'];

/**
 * Builds a standardized validation error carrying the fields required by the
 * project's Standardized Error Contract (code, message, field, rejectedValue).
 * @param {string} message - Human-readable error description
 * @param {number} statusCode - HTTP status code to return
 * @param {string} code - Machine-readable error code
 * @param {string} [field] - Name of the offending payload field
 * @param {*} [rejectedValue] - Value that failed validation
 * @returns {Error}
 */
function buildError(message, statusCode, code, field, rejectedValue) {
  const error = new Error(message);
  error.statusCode = statusCode;
  error.code = code;
  if (field !== undefined) {
    error.field = field;
  }
  if (rejectedValue !== undefined) {
    error.rejectedValue = rejectedValue;
  }
  return error;
}

/**
 * Validates a quote request payload against all business rules and returns
 * a clean, sanitized payload ready to be consumed by the pricing engine.
 * Throws a standardized error (statusCode, code, field, rejectedValue) on
 * the first validation failure encountered.
 * @param {Object} payload - Raw request body
 * @returns {Object} Sanitized payload
 */
function validateQuotePayload(payload) {
  const data = payload || {};
  const {
    total_quantity,
    heart_shaped_quantity = 0,
    service_type = 'PICKUP',
    delivery_distance_miles,
    dry_ice_blocks = 0,
    flavors = null
  } = data;

  // 1. Presence check for total_quantity (HTTP 400)
  if (total_quantity === undefined || total_quantity === null) {
    throw buildError(
      'Field "total_quantity" is required.',
      400,
      'ERR_MISSING_FIELD',
      'total_quantity',
      total_quantity
    );
  }

  // 2. Integer type check for total_quantity (HTTP 422)
  if (typeof total_quantity !== 'number' || !Number.isInteger(total_quantity)) {
    throw buildError(
      'Field "total_quantity" must be an integer.',
      422,
      'ERR_INVALID_DATA_TYPE',
      'total_quantity',
      total_quantity
    );
  }

  // 3. Minimum Order Quantity constraint (HTTP 400)
  const minOrderQty = businessRules.moq?.minimum_order_quantity ?? 50;
  if (total_quantity < minOrderQty) {
    throw buildError(
      `Minimum order quantity is ${minOrderQty} popsicles.`,
      400,
      'ERR_BELOW_MINIMUM_ORDER',
      'total_quantity',
      total_quantity
    );
  }

  // 4. Negative value checks (HTTP 422)
  if (typeof heart_shaped_quantity !== 'number' || heart_shaped_quantity < 0) {
    throw buildError(
      'Quantities cannot be negative.',
      422,
      'ERR_INVALID_DATA_TYPE',
      'heart_shaped_quantity',
      heart_shaped_quantity
    );
  }

  if (typeof dry_ice_blocks !== 'number' || dry_ice_blocks < 0) {
    throw buildError(
      'Quantities cannot be negative.',
      422,
      'ERR_INVALID_DATA_TYPE',
      'dry_ice_blocks',
      dry_ice_blocks
    );
  }

  // 5. Upper bound: heart-shaped quantity cannot exceed total quantity (HTTP 400)
  if (heart_shaped_quantity > total_quantity) {
    throw buildError(
      'Heart-shaped popsicle quantity cannot exceed total quantity.',
      400,
      'ERR_HEART_EXCEEDS_TOTAL',
      'heart_shaped_quantity',
      heart_shaped_quantity
    );
  }

  // 6. service_type enum check (HTTP 422)
  if (!VALID_SERVICE_TYPES.includes(service_type)) {
    throw buildError(
      `Invalid service type: ${service_type}`,
      422,
      'ERR_INVALID_DATA_TYPE',
      'service_type',
      service_type
    );
  }

  // 7. Conditional field: delivery_distance_miles required and bounded when DELIVERY (HTTP 400)
  let sanitizedDistanceMiles = 0;
  if (service_type === 'DELIVERY') {
    const maxRadius = businessRules.logistics?.delivery?.max_radius_miles ?? 30.0;
    const isValidDistance =
      typeof delivery_distance_miles === 'number' &&
      delivery_distance_miles >= 0 &&
      delivery_distance_miles <= maxRadius;

    if (!isValidDistance) {
      throw buildError(
        `Delivery distance must be between 0 and ${maxRadius} miles.`,
        400,
        'ERR_DISTANCE_OUT_OF_RANGE',
        'delivery_distance_miles',
        delivery_distance_miles
      );
    }
    sanitizedDistanceMiles = delivery_distance_miles;
  }

  // 8. Flavor count integrity (HTTP 400)
  let sanitizedFlavors = null;
  if (Array.isArray(flavors) && flavors.length > 0) {
    const sumFlavors = flavors.reduce((sum, item) => sum + (item.quantity || 0), 0);
    if (sumFlavors !== total_quantity) {
      throw buildError(
        `Sum of flavor quantities (${sumFlavors}) does not match total quantity (${total_quantity}).`,
        400,
        'ERR_FLAVOR_SUM_MISMATCH',
        'flavors',
        sumFlavors
      );
    }
    sanitizedFlavors = flavors;
  }

  return {
    total_quantity,
    heart_shaped_quantity,
    service_type,
    delivery_distance_miles: sanitizedDistanceMiles,
    dry_ice_blocks,
    flavors: sanitizedFlavors
  };
}

module.exports = { validateQuotePayload };
