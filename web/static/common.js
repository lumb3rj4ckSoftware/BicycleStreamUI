export function fmt(v,d=1){const n=Number(v);return Number.isFinite(n)?n.toFixed(d):'–'}
export function qs(sel,root=document){return root.querySelector(sel)}
export function qsa(sel,root=document){return [...root.querySelectorAll(sel)]}
export function connect(onState,onEvent){
  let ws=null,timer=null,lastSeq=0,stopped=false;
  const poll=async()=>{try{const r=await fetch('/api/state',{cache:'no-store'});if(r.ok)onState(await r.json());const e=await fetch('/api/events?since='+lastSeq,{cache:'no-store'});if(e.ok){const d=await e.json();for(const x of d.events||[]){lastSeq=Math.max(lastSeq,x.seq||0);onEvent?.(x)}}}catch(_){}};
  const open=()=>{if(stopped)return;const proto=location.protocol==='https:'?'wss:':'ws:';ws=new WebSocket(proto+'//'+location.host+'/ws');
    ws.onmessage=(m)=>{try{const d=JSON.parse(m.data);if(d.type==='state')onState(d.payload);if(d.type==='event'&&(d.payload.seq||0)>lastSeq){lastSeq=d.payload.seq;onEvent?.(d.payload)}}catch(_){}};
    ws.onclose=()=>{if(stopped)return;timer=setTimeout(open,1200)};ws.onerror=()=>ws.close();
  };open();
  const fallback=setInterval(()=>{if(!ws||ws.readyState!==1)poll()},1200);
  return()=>{stopped=true;clearTimeout(timer);clearInterval(fallback);try{ws?.close()}catch(_){}};
}
export async function action(action,payload={}){const r=await fetch('/api/admin/action',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action,payload})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Action failed');return d}
