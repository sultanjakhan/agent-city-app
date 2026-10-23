'use strict';
// Optional helper for the supplied frozen LiveSessions renderer. No DOM rebuild.
(function(root){
 const known=value=>Number.isSafeInteger(value)&&value>=0;
 function stageTiming(stage,now=Date.now()){
  if(!stage?.attemptBinding)return null;
  if(known(stage.durationMs))return {value:stage.durationMs,label:'collector-reported duration'};
  const start=Date.parse(stage.startedAt||'');
  if(['running','active','waiting'].includes(stage.status)&&!stage.endedAt&&Number.isFinite(start)&&start<=now)
   return {value:now-start,label:'running elapsed · derived from observed start; not completed duration'};
  return {value:null,label:'duration unknown'};
 }
 function stageMetrics(stage,formatNumber,formatDuration,now=Date.now()){
  const timing=stageTiming(stage,now);if(!timing)return null;
  const tokens=stage.usage?.total;
  return `${known(tokens)?formatNumber(tokens):'Unknown'} tokens · ${timing.value===null?'Unknown':formatDuration(timing.value)} · ${timing.label}`;
 }
 root.PassiveAttemptView=Object.freeze({stageTiming,stageMetrics});
})(globalThis);
