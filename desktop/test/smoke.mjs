// Smoke test: launches the real Electron shell and checks the hosted page and its lockdown.
import { _electron as electron } from 'playwright';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = [root];
if (process.env.CI || process.getuid?.() === 0) args.unshift('--no-sandbox');

const app = await electron.launch({ args });
let failed = false;
try {
  const page = await app.firstWindow();
  const pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));
  await page.waitForSelector('#drop');

  assert.match(await page.title(), /Save Editor/);
  assert.equal(await page.evaluate(() => typeof require), 'undefined', 'Node leaked into the renderer');
  assert.equal(await page.evaluate(() => typeof window.showSaveFilePicker), 'function', 'native save picker missing');
  assert.equal(await page.evaluate(() => window.open('https://example.com') === null), true, 'popup was not denied');

  await page.evaluate(() => { location.href = 'file:///'; }).catch(() => {});
  await page.waitForTimeout(500);
  assert.match(page.url(), /des_editor\.html$/, 'navigation away from the editor was not blocked');

  assert.deepEqual(pageErrors, [], 'page errors: ' + pageErrors.join('\n'));
  console.log('desktop smoke test passed');
} catch (error) {
  failed = true;
  console.error(error);
} finally {
  await app.close();
}
process.exit(failed ? 1 : 0);
