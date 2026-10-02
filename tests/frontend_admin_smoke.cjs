// Execute the admin module against its actual HTML IDs and lightweight DOM stubs.
const fs=require('fs'),vm=require('vm');
const root=require('path').resolve(__dirname,'..');
const html=fs.readFileSync(root+'/web/admin.html','utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
const elements=Object.fromEntries(ids.map(id=>[id,{id,value:id==='simChat'?'!km':'3',checked:false,dataset:{},textContent:'',innerHTML:'',style:{},classList:{toggle(){},add(){},remove(){}},querySelectorAll(){return []},append(){}}]));
const actions=[];
const context={console,Set,Math,Date,Number,String,JSON,alert(){},confirm(){return true},setInterval(){return 1},clearInterval(){},window:{open(){}},location:{},qs(selector){const e=elements[selector.slice(1)];if(!e)throw new Error('Missing '+selector);return e},qsa(){return []},fmt(v){return Number(v).toFixed(1)},connect(){},async action(name,payload){actions.push({name,payload});return {reply:'[SIM] 0.0/1000 km'}},fetch:async()=>({json:async()=>({items:[]})})};
const script=html.match(/<script type="module">([\s\S]*?)<\/script>/)[1].replace(/import[^;]+;/,'');
vm.createContext(context);vm.runInContext(script,context);
(async()=>{await elements.simStart.onclick();await elements.simChatSend.onclick();if(!actions.some(a=>a.name==='simulation_start')||!actions.some(a=>a.name==='sim_chat'))throw new Error('Action bindings failed');if(!elements.simChatReply.textContent.includes('[SIM]'))throw new Error('Reply output failed');console.log('Admin module initialized; simulation and chat buttons bound; local reply displayed.')})().catch(e=>{console.error(e);process.exitCode=1});
