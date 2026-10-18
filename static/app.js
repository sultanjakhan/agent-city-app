'use strict';
const UI_VERSION='0.5.26';
const t=I18n.t;
I18n.init();
const $ = id => document.getElementById(id);
const sourceFor = id => state?.sources?.find(source=>source.id===id);
const providerName = id => sourceFor(id)?.name || id;
const needsKey = source => source.keyRequired ?? Boolean(source.keyUrl);
let state, view='dashboard', filter='all', selected, keyProvider, keyAction, timer, toastTimer;
let providerStateEpoch=0;
const navStorageKey='agentcity-nav-collapsed';
function syncNavOverlay(){
  const open=matchMedia('(max-width: 520px)').matches&&!document.body.classList.contains('nav-collapsed');
  document.querySelector('main').inert=open;
  if($('nav-backdrop'))$('nav-backdrop').hidden=!open;
}
function setNavCollapsed(collapsed){
  document.body.classList.toggle('nav-collapsed',collapsed);
  syncNavOverlay();
  const toggle=$('toggle-nav');
  if(!toggle)return;
  hideNavTooltip();for(const button of document.querySelectorAll('aside [data-view]')){if(collapsed)button.removeAttribute('title');else button.title=button.getAttribute('aria-label');}
  const label=t(collapsed?'Развернуть меню':'Свернуть меню');
  toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',label);toggle.title=label;
  const text=toggle.querySelector('span');if(text)text.textContent=collapsed?'Развернуть':'Свернуть';
}
let navTooltip=null,navTooltipOwner=null;
function hideNavTooltip(){if(navTooltip)navTooltip.hidden=true;navTooltipOwner?.removeAttribute('aria-describedby');navTooltipOwner=null;}
function showNavTooltip(button){
 if(!document.body.classList.contains('nav-collapsed'))return;navTooltipOwner=button;navTooltip.textContent=button.getAttribute('aria-label');navTooltip.hidden=false;button.setAttribute('aria-describedby','nav-tooltip');
 const r=button.getBoundingClientRect(),tip=navTooltip.getBoundingClientRect(),aside=document.querySelector('aside').getBoundingClientRect();navTooltip.style.left=Math.min(aside.right+10,innerWidth-tip.width-8)+'px';navTooltip.style.top=Math.max(8,Math.min(r.top+(r.height-tip.height)/2,innerHeight-tip.height-8))+'px';
}
function initNav(){
  navTooltip=el('div','nav-tooltip');navTooltip.id='nav-tooltip';navTooltip.setAttribute('role','tooltip');navTooltip.hidden=true;document.body.append(navTooltip);
  for(const button of document.querySelectorAll('aside [data-view]')){button.addEventListener('mouseenter',()=>showNavTooltip(button));button.addEventListener('mouseleave',hideNavTooltip);button.addEventListener('focus',()=>showNavTooltip(button));button.addEventListener('blur',hideNavTooltip);button.addEventListener('click',hideNavTooltip);}
  window.addEventListener('resize',hideNavTooltip);document.querySelector('aside nav').addEventListener('scroll',hideNavTooltip);
  const compact={architecture:'Схема',dashboard:'Главная',models:'Модели',connections:'API',skills:'Навыки',extensions:'Дополн.',repos:'Проекты',rules:'Правила',codexbar:'Лимиты',settings:'Опции'};
  for(const button of document.querySelectorAll('[data-view]')){const label=el('small','compact-label',compact[button.dataset.view]);button.append(label);}

  const backdrop=el('button','nav-backdrop');backdrop.id='nav-backdrop';backdrop.setAttribute('aria-label',t('Закрыть меню'));backdrop.hidden=true;backdrop.addEventListener('click',()=>setNavCollapsed(true));document.querySelector('main').before(backdrop);
  let collapsed=matchMedia('(max-width: 680px)').matches;
  try{const saved=localStorage.getItem(navStorageKey)??sessionStorage.getItem(navStorageKey);if(saved!==null)collapsed=saved==='1';}catch{}
  setNavCollapsed(collapsed);
  matchMedia('(max-width: 520px)').addEventListener('change',syncNavOverlay);
}
const titles = {architecture:['Архитектура','Технические пайплайны'],dashboard:['Дашборд',''],models:['Модели','Проверяй доступ и выбирай, чем пользоваться.'], connections:['Подключения','API и инструменты, которые дают доступ к моделям.'], codexbar:['Лимиты','Данные подписок из CodexBar.'],settings:['Настройки',''],skills:['Навыки',''],extensions:['Расширения',''],repos:['Проекты',''],rules:['Правила','']};
if(Object.hasOwn(titles,location.hash.slice(1)))view=location.hash.slice(1);
function el(tag,cls,text,raw=false){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=raw?text:t(text);return n;}
function age(v){const n=Date.parse(v);return Number.isFinite(n)?Math.max(0,(Date.now()-n)/1000):Infinity;}
function when(v){return Number.isFinite(Date.parse(v))?new Date(v).toLocaleString(I18n.locale,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):t('ещё не проверяли');}
function toast(text){$('toast').textContent=t(text);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3500);}
async function request(path,body){if(window.agentCityOwnerReady&&!(await window.agentCityOwnerReady))throw Error('Откройте Agent City через launcher.');const epoch=providerStateEpoch;const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Agent-City':'1','X-Agent-City-Token':state?.csrfToken||''},body:JSON.stringify(body)}:{});const data=await r.json();if(!r.ok){if(r.status===401&&window.agentCityOwnerDenied)window.agentCityOwnerDenied();const error=Error(data.error||'Не удалось выполнить запрос');error.status=r.status;throw error;}if(data.providerRegistry&&epoch!==providerStateEpoch)return state;return data;}
function replied(check){return ['ok','mismatch'].includes(check?.status)&&!!check?.reply&&check?.finishReason==='stop';}
function status(route){
  const c=route.check;
  if(sourceFor(route.provider)?.accessMode==='subscription')return {label:'Подписка · доступ не проверен',note:'',tone:'neutral'};
  if(replied(c))return {label:age(c.attemptedAt)>86400?'Отвечала ранее':'Ответ получен',note:when(c.attemptedAt),tone:'good'};
  const labels={key_changed:'Ключ изменён',missing_key:'Нужен ключ',credential_error:'Ключ недоступен',auth_error:'Ключ не принят',payment_required:'Требуется оплата',forbidden:'Доступ отклонён',rate_limited:'Лимит запросов',empty:'Нет итогового текста',incomplete:'Ответ обрезан',mismatch:'Ответ не совпал',http_error:'Ошибка API',timeout:'Нет ответа вовремя',network_error:'Нет связи',invalid_response:'Ошибка формата',price_unverified:'Тариф не подтверждён',catalog_error:'Тариф не проверен'};
  if(c&&c.status!=='skipped')return {label:labels[c.status]||'Не проверена',note:c.httpStatus?`HTTP ${c.httpStatus}`:'',tone:['missing_key','price_unverified','catalog_error'].includes(c.status)?'neutral':'warn'};
  if(!state.credentials?.[route.provider])return {label:'Нужен ключ',note:'Запрос не отправлялся',tone:'neutral'};
  if(route.model.priceVerified===false)return {label:'Тариф не подтверждён',note:'Ответ не проверялся',tone:'neutral'};
  if(c?.status==='skipped')return {label:'Не проверена',note:c.detail?.includes('лимит')?'Проверка остановлена по лимиту':'Запрос не отправлялся',tone:'neutral'};
  return {label:'Не проверена',note:'Запрос не отправлялся',tone:'neutral'};
}
function models(){
  const merged=new Map();
  for(const [provider,catalog] of Object.entries(state.catalogs||{}))for(const m of catalog.docsOnly?[]:(sourceFor(provider)?.catalogPolicy==='all'?(catalog.allModels||catalog.models||[]):catalog.models||[])){
    if(sourceFor(provider)?.catalogPolicy!=='all'&&m.priceVerified!==true)continue;
    if(!merged.has(m.id))merged.set(m.id,{...m,routes:[]});
    merged.get(m.id).routes.push({provider,model:m,check:state.checks?.[provider+'|'+m.id],stale:!!catalog.error||age(catalog.updatedAt)>3600,updatedAt:catalog.updatedAt});
  }
  for(const id of state.favorites||[])if(!merged.has(id))merged.set(id,{id,name:id,developer:'unknown',routes:[],removed:true});
  return [...merged.values()].sort((a,b)=>Number(b.routes.some(r=>replied(r.check)))-Number(a.routes.some(r=>replied(r.check)))||Number(b.routes.some(r=>r.model.priceVerified===true))-Number(a.routes.some(r=>r.model.priceVerified===true))||a.name.localeCompare(b.name));
}
function clientCompatibility(m){return m.kind==='structured'?'api':m.routes.some(r=>sourceFor(r.provider)?.clientIds?.length)?'client':'unknown';}
function quotaRows(){return (state.codexbar?.providers||[]).map(r=>({...r,windows:(r.windows||[]).filter(w=>!['session','primary'].includes(w.kind)&&!/^сессия$|^session$/i.test(w.label||'')&&(Number.isFinite(w.remainingPercent)||w.resetAt))})).filter(r=>r.windows.length);}
function setView(v){if(!Object.hasOwn(titles,v))return;if(v==='repos'&&view!=='repos')repoRows=null;view=v;history.replaceState(null,'','#'+v);if(matchMedia('(max-width: 520px)').matches)setNavCollapsed(true);render();}
window.addEventListener('hashchange',()=>setView(location.hash.slice(1)||'dashboard'));
function render(){
  if(!state)return;
  const localOnly=!!state.settings?.localOnly;
  $("local-mode-notice").hidden=!localOnly;
  $("local-mode-notice").textContent=I18n.language==="en"?"Local-only: cloud, keys and network checks are temporarily disabled.":"Только локально: облако, ключи и сетевые проверки временно отключены.";
  showUpdate(state.settings?.version);
  $('limits-nav').hidden=!quotaRows().length;
  $('app-version').textContent='v'+(state.settings?.version||UI_VERSION);$('app-version').title=t('Версия приложения')+' '+(state.settings?.version||UI_VERSION);
  for(const b of document.querySelectorAll('[data-view]')){const labels={architecture:'Схема',dashboard:'Главная',models:'Модели',connections:'API',skills:'Навыки',extensions:'Дополн.',repos:'Проекты',rules:'Правила',codexbar:'Лимиты',settings:'Опции'};b.querySelector('.compact-label').textContent=t(labels[b.dataset.view]);}
  if(view==='codexbar'&&$('limits-nav').hidden)view='connections';
  const providerFilter=$('provider-filter'),previousProvider=providerFilter.value;
  providerFilter.replaceChildren(new Option(t('Любой API'),'all'),...(state.sources||[]).map(s=>new Option(s.name,s.id)));
  providerFilter.value=[...providerFilter.options].some(o=>o.value===previousProvider)?previousProvider:'all';
  document.querySelector('.page-header').classList.toggle('connection-header',view==='connections');document.querySelector('.connection-checks').hidden=view!=='connections';
  if(document.body.classList.contains('nav-collapsed'))for(const button of document.querySelectorAll('aside [data-view]'))button.removeAttribute('title');
  $('page-title').textContent=t(titles[view][0]);$('page-description').textContent=view==='architecture'?'Технические пайплайны Agent City':t(titles[view][1]);
  for(const button of document.querySelectorAll('[data-view]')){button.classList.toggle('active',button.dataset.view===view);button.setAttribute('aria-current',button.dataset.view===view?'page':'false');}
  $('architecture-view').hidden=view!=='architecture';
  $('dashboard-view').hidden=view!=='dashboard';$('catalog-view').hidden=view!=='models';$('connections-view').hidden=view!=='connections';$('codexbar-view').hidden=view!=='codexbar';
  $('settings-view').hidden=view!=='settings';$('skills-view').hidden=view!=='skills';$('extensions-view').hidden=view!=='extensions';$('repos-view').hidden=view!=='repos';$('rules-view').hidden=view!=='rules';$('refresh').hidden=['settings','skills','rules','architecture'].includes(view);
  const busy=view!=='dashboard'&&(state.busy||[]).some(x=>view==='codexbar'?x==='codexbar':x!=='codexbar'&&x!=='check');
  const refreshLabel=t(busy?'Обновление…':view==='dashboard'?'Обновить задачи':view==='codexbar'?'Обновить лимиты':['extensions','repos'].includes(view)?'Обновить библиотеку':'Обновить каталоги');
  $('refresh').disabled=busy||(localOnly&&['models','connections','codexbar'].includes(view));$('refresh-label').textContent=t(refreshLabel);$('refresh').setAttribute('aria-label',refreshLabel);$('refresh').title=refreshLabel;
  const failed=Object.entries(state.catalogs||{}).filter(([,c])=>c.error).map(([p])=>providerName(p));
  $('notice').hidden=view!=='connections'||!failed.length;$('notice').textContent=t('Не удалось обновить: {providers}. Подробности — в карточках провайдеров.',{providers:failed.join(', ')});
  if(view==='architecture')renderPipelineEditor();else if(view==='dashboard')renderDashboard();else if(view==='models')renderModels();else if(view==='connections')renderConnections();else if(view==='codexbar')renderBar();else if(view==='settings')renderSettings();else if(view==='skills')renderSkills();else if(view==='extensions')renderProjects();else if(view==='repos')renderRepos();else if(view==='rules')renderRules();
  if(typeof maybeDataOnboarding==='function')maybeDataOnboarding();
  if(selected&&$('model-dialog').open)renderDialog();
  clearTimeout(timer);if(state.busy?.length)timer=setTimeout(load,900);
}
function renderModels(){
  renderAvailability();
  const all=models(),q=$('search').value.trim().toLowerCase(),provider=$('provider-filter').value,china=$('china-filter').checked,vs=$('vscode-filter').value;
  const active=all.filter(m=>!m.removed),answered=active.filter(m=>m.routes.some(r=>replied(r.check)));
  $('all-count').textContent=t(active.length);$('reply-count').textContent=t(answered.length);$('favorite-count').textContent=t(state.favorites.length);
  document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('active',b.dataset.filter===filter);b.setAttribute('aria-pressed',String(b.dataset.filter===filter));});
  const rows=all.filter(m=>(filter==='favorites'?state.favorites.includes(m.id):!m.removed)&&(filter!=='replied'||m.routes.some(r=>replied(r.check)))&&(!q||`${m.name} ${m.id} ${m.developer}`.toLowerCase().includes(q))&&(!china||m.chinese)&&(provider==='all'||m.routes.some(r=>r.provider===provider))&&(vs==='all'||vs===clientCompatibility(m)));
  $('catalog-summary').textContent=t(t('Показано {shown} из {total}',{shown:rows.length,total:active.length}));
  const activeFilters=Number(provider!=='all')+Number(china)+Number(vs!=='all');
  $('filter-label').textContent=t(activeFilters?`${t('Фильтры')} · ${activeFilters}`:'Фильтры');$('toggle-filters').classList.toggle('has-filters',activeFilters>0);
  const list=$('model-list');const focused=document.activeElement?.dataset.star;list.replaceChildren();
  for(const m of rows){
    const row=el('li','model-row'),heading=el('div','model-heading'),title=el('button','model-title',m.name.replace(/\s*\(free\)$/i,'').replace(/^[^:]+:\s+/,''),true);title.title=m.name;title.addEventListener('click',()=>openDialog(m.id));
    const routes=provider==='all'?m.routes:m.routes.filter(r=>r.provider===provider);
    const best=routes.find(r=>replied(r.check))||routes.find(r=>r.check?.sent)||routes[0],s=best?status(best):{label:'Нет в каталоге',tone:'neutral'};
    const facts=el('div','model-facts'),badge=el('span',`status ${s.tone}`,s.label);badge.title=[s.note,best?.check?.detail].filter(Boolean).map(x=>t(x)).join(' · ');facts.append(badge);if(best?.model.priceVerified!==true)facts.append(el('span','status neutral',best?.model.priceStatus==='paid'?'Платная модель':'Цена неизвестна'));
    if(routes.length&&routes.every(r=>r.stale))facts.append(el('span','catalog-origin','Сохранённый каталог'));
    const saved=state.favorites.includes(m.id),star=el('button','star',saved?'★':'☆');star.dataset.star=m.id;star.setAttribute('aria-pressed',String(saved));star.setAttribute('aria-label',`${t(saved?'Убрать из избранного':'В избранное')}: ${m.name}`);star.addEventListener('click',()=>favorite(m.id,!saved));heading.append(title,star);
    row.append(heading,facts);list.append(row);
  }
  if(focused)[...list.querySelectorAll('[data-star]')].find(b=>b.dataset.star===focused)?.focus({preventScroll:true});
  $('empty').hidden=!!rows.length;
  $('empty-title').textContent=t(filter==='replied'?'Подтверждённых ответов пока нет':filter==='favorites'&&!state.favorites.length?'В избранном пока пусто':'Ничего не нашлось');
  $('empty-description').textContent=t(filter==='replied'?'Открой модель и запусти проверку доступного API.':filter==='favorites'?'Добавь нужные модели звёздочкой.':'Измени запрос или фильтры.');
}
function link(label,url){const a=el('a','',label);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
// clientIds proves declared support only. Installation never proves provider configuration/authentication.
function clientInventory(){
  const known=new Map([['cline',{id:'cline',name:'Cline'}],['kilo',{id:'kilo',name:'Kilo Code'}],['opencode',{id:'opencode',name:'OpenCode'}],['codex',{id:'codex',name:'Codex'}],['claude-code',{id:'claude-code',name:'Claude Code'}]]);
  for(const c of state.clients||[])known.set(c.id,c);
  for(const source of state.sources||[])for(const id of source.clientIds||[])if(!known.has(id))known.set(id,{id,name:id});
  return [...known.values()];
}
function providerClients(source){
  const clients=clientInventory().filter(c=>(source.clientIds||[]).includes(c.id)).map(c=>({...c,kind:'support'}));
  const snapshot=(state.codexbar?.providers||[]).find(c=>c.id===source.id);
  if(snapshot)clients.push({id:'codexbar',name:'CodexBar',kind:'snapshot',snapshot});
  return clients;
}
function clientTags(source){
  const tags=el('div','provider-client-tags');
  for(const client of providerClients(source)){
    const tag=el('button');tag.type='button';tag.className='provider-client-tag';tag.dataset.client=client.id;
    tag.textContent=client.name;
    tag.title=client.kind==='support'?t('Объявленная поддержка клиента. ')+t('{extension} · {cli}. Настройка провайдера и авторизация в клиенте не проверены.',{extension:t(client.extensionInstalled===undefined?'Установка расширения неизвестна':client.extensionInstalled?'Расширение найдено':'Расширение не найдено'),cli:t(client.cliInstalled===undefined?'Установка CLI неизвестна':client.cliInstalled?'CLI найден':'CLI в PATH не найден')}):t('Совпадение ID в снимке CodexBar от {date}. {status} Авторизация API не подтверждена.',{date:when(client.snapshot.updatedAt),status:t(client.snapshot.error?'Ошибка источника.':'Данные подписки; не API-доступ.')});
    tag.setAttribute('aria-label',client.name+'. '+tag.title);tag.setAttribute('aria-expanded','false');
    tag.addEventListener('click',()=>{
      const open=tag.getAttribute('aria-expanded')!=='true';for(const button of tags.querySelectorAll('button[data-client]'))button.setAttribute('aria-expanded','false');
      tags.querySelector('.provider-client-description')?.remove();
      if(open){tag.setAttribute('aria-expanded','true');const description=el('p','provider-client-description',tag.title,true);description.setAttribute('role','status');if(client.docs)description.append(' ',link('Документация ↗',client.docs));tags.append(description);}
    });
    tags.append(tag);
  }
  if(!tags.childElementCount)tags.append(el('span','provider-client-unknown','Связь с клиентами не подтверждена'));
  return tags;
}
function catalogErrorText(error){
 const messages={authentication:'Источник каталога требует авторизацию · HTTP 401',forbidden:'Источник каталога отклонил запрос · HTTP 403',rate_limit:'Источник каталога ограничил запросы · HTTP 429',timeout:'Источник каталога не ответил вовремя.',format:'Формат каталога не удалось прочитать.',storage:'Каталог не удалось сохранить на устройстве.',network:'Не удалось подключиться к источнику каталога.',unknown:'Причина ошибки каталога не определена.'};
 return error?.category==='http'?t('Источник каталога вернул HTTP {code}.',{code:error.httpStatus}):t(messages[error?.category]||messages.unknown);
}
function catalogError(c,facts){
 if(!c.error)return null;
 if(facts?.refresh?.error)return facts.refresh.error;
 const match=String(c.error).match(/\bHTTP\s+(\d{3})\b/i),code=match?Number(match[1]):null;
 return {category:({401:'authentication',403:'forbidden',429:'rate_limit'})[code]||(code?'http':'unknown'),httpStatus:code};
}
function connectionDetails(source,c,facts){
 const box=el('section','connection-observation'),list=el('dl','connection-facts');
 const add=(label,text)=>list.append(el('dt','',label),el('dd','',text,true));
 const date=c.observedAt||c.updatedAt,published=c.catalogScope==='published'||String(c.sourceKind||'').startsWith('official_docs');
 add('Источник каталога',t(date?(published?'Опубликованная документация':'API провайдера'):'Не получен'));
 add('Дата снимка',date?when(date):t('Неизвестна'));
 add('Последняя попытка',c.attemptedAt?when(c.attemptedAt):t('Не выполнялась'));
 add('Обновление',t(state.settings?.localOnly?'Приостановлено · local-only':source.catalogSupported===false?'Не поддерживается':c.error?'Ошибка обновления':facts?.refresh?.lastResult==='succeeded'?'Последняя попытка успешна':'Результат не подтверждён'));
 add('Доступность провайдера',t('Не проверена'));
 add('Доступ аккаунта к моделям',t('Не проверен'));
 add('Текущая авторизация API',t(state.settings?.localOnly?'Приостановлена · local-only':'Не проверена'));
 const savedAuth=facts?.authentication?.lastObservation;
 if(savedAuth){const names={accepted:'Каталог аккаунта ранее получен',rejected:'Источник ранее отклонил авторизацию',forbidden:'Источник ранее отклонил запрос',rate_limited:'Источник ранее ограничил запросы'};add('Сохранённая проверка авторизации',t('{status} · {date}',{status:t(names[savedAuth.status]),date:when(savedAuth.observedAt)}));}
 const reply=facts?.inference?.lastCompletedReplyAt;
 add('Последний завершённый ответ',reply?when(reply):t('Не зафиксирован'));
 box.append(list,el('p','connection-evidence-note',c.error&&catalogError(c,facts)?.category==='forbidden'?'Снимок каталога и сохранённые проверки не подтверждают текущий доступ. HTTP 403 относится к запросу каталога; причина блокировки и доступность всего провайдера не установлены.':'Снимок каталога и сохранённые проверки не подтверждают текущий доступ.'));
 const url=facts?.catalog?.sourceUrl;if(url)box.append(link('Источник каталога ↗',url));
 return box;
}
let connectionKeyForms=new Map(),providerDetailNodes=new Map(),providerDetailsId=null,providerDetailsReturn=null;
function openProviderDetails(id){
 const node=providerDetailNodes.get(id);if(!node)return;
 providerDetailsId=id;providerDetailsReturn=document.activeElement;node.hidden=false;$('provider-details-title').textContent=providerName(id);$('provider-details-body').replaceChildren(node);$('provider-details-dialog').showModal();$('close-provider-details').focus();
}
$('close-provider-details').addEventListener('click',()=>$('provider-details-dialog').close());
$('provider-details-dialog').addEventListener('keydown',event=>{if(event.key!=='Tab')return;const nodes=[...event.currentTarget.querySelectorAll('button,a[href],input,select,textarea,[tabindex]')].filter(node=>!node.disabled&&node.tabIndex>=0&&node.getClientRects().length);const first=nodes[0],last=nodes.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}});
$('provider-details-dialog').addEventListener('close',()=>{
 const id=providerDetailsId,node=$('provider-details-body').firstElementChild,row=[...$('source-list').querySelectorAll('[data-provider]')].find(row=>row.dataset.provider===id);
 if(node){node.hidden=true;if(row)row.insertBefore(node,row.querySelector('.connection-actions'));}
 providerDetailsId=null;(providerDetailsReturn?.isConnected?providerDetailsReturn:row?.querySelector('.provider-heading'))?.focus();
});
function providerOptions(source){
 const box=el('section','provider-options'),accessLabel=el('label','','Способ доступа'),policyLabel=el('label','','Каталог');
 const access=el('select'),policy=el('select');access.dataset.providerSetting='accessMode';policy.dataset.providerSetting='catalogPolicy';
 access.append(new Option(t('API'),'api'),new Option(t('Подписка'),'subscription'));policy.append(new Option(t('Только подтверждённые бесплатные'),'confirmed-free-only'),new Option(t('Все модели'),'all'));
 access.value=(providerOptionSaving?.id===source.id?providerOptionSaving.settings.accessMode:source.accessMode)||'api';policy.value=(providerOptionSaving?.id===source.id?providerOptionSaving.settings.catalogPolicy:source.catalogPolicy)||'confirmed-free-only';access.disabled=policy.disabled=!!providerOptionSaving;accessLabel.append(access);policyLabel.append(policy);const receipt=el('p','provider-settings-receipt');receipt.setAttribute('role','status');
 const save=async()=>{if(providerOptionSaving)return;providerOptionSaving={id:source.id,settings:{accessMode:access.value,catalogPolicy:policy.value}};access.disabled=policy.disabled=true;receipt.textContent=t('Сохранение…');
  try{const snapshot=await providerRequest('/api/providers/settings',{id:source.id,settings:providerOptionSaving.settings,revision:state.providerRegistry.revision});adoptProviderState(snapshot);toast('Настройки сохранены');}
  catch(error){providerOptionSaving=null;if(error.status===409){try{adoptProviderState(await providerRequest('/api/state'));}catch{}}else renderConnections();const current=providerDetailNodes.get(source.id)?.querySelector('.provider-settings-receipt');if(current)current.textContent=t(error.message);toast(error.message);}
  finally{providerOptionSaving=null;for(const input of document.querySelectorAll('[data-provider-setting]'))input.disabled=false;access.disabled=policy.disabled=false;}};
 access.addEventListener('change',save);policy.addEventListener('change',save);const help=el('button','text-button','О настройках');help.type='button';help.addEventListener('click',()=>{$('provider-help-dialog').showModal();});box.append(accessLabel,policyLabel,help,receipt);return box;
}
let providerOptionSaving=null;
function renderConnections(){
  renderAvailability();
  $('add-provider').disabled=!state.providerRegistry;
  for(const form of document.querySelectorAll('#source-list .inline-key-form,#provider-details-body .inline-key-form'))connectionKeyForms.set(form.dataset.keyProvider,form);
  for(const id of connectionKeyForms.keys())if(!state.sources.some(source=>source.id===id))connectionKeyForms.delete(id);
  const forms=connectionKeyForms;
  const focused=document.activeElement;providerDetailNodes=new Map();
  $('source-list').replaceChildren();
  const select=$('connection-client'),previous=select.value;
  const clients=[...clientInventory(),{id:'codexbar',name:'CodexBar'}];
  select.replaceChildren(new Option(t('Все клиенты'),'all'),...clients.map(c=>new Option(c.name,c.id)),new Option(t('Связь с клиентами не подтверждена'),'unknown'));
  select.value=[...select.options].some(o=>o.value===previous)?previous:'all';
  const query=$('connection-search').value.trim().toLowerCase(),client=select.value;
  const sources=state.sources.filter(source=>(!query||`${source.name} ${source.id} ${source.website||''}`.toLowerCase().includes(query))&&(client==='all'||(client==='unknown'?!providerClients(source).length:providerClients(source).some(c=>c.id===client))));
  $('connection-summary').textContent=t('Показано {shown} из {total}',{shown:sources.length,total:state.sources.length});
  if(!sources.length)$('source-list').append(el('p','section-description',state.sources.length?'Нет провайдеров по выбранному клиенту и поиску.':'Провайдеров пока нет. Добавь сайт провайдера.'));
  for(const source of sources){
    const c=state.catalogs[source.id]||{},info=state.credentialInfo?.[source.id]||{available:state.credentials?.[source.id]},busy=state.busy?.includes(source.id);
    const checks=Object.values(state.checks||{}).filter(x=>x.provider===source.id&&x.status!=='skipped').sort((a,b)=>Date.parse(b.attemptedAt)-Date.parse(a.attemptedAt));
    const facts=state.connectionStatus?.[source.id],localOnly=!!state.settings?.localOnly;
    const label=localOnly?'Доступ не проверен · local-only':source.accessMode==='subscription'?'Подписка · доступ не проверен':source.docsOnly?'Доступ не проверен':info.unreadable?'Ключ недоступен · доступ не проверен':needsKey(source)&&info.available?'Ключ сохранён · доступ не проверен':needsKey(source)&&info.available===false?'Нужен ключ · доступ не проверен':'Доступ не проверен';
    const row=el('div','connection-row'),main=el('div','connection-main'),heading=el('button','provider-heading',source.name,true);row.dataset.provider=source.id;
    heading.type='button';heading.setAttribute('aria-haspopup','dialog');heading.dataset.providerToggle=source.id;heading.addEventListener('click',()=>openProviderDetails(source.id));main.hidden=true;providerDetailNodes.set(source.id,main);main.append(connectionDetails(source,c,facts),providerOptions(source));
    const runtime=state.providerRuntime?.[source.id];
    if(runtime){const message=source.id==='openai'&&runtime.status==='authenticated'&&runtime.auth==='chatgpt'?'Codex: сохранённая проверка входа через ChatGPT':source.id==='zen'?'Zen: API-ключ · pay-as-you-go':'Авторизация не проверена';
      main.append(el('p','provider-runtime-status',message),el('p','provider-runtime-source',t('Проверено: {date} · {source}',{date:when(runtime.checkedAt),source:runtime.source==='codex-login-status'?'codex login status':t('Локальный статус и официальная документация')})),el('p','provider-runtime-limits','Доступ к моделям и ответ не проверены.'));
      if(source.id==='zen')main.append(el('p','provider-runtime-zen',runtime.clientInPath===false?'OpenCode CLI не найден в PATH. Ключ API не проверен.':'Ключ API и баланс не проверены.'));
    }
    if(source.supported===false){
      main.append(link('Сайт провайдера ↗',source.website),el('p','','Сайт сохранён. API-адаптер не поддерживается; токен и модели не импортируются.'));
      const actions=el('div','connection-actions'),remove=el('button','text-button','Удалить провайдера');remove.addEventListener('click',()=>openRemoveProvider(source));actions.prepend(el('span','status neutral','Сайт сохранён'));actions.append(remove);row.append(heading,main,actions,clientTags(source));$('source-list').append(row);continue;
    }
    const summary=c.pricingSummary,entries=summary?[summary.confirmedFree,summary.knownPaid,summary.unknown].reduce((sum,n)=>sum+(Number.isFinite(n)?n:0),0):c.models?.length||0;
    main.append(el('p','',c.docsOnly?'Каталог API ещё не получен':t('Моделей: {count} · {catalog}',{count:entries,catalog:c.updatedAt?t('каталог от {date}',{date:when(c.updatedAt)}):t('каталог не получен')})));
    if(c.error){
      main.append(el('p','provider-receipt',t('Ошибка получения каталога: {error}',{error:catalogErrorText(catalogError(c,facts))}),true));
      const cache=c.updatedAt?(c.models?.length?t('Показан сохранённый каталог от {date}; обновление не удалось.',{date:when(c.updatedAt)}):'Обновление не удалось. Последний сохранённый каталог пуст.'):'Каталог не получен. Сохранённых моделей нет.';
      main.append(el('p','provider-cache-note',cache));
    }
    if(c.catalogScope==='published')main.append(el('p','catalog-provenance',t('Источник: документация · {date}',{date:when(c.observedAt)})),el('p','provider-source-note','Доступ аккаунта не проверен.'));
    if(c.sourceKind==='official_docs_snapshot')main.append(el('p','','Датированный снимок документации. Обновление из сети ПК может быть заблокировано; дата снимка не меняется при ошибке.'));
    if(c.attemptedAt)main.append(el('p','provider-attempt',t('Попытка обновления: {date}',{date:when(c.attemptedAt)}),true));
    if(!c.error&&!source.docsOnly){
      const free=(c.models||[]).filter(m=>m.priceVerified===true).length,summary=c.pricingSummary;
      const note=!c.updatedAt?'Каталог ещё не получен.':free?'В списке моделей показан подтверждённый нулевой тариф.':summary?.complete&&summary.knownPaid>0&&summary.confirmedFree===0?'Бесплатных моделей в полученном каталоге нет.':'Бесплатность моделей не подтверждена.';
      main.append(el('p','provider-catalog-state',note));
    }
    if(checks[0])main.append(el('p','provider-receipt',t('Ответ модели: {status} · {date}',{status:t(status({provider:source.id,model:{},check:checks[0]}).label).toLowerCase(),date:when(checks[0].attemptedAt)})));

    if(source.discoveryOnly)main.append(el('p','','Каталог доступных моделей. Бесплатная квота аккаунта пока не подтверждена.'));
    if(!source.docsOnly)main.append(el('p','',t('С нулевой ценой: {free}. С неизвестной ценой: {unknown}.',{free:(c.models||[]).filter(m=>m.priceVerified===true).length,unknown:summary?.unknown??(c.models||[]).filter(m=>m.priceVerified!==true).length})));
    if(summary?.knownPaid)main.append(el('p','',t('Записей с известным платным тарифом: {count}.',{count:summary.knownPaid})));
    const detail=el('section','provider-access');detail.append(el('h3','','Доступ'));
    detail.append(link('Документация ↗',source.docs));
    if(source.docsOnly){detail.append(el('h3','','API'),el('p','','API-адаптер не подключён. Ключ не проверен.'),link('API-документация ↗',source.docs),el('h3','','Подписка'),el('p','','Авторизация — в официальном клиенте. Доступ не проверен.'),link('Вход в официальном клиенте ↗',source.subscriptionDocs));}
    const unmatched=(state.codexbar?.providers||[]).filter(item=>!state.sources.some(source=>source.id===item.id));if(unmatched.length){detail.append(el('p','',t('CodexBar: {names}. Соответствие API-провайдеру не установлено.',{names:unmatched.map(item=>item.name).join(', ')})));const limits=el('button','text-button','Лимиты подписок');limits.addEventListener('click',()=>{$('provider-details-dialog').close();setView('codexbar');});detail.append(limits);}
    main.append(detail);
    const actions=el('div','connection-actions');actions.append(el('span','status neutral connection-access-status',label));
    const remove=el('button','text-button','Удалить провайдера');remove.disabled=!!busy||state.busy?.includes('check');remove.addEventListener('click',()=>openRemoveProvider(source));actions.append(remove);
    if(needsKey(source)&&source.accessMode!=='subscription'){const connect=el('button','secondary',info.available?'Изменить ключ':'Вставить ключ');connect.disabled=localOnly;connect.addEventListener('click',()=>openKey(source.id));main.append(connect);}
    {const update=el('button','text-button',busy?'Обновление…':'Обновить каталог');update.disabled=localOnly||source.catalogSupported===false||!!busy||(source.accountCatalog&&needsKey(source)&&!info.available);update.title=localOnly?t('Обновление приостановлено в local-only'):source.accountCatalog&&!info.available?t('Для каталога нужен API-ключ'):'';update.addEventListener('click',()=>refreshSource(source.id));actions.append(update);}
    if(needsKey(source)&&source.accessMode!=='subscription')main.append(inlineKeyForm(source,info,forms.get(source.id)));
    const catalogLine=el('p','connection-catalog-summary');
    const date=c.observedAt||c.updatedAt,published=c.catalogScope==='published'||String(c.sourceKind||'').startsWith('official_docs');
    catalogLine.textContent=date?t('{source} · снимок {date}',{source:t(published?'Документация':'API'),date:when(date)}):t('Каталог не получен');
    if(c.error)catalogLine.append(' · ',el('span','connection-refresh-error','Обновление не удалось'));
    row.append(heading,catalogLine,main,actions,clientTags(source));$('source-list').append(row);
  }
  if(providerDetailsId){const node=providerDetailNodes.get(providerDetailsId);if(node){node.hidden=false;$('provider-details-title').textContent=providerName(providerDetailsId);$('provider-details-body').replaceChildren(node);}else $('provider-details-dialog').close();}
  if(focused?.isConnected)focused.focus({preventScroll:true});

}
async function refreshSource(provider){if(state.settings?.localOnly){toast('Обновление приостановлено в local-only');return;}try{state=await request('/api/refresh',{target:provider});render();}catch(e){toast(e.message);}}
function openKey(provider){
  if(state.settings?.localOnly){toast('Работа с ключами приостановлена в local-only');return;}
  if(keyAction){toast('Дождись сохранения ключа');return;}
  keyProvider=provider;const source=state.sources.find(s=>s.id===provider),info=state.credentialInfo?.[provider]||{};
  $('key-title').textContent=source.name;$('api-key').value='';$('key-error').hidden=true;
  $('key-account').href=source.keyUrl;$('key-terms').textContent=t(source.terms||'Сохранение ключа не отправляет запросы к модели. После обновления каталога проверку можно запустить в её карточке.');
  $('key-current').textContent=t(info.source==='environment'?'Сейчас используется ключ из окружения. Сохранённый здесь ключ получит приоритет.':info.available?'Ключ уже найден на компьютере. Можно заменить его новым.':'Создай ключ в аккаунте провайдера и вставь в поле ниже.');
  $('save-key').disabled=info.canSave===false;$('api-key').disabled=info.canSave===false;
  $('remove-key').hidden=!info.removable;$('remove-key').disabled=false;$('remove-key').textContent=t('Удалить с компьютера');$('remove-key').dataset.confirm='';
  if(info.canSave===false)$('key-current').textContent=t('Ввод ключа здесь поддерживается в Windows. На этой системе используй переменную окружения провайдера.');
  $('key-dialog').showModal();$('api-key').focus();
}
async function changeKey(action){
  if(keyAction)return;
  const provider=keyProvider;
  if(!provider)return;
  keyAction=action;
  const button=action==='save'?$('save-key'):$('remove-key');button.disabled=true;$('key-error').hidden=true;
  try{const body={provider,action};if(action==='save')body.key=$('api-key').value.trim();
    state=await request('/api/credential',body);if(keyProvider===provider){$('api-key').value='';$('key-dialog').close();render();}
    toast(action==='save'?'Ключ сохранён. Обновляю каталог.':'Сохранённый ключ удалён');
    if(action==='save')await refreshSource(provider);
  }catch(e){if(keyProvider===provider){$('key-error').textContent=t(e.message);$('key-error').hidden=false;button.disabled=false;if(!$('key-dialog').open)toast(e.message);}}
  finally{keyAction=null;}
}
function renderBar(){
  const bar=state.codexbar||{},rows=quotaRows();
  $('bar-status').textContent=t(bar.error||`CodexBar ${bar.version||''} · ${t('Снимок от {date}',{date:when(bar.generatedAt)})}`);
  $('quota-grid').replaceChildren();$('bar-empty').hidden=!!rows.length;
  for(const r of rows){const fresh=!bar.error&&Number.isFinite(bar.staleAfterSeconds)&&age(bar.generatedAt)<=bar.staleAfterSeconds&&age(r.updatedAt)<=bar.staleAfterSeconds,card=el('article','quota-card'),head=el('header');head.append(el('h3','',r.name,true),el('span','',r.error?'Ошибка источника':fresh?'Обновлено':'Снимок'));card.append(head);
    if(r.error||bar.error)card.append(el('p','quota-error',r.error?'CodexBar не смог получить лимиты этого аккаунта.':'Обновление не удалось. Показан последний снимок.'));
    for(const w of r.windows||[]){const block=el('div','quota-window'),heading=el('div','window-heading');heading.append(el('span','',w.label),el('strong','',Number.isFinite(w.remainingPercent)?t('{percent}% осталось',{percent:Math.round(w.remainingPercent)}):'Нет данных'));block.append(heading);if(Number.isFinite(w.remainingPercent)){const progress=el('progress');progress.max=100;progress.value=w.remainingPercent;progress.setAttribute('aria-label',t(w.label));block.append(progress);}block.append(el('small','',w.resetAt?t('Сброс: {date}',{date:when(w.resetAt)}):'Время сброса не указано'));card.append(block);}
    card.append(el('div','quota-time',when(r.updatedAt)));$('quota-grid').append(card);
  }
}
function openDialog(id){selected=id;renderDialog();$('model-dialog').showModal();}
function renderDialog(){
  const m=models().find(x=>x.id===selected);if(!m)return;
  $('dialog-title').textContent=m.name;$('dialog-developer').textContent=m.developer+(m.chinese?' · '+t('Китай'):'');$('dialog-id').textContent=m.id;
  $('dialog-routes').replaceChildren();$('dialog-evidence').replaceChildren();
  for(const r of m.routes){const row=el('div','dialog-route'),main=el('div');const s=status(r);main.append(el('strong','',providerName(r.provider),true),el('p','',`${t(s.label)}${r.check?.detail?' · '+t(r.check.detail):''}`),el('p','',r.model.priceVerified!==true?'Бесплатность не подтверждена. Запрос к модели заблокирован' :r.stale?'Нулевой тариф сохранён. Перед запросом проверяется снова.':'Нулевой тариф подтверждён каталогом'));
    const hasKey=state.credentials?.[r.provider],unpriced=r.model.priceVerified!==true||(r.model.kind||'chat')!=='chat'||sourceFor(r.provider)?.accessMode==='subscription',button=el('button','secondary',!hasKey?'Подключить':m.kind==='structured'||unpriced?'Условия доступа':'Проверить');
    button.disabled=!!state.busy?.includes('check');button.addEventListener('click',async()=>{if(!hasKey||m.kind==='structured'||unpriced){$('model-dialog').close();setView('connections');openProviderDetails(r.provider);return;}button.disabled=true;try{state=await request('/api/check',{provider:r.provider,model:m.id});render();}catch(e){toast(e.message);button.disabled=false;}});row.append(main,button);$('dialog-routes').append(row);
    $('dialog-evidence').append(el('p','',t('{provider} · контекст: {context} · инструменты: {tools}',{provider:providerName(r.provider),context:r.model.context?Math.round(r.model.context/1000)+'K':t('неизвестен'),tools:t(r.model.tools===true?'заявлены':r.model.tools===false?'не заявлены':'неизвестно')})));
    const source=sourceFor(r.provider);if(source?.catalogUrl)main.append(link('Источник данных ↗',source.catalogUrl),el('p','',t('Каталог получен: {date}',{date:when(r.updatedAt)})));
    if(r.model.upstreams?.length){$('dialog-evidence').append(el('h3','','Провайдеры Hugging Face'));for(const upstream of r.model.upstreams)$('dialog-evidence').append(el('p','',t('{provider} · контекст: {context} · инструменты: {tools}',{provider:upstream.name,context:upstream.context||t('неизвестен'),tools:t(upstream.tools===true?'заявлены':upstream.tools===false?'не заявлены':'неизвестно')})));}
    if(r.check){$('dialog-evidence').append(el('p','',t('{date} · {sent} · {ms} мс',{date:when(r.check.attemptedAt),sent:t(r.check.sent?'Запрос отправлен':'Запрос не отправлен'),ms:r.check.durationMs??0})),el('pre','',r.check.reply||t(r.check.detail),true));if(r.check.status==='mismatch')$('dialog-evidence').append(el('p','','Ответ завершён, но точный контрольный формат не соблюдён. Это подтверждает текстовый доступ, а не качество модели.'));}
  }
  $('dialog-vscode').textContent=t(m.kind==='structured'?'Jev возвращает структурированные решения. Его можно вызвать из кода проекта; как текстовый агент Cline/Kilo/OpenCode он здесь не подключается.':m.routes.some(r=>r.provider==='openrouter')?t('Cline → Settings → API Provider: OpenRouter → Model: {id}. Также доступен выбор OpenRouter в Kilo Code и OpenCode. Нужен ключ этого API. Работа с инструментами ещё не проверена.',{id:m.id}):m.routes.some(r=>r.provider==='cline')?t('Cline → Settings → API Provider: Cline → Model: {id}. Для расширения войди в Cline; отдельный ключ панели не означает, что расширение уже настроено.',{id:m.id}):m.routes.some(r=>r.provider==='kilo')?t('Kilo Code → Settings → Kilo Gateway → {id}. Доступ расширения и анонимного API может различаться.',{id:m.id}):m.routes.some(r=>state.sources.find(s=>s.id===r.provider)?.discoveryOnly)?t('Выбери провайдера {providers} в настройках клиента или его официальный совместимый API. Доступность этой модели и вызов инструментов в VS Code ещё не проверены.',{providers:m.routes.map(r=>providerName(r.provider)).join(' / ')}):t('Установи OpenCode, открой терминал VS Code, выполни opencode и /connect → OpenCode Zen. Затем выбери {id} через /models. Доступ к API ещё нужно проверить.',{id:m.id}));
  $('dialog-favorite').textContent=t(state.favorites.includes(selected)?'Убрать из избранного':'Добавить в избранное');
}
async function favorite(id,enabled){try{state=await request('/api/favorite',{id,enabled});render();}catch(e){toast(e.message);}}
async function load(){const epoch=providerStateEpoch;try{state=await request('/api/state');render();}catch{if(epoch!==providerStateEpoch)return;$('notice').hidden=false;$('notice').textContent=t('Приложение не отвечает. Запусти Agent City заново.');clearTimeout(timer);timer=setTimeout(load,5000);}}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
initNav();
$('language').value=I18n.language;
$('language').addEventListener('change',()=>{I18n.setLanguage($('language').value);setNavCollapsed(document.body.classList.contains('nav-collapsed'));$('nav-backdrop').setAttribute('aria-label',t('Закрыть меню'));render();});
document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{filter=b.dataset.filter;renderModels();}));
$('search').addEventListener('input',()=>state&&renderModels());for(const id of ['china-filter','provider-filter','vscode-filter'])$(id).addEventListener('change',()=>state&&renderModels());
function clearFilters(){$('search').value='';$('china-filter').checked=false;$('provider-filter').value='all';$('vscode-filter').value='all';render();}
$('reset-filters').addEventListener('click',clearFilters);$('clear-filters').addEventListener('click',clearFilters);
$('toggle-filters').addEventListener('click',()=>{const open=$('filter-panel').hidden;$('filter-panel').hidden=!open;$('toggle-filters').setAttribute('aria-expanded',String(open));});
$('refresh').addEventListener('click',async()=>{if(view==='dashboard'){await loadDashboard(true);return;}if(view==='extensions'){projectsSnapshot=null;await renderProjects();return;}if(view==='repos'){repoRows=null;await renderRepos();return;}try{state=await request('/api/refresh',{target:view==='codexbar'?'codexbar':'catalog'});render();}catch(e){toast(e.message);}});
$('toggle-nav').addEventListener('click',()=>{const collapsed=!document.body.classList.contains('nav-collapsed');setNavCollapsed(collapsed);try{localStorage.setItem(navStorageKey,collapsed?'1':'0');}catch{}});
$('close-dialog').addEventListener('click',()=>$('model-dialog').close());$('dialog-favorite').addEventListener('click',()=>favorite(selected,!state.favorites.includes(selected)));
$('copy-id').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(selected);toast('ID скопирован');}catch{toast('Выдели и скопируй ID вручную');}});
$('connection-search').addEventListener('input',()=>state&&renderConnections());$('connection-client').addEventListener('change',()=>state&&renderConnections());
$('close-key').addEventListener('click',()=>$('key-dialog').close());
$('key-dialog').addEventListener('close',()=>{$('api-key').value='';});
$('key-form').addEventListener('submit',e=>{e.preventDefault();changeKey('save');});
$('remove-key').addEventListener('click',()=>{const b=$('remove-key');if(b.dataset.confirm!=='yes'){b.dataset.confirm='yes';b.textContent=t('Подтвердить удаление');return;}changeKey('remove');});
setInterval(()=>{if(state&&!state.busy?.length&&document.visibilityState==='visible')load();},60000);
load();

function showUpdate(version){
 const existing=$('app-update');
 if(!version||version===UI_VERSION){existing?.remove();return;}
 const older=/^\d+\.\d+\.\d+$/.test(version)&&version.localeCompare(UI_VERSION,undefined,{numeric:true})<0;
 const label=older?'Интерфейс обновлён. Перезапусти сервер Agent City, чтобы завершить обновление.':'Обновление готово — перезагрузить интерфейс';
 if(existing?.dataset.version===version){existing.textContent=t(label);return;}
 const banner=el(older?'p':'button','update-banner',label);
 banner.id='app-update';banner.dataset.version=version;
 if(older)banner.setAttribute('role','status');else banner.addEventListener('click',()=>location.reload());
 if(existing)existing.replaceWith(banner);else document.querySelector('main').prepend(banner);
}
function renderAvailability(){
 const a=state.availability||{},batch=state.batch||{},busy=!!state.busy?.length;
 $('check-new-connections').disabled=busy||!a.pending;$('cancel-connection-checks').hidden=!batch.running;
 $('check-pending').disabled=busy||!a.pending;$('cancel-checks').hidden=!batch.running;
 const reasons=$('availability-reasons');reasons.replaceChildren();
 for(const [key,label] of [['responded','Ответ получен'],['pending','Можно проверить'],['needsRetry','Прошлая проверка не завершилась ответом'],['needsKey','Нужен ключ'],['needsAccess','Тариф или способ вызова не подтверждён']])reasons.append(el('p','',`${t(label)}: ${a[key]??0}`));
 const button=el('button','text-button','Открыть подключения');button.addEventListener('click',()=>setView('connections'));reasons.append(button);
 $('batch-status').hidden=!batch.total;
 $('batch-status').textContent=t(batch.running?'Проверено {done} из {total} · новых ответов {ok}':'Проход завершён: проверок {done}, новых ответов {ok}',{done:batch.completed,total:batch.total,ok:batch.responded})+(Object.keys(batch.stopped||{}).length?' · '+t('Остановлено')+': '+Object.entries(batch.stopped).map(([p,s])=>providerName(p)+' — '+t(status({provider:p,model:{},check:{status:s}}).label)).join(', '):'');
}
$ ('check-pending').addEventListener('click',async()=>{try{state=await request('/api/check-pending',{start:true});render();}catch(e){toast(e.message);}});
$('cancel-checks').addEventListener('click',async()=>{try{state=await request('/api/check-cancel',{cancel:true});render();}catch(e){toast(e.message);}});

function inlineKeyForm(source,info,existing){
 if(existing){const input=existing.querySelector('input');input.disabled=info.canSave===false;existing.querySelector('button').disabled=info.canSave===false;input.placeholder=t(info.available?'Новый ключ для замены':'Вставь ключ сюда');input.setAttribute('aria-label',t('API-ключ')+' '+source.name);existing.querySelector('label').firstChild.nodeValue=t('API-ключ')+' · '+source.name;existing.querySelector('button').textContent=t('Сохранить и подключить');existing.querySelector('a').textContent=t('Получить API-ключ ↗');existing.querySelector('.inline-key-message').textContent=t(existing.dataset.notice||'');return existing;}
 const form=el('form','inline-key-form');form.dataset.keyProvider=source.id;form.autocomplete='off';
 const label=el('label','',t('API-ключ')+' · '+source.name),input=el('input');input.type='password';input.autocomplete='new-password';input.minLength=20;input.maxLength=2048;input.required=true;input.spellcheck=false;input.placeholder=t(info.available?'Новый ключ для замены':'Вставь ключ сюда');input.setAttribute('aria-label',t('API-ключ')+' '+source.name);input.disabled=info.canSave===false;label.append(input);
 const button=el('button','primary','Сохранить и подключить');button.type='submit';button.disabled=info.canSave===false;
 const message=el('p','inline-key-message');message.setAttribute('role','status');
 form.append(label,button,link('Получить API-ключ ↗',source.keyUrl),message);
 const showMessage=text=>{form.dataset.notice=text;message.textContent=t(text);};
 form.addEventListener('submit',async e=>{e.preventDefault();if(keyAction){showMessage('Дождись сохранения ключа');return;}keyAction='inline';button.disabled=true;input.disabled=true;showMessage('Сохранение…');
  try{state=await request('/api/credential',{provider:source.id,action:'save',key:input.value.trim()});input.value='';showMessage('Ключ сохранён. Обновляю каталог.');await refreshSource(source.id);}
  catch(e){showMessage(e.message);}finally{keyAction=null;button.disabled=info.canSave===false;input.disabled=info.canSave===false;}
 });return form;
}
$('check-new-connections').addEventListener('click',()=> $('check-pending').click());
$('cancel-connection-checks').addEventListener('click',()=> $('cancel-checks').click());

$('close-provider-help').addEventListener('click',()=>$('provider-help-dialog').close());
