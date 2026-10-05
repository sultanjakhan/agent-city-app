const {test,expect}=require('./owner-fixture.cjs');
const path=require('node:path');
const ns='11111111-1111-4111-8111-111111111111';
function response(){
 const tasks=['Уточнить границы интеграции','Проверить переходы между этапами','Согласовать описание требований','Подготовить сценарии приёмки','Описать открытые вопросы'].map((title,i)=>({sourceId:'native-'+i,taskKey:'cicada-product-'+i,title,version:1,stage:i===0?'analysis':'',stageLabel:i===0?'Анализ':'',completed:false,isActive:false,isPaused:false,date:null,plannedTime:null,actualMinutes:0}));
 return {schemaVersion:1,cicada:{status:'connected',source:{label:'Cicada',sourceNamespace:ns},readAt:new Date().toISOString(),tasks:[tasks[0]],availableTasks:tasks,availableStatus:'connected',historyTasks:[]},runs:[{runId:'actual-1',taskKey:tasks[0].taskKey,agent:'codex',model:'known-model',status:'running',updatedAt:new Date().toISOString(),skillIds:[],skills:[]}],workRegistry:{publishers:{},bindings:{}}};
}
function connection(enabled=false){return {revision:1,config:{enabled,transport:'pipe',sourceNamespace:ns,scopes:['tasks:read','tasks:write'],staleAfterSeconds:300},tasks:{},outbox:{},lastSuccess:enabled?new Date().toISOString():null,failure:null};}

test('dashboard keeps current work while Tasks exposes searchable personal records',async({page})=>{
 const data=response(),writes=[];await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:connection()}));page.on('request',r=>{if(r.method()==='POST'&&r.url().includes('/api/task-sync/'))writes.push(r.url());});
 await page.goto('/#dashboard');await expect(page.locator('#dashboard-tasks .task-widget-row')).toHaveCount(1);await expect(page.locator('#dashboard-view [role=tablist],#dashboard-search,#work-registry:visible')).toHaveCount(0);
 await page.locator('[data-view="tasks"]').click();await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(5);await expect(page.locator('#task-exchange-status')).toContainText('двусторонний обмен выключен');
 await expect(page.locator('#tasks-list .task-widget-row').first()).toContainText('known-model');for(const placeholder of ['Этап не задан','Время: 0','Твой таймер: не идёт'])await expect(page.locator('#tasks-list')).not.toContainText(placeholder);
 await page.locator('#tasks-status').selectOption('current');await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(1);
 await page.locator('#tasks-status').selectOption('all');await page.locator('#tasks-search').fill('native-4');await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(1);
 data.cicada.availableTasks[4].title='Изменено в Cicada';data.cicada.availableTasks[4].version=2;await page.locator('#refresh').click();await expect(page.locator('#tasks-list')).toContainText('Изменено в Cicada');
 await page.locator('#tasks-list .task-widget-open').click();await expect(page.locator('#task-screen')).toBeVisible();await expect(page.locator('#task-list-screen')).toBeHidden();await expect(page.locator('#tasks-view dialog,#tasks-view aside')).toHaveCount(0);
 await page.locator('#close-dashboard-task').click();await expect(page.locator('#tasks-search')).toHaveValue('native-4');await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(1);
 await page.locator('#tasks-list .task-widget-open').click();await expect(page.locator('#share-native-task')).toHaveText('Настроить обмен задачами');await page.locator('#share-native-task').click();await expect(page.locator('#task-connection')).toBeVisible();expect(writes).toEqual([]);
});

test('sharing uses the selected native ID and revision without creating a second task owner',async({page})=>{
 const data=response(),sync=connection(true),sent=[];await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:sync}));
 await page.route('**/api/task-sync/queue',async r=>{const op=r.request().postDataJSON();sent.push(op);sync.outbox[op.operationId]={state:'pending',request:op};await r.fulfill({json:{state:'pending'}});});await page.route('**/api/task-sync/exchange',r=>r.fulfill({json:sync}));
 await page.goto('/#tasks');await page.locator('#tasks-list').getByRole('button',{name:'Подготовить сценарии приёмки',exact:true}).click();await page.locator('#share-native-task').click();await expect.poll(()=>sent.length).toBe(1);expect(sent[0].command).toBe('share');expect(sent[0].arguments).toEqual({taskId:'native-3',expectedVersion:1});await expect(page.locator('#task-screen .shared-pending')).toContainText('ожидает отправки');
 const native=data.cicada.availableTasks[3],task={id:native.sourceId,version:2,title:native.title,stage:'',completed:false,reports:[],results:[],review:null,freshness:'fresh',binding:{sourceNamespace:ns,sourceType:'note',sourceId:native.sourceId,taskKey:'cicada-stable-different-key'}};sync.tasks[task.id]=task;
 await page.locator('#close-dashboard-task').click();await page.locator('#refresh').click();await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(5);await expect(page.locator('#tasks-list').getByRole('button',{name:native.title,exact:true})).toHaveCount(1);
 task.binding.sourceNamespace='22222222-2222-4222-8222-222222222222';task.binding.taskKey='cicada-other-source-key';await page.locator('#refresh').click();await expect(page.locator('#tasks-list .task-widget-row')).toHaveCount(6);
});

test('opening Dashboard work selects Tasks and Back restores the origin without overflow',async({page})=>{
 const data=response();await page.route('**/api/dashboard',r=>r.fulfill({json:data}));await page.route('**/api/task-sync',r=>r.fulfill({json:connection()}));
 await page.goto('/#dashboard');await page.locator('#dashboard-tasks .task-widget-open').click();await expect(page.locator('[data-view="tasks"]')).toHaveAttribute('aria-current','page');await expect(page.locator('#task-screen')).toBeVisible();await expect(page.locator('#task-tab-overview')).toHaveAttribute('aria-selected','true');
 await page.locator('#task-tab-context').click();await expect(page.locator('#task-panel-context')).toContainText('native-0');await expect(page.locator('#task-panel-overview')).toBeHidden();await page.locator('#task-tab-overview').click();
 for(const width of [610,390,360]){await page.setViewportSize({width,height:844});expect(await page.locator('#tasks-view').evaluate(el=>el.scrollWidth>el.clientWidth)).toBe(false);}
 await expect(page.locator('#tasks-view details,#tasks-view summary')).toHaveCount(0);await page.locator('#close-dashboard-task').click();await expect(page.locator('#dashboard-view')).toBeVisible();
});
