const http = require('http');

const testCases = [
  {
    id: 'TC-B01',
    name: 'Lower Invalid Boundary of MOQ (49 units)',
    payload: { total_quantity: 49, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 400,
    expectedErrorCode: 'ERR_BELOW_MINIMUM_ORDER'
  },
  {
    id: 'TC-B02',
    name: 'Lower Valid Boundary of MOQ (50 units - Tier 1)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.50,
    expectedTotal: 175.00,
    expectedDeposit: 87.50
  },
  {
    id: 'TC-B03',
    name: 'Adjacent Step Above MOQ (51 units - Tier 1)',
    payload: { total_quantity: 51, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.50,
    expectedTotal: 178.50,
    expectedDeposit: 89.25
  },
  {
    id: 'TC-B04',
    name: 'Upper Boundary of Tier 1 (99 units)',
    payload: { total_quantity: 99, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.50,
    expectedTotal: 346.50,
    expectedDeposit: 173.25
  },
  {
    id: 'TC-B05',
    name: 'Lower Boundary of Tier 2 (100 units)',
    payload: { total_quantity: 100, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.25,
    expectedTotal: 325.00,
    expectedDeposit: 162.50
  },
  {
    id: 'TC-B06',
    name: 'Upper Boundary of Tier 2 (199 units)',
    payload: { total_quantity: 199, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.25,
    expectedTotal: 646.75,
    expectedDeposit: 323.38
  },
  {
    id: 'TC-B07',
    name: 'Lower Boundary of Tier 3 (200 units)',
    payload: { total_quantity: 200, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedUnitPrice: 3.00,
    expectedTotal: 600.00,
    expectedDeposit: 300.00
  },
  {
    id: 'TC-B08',
    name: 'Negative Heart-Shaped Quantity (-1 units)',
    payload: { total_quantity: 50, heart_shaped_quantity: -1, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 422,
    expectedErrorCode: 'ERR_INVALID_DATA_TYPE'
  },
  {
    id: 'TC-B09',
    name: 'Zero Heart-Shaped Quantity (0 units)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedHeartSurcharge: 0.00
  },
  {
    id: 'TC-B10',
    name: 'All Items Heart-Shaped (50 of 50 units)',
    payload: { total_quantity: 50, heart_shaped_quantity: 50, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedHeartSurcharge: 25.00,
    expectedTotal: 200.00
  },
  {
    id: 'TC-B11',
    name: 'Heart Count Exceeds Total (51 on 50)',
    payload: { total_quantity: 50, heart_shaped_quantity: 51, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 400,
    expectedErrorCode: 'ERR_HEART_EXCEEDS_TOTAL'
  },
  {
    id: 'TC-B12',
    name: 'Delivery Distance Lower Boundary (0.0 miles)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'DELIVERY', delivery_distance_miles: 0.0, dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedDeliveryFee: 25.00
  },
  {
    id: 'TC-B13',
    name: 'Delivery Distance Upper Boundary (30.0 miles)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'DELIVERY', delivery_distance_miles: 30.0, dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedDeliveryFee: 75.00
  },
  {
    id: 'TC-B14',
    name: 'Delivery Distance Exceeds Boundary (30.1 miles)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'DELIVERY', delivery_distance_miles: 30.1, dry_ice_blocks: 0 },
    expectedStatus: 400,
    expectedErrorCode: 'ERR_DISTANCE_OUT_OF_RANGE'
  },
  {
    id: 'TC-B15',
    name: 'Dry Ice Blocks Lower Boundary (0 blocks)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: 0 },
    expectedStatus: 200,
    expectedDryIceFee: 0.00
  },
  {
    id: 'TC-B16',
    name: 'Negative Dry Ice Blocks (-1 blocks)',
    payload: { total_quantity: 50, heart_shaped_quantity: 0, service_type: 'PICKUP', dry_ice_blocks: -1 },
    expectedStatus: 422,
    expectedErrorCode: 'ERR_INVALID_DATA_TYPE'
  },
  {
    id: 'TC-B17',
    name: 'Flavor Quantities Sum Mismatch (48 of 50 units)',
    payload: {
      total_quantity: 50,
      heart_shaped_quantity: 0,
      service_type: 'PICKUP',
      dry_ice_blocks: 0,
      flavors: [{ flavor_name: 'Strawberry', quantity: 25 }, { flavor_name: 'Mango', quantity: 23 }]
    },
    expectedStatus: 400,
    expectedErrorCode: 'ERR_FLAVOR_SUM_MISMATCH'
  },
  {
    id: 'TC-B18',
    name: 'Penny Rounding and Deposit Split Balance Verification',
    payload: { total_quantity: 51, heart_shaped_quantity: 1, service_type: 'DELIVERY', delivery_distance_miles: 28.5, dry_ice_blocks: 1 },
    expectedStatus: 200,
    verifyRoundingSum: true
  }
];

function runRequest(test) {
  return new Promise((resolve) => {
    const data = JSON.stringify(test.payload);
    const req = http.request({
      hostname: 'localhost',
      port: 5000,
      path: '/api/v1/orders/quote',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data)
      }
    }, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => {
        try {
          const parsed = JSON.parse(body);
          resolve({ test, actualStatus: res.statusCode, body: parsed });
        } catch (e) {
          resolve({ test, actualStatus: res.statusCode, body: null });
        }
      });
    });

    req.on('error', (err) => {
      resolve({ test, error: err.message });
    });

    req.write(data);
    req.end();
  });
}

async function startTestSuite() {
  console.log('\n========================================================================');
  console.log('      POPSSIBILITIES - COMPLETE 18 BOUNDARY TEST CASES SUITE            ');
  console.log('========================================================================\n');

  let passedCount = 0;

  for (const tc of testCases) {
    const res = await runRequest(tc);

    if (res.error) {
      console.log(`❌ [FAIL] ${tc.id}: ${tc.name} -> Connection Error: ${res.error}`);
      continue;
    }

    let isPassed = false;
    let detailMsg = '';

    if (tc.expectedStatus === 400 || tc.expectedStatus === 422) {
      const statusMatch = res.actualStatus === tc.expectedStatus;
      const codeMatch = res.body?.error?.code === tc.expectedErrorCode;
      isPassed = statusMatch && codeMatch;
      detailMsg = `Status: ${res.actualStatus}, Code: ${res.body?.error?.code || 'None'}`;
    } else if (tc.expectedStatus === 200) {
      isPassed = res.actualStatus === 200;
      const b = res.body?.data || {};

      if (tc.expectedUnitPrice !== undefined && b.tier_applied?.unit_price !== tc.expectedUnitPrice) isPassed = false;
      if (tc.expectedTotal !== undefined && b.pricing_summary?.total_amount !== tc.expectedTotal) isPassed = false;
      if (tc.expectedDeposit !== undefined && b.pricing_summary?.deposit_due_now !== tc.expectedDeposit) isPassed = false;
      if (tc.expectedHeartSurcharge !== undefined && b.breakdown?.heart_shaped_surcharge !== tc.expectedHeartSurcharge) isPassed = false;
      if (tc.expectedDeliveryFee !== undefined && b.breakdown?.delivery_fee !== tc.expectedDeliveryFee) isPassed = false;
      if (tc.expectedDryIceFee !== undefined && b.breakdown?.dry_ice_amount !== tc.expectedDryIceFee) isPassed = false;

      if (tc.verifyRoundingSum) {
        const sumDepositAndBalance = Number((b.pricing_summary?.deposit_due_now + b.pricing_summary?.balance_due_later).toFixed(2));
        if (sumDepositAndBalance !== b.pricing_summary?.total_amount) {
          isPassed = false;
        }
      }

      detailMsg = `Status: ${res.actualStatus}, Total: $${b.pricing_summary?.total_amount || 0}, Deposit: $${b.pricing_summary?.deposit_due_now || 0}`;
    }

    if (isPassed) {
      passedCount++;
      console.log(`✅ [PASS] ${tc.id}: ${tc.name} -> (${detailMsg})`);
    } else {
      console.log(`❌ [FAIL] ${tc.id}: ${tc.name} -> (${detailMsg})`);
    }
  }

  console.log('\n------------------------------------------------------------------------');
  console.log(`Total: ${testCases.length} | Passed: ${passedCount} | Failed: ${testCases.length - passedCount}`);
  console.log('========================================================================\n');
}

startTestSuite();