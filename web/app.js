"use strict";

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

const SEED_INVOICES = [{"id":"INV-2291","file":"wexler_cole_july.pdf","text":"WEXLER & COLE LLP\n1 Battery Park Plaza, New York, NY 10004\n\n                            INVOICE\n\nInvoice No:       WC-2291\nInvoice Date:     2026-07-31\nClient Matter:    MAT-1042 / Acme Robotics v. Nordic Systems\nBilling Period:   July 2026\n\nPROFESSIONAL SERVICES\n  L120  Analysis/Strategy          6.5 hrs @ $410.00      2,665.00\n  L210  Pleadings                  2.0 hrs @ $410.00        820.00\n\nDISBURSEMENTS\n  E106  Online research                                      94.00\n\n                     TOTAL DUE (USD)                    $3,579.00\n\nPayment due within 30 days per outside counsel guidelines."},{"id":"INV-2292","file":"bramwell_hastings_q3.pdf","text":"Bramwell Hastings LLP\nStatement of Account\n\nMatter ID ......... MAT-2287\nMatter Name ....... Series C Financing\nInvoice ........... BH-88104\nDate .............. 2026-08-03\n\n  Partner   J. Bramwell     11.0 hrs   $875/hr      9,625.00\n  Associate  R. Okafor      14.5 hrs   $520/hr      7,540.00\n  Paralegal  D. Ruiz         6.0 hrs   $210/hr      1,260.00\n\n  Subtotal                                         18,425.00\n  Less negotiated discount (8%)                    -1,474.00\n\n  AMOUNT PAYABLE USD                              16,951.00"},{"id":"INV-2293","file":"ridgeline_ediscovery_aug.pdf","text":"RIDGELINE eDISCOVERY INC.\nData processing & hosting services\n\nBill To: Legal Operations\nMatter: MAT-1042\nInvoice #: RE-40219   Date: 2026-08-05\n\n  Processing, 412 GB @ $9.50/GB ................ 3,914.00\n  Hosting, 1.2 TB, monthly ....................... 480.00\n\n  TOTAL DUE: $4,394.00\n\nTerms: Net 45."},{"id":"INV-2294","file":"tanaka_ip_partners_aug.pdf","text":"TANAKA IP PARTNERS\nIntellectual Property Counsel | Tokyo * Palo Alto\n\nINVOICE TIP-7731                     Issued 2026-08-06\nMatter Reference: MAT-1042\n\n  Claim chart preparation      8.0 hrs @ $560.00     4,480.00\n  Prior art review             3.5 hrs @ $560.00     1,960.00\n  E110 Out-of-town travel (airfare, business)          2,180.00\n\n  TOTAL AMOUNT DUE (USD)                            $8,620.00"},{"id":"INV-2295","file":"orion_court_reporting.pdf","text":"ORION COURT REPORTING\nCertified transcripts and videography\n\nInvoice OCR-1188 | 2026-08-07 | Matter MAT-3310\n\n  Deposition transcript, 214 pages @ $4.15 ......... 888.10\n  Rough draft, same day ............................ 165.00\n  Videographer, 4 hrs @ $95.00 ..................... 380.00\n\n  TOTAL DUE (USD) $1,433.10"},{"id":"INV-2296","file":"vector_legal_staffing.pdf","text":"VECTOR LEGAL STAFFING\nContract attorney placement\n\nINVOICE VLS-5540\nDATE 2026-08-08\nMATTER MAT-4455 (EU Data Privacy Audit)\n\n  Contract review, 6 reviewers x 38 hrs @ $72/hr .... 16,416.00\n  Project management fee ............................. 1,800.00\n\n  TOTAL 18,216.00 USD"},{"id":"INV-2297","file":"delacroix_boone_scan.pdf","text":"DELACROIX & B00NE\n       -- scanned copy, fax quality --\n\nInvoice  DB-0 9 12          Date  2026/08/09\nMatter   MA T-  ????\n\n  Corporate governance advice     4.0 hr5   1,840.OO\n  Board minute drafting           2.5 hrs     1,150.00\n\n  T0TAL  DUE     $  2,99O.00\n\n(margin note, handwritten) confirm matter w/ K. Adeyemi"},{"id":"INV-2298","file":"wexler_cole_aug_supplemental.pdf","text":"WEXLER & COLE LLP\n\n                            INVOICE\n\nInvoice No:       WC-2314\nInvoice Date:     2026-08-10\nClient Matter:    MAT-3310 / Hollis Employment Arbitration\n\nPROFESSIONAL SERVICES\n  L390  Other discovery            3.0 hrs @ $410.00      1,230.00\n  A101  Plan and prepare (admin)   1.5 hrs @ $410.00        615.00\n  L440  Other trial preparation    2.0 hrs @ $410.00        820.00\n\n                     TOTAL DUE (USD)                    $2,665.00"},{"id":"INV-2299","file":"halcyon_trial_graphics.pdf","text":"HALCYON TRIAL GRAPHICS\nDemonstratives & courtroom presentation\n\nInvoice HTG-2077  //  2026-08-11  //  Matter MAT-1042\n\n  Animation storyboard, 3 scenes .................. 6,300.00\n  Exhibit board printing, 22 boards ............... 1,540.00\n  Rush surcharge .................................... 900.00\n\n  TOTAL DUE (USD) $8,740.00"},{"id":"INV-2300","file":"bramwell_hastings_diligence.pdf","text":"Bramwell Hastings LLP\nStatement of Account\n\nMatter ID ......... MAT-5001\nMatter Name ....... Project Ferrous / M&A Diligence\nInvoice ........... BH-88266\nDate .............. 2026-08-12\n\n  Partner   J. Bramwell      4.0 hrs   $875/hr      3,500.00\n  Associate  L. Vance        2.5 hrs   $520/hr      1,300.00\n\n  AMOUNT PAYABLE USD                                4,800.00"},{"id":"INV-2301","file":"tanaka_ip_partners_filing.pdf","text":"TANAKA IP PARTNERS\n\nINVOICE TIP-7802                     Issued 2026-08-13\nMatter Reference: MAT-1042\n\n  Office action response       2.0 hrs @ $560.00     1,120.00\n  USPTO filing fee                                      800.00\n\n  TOTAL AMOUNT DUE (USD)                            $1,920.00"},{"id":"INV-2302","file":"orion_court_reporting_2.pdf","text":"ORION COURT REPORTING\n\nInvoice OCR-1204 | 2026-08-14 | Matter MAT-3310\n\n  Deposition transcript, 96 pages @ $4.15 .......... 398.40\n  Exhibit scanning ................................. 120.00\n\n  TOTAL DUE (USD) $518.40"},{"id":"INV-2303","file":"delacroix_boone_aug.pdf","text":"DELACROIX & BOONE\nCorporate & Governance\n\nInvoice DB-0944            Date 2026-08-15\nMatter MAT-5001 / Project Ferrous\n\n  Diligence memo             9.0 hrs @ $455.00      4,095.00\n  Signing checklist          2.0 hrs @ $455.00        910.00\n\n  TOTAL DUE     $5,005.00"},{"id":"INV-2304","file":"wexler_cole_privacy.pdf","text":"WEXLER & COLE LLP\n\n                            INVOICE\n\nInvoice No:       WC-2330\nInvoice Date:     2026-08-16\nClient Matter:    MAT-4455 / EU Data Privacy Audit\n\nPROFESSIONAL SERVICES\n  L110  Fact investigation        5.0 hrs @ $410.00      2,050.00\n  L120  Analysis/Strategy         2.0 hrs @ $410.00        820.00\n\n                     TOTAL DUE (USD)                    $2,870.00"}];
const PRESEED_IDS = ["INV-2291","INV-2292","INV-2293","INV-2294","INV-2295"];
const BY_ID = Object.fromEntries(SEED_INVOICES.map(i => [i.id, i]));
const clone = value => JSON.parse(JSON.stringify(value));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const round2 = n => Math.round((n + Number.EPSILON) * 100) / 100;
const fmt = n => Number(n).toLocaleString(undefined,{minimumFractionDigits:Number.isInteger(Number(n))?0:2,maximumFractionDigits:2});


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

// --- extraction ---------------------------------------------------------------
// The live model runs behind /api/extract (a Vercel function), so the API key
// never reaches the browser. Opened as a file, or if the call fails, the
// in-browser reader above answers instead.
const LIVE = {on: false, model: null};

async function checkLive() {
  if (location.protocol === "file:") return;
  try {
    const r = await fetch("/api/extract");
    if (r.ok) { const j = await r.json(); LIVE.on = !!j.live; LIVE.model = j.model; }
  } catch (e) { /* stays offline */ }
}

function extractOffline(text, note) {
  const fields = readInvoice(text);
  if (note) fields.notes.push(note);
  return {fields, backend: "offline"};
}

async function extract(text, offline) {
  if (offline || !LIVE.on) return extractOffline(text);
  try {
    const r = await fetch("/api/extract", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({text})});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "HTTP " + r.status);
    return {fields: j.fields, backend: j.backend};
  } catch (e) {
    return extractOffline(text, `live model unavailable (${e.message}); read by the offline reader`);
  }
}

// --- state --------------------------------------------------------------------
let state, selected = null, generation = 0, jobs = Promise.resolve(), pasted = 0;
const running = new Set();

function newState() {
  const spend = {};
  for (const [id, m] of Object.entries(INITIAL_POLICY.matters)) spend[id] = m.spent_to_date;
  return {spend, records: {}, queue: [], audit: []};
}

function audit(event, record, actor) {
  state.audit.unshift({n: state.audit.length + 1, event, actor, invoice_id: record.invoice_id, amount: record.amount});
}

async function processInvoice(invoice, offline = false) {
  const token = generation;
  const {fields, backend} = await extract(invoice.text, offline);
  if (token !== generation) return;  // the page was reset while this was in flight
  const verdict = policyCheck(fields, INITIAL_POLICY, state.spend);
  const record = {invoice_id: invoice.id, ...fields, backend, status: verdict.status, checks: verdict.checks, reasons: verdict.reasons};
  state.records[invoice.id] = record;
  if (verdict.status === "APPROVE") {
    if (state.spend[fields.matter_id] != null) state.spend[fields.matter_id] += fields.amount || 0;
    audit("Auto-approved", record, "policy");
  } else {
    state.queue.unshift(invoice.id);
    audit("Sent to review", record, "policy");
  }
}

function resolve(id, approve) {
  const record = state.records[id], n = state.queue.indexOf(id);
  if (n < 0) return;
  state.queue.splice(n, 1);
  if (approve && state.spend[record.matter_id] != null) state.spend[record.matter_id] += record.amount || 0;
  record.status = approve ? "HUMAN_APPROVED" : "HUMAN_REJECTED";
  audit(approve ? "Reviewer approved" : "Reviewer rejected", record, "reviewer");
  render();
}

function run(ids) {
  for (const id of ids) running.add(id);
  render();
  jobs = jobs.then(async () => {
    for (const id of ids) {
      if (BY_ID[id] && !state.records[id]) await processInvoice(BY_ID[id]);
      running.delete(id);
      render();
    }
  });
}

async function reset() {
  generation++;
  running.clear();
  state = newState();
  for (const inv of SEED_INVOICES.filter(i => i.custom)) {
    SEED_INVOICES.splice(SEED_INVOICES.indexOf(inv), 1); delete BY_ID[inv.id];
  }
  for (const id of PRESEED_IDS) await processInvoice(BY_ID[id], true);
  selected = PRESEED_IDS[0];
  render();
}

// --- rendering ----------------------------------------------------------------
const $ = id => document.getElementById(id);
const esc = v => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const money = n => n == null ? "not found" : "$" + Number(n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
const STATUS = {
  APPROVE: ["ok", "Approved"], EXCEPTION: ["hold", "Needs review"],
  HUMAN_APPROVED: ["ok", "Approved by reviewer"], HUMAN_REJECTED: ["no", "Rejected"],
};
const badge = status => `<span class="badge ${STATUS[status][0]}">${STATUS[status][1]}</span>`;

function renderInbox() {
  $("inbox").innerHTML = SEED_INVOICES.map(inv => {
    const record = state.records[inv.id];
    const right = running.has(inv.id) ? `<span class="badge wait">Reading…</span>` : record ? badge(record.status) : `<span class="badge todo">Not run</span>`;
    return `<button class="row ${selected === inv.id ? "on" : ""}" data-id="${esc(inv.id)}">
      <span><b>${esc(inv.id)}</b><small>${esc(record && record.vendor || inv.file)}</small></span>${right}</button>`;
  }).join("");
  const left = SEED_INVOICES.filter(i => !state.records[i.id] && !running.has(i.id)).length;
  $("btnAll").disabled = !left;
  $("btnAll").textContent = left ? `Run the other ${left}` : "All done";
}

function renderDetail() {
  const invoice = BY_ID[selected], record = state.records[selected];
  if (!invoice) { $("detail").innerHTML = `<p class="empty">Pick an invoice on the left.</p>`; return; }
  const source = `<details><summary>Invoice text</summary><pre>${esc(invoice.text)}</pre></details>`;
  if (!record) {
    $("detail").innerHTML = running.has(selected)
      ? `<h3>${esc(invoice.id)}</h3><p class="empty"><span class="spin"></span>${LIVE.on ? "Gemini is reading the invoice…" : "Reading the invoice…"}</p>${source}`
      : `<h3>${esc(invoice.id)}</h3><p class="empty">This invoice has not been run yet.</p><button class="btn" id="btnRun">Run this invoice</button>${source}`;
    return;
  }
  const said = record.model_confidence;
  const lowered = said != null && said !== record.confidence ? ` <small>(the model said ${said.toFixed(2)}; lowered because a check failed)</small>` : "";
  const verdict = {
    APPROVE: "Approved automatically. Every rule passed.",
    EXCEPTION: `Sent to a person. ${record.reasons.length} rule${record.reasons.length === 1 ? "" : "s"} failed.`,
    HUMAN_APPROVED: "Approved by the reviewer.", HUMAN_REJECTED: "Rejected by the reviewer.",
  }[record.status];
  $("detail").innerHTML = `
    <div class="verdict ${STATUS[record.status][0]}"><h3>${esc(invoice.id)}</h3><p>${verdict}</p></div>
    <h4>What was read <small>by ${record.backend === "gemini" ? esc(LIVE.model) : "the offline reader"}</small></h4>
    <dl>
      <dt>Vendor</dt><dd>${esc(record.vendor || "not found")}</dd>
      <dt>Total</dt><dd>${money(record.amount)}</dd>
      <dt>Matter</dt><dd>${esc(record.matter_id || "not found")}</dd>
      <dt>Line items</dt><dd>${(record.line_items || []).length}</dd>
      <dt>Confidence</dt><dd>${Number(record.confidence).toFixed(2)}${lowered}</dd>
    </dl>
    ${(record.notes || []).length ? `<ul class="notes">${record.notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    <h4>Policy rules</h4>
    <ul class="checks">${record.checks.map(c => `<li class="${c.status}"><i></i><span><b>${esc(c.title)}</b><small>${esc(c.detail)}</small></span></li>`).join("")}</ul>
    ${source}`;
}

function renderQueue() {
  $("queueCount").textContent = state.queue.length;
  $("queue").innerHTML = state.queue.map(id => {
    const r = state.records[id];
    return `<div class="item"><div><b>${esc(id)}</b> · ${esc(r.vendor || "unknown vendor")} · ${money(r.amount)}
      <ul>${r.reasons.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>
      <div class="acts"><button class="btn sm" data-ok="${esc(id)}">Approve</button><button class="btn sm ghost" data-no="${esc(id)}">Reject</button></div></div>`;
  }).join("") || `<p class="empty">Nothing is waiting.</p>`;
}

function renderAudit() {
  $("auditCount").textContent = state.audit.length;
  $("audit").innerHTML = state.audit.map(a =>
    `<tr><td>${a.n}</td><td>${esc(a.event)}</td><td>${esc(a.invoice_id)}</td><td class="num">${money(a.amount)}</td><td>${esc(a.actor)}</td></tr>`).join("");
}

function render() {
  $("mode").textContent = LIVE.on ? `Live · ${LIVE.model}` : "Offline reader";
  $("mode").className = "chip " + (LIVE.on ? "live" : "");
  renderInbox(); renderDetail(); renderQueue(); renderAudit();
}

// --- events -------------------------------------------------------------------
$("inbox").addEventListener("click", e => {
  const row = e.target.closest(".row");
  if (row) { selected = row.dataset.id; render(); }
});
$("detail").addEventListener("click", e => { if (e.target.id === "btnRun") run([selected]); });
$("btnAll").onclick = () => run(SEED_INVOICES.filter(i => !state.records[i.id] && !running.has(i.id)).map(i => i.id));
$("btnReset").onclick = reset;
$("queue").addEventListener("click", e => {
  if (e.target.dataset.ok) resolve(e.target.dataset.ok, true);
  if (e.target.dataset.no) resolve(e.target.dataset.no, false);
});
function addInvoice(text, file) {
  const invoice = {id: `${file === "pasted text" ? "PASTED" : "UPLOAD"}-${++pasted}`, file, text, custom: true};
  SEED_INVOICES.unshift(invoice); BY_ID[invoice.id] = invoice;
  selected = invoice.id;
  run([invoice.id]);
}

$("btnPaste").onclick = () => {
  const text = $("pasteText").value.trim();
  if (!text) { $("pasteText").focus(); return; }
  $("pasteText").value = "";
  addInvoice(text, "pasted text");
};

// --- PDF upload ---------------------------------------------------------------
// The PDF is turned into text here in the browser (pdf.js), then takes the same
// path as a pasted invoice. A scan with no text layer cannot be read this way.
const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38/";
const MAX_PDF_BYTES = 5 * 1024 * 1024, MAX_CHARS = 8000;

// Rebuild lines from positioned text runs: same baseline = same line, and a
// horizontal gap becomes spaces so amounts stay in their own column.
function linesFrom(items) {
  const runs = items.filter(i => i.str.trim()).map(i => ({text: i.str, x: i.transform[4], y: i.transform[5], w: i.width}));
  runs.sort((a, b) => b.y - a.y || a.x - b.x);
  const lines = [];
  for (const run of runs) {
    const line = lines[lines.length - 1];
    if (line && Math.abs(line.y - run.y) < 3) line.runs.push(run); else lines.push({y: run.y, runs: [run]});
  }
  return lines.map(line => {
    let out = "", end = null;
    for (const run of line.runs.sort((a, b) => a.x - b.x)) {
      const charWidth = run.w / run.text.length || 6;
      if (end != null) out += " ".repeat(Math.max(1, Math.round((run.x - end) / charWidth)));
      out += run.text; end = run.x + run.w;
    }
    return out;
  });
}

async function pdfToText(file) {
  const pdfjs = await import(PDFJS + "pdf.min.mjs");
  pdfjs.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.mjs";
  const pdf = await pdfjs.getDocument({data: await file.arrayBuffer()}).promise;
  const lines = [];
  for (let n = 1; n <= pdf.numPages; n++) lines.push(...linesFrom((await (await pdf.getPage(n)).getTextContent()).items));
  return lines.join("\n").trim();
}

$("pdfFile").onchange = async e => {
  const file = e.target.files[0], note = $("pdfNote");
  e.target.value = "";
  if (!file) return;
  if (file.size > MAX_PDF_BYTES) { note.textContent = "That PDF is over 5 MB."; return; }
  note.textContent = "Reading the PDF…";
  try {
    const text = await pdfToText(file);
    if (!text) { note.textContent = "No text found. Scanned PDFs without a text layer are not supported."; return; }
    if (text.length > MAX_CHARS) { note.textContent = "That PDF has too much text for one invoice (8,000 characters max)."; return; }
    note.textContent = "";
    addInvoice(text, file.name);
  } catch (err) {
    note.textContent = "That file could not be read as a PDF.";
  }
};

reset().then(checkLive).then(render);
