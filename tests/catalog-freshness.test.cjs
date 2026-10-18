const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const now=Date.parse('2026-10-02T12:00:00Z');
class Clock extends Date {static now(){return now;}}
// Isolate the real pure projection/text functions, without simulating browser acceptance.
function harness(){
 const scope={Date:Clock,Number,Object,Map,state:{catalogs:{},favorites:[],checks:{},connectionStatus:{}},sourceFor:()=>({}),replied:()=>false};
 vm.createContext(scope);
 for(const name of ['catalogStaleness','catalogPriceNote','models']){
  const start=source.indexOf('function '+name+'(');assert.notEqual(start,-1);
  const rest=source.slice(start),end=rest.search(/\n(?:async )?function /);
  vm.runInContext(end<0?rest:rest.slice(0,end),scope);
 }
 return scope;
}

test('catalogue age is unknown in the future, fresh through exactly one hour, then stale',()=>{
 const scope=harness();
 for(const [at,expected] of [
  ['2026-10-02T12:00:01Z',null],['2026-10-02T12:00:00Z',false],
  ['2026-10-02T11:00:00Z',false],['2026-10-02T10:59:59Z',true],
  ['2026-10-02T17:00:01+05:00',null],['2026-10-02T17:00:00+05:00',false],
  ['2026-10-02T16:00:00+05:00',false],['2026-10-02T15:59:59+05:00',true],
  ['invalid',null],[undefined,null]
 ])assert.equal(scope.catalogStaleness({updatedAt:at}),expected,String(at));
});

test('backend unknown survives rendering even when another saved date appears recent',()=>{
 const scope=harness();
 assert.equal(scope.catalogStaleness({updatedAt:'2026-10-02T12:00:00Z'},{stale:null}),null);
 assert.equal(scope.catalogStaleness({updatedAt:'2026-10-02T11:00:00Z'},{stale:false}),false);
 assert.equal(scope.catalogStaleness({error:'saved failure',updatedAt:'invalid'},{stale:null}),true);
 assert.equal(scope.catalogStaleness({updatedAt:'2026-10-02T12:00:00Z'},{stale:true}),true);
});

test('actual model projection retains unknown and never calls a future catalogue confirmed',()=>{
 const scope=harness(),catalog={models:[{id:'synthetic',name:'Synthetic',priceVerified:true}],
  observedAt:'2026-10-02T12:00:01Z',updatedAt:'2026-10-02T12:00:00Z'};
 scope.state.catalogs.lab=catalog;scope.state.connectionStatus.lab={catalog:{stale:null}};
 const before=JSON.stringify(scope.state),route=scope.models()[0].routes[0];
 assert.equal(route.stale,null);
 assert.equal(scope.catalogPriceNote(route),'Нулевой тариф сохранён. Перед запросом проверяется снова.');
 assert.doesNotMatch(scope.catalogPriceNote(route),/подтверждён каталогом/);
 assert.equal(JSON.stringify(scope.state),before);
 catalog.observedAt='2026-10-02T12:00:00Z';scope.state.connectionStatus.lab.catalog.stale=false;
 assert.equal(scope.models()[0].routes[0].stale,false);
 assert.equal(scope.catalogPriceNote(scope.models()[0].routes[0]),'Нулевой тариф подтверждён каталогом');
});

test('saved and unknown freshness do not override the existing unverified-price message',()=>{
 const scope=harness();
 for(const stale of [null,undefined,true,false])assert.equal(
  scope.catalogPriceNote({model:{priceVerified:false},stale}),
  'Бесплатность не подтверждена. Запрос к модели заблокирован');
 for(const stale of [null,undefined,true])assert.equal(
  scope.catalogPriceNote({model:{priceVerified:true},stale}),
  'Нулевой тариф сохранён. Перед запросом проверяется снова.');
});
