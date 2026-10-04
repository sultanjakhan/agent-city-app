// UI-only acceptance using a previously captured LOCAL panel snapshot.
// No model requests, catalogue refreshes, credentials or account reads.
const {chromium}=require('@playwright/test');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const directory=path.resolve(process.env.PANEL_DESIGN_DIR||'local/design-v3');
  const snapshot=JSON.parse(fs.readFileSync(path.join(directory,'snapshot.json'),'utf8'));
  snapshot.busy=[];
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const report={screens:[],errors:[],mutations:[]};
  try{
    const page=await browser.newPage();
    page.on('pageerror',e=>report.errors.push(e.message));
    await page.route('**/api/**',async route=>{
      if(route.request().method()!=='GET'){report.mutations.push(route.request().url());return route.abort();}
      if(route.request().url().endsWith('/api/state'))return route.fulfill({json:snapshot});
      return route.abort();
    });
    for(const [name,width,height] of [['window',610,950],['desktop',1280,900],['mobile',390,844]]){
      await page.setViewportSize({width,height});await page.goto('http://127.0.0.1:47831');
      await page.locator('.model-row').first().waitFor();
      const metrics=await page.evaluate(()=>{
        const list=document.querySelector('.list-scroll').getBoundingClientRect();
        const rows=[...document.querySelectorAll('.model-row')].map(n=>n.getBoundingClientRect());
        const title=document.querySelector('.model-title'),meta=document.querySelector('.model-meta'),status=document.querySelector('.model-row .status');
        return {firstRowTop:rows[0].top,completeRows:rows.filter(r=>r.top>=list.top&&r.bottom<=list.bottom).length,
          overflow:document.documentElement.scrollWidth>innerWidth,fontTitle:getComputedStyle(title).fontSize,
          fontSecondary:getComputedStyle(meta).fontSize,fontStatus:getComputedStyle(status).fontSize,
          pageColor:getComputedStyle(document.body).backgroundColor,textColor:getComputedStyle(title).color,
          secondaryColor:getComputedStyle(meta).color,filtersHidden:document.querySelector('#filter-panel').hidden};
      });
      report.screens.push({name,width,height,...metrics});
      await page.screenshot({path:path.join(directory,name+'.png')});
      if(name==='window'){
        await page.getByRole('button',{name:'Фильтры',exact:true}).click();
        await page.screenshot({path:path.join(directory,'filters.png')});
        await page.getByLabel('Китайские',{exact:true}).check();
        await page.getByRole('button',{name:'Фильтры · 1',exact:true}).click();
        await page.screenshot({path:path.join(directory,'chinese.png')});
        await page.locator('.model-title').first().click();
        await page.screenshot({path:path.join(directory,'details.png')});
        await page.keyboard.press('Escape');
        await page.getByRole('button',{name:'Подключения',exact:true}).click();
        await page.screenshot({path:path.join(directory,'connections.png')});
        const keyButton=page.locator('[data-provider="gemini"]').getByRole('button',{name:'Изменить ключ'});
        if(await keyButton.count()){await keyButton.click();await page.screenshot({path:path.join(directory,'key-dialog.png')});await page.keyboard.press('Escape');}
        await page.getByRole('button',{name:'Лимиты CodexBar',exact:true}).click();
        await page.screenshot({path:path.join(directory,'codexbar.png')});
      }
    }
    fs.writeFileSync(path.join(directory,'report.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
    if(report.errors.length||report.mutations.length||report.screens.some(s=>s.overflow)||report.screens[0].firstRowTop>280||report.screens[0].completeRows<5)process.exitCode=1;
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
