const { test, expect } = require('./owner-fixture.cjs');

// Presentation-only synthetic API fixtures; real ingestion/connector coverage is
// in test_observation_import.py. No installed runtime is exercised here.
function observation(){
 const unknown={value:null,source:null,observedAt:null},at='2026-01-01T10:00:00Z';
 return {bundle:{schemaVersion:1,kind:'observation-bundle',observationId:'synthetic-ui-observation',sequence:1,
  task:{profile:'production',sourceKey:'0123456789abcdef',sourceId:'synthetic-task',taskKey:'cicada-0123456789abcdef-synthetic-task'},
  exporter:{id:'synthetic-exporter',source:'synthetic-stream'},observedAt:at,exportedAt:at,
  coverage:{kind:'attempt',attemptId:'synthetic-ui-attempt',startedAt:null,endedAt:null,source:'synthetic-event'},
  fields:{status:unknown,sessionId:{value:'synthetic-session',source:'synthetic-event',observedAt:at},parentSessionId:unknown,
   model:{value:'<img src=x onerror=alert(1)>',source:'synthetic-event',observedAt:at},inputTokens:unknown,outputTokens:unknown,startedAt:unknown,endedAt:unknown,durationMs:unknown},skillApplications:null},
  bundleHash:'a'.repeat(64),task:{sourceId:'synthetic-task',title:'Synthetic imported task',completed:false},origin:'imported',readOnly:true,independentlyVerified:false};
}

test('bundle review requires explicit approval and imported metadata stays separate',async({page})=>{
 let imports=0;const row=observation();
 await page.route('**/api/observations/preview',route=>route.fulfill({json:{...row,previewToken:'synthetic-preview',revision:'none',changed:true}}));
 await page.route('**/api/observations/import',route=>{imports++;return route.fulfill({json:{changed:true,origin:'imported',readOnly:true}});});
 await page.route('**/api/dashboard',async route=>{const body=await(await route.fetch()).json();body.importedObservations={rows:imports?[{...row,importedAt:'2026-01-02T10:00:00Z',receipts:[{sequence:1}]}]:[],unavailableCount:0};await route.fulfill({json:body});});
 await page.goto('/#dashboard');await page.locator('#observation-file').setInputFiles({name:'synthetic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(row.bundle))});
 await expect(page.locator('#observation-review')).toBeVisible();expect(imports).toBe(0);
 await expect(page.locator('#observation-review-body')).toContainText('Unknown');
 await page.locator('#approve-observation-import').click();await expect(page.locator('#observation-review')).toBeHidden();expect(imports).toBe(1);
 await expect(page.locator('#imported-observation-rows .imported-observation')).toHaveCount(0);
 await page.locator('#dashboard-history-tab').click();
 const card=page.locator('#imported-observation-rows .imported-observation');await expect(card).toHaveCount(1);
 await expect(card).toContainText('Imported · read-only');await expect(card).toContainText('synthetic-session');
 await expect(card).toContainText('Supplied provenance is not independent execution verification.');
 await expect(card.locator('img')).toHaveCount(0);await expect(card).toContainText('<img src=x onerror=alert(1)>');
 await expect(card.locator('button')).toHaveCount(0);
});

test('cancel review never imports and oversize file is rejected before request',async({page})=>{
 let previews=0,imports=0;const row=observation();
 await page.route('**/api/observations/preview',route=>{previews++;return route.fulfill({json:{...row,previewToken:'synthetic-preview',revision:'none',changed:true}});});
 await page.route('**/api/observations/import',route=>{imports++;return route.fulfill({json:{changed:true}});});
 await page.goto('/#dashboard');await page.locator('#observation-file').setInputFiles({name:'synthetic.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(row.bundle))});
 await expect(page.locator('#observation-review')).toBeVisible();await page.locator('#cancel-observation-import').click();expect(imports).toBe(0);
 await page.locator('#observation-file').setInputFiles({name:'large.json',mimeType:'application/json',buffer:Buffer.alloc(32769,32)});
 await expect(page.locator('#observation-import-status')).toContainText('32 KiB');expect(previews).toBe(1);expect(imports).toBe(0);
});
