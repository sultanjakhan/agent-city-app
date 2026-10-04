const { test, expect } = require('./owner-fixture.cjs');
test('local-only mode is visible and network refresh is unavailable', async ({ page }) => {
  await page.route('**/api/state', async route => {
    const response=await route.fetch();const body=await response.json();
    body.settings.localOnly=true;
    for(const key of Object.keys(body.credentials)) body.credentials[key]=null;
    for(const key of Object.keys(body.credentialInfo)) body.credentialInfo[key]={available:null,source:'paused',canSave:false,removable:false,localOnly:true};
    await route.fulfill({response,json:body});
  });
  await page.goto('/');
  await expect(page.locator('#local-mode-notice')).toBeVisible();
  await page.locator('[data-view="models"]').click();
  await expect(page.locator('#refresh')).toBeDisabled();
  await page.locator('#language').selectOption('en');
  await expect(page.locator('#local-mode-notice')).toContainText('Local-only');
});
