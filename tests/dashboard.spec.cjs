const { test, expect } = require('./owner-fixture.cjs');

test('live unbound reports remain accessible in history without a dashboard disclosure',async({page})=>{
 await page.route('**/api/dashboard',async route=>{const body=await(await route.fetch()).json();body.cicada.tasks=[];body.cicada.historyTasks=[];body.runs=[{runId:'synthetic-unbound-live',taskKey:null,agent:'codex',model:null,status:'running',sequence:1,updatedAt:new Date().toISOString(),mcpCalls:null,skills:[],history:[]}];delete body.cicada.availableTasks;await route.fulfill({json:body});});
 await page.goto('/#dashboard');await expect(page.locator('#dashboard-view details,#dashboard-view summary')).toHaveCount(0);await expect(page.locator('#work-registry')).toBeHidden();
 await page.locator('#dashboard-history-tab').click();const row=page.locator('.task-widget-row').filter({hasText:'synthetic-unbound-live'});await expect(row).toContainText('Работает');await row.locator('.task-widget-open').click();await expect(page.locator('#dashboard-task-dialog')).toContainText('Не привязан к задаче Cicada.');await expect(page.locator('#dashboard-task-dialog details,#dashboard-task-dialog summary')).toHaveCount(0);
});

test('compact report keeps totals, six stages and fixed actions usable in both languages',async({page},testInfo)=>{
 const key='cicada-0123456789abcdef-compact';let revision=0;
 await page.route('**/api/dashboard',async route=>{
  const body=await (await route.fetch()).json();body.cicada.tasks=[];body.cicada.historyTasks=[{taskKey:key,title:'Проверка отчёта задачи',completed:true,actualMinutes:14,stageLabel:'Приёмка'}];
  body.runs=Array.from({length:6},(_,i)=>({runId:'compact-'+i,sequence:1,taskKey:key,agent:'codex',model:i===3?'small-model':null,stage:`${i+1}. ${['Анализ','План','Подготовка','Извлечение полей','Проверка результата','Проверка MCP'][i]}`,status:i===4?'error':'done',inputTokens:i===3?265:null,outputTokens:i===3?1656:null,mcpCalls:[],skills:[],updatedAt:'2026-09-27T08:01:00Z',firstReportedAt:'2026-09-27T08:00:00Z'}));
  if(revision)body.runs.push({...body.runs[0],runId:'added',stage:'Новый этап',firstReportedAt:'2026-09-27T07:00:00Z'});
  delete body.cicada.availableTasks;await route.fulfill({json:body});
 });
 await page.setViewportSize({width:900,height:900});await page.goto('/?task='+key+'&history=1#dashboard');
 const dialog=page.locator('#dashboard-task-dialog');await expect(dialog).toBeVisible();
 expect((await dialog.locator('.report-total-value').first().innerText()).replace(/\D/g,'')).toBe('1921');
 await expect(dialog.locator('.report-total-value').last()).toHaveText('14 мин');
 await expect(dialog.locator('details,summary')).toHaveCount(0);
 const stageBoxes=await dialog.locator('.stage-report-heading').evaluateAll(nodes=>nodes.map(n=>({height:n.getBoundingClientRect().height,bottom:n.getBoundingClientRect().bottom})));
 expect(stageBoxes).toHaveLength(6);expect(Math.max(...stageBoxes.map(r=>r.height))).toBeLessThan(82);await dialog.locator('.stage-report').last().scrollIntoViewIfNeeded();
 await page.screenshot({path:testInfo.outputPath('compact-report-ru.png')});
 const review=dialog.locator('.stage-report').filter({hasText:'5. Проверка результата'});await page.locator('#copy-task-report').focus();
 revision++;await page.evaluate(()=>loadDashboard(true));
 await expect(review.locator('.run-metrics')).toHaveCount(1);await expect(page.locator('#copy-task-report')).toBeFocused();
 await expect(dialog.locator('.stage-report').filter({hasText:'Новый этап'})).toHaveCount(1);
 await page.locator('#close-dashboard-task').click();await page.locator('#language').selectOption('en');
 await page.getByRole('button',{name:'Проверка отчёта задачи',exact:true}).click();
 await expect(dialog.locator('.report-totals')).toContainText('Reported tokens');await expect(dialog.locator('.report-totals')).toContainText('14 min');
 await expect(dialog).not.toContainText('unknown usage');
 await page.setViewportSize({width:390,height:844});await expect(dialog.locator('.report-total-value').last()).toHaveText('14 min');
 expect(await dialog.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(false);
 await page.screenshot({path:testInfo.outputPath('compact-report-en-narrow.png')});
 for(const id of ['close-dashboard-task','copy-task-report']){const box=await page.locator('#'+id).boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(390);expect(box.y+box.height).toBeLessThanOrEqual(844);}
});

test('task report shows exact stage totals, failed attempts and exports the same report',async({page})=>{
 const key='cicada-0123456789abcdef-stages';
 await page.route('**/api/dashboard',async route=>{
  const body=await (await route.fetch()).json();body.cicada.tasks=[];body.cicada.historyTasks=[{taskKey:key,title:'Task stages QA',completed:true,actualMinutes:74,stageHistory:[]}];
  const make=(id,stage,model,input,output,status='done')=>({runId:id,taskKey:key,sequence:2,agent:'agent-city',model,stage,status,inputTokens:input,outputTokens:output,mcpCalls:[],skills:[],skillIds:[],firstReportedAt:'2026-09-27T08:00:00Z',updatedAt:'2026-09-27T08:01:00Z',history:[{stage,reportedAt:'2026-09-27T08:00:00Z',inputTokens:null,outputTokens:null,status:'running'},{stage,reportedAt:'2026-09-27T08:01:00Z',inputTokens:input,outputTokens:output,status}]});
  const first=make('first-run','1. Extract','model-a',20,7),second=make('second-run','1. Extract','model-b',10,3),review=make('failed-run','2. Review','model-c',null,null,'error');
  first.skillIds=['skill-aaaaaaaaaaaaaaaaaaaaaaaa'];first.skills=[{id:first.skillIds[0],name:'extract-fields'}];first.mcpCalls=[{server:'docs',tool:'fetch',calls:2}];
  second.skillIds=['skill-bbbbbbbbbbbbbbbbbbbbbbbb'];second.skills=[];second.mcpCalls=null;
  review.skillIds=['skill-cccccccccccccccccccccccc'];review.skills=[{id:review.skillIds[0],name:'qa-check'}];
  body.runs=[first,second,review];
  delete body.cicada.availableTasks;await route.fulfill({json:body});
 });
 await page.goto('/?task='+key+'&history=1#dashboard');
 const body=page.locator('#dashboard-task-body');
 await expect(body.locator('.report-total').first()).toContainText('Учтено токенов');
 await expect(body.locator('.report-total-value').first()).toHaveText('40');
 await expect(body.locator('.report-total-value').last()).toHaveText('1 ч 14 мин');
 await expect(body.locator('.report-measurements .run-metrics')).toContainText('Учтено: 30');
 await expect(body).not.toContainText('unknown usage');
 await expect(body.locator('.stage-report')).toHaveCount(2);
 const extract=body.locator('.stage-report').first();
 await expect(extract.locator(':scope > .stage-report-heading')).toContainText('40 ток.');
 await expect(extract.locator(':scope > .stage-report-heading')).toContainText('model-a, model-b');
 await expect(extract.locator(':scope > .stage-report-heading .stage-skills')).toHaveText('Навыки: extract-fields, skill-bbbbbbbbbbbbbbbbbbbbbbbb');
 await expect(extract.locator(':scope > .stage-report-heading .stage-mcp')).toHaveText('MCP: fetch × 2 · частично');
 await expect(extract.locator(':scope > .stage-report-heading')).not.toContainText('qa-check');
 await expect(extract.locator('article.run-row:not(.single-attempt)')).toHaveCount(2);
 const review=body.locator('.stage-report').last();
 await expect(review.locator(':scope > .stage-report-heading .stage-skills')).toHaveText('Навыки: qa-check');
 await expect(review.locator(':scope > .stage-report-heading .stage-mcp')).toHaveText('MCP: 0');
 await expect(review.locator('article.run-row:not(.single-attempt)')).toHaveCount(0);
 await expect(review.locator('.single-attempt .run-metrics')).toBeVisible();
 await expect(review).toContainText('Ошибка исполнителя. Причина не сообщена');
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.testReport=text;}}}));
 await page.getByRole('button',{name:'Скопировать отчёт',exact:true}).click();
 const report=await page.evaluate(()=>window.testReport);
 expect(report).toContain('Task stages QA');expect(report).toContain('1. Extract');expect(report).toContain('Вход: 30 · Выход: 10');expect(report).toContain('model-c');expect(report).toContain('Ошибка исполнителя. Причина не сообщена в отчёте.');expect(report).toContain('Навыки:');expect(report).toContain('Запусков: 3');expect(report).toContain('Время в Cicada: 1 ч 14 мин');
 const extractText=report.split('\n1. Extract\n')[1].split('\n2. Review\n')[0];expect(extractText).toContain('extract-fields');expect(extractText).toContain('docs / fetch × 2');expect(extractText).not.toContain('qa-check');
 await page.setViewportSize({width:390,height:844});
 const metrics=await body.evaluate(el=>({overflow:el.scrollWidth>el.clientWidth}));expect(metrics.overflow).toBe(false);
 await page.locator('#copy-task-id').focus();
 await page.evaluate(()=>renderDashboardTask());
 await expect(page.locator('#copy-task-id')).toBeFocused();
 await expect(body.locator('details,summary')).toHaveCount(0);
 await body.evaluate(el=>{el.scrollTop=el.scrollHeight;});
 for(const id of ['close-dashboard-task','copy-task-report']){const box=await page.locator('#'+id).boundingBox();expect(box.y).toBeGreaterThanOrEqual(0);expect(box.y+box.height).toBeLessThanOrEqual(844);}
 await page.locator('#close-dashboard-task').click();
 await expect(page.locator('.dashboard-task .status')).toHaveText('Неудачных попыток: 1');
});

test('old cumulative snapshots have overall usage and no invented stage splits',async({page})=>{
 const key='cicada-0123456789abcdef-legacy';
 await page.route('**/api/dashboard',async route=>{
  const body=await (await route.fetch()).json();body.cicada.tasks=[];body.cicada.historyTasks=[];
  body.runs=[{runId:'legacy-0001',taskKey:key,sequence:2,agent:'agent-city',model:'legacy-model',stage:'Verify',status:'done',inputTokens:265,outputTokens:1368,mcpCalls:null,skills:[],skillIds:[],updatedAt:'2026-09-27T08:01:00Z',history:[{stage:'Infer',reportedAt:'2026-09-27T08:00:00Z'},{stage:'Verify',reportedAt:'2026-09-27T08:01:00Z',inputTokens:265,outputTokens:1368}]}];
  delete body.cicada.availableTasks;await route.fulfill({json:body});
 });
 await page.goto('/?task='+key+'&history=1#dashboard');
 const body=page.locator('#dashboard-task-body');await expect(body.locator('.report-measurements .run-metrics')).toContainText('Вход: 265 · Выход: 1368');
 await expect(body.locator('.stage-report:not(.unallocated-runs)')).toHaveCount(0);
 await expect(body.locator('.unallocated-runs > h3')).toHaveText('Ещё отчёты без этапов: 1');
 await expect(body.locator('.report-total-value').last()).toHaveText('—');
});

test('history groups completed executors, opens a shared link and keeps unknown tokens',async({page})=>{
 const key='cicada-0123456789abcdef-history-task';
 await page.route('**/api/dashboard',async route=>{
  const body=await (await route.fetch()).json();
  body.cicada.tasks=[];body.cicada.historyTasks=[{taskKey:key,title:'Completed QA task',completed:true,stageLabel:'Acceptance',stageHistory:[{stageLabel:'Analysis',at:'2026-09-27T08:00:00Z'}]}];
  const base={taskKey:key,status:'done',updatedAt:'2026-09-27T09:00:00Z',skillIds:[],skills:[],mcpCalls:[],history:[]};
  body.runs=[{...base,runId:'qa-root-001',agent:'codex',model:null,inputTokens:null,outputTokens:null},{...base,runId:'qa-worker-001',agent:'agent-city',model:'synthetic-small-model',inputTokens:265,outputTokens:1368}];
  delete body.cicada.availableTasks;await route.fulfill({json:body});
 });
 await page.goto('/?task='+key+'&history=1#dashboard');
 await expect(page.locator('#dashboard-history-tab')).toHaveAttribute('aria-selected','true');
 await expect(page.locator('#dashboard-task-dialog')).toBeVisible();
 await expect(page.locator('#dashboard-task-title')).toHaveText('Completed QA task');
 await expect(page.locator('.run-row')).toHaveCount(2);
 await expect(page.locator('.run-row').first()).toContainText('Вход: — · Выход: —');
 await expect(page.locator('.run-row').last()).toContainText('1368');
 await expect(page.locator('#dashboard-task-body')).toContainText('Задача завершена в Cicada');
 await page.locator('#close-dashboard-task').click();
 await expect(page.locator('.dashboard-task')).toHaveCount(1);
  await page.locator('#dashboard-current-tab').click();
  await expect(page.locator('.dashboard-task')).toHaveCount(0);
  const currentUrl=page.url();
  await page.locator('#dashboard-search').fill('http://127.0.0.1:47831/?task='+key+'&history=1#dashboard');
  await page.locator('#dashboard-search').press('Enter');
  await expect(page.locator('#dashboard-task-dialog')).toBeVisible();
  await expect(page.locator('#dashboard-task-title')).toHaveText('Completed QA task');
  expect(page.url()).toBe(currentUrl);
  await page.locator('#close-dashboard-task').click();
  await page.locator('#dashboard-current-tab').click();
  await page.locator('#dashboard-current-tab').press('ArrowRight');
 await expect(page.locator('#dashboard-history-tab')).toBeFocused();
 await expect(page.locator('.dashboard-task')).toHaveCount(1);
 await page.locator('#language').selectOption('en');
 await expect(page.locator('#dashboard-history-tab')).toHaveText('Run history');
 await page.reload();
 await expect(page.locator('#dashboard-task-title')).toHaveText('Completed QA task');
});

test('history retains metadata with unavailable task titles and escapes provider data',async({page})=>{
 await page.route('**/api/dashboard',async route=>{
  const body=await (await route.fetch()).json();body.cicada.tasks=[];delete body.cicada.historyTasks;
  body.runs=[{runId:'old-server-run',taskKey:'cicada-0123456789abcdef-removed',agent:'codex',model:'<img src=x onerror=alert(1)>',status:'error',updatedAt:'2026-09-27T09:00:00Z',inputTokens:null,outputTokens:null,skillIds:[],skills:[],mcpCalls:null}];
  delete body.cicada.availableTasks;await route.fulfill({json:body});
 });
 await page.goto('/?history=1#dashboard');
 await expect(page.locator('.dashboard-task')).toContainText('Отчёты сохранены');
 await expect(page.locator('.dashboard-task img')).toHaveCount(0);
 await page.locator('.dashboard-task .model-title').click();
 await expect(page.locator('#dashboard-task-body')).toContainText('Нет данных');
 await expect(page.locator('#dashboard-task-body img')).toHaveCount(0);
});

test('cloud connector lives in settings, imports a profile and renders status without its secrets',async({page})=>{
  let connected=false,received;
  const profile={profile:'agent-city-activity-v1',endpoint:'https://agent-city-sync-v1.example.workers.dev',device:'device-test',token:'synthetic-token',key:'synthetic-key'};
  await page.route('**/api/cloud',route=>route.fulfill({json:{configured:connected,state:connected?'connected':'not_configured',endpoint:connected?profile.endpoint:null,device:connected?profile.device:null,lastSync:connected?new Date().toISOString():null,error:null,remoteDevices:[]}}));
  await page.route('**/api/cloud/profile',route=>{received=route.request().postDataJSON();connected=true;return route.fulfill({json:{configured:true}});});
  await page.goto('/');
  await expect(page.locator('#dashboard-connector')).toHaveCount(0);
  await page.locator('[data-view="settings"]').click();
  await expect(page.locator('#cloud-status')).toContainText('Облако не подключено');
  await page.locator('#cloud-profile-file').setInputFiles({name:'profile.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(profile))});
  await expect(page.locator('#cloud-status')).toContainText('Синхронизировано');
  expect(received).toEqual(profile);
  await expect(page.locator('#cloud-profile-file')).toHaveValue('');
  await expect(page.locator('body')).not.toContainText(profile.token);
  await expect(page.locator('body')).not.toContainText(profile.key);
  await page.locator('#language').selectOption('en');
  await expect(page.locator('#cloud-settings')).toContainText('Mac and PC sync');
});

test('dashboard automatically refreshes task stages and renders reported MCP counters',async({page})=>{
  let calls=0;
  await page.route('**/api/dashboard',async route=>{
    const body=await (await route.fetch()).json();calls++;
    if(body.cicada.tasks[0])body.cicada.tasks[0].stageLabel=calls>1?'New actual stage':'Initial actual stage';
    body.runs=[{runId:'actual-run-01',taskKey:null,agent:'codex',status:'running',model:null,updatedAt:new Date().toISOString(),skills:[],mcpCalls:[{server:'docs',tool:'search',calls:3}],inputTokens:null,outputTokens:null}];
    delete body.cicada.availableTasks;await route.fulfill({json:body});
  });
  await selectSource(page,'production');await page.goto('/');
  await expect(page.locator('.task-stage')).toContainText('Initial actual stage');
  await expect(page.locator('.task-stage')).toContainText('New actual stage',{timeout:8000});
  await page.locator('#dashboard-history-tab').click();await page.locator('.task-widget-row').filter({hasText:'actual-run-01'}).locator('.task-widget-open').click();await expect(page.locator('#dashboard-task-body')).toContainText('docs / search × 3');
});

async function selectSource(page, sourceId) {
  const settings = await (await page.request.get('/api/connectors')).json();
  const state = await (await page.request.get('/api/state')).json();
  const response = await page.request.post('/api/connectors/cicada', {
    data: { sourceId, revision: settings.revision },
    headers: { 'X-Agent-City': '1', 'X-Agent-City-Token': state.csrfToken },
  });
  expect(response.status()).toBe(200);
}

test('dashboard uses the synthetic Cicada source and exposes the current version', async ({ page }) => {
  const health = await page.request.get('/api/health');
  expect((await health.json()).version).toBe(require('../package.json').version);
  await selectSource(page, 'production');
  await page.goto('/');
  await expect(page.locator('#app-version')).toHaveText('v'+require('../package.json').version);
  await expect(page.locator('#dashboard-view')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Production task title', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Production task title', exact: true }).click();
  await expect(page.locator('#dashboard-task-dialog')).toBeVisible();
  await expect(page.locator('#dashboard-task-body')).toContainText('analysis');
  await expect(page.locator('#dashboard-task-body')).not.toContainText('private notes must not leave Cicada');
});

test('reported model, skill and nullable tokens are shown, while an old running report is marked stale', async ({ page }) => {
  await page.route('**/api/dashboard', async route => {
    const response = await route.fetch();
    const body = await response.json();
    const task = body.cicada.tasks[0];
    body.runs = [{
      runId: 'run-00000001', sequence: 1, taskKey: task.taskKey, agent: 'codex',
      model: 'synthetic-model', provider: 'synthetic-provider', stage: 'analysis', status: 'running',
      skillIds: ['skill-0123456789abcdef01234567'], inputTokens: 0, outputTokens: null,
      updatedAt: '2020-01-01T00:00:00+00:00', history: [],
      skills: [{ id: 'skill-0123456789abcdef01234567', name: 'sample' }],
    }];
    delete body.cicada.availableTasks;await route.fulfill({ json: body });
  });
  await selectSource(page, 'production');
  await page.goto('/');
  await page.getByRole('button', { name: 'Production task title', exact: true }).click();
  const body = page.locator('#dashboard-task-body');
  await expect(body).toContainText('synthetic-provider');
  await expect(body).toContainText('synthetic-model');
  await expect(body).toContainText('sample');
  await expect(body).toContainText('0');
  await expect(body).toContainText('—');
  await expect(body).toContainText('Нет свежего отчёта');
});

test('dashboard search and refresh render new task data from the API', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/dashboard', async route => {
    calls += 1;
    const response = await route.fetch();
    const body = await response.json();
    if (calls > 1) {
      body.cicada.tasks[0].title = 'Refreshed task title';
      body.cicada.tasks[0].stageLabel = 'Refreshed stage';
    }
    delete body.cicada.availableTasks;await route.fulfill({ json: body });
  });
  await selectSource(page, 'production');
  await page.goto('/');
  await page.locator('#dashboard-search').fill('Production');
  await expect(page.locator('.dashboard-task')).toHaveCount(1);
  await page.locator('#dashboard-search').fill('missing task');
  await expect(page.locator('.dashboard-task')).toHaveCount(0);
  await page.locator('#dashboard-search').fill('');
  await page.locator('#refresh').click();
  await expect(page.getByRole('button', { name: 'Refreshed task title', exact: true })).toBeVisible();
  await expect(page.locator('.task-stage')).toContainText('Refreshed stage');
});

test('dashboard escapes untrusted task fields and excludes stale reports from working filter', async ({ page }) => {
  await page.route('**/api/dashboard', async route => {
    const response = await route.fetch();
    const body = await response.json();
    const task = body.cicada.tasks[0];
    task.isActive=false;task.isPaused=true;
    task.title = '<img src=x onerror=alert(1)>';
    task.stageLabel = '<script>alert(1)</script>';
    body.runs = [{
      runId: 'run-00000002', sequence: 1, taskKey: task.taskKey, agent: 'codex',
      model: 'stale-model', provider: 'synthetic-provider', stage: 'analysis', status: 'running',
      skillIds: [], inputTokens: 0, outputTokens: null,
      updatedAt: '2020-01-01T00:00:00+00:00', history: [], skills: [],
    }];
    delete body.cicada.availableTasks;await route.fulfill({ json: body });
  });
  await selectSource(page, 'production');
  await page.goto('/');
  await expect(page.getByRole('button', { name: '<img src=x onerror=alert(1)>', exact: true })).toBeVisible();
  await expect(page.locator('.dashboard-task')).toContainText('<script>alert(1)</script>');
  await expect(page.locator('.dashboard-task img, .dashboard-task script')).toHaveCount(0);
  await page.locator('#dashboard-filter').selectOption('working');
  await expect(page.locator('.dashboard-task')).toHaveCount(0);
  await page.locator('#dashboard-filter').selectOption('all');
  await page.getByRole('button', { name: '<img src=x onerror=alert(1)>', exact: true }).click();
  const dialog = page.locator('#dashboard-task-body');
  const tokenText = await dialog.locator('.run-row .run-metrics dd').filter({ hasText: '0' }).first().textContent();
  expect(tokenText).toContain('0');
  expect([...tokenText].slice(-3).map(character => character.codePointAt(0))).toEqual([0x003a, 0x0020, 0x2014]);
});

test('reports stay bound to their source task key when switching profiles with the same source id', async ({ page }) => {
  await selectSource(page, 'production');
  const production = (await (await page.request.get('/api/dashboard')).json()).cicada.tasks[0];
  const skill = (await (await page.request.get('/api/skill-inventory')).json()).skills[0];
  const state = await (await page.request.get('/api/state')).json();
  const reported = await page.request.post('/api/runs/report', {
    data: {
      runId: 'run-00000003', sequence: 1, taskKey: production.taskKey,
      agent: 'codex', model: 'production-model', provider: 'synthetic-provider',
      stage: 'analysis', status: 'done', skillIds: [skill.id], inputTokens: 0, outputTokens: null,
    },
    headers: { 'X-Agent-City': '1', 'X-Agent-City-Token': state.csrfToken },
  });
  expect(reported.status()).toBe(200);
  try {
    await selectSource(page, 'dev');
    const dev = (await (await page.request.get('/api/dashboard')).json()).cicada.tasks[0];
    expect(dev.sourceId).toBe(production.sourceId);
    expect(dev.taskKey).not.toBe(production.taskKey);
    await page.goto('/');
    await page.getByRole('button', { name: 'DEV task title', exact: true }).click();
    await expect(page.locator('#dashboard-task-body')).not.toContainText('production-model');
    await expect(page.locator('#dashboard-task-body')).toContainText('Отчётов исполнителей пока нет');
  } finally {
    await selectSource(page, 'production');
  }
});

test('connector switches production, DEV and disconnected source across reloads', async ({ page }) => {
  await selectSource(page, 'production');
  await page.goto('/');
  await page.locator('[data-view="settings"]').click();
  const source = page.locator('#cicada-source');
  await expect(source.locator('option')).toHaveCount(3);
  await source.selectOption('dev');
  await page.locator('#save-cicada-source').click();
  await expect(page.locator('#cicada-source-message')).toContainText('Источник сохранён');
  await page.reload();
  await page.locator('[data-view="dashboard"]').click();
  await expect(page.getByRole('button', { name: 'DEV task title', exact: true })).toBeVisible();
  await page.locator('[data-view="settings"]').click();
  await page.locator('#cicada-source').selectOption('');
  await page.locator('#save-cicada-source').click();
  await page.reload();
  await page.locator('[data-view="dashboard"]').click();
  await expect(page.locator('#dashboard-empty')).toContainText('Выбери источник');
  await page.locator('[data-view="settings"]').click();
  await page.locator('#cicada-source').selectOption('production');
  await page.locator('#save-cicada-source').click();
});

test('English labels and narrow navigation remain usable at 390px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 640 });
  await selectSource(page, 'production');
  await page.goto('/');
  await page.locator('#language').selectOption('en');
  await expect(page.locator('#page-title')).toHaveText('Dashboard');
  await expect(page.locator('#dashboard-search')).toHaveAttribute('placeholder', 'Find a task');
  const metrics = await page.locator('aside.app-header').evaluate(node => {
    const rect = node.getBoundingClientRect();
    return { bottom: rect.bottom, viewport: innerHeight, overflow: document.documentElement.scrollWidth > innerWidth };
  });
  expect(metrics.bottom).toBeLessThanOrEqual(metrics.viewport + 1);
  expect(metrics.overflow).toBe(false);
  await page.locator('#toggle-nav').click();
  await expect(page.locator('#nav-backdrop')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Dashboard', exact: true })).toBeVisible();
  await page.locator('[data-view="settings"]').click();
  await expect(page.locator('#settings-view')).toBeVisible();
});
