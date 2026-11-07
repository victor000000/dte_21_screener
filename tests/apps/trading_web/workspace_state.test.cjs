/* Headless UI state tests. No HTTP server, broker or DOM automation required. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const nodes=new Map();
const node=selector=>{
 if(!nodes.has(selector))nodes.set(selector,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,
  selectedOptions:[{textContent:'Synthetic paper account'}],classList:{toggle(){}},attributes:{},
  setAttribute(k,v){this.attributes[k]=v;},addEventListener(){},replaceChildren(){this.innerHTML='';},focus(){},scrollIntoView(){}});
 return nodes.get(selector);
};
node('#broker').value='ibkr';node('#effect').value='debit';
let loading=false;
const context={document:{querySelector:node,querySelectorAll:()=>[]},setInterval(){},setTimeout(){},queueMicrotask,
 fetch(){throw Error('UI state tests must never perform HTTP');},
 window:{WorkspaceNavigation:{current:()=> 'positions'},RiskUI:{invalidate(){},isLoading:()=>loading,bind(){}},
  ScreenUI:{page:()=>'<h1>Screening</h1>',bind(){}},addEventListener(){}}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../../apps/trading_web/static/app.js'),'utf8'),context);
const run=code=>vm.runInContext(code,context);
assert.equal(run('ticketOpen'),false,'startup must keep editor closed');
run('newTicket()');assert.equal(node('#ticket').hidden,false);
run("legs[0].underlying='QQQ';preview={token:'synthetic'};setTicketOpen(false)");
assert.equal(node('#ticket').hidden,true);
run('setTicketOpen(true)');assert.equal(run('legs[0].underlying'),'QQQ');
assert.equal(run('preview.token'),'synthetic','collapse must preserve order review');
run("page='screening';render()");assert.equal(node('#ticket').hidden,true);
run("page='positions';render()");assert.equal(node('#ticket').hidden,false);
assert.equal(run('legs[0].underlying'),'QQQ','research round trip must preserve draft');
loading=true;run('render()');assert.equal(node('#estimate-risk').disabled,true,'render must preserve pending risk state');
loading=false;run('render()');assert.equal(node('#estimate-risk').disabled,false);
node('#broker').value='alpaca';run('render()');assert.equal(node('#estimate-risk').disabled,true);
run('newTicket()');assert.equal(run('legs[0].underlying'),'');assert.equal(run('preview'),null);
console.log('Workspace state: collapse/research draft preservation, review preservation and rendered risk gating passed.');
