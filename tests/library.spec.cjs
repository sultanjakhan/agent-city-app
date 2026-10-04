const { test, expect } = require('./owner-fixture.cjs');

const seedProjects = [
  { id: 'supermemory', name: 'Supermemory', description: { ru: 'Memory layer', en: 'Memory layer' }, useCases: [{ ru: 'Context', en: 'Context' }], category: 'memory', status: 'reference', repoUrl: 'https://github.com/supermemoryai/supermemory', docsUrl: 'https://docs.supermemory.ai/' },
  { id: 'chroma', name: 'Chroma', description: { ru: 'Retrieval', en: 'Retrieval' }, useCases: [{ ru: 'Index', en: 'Index' }], category: 'retrieval', status: 'reference', repoUrl: 'https://github.com/chroma-core/chroma', docsUrl: 'https://docs.trychroma.com/' },
  { id: 'ragas', name: 'Ragas', description: { ru: 'Evaluation', en: 'Evaluation' }, useCases: [{ ru: 'Evaluation', en: 'Evaluation' }], category: 'evals', status: 'reference', repoUrl: 'https://github.com/vibrantlabsai/ragas', docsUrl: 'https://docs.ragas.io/' },
  { id: 'mcp-registry', name: 'MCP Registry', description: { ru: 'MCP', en: 'MCP' }, useCases: [{ ru: 'Catalogue', en: 'Catalogue' }], category: 'mcp', status: 'reference', repoUrl: 'https://github.com/modelcontextprotocol/registry', docsUrl: 'https://registry.modelcontextprotocol.io/docs' },
];

function clone(value) { return JSON.parse(JSON.stringify(value)); }

async function routeProjects(page) {
  const state = { projects: clone(seedProjects), revision: 'fixture-rev-0', saves: [] };
  await page.route('**/api/extensions**', async route => {
    const request = route.request();
    if (request.method() === 'GET') return route.fulfill({ json: { schemaVersion: 1, projects: state.projects, revision: state.revision } });
    if (request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/api/extensions/save')) {
      const payload = request.postDataJSON();
      expect(payload.revision).toBe(state.revision);
      state.saves.push(payload.project);
      const index = state.projects.findIndex(project => project.id === payload.project.id);
      if (index === -1) state.projects.push(payload.project); else state.projects[index] = payload.project;
      state.revision = `fixture-rev-${state.saves.length}`;
      return route.fulfill({ json: { schemaVersion: 1, projects: state.projects, revision: state.revision } });
    }
    return route.continue();
  });
  return state;
}

async function openProjects(page) {
  await page.goto('/');
  await page.locator('[data-view="extensions"]').click();
  await expect(page.locator('#extensions-view')).toBeVisible();
}

test.describe('project library', () => {
  test('saves a project through the local fixture API', async ({ page }) => {
    await openProjects(page);
    await page.locator('#add-project').click();
    await page.locator('#project-name').fill('Fixture project');
    await page.locator('#project-repo').fill('https://github.com/example/fixture-project');
    await page.locator('#project-docs').fill('https://github.com/example/fixture-project/docs');
    await page.locator('#project-ru').fill('Fixture description');
    await page.locator('#project-en').fill('Fixture description');
    await page.locator('#project-cases-ru').fill('Fixture case');
    await page.locator('#project-cases-en').fill('Fixture case');
    await page.locator('#project-category').selectOption('other');
    await page.locator('#save-project').click();
    await expect(page.getByRole('heading', { name: 'Fixture project', exact: true })).toBeVisible();
  });

  test('shows four reference cards and projects navigation in RU and EN', async ({ page }) => {
    await routeProjects(page); await openProjects(page);
    await expect(page.locator('.library-row')).toHaveCount(4);
    await expect(page.locator('.library-row h2')).toContainText(['Supermemory', 'Chroma', 'Ragas', 'MCP Registry']);
    await expect(page.locator('[data-view="extensions"]')).toBeVisible();
    await page.locator('#language').selectOption('en');
    await expect(page.locator('[data-view="extensions"]')).toContainText('Extensions');
    await expect(page.locator('#add-project')).toContainText('Add');
  });

  test('adds a project through the form, edits it, and keeps it after reload', async ({ page }) => {
    const api = await routeProjects(page); await openProjects(page);
    await page.locator('#add-project').click();
    await page.locator('#project-name').fill('Local Memory');
    await page.locator('#project-repo').fill('https://github.com/example/local-memory');
    await page.locator('#project-docs').fill('https://github.com/example/local-memory/docs');
    await page.locator('#project-ru').fill('Russian description');
    await page.locator('#project-en').fill('English description');
    await page.locator('#project-cases-ru').fill('Store context');
    await page.locator('#project-cases-en').fill('Store context');
    await page.locator('#project-category').selectOption('memory');
    await page.locator('#save-project').click();
    await expect(page.getByRole('heading', { name: 'Local Memory', exact: true })).toBeVisible();
    expect(api.saves).toHaveLength(1);
    const row = page.locator('.library-row').filter({ hasText: 'Local Memory' });
    await row.locator('button.text-button').click();
    await expect(page.locator('#project-dialog')).toBeVisible();
    await page.locator('#project-name').fill('Local Memory Updated');
    await page.locator('#project-en').fill('Updated local memory');
    await page.locator('#save-project').click();
    await expect(page.getByRole('heading', { name: 'Local Memory Updated', exact: true })).toBeVisible();
    expect(api.saves).toHaveLength(2);
    await page.reload(); await page.locator('[data-view="extensions"]').click();
    await expect(page.getByRole('heading', { name: 'Local Memory Updated', exact: true })).toBeVisible();
  });

  test('keeps an unsaved project draft while state polling runs', async ({ page }) => {
    await routeProjects(page); await openProjects(page); await page.locator('#add-project').click();
    await page.locator('#project-name').fill('Draft survives poll');
    await page.locator('#project-ru').fill('Draft description');
    await page.evaluate(() => load());
    await expect(page.locator('#project-name')).toHaveValue('Draft survives poll');
    await expect(page.locator('#project-ru')).toHaveValue('Draft description');
  });

  test('locks extension fields while saving and restores the draft after failure', async ({ page }) => {
    await routeProjects(page); await openProjects(page);
    await page.locator('.library-row').first().locator('button.text-button').click();
    await page.locator('#project-name').fill('Retained draft');
    let release;
    const responseGate = new Promise(resolve => { release = resolve; });
    await page.route('**/api/extensions/save', async route => {
      await responseGate;
      await route.fulfill({status: 503, json: {error: 'Temporary fixture failure'}});
    });
    const saving = page.waitForRequest('**/api/extensions/save');
    await page.locator('#save-project').click(); await saving;
    await expect(page.locator('#project-name')).toBeDisabled();
    await expect(page.locator('#project-en')).toBeDisabled();
    await expect(page.locator('#close-project')).toBeDisabled();
    release();
    await expect(page.locator('#project-name')).toBeEnabled();
    await expect(page.locator('#project-name')).toHaveValue('Retained draft');
    await expect(page.locator('#project-dialog')).toBeVisible();
  });
});

test('filters workspace skills and treats an installed skill as readonly', async ({ page }) => {
  const saves = [];
  await page.route('**/api/skill-inventory**', async route => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('id') === 'readonly-fixture') return route.fulfill({ json: { id: 'readonly-fixture', name: 'Installed fixture', status: 'installed', editable: false, path: 'C:\\synthetic\\SKILL.md', content: '# Read only', revision: 'a'.repeat(64), history: [] } });
    return route.fulfill({ json: { schemaVersion: 1, skills: [
      { id: 'sample', slug: 'sample', name: 'sample', status: 'workspace', editable: true, path: 'workspace/sample/SKILL.md' },
      { id: 'readonly-fixture', name: 'Installed fixture', status: 'installed', editable: false, path: 'C:\\synthetic\\SKILL.md' },
    ] } });
  });
  await page.route('**/api/skills/save', async route => { saves.push(route.request().postDataJSON()); return route.fulfill({ status: 500, json: { error: 'unexpected save' } }); });
  await page.goto('/'); await page.locator('[data-view="skills"]').click();
  await page.locator('#skills-origin').selectOption('workspace');
  await expect(page.locator('#skills-list .library-row')).toHaveCount(1);
  await expect(page.locator('#skills-list')).toContainText('sample');
  await page.locator('#skills-origin').selectOption('installed');
  await expect(page.locator('#skills-list .library-row')).toHaveCount(1);
  await page.getByRole('button', { name: 'Installed fixture', exact: true }).click();
  await expect(page.locator('#skill-dialog')).toBeVisible();
  await expect(page.locator('#skill-content')).toHaveAttribute('readonly', '');
  await expect(page.locator('#save-skill')).toBeDisabled();
  await expect(page.locator('#skill-dialog .skill-actions')).toBeHidden();
  expect(saves).toHaveLength(0);
});

for (const width of [390, 610]) {
  test(`navigation fits at ${width}px and compact labels remain available`, async ({ page }) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 950 }); await page.goto('/');
    if (!(await page.locator('body').evaluate(node => node.classList.contains('nav-collapsed')))) await page.locator('#toggle-nav').click();
    await expect(page.locator('[data-view] .compact-label').first()).toBeVisible();
    const metrics = await page.locator('aside.app-header').evaluate(node => ({ bottom: node.getBoundingClientRect().bottom, viewport: window.innerHeight, scrollWidth: document.documentElement.scrollWidth, width: window.innerWidth }));
    expect(metrics.bottom).toBeLessThanOrEqual(metrics.viewport + 1); expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.width);
  });
}
