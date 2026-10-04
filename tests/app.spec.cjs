const {test,expect}=require('./owner-fixture.cjs');
async function openDetails(page,id){const dialog=page.locator('#provider-details-dialog');if(await dialog.isVisible())await page.locator('#close-provider-details').click();await page.locator(`[data-provider="${id}"] .provider-heading`).click();}

test('simple model list, Chinese filter, favorites persist, API check and IDE evidence separate',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/#models');await expect(page.locator('.model-row')).toHaveCount(2);
  await page.getByRole('button',{name:'Фильтры',exact:true}).click();
  await page.getByLabel('Китайские',{exact:true}).check();await expect(page.locator('.model-row')).toHaveCount(1);
  await page.getByRole('button',{name:'Qwen Test',exact:true}).click();await expect(page.locator('.dialog-route')).toHaveCount(2);
  await page.getByRole('button',{name:'Проверить',exact:true}).first().click();
  await expect(page.locator('.dialog-route').first()).toContainText('Ответ получен');
  await expect(page.locator('#dialog-vscode')).toContainText('ещё не проверена');
  await page.getByRole('button',{name:'Добавить в избранное',exact:true}).click();
  await expect(page.locator('#dialog-favorite')).toHaveText('Убрать из избранного');await page.keyboard.press('Escape');
  await page.locator('[data-filter="replied"]').click();await expect(page.locator('.model-row')).toHaveCount(1);
  await page.reload();await page.locator('[data-filter="favorites"]').click();await expect(page.locator('.model-row')).toHaveCount(1);
  await page.getByLabel('Найти модель или разработчика').fill('no-such-model');await expect(page.locator('#empty')).toBeVisible();
  await page.getByRole('button',{name:'Сбросить фильтры'}).click();await page.locator('.star').click();await expect(page.locator('#empty-title')).toHaveText('В избранном пока пусто');
  await page.locator('[data-view="connections"]').click();await expect(page.locator('[data-provider="openrouter"] [data-client="cline"]')).toHaveAttribute('title',/Расширение найдено/);await expect(page.locator('[data-provider="openrouter"] [data-client="opencode"]')).toHaveAttribute('title',/Расширение не найдено/);await expect(page.locator('#source-list')).toContainText('Нужен ключ');
  await page.locator('[data-view="codexbar"]').click();await expect(page.locator('.quota-card')).toHaveCount(1);await expect(page.getByText('0% осталось',{exact:true})).toBeVisible();await expect(page.getByText('Сессия',{exact:true})).toHaveCount(0);expect(errors).toEqual([]);
});

test('unknown prices stay hidden, narrow layout, cached failure and untrusted model names',async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto('/#models');await expect(page.locator('.model-row')).toHaveCount(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Фильтры',exact:true}).click();
  await page.getByLabel('Совместимость с VS Code').selectOption('api');await expect(page.locator('.model-row')).toHaveCount(0);await expect(page.locator('#empty')).toBeVisible();
  await page.getByLabel('Совместимость с VS Code').selectOption('all');
  await page.getByRole('button',{name:'Обновить каталоги',exact:true}).click();await expect(page.locator('#access-alert')).toHaveCount(0);await expect(page.locator('#notice')).toBeHidden();await expect(page.locator('.model-row')).toHaveCount(2);
  await page.getByRole('button',{name:'Подключения',exact:true}).click();await expect(page.locator('#notice')).toBeVisible();await page.locator('[data-view="models"]').click();
  await page.getByRole('button',{name:'Qwen Test',exact:true}).click();await expect(page.locator('.dialog-route').first()).toContainText('Нулевой тариф сохранён');await page.keyboard.press('Escape');
  await page.route('**/api/state',async route=>{const r=await route.fetch(),body=await r.json();body.catalogs.openrouter.models[0].name='<img src=x onerror=alert(1)>';await route.fulfill({json:body});});
  await page.reload();await expect(page.getByRole('button',{name:'<img src=x onerror=alert(1)>',exact:true})).toBeVisible();await expect(page.locator('.model-row img')).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:'test-results/mobile-v2.png',fullPage:true});
});

test('610px app window shows the list without scrolling through controls',async({page})=>{
  await page.setViewportSize({width:610,height:950});
  await page.route('**/api/state',async route=>{
    const r=await route.fetch(),body=await r.json(),source=body.catalogs.openrouter.models[0];
    body.catalogs={openrouter:{models:Array.from({length:12},(_,i)=>({...source,id:`example/test-${i}:free`,name:`Example model ${i}`}))}};
    await route.fulfill({json:body});
  });
  await page.goto('/#models');await expect(page.locator('.model-row')).toHaveCount(12);
  const metrics=await page.evaluate(()=>{
    const list=document.querySelector('.list-scroll').getBoundingClientRect();
    const rows=[...document.querySelectorAll('.model-row')].map(n=>n.getBoundingClientRect());
    return {first:rows[0].top,visible:rows.filter(r=>r.top>=list.top&&r.bottom<=list.bottom).length,
      titleSize:parseFloat(getComputedStyle(document.querySelector('.model-title')).fontSize),
      overflow:document.documentElement.scrollWidth>innerWidth};
  });
  expect(metrics.first).toBeLessThan(280);expect(metrics.visible).toBeGreaterThanOrEqual(5);
  expect(metrics.titleSize).toBeGreaterThanOrEqual(17);expect(metrics.overflow).toBe(false);
  await expect(page.locator('#filter-panel')).toBeHidden();
  await page.getByRole('button',{name:'Фильтры',exact:true}).click();await page.getByLabel('Китайские',{exact:true}).check();
  await page.getByRole('button',{name:'Фильтры · 1',exact:true}).click();await expect(page.locator('#filter-panel')).toBeHidden();
  await expect(page.getByRole('button',{name:'Фильтры · 1',exact:true})).toBeVisible();
});

test('navigation toggle compacts and restores without changing the view',async({page})=>{
  await page.goto('/#models');
  const toggle=page.locator('#toggle-nav');
  await expect(toggle).toBeVisible();
  const before=await toggle.boundingBox();
  await toggle.click();
  await expect(page.locator('body')).toHaveClass(/nav-collapsed/);
  await expect(toggle).toHaveAttribute('aria-expanded','false');
  const compact=await toggle.boundingBox();
  expect(compact.x).toBeLessThan(before.x);
  await page.locator('[data-view="connections"]').click();
  await expect(page.locator('#source-list')).toBeVisible();
  await toggle.click();
  await expect(page.locator('body')).not.toHaveClass(/nav-collapsed/);
  await expect(toggle).toHaveAttribute('aria-expanded','true');
  await expect(page.locator('#source-list')).toBeVisible();
  await toggle.click();
  await page.reload();
  await expect(page.locator('body')).toHaveClass(/nav-collapsed/);
  await expect(toggle).toHaveAttribute('aria-expanded','false');
  await toggle.click();
  await expect(page.locator('body')).not.toHaveClass(/nav-collapsed/);
  expect(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k!=='agentcity-nav-collapsed'))).toEqual([]);
});

test('paste a key in the app, clear on close, save encrypted and remove',async({page})=>{
  const key='synthetic-ui-key-1234567890';
  await page.goto('/#models');await page.locator('[data-view="connections"]').click();
  const provider=page.locator('[data-provider="cline"]');
  await openDetails(page,'cline');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
  await expect(page.locator('#api-key')).toHaveAttribute('type','password');
  await page.locator('#api-key').fill(key);await page.keyboard.press('Escape');
  await expect(page.locator('#api-key')).toHaveValue('');
  await openDetails(page,'cline');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
  await page.locator('#api-key').fill(key);await page.getByRole('button',{name:'Сохранить и обновить'}).click();
  await expect(page.locator('#key-dialog')).not.toBeVisible();
  await expect(page.locator('#api-key')).toHaveValue('');
  await expect(provider).toContainText('Ключ сохранён');
  await expect(page.locator('#provider-details-body').getByRole('button',{name:'Изменить ключ'})).toBeVisible();
  const state=await page.evaluate(()=>fetch('/api/state').then(r=>r.text()));expect(state).not.toContain(key);
  expect(await page.evaluate(()=>Object.keys(localStorage).filter(k=>k!=='agentcity-nav-collapsed'))).toEqual([]);
  await page.reload();await page.locator('[data-view="connections"]').click();
  await openDetails(page,'cline');await page.locator('#provider-details-body').getByRole('button',{name:'Изменить ключ'}).click();
  await page.getByRole('button',{name:'Удалить с компьютера'}).click();
  await page.getByRole('button',{name:'Подтвердить удаление'}).click();
  await expect(page.locator('#key-dialog')).not.toBeVisible();
  await expect(page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'})).toBeVisible();
});

test('pending key save cannot switch provider or refresh the wrong catalogue',async({page})=>{
  let release,started=false;
  const gate=new Promise(resolve=>{release=resolve;}),refreshes=[];
  await page.route('**/api/credential',async route=>{
    if(route.request().postDataJSON().action==='save'){started=true;await gate;}
    await route.continue();
  });
  page.on('request',request=>{if(request.url().endsWith('/api/refresh'))refreshes.push(request.postDataJSON().target);});
  await page.goto('/#models');await page.locator('[data-view="connections"]').click();
  await openDetails(page,'cline');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
  await page.locator('#api-key').fill('synthetic-race-key-1234567890');
  await page.getByRole('button',{name:'Сохранить и обновить'}).click();
  await expect.poll(()=>started).toBe(true);
  try{
    await page.keyboard.press('Escape');
    await openDetails(page,'mistral');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
    await expect(page.locator('#key-dialog')).not.toBeVisible();
    await expect(page.locator('#toast')).toHaveText('Дождись сохранения ключа');
  }finally{release();}
  await expect(page.locator('[data-provider="cline"]')).toContainText('Ключ сохранён');
  await expect.poll(()=>refreshes).toEqual(['cline']);
  await openDetails(page,'mistral');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
  await expect(page.locator('#key-title')).toHaveText('Mistral AI');
  await expect(page.locator('#api-key')).toHaveValue('');
});

test('new API data drives the catalogue, filters and connection form without UI constants',async({page})=>{
  const data=(await (await page.request.get('/api/state')).json());
  data.sources.push({id:'new-api',name:'New API',keyRequired:true,keyUrl:'https://example.invalid/keys',docs:'https://example.invalid/docs',clientIds:['cline']});
  data.catalogs['new-api']={models:[{id:'new/dynamic',name:'Dynamic model',context:8192,tools:true,priceVerified:true}],updatedAt:new Date().toISOString()};
  data.credentials['new-api']=false;
  data.codexbar.providers=[{id:'codex',name:'Codex',windows:[{kind:'session',label:'Сессия',remainingPercent:100}]}];
  await page.route('**/api/state',route=>route.fulfill({json:data}));
  await page.goto('/#models');
  await expect(page.getByRole('button',{name:'Dynamic model',exact:true})).toBeVisible();
  await expect(page.locator('#limits-nav')).toBeHidden();
  await page.locator('#toggle-filters').click();await page.locator('#provider-filter').selectOption('new-api');
  await expect(page.locator('.model-row')).toHaveCount(1);await expect(page.locator('.model-row')).toContainText('Нужен ключ');
  await page.locator('#vscode-filter').selectOption('client');await expect(page.locator('.model-row')).toHaveCount(1);
  await page.locator('[data-view="connections"]').click();
  await openDetails(page,'new-api');await page.locator('#provider-details-body').getByRole('button',{name:'Вставить ключ'}).click();
  await expect(page.locator('#key-title')).toHaveText('New API');await expect(page.locator('#key-account')).toHaveAttribute('href','https://example.invalid/keys');
});

test('full-width vertical rows, usable sidebar and no session quota on small and wide screens',async({page})=>{
  for(const width of [390,610,1600]){
    await page.setViewportSize({width,height:950});await page.goto('/#models');
    await expect(page.locator('.model-row').first()).toBeVisible();
    const metrics=await page.evaluate(()=>{
      const list=document.querySelector('.list-scroll').getBoundingClientRect(),row=document.querySelector('.model-row').getBoundingClientRect(),main=document.querySelector('main').getBoundingClientRect();
      const controls=[...document.querySelectorAll('.app-header button')].filter(e=>e.getBoundingClientRect().width);
      return {gap:innerWidth-list.right,mainRight:main.right,rowWidth:row.width,listWidth:list.width,overflow:document.documentElement.scrollWidth>innerWidth,fit:controls.every(e=>{const r=e.getBoundingClientRect(),a=e.closest('aside').getBoundingClientRect();return r.left>=a.left&&r.right<=a.right&&r.bottom<=a.bottom;})};
    });
    expect(metrics.gap).toBeLessThanOrEqual(32);expect(metrics.mainRight).toBe(width);expect(metrics.rowWidth).toBeGreaterThan(metrics.listWidth-20);expect(metrics.overflow).toBe(false);expect(metrics.fit).toBe(true);
    if(width===390){
      await page.locator('#toggle-nav').click();await expect(page.locator('#nav-backdrop')).toBeVisible();
      await page.locator('[data-view="connections"]').click();await expect(page.locator('#nav-backdrop')).toBeHidden();await expect(page.locator('#source-list')).toBeVisible();
    }
  }
});

test('RU and EN persist, search and filters still work, raw model data stays unchanged',async({page})=>{
  await page.goto('/#models');
  await page.locator('#language').selectOption('en');
  await expect(page.locator('html')).toHaveAttribute('lang','en');await expect(page).toHaveTitle('Agent City ['+new URL(page.url()).hostname+']');
  await expect(page.getByRole('button',{name:'Connections',exact:true})).toBeVisible();
  await expect(page.getByPlaceholder('Find a model')).toBeVisible();
  await page.getByPlaceholder('Find a model').fill('qwen');await expect(page.locator('.model-row')).toHaveCount(1);
  await page.getByRole('button',{name:'Qwen Test',exact:true}).click();
  await expect(page.locator('#dialog-id')).toHaveText('qwen/test:free');
  await expect(page.locator('#dialog-vscode')).toContainText('Tool use has not been checked');
  await expect(page.getByRole('button',{name:'Copy ID',exact:true})).toBeVisible();await page.keyboard.press('Escape');
  await page.reload();await expect(page.locator('#language')).toHaveValue('en');
  await page.locator('[data-view="connections"]').click();
  await openDetails(page,'cline');await page.locator('#provider-details-body').getByRole('button',{name:/^(Paste key|Change key)$/}).click();
  await expect(page.getByRole('button',{name:'Save and refresh',exact:true})).toBeVisible();
  await expect(page.locator('#key-current')).toHaveText(/Create a key|A key was found/);await page.keyboard.press('Escape');
  await page.locator('#close-provider-details').click();await page.locator('#language').selectOption('ru');await expect(page.locator('#page-title')).toHaveText('Подключения');
  await expect(page.getByRole('button',{name:'Обновить каталоги',exact:true})).toBeVisible();
});

test('English limits, errors and narrow layout render without translating model names or replies',async({page})=>{
  await page.route('**/api/state',async route=>{
    const r=await route.fetch(),body=await r.json();
    body.catalogs.openrouter.models[0].name='Модели';
    body.checks['openrouter|qwen/test:free']={status:'ok',reply:'Ответ получен',finishReason:'stop',sent:true,attemptedAt:new Date().toISOString()};
    body.catalogs.openrouter.error='Источник вернул HTTP 403. Попробуй обновить позже.';
    await route.fulfill({json:body});
  });
  await page.setViewportSize({width:390,height:844});await page.goto('/#models');await page.locator('#language').selectOption('en');
  await page.getByRole('button',{name:'Модели',exact:true}).click();
  await expect(page.locator('#model-dialog details')).toHaveCount(0);await expect(page.locator('#dialog-evidence pre').first()).toHaveText('Ответ получен');await page.keyboard.press('Escape');
  await page.locator('[data-view="settings"]').click();await page.locator('#settings-tab-catalogs').click();await expect(page.locator('#catalog-sources')).toBeVisible();
  await page.locator('[data-view="codexbar"]').click();await expect(page.getByText('0% remaining',{exact:true})).toBeVisible();
  const metrics=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,buttons:[...document.querySelectorAll('.page-header button,.page-header select')].every(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})}));
  expect(metrics.overflow).toBe(false);expect(metrics.buttons).toBe(true);
});

test('sources, provider discovery and legacy skipped errors are visible in English',async({page})=>{
 await page.route('**/api/state',async route=>{const r=await route.fetch(),s=await r.json();s.checks['openrouter|qwen/test:free']={status:'skipped',detail:'Не проверена: лимит запросов · http 429',sent:false};await route.fulfill({json:s});});
 await page.goto('/#models');await page.locator('#language').selectOption('en');
 await page.getByRole('button',{name:'Qwen Test',exact:true}).click();
 await expect(page.locator('#dialog-routes')).toContainText('Not checked: Rate limit reached · HTTP 429');
 await expect(page.locator('#dialog-routes').getByRole('link',{name:'Data source ↗'}).first()).toHaveAttribute('href',/^https:/);
 await page.keyboard.press('Escape');await page.locator('[data-view="settings"]').click();
 await page.locator('#settings-tab-agents').click();
 await expect(page.locator('#settings-info')).toContainText('Read-only API');
 await page.locator('#settings-tab-catalogs').click();
 await page.getByText('Provider discovery',{exact:true}).click();
 await page.locator('#settings-view').getByPlaceholder('Find a provider').fill('New Lab');await expect(page.locator('.directory-row')).toHaveCount(1);
 await expect(page.locator('.directory-row')).toContainText('Connection not checked');
});

test('skill edit requires preview, survives poll, saves and loads history as a draft',async({page})=>{
 await page.goto('/#models');await page.locator('#language').selectOption('en');await page.locator('[data-view="skills"]').click();
 await page.getByRole('button',{name:'sample',exact:true}).click();await expect(page.locator('#skill-dialog')).toBeVisible();
 const original=await page.locator('#skill-content').inputValue();
 await page.locator('#skill-content').fill(original+'Changed by the synthetic UI test.\n');
 await expect(page.locator('#save-skill')).toBeDisabled();
 await page.locator('#preview-skill').click();await expect(page.locator('#skill-diff')).toContainText('+Changed by the synthetic UI test.');
 await expect(page.locator('#save-skill')).toBeEnabled();
 await page.evaluate(()=>load());await expect(page.locator('#skill-content')).toHaveValue(original+'Changed by the synthetic UI test.\n');
 await page.locator('#save-skill').click();await expect(page.locator('#skill-message')).toContainText('File saved');
 await page.getByText('Version history',{exact:true}).click();await page.locator('#load-skill-version').click();
 await expect(page.locator('#skill-content')).toHaveValue(original);await expect(page.locator('#save-skill')).toBeDisabled();
 await page.locator('#preview-skill').click();await page.locator('#save-skill').click();await expect(page.locator('#skill-message')).toContainText('File saved');
 await page.locator('#close-skill').click();
 await page.setViewportSize({width:390,height:844});await page.locator('[data-view="skills"]').click();await expect(page.locator('#nav-backdrop')).toBeHidden();await page.getByRole('button',{name:'sample',exact:true}).click();await expect(page.locator('#skill-dialog')).toBeVisible();
 expect(await page.locator('#skill-dialog').evaluate(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;})).toBe(true);
});
