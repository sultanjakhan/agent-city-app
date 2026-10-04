const {test,expect}=require('./owner-fixture.cjs');
test.afterEach(async({page})=>{await page.unrouteAll({behavior:'wait'});});

const observed='2026-09-27T09:00:00Z',attempted='2026-10-02T11:00:00Z';
function facts({saved=true,localOnly=false,error=null,accepted=false}={}){
 return {catalog:{state:saved?'saved':'missing',source:saved?'published_docs':'none',sourceUrl:'https://example.invalid/catalog',updatedAt:saved?observed:null,observedAt:saved?observed:null,stale:saved,modelCount:saved?1:0},
  refresh:{state:localOnly?'paused':'available',attemptedAt:attempted,lastResult:error?'failed':'not_checked',error},
  providerAvailability:'not_checked',authentication:{state:localOnly?'paused':'not_checked',lastObservation:accepted?{status:'accepted',observedAt:observed}:null,clientObservation:null},entitlement:'not_checked',inference:{state:localOnly?'paused':'not_checked',lastCompletedReplyAt:null}};
}

test('saved documentation and failed refresh stay distinct from account access in compact cards and details',async({page})=>{
 const errors=[],protectedRequests=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(['/api/refresh','/api/credential','/api/check','/api/cloud/sync'].some(p=>r.url().endsWith(p)))protectedRequests.push(r.url());});
 await page.route('**/api/state',async route=>{
  const data=await(await route.fetch()).json();
  data.catalogs.groq={models:[{id:'saved',priceVerified:false}],updatedAt:observed,observedAt:observed,catalogScope:'published',attemptedAt:attempted,error:'HTTP 403 synthetic-private-body',authStatus:'accepted'};
  data.connectionStatus.groq=facts({error:{category:'forbidden',httpStatus:403}});
  data.catalogs.cerebras={models:[],attemptedAt:attempted,error:'HTTP 403 synthetic-private-body'};
  data.connectionStatus.cerebras=facts({saved:false,error:{category:'forbidden',httpStatus:403}});
  await route.fulfill({json:data});
 });
 await page.goto('/#connections');const row=page.locator('[data-provider="groq"]');
 await expect(row.locator('.connection-catalog-summary')).toContainText('Документация · снимок');
 await expect(row.locator('.connection-catalog-summary')).toContainText('Обновление не удалось');
 await expect(row.locator('.connection-access-status')).toContainText('доступ не проверен');
 await expect(row.locator('.connection-access-status')).not.toHaveClass(/good/);
 await expect(page.locator('[data-provider="cerebras"] .connection-catalog-summary')).toContainText('Каталог не получен');
 await expect(row.locator('.connection-facts')).toBeHidden();
 await row.locator('.provider-heading').click();const details=page.locator('#provider-details-body');
 await expect(details.locator('.connection-facts')).toContainText('Опубликованная документация');
 await expect(details.locator('.connection-facts')).toContainText('Доступ аккаунта к моделямНе проверен');
 await expect(details.locator('.provider-receipt').first()).toContainText('Источник каталога отклонил запрос · HTTP 403');
 await expect(details).not.toContainText('synthetic-private-body');
 await expect(details.locator('.connection-evidence-note')).toContainText('доступность всего провайдера не установлены');
 await page.locator('#language').selectOption('en');
 await expect(details.locator('.connection-facts')).toContainText('Published documentation');
 await expect(details.locator('.connection-facts')).not.toContainText(/[А-Яа-яЁё]/);
 await expect(details.locator('.provider-receipt').first()).toContainText('Catalog source rejected the request · HTTP 403');
 await page.locator('#close-provider-details').click();await expect(row.locator('.provider-heading')).toBeFocused();
 await page.setViewportSize({width:390,height:844});await page.locator('#toggle-nav').click();await row.locator('.provider-heading').click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/connection-status-mobile.png'});
 expect(errors).toEqual([]);expect(protectedRequests).toEqual([]);
});

test('local-only never turns a saved accepted key into current access and blocks card actions',async({page})=>{
 const requests=[];page.on('request',r=>{if(['/api/refresh','/api/credential','/api/check','/api/cloud/sync'].some(p=>r.url().endsWith(p)))requests.push(r.url());});
 await page.route('**/api/state',async route=>{
  const data=await(await route.fetch()).json();data.settings.localOnly=true;
  data.catalogs.openrouter={models:[{id:'cached',priceVerified:true}],updatedAt:observed,attemptedAt:observed,authStatus:'accepted'};
  data.connectionStatus.openrouter=facts({localOnly:true,accepted:true});
  for(const key of Object.keys(data.credentials))data.credentials[key]=null;
  for(const key of Object.keys(data.credentialInfo))data.credentialInfo[key]={available:null,source:'paused',canSave:false,localOnly:true};
  await route.fulfill({json:data});
 });
 await page.goto('/#connections');const row=page.locator('[data-provider="openrouter"]');
 await expect(row.locator('.connection-access-status')).toHaveText('Доступ не проверен · local-only');
 await expect(row.locator('.connection-access-status')).not.toHaveClass(/good/);
 await expect(row.getByRole('button',{name:'Обновить каталог',exact:true})).toBeDisabled();
 await expect(page.locator('#refresh')).toBeDisabled();
 await row.locator('.provider-heading').click();const details=page.locator('#provider-details-body');
 await expect(details.locator('.connection-facts')).toContainText('Приостановлена · local-only');
 await expect(details.getByRole('button',{name:'Вставить ключ',exact:true})).toBeDisabled();
 await expect(details.locator('input[type="password"]')).toBeDisabled();
 await page.evaluate(()=>refreshSource('openrouter'));await page.evaluate(()=>openKey('openrouter'));
 await expect(page.locator('#key-dialog')).toBeHidden();
 await page.locator('#close-provider-details').click();await page.reload();
 await expect(row.locator('.connection-access-status')).toHaveText('Доступ не проверен · local-only');
 expect(requests).toEqual([]);
});

test('refresh failure preserves the saved date and restores controls for an explicit retry',async({page})=>{
 let calls=0;
 await page.route('**/api/refresh',async route=>{
  calls++;const data=await(await page.request.get('/api/state')).json();data.busy=[];
  data.catalogs.kilo={models:[{id:'saved',priceVerified:true}],updatedAt:observed,attemptedAt:attempted,error:'network failed synthetic-private-body'};
  data.connectionStatus.kilo=facts({error:{category:'network',httpStatus:null}});
  await route.fulfill({json:data});
 });
 await page.goto('/#connections');const row=page.locator('[data-provider="kilo"]');
 await row.getByRole('button',{name:'Обновить каталог',exact:true}).click();
 await expect(row.locator('.connection-catalog-summary')).toContainText('Обновление не удалось');
 await row.locator('.provider-heading').click();
 await expect(page.locator('#provider-details-body .provider-receipt').first()).toContainText('Не удалось подключиться к источнику каталога.');
 await expect(page.locator('#provider-details-body')).not.toContainText('synthetic-private-body');
 await expect(page.locator('#provider-details-body .provider-cache-note')).toContainText('Показан сохранённый каталог от');
 await page.locator('#close-provider-details').click();
 await expect(row.getByRole('button',{name:'Обновить каталог',exact:true})).toBeEnabled();
 const retried=page.waitForResponse(response=>response.url().endsWith('/api/refresh'));
 await row.getByRole('button',{name:'Обновить каталог',exact:true}).click();
 await retried;
 await expect.poll(()=>calls).toBe(2);
});
