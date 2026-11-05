/* Run with Node: verify cadence, in-flight protection, pause and draft preservation. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const path=require('node:path');
let clock=10000,calls=0,interval,intervalMs,resolve;
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='#broker'?'ibkr':'',checked:true,disabled:false,replaceChildren(){}});return elements.get(id);};
const sandbox={window:{LiveUI:{enabled:()=>true}},document:{hidden:false},page:'risk',session:{},
  $:element,esc:String,draftPayload:()=>({}),render(){},message(){},Date:{now:()=>clock},
  setInterval(fn,ms){interval=fn;intervalMs=ms;},queueMicrotask,
  api(){calls++;return new Promise(r=>{resolve=r;});}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../apps/trading_web/static/risk-ui.js'),'utf8'),sandbox);
(async()=>{
  assert.equal(intervalMs,1000);
  interval();assert.equal(calls,1);
  clock=20000;interval();assert.equal(calls,1,'pending request must not overlap');
  resolve({horizons:[],issues:[],decision:'synthetic fixture'});
  await new Promise(r=>setImmediate(r));
  sandbox.window.RiskUI.bind();
  element('#risk-auto').onchange({target:{checked:false}});interval();assert.equal(calls,1);
  element('#risk-auto').onchange({target:{checked:true}});
  sandbox.document.hidden=true;interval();assert.equal(calls,1);
  sandbox.document.hidden=false;
  sandbox.window.RiskUI.setReviewed({draft:{}});interval();assert.equal(calls,1,'draft comparison stays visible');
  sandbox.window.RiskUI.invalidate();interval();assert.equal(calls,2);
  console.log('PASS: 10-second risk refresh, no overlap, pause/hidden and draft preservation');
})().catch(e=>{console.error(e);process.exitCode=1;});
