const { calculateOrderQuote } = require('../services/pricingEngine');
const { validateQuotePayload } = require('../validators/quoteValidator');

/**
 * Controller to handle quote calculation requests.
 * @param {Object} payload
 * @returns {{ statusCode: number, body: Object }}
 */
function handleOrderQuote(payload) {
  try {
    const sanitizedPayload = validateQuotePayload(payload);
    const quoteData = calculateOrderQuote(sanitizedPayload);
    return {
      statusCode: 200,
      body: {
        success: true,
        data: quoteData
      }
    };
  } catch (err) {
    const statusCode = err.statusCode || 400;
    const errorBody = {
      success: false,
      error: {
        code: err.code || 'ERR_CALCULATION_FAILED',
        message: err.message
      }
    };

    if (err.field !== undefined) {
      errorBody.error.field = err.field;
    }
    if (err.rejectedValue !== undefined) {
      errorBody.error.rejected_value = err.rejectedValue;
    }

    return {
      statusCode,
      body: errorBody
    };
  }
}

module.exports = { handleOrderQuote };
