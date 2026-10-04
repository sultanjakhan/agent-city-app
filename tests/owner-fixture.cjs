const base=require('@playwright/test');
let session;
const test=base.test.extend({ownerSession:[async({context,baseURL,page},use,testInfo)=>{
 const owner=new URL(baseURL),physical='http://127.0.0.1:'+owner.port;
 if(!session){session=(async()=>{const response=await context.request.post(physical+'/api/owner-bootstrap',{headers:{'X-Agent-City':'1','Origin':baseURL,'Host':owner.host},data:{capability:require('node:crypto').createHmac('sha256',process.env.AGENT_CITY_UI_BOOTSTRAP).update(String(testInfo.workerIndex)).digest('base64url')}});if(response.status()!==200)throw Error('Synthetic owner bootstrap failed');return (await context.cookies()).filter(cookie=>cookie.name.startsWith('agent_city_owner_')).map(cookie=>({...cookie,domain:owner.hostname}));})();}
 const cookies=await session;await context.clearCookies({domain:'127.0.0.1'});await context.addCookies(cookies);
 // Reserved .localhost resolves in Chromium. Native APIRequestContext uses the
 // OS resolver, so connect to loopback while preserving the logical Host/Origin.
 for(const method of ['get','post','put','delete','patch','head']){const original=context.request[method].bind(context.request);context.request[method]=(url,options={})=>{const logical=new URL(url,baseURL);if(logical.origin!==baseURL)return original(url,options);return original(physical+logical.pathname+logical.search,{...options,headers:{Host:owner.host,Origin:baseURL,Cookie:cookies.map(cookie=>cookie.name+'='+cookie.value).join('; '),...options.headers}});};}
 function wrap(handler){if(typeof handler!=='function')return handler;return async(route,request)=>{const original=route.fetch.bind(route);route.fetch=(options={})=>{const logical=new URL(route.request().url());if(logical.origin!==baseURL)return original(options);return original({...options,url:physical+logical.pathname+logical.search,headers:{...route.request().headers(),...options.headers,Host:owner.host,Cookie:cookies.map(cookie=>cookie.name+'='+cookie.value).join('; ')}});};return handler(route,request);};}
 const pageRoute=page.route.bind(page);page.route=(url,handler,options)=>pageRoute(url,wrap(handler),options);
 await use();
},{auto:true}]});
module.exports={...base,test};
