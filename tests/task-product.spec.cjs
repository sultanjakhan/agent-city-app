const {test,expect}=require('./owner-fixture.cjs');
const path=require('node:path');
const ns='11111111-1111-4111-8111-111111111111';
function response(){
 const tasks=['Уточнить границы интеграции','Проверить переходы между этапами','Согласовать описание требований','Подготовить сценарии приёмки','Описать открытые вопросы'].map((title,i)=>({sourceId:'native-'+i,taskKey:'cicada-product-'+i,title,version:1,stage:i===0?'analysis':'',stageLabel:i===0?'Анализ':'',completed:false,isActive:false,isPaused:false,date:null,plannedTime:null,actualMinutes:0}));
 return {schemaVersion:1,cicada:{status:'connected',source:{label:'Cicada',sourceNamespace:ns},readAt:new Date().toISOString(),tasks:[tasks[0]],availableTasks:tasks,availableStatus:'connected',historyTasks:[]},runs:[{runId:'actual-1',taskKey:tasks[0].taskKey,agent:'codex',model:'known-model',status:'running',updatedAt:new Date().toISOString(),skillIds:[],skills:[]}],workRegistry:{publishers:{},bindings:{}}};
}
function connection(enabled=false){return {revision:1,config:{enabled,transport:'pipe',sourceNamespace:ns,scopes:['tasks:read','tasks:write'],staleAfterSeconds:300},tasks:{},outbox:{},lastSuccess:enabled?new Date().toISOString():null,failure:null};}

test('all personal tasks, current work, ID search and refreshed native edits remain distinct',async({page})=>{
 const data=response(),sync=connection(),writes=[];
 await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:sync}));
 page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/task-sync/'))writes.push(r.url());});
 await page.goto('/#dashboard');await expect(page.locator('.task-widget-row')).toHaveCount(5);
 await expect(page.locator('#task-exchange-status')).toContainText('двусторонний обмен выключен');
 await page.locator('#dashboard-filter').selectOption('current');await expect(page.locator('.task-widget-row')).toHaveCount(1);
 await page.locator('#dashboard-filter').selectOption('all');await page.locator('#dashboard-search').fill('native-4');await expect(page.locator('.task-widget-row')).toHaveCount(1);
 data.cicada.availableTasks[4].title='Изменено в Cicada';data.cicada.availableTasks[4].version=2;
 await page.locator('#refresh').click();await expect(page.locator('.task-widget-row')).toContainText('Изменено в Cicada');
 await page.locator('.task-widget-open').click();await expect(page.locator('#share-native-task')).toHaveText('Настроить обмен задачами');
 await page.locator('#share-native-task').click();await expect(page.locator('#task-connection')).toBeVisible();
 expect(writes).toEqual([]);
});

test('sharing connects the selected native ID and expected revision without creating a task',async({page})=>{
 const data=response(),sync=connection(true),sent=[];
 await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:sync}));
 await page.route('**/api/task-sync/queue',async r=>{const op=r.request().postDataJSON();sent.push(op);sync.outbox[op.operationId]={state:'pending',request:op};await r.fulfill({json:{state:'pending'}});});
 await page.route('**/api/task-sync/exchange',r=>r.fulfill({json:sync}));
 await page.goto('/#dashboard');await page.getByRole('button',{name:'Подготовить сценарии приёмки',exact:true}).click();
 await page.locator('#share-native-task').click();await expect.poll(()=>sent.length).toBe(1);
 expect(sent[0].command).toBe('share');expect(sent[0].arguments).toEqual({taskId:'native-3',expectedVersion:1});
 await expect(page.locator('#dashboard-task-dialog')).toBeVisible();
 await expect(page.locator('.shared-pending')).toContainText('ожидает отправки');
});

test('native and shared rows merge only by exact source namespace and native ID',async({page})=>{
 const data=response(),sync=connection(true),native=data.cicada.availableTasks[3];
 const task={id:native.sourceId,version:1,title:native.title,stage:'',completed:false,reports:[],results:[],review:null,freshness:'fresh',binding:{sourceNamespace:ns,sourceType:'note',sourceId:native.sourceId,taskKey:'cicada-stable-different-key'}};sync.tasks[task.id]=task;
 await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:sync}));
 await page.goto('/#dashboard');await expect(page.locator('.task-widget-row')).toHaveCount(5);await expect(page.getByRole('button',{name:native.title,exact:true})).toHaveCount(1);
 task.binding.sourceNamespace='22222222-2222-4222-8222-222222222222';await page.locator('#refresh').click();
 await expect(page.locator('.task-widget-row')).toHaveCount(6);await expect(page.getByRole('button',{name:native.title,exact:true})).toHaveCount(2);
});

test('compact task list shows observed metadata without placeholder clutter in light and dark',async({page})=>{
 const data=response();await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:connection()}));
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/#dashboard');
 const rows=page.locator('.task-widget-row');await expect(rows).toHaveCount(5);
 await expect(rows.first()).toContainText('known-model');await expect(rows.last()).toContainText('Статус ИИ неизвестен');
 await expect(page.locator('#dashboard-tasks')).not.toContainText('Этап не задан');await expect(page.locator('#dashboard-tasks')).not.toContainText('Время: 0');await expect(page.locator('#dashboard-tasks')).not.toContainText('Твой таймер: не идёт');
 const heights=await rows.evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));expect(Math.max(...heights)).toBeLessThan(116);
 await page.screenshot({path:path.resolve('../product-desktop-light.png'),fullPage:true});
 for(const width of [610,390,360]){
  await page.setViewportSize({width,height:844});if(width<=520)await page.evaluate(()=>setNavCollapsed(true));
  expect(await page.locator('#dashboard-view').evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(false);
  const targets=await rows.locator('.task-widget-title,.task-widget-open').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().height));expect(Math.min(...targets)).toBeGreaterThanOrEqual(44);
  expect(await rows.locator('.task-widget-title').evaluateAll(nodes=>nodes.every(n=>n.getBoundingClientRect().right<=n.closest('.task-widget-main').getBoundingClientRect().right+1))).toBe(true);
 }
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.screenshot({path:path.resolve('../product-narrow-dark.png'),fullPage:true});
 await expect(page.locator('#dashboard-view details,#dashboard-view summary')).toHaveCount(0);expect(errors).toEqual([]);
});
