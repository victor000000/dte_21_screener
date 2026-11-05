const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const nodes=new Map();
const node=s=>{if(!nodes.has(s))nodes.set(s,{value:'',innerHTML:'',textContent:'',disabled:false,replaceChildren(){this.innerHTML='';}});return nodes.get(s);};
node('#broker').value='ibkr';
let resolve, calls=0;
const context={window:{},$ :node,session:{token:'test'},page:'positions',document:{hidden:false},setInterval(){},
  draftPayload:()=>({broker:node('#broker').value,legs:[]}),
  api:()=>{calls++;return new Promise(r=>resolve=r);},render(){},message(){},
  esc:s=>String(s??'').replaceAll('<','&lt;').replaceAll('>','&gt;'),
  money:s=>String(s??'—'),currencyMoney:s=>String(s??'—'),time:s=>s,heading:()=>''};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../../apps/trading_web/static/risk-ui.js'),'utf8'),context);
const risk=context.window.RiskUI;
const response={status:'unavailable',decision:'No clearance',horizons:[],issues:['<script>'],inputs:[],limitations:[]};
(async()=>{
  let pending=risk.estimate(true);assert.equal(calls,1);risk.invalidate();resolve(response);await pending;
  assert.equal(node('#ticket-risk').innerHTML,'','edited draft must discard delayed response');
  pending=risk.estimate(true);node('#broker').value='alpaca';resolve(response);await pending;
  assert.equal(node('#ticket-risk').innerHTML,'','account switch must discard delayed response');
  node('#broker').value='ibkr';pending=risk.estimate(true);resolve(response);await pending;
  assert.match(node('#ticket-risk').innerHTML,/&lt;script&gt;/,'provider text must be escaped');
  assert.equal(node('#estimate-risk').disabled,false);
  console.log('Risk UI: draft invalidation, account isolation, escaping and loading cleanup passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});
