const {test,expect}=require('./owner-fixture.cjs');
const ns='11111111-1111-4111-8111-111111111111';
function dashboard(task,runs){return {cicada:{status:'connected',source:{label:'Cicada',sourceNamespace:ns},tasks:[],availableTasks:[],historyTasks:task?[task]:[]},runs,workRegistry:{publishers:{},bindings:{}}};}
const disconnected={config:{enabled:false,scopes:['tasks:read'],staleAfterSeconds:300},tasks:{},outbox:{},receipts:{}};
async function fixtures(page,body){await page.route('**/api/dashboard',r=>r.fulfill({json:body}));await page.route('**/api/task-sync',r=>r.fulfill({json:disconnected}));}

test('selected stage is shown below its selector and copied report retains every real attempt',async({page})=>{
 const key='cicada-0123456789abcdef-stages',task={taskKey:key,title:'Task stages QA',completed:true,actualMinutes:74};
 const run=(id,stage,input,output,status='done')=>({runId:id,taskKey:key,sequence:2,agent:'Codex',model:'model-'+id,stage,status,inputTokens:input,outputTokens:output,mcpCalls:[],skills:[],updatedAt:'2026-09-27T08:01:00Z',firstReportedAt:'2026-09-27T08:00:00Z',history:[{stage,status:'running',reportedAt:'2026-09-27T08:00:00Z'},{stage,status,reportedAt:'2026-09-27T08:01:00Z'}]});
 const first=run('first','1. Extract',20,7),second=run('second','1. Extract',10,3),failed=run('failed','2. Review',null,null,'error');first.mcpCalls=[{server:'docs',tool:'fetch',calls:2}];second.mcpCalls=null;
 const data=dashboard(task,[first,second,failed]);await fixtures(page,data);await page.goto('/?task='+key+'#tasks');const screen=page.locator('#task-screen');await expect(screen).toBeVisible();await expect(screen.locator('.report-total-value').first()).toHaveText('40');await expect(screen.locator('.report-total-value').last()).toHaveText('1 ч 14 мин');await expect(screen.locator('.task-stage-choice')).toHaveCount(2);
 await screen.getByRole('tab',{name:/1. Extract/}).click();await expect(page.locator('#task-stage-details .run-row')).toHaveCount(2);await expect(page.locator('#task-stage-details')).toContainText('fetch × 2 · частично');
 const placement=await screen.evaluate(node=>({selector:node.querySelector('.task-stage-selector').getBoundingClientRect().bottom,detail:node.querySelector('#task-stage-details').getBoundingClientRect().top}));expect(placement.detail).toBeGreaterThanOrEqual(placement.selector);
 await screen.getByRole('tab',{name:/2. Review/}).click();await expect(page.locator('#task-stage-details')).toContainText('Ошибка исполнителя. Причина не сообщена');await expect(screen.locator('details,summary,aside,dialog')).toHaveCount(0);
 await page.locator('#task-stage-choice-0').focus();await page.locator('#task-stage-choice-0').press('End');await expect(page.locator('#task-stage-choice-1')).toBeFocused();await expect(page.locator('#task-stage-choice-1')).toHaveAttribute('aria-selected','true');
 await page.locator('#copy-task-report').focus();data.runs.push(run('added','0. Additional',null,null));await page.evaluate(()=>loadDashboard(true));await expect(page.locator('#copy-task-report')).toBeFocused();await expect(page.locator('#task-stage-details h3')).toHaveText('2. Review');await expect(screen.locator('.task-stage-choice')).toHaveCount(3);
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.testReport=text;}}}));await page.locator('#copy-task-report').click();const report=await page.evaluate(()=>window.testReport);expect(report).toContain('1. Extract');expect(report).toContain('2. Review');expect(report).toContain('Вход: 30 · Выход: 10');expect(report).toContain('model-failed');
 await page.setViewportSize({width:390,height:844});expect(await screen.evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(false);
});

test('legacy cumulative report has overall usage without inventing a stage split',async({page})=>{
 const key='cicada-0123456789abcdef-legacy',run={runId:'legacy-0001',taskKey:key,sequence:2,agent:'Codex',model:'legacy-model',stage:'Verify',status:'done',inputTokens:265,outputTokens:1368,mcpCalls:null,skills:[],updatedAt:'2026-09-27T08:01:00Z',history:[{stage:'Infer',reportedAt:'2026-09-27T08:00:00Z'},{stage:'Verify',reportedAt:'2026-09-27T08:01:00Z'}]};
 await fixtures(page,dashboard(null,[run]));await page.goto('/?task='+key+'#tasks');await expect(page.locator('#task-screen .report-total-value').first()).toHaveText('1 633');await expect(page.locator('#task-stage-details')).toContainText('Расход по этапам не определён');await expect(page.locator('#task-screen .task-stage-choice')).toHaveCount(1);await page.locator('#task-tab-context').click();await expect(page.locator('#task-panel-context')).toContainText('Отчёты сохранены');
});

test('task history preserves unbound reports as text without rendering provider HTML',async({page})=>{
 const run={runId:'actual-unbound',taskKey:null,agent:'Codex',model:'<img src=x onerror=alert(1)>',status:'error',sequence:1,updatedAt:'2026-09-27T08:01:00Z',mcpCalls:null,skills:[],history:[]};await fixtures(page,dashboard(null,[run]));await page.goto('/#tasks');await page.locator('#tasks-history-tab').click();await page.locator('#tasks-list .task-widget-open').click();await expect(page.locator('#task-screen')).toContainText('<img src=x onerror=alert(1)>');await expect(page.locator('#task-screen img')).toHaveCount(0);await page.locator('#task-tab-context').click();await expect(page.locator('#task-panel-context')).toContainText('Не привязан к задаче Cicada.');
});

test('live unbound reports remain available in task History without becoming Dashboard tasks',async({page})=>{
 const run={runId:'live-unbound-history',taskKey:null,sequence:1,agent:'Codex',model:null,status:'running',updatedAt:new Date().toISOString(),skills:[],mcpCalls:null,history:[]};await fixtures(page,dashboard(null,[run]));await page.goto('/#dashboard');await expect(page.locator('#dashboard-tasks .task-widget-row')).toHaveCount(0);await page.locator('[data-view="tasks"]').click();await page.locator('#tasks-history-tab').click();const row=page.locator('#tasks-list .task-widget-row').filter({hasText:run.runId});await expect(row).toContainText('ИИ работает');await row.locator('.task-widget-open').click();await page.locator('#task-tab-context').click();await expect(page.locator('#task-panel-context')).toContainText('Не привязан к задаче Cicada.');
});

test('copy ID and report link round-trip the same task while URL search opens without navigating away',async({page})=>{
 const key='cicada-0123456789abcdef-linked',task={taskKey:key,title:'Linked completed task',completed:true};
 const run={runId:'linked-run',taskKey:key,sequence:1,agent:'Codex',status:'done',model:null,inputTokens:null,outputTokens:null,skills:[],mcpCalls:null,updatedAt:'2026-09-27T08:01:00Z'};
 await fixtures(page,dashboard(task,[run]));await page.goto('/?task='+key+'&history=1#dashboard');await expect(page.locator('#dashboard-task-title')).toHaveText(task.title);await expect(page.locator('[data-view="tasks"]')).toHaveAttribute('aria-current','page');await expect(page.locator('#task-stage-details')).toContainText('Вход: — · Выход: —');
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedTaskText=text;}}}));await page.locator('#copy-task-id').click();expect(await page.evaluate(()=>window.copiedTaskText)).toBe(key);await page.locator('#copy-report-link').click();const link=await page.evaluate(()=>window.copiedTaskText);expect(new URL(link).searchParams.get('task')).toBe(key);expect(new URL(link).hash).toBe('#tasks');
 await page.locator('#close-dashboard-task').click();await page.locator('[data-view="tasks"]').click();const currentUrl=page.url();await page.locator('#tasks-search').fill(link);await page.locator('#tasks-search').press('Enter');await expect(page.locator('#dashboard-task-title')).toHaveText(task.title);expect(page.url()).toBe(currentUrl);
 await page.goto(link);await expect(page.locator('#task-screen')).toBeVisible();await expect(page.locator('#dashboard-task-title')).toHaveText(task.title);
 await page.locator('#task-tab-overview').focus();await page.locator('#task-tab-overview').press('ArrowRight');await expect(page.locator('#task-tab-history')).toBeFocused();await expect(page.locator('#task-tab-history')).toHaveAttribute('aria-selected','true');
 await page.locator('#language').selectOption('en');await expect(page.locator('#task-tab-context')).toHaveText('Context');await page.locator('#task-tab-overview').click();await expect(page.locator('#task-panel-overview .report-totals')).toContainText('Reported tokens');
});

test('stored reports do not attach to another Cicada profile with the same native ID',async({page})=>{
 await selectSource(page,'production');const production=(await(await page.request.get('/api/dashboard')).json()).cicada.tasks[0];const skill=(await(await page.request.get('/api/skill-inventory')).json()).skills[0],state=await(await page.request.get('/api/state')).json();
 const reported=await page.request.post('/api/runs/report',{data:{runId:'run-source-regression-060',sequence:1,taskKey:production.taskKey,agent:'codex',model:'production-only-model',provider:'synthetic-provider',stage:'analysis',status:'done',skillIds:[skill.id],inputTokens:0,outputTokens:null},headers:{'X-Agent-City':'1','X-Agent-City-Token':state.csrfToken}});expect(reported.status()).toBe(200);
 try{await selectSource(page,'dev');const dev=(await(await page.request.get('/api/dashboard')).json()).cicada.tasks[0];expect(dev.sourceId).toBe(production.sourceId);expect(dev.taskKey).not.toBe(production.taskKey);await page.goto('/#dashboard');await page.locator('#dashboard-tasks').getByRole('button',{name:'DEV task title',exact:true}).click();await expect(page.locator('#task-screen')).not.toContainText('production-only-model');await expect(page.locator('#task-screen .run-row')).toHaveCount(0);await expect(page.locator('#task-panel-overview .report-total-value').first()).toHaveText('—');await page.locator('#task-tab-context').click();await expect(page.locator('#task-panel-context')).toContainText(dev.sourceId);}
 finally{await selectSource(page,'production');}
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

async function selectSource(page, sourceId) {
  const settings = await (await page.request.get('/api/connectors')).json();
  const state = await (await page.request.get('/api/state')).json();
  const response = await page.request.post('/api/connectors/cicada', {
    data: { sourceId, revision: settings.revision },
    headers: { 'X-Agent-City': '1', 'X-Agent-City-Token': state.csrfToken },
  });
  expect(response.status()).toBe(200);
}

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
