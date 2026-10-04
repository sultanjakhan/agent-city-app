const { test, expect } = require('./owner-fixture.cjs');

async function openView(page, view) {
  await page.goto('/');
  await page.locator(`[data-view="${view}"]`).click();
}

test('settings tabs support keyboard navigation, persistence and rule drafts survive switching', async ({ page }) => {
  await openView(page, 'settings');
  await expect(page.locator('#settings-connectors')).toBeVisible();
  await expect(page.locator('#cicada-source option')).not.toHaveCount(1);
  await page.locator('#cicada-source').selectOption('');
  await page.locator('#settings-tab-catalogs').click();
  await expect(page.locator('#settings-catalogs')).toBeVisible();
  await expect(page.locator('#settings-connectors')).toBeHidden();
  await page.locator('#settings-tab-catalogs').press('ArrowRight');
  await expect(page.locator('#settings-tab-agents')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#settings-tab-agents')).toBeFocused();
  await expect(page.locator('#settings-agents')).toBeVisible();
  await page.locator('#language').selectOption('en');
  await expect(page.locator('#settings-tab-agents')).toHaveText('Agents');
  await expect(page.locator('#settings-agents')).toContainText('Agent City provides context on request.');
  await expect(page.locator('#rules-agent-status')).toContainText('The Codex connection instruction');
  await page.locator('#language').selectOption('ru');
  await page.locator('#settings-tab-connectors').click();
  await page.evaluate(() => load());
  await expect(page.locator('#cicada-source')).toHaveValue('');

  await page.locator('[data-view="rules"]').click();
  await page.locator('#rules-content').fill('draft retained while changing settings');
  await page.locator('[data-view="settings"]').click();
  await page.locator('#settings-tab-data').click();
  await page.locator('[data-view="rules"]').click();
  await expect(page.locator('#rules-content')).toHaveValue('draft retained while changing settings');
  await page.locator('#discard-rules').click();
  await page.reload();
  await page.locator('[data-view="settings"]').click();
  await expect(page.locator('#settings-tab-data')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#settings-data')).toBeVisible();
  await page.evaluate(() => localStorage.removeItem('agentcity-settings-tab'));
});

test('inline key draft survives state polling', async ({ page }) => {
  await openView(page, 'connections');await page.locator('[data-provider="openrouter"] .provider-heading').click();
  const form = page.locator('.inline-key-form[data-key-provider="openrouter"]');
  await expect(form).toBeVisible();
  const input = form.locator('input[type="password"]');
  await input.fill('synthetic-key-for-polling-1234');
  await page.evaluate(() => load());
  await expect(input).toHaveValue('synthetic-key-for-polling-1234');
  await page.locator('#language').selectOption('en');
  await expect(form.locator('button')).toHaveText('Save and connect');
  await expect(input).toHaveValue('synthetic-key-for-polling-1234');
  await page.locator('#language').selectOption('ru');
  await expect(form.locator('button')).toHaveText('Сохранить и подключить');
});

test('synthetic inline key save refreshes only its provider catalog', async ({ page }) => {
  const refreshes = [], key = 'synthetic-key-for-save-1234';
  page.on('request', request => {if(new URL(request.url()).pathname==='/api/refresh')refreshes.push(request.postDataJSON().target);});
  await openView(page, 'connections');await page.locator('[data-provider="openrouter"] .provider-heading').click();
  const form = page.locator('.inline-key-form[data-key-provider="openrouter"]');
  await form.locator('input[type="password"]').fill(key);
  await form.locator('button[type="submit"]').click();
  await expect.poll(() => refreshes).toEqual(['openrouter']);
  await expect(form.locator('input')).toHaveValue('');
  await page.reload();await page.locator('[data-view=connections]').click();
  await expect(page.locator('.connection-row[data-provider=openrouter]')).toContainText('Ключ сохранён');
  expect(await page.evaluate(()=>fetch('/api/state').then(r=>r.text()))).not.toContain(key);
  expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain(key);
});

test('rules preview/save survives reload and blocks a dirty scope switch', async ({ page }) => {
  await openView(page, 'rules');
  const scope = page.locator('#rules-scope');
  await expect(scope.locator('option')).toHaveCount(2);
  const repoId = await scope.locator('option').nth(1).getAttribute('value');
  await page.locator('#rules-content').fill('global synthetic rule');
  await scope.selectOption(repoId);
  await expect(scope).toHaveValue('global');
  await expect(page.locator('#rules-message')).toContainText('Сначала сохрани');
  await page.locator('#preview-rules').click();
  await expect(page.locator('#rules-diff-section')).toBeVisible();
  await expect(page.locator('#save-rules')).toBeEnabled();
  await page.locator('#save-rules').click();
  await page.reload();
  await page.locator('[data-view="rules"]').click();
  await expect(page.locator('#rules-content')).toHaveValue('global synthetic rule');
});

test('rules conflict keeps the draft, refreshes its base and allows re-preview/save', async ({ page }) => {
  await openView(page, 'rules');
  const draft = 'draft after an external rules update';
  await page.locator('#rules-content').fill(draft);
  await page.locator('#preview-rules').click();
  await expect(page.locator('#save-rules')).toBeEnabled();

  const externalStatus = await page.evaluate(async () => {
    const state = await (await fetch('/api/state')).json();
    const current = await (await fetch('/api/rules?scope=global')).json();
    const response = await fetch('/api/rules/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Agent-City': '1', 'X-Agent-City-Token': state.csrfToken},
      body: JSON.stringify({scope: 'global', content: 'external rules update', revision: current.revision}),
    });
    return response.status;
  });
  expect(externalStatus).toBe(200);

  await page.locator('#save-rules').click();
  await expect(page.locator('#rules-message')).toContainText('Правила изменились извне');
  await expect(page.locator('#rules-content')).toHaveValue(draft);
  await expect(page.locator('#save-rules')).toBeDisabled();
  await page.locator('#preview-rules').click();
  await expect(page.locator('#rules-diff')).toContainText('-external rules update');
  await expect(page.locator('#save-rules')).toBeEnabled();
  await page.locator('#save-rules').click();
  await page.locator('#rules-context-section summary').click();
  await expect(page.locator('#rules-effective')).toContainText(draft);
});

test('repository profile persists selected extension and exposes instructions and rules', async ({ page }) => {
  await openView(page, 'repos');
  const row = page.locator('.repo-row').filter({ hasText: 'fixture-repo' });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: 'fixture-repo', exact: true }).click();
  await expect(page.locator('#repo-dialog')).toBeVisible();
  const checkbox = page.locator('#repo-extensions input[type="checkbox"]').first();
  await checkbox.check();
  await page.locator('#save-repo-profile').click();
  await expect(page.locator('#repo-message')).toContainText('Профиль сохранён');
  await expect(page.locator('#repo-instructions')).toContainText('Keep repository instructions intact.');
  const repoId = await page.locator('#open-repo-rules').evaluate(() => currentRepo.id);
  await page.locator('#close-repo').click();
  await row.getByRole('button', { name: 'fixture-repo', exact: true }).click();
  await expect(page.locator('#repo-extensions input[type="checkbox"]').first()).toBeChecked();
  await page.locator('#open-repo-rules').click();
  await expect(page.locator('#rules-scope')).toHaveValue(repoId);
  await expect(page.locator('#rules-native-section')).toBeVisible();
  await expect(page.locator('#rules-native')).toContainText('Keep repository instructions intact.');
  await expect(page.locator('#rules-native textarea')).toHaveCount(0);
  await page.locator('#rules-content').fill('saved repository supplement');
  await page.locator('#preview-rules').click();
  await page.locator('#save-rules').click();
  await page.locator('#rules-context-section summary').click();
  await expect(page.locator('#rules-effective')).toContainText('saved repository supplement');
});

test('installed skill toggle is reversible and view stats do not become usage stats', async ({ page }) => {
  await openView(page, 'skills');
  await page.locator('#skills-origin').selectOption('installed');
  const row = page.locator('#skills-list .library-row').filter({ hasText: 'Installed test' });
  await expect(row).toBeVisible();
  await expect(row.locator('.skill-stats').first()).toContainText('Применений по отчётам: 0');
  await row.getByRole('button', { name: 'Installed test', exact: true }).click();
  await page.locator('#close-skill').click();
  const refreshed = page.locator('#skills-list .library-row').filter({ hasText: 'Installed test' });
  await expect(refreshed.locator('.skill-stats').first()).toContainText('Применений по отчётам: 0');
  await expect(refreshed.locator('.skill-stats').first()).toContainText('Просмотров: 1');
  await refreshed.getByRole('button', { name: 'Выключить в Codex', exact: true }).click();
  await expect(page.locator('#skills-list .library-row').filter({ hasText: 'Installed test' }).getByRole('button', { name: 'Включить в Codex', exact: true })).toBeVisible();
  await page.locator('#skills-list .library-row').filter({ hasText: 'Installed test' }).getByRole('button', { name: 'Включить в Codex', exact: true }).click();
  await expect(page.locator('#skills-list .library-row').filter({ hasText: 'Installed test' }).getByRole('button', { name: 'Выключить в Codex', exact: true })).toBeVisible();
});
