const {test,expect}=require('./owner-fixture.cjs');
const ns='11111111-1111-4111-8111-111111111111';
const path=require('node:path');
function fixture(){const task={id:'synthetic-native-1',version:3,title:'Общая задача',content:'Сохранённое описание',tags:'task-sphere:personal',stage:'requirements',process:'system-analysis',completed:false,humanTimerActive:false,reports:[],results:[{version:1,content:'Результат на проверке'}],history:[],comments:[],intents:[],workflow:null,review:{resultVersion:1,state:'awaiting_review',intentId:null},binding:{sourceNamespace:ns,sourceType:'note',sourceId:'synthetic-native-1',taskKey:'cicada-synthetic-native-1'}};return {schemaVersion:1,revision:2,config:{enabled:true,transport:'http',endpoint:'http://127.0.0.1:47990/commands',profile:'',client:'',tokenEnv:'SYNTHETIC_TOKEN',sourceNamespace:ns,scopes:['tasks:read','tasks:write','tasks:review'],taskIds:null,staleAfterSeconds:300},tasks:{[task.id]:task},outbox:{},receipts:{},lastSuccess:null,lastAttempt:null,failure:{code:'task_connection_unavailable'}};}
test('shared task uses exact ID, honest execution, review and distinct timer',async({page})=>{
 const value=fixture(),sent=[];await page.route('**/api/task-sync',r=>r.fulfill({json:value}));
 await page.route('**/api/task-sync/queue',async r=>{const body=r.request().postDataJSON();sent.push(body);value.outbox[body.operationId]={state:'pending',request:body,conflict:null};await r.fulfill({json:value.outbox[body.operationId]});});
 await page.route('**/api/task-sync/exchange',r=>r.fulfill({json:value}));
 await page.goto('/#dashboard');const row=page.locator('[data-shared-task-id="synthetic-native-1"]');await expect(row).toHaveCount(1);await expect(row).toContainText('Результат ожидает проверки');await expect(row).toContainText('Твой таймер: не идёт');await expect(row).toContainText('Модель неизвестна');
 await row.getByRole('button',{name:'Общая задача',exact:true}).click();const dialog=page.locator('#shared-task-dialog');await dialog.getByLabel('Комментарий / отзыв').fill('Сохрани прежний результат');await dialog.getByRole('button',{name:'Запросить доработку',exact:true}).click();await expect(dialog).not.toBeVisible();
 expect(sent).toHaveLength(1);expect(sent[0].arguments).toEqual({taskId:'synthetic-native-1',expectedVersion:3,resultVersion:1,decision:'rework',comment:'Сохрани прежний результат'});await expect(page.locator('.shared-pending').first()).toContainText('ожидает отправки');await expect(row).not.toContainText('ИИ работает');
});
test('unknown queue outcome retries identical operation and preserves local draft',async({page})=>{
 const value=fixture(),sent=[];let dropped=false;await page.route('**/api/task-sync',r=>r.fulfill({json:value}));
 await page.route('**/api/task-sync/queue',async r=>{sent.push(r.request().postDataJSON());if(!dropped){dropped=true;await r.abort('failed');}else await r.fulfill({json:{state:'pending'}});});await page.route('**/api/task-sync/exchange',r=>r.fulfill({json:value}));
 await page.goto('/#dashboard');await page.getByRole('button',{name:'Добавить общую задачу',exact:true}).click();await page.locator('#shared-task-dialog').getByLabel('Название',{exact:true}).fill('Новая без дублей');await page.locator('#shared-task-dialog').getByRole('button',{name:'Создать в Cicada',exact:true}).click();await expect(page.locator('.shared-pending h3')).toContainText('ответ на отправку не получен');
 await page.locator('#shared-task-dialog').getByRole('button',{name:'Закрыть',exact:true}).click();await page.getByRole('button',{name:'Повторить ту же отправку',exact:true}).click();await expect.poll(()=>sent.length).toBe(2);expect(sent[0]).toEqual(sent[1]);await expect.poll(()=>page.evaluate(()=>localStorage.getItem('agent-city-shared-unsent-v1'))).toBe('{}');
});
test('connection setup exposes credential reference, freshness and actionable failure at narrow width',async({page})=>{
 const value=fixture();await page.route('**/api/task-sync',r=>r.fulfill({json:value}));await page.setViewportSize({width:390,height:844});await page.goto('/#settings');await page.getByRole('tab',{name:'Коннекторы',exact:true}).click();const form=page.locator('#task-connection');await expect(form.getByLabel('Адрес API',{exact:true})).toHaveValue(value.config.endpoint);await expect(form.getByLabel('Имя переменной окружения с секретом')).toHaveValue('SYNTHETIC_TOKEN');await expect(form).toContainText('Последний успешный обмен: ещё не было');await expect(form).toContainText('Проверь адрес');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await expect(form.locator('input[type=password]')).toHaveCount(0);
});

test('native report shape shows actual executor and model and rejects stale running as current work',async({page})=>{
 const value=fixture(),task=value.tasks['synthetic-native-1'];task.review=null;task.results=[];task.freshness='fresh';value.lastSuccess=new Date().toISOString();value.failure=null;
 task.reports=[{runId:'old-native-run',agent:'Old executor',model:'old-model',status:'done',receivedAt:new Date(Date.now()-600000).toISOString()},{runId:'latest-native-run',agent:'Codex',model:'actual-model',status:'running',receivedAt:new Date().toISOString()}];
 await page.route('**/api/task-sync',r=>r.fulfill({json:value}));await page.goto('/#dashboard');const row=page.locator('[data-shared-task-id="synthetic-native-1"]');
 await expect(row).toContainText('ИИ работает · по отчёту');await expect(row).toContainText('Codex · actual-model');await expect(row).not.toContainText('old-model');
 await page.locator('#dashboard-filter').selectOption('working');await expect(row).toBeVisible();
 task.reports[1].receivedAt=new Date(Date.now()-600000).toISOString();task.reports.shift();await page.evaluate(()=>loadSharedTasks());await expect(row).toHaveCount(0);
 await page.locator('#dashboard-filter').selectOption('all');await expect(row).toContainText('нет свежего подтверждения');
 delete task.reports[0].receivedAt;await page.evaluate(()=>loadSharedTasks());await expect(row).toContainText('нет свежего подтверждения');
 await row.locator('.task-widget-open').click();await expect(page.locator('#shared-task-dialog details,#shared-task-dialog summary')).toHaveCount(0);
});

test('flat review history preserves earlier results, feedback, comments and stage history as escaped text',async({page})=>{
 const value=fixture(),task=value.tasks['synthetic-native-1'];task.results=[{version:1,content:'Прежний результат <img src=x>'},{version:2,content:'Исправленный результат'}];task.review={state:'accepted',resultVersion:2};task.completed=true;
 task.history=[{action:'rework',resultVersion:1,comment:'Сохрани замечания'},{action:'accept',resultVersion:2,comment:null}];task.comments=[{content:'Комментарий сохранён',at:'2026-10-04T10:00:00Z'}];task.stageHistory=[{stage:'requirements',at:'2026-10-04T09:00:00Z'}];
 await page.route('**/api/task-sync',r=>r.fulfill({json:value}));await page.goto('/#dashboard');await page.locator('#dashboard-history-tab').click();await page.locator('[data-shared-task-id="synthetic-native-1"] .task-widget-open').click();const history=page.locator('.shared-task-history');
 for(const text of ['Прежний результат <img src=x>','Исправленный результат','Сохрани замечания','Комментарий сохранён','requirements','Принято','Запрошена доработка'])await expect(history).toContainText(text);
 await expect(history.locator('details,summary,img')).toHaveCount(0);await expect(history).not.toContainText('"resultVersion"');
});

test('dashboard refresh and periodic read show changed shared tasks without reopening the page',async({page})=>{
 const value=fixture(),task=value.tasks['synthetic-native-1'];await page.route('**/api/task-sync',r=>r.fulfill({json:value}));await page.goto('/#dashboard');const row=page.locator('[data-shared-task-id="synthetic-native-1"]');await expect(row).toContainText(task.title);
 task.title='Изменено в Cicada';await page.locator('#refresh').click();await expect(row).toContainText(task.title);
 task.stage='review';await expect(row.locator('.task-stage')).toHaveText('review',{timeout:8000});
});

test('Cicada-style widget opens exact-ID review from its arrow and stays within narrow/dark layouts',async({page})=>{
 const value=fixture(),task=value.tasks['synthetic-native-1'];task.title='Проверить описание требований и сохранить замечания';
 const running=structuredClone(task);running.id='synthetic-native-2';running.binding.sourceId=running.id;running.binding.taskKey='cicada-synthetic-native-2';running.title='Подготовить план следующего этапа';running.stage='analysis';running.review=null;running.results=[];
 task.freshness='fresh';running.freshness='fresh';running.reports=[{runId:'synthetic-widget-run',agent:'Codex',model:'synthetic-model',receivedAt:new Date().toISOString(),status:'running'}];value.tasks[running.id]=running;value.lastSuccess=new Date().toISOString();value.failure=null;
 await page.route('**/api/task-sync',r=>r.fulfill({json:value}));await page.route('**/api/dashboard',async r=>{const body=await(await r.fetch()).json();body.cicada.tasks=[];await r.fulfill({json:body});});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/#dashboard');
 const widget=page.locator('.task-widget'),row=page.locator('[data-shared-task-id="synthetic-native-1"]');await expect(widget).toBeVisible();await expect(page.locator('#task-widget-count')).toHaveText('Показано: 2');await expect(row.locator('.task-widget-status')).toContainText('ожидает проверки');
 await expect(page.locator('#work-registry')).toBeHidden();await expect(page.locator('#dashboard-view details,#dashboard-view summary')).toHaveCount(0);await expect(page.locator('#dashboard-view')).not.toContainText('Как это считается');
 await page.screenshot({path:path.resolve('../widget-desktop-light.png'),fullPage:true});
 await row.getByRole('button',{name:'Открыть задачу: '+task.title,exact:true}).click();await expect(page.locator('#shared-task-dialog')).toContainText(task.id);await expect(page.locator('#shared-task-dialog')).toContainText('Результат на проверке');await page.locator('#shared-task-dialog').getByRole('button',{name:'Закрыть',exact:true}).click();
 task.title='ДлинноеНазваниеЖ文'.repeat(25);await page.reload();await expect(row).toContainText(task.title);
 for(const width of [610,390,360]){
  await page.setViewportSize({width,height:950});
  if(width===390)await page.locator('#toggle-nav').click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  const controls=await widget.locator('.task-widget-open,.task-widget-title').evaluateAll(nodes=>nodes.map(n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,width:b.width,height:b.height};}));
  for(const box of controls){expect(box.left).toBeGreaterThanOrEqual(0);expect(box.right).toBeLessThanOrEqual(width);expect(box.height).toBeGreaterThanOrEqual(44);}
 }
 await row.getByRole('button',{name:'Открыть задачу: '+task.title,exact:true}).click();await expect(page.locator('#shared-task-dialog')).toContainText(task.id);await page.locator('#shared-task-dialog').getByRole('button',{name:'Закрыть',exact:true}).click();
 task.title='Проверить описание требований и сохранить замечания';await page.reload();await expect(row).toContainText(task.title);
 await page.screenshot({path:path.resolve('../widget-narrow-light.png'),fullPage:true});
 await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.screenshot({path:path.resolve('../widget-narrow-dark.png'),fullPage:true});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);expect(errors).toEqual([]);
});
