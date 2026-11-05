const stamp=()=>new Date().toISOString();
const risk=(draft=false,currency='USD')=>({status:'conditional estimate',account:{id:'TEST_ONLY',equity:100000,currency},mode:'paper',received_at:stamp(),draft:draft?{}:null,working_orders:0,decision:'TEST FIXTURE — NO BROKER DATA. Diagnostic only.',issues:[],limitations:['Synthetic fixtures for browser testing only.'],inputs:[],horizons:[1,5,10,15,20,21].map((days,i)=>({days,label:['1 day','1 week','2 weeks','3 weeks','4 weeks','21 days · primary'][i],current:{cvar:3000,pct:3,var:2000,worst:10000,band:'below warning',scenarios:400,tail_mass:20},after:draft?{cvar:6000,pct:6,var:4500,worst:15000,band:'warning',scenarios:400,tail_mass:20}:null,incremental_cvar:draft?3000:null}))});
const snapshot=()=>({account:{id:'TEST_ONLY',source:'TEST FIXTURE — NO BROKER DATA',equity:100000,buying_power:50000,currency:'USD'},positions:[],orders:[],fills:[],received_at:stamp()});
async function fixture(route,state){
 const req=route.request(),url=new URL(req.url()),p=url.pathname;
 const reply=d=>route.fulfill({json:d});
 if(p==='/api/session')return route.continue();
 if(p==='/api/risk'){state.riskCalls++;if(state.holdRisk)await new Promise(r=>state.releaseRisk=r);return reply(risk(Boolean(req.postDataJSON()?.ticket),state.currency));}
 if(req.method()!=='GET'){state.blockedWrites.push(p);return route.fulfill({status:403,json:{error:'Isolated browser test: mutation blocked'}});}
 if(p==='/api/snapshot')return reply(snapshot());
 if(p==='/api/receipts')return reply([]);
 if(p==='/api/market/connections')return reply({});
 if(p==='/api/market/quotes')return reply({rows:[],source:'test'});
 if(p==='/api/market/underlying')return reply({observations:[],sources:[]});
 if(p==='/api/cn/catalog')return reply({products:[],status:[],release:'TEST_ONLY'});
 if(p==='/api/cn/leg-risk')return reply({legs:[],futures:[],limitations:[]});
 if(p==='/api/screening')return reply({available:false,message:'No saved screen in isolated fixture'});
 if(p==='/api/attribution')return reply({available:false,days:[],message:'No attribution in isolated fixture'});
 if(p==='/api/data/status')return reply({jobs:[],blockers:[],sources:[],existing_jobs:[],received_at:stamp()});
 return route.fulfill({status:503,json:{error:'Isolated fixture: endpoint unavailable'}});
}
module.exports={fixture,risk};
