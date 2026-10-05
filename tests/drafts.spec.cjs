const {test,expect}=require('./owner-fixture.cjs');
const id='a'.repeat(32),other='b'.repeat(32);
const snapshot=page=>page.evaluate(()=>window.agentCityDrafts.snapshot());
async function editor(page){await page.goto('/');await page.evaluate(()=>document.getElementById('skill-dialog').showModal());return page.locator('#skill-content');}
test('clean documents and search filters close without a prompt; close rollback restores interaction',async({page})=>{
 await page.goto('/#tasks');await page.locator('#tasks-search').fill('search is not a draft');
 expect(await snapshot(page)).toEqual({version:1,dirty:false,busy:false});
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close',false),id)).toBe('clean');
 await expect(page.locator('#unsaved-changes-dialog')).toHaveCount(0);
 expect(await page.evaluate(()=>document.body.inert)).toBe(true);
 await page.evaluate(id=>window.agentCityDrafts.cancel(id),id);expect(await page.evaluate(()=>document.body.inert)).toBe(false);
});
test('cancel and Escape preserve edits; discard requires an explicit decision and freezes new input',async({page})=>{
 const field=await editor(page);await field.fill('Unsaved private fixture');
 expect((await snapshot(page)).dirty).toBe(true);
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close',false),id)).toBe('blocked');
 await expect(page.locator('#unsaved-changes-dialog')).toHaveCount(0);
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close',true),id)).toBe('pending');
 await expect(page.getByRole('button',{name:'Вернуться к изменениям',exact:true})).toBeFocused();
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close'),other)).toBe('busy');
 await page.keyboard.press('Escape');expect(await page.evaluate(id=>window.agentCityDrafts.poll(id),id)).toBe('cancel');await expect(field).toHaveValue('Unsaved private fixture');
 await page.evaluate(id=>window.agentCityDrafts.cancel(id),id);
 await page.evaluate(id=>window.agentCityDrafts.request(id,'restart'),id);
 await page.getByRole('button',{name:'Перезапустить без сохранения'}).click();
 expect(await page.evaluate(id=>window.agentCityDrafts.poll(id),id)).toBe('discard');expect(await page.evaluate(()=>document.body.inert)).toBe(true);
 await page.evaluate(id=>window.agentCityDrafts.cancel(id),id);expect(await page.evaluate(()=>document.body.inert)).toBe(false);await expect(field).toHaveValue('Unsaved private fixture');
});
test('failed saves and previews retain drafts; acknowledgement clears only saved scopes',async({page})=>{
 const field=await editor(page);await field.fill('First edit');
 await page.route('**/api/skills/save',r=>r.fulfill({status:409,json:{error:'revision conflict'}}));
 expect(await page.evaluate(()=>request('/api/skills/save',{content:'First edit'}).then(()=>true,()=>false))).toBe(false);
 expect((await snapshot(page)).dirty).toBe(true);
 await page.route('**/api/skills/preview',r=>r.fulfill({json:{}}));await page.evaluate(()=>request('/api/skills/preview',{content:'First edit'}));expect((await snapshot(page)).dirty).toBe(true);
 await page.route('**/api/rules/save',r=>r.fulfill({json:{}}));await page.evaluate(()=>request('/api/rules/save',{content:'Unrelated fixture'}));expect((await snapshot(page)).dirty).toBe(true);
 await page.unroute('**/api/skills/save');await page.route('**/api/skills/save',r=>r.fulfill({json:{}}));await page.evaluate(()=>request('/api/skills/save',{content:'First edit'}));expect((await snapshot(page)).dirty).toBe(false);
 await field.fill('Changed after save');expect((await snapshot(page)).dirty).toBe(true);
});
test('in-flight writes block close and edits after submission survive successful acknowledgement',async({page})=>{
 const field=await editor(page);await field.fill('Submitted value');
 let release;const hold=new Promise(resolve=>release=resolve);
 await page.route('**/api/skills/save',async r=>{await hold;await r.fulfill({json:{}});});
 await page.evaluate(()=>{window.draftSave=request('/api/skills/save',{content:'Submitted value'});});
 await expect.poll(async()=>(await snapshot(page)).busy).toBe(true);
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close'),id)).toBe('busy');
 await field.fill('Later edit');release();await page.evaluate(()=>window.draftSave);
 expect(await snapshot(page)).toEqual({version:1,dirty:true,busy:false});await expect(field).toHaveValue('Later edit');
});
test('unacknowledged local operations remain drafts; native snapshots contain no form values or secrets',async({page})=>{
 await page.goto('/');await page.evaluate(()=>{localStorage.setItem('agent-city-shared-unsent-v1',JSON.stringify({fixture:{secret:'not exported'}}));});
 expect(await snapshot(page)).toEqual({version:1,dirty:true,busy:false});
 expect(await page.evaluate(id=>window.agentCityDrafts.request(id,'close',false),id)).toBe('blocked');
 await page.evaluate(()=>localStorage.removeItem('agent-city-shared-unsent-v1'));expect((await snapshot(page)).dirty).toBe(false);
});
test('provider website acknowledgement does not clear a key; saving a key does not clear website edits',async({page})=>{
 await page.goto('/');await page.evaluate(()=>document.getElementById('provider-dialog').showModal());
 await page.locator('#provider-website').fill('https://example.invalid');await page.locator('#provider-api-key').fill('synthetic-secret');
 await page.route('**/api/providers/add',r=>r.fulfill({json:{}}));await page.evaluate(()=>providerRequest('/api/providers/add',{website:'https://example.invalid'}));expect((await snapshot(page)).dirty).toBe(true);
 await page.route('**/api/credential',r=>r.fulfill({json:{}}));await page.evaluate(()=>providerRequest('/api/credential',{key:'synthetic-secret'}));expect((await snapshot(page)).dirty).toBe(false);
 await page.locator('#provider-website').fill('https://other.invalid');await page.evaluate(()=>providerRequest('/api/credential',{key:'synthetic-secret'}));expect((await snapshot(page)).dirty).toBe(true);
});
test('Russian and English close prompts fit a narrow viewport with the safe default focused',async({page})=>{
 await page.setViewportSize({width:400,height:780});const field=await editor(page);await field.fill('Narrow fixture');
 await page.evaluate(id=>window.agentCityDrafts.request(id,'close'),id);const dialog=page.locator('#unsaved-changes-dialog');await expect(dialog).toBeVisible();
 const box=await dialog.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(400);
 await page.getByRole('button',{name:'Вернуться к изменениям',exact:true}).click();await page.evaluate(id=>window.agentCityDrafts.cancel(id),id);
 await page.evaluate(()=>I18n.setLanguage('en'));await page.evaluate(id=>window.agentCityDrafts.request(id,'restart'),id);
 await expect(page.getByRole('button',{name:'Go back to edits'})).toBeFocused();await expect(dialog).toContainText('Restart without saving');
});
