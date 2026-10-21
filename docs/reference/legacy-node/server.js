const http = require('http');
const { handleOrderQuote } = require('./src/controllers/orderController');

const PORT = process.env.PORT || 5000;

const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');

  if (req.method === 'POST' && req.url === '/api/v1/orders/quote') {
    let rawData = '';
    req.on('data', chunk => {
      rawData += chunk;
    });

    req.on('end', () => {
      try {
        const payload = JSON.parse(rawData);
        const result = handleOrderQuote(payload);
        res.writeHead(result.statusCode);
        res.end(JSON.stringify(result.body, null, 2));
      } catch (err) {
        res.writeHead(400);
        res.end(JSON.stringify({
          success: false,
          error: {
            code: 'INVALID_JSON',
            message: 'Malformed JSON payload'
          }
        }, null, 2));
      }
    });
  } else {
    res.writeHead(404);
    res.end(JSON.stringify({
      success: false,
      error: {
        code: 'NOT_FOUND',
        message: 'Route not found'
      }
    }, null, 2));
  }
});

server.listen(PORT, () => {
  console.log(`Popssibilities Pricing Server running on http://localhost:${PORT}`);
});