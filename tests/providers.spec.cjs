const {test,expect}=require('./owner-fixture.cjs');

test('a delayed pre-delete poll cannot resurrect a deleted provider',async({page})=>{
 await page.goto('/#connections');let release,captured;
 const gate=new Promise(resolve=>release=resolve),ready=new Promise(resolve=>captured=resolve);
 await page.route('**/api/state',async route=>{const old=await(await route.fetch()).json();captured();await gate;await route.fulfill({json:old});});
 await page.evaluate(()=>{window.pendingProviderPoll=load();});await ready;
 try{
  const row=page.locator('[data-provider="openrouter"]');
  await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();await expect(row).toHaveCount(0);
  release();await page.evaluate(()=>window.pendingProviderPoll);await expect(row).toHaveCount(0);
 }finally{
  release();const data=await(await page.request.get('/api/state')).json();
  if(!data.sources.some(source=>source.id==='openrouter'))await page.request.post('/api/providers/add',{data:{website:'https://openrouter.ai',revision:data.providerRegistry.revision},headers:{'X-Agent-City':'1','X-Agent-City-Token':data.csrfToken}});
 }
});

test('a delayed Refresh response cannot hide a newly added provider',async({page})=>{
 await page.goto('/#connections');let release,captured;
 const gate=new Promise(resolve=>release=resolve),ready=new Promise(resolve=>captured=resolve);
 await page.route('**/api/refresh',async route=>{const old=await(await page.request.get('/api/state')).json();captured();await gate;await route.fulfill({json:old});});
 await page.evaluate(()=>{const original=request;request=(...args)=>{const pending=original(...args);if(args[0]==='/api/refresh')window.pendingProviderRefresh=pending;return pending;};});
 await page.locator('#refresh').click();await ready;
 try{
  await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://refresh-race.example');await page.locator('#save-provider').click();
  const row=page.locator('[data-provider^="website-"]').filter({hasText:'refresh-race.example'});await expect(row).toBeVisible();
  release();await page.evaluate(()=>window.pendingProviderRefresh);await expect(row).toBeVisible();
  await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
 }finally{release();}
});

test('website addition, reload, cancel removal and persistent deletion use no provider request',async({page})=>{
 const errors=[],network=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(new URL(r.url()).hostname!==process.env.AGENT_CITY_UI_OWNER_HOST&&!new URL(r.url()).hostname.match(/^(127\.0\.0\.1|localhost)$/))network.push(r.url());});
 await page.goto('/#connections');await page.locator('#add-provider').click();
 await page.locator('#provider-website').fill('https://ui-lab.example/docs');
 await page.locator('#save-provider').click();await expect(page.locator('#provider-dialog')).toBeHidden();
 const row=page.locator('[data-provider^="website-"]').filter({hasText:'ui-lab.example'});
 await expect(row).toContainText('API-адаптер не поддерживается');
 await expect(row.getByRole('button',{name:'Вставить ключ'})).toHaveCount(0);
 await page.reload();await expect(row).toBeVisible();
 await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#cancel-remove-provider').click();await expect(row).toBeVisible();
 await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();await expect(row).toHaveCount(0);
 await page.reload();await expect(row).toHaveCount(0);expect(network).toEqual([]);expect(errors).toEqual([]);
});

test('known provider can be removed and restored by website without fetching or inference',async({page})=>{
 const forbidden=[];page.on('request',r=>{if(['/api/refresh','/api/check','/api/check-pending','/api/credential','/api/cloud/sync'].some(p=>r.url().endsWith(p)))forbidden.push(r.url());});
 await page.goto('/#connections');const row=page.locator('[data-provider="openrouter"]');
 await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();await expect(row).toHaveCount(0);
 await page.reload();await expect(row).toHaveCount(0);
 await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://openrouter.ai');await page.locator('#save-provider').click();
 await expect(row).toBeVisible();await row.locator('.provider-heading').click();await expect(page.locator('#provider-details-body').getByRole('button',{name:/^(Вставить|Изменить) ключ$/})).toBeVisible();expect(forbidden).toEqual([]);
});

test('duplicate and invalid links keep the form draft; Escape supports discard or continued editing',async({page})=>{
 await page.goto('/#connections');await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://openrouter.ai');await page.locator('#save-provider').click();
 await expect(page.locator('#provider-error')).toHaveText('Этот провайдер уже добавлен.');await expect(page.locator('#provider-website')).toHaveValue('https://openrouter.ai');
 await page.locator('#provider-website').fill('https://unknown.example/?token=do-not-store');await page.locator('#save-provider').click();await expect(page.locator('#provider-error')).toContainText('без токенов');
 page.once('dialog',dialog=>dialog.dismiss());await page.keyboard.press('Escape');await expect(page.locator('#provider-dialog')).toBeVisible();
 page.once('dialog',dialog=>dialog.accept());await page.keyboard.press('Escape');await expect(page.locator('#provider-dialog')).toBeHidden();
 await page.locator('#add-provider').click();await expect(page.locator('#provider-website')).toHaveValue('');await page.locator('#close-provider').click();
});

test('pending save blocks repeated clicks and closing; save failure preserves draft for retry',async({page})=>{
 let posts=0,release;const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/providers/add',async route=>{posts++;if(posts===1){await gate;await route.fulfill({status:500,json:{error:'Synthetic write failed'}});}else await route.continue();});
 await page.goto('/#connections');await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://retry-lab.example');await page.locator('#save-provider').click();
 await expect(page.locator('#save-provider')).toBeDisabled();await expect(page.locator('#close-provider')).toBeDisabled();
 await page.evaluate(()=>document.querySelector('#provider-form').dispatchEvent(new Event('submit',{cancelable:true})));
 await page.keyboard.press('Escape');await expect(page.locator('#provider-dialog')).toBeVisible();expect(posts).toBe(1);release();
 await expect(page.locator('#provider-error')).toHaveText('Synthetic write failed');await expect(page.locator('#provider-website')).toHaveValue('https://retry-lab.example');
 await page.locator('#save-provider').click();await expect(page.locator('#provider-dialog')).toBeHidden();expect(posts).toBe(2);
 const row=page.locator('[data-provider^="website-"]').filter({hasText:'retry-lab.example'});await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
});

test('revision conflict refreshes state without losing draft and allows explicit retry',async({page})=>{
 let posts=0;
 await page.route('**/api/providers/add',async route=>{posts++;if(posts===1)await route.fulfill({status:409,json:{error:'Список изменился. Обнови список и повтори действие.'}});else await route.continue();});
 await page.goto('/#connections');await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://conflict-lab.example');await page.locator('#save-provider').click();
 await expect(page.locator('#provider-error')).toContainText('Список изменился');await expect(page.locator('#provider-website')).toHaveValue('https://conflict-lab.example');
 await expect(page.locator('#save-provider')).toBeEnabled();await page.locator('#save-provider').click();await expect(page.locator('#provider-dialog')).toBeHidden();
 const row=page.locator('[data-provider^="website-"]').filter({hasText:'conflict-lab.example'});await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
});

test('only explicit zero pricing is shown; narrow provider form keeps controls and errors visible',async({page})=>{
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();data.catalogs={openrouter:{models:[
  {id:'confirmed',name:'Confirmed zero',priceVerified:true},
  {id:'confirmed-paid',name:'Known paid price',priceVerified:false,pricing:{prompt:'0.01',completion:'0.02'}},
  {id:'unknown:free',name:'Unknown price despite free ID',priceVerified:false},
  {id:'trial:free',name:'Conditional trial credits',priceVerified:false,plan:'trial',freeCredits:10},
  {id:'missing',name:'Missing price'},
 ]}};await route.fulfill({json:data});});
 await page.goto('/#models');await expect(page.locator('.model-row')).toHaveCount(1);await expect(page.locator('.model-row')).toContainText('Confirmed zero');
 await page.setViewportSize({width:390,height:844});await page.locator('[data-view="connections"]').click();await page.locator('#add-provider').click();
 await expect(page.locator('#provider-title')).toBeVisible();await expect(page.locator('#save-provider')).toBeInViewport();await expect(page.locator('#close-provider')).toBeInViewport();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/provider-form-mobile.png'});
 await page.locator('#provider-website').fill('https://127.0.0.1');await page.locator('#save-provider').click();await expect(page.locator('#provider-error')).toContainText('не IP-адрес');
 await page.screenshot({path:'test-results/provider-form-error-mobile.png'});
});

test('empty provider list and English form show an actionable state',async({page})=>{
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();data.sources=[];data.catalogs={};await route.fulfill({json:data});});
 await page.goto('/#connections');await expect(page.locator('#source-list')).toContainText('Провайдеров пока нет');
 await page.screenshot({path:'test-results/providers-empty.png'});
 await page.locator('#language').selectOption('en');await page.locator('#add-provider').click();
 await expect(page.locator('#provider-title')).toHaveText('Add provider');await expect(page.locator('#save-provider')).toHaveText('Add');
 await expect(page.locator('#provider-dialog')).toContainText('Website and API addresses differ');
 await page.screenshot({path:'test-results/provider-form-desktop-en.png'});
});

test('network failure restores controls and retains the draft without automatic retry',async({page})=>{
 let posts=0;await page.route('**/api/providers/add',route=>{posts++;return route.abort('failed');});
 await page.goto('/#connections');await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://offline-lab.example');await page.locator('#save-provider').click();
 await expect(page.locator('#provider-error')).toContainText('изменение могло сохраниться');
 await expect(page.locator('#save-provider')).toBeEnabled();await expect(page.locator('#provider-website')).toHaveValue('https://offline-lab.example');expect(posts).toBe(1);
});

test('Zen Groq Cerebras add then Refresh updates cards immediately and survives reload',async({page})=>{
 const catalogs={},refreshes=[];
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();Object.assign(data.catalogs,catalogs);await route.fulfill({json:data});});
 let selected;
 await page.route('**/api/refresh',async route=>{
  const body=route.request().postDataJSON();expect(body.target).toBe('catalog');refreshes.push(selected);
  const data=await(await page.request.get('/api/state')).json();
  expect(route.request().headers()['x-agent-city-token']).toBe(data.csrfToken);
  catalogs[selected]={models:[{id:`${selected}/unpriced`,name:'Synthetic unknown-price model',priceVerified:false}],updatedAt:new Date().toISOString(),error:null};
  Object.assign(data.catalogs,catalogs);data.busy=[];await route.fulfill({json:data});
 });
 await page.goto('/#connections');
 for(const [id,site] of [['zen','https://opencode.ai'],['groq','https://groq.com'],['cerebras','https://cerebras.ai']]){
  selected=id;const row=page.locator(`[data-provider="${id}"]`);
  await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();await expect(row).toHaveCount(0);
  await page.locator('#add-provider').click();await page.locator('#provider-website').fill(site);await page.locator('#save-provider').click();await expect(row).toBeVisible();
  await page.locator('#refresh').click();await expect(row.locator('.provider-catalog-state')).toHaveText('Бесплатность моделей не подтверждена.');
  await page.reload();await expect(row).toBeVisible();await expect(row.locator('.provider-catalog-state')).toHaveText('Бесплатность моделей не подтверждена.');
 }
 expect(refreshes).toEqual(['zen','groq','cerebras']);
});

test('403 with no snapshot does not claim cached models, and a real snapshot is identified',async({page})=>{
 await page.route('**/api/state',async route=>{
  const data=await(await route.fetch()).json();
  data.catalogs.zen={models:[],error:'Доступ отклонён · HTTP 403',attemptedAt:'2026-10-01T09:00:00Z'};
  data.catalogs.groq={models:[],updatedAt:'2026-09-27T00:00:00Z',error:'Доступ отклонён · HTTP 403'};
  data.catalogs.cerebras={models:[{id:'old',priceVerified:false}],updatedAt:'2026-09-27T00:00:00Z',error:'Доступ отклонён · HTTP 403'};
  await route.fulfill({json:data});
 });
 await page.goto('/#connections');
 await expect(page.locator('[data-provider="zen"] .provider-cache-note')).toHaveText('Каталог не получен. Сохранённых моделей нет.');
 await expect(page.locator('[data-provider="groq"] .provider-cache-note')).toHaveText('Обновление не удалось. Последний сохранённый каталог пуст.');
 await expect(page.locator('[data-provider="cerebras"] .provider-cache-note')).toContainText('Показан сохранённый каталог от');
 await expect(page.locator('[data-provider="zen"] .provider-attempt')).toContainText('Попытка обновления:');
 await page.locator('#language').selectOption('en');await expect(page.locator('#notice')).not.toContainText('Cached models remain');
 await expect(page.locator('[data-provider="zen"] .provider-cache-note')).toHaveText('Catalog not received. No cached models.');
 await page.screenshot({path:'test-results/providers-403-precise.png',fullPage:true});
});

test('paid-only and unknown-price providers remain stored while the model list is free only',async({page})=>{
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();
  data.catalogs.openrouter={models:[],updatedAt:'2026-10-01T00:00:00Z',pricingSummary:{confirmedFree:0,knownPaid:4,unknown:0,complete:true}};
  data.catalogs.groq={models:[{id:'unknown:free',priceVerified:false}],updatedAt:'2026-10-01T00:00:00Z'};
  await route.fulfill({json:data});
 });
 await page.goto('/#connections');
 await expect(page.locator('[data-provider="openrouter"] .provider-catalog-state')).toHaveText('Бесплатных моделей в полученном каталоге нет.');
 await expect(page.locator('[data-provider="groq"] .provider-catalog-state')).toHaveText('Бесплатность моделей не подтверждена.');
 await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://paid-only-ui.example');await page.locator('#save-provider').click();
 const row=page.locator('[data-provider^="website-"]').filter({hasText:'paid-only-ui.example'});await expect(row).toContainText('API-адаптер не поддерживается');
 await page.reload();await expect(row).toBeVisible();await expect(page.locator('[data-provider="openrouter"]')).toBeVisible();
 await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
});


test('client tags distinguish declared support, installation and unmapped subscriptions; filters combine with search and refresh',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto('/#connections');
 await expect(page.locator('#client-list')).toHaveCount(0);await expect(page.locator('#bar-connection')).toHaveCount(0);
 const openrouter=page.locator('[data-provider="openrouter"]');
 await expect(openrouter.locator('[data-client="cline"]')).toHaveText('Cline');
 await expect(openrouter.locator('[data-client="cline"]')).toHaveAttribute('title',/Настройка провайдера и авторизация.*не проверены/);
 await expect(openrouter.locator('[data-client="kilo"]')).toHaveAttribute('title',/Установка расширения неизвестна/);
 await expect(page.locator('#client-mapping-note')).toHaveCount(0);
 for(const [client,ids] of [['cline',['openrouter','cline']],['kilo',['openrouter','kilo']],['opencode',['openrouter','zen']],['codexbar',[]]]){
  await page.locator('#connection-client').selectOption(client);
  expect(await page.locator('#source-list [data-provider]').evaluateAll(rows=>rows.map(row=>row.dataset.provider))).toEqual(ids);
 }
 await expect(page.locator('#source-list')).toContainText('Нет провайдеров');
 await page.locator('#connection-client').selectOption('unknown');await expect(page.locator('[data-provider="groq"]')).toBeVisible();await expect(page.locator('[data-provider="openrouter"]')).toHaveCount(0);
 await page.locator('#connection-client').selectOption('cline');await page.locator('#connection-search').fill('openrouter');await expect(page.locator('#source-list [data-provider]')).toHaveCount(1);
 await page.route('**/api/refresh',async route=>{const data=await(await page.request.get('/api/state')).json();await route.fulfill({json:data});});
 await page.locator('#refresh').click();await expect(page.locator('#connection-client')).toHaveValue('cline');await expect(page.locator('#connection-search')).toHaveValue('openrouter');await expect(openrouter).toBeVisible();
 await page.locator('#connection-search').fill('no-such-provider');await expect(page.locator('#source-list')).toContainText('Нет провайдеров');
 await page.locator('#connection-client').selectOption('all');await page.locator('#connection-search').fill('groq');await expect(page.locator('[data-provider="groq"]')).toContainText('Связь с клиентами не подтверждена');expect(errors).toEqual([]);
});

test('CodexBar exact ID is a snapshot tag, never client authentication; responsive filters and tags fit',async({page})=>{
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();data.codexbar.providers.push({id:'openrouter',name:'OpenRouter',updatedAt:new Date().toISOString(),error:true,windows:[]});await route.fulfill({json:data});});
 await page.goto('/#connections');await page.locator('#connection-client').selectOption('codexbar');
 await expect(page.locator('#source-list [data-provider]')).toHaveCount(1);await expect(page.locator('[data-client="codexbar"]')).toHaveAttribute('title',/Ошибка источника.*Авторизация API не подтверждена/);
 await page.locator('#connection-client').selectOption('all');await page.setViewportSize({width:390,height:844});await page.locator('#toggle-nav').click();
 await expect(page.locator('#connection-search')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:'test-results/provider-clients-mobile.png',fullPage:true});await page.locator('[data-provider="openrouter"]').scrollIntoViewIfNeeded();await page.screenshot({path:'test-results/provider-clients-mobile-tags.png',fullPage:true});
 await page.setViewportSize({width:1280,height:900});await page.locator('#language').selectOption('en');await expect(page.locator('#connection-client option[value="all"]')).toHaveText('All clients');
 await page.screenshot({path:'test-results/provider-clients-desktop.png',fullPage:true});
});


test('filtering does not discard an unsaved inline key draft or submit it',async({page})=>{
 const writes=[];page.on('request',r=>{if(r.url().endsWith('/api/credential'))writes.push(r.url());});
 await page.goto('/#connections');await page.locator('[data-provider="groq"] .provider-heading').click();const input=page.locator('[data-provider="groq"] .inline-key-form input');await page.locator('#provider-details-body .inline-key-form input').fill('synthetic-filter-draft');await page.locator('#close-provider-details').click();
 await page.locator('#connection-client').selectOption('cline');await expect(input).toHaveCount(0);
 await page.locator('#connection-client').selectOption('all');await expect(input).toHaveValue('synthetic-filter-draft');
 await page.locator('#connection-search').fill('openrouter');await expect(input).toHaveCount(0);await page.locator('#connection-search').fill('');await expect(input).toHaveValue('synthetic-filter-draft');expect(writes).toEqual([]);
});


test('client tags occupy a separate bottom row below key status on desktop and mobile',async({page})=>{
 await page.route('**/api/state',async route=>{const data=await(await route.fetch()).json();data.catalogs.openrouter.authStatus='accepted';data.credentialInfo.openrouter.available=true;data.credentials.openrouter=true;await route.fulfill({json:data});});
 await page.goto('/#connections');await page.locator('#connection-search').fill('openrouter');
 const row=page.locator('[data-provider="openrouter"]');
 for(const width of [1280,390]){
  await page.setViewportSize({width,height:900});if(width===390)await page.locator('#toggle-nav').click();
  await row.scrollIntoViewIfNeeded();await expect(row.locator('.connection-actions > .status')).toHaveText('Ключ сохранён · доступ не проверен');
  const layout=await row.evaluate(row=>{const status=row.querySelector('.connection-actions > .status').getBoundingClientRect(),actions=row.querySelector('.connection-actions').getBoundingClientRect(),tags=row.querySelector('.provider-client-tags').getBoundingClientRect();return {below:tags.top>=actions.bottom&&tags.top>=status.bottom,last:row.lastElementChild.classList.contains('provider-client-tags'),overflow:document.documentElement.scrollWidth>innerWidth};});
  expect(layout).toEqual({below:true,last:true,overflow:false});
  await page.screenshot({path:`test-results/provider-tags-bottom-${width}.png`,fullPage:true});
 }
 await page.locator('#connection-client').selectOption('opencode');await expect(row).toBeVisible();await expect(row.locator('[data-client="opencode"]')).toHaveText('OpenCode');
});


test('client marks use only equal-sized neutral names, with keyboard and touch-accessible explanations',async({page})=>{
 await page.goto('/#connections');await page.locator('#connection-search').fill('openrouter');const row=page.locator('[data-provider="openrouter"]'),tags=row.locator('button[data-client]');
 await expect(tags).toHaveText(['Cline','Kilo Code','OpenCode']);
 expect(await tags.evaluateAll(tags=>tags.map(tag=>[tag.getBoundingClientRect().width,tag.getBoundingClientRect().height]))).toEqual([[100,28],[100,28],[100,28]]);
 const cline=row.locator('[data-client="cline"]');await cline.focus();await page.keyboard.press('Enter');await expect(cline).toHaveAttribute('aria-expanded','true');await expect(row.locator('.provider-client-description')).toContainText('Объявленная поддержка клиента');await expect(row.locator('.provider-client-description')).toContainText('авторизация в клиенте не проверены');
 await page.keyboard.press('Enter');await expect(row.locator('.provider-client-description')).toHaveCount(0);
 await page.setViewportSize({width:390,height:900});await page.locator('#toggle-nav').click();await row.locator('[data-client="opencode"]').click();await expect(row.locator('.provider-client-description')).toContainText('Расширение не найдено');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await row.scrollIntoViewIfNeeded();await page.screenshot({path:'test-results/provider-neutral-tags-mobile.png',fullPage:true});await page.setViewportSize({width:1280,height:900});await page.screenshot({path:'test-results/provider-neutral-tags-desktop.png',fullPage:true});
});


test('provider modal traps focus, closes with Escape, restores focus, preserves draft on refresh and reopen',async({page})=>{
 await page.goto('/#connections');const row=page.locator('[data-provider="openrouter"]'),heading=row.locator('.provider-heading'),dialog=page.locator('#provider-details-dialog');
 await expect(row.locator('details')).toHaveCount(0);await expect(row.locator('.inline-key-form')).toBeHidden();await heading.focus();await page.keyboard.press('Enter');await expect(dialog).toBeVisible();await expect(page.locator('#close-provider-details')).toBeFocused();await page.locator('#provider-details-body .inline-key-form input').fill('synthetic-modal-draft-12345');await page.evaluate(()=>load());await expect(dialog).toBeVisible();await expect(page.locator('#provider-details-body .inline-key-form input')).toHaveValue('synthetic-modal-draft-12345');
 await page.keyboard.press('Escape');await expect(dialog).toBeHidden();await expect(heading).toBeFocused();await heading.click();await expect(page.locator('#provider-details-body .inline-key-form input')).toHaveValue('synthetic-modal-draft-12345');await page.setViewportSize({width:390,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/provider-modal-mobile.png',fullPage:true});await page.locator('#close-provider-details').click();await expect(dialog).toBeHidden();
});

test('optional key saves locally after adding a known provider without any refresh; unknown website never receives key',async({page})=>{
 const key='synthetic-optional-key-123456789',requests=[];page.on('request',r=>{if(r.method()==='POST')requests.push({url:new URL(r.url()).pathname,body:r.postDataJSON()});});
 await page.goto('/#connections');const row=page.locator('[data-provider="groq"]');await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
 await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://groq.com');await page.locator('#provider-api-key').fill(key);await page.locator('#save-provider').click();await expect(page.locator('#provider-dialog')).toBeHidden();await expect(row).toContainText('Ключ сохранён');
 expect(requests.filter(r=>r.url==='/api/credential').map(r=>r.body.provider)).toEqual(['groq']);expect(requests.find(r=>r.url==='/api/providers/add').body.key).toBeUndefined();expect(requests.some(r=>r.url==='/api/refresh')).toBe(false);expect(await page.request.get('/api/state').then(r=>r.text())).not.toContain(key);expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain(key);
 await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://unsupported-key.example');await page.locator('#provider-api-key').fill(key);const before=requests.length;await page.locator('#save-provider').click();await expect(page.locator('#provider-error')).toContainText('ввод ключа не поддерживается');expect(requests.slice(before).map(r=>r.url)).toEqual(['/api/providers/resolve']);expect(JSON.stringify(requests.slice(before))).not.toContain(key);
 await page.locator('#provider-api-key').fill('');await page.locator('#save-provider').click();await expect(page.locator('[data-provider^="website-"]').filter({hasText:'unsupported-key.example'})).toBeVisible();
});

test('partial provider save retains record and retries only key; duplicate clicks and close are blocked',async({page})=>{
 const key='synthetic-partial-key-123456789';let release,keys=0,adds=0;const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/providers/add',async route=>{adds++;await route.continue();});
 await page.route('**/api/credential',async route=>{keys++;if(keys===1){await gate;await route.fulfill({status:500,json:{error:'Synthetic failure'}});}else await route.continue();});
 await page.goto('/#connections');const row=page.locator('[data-provider="cerebras"]');await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();
 await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://cerebras.ai');await page.locator('#provider-api-key').fill(key);await page.locator('#save-provider').click();await expect(page.locator('#save-provider')).toBeDisabled();await page.keyboard.press('Escape');await expect(page.locator('#provider-dialog')).toBeVisible();await page.evaluate(()=>document.querySelector('#provider-form').dispatchEvent(new Event('submit',{cancelable:true})));release();
 await expect(page.locator('#provider-error')).toContainText('Провайдер сохранён, но ключ не сохранён');await expect(row).toBeVisible();await expect(page.locator('#provider-api-key')).toHaveValue(key);await expect(page.locator('#save-provider')).toHaveText('Сохранить ключ');await page.locator('#save-provider').click();await expect(page.locator('#provider-dialog')).toBeHidden();expect(adds).toBe(1);expect(keys).toBe(2);await expect(page.locator('#provider-api-key')).toHaveValue('');
});


test('optional key draft is cleared on confirmed close, and the add form remains usable on mobile',async({page})=>{
 await page.goto('/#connections');await page.setViewportSize({width:390,height:900});await page.locator('#toggle-nav').click();await page.locator('#add-provider').click();await expect(page.locator('#provider-api-key')).toHaveAttribute('type','password');await expect(page.locator('#provider-api-key')).not.toHaveAttribute('required','');await page.screenshot({path:'test-results/provider-add-optional-mobile.png',fullPage:true});
 await page.locator('#provider-website').fill('https://cancel-key.example');await page.locator('#provider-api-key').fill('synthetic-cancel-key-123456789');page.once('dialog',dialog=>dialog.accept());await page.locator('#close-provider').click();await expect(page.locator('#provider-api-key')).toHaveValue('');await page.locator('#add-provider').click();await expect(page.locator('#provider-api-key')).toHaveValue('');
});

test('uncertain optional key response preserves provider and requires an explicit retry',async({page})=>{
 let writes=0;await page.route('**/api/credential',route=>{writes++;return route.abort('failed');});await page.goto('/#connections');const row=page.locator('[data-provider="zen"]');await row.getByRole('button',{name:'Удалить провайдера'}).click();await page.locator('#confirm-remove-provider').click();await page.locator('#add-provider').click();await page.locator('#provider-website').fill('https://opencode.ai');await page.locator('#provider-api-key').fill('synthetic-uncertain-key-123456789');await page.locator('#save-provider').click();await expect(page.locator('#provider-error')).toContainText('Сохранение ключа не подтверждено');await expect(row).toBeVisible();expect(writes).toBe(1);await expect(page.locator('#save-provider')).toBeEnabled();
});


test('OpenAI and Claude are independent references with separate API and subscription details, never an automatic login',async({page})=>{
 const writes=[];page.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});await page.goto('/#connections');
 for(const id of ['openai','anthropic']){
  const row=page.locator(`[data-provider="${id}"]`);await expect(row).toBeVisible();await expect(row.locator('.connection-actions button').last()).toBeDisabled();await row.locator('.provider-heading').click();const body=page.locator('#provider-details-body');await expect(body.getByRole('heading',{name:'API',exact:true})).toBeVisible();await expect(body.getByRole('heading',{name:'Подписка',exact:true})).toBeVisible();await expect(body.locator('input')).toHaveCount(0);await expect(body.locator('details')).toHaveCount(0);
  await page.keyboard.press('Shift+Tab');await expect(page.locator('#provider-details-dialog')).toBeVisible();expect(await page.evaluate(()=>document.activeElement.closest('#provider-details-dialog')!==null)).toBe(true);
  if(id==='openai')await page.screenshot({path:'test-results/provider-reference-desktop.png',fullPage:true});await page.keyboard.press('Escape');await expect(row.locator('.provider-heading')).toBeFocused();
 }
 expect(writes).toEqual([]);await page.locator('[data-view="models"]').click();await page.getByRole('button',{name:'Qwen Test',exact:true}).click();await expect(page.locator('#dialog-id')).toHaveText('qwen/test:free');await expect(page.locator('#model-dialog details')).toHaveCount(0);await page.screenshot({path:'test-results/model-details-desktop.png',fullPage:true});
});
