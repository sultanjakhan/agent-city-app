const {test,expect}=require('./owner-fixture.cjs');
const {createHash,randomUUID}=require('node:crypto');
const fs=require('node:fs/promises');
const productionNS='11111111-1111-4111-8111-111111111111';
function binding(){return {sourceNamespace:productionNS,sourceType:'note',sourceId:'shared-task',taskKey:'cicada-'+createHash('sha256').update(productionNS).digest('hex').slice(0,16)+'-shared-task'};}
function snapshot(title='Synthetic published task'){
 const published=new Date(Date.now()-2000).toISOString(),updated=new Date(Date.now()-120000).toISOString();
 return {schemaVersion:1,kind:'work-registry-snapshot',snapshotId:randomUUID(),sequence:1,source:{publisherId:'synthetic-'+randomUUID(),sourceNamespace:randomUUID(),mode:'published-snapshot'},publishedAt:published,staleAfterSeconds:60,projects:[{id:'engineering',title:'Synthetic published project'}],tasks:[{id:'root',projectId:'engineering',parentTaskId:null,title,relationship:'root',status:'checking',lastUpdated:updated,provenance:{kind:'parent-published',reference:'synthetic-public-fixture'},operation:'Synthetic local check',waitingFor:null,result:null,localBinding:binding()}],runs:[]};
}
async function api(page,route,body){const state=await(await page.request.get('/api/state')).json();const response=await page.request.post(route,{data:body,headers:{'X-Agent-City':'1','X-Agent-City-Token':state.csrfToken}});return {status:response.status(),body:await response.json()};}
async function selectSource(page,id){const state=await(await page.request.get('/api/connectors')).json();const result=await api(page,'/api/connectors/cicada',{sourceId:id,revision:state.revision});expect(result.status).toBe(200);}
async function openImport(page){await page.goto('/#settings');await page.locator('#settings-tab-data').click();await page.locator('#language').selectOption('en');}
async function preview(page,doc){await page.locator('#work-registry-file').setInputFiles({name:'synthetic-exchange.json',mimeType:'application/json',buffer:Buffer.from(typeof doc==='string'?doc:JSON.stringify(doc))});await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-apply')).toBeEnabled();}
async function apply(page,accept=true){page.once('dialog',dialog=>accept?dialog.accept():dialog.dismiss());await page.locator('#work-registry-apply').click();if(accept)await expect(page.locator('#work-registry-message')).toContainText('saved locally');}

test('published hierarchy remains an observation, survives reload, keeps visible details and responds to search',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));await openImport(page);
 const doc=snapshot('Synthetic <img src=x onerror=window.registryInjected=true>');
 doc.tasks.push({...doc.tasks[0],id:'child',title:'Synthetic child decision',parentTaskId:'root',relationship:'parallel',status:'decision-needed',localBinding:null});
 await preview(page,doc);await expect(page.locator('#work-registry-preview-body')).toContainText('work-registry-snapshot');
 const before=await(await page.request.get('/api/work-exchange')).json();expect(before.publishers[doc.source.publisherId+':'+doc.source.sourceNamespace]).toBeUndefined();
 await apply(page,false);await expect(page.locator('#work-registry-apply')).toBeEnabled();await apply(page);
 const root=page.locator('[data-registry-task-id=root]').filter({hasText:doc.tasks[0].title});await expect(root).toContainText('checking · stale');
 await expect(root.locator('h4').first()).toBeVisible();await expect(root.locator('details,summary')).toHaveCount(0);
 await page.evaluate(()=>loadDashboard(true));await expect(root.locator('h4').first()).toBeVisible();
 await expect(root).toContainText('Dispatch unavailable');expect(await page.evaluate(()=>window.registryInjected)).toBeUndefined();await expect(page.locator('#work-registry img')).toHaveCount(0);
 await page.locator('#work-registry-search').fill('Synthetic child decision');await expect(page.locator('[data-registry-task-id=child]').filter({hasText:'Synthetic child decision'})).toBeVisible();await expect(root).toHaveCount(0);
 await page.locator('#work-registry-search').fill('');await page.reload();await expect(root).toContainText('checking · stale');expect(errors).toEqual([]);
});

test('explicit stable binding imports reports dynamically, exports strict envelope, and never invents usage or task completion',async({page})=>{
 await selectSource(page,'production');await openImport(page);await preview(page,{schemaVersion:1,kind:'cicada-task-binding',binding:binding()});await apply(page);
 const doc=snapshot('Synthetic paired registry');await preview(page,doc);await apply(page);
 const run={runId:'synthetic-'+randomUUID(),sequence:1,taskKey:binding().taskKey,agent:'codex',model:null,provider:null,stage:'synthetic-check',status:'waiting',skillIds:[],mcpCalls:null,inputTokens:null,outputTokens:null};
 await preview(page,{schemaVersion:1,kind:'cicada-run-report',binding:binding(),report:run});await apply(page);
 const card=page.locator('[data-registry-task-id=root]').filter({hasText:'Synthetic paired registry'});await expect(card).toContainText('Imported executor reports: 1');await expect(card).toContainText('Cost unknown');
 await expect(card.locator('.report-total-value').first()).toHaveText('—');
 const downloaded=page.waitForEvent('download');await card.getByRole('button',{name:'Export latest report'}).click();const download=await downloaded;const file=await download.path();const exported=JSON.parse(await fs.readFile(file,'utf8'));expect(exported.binding).toEqual(binding());expect(exported.report.runId).toBe(run.runId);expect(exported.report.inputTokens).toBeNull();expect(exported.report.updatedAt).toBeUndefined();
 const result=await api(page,'/api/runs/report',{...run,sequence:2,status:'done'});expect(result.status).toBe(200);await page.evaluate(()=>loadDashboard(true));await expect(card.locator('.stage-report')).toContainText('Done');
 const dashboard=await(await page.request.get('/api/dashboard')).json();expect(dashboard.cicada.tasks.find(task=>task.sourceId==='shared-task').completed).toBe(false);expect(doc.tasks[0].status).toBe('checking');
 await selectSource(page,'dev');await page.evaluate(()=>loadDashboard(true));await expect(card).toContainText('not paired');await expect(card.getByRole('button',{name:'Export latest report'})).toHaveCount(0);await selectSource(page,'production');
});

test('preview failure and revision conflict restore controls, retain file draft, and require explicit retry',async({page})=>{
 await openImport(page);const doc=snapshot('Synthetic retry');let failed=false;
 await page.route('**/api/work-exchange/preview',route=>{if(!failed){failed=true;return route.abort();}return route.continue();});
 await page.locator('#work-registry-file').setInputFiles({name:'retry.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-message')).toContainText('Draft retained');await expect(page.locator('#work-registry-apply')).toBeDisabled();await expect(page.locator('#work-registry-preview')).toBeEnabled();
 await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-apply')).toBeEnabled();
 const other=snapshot('Synthetic other writer'),profile=await(await page.request.get('/api/work-exchange')).json(),p=await api(page,'/api/work-exchange/preview',{document:JSON.stringify(other),revision:profile.revision});expect(p.status).toBe(200);expect((await api(page,'/api/work-exchange/apply',{previewToken:p.body.previewToken,revision:profile.revision})).status).toBe(200);
 page.once('dialog',dialog=>dialog.accept());await page.locator('#work-registry-apply').click();await expect(page.locator('#work-registry-message')).toContainText('Draft retained');await expect(page.locator('#work-registry-apply')).toBeDisabled();
 await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-apply')).toBeEnabled();await apply(page);await expect(page.locator('[data-registry-task-id=root]').filter({hasText:'Synthetic retry'})).toBeVisible();
});

test('invalid private fields and duplicate JSON never render, pending preview prevents repeats, and mobile controls fit',async({page})=>{
 await openImport(page);const doc=snapshot('Synthetic pending');const before=await(await page.request.get('/api/work-exchange')).json();
 await page.locator('#work-registry-file').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...doc,credentials:'KEEP_OFF_UI'}))});await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-message')).toContainText('Invalid');await expect(page.locator('#work-registry-preview-body')).not.toContainText('KEEP_OFF_UI');
 expect((await(await page.request.get('/api/work-exchange')).json()).revision).toBe(before.revision);
 let release;await page.route('**/api/work-exchange/preview',async route=>{await new Promise(resolve=>release=resolve);await route.continue();});
 await page.locator('#work-registry-file').setInputFiles({name:'pending.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});await page.locator('#work-registry-preview').click();await expect(page.locator('#work-registry-preview')).toBeDisabled();await expect(page.locator('#work-registry-file')).toBeDisabled();await expect.poll(()=>typeof release).toBe('function');release();await expect(page.locator('#work-registry-apply')).toBeEnabled();
 await page.setViewportSize({width:390,height:844});await page.locator('#toggle-nav').click();await page.locator('#work-registry-apply').scrollIntoViewIfNeeded();await expect(page.locator('#work-registry-apply')).toBeInViewport();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
