const { chromium } = require('playwright');
(async () => {
    const browser = await chromium.launch({ headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
    const page = await browser.newPage();
    page.on('console', msg => console.log('PAGE LOG:', msg.text()));
    page.on('pageerror', error => console.log('PAGE ERROR:', error.message));
    
    await page.goto('http://localhost:3000');
    console.log("Navigated to page");
    await page.waitForTimeout(1000);
    
    try {
        await page.click('button:has-text("Simulate Car Arrival")');
        console.log("Clicked Simulate Car Arrival");
    } catch(e) {
        console.log("Could not find Simulate Car Arrival button", e);
    }
    await page.waitForTimeout(15000);
    await browser.close();
})();
