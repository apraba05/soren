"use strict";

const MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0";
const PACE = 160;
const EXTRACTION_PROMPT = `You are a legal-billing intake assistant.

Read the invoice below and return ONLY a JSON object with this schema:
  vendor      string  - the billing firm exactly as printed
  amount      number  - the final total payable, no currency symbol
  currency    string  - ISO code, default USD
  matter_id   string  - the client matter, format MAT-####, null if absent
  line_items  array   - {code, description, amount} per billed line
  confidence  number  - 0..1, your own certainty about the fields above
  notes       array   - anything a human should know about this document

Do not judge the invoice. Do not approve or reject it. Extract only.
If a field is unreadable, return null and lower your confidence.

--- INVOICE ---
{document}
--- END INVOICE ---`;

const INITIAL_POLICY = {
  version: 3, currency: "USD", settings: {review_minutes_per_invoice: 7},
  rules: [
    {id:"extraction_confidence",enabled:true,title:"Extraction confidence",description:"Never act on fields the model was unsure about.",params:{min_confidence:.80}},
    {id:"matter_known",enabled:true,title:"Known matter",description:"Every invoice must map to an open matter in the registry.",params:{}},
    {id:"vendor_panel",enabled:true,title:"Approved vendor panel",description:"Only firms on the panel can be paid without a human signature.",params:{}},
    {id:"amount_ceiling",enabled:true,title:"Auto-approval ceiling",description:"Invoices above the ceiling always get a human signature.",params:{max_auto_approve:5000}},
    {id:"blocked_line_items",enabled:true,title:"Disallowed billing codes",description:"Codes the outside counsel guidelines say we do not pay.",params:{blocked:[
      {code:"A101",label:"administrative / clerical time"},{code:"E110",label:"out-of-town travel"},
      {code:"rush surcharge",label:"unapproved rush surcharge"},{code:"word processing",label:"clerical word processing"}]}},
    {id:"matter_budget",enabled:true,title:"Matter budget guard",description:"Hold invoices that would push a matter past its budget ceiling.",params:{utilization_ceiling:.90}}
  ],
  approved_vendors:["Wexler & Cole LLP","Bramwell Hastings LLP","Tanaka IP Partners","Orion Court Reporting","Delacroix & Boone"],
  matters:{
    "MAT-1042":{name:"Acme Robotics v. Nordic Systems",budget:50000,spent_to_date:41200},
    "MAT-2287":{name:"Series C Financing",budget:90000,spent_to_date:52000},
    "MAT-3310":{name:"Hollis Employment Arbitration",budget:25000,spent_to_date:9400},
    "MAT-4455":{name:"EU Data Privacy Audit",budget:40000,spent_to_date:12800},
    "MAT-5001":{name:"Project Ferrous / M&A Diligence",budget:150000,spent_to_date:61000}
  }
};

const TOOLS = [
  {name:"extract_invoice_fields",description:"Extract vendor, amount, matter id and line items from raw invoice text. Returns a confidence score. Does not approve anything.",inputSchema:{type:"object",properties:{invoice_text:{type:"string"}},required:["invoice_text"]}},
  {name:"check_billing_policy",description:"Evaluate extracted invoice fields against policy.yaml. Returns APPROVE or EXCEPTION with a reason for every rule that fired.",inputSchema:{type:"object",properties:{vendor:{type:"string"},amount:{type:"number"},matter_id:{type:["string","null"]},confidence:{type:"number"},line_items:{type:"array"}},required:["amount","confidence"]}},
  {name:"list_exception_queue",description:"List invoices currently waiting on a human decision.",inputSchema:{type:"object",properties:{}}}
];

const SEED_INVOICES = [{"id":"INV-2291","file":"wexler_cole_july.pdf","text":"WEXLER & COLE LLP\n1 Battery Park Plaza, New York, NY 10004\n\n                            INVOICE\n\nInvoice No:       WC-2291\nInvoice Date:     2026-07-31\nClient Matter:    MAT-1042 / Acme Robotics v. Nordic Systems\nBilling Period:   July 2026\n\nPROFESSIONAL SERVICES\n  L120  Analysis/Strategy          6.5 hrs @ $410.00      2,665.00\n  L210  Pleadings                  2.0 hrs @ $410.00        820.00\n\nDISBURSEMENTS\n  E106  Online research                                      94.00\n\n                     TOTAL DUE (USD)                    $3,579.00\n\nPayment due within 30 days per outside counsel guidelines."},{"id":"INV-2292","file":"bramwell_hastings_q3.pdf","text":"Bramwell Hastings LLP\nStatement of Account\n\nMatter ID ......... MAT-2287\nMatter Name ....... Series C Financing\nInvoice ........... BH-88104\nDate .............. 2026-08-03\n\n  Partner   J. Bramwell     11.0 hrs   $875/hr      9,625.00\n  Associate  R. Okafor      14.5 hrs   $520/hr      7,540.00\n  Paralegal  D. Ruiz         6.0 hrs   $210/hr      1,260.00\n\n  Subtotal                                         18,425.00\n  Less negotiated discount (8%)                    -1,474.00\n\n  AMOUNT PAYABLE USD                              16,951.00"},{"id":"INV-2293","file":"ridgeline_ediscovery_aug.pdf","text":"RIDGELINE eDISCOVERY INC.\nData processing & hosting services\n\nBill To: Legal Operations\nMatter: MAT-1042\nInvoice #: RE-40219   Date: 2026-08-05\n\n  Processing, 412 GB @ $9.50/GB ................ 3,914.00\n  Hosting, 1.2 TB, monthly ....................... 480.00\n\n  TOTAL DUE: $4,394.00\n\nTerms: Net 45."},{"id":"INV-2294","file":"tanaka_ip_partners_aug.pdf","text":"TANAKA IP PARTNERS\nIntellectual Property Counsel | Tokyo * Palo Alto\n\nINVOICE TIP-7731                     Issued 2026-08-06\nMatter Reference: MAT-1042\n\n  Claim chart preparation      8.0 hrs @ $560.00     4,480.00\n  Prior art review             3.5 hrs @ $560.00     1,960.00\n  E110 Out-of-town travel (airfare, business)          2,180.00\n\n  TOTAL AMOUNT DUE (USD)                            $8,620.00"},{"id":"INV-2295","file":"orion_court_reporting.pdf","text":"ORION COURT REPORTING\nCertified transcripts and videography\n\nInvoice OCR-1188 | 2026-08-07 | Matter MAT-3310\n\n  Deposition transcript, 214 pages @ $4.15 ......... 888.10\n  Rough draft, same day ............................ 165.00\n  Videographer, 4 hrs @ $95.00 ..................... 380.00\n\n  TOTAL DUE (USD) $1,433.10"},{"id":"INV-2296","file":"vector_legal_staffing.pdf","text":"VECTOR LEGAL STAFFING\nContract attorney placement\n\nINVOICE VLS-5540\nDATE 2026-08-08\nMATTER MAT-4455 (EU Data Privacy Audit)\n\n  Contract review, 6 reviewers x 38 hrs @ $72/hr .... 16,416.00\n  Project management fee ............................. 1,800.00\n\n  TOTAL 18,216.00 USD"},{"id":"INV-2297","file":"delacroix_boone_scan.pdf","text":"DELACROIX & B00NE\n       -- scanned copy, fax quality --\n\nInvoice  DB-0 9 12          Date  2026/08/09\nMatter   MA T-  ????\n\n  Corporate governance advice     4.0 hr5   1,840.OO\n  Board minute drafting           2.5 hrs     1,150.00\n\n  T0TAL  DUE     $  2,99O.00\n\n(margin note, handwritten) confirm matter w/ K. Adeyemi"},{"id":"INV-2298","file":"wexler_cole_aug_supplemental.pdf","text":"WEXLER & COLE LLP\n\n                            INVOICE\n\nInvoice No:       WC-2314\nInvoice Date:     2026-08-10\nClient Matter:    MAT-3310 / Hollis Employment Arbitration\n\nPROFESSIONAL SERVICES\n  L390  Other discovery            3.0 hrs @ $410.00      1,230.00\n  A101  Plan and prepare (admin)   1.5 hrs @ $410.00        615.00\n  L440  Other trial preparation    2.0 hrs @ $410.00        820.00\n\n                     TOTAL DUE (USD)                    $2,665.00"},{"id":"INV-2299","file":"halcyon_trial_graphics.pdf","text":"HALCYON TRIAL GRAPHICS\nDemonstratives & courtroom presentation\n\nInvoice HTG-2077  //  2026-08-11  //  Matter MAT-1042\n\n  Animation storyboard, 3 scenes .................. 6,300.00\n  Exhibit board printing, 22 boards ............... 1,540.00\n  Rush surcharge .................................... 900.00\n\n  TOTAL DUE (USD) $8,740.00"},{"id":"INV-2300","file":"bramwell_hastings_diligence.pdf","text":"Bramwell Hastings LLP\nStatement of Account\n\nMatter ID ......... MAT-5001\nMatter Name ....... Project Ferrous / M&A Diligence\nInvoice ........... BH-88266\nDate .............. 2026-08-12\n\n  Partner   J. Bramwell      4.0 hrs   $875/hr      3,500.00\n  Associate  L. Vance        2.5 hrs   $520/hr      1,300.00\n\n  AMOUNT PAYABLE USD                                4,800.00"},{"id":"INV-2301","file":"tanaka_ip_partners_filing.pdf","text":"TANAKA IP PARTNERS\n\nINVOICE TIP-7802                     Issued 2026-08-13\nMatter Reference: MAT-1042\n\n  Office action response       2.0 hrs @ $560.00     1,120.00\n  USPTO filing fee                                      800.00\n\n  TOTAL AMOUNT DUE (USD)                            $1,920.00"},{"id":"INV-2302","file":"orion_court_reporting_2.pdf","text":"ORION COURT REPORTING\n\nInvoice OCR-1204 | 2026-08-14 | Matter MAT-3310\n\n  Deposition transcript, 96 pages @ $4.15 .......... 398.40\n  Exhibit scanning ................................. 120.00\n\n  TOTAL DUE (USD) $518.40"},{"id":"INV-2303","file":"delacroix_boone_aug.pdf","text":"DELACROIX & BOONE\nCorporate & Governance\n\nInvoice DB-0944            Date 2026-08-15\nMatter MAT-5001 / Project Ferrous\n\n  Diligence memo             9.0 hrs @ $455.00      4,095.00\n  Signing checklist          2.0 hrs @ $455.00        910.00\n\n  TOTAL DUE     $5,005.00"},{"id":"INV-2304","file":"wexler_cole_privacy.pdf","text":"WEXLER & COLE LLP\n\n                            INVOICE\n\nInvoice No:       WC-2330\nInvoice Date:     2026-08-16\nClient Matter:    MAT-4455 / EU Data Privacy Audit\n\nPROFESSIONAL SERVICES\n  L110  Fact investigation        5.0 hrs @ $410.00      2,050.00\n  L120  Analysis/Strategy         2.0 hrs @ $410.00        820.00\n\n                     TOTAL DUE (USD)                    $2,870.00"}];
const PRESEED_IDS = ["INV-2291","INV-2292","INV-2293","INV-2294","INV-2295"];
const BY_ID = Object.fromEntries(SEED_INVOICES.map(i => [i.id, i]));
const clone = value => JSON.parse(JSON.stringify(value));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const round2 = n => Math.round((n + Number.EPSILON) * 100) / 100;
const fmt = n => Number(n).toLocaleString(undefined,{minimumFractionDigits:Number.isInteger(Number(n))?0:2,maximumFractionDigits:2});

let state, jobChain = Promise.resolve(), generation = 0;

function key(name) { return (name || "").toLowerCase().replace(/[^a-z0-9]/g, ""); }
function check(rule, fired, detail) { return {id:rule.id,title:rule.title,status:fired?"fire":"pass",detail}; }

function policyCheck(fields, policy, spend) {
  const checks = policy.rules.map(rule => {
    if (!rule.enabled) return {id:rule.id,title:rule.title,status:"off",detail:"rule disabled in policy.yaml"};
    if (rule.id === "extraction_confidence") {
      const floor=rule.params.min_confidence, got=fields.confidence || 0;
      return check(rule,got<floor,`model confidence ${got.toFixed(2)} ${got<floor?"is below":"clears"} the ${floor.toFixed(2)} floor`);
    }
    if (rule.id === "matter_known") {
      const matter=fields.matter_id;
      if (!matter) return check(rule,true,"no matter id could be read off the invoice");
      if (!policy.matters[matter]) return check(rule,true,`${matter} is not an open matter`);
      return check(rule,false,`${matter} - ${policy.matters[matter].name}`);
    }
    if (rule.id === "vendor_panel") {
      if (!fields.vendor) return check(rule,true,"vendor name could not be read");
      const onPanel=policy.approved_vendors.some(v=>key(v)===key(fields.vendor));
      return check(rule,!onPanel,`'${fields.vendor}' is ${onPanel?"":"not "}on the approved panel`);
    }
    if (rule.id === "amount_ceiling") {
      if (fields.amount == null) return check(rule,true,"no invoice total could be read");
      const ceiling=rule.params.max_auto_approve, fired=fields.amount>ceiling;
      return check(rule,fired,`$${fmt(fields.amount)} ${fired?"exceeds":"is under"} the $${fmt(ceiling)} ${fired?"auto-approval ":""}ceiling`);
    }
    if (rule.id === "blocked_line_items") {
      const hits=[];
      for (const item of fields.line_items || []) {
        const hay=`${item.code||""} ${item.description||""}`.toLowerCase();
        for (const b of rule.params.blocked) if (hay.includes(b.code.toLowerCase())) hits.push(`${b.code} (${b.label})`);
      }
      const unique=[...new Set(hits)].sort();
      return check(rule,!!unique.length,unique.length?`billed for ${unique.join(", ")}`:`${(fields.line_items||[]).length} line item(s), none disallowed`);
    }
    const matter=fields.matter_id, amount=fields.amount, ceiling=rule.params.utilization_ceiling;
    if (!matter || !policy.matters[matter] || amount == null) return check(rule,false,"skipped - needs a known matter and a total");
    const projected=((spend[matter]||0)+amount)/policy.matters[matter].budget, fired=projected>ceiling;
    return check(rule,fired,fired
      ? `would put ${matter} at ${Math.round(projected*100)}% of its $${fmt(policy.matters[matter].budget)} budget (ceiling ${Math.round(ceiling*100)}%)`
      : `${matter} would sit at ${Math.round(projected*100)}% of budget`);
  });
  const reasons=checks.filter(c=>c.status==="fire").map(c=>c.detail);
  return {status:reasons.length?"EXCEPTION":"APPROVE",reasons,checks,policy_version:policy.version};
}

function normalizeVendor(line) {
  line=line.trim().replace(/[.,]+$/,"").split("//")[0].trim();
  if (!line || line.length>60) return null;
  const acronyms=new Set(["LLP","LLC","IP","PC","PLLC"]);
  return line.split(/\s+/).map(word => {
    if (acronyms.has(word.toUpperCase())) return word.toUpperCase();
    if (word===word.toUpperCase()) return word.charAt(0).toUpperCase()+word.slice(1).toLowerCase();
    if (word.length>1 && word.slice(1)===word.slice(1).toUpperCase()) return word[0]+word.slice(1).toLowerCase();
    return word;
  }).join(" ");
}

function repair(token) {
  const repairs=(token.match(/[OQ]/g)||[]).length;
  const value=Number(token.replace(/[OQ]/g,"0").replace(/[ ,]/g,""));
  return [Number.isFinite(value)?value:null,repairs];
}

function readInvoice(document) {
  let text=document;
  if (text.includes("--- INVOICE ---")) text=text.split("--- INVOICE ---")[1].split("--- END INVOICE ---")[0];
  const lines=text.split(/\r?\n/).map(x=>x.replace(/\s+$/, "")), notes=[];
  let repairs=0, vendor=null;
  for (const line of lines.slice(0,3)) if (line.trim()) { vendor=normalizeVendor(line); break; }
  const moneyPattern="-?[0-9OQ]{1,3}(?:,[0-9OQ]{3})*\\.[0-9OQ]{2}";
  const totalLabel=/t[o0]tal|amount\s+payable|amount\s+due/i;
  const preferredLabel=/total\s+due|amount\s+due|amount\s+payable|total\s+amount/i;
  const trailing=new RegExp("\\$?\\s*("+moneyPattern+")\\s*(?:USD)?\\s*$","i");
  const totals=lines.filter(line=>totalLabel.test(line)&&trailing.test(line));
  const preferred=totals.filter(line=>preferredLabel.test(line)), candidates=preferred.length?preferred:totals;
  let amount=null;
  if (candidates.length) { const got=repair(candidates[candidates.length-1].match(trailing)[1]); amount=got[0]; repairs+=got[1]; if(totals.length>1) notes.push(`${totals.length} total-like lines found, took the labelled one`); }
  const matterMatch=text.match(/MAT-\d{4}/), matter_id=matterMatch?matterMatch[0]:null;
  if (!matter_id) notes.push("no matter id matched MAT-####");
  const line_items=[];
  for (const line of lines) {
    if (!line.trim() || totalLabel.test(line)) continue;
    const hit=line.match(trailing); if(!hit) continue;
    const got=repair(hit[1]); if(got[0]==null) continue; repairs+=got[1];
    let head=line.slice(0,hit.index).trim().replace(/^[. ]+|[. ]+$/g,"").replace(/\s+/g," ");
    const cm=head.match(/^([A-Z]\d{3})\b/), code=cm?cm[1]:null; if(code) head=head.slice(code.length).trim();
    line_items.push({code,description:head,amount:got[0]});
  }
  let confidence=.99; if(amount==null)confidence-=.35;if(!matter_id)confidence-=.25;if(!vendor)confidence-=.20;
  if(repairs){confidence-=.30;notes.push(`repaired ${repairs} OCR character(s) inside numbers`);}if(totals.length>1)confidence-=.03;if(!line_items.length)confidence-=.05;
  return {vendor,amount:amount==null?null:round2(amount),currency:"USD",matter_id,line_items,confidence:round2(Math.max(confidence,.05)),notes};
}

function rngFor(text) {
  let h=2166136261; for(let i=0;i<text.length;i++){h^=text.charCodeAt(i);h=Math.imul(h,16777619);}
  return ()=>{h+=0x6D2B79F5;let t=h;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};
}

function extract(document, quiet=false) {
  const prompt=EXTRACTION_PROMPT.replace("{document}",document), random=rngFor(document);
  let fields=readInvoice(prompt);
  if(state.faults.llm_degraded){fields=clone(fields);fields.confidence=round2(.31+random()*(.62-.31));if(fields.amount!=null)fields.amount=round2(fields.amount*(.55+random()*.9));if(random()<.4)fields.matter_id=null;fields.notes=[...(fields.notes||[]),"model returned unstable fields"];}
  const raw_output=JSON.stringify(fields,null,2), usage={inputTokens:Math.max(1,Math.floor(prompt.length/4)),outputTokens:Math.max(1,Math.floor(raw_output.length/4))};
  usage.totalTokens=usage.inputTokens+usage.outputTokens;
  return {fields,prompt,raw_output,usage,latency_ms:quiet?0:Math.floor(220+random()*280+(state.faults.llm_degraded?150:0)),model_id:MODEL_ID,backend:"simulated"};
}

function nextStreamId(){state.seq++;return `${Date.now()}-${state.seq}`;}
function doStore(op,payload){
  if(op==="audit")state.auditRaw.push({...clone(payload),stream_id:nextStreamId()});
  else if(op==="queue")state.queue.unshift(clone(payload));
}
function storeWrite(op,payload){if(!state.store.up){state.buffer.push([op,clone(payload)]);return true;}doStore(op,payload);return false;}
function appendAudit(entry){return storeWrite("audit",{...entry,ts:entry.ts||Date.now()/1000});}
function pushException(item){return storeWrite("queue",item);}
function popException(id){const n=state.queue.findIndex(q=>q.invoice_id===id);return n<0?null:state.queue.splice(n,1)[0];}

async function emitStage(event){onStage(event);render(snapshot());await sleep(PACE);}
function emitMcp(event){logMcp(event);}

async function processInvoice(invoice, quiet=false, token=generation) {
  const started=performance.now();
  const hop=async(stage,status,detail="",extra={})=>{if(!quiet){await emitStage({invoice_id:invoice.id,stage,status,detail,...extra});if(token!==generation)throw new Error("reset");}};
  try {
    await hop("intake","active",`${invoice.id} (${invoice.file})`);
    await hop("extract","active","tools/call extract_invoice_fields");
    if(!quiet)emitMcp({direction:"request",method:"tools/call",tool:"extract_invoice_fields",payload:{invoice_text:invoice.text.slice(0,80)+" ..."}});
    const extraction=extract(invoice.text,quiet), fields=extraction.fields; state.tokens+=extraction.usage.totalTokens;
    if(!quiet){await sleep(extraction.latency_ms);emitMcp({direction:"response",method:"tools/call",tool:"extract_invoice_fields",is_error:false,payload:{vendor:fields.vendor,amount:fields.amount,matter_id:fields.matter_id,confidence:fields.confidence}});}
    await hop("extract","done",`${extraction.usage.totalTokens} tokens, ${extraction.latency_ms} ms`,{fields,prompt:extraction.prompt,raw_output:extraction.raw_output,usage:extraction.usage});
    await hop("policy","active","tools/call check_billing_policy");
    if(!quiet)emitMcp({direction:"request",method:"tools/call",tool:"check_billing_policy",payload:{vendor:fields.vendor,amount:fields.amount,matter_id:fields.matter_id,confidence:fields.confidence}});
    const verdict=policyCheck(fields,state.policy,state.spend);
    if(!quiet){for(const c of verdict.checks){onCheck(c);await sleep(PACE/2);}emitMcp({direction:"response",method:"tools/call",tool:"check_billing_policy",is_error:false,payload:{status:verdict.status,reasons:verdict.reasons}});}
    await hop("policy","done",verdict.status,{checks:verdict.checks});
    const elapsed=Math.floor(performance.now()-started), record={invoice_id:invoice.id,file:invoice.file,vendor:fields.vendor,amount:fields.amount,matter_id:fields.matter_id,confidence:fields.confidence,status:verdict.status,reasons:verdict.reasons,checks:verdict.checks,notes:fields.notes||[],line_items:fields.line_items||[],policy_version:verdict.policy_version,model:MODEL_ID,backend:"simulated",latency_ms:elapsed,decided_at:Date.now()/1000};
    const approved=verdict.status==="APPROVE";if(approved&&state.spend[record.matter_id]!=null)state.spend[record.matter_id]+=record.amount||0;
    const buffered=appendAudit({invoice_id:invoice.id,actor:"agent",event:approved?"AUTO_APPROVED":"ROUTED_TO_HUMAN",status:verdict.status,vendor:record.vendor,amount:record.amount,matter_id:record.matter_id,confidence:record.confidence,reasons:verdict.reasons,policy_version:verdict.policy_version});
    if(!approved)pushException({invoice_id:invoice.id,file:invoice.file,vendor:record.vendor,amount:record.amount,matter_id:record.matter_id,confidence:record.confidence,reasons:verdict.reasons,queued_at:Date.now()/1000});
    state.decisions.push(record);state.latencies.push(elapsed);state.pending.delete(invoice.id);
    await hop("route","done",approved?"auto-approved":"queued for human review",{decision_status:verdict.status,buffered});
    if(!quiet){onDecision(record);render(snapshot());}
    return record;
  } catch(err) { if(err.message!=="reset")addLog("error",`${invoice.id} failed: ${err.message}`); return null; }
}

function metrics(){const approved=state.decisions.filter(d=>["APPROVE","HUMAN_APPROVED"].includes(d.status)),auto=state.decisions.filter(d=>d.status==="APPROVE");return{processed:state.decisions.length,auto_approved:auto.length,exceptions:state.decisions.filter(d=>d.status==="EXCEPTION").length,auto_rate:state.decisions.length?Math.round(100*auto.length/state.decisions.length):0,usd_auto_approved:round2(approved.reduce((n,d)=>n+(d.amount||0),0)),usd_held:round2(state.queue.reduce((n,q)=>n+(q.amount||0),0)),avg_latency_ms:state.latencies.length?Math.floor(state.latencies.reduce((a,b)=>a+b,0)/state.latencies.length):0,minutes_saved:auto.length*state.policy.settings.review_minutes_per_invoice,tokens:state.tokens};}
function whatif(){const spend=Object.fromEntries(Object.entries(state.policy.matters).map(([id,m])=>[id,m.spent_to_date])),flips=[];for(const r of state.decisions){const v=policyCheck(r,state.policy,spend);if(v.status==="APPROVE"&&spend[r.matter_id]!=null)spend[r.matter_id]+=r.amount||0;const was=["APPROVE","HUMAN_APPROVED"].includes(r.status)?"APPROVE":"EXCEPTION";if(v.status!==was)flips.push({invoice_id:r.invoice_id,from:was,to:v.status,reasons:v.reasons});}return flips;}
function snapshot(){return{invoices:SEED_INVOICES.map(i=>({...i,done:!state.pending.has(i.id)})),policy:state.policy,matters:Object.entries(state.policy.matters).map(([id,m])=>({id,name:m.name,budget:m.budget,spent:round2(state.spend[id]||0),utilisation:Math.round(1000*(state.spend[id]||0)/m.budget)/10})),decisions:state.decisions.slice(-40),audit:state.auditRaw.slice(-60).reverse(),queue:clone(state.queue),metrics:metrics(),store:{backend:"in-process",up:state.store.up,audit_len:state.auditRaw.length,queue_len:state.queue.length,buffered:state.buffer.length,replayed:state.store.replayed},faults:state.faults,runtime:{model:MODEL_ID,bedrock:"simulated",redis:"in-process",pending:state.pending.size},tools:TOOLS,whatif:whatif()};}

async function resetState() {generation++;state={policy:clone(INITIAL_POLICY),spend:{},decisions:[],pending:new Set(SEED_INVOICES.map(i=>i.id)),latencies:[],tokens:0,auditRaw:[],queue:[],buffer:[],seq:0,store:{up:true,replayed:0},faults:{llm_degraded:false,redis_down:false}};for(const[id,m]of Object.entries(state.policy.matters))state.spend[id]=m.spent_to_date;for(const id of PRESEED_IDS)await processInvoice(BY_ID[id],true,generation);running=null;render(snapshot());}
function addLog(level,text){$("mcplog").insertAdjacentHTML("afterbegin",`<div style="color:var(--${level==="error"?"bad":level==="warn"?"warn":"ok"})">${text}</div>`);}
function queueJobs(ids){jobChain=jobChain.then(async()=>{for(const id of ids)if(state.pending.has(id)){running=id;render(snapshot());await processInvoice(BY_ID[id],false,generation);}});}
function runInvoice(id){const inv=BY_ID[id];resetPipe();running=id;$("liveId").textContent=id+"  "+inv.file;$("rawText").textContent=inv.text;queueJobs([id]);}
function updatePolicy(body){for(const r of state.policy.rules)if(r.id===body.rule_id){if("enabled"in body)r.enabled=!!body.enabled;if("param"in body)r.params[body.param]=body.value;}if(body.vendor){const n=state.policy.approved_vendors.indexOf(body.vendor);n>=0?state.policy.approved_vendors.splice(n,1):state.policy.approved_vendors.push(body.vendor);}state.policy.version=round2(state.policy.version+.1);render(snapshot());}
function resolveItem(id,action){const item=popException(id);if(!item)return;if(action==="approve"&&state.spend[item.matter_id]!=null)state.spend[item.matter_id]+=item.amount||0;appendAudit({invoice_id:id,actor:"human:K. Adeyemi",event:action==="approve"?"HUMAN_APPROVED":"HUMAN_REJECTED",status:action==="approve"?"APPROVE":"REJECT",vendor:item.vendor,amount:item.amount,matter_id:item.matter_id,reasons:item.reasons,policy_version:state.policy.version});const record=state.decisions.find(d=>d.invoice_id===id);if(record)record.status=action==="approve"?"HUMAN_APPROVED":"HUMAN_REJECTED";render(snapshot());}
function rescore(){const released=[];for(const item of [...state.queue]){const record=state.decisions.find(d=>d.invoice_id===item.invoice_id);if(!record)continue;const verdict=policyCheck(record,state.policy,state.spend);if(verdict.status!=="APPROVE")continue;popException(item.invoice_id);if(state.spend[record.matter_id]!=null)state.spend[record.matter_id]+=record.amount||0;record.status="APPROVE";record.reasons=[];record.checks=verdict.checks;appendAudit({invoice_id:item.invoice_id,actor:"agent",event:"RELEASED_ON_POLICY_CHANGE",status:"APPROVE",vendor:record.vendor,amount:record.amount,matter_id:record.matter_id,confidence:record.confidence,reasons:[`policy v${state.policy.version} no longer flags this invoice`],policy_version:state.policy.version});released.push(item.invoice_id);}addLog("ok",`re-scored queue, released ${released.length}`);render(snapshot());}

$("inbox").addEventListener("click",e=>{const el=e.target.closest(".inv");if(el&&!el.classList.contains("done"))runInvoice(el.dataset.id);});
$("btnAll").onclick=()=>{resetPipe();queueJobs([...state.pending]);};
$("btnReset").onclick=()=>{resetPipe();resetState();};
$("btnDrift").onclick=()=>{state.faults.llm_degraded=!state.faults.llm_degraded;addLog(state.faults.llm_degraded?"warn":"ok",`model drift ${state.faults.llm_degraded?"INJECTED":"cleared"}`);render(snapshot());};
$("btnRedis").onclick=()=>{if(state.store.up){state.store.up=false;state.faults.redis_down=true;addLog("error","Redis unreachable - audit writes now buffering");}else{state.store.up=true;state.faults.redis_down=false;const replayed=state.buffer.length;while(state.buffer.length)doStore(...state.buffer.shift());state.store.replayed+=replayed;addLog("ok",`Redis back - replayed ${replayed} buffered write(s)`);}render(snapshot());};
$("btnRescore").onclick=rescore;
$("rules").addEventListener("click",e=>{const el=e.target.closest(".toggle");if(el)updatePolicy({rule_id:el.dataset.rule,enabled:!state.policy.rules.find(r=>r.id===el.dataset.rule).enabled});});
$("vendors").addEventListener("click",e=>{const el=e.target.closest(".vchip");if(el)updatePolicy({vendor:el.dataset.v});});
$("queue").addEventListener("click",e=>{if(e.target.dataset.ok)resolveItem(e.target.dataset.ok,"approve");if(e.target.dataset.no)resolveItem(e.target.dataset.no,"reject");});
const slider=(id,rule,param,formatter)=>{$(id).oninput=()=>setSlider(id,$(id).value,formatter(+$(id).value));$(id).onchange=()=>updatePolicy({rule_id:rule,param,value:+$(id).value});};
slider("ceil","amount_ceiling","max_auto_approve",money);slider("conf","extraction_confidence","min_confidence",v=>v.toFixed(2));slider("bud","matter_budget","utilization_ceiling",v=>Math.round(v*100)+"%");

resetState();
