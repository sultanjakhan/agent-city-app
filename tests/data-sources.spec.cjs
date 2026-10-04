const {test,expect}=require('./owner-fixture.cjs');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');

async function openData(page){
 await page.goto('/#settings');await page.locator('#settings-tab-data').click();
 await expect(page.locator('[data-source-root="city"]')).toBeVisible();
}
async function api(page,route,body){
 const state=await(await page.request.get('/api/state')).json();
 const response=await page.request.post(route,{data:body,headers:{'X-Agent-City':'1','X-Agent-City-Token':state.csrfToken}});
 expect(response.status()).toBe(200);return response.json();
}
async function lab(page){
 const profile=await(await page.request.get('/api/data-sources')).json(),base=path.dirname(profile.profilePath);
 expect(path.basename(base)).toMatch(/^agentcity-ui-/);
 const root=path.join(base,'sources-ui-'+crypto.randomUUID());fs.mkdirSync(path.join(root,'panel'),{recursive:true});
 fs.writeFileSync(path.join(root,'panel','projects.json'),JSON.stringify({projects:[{name:'PRIVATE_SOURCE_TEXT'}]}));
 return {profile,root,base};
}
async function restore(page,profile){
 const current=await(await page.request.get('/api/data-sources')).json();
 const body={manifest:profile.manifest,bindings:profile.bindings,revision:current.revision};
 const preview=await api(page,'/api/data-sources/preview',body);
 await api(page,'/api/data-sources/apply',{...body,previewToken:preview.previewToken});
}
test.afterEach(async({page})=>{await page.unrouteAll({behavior:'wait'});});

test('folder preview is read only, explicit apply persists placement, and portable export excludes local paths',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await openData(page);const {profile,root}=await lab(page);
 const before=await(await page.request.get('/api/extensions')).json();
 try{
  await page.locator('[data-source-root="city"]').fill(root);
  await expect(page.locator('#apply-data-sources')).toBeDisabled();
  await page.locator('#preview-data-sources').click();
  await expect(page.locator('#data-sources-preview [data-source-summary="projects"]')).toContainText('Записей: 1');
  await expect(page.locator('#data-sources-preview')).not.toContainText('PRIVATE_SOURCE_TEXT');
  expect((await(await page.request.get('/api/data-sources')).json()).revision).toBe(profile.revision);
  await page.locator('[data-source-section="projects"] select').selectOption('dashboard');
  await page.locator('[data-source-section="runs"] input').uncheck();
  await expect(page.locator('#apply-data-sources')).toBeDisabled();
  await page.locator('#preview-data-sources').click();await expect(page.locator('#apply-data-sources')).toBeEnabled();
  await page.locator('#apply-data-sources').click();await expect(page.locator('#data-sources-message')).toContainText('Выбор сохранён');
  expect(await(await page.request.get('/api/extensions')).json()).toEqual(before);
  await page.reload();await page.locator('#settings-tab-data').click();
  await expect(page.locator('[data-source-root="city"]')).toHaveValue(root);
  await expect(page.locator('[data-source-section="projects"] select')).toHaveValue('dashboard');
  await expect(page.locator('[data-source-section="runs"] input')).not.toBeChecked();
  const downloading=page.waitForEvent('download');await page.locator('#export-data-sources').click();const download=await downloading;
  const doc=JSON.parse(fs.readFileSync(await download.path(),'utf8'));expect(JSON.stringify(doc)).not.toContain(root);
  expect(doc.profiles.every(profile=>profile.config.source.path===null&&profile.config.refresh.mode==='manual')).toBe(true);
  await page.locator('aside [data-view="dashboard"]').click();await expect(page.locator('#data-sources-dashboard')).toBeVisible();
  await expect(page.locator('#data-sources-dashboard [data-source-summary="projects"]')).toContainText('Записей: 1');
  await expect(page.locator('#data-sources-dashboard [data-source-summary="runs"]')).toHaveCount(0);
  expect(errors).toEqual([]);
 }finally{await restore(page,profile);}
});

test('creating structure requires preview and separate confirmation without Git or data migration',async({page})=>{
 await openData(page);const {profile,root,base}=await lab(page),destination=path.join(base,'sources-ui-new-'+crypto.randomUUID());
 try{
  await page.locator('[data-source-root="city"]').fill(destination);
  await expect(page.locator('[data-source-create="city"]')).toBeDisabled();
  await page.locator('#preview-data-sources').click();await expect(page.locator('[data-source-create="city"]')).toBeEnabled();
  expect(fs.existsSync(destination)).toBe(false);
  page.once('dialog',dialog=>dialog.dismiss());await page.locator('[data-source-create="city"]').click();expect(fs.existsSync(destination)).toBe(false);
  page.once('dialog',dialog=>dialog.accept());await page.locator('[data-source-create="city"]').click();
  await expect(page.locator('#data-sources-message')).toContainText('Структура создана');
  expect(fs.readdirSync(destination).sort()).toEqual(['panel','repositories','skills']);expect(fs.existsSync(path.join(destination,'.git'))).toBe(false);
  expect(fs.existsSync(path.join(destination,'panel','projects.json'))).toBe(false);
  expect((await(await page.request.get('/api/data-sources')).json()).revision).toBe(profile.revision);
  expect(fs.existsSync(path.join(root,'panel','projects.json'))).toBe(true);
  await expect(page.locator('#apply-data-sources')).toBeDisabled();
 }finally{await restore(page,profile);}
});

test('validation and stale revision keep draft; only another preview permits an explicit retry',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));await openData(page);const {profile,root}=await lab(page);
 try{
  await page.locator('[data-source-root="city"]').fill(path.join(root,'sessions'));await page.locator('#preview-data-sources').click();
  await expect(page.locator('#data-sources-error')).toContainText('Хранилища ключей и сессий');
  await page.locator('[data-source-root="city"]').fill(root);await page.locator('#preview-data-sources').click();await expect(page.locator('#apply-data-sources')).toBeEnabled();
  const changed=structuredClone(profile.manifest);changed.sections[0].visible=false;
  const body={manifest:changed,bindings:{},revision:profile.revision},preview=await api(page,'/api/data-sources/preview',body);
  await api(page,'/api/data-sources/apply',{...body,previewToken:preview.previewToken});
  await page.locator('#apply-data-sources').click();await expect(page.locator('#data-sources-error')).toContainText('Источники изменились');
  await expect(page.locator('[data-source-root="city"]')).toHaveValue(root);await expect(page.locator('#apply-data-sources')).toBeDisabled();
  await page.locator('#preview-data-sources').click();await expect(page.locator('#apply-data-sources')).toBeEnabled();
  await page.locator('#apply-data-sources').click();await expect(page.locator('#data-sources-message')).toContainText('Выбор сохранён');expect(errors).toEqual([]);
 }finally{await restore(page,profile);}
});

test('portable import is a draft, unknown secret fields are rejected, and mobile English controls fit',async({page})=>{
 await openData(page);const {profile}=await lab(page);
 const doc=await(await page.request.get('/api/data-sources/export')).json();
 await page.locator('#import-data-sources').setInputFiles({name:'duplicate.json',mimeType:'application/json',buffer:Buffer.from('{"schemaVersion":1,"schemaVersion":1}')});
 await expect(page.locator('#data-sources-error')).toContainText('Invalid portable JSON');

 await page.locator('#import-data-sources').setInputFiles({name:'invalid.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({...doc,credentials:{}}))});
 await expect(page.locator('#data-sources-error')).toBeVisible();
 await page.locator('#import-data-sources').setInputFiles({name:'data-sources.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(doc))});
 await expect(page.locator('#data-sources-message')).toContainText('Конфигурация загружена в черновик');
 expect((await(await page.request.get('/api/data-sources')).json()).revision).toBe(profile.revision);
 await expect(page.locator('#apply-data-sources')).toBeDisabled();
 await page.locator('#language').selectOption('en');await expect(page.locator('#settings-tab-data')).toHaveText('Data and sources');
 await page.setViewportSize({width:390,height:844});await page.locator('#toggle-nav').click();
 await page.locator('#preview-data-sources').scrollIntoViewIfNeeded();await expect(page.locator('#preview-data-sources')).toBeInViewport();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/data-sources-mobile.png',fullPage:true});
});

test('first run offers setup or skip once, existing profiles do not get forced onboarding',async({page})=>{
 let first=true;
 await page.route('**/api/state',async route=>{const value=await(await route.fetch()).json();value.dataSourcesOnboarding=first;await route.fulfill({json:value});});
 await page.route('**/api/data-sources/dismiss',async route=>{first=false;await route.continue();});
 await page.goto('/');await expect(page.locator('#data-onboarding-dialog')).toBeVisible();
 await page.locator('#setup-data-onboarding').click();await expect(page.locator('#settings-data')).toBeVisible();
 await expect(page.locator('#data-onboarding-dialog')).toBeHidden();
 await page.reload();await expect(page.locator('#data-onboarding-dialog')).toBeVisible();
 await page.locator('#skip-data-onboarding').click();await expect(page.locator('#data-onboarding-dialog')).toBeHidden();
 await page.reload();await expect(page.locator('#data-onboarding-dialog')).toBeHidden();
});
