const puppeteer = require('puppeteer');

(async () => {
  const browser = await puppeteer.launch({ headless: 'new' });
  const page = await browser.newPage();
  
  page.on('console', msg => {
    console.log(`[CONSOLE ${msg.type()}]`, msg.text());
  });
  
  page.on('pageerror', error => {
    console.log('[PAGE ERROR]', error.message);
  });
  
  page.on('error', error => {
    console.log('[ERROR]', error.message);
  });

  await page.goto('http://localhost:7600/', { waitUntil: 'networkidle2' });
  
  // Click Proxy Pool tab
  console.log('Switching to Proxy Pool tab...');
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'));
    const proxyTab = btns.find(b => b.textContent.includes('Proxy Pool'));
    if (proxyTab) proxyTab.click();
  });
  
  await new Promise(r => setTimeout(r, 1000));
  
  // Click Import button
  console.log('Clicking Import button...');
  await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('button'));
    const importBtn = btns.find(b => b.textContent.includes('Import'));
    if (importBtn) importBtn.click();
  });
  
  await new Promise(r => setTimeout(r, 2000));
  
  const bodyHtml = await page.evaluate(() => document.body.innerHTML);
  console.log('--- DOM START ---');
  console.log(bodyHtml.substring(0, 500) + '... (truncated)');
  
  const modalCount = await page.evaluate(() => document.querySelectorAll('.modal').length);
  console.log('Number of .modal elements:', modalCount);
  
  const modalHtml = await page.evaluate(() => {
    const m = document.querySelector('.modal');
    return m ? m.innerHTML : 'No modal found';
  });
  console.log('--- MODAL HTML ---');
  console.log(modalHtml);
  
  await page.screenshot({ path: 'puppeteer_test.png' });
  console.log('Done.');
  await browser.close();
})();
