const {test,expect}=require('./owner-fixture.cjs');

test('new-model checks require an explicit action, show progress and can stop',async({page})=>{
 let snapshot,starts=0,cancels=0;
 await page.route('**/api/state',async route=>{
  if(!snapshot){snapshot=await (await route.fetch()).json();snapshot.availability={total:3,responded:0,pending:2,needsRetry:0,needsAccess:1,needsKey:0};snapshot.busy=[];snapshot.batch={};}
  await route.fulfill({json:snapshot});
 });
 await page.route('**/api/check-pending',async route=>{
  starts++;expect(route.request().method()).toBe('POST');expect(route.request().headers()['x-agent-city-token']).toBe(snapshot.csrfToken);
  snapshot.busy=['check'];snapshot.batch={total:2,completed:0,responded:0,running:true,stopped:{}};await route.fulfill({json:snapshot});
 });
 await page.route('**/api/check-cancel',async route=>{
  cancels++;snapshot.busy=[];snapshot.batch={...snapshot.batch,running:false,cancelled:true};await route.fulfill({json:snapshot});
 });
 await page.goto('/');await page.locator('[data-view=connections]').click();await expect(page.locator('#check-new-connections')).toBeEnabled();expect(starts).toBe(0);
 await page.locator('#check-new-connections').click();await expect(page.locator('#batch-status')).toContainText('0');await expect(page.locator('#check-new-connections')).toBeDisabled();
 await page.locator('#cancel-connection-checks').click();await expect(page.locator('#cancel-connection-checks')).toBeHidden();expect(starts).toBe(1);expect(cancels).toBe(1);
});

test('a new server version offers reload without discarding a project draft',async({page})=>{
 await page.route('**/api/state',async route=>{const state=await(await route.fetch()).json();state.settings.version='future-test';await route.fulfill({json:state});});
 await page.goto('/');await expect(page.locator('#app-update')).toBeVisible();
 await page.locator('[data-view="extensions"]').click();await expect(page.locator('#projects-list .library-row').first()).toBeVisible();
 await page.locator('#add-project').click();await page.locator('#project-name').fill('Keep my draft');
 await page.evaluate(()=>load());await expect(page.locator('#project-name')).toHaveValue('Keep my draft');await expect(page.locator('#project-dialog')).toBeVisible();
});

test('an older server asks for restart instead of an endless page reload',async({page})=>{
 let older=true;
 await page.route('**/api/state',async route=>{const state=await(await route.fetch()).json();if(older)state.settings.version='0.0.0';await route.fulfill({json:state});});
 await page.goto('/');await expect(page.locator('#app-update')).toContainText('Перезапусти сервер');
 await expect(page.locator('button#app-update')).toHaveCount(0);
 await page.locator('#language').selectOption('en');await expect(page.locator('#app-update')).toContainText('Restart the Agent City server');
 older=false;await page.evaluate(()=>load());await expect(page.locator('#app-update')).toHaveCount(0);
});


test('connections title and Check new models share a row without overflow in both languages',async({page})=>{
 const requests=[];page.on('request',r=>{if(r.method()==='POST')requests.push(r.url());});
 await page.goto('/#connections');
 for(const language of ['ru','en']){
  await page.locator('#language').selectOption(language);
  await expect(page.locator('#page-title')).toHaveText(language==='en'?'Connections':'Подключения');
  for(const width of [1280,610,390,320]){
   await page.setViewportSize({width,height:900});await page.evaluate(()=>setNavCollapsed(true));await expect(page.locator('#check-new-connections')).toBeVisible();
   const metrics=await page.evaluate(()=>{const title=document.querySelector('#page-title').getBoundingClientRect(),action=document.querySelector('#check-new-connections').getBoundingClientRect();return {aligned:Math.abs((title.top+title.bottom-action.top-action.bottom)/2)<2,left:title.right<action.left,overflow:document.documentElement.scrollWidth>innerWidth,inside:action.right<=innerWidth&&title.left>=0};});
   expect(metrics).toEqual({aligned:true,left:true,overflow:false,inside:true});
   if(width===1280||width===390)await page.screenshot({path:`test-results/connections-header-${language}-${width}.png`,fullPage:true});
  }
 }
 expect(requests).toEqual([]);await page.locator('[data-view="models"]').click();await expect(page.locator('#check-new-connections')).toBeHidden();
});
