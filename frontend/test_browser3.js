const { chromium } = require('playwright');
(async () => {
    const browser = await chromium.launch({ headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
    const page = await browser.newPage();

    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('websocket', ws => {
        console.log(`WebSocket opened: ${ws.url()}`);
        ws.on('framesent', event => console.log('WS SENT:', typeof event.payload === 'string' ? event.payload.substring(0, 50) : 'binary'));
        ws.on('framereceived', event => console.log('WS RECV:', typeof event.payload === 'string' ? event.payload.substring(0, 50) : 'binary'));
        ws.on('close', () => console.log('WS CLOSED'));
    });

    await page.goto('http://localhost:3000');
    await page.waitForTimeout(1000);
    await page.click('button:has-text("Simulate Car Arrival")');
    console.log("Clicked Simulate Car Arrival");
    await page.waitForTimeout(6000);
    await browser.close();
})();
