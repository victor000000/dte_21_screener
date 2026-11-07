const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = name => fs.readFileSync(path.resolve(__dirname, '../../../apps/trading_web/static', name), 'utf8');
const nodes = new Map();
const node = key => {if (!nodes.has(key)) nodes.set(key, {value:'', disabled:false}); return nodes.get(key);};
let navigations = [], clears = 0;
const draft = [{underlying:'QQQ',expiry:'2026-12-18',strike:'500',qty:2}];
const context = {window:{LiveUI:{clear(){clears++;},connectionHtml(){return '';},html(){return '';}},WorkspaceNavigation:{go:p=>navigations.push(p)}},
  $:node, setInterval(){}, legs:draft, esc:String, heading:()=>'', document:{querySelectorAll:()=>[]}};
vm.createContext(context);
vm.runInContext(source('market-ui.js'), context);
context.window.MarketUI.selectUnderlying('FUT:ZN:CBOT');
assert.equal(navigations.length,0);
context.window.MarketUI.selectUnderlying('TLT');
assert.deepEqual(navigations,['chain']);
assert.equal(clears,1);
assert.match(context.window.MarketUI.chainPage(), /id="chain-symbol" value="TLT"/);
assert.match(context.window.MarketUI.chainPage(), /Load expiries first/);
assert.equal(draft[0].underlying,'QQQ','screening handoff must preserve the draft');
context.URLSearchParams = URLSearchParams;
context.queueMicrotask = queueMicrotask;
context.page = 'screening';
context.render = () => {};
context.api = async () => ({available:true,metadata:{},rows:[
 {instrument:'TLT',asset_class:'equity_or_fund'},
 {instrument:'ZN',asset_class:'future'},
 {instrument:'SPX',asset_class:'index'},
 {instrument:'QQQ',asset_class:'unknown'}]});
vm.runInContext(source('screen-ui.js'),context);
context.window.ScreenUI.bind('screening');
setImmediate(()=>{
 const html=context.window.ScreenUI.page();
 assert.match(html,/data-screen-chain="TLT"/);
 for(const ticker of ['ZN','SPX','QQQ']) assert.ok(!html.includes(`data-screen-chain="${ticker}"`));
 console.log('Workspace flow: ticker handoff, draft preservation and unsupported-asset guards passed.');
});
