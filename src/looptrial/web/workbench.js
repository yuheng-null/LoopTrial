import { TracePlot, colors, formatNumber } from "./plot.js";
import { tr, lang, localize, switchLanguage } from "./i18n.js";

const $ = id => document.getElementById(id);
const livePlot = new TracePlot($("live-plot"));
const overlayPlot = new TracePlot($("compare-plot"));
let snap = {};
let appliedSession = null;
let liveSignals = [], liveSelection = new Set();
let overlay = null, overlaySignals = [], overlaySelection = new Set();
let frozenRows = null;
let pendingWrite = false, pendingConnect = false, pendingRun = false, pendingStop = false;
let refreshing = false, serviceLost = false, knownRecords = [], latestRun = "", overlayEpoch = 0;
let recordSignature = "", eventSignature = "", eventContainerSession = null;
let view = "live";

const controlsToggle = document.createElement("button");
controlsToggle.type = "button";
controlsToggle.className = "mobile-controls";
document.querySelector(".rail").append(controlsToggle);
controlsToggle.addEventListener("click", () => {
  document.querySelector(".rail").classList.toggle("open");
  updateControlsToggle();
});

function node(tag, value, className) {
  const item = document.createElement(tag);
  if (value !== undefined && value !== null) item.textContent = value;
  if (className) item.className = className;
  return item;
}
function option(value, text) { const el = node("option", text); el.value = value; return el; }

function showError(error) {
  const el = $("alert");
  el.firstElementChild.textContent = error.message || String(error);
  el.hidden = false;
}
function clearError() { $("alert").hidden = true; }
$("dismiss").addEventListener("click", clearError);

async function api(operation, params = {}) {
  const response = await fetch("./api/" + operation, {
    method:"POST", headers:{"Content-Type":"application/json","X-LoopTrial":"1"},
    body:JSON.stringify(params), cache:"no-store", credentials:"same-origin"
  });
  let data;
  try { data = await response.json(); }
  catch { throw Error(tr("requestFailed") + " · HTTP " + response.status); }
  if (!response.ok || data?.ok === false) {
    const reason = data?.error || data || {};
    throw Error([reason.code,reason.message || response.statusText || tr("requestFailed")].filter(Boolean).join(" · "));
  }
  return data;
}

function stamp(raw) {
  if (raw === null || raw === undefined || raw === "") return "—";
  const date = new Date(typeof raw === "number" && raw < 1e12 ? raw*1000 : raw);
  if (!Number.isFinite(date.getTime())) return String(raw);
  return date.toLocaleTimeString(lang()==="zh"?"zh-CN":"en-GB", {hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
}
function displayNumber(value, digits = 6) { return Number.isFinite(value) ? formatNumber(value,digits) : "—"; }

function updateControlsToggle() {
  const on = document.querySelector(".rail").classList.contains("open");
  controlsToggle.textContent = tr(on ? "hideControls" : "controls");
  controlsToggle.setAttribute("aria-expanded", String(on));
}

async function scan() {
  const devices = await api("devices");
  const candidates = [...(devices.simulated || []), ...(devices.serial_candidates || [])];
  if (devices.ble) candidates.push(String(devices.ble).split(" ")[0]);
  if (Array.isArray(devices.race)) candidates.push(...devices.race);
  if (typeof devices.race === "string") candidates.push(devices.race);
  $("devices").replaceChildren(...[...new Set(candidates)].map(uri=>{
    const button=node("button",uri); button.type="button";
    button.addEventListener("click",()=>{ $("device-uri").value=uri; closePicker(); $("connect").focus(); });
    return button;
  }));
}

function closePicker() { $("devices").hidden=true; $("choose-device").setAttribute("aria-expanded","false"); }
$("choose-device").addEventListener("click",()=>{
  const open=$("devices").hidden; $("devices").hidden=!open; $("choose-device").setAttribute("aria-expanded",String(open));
  if(open) $("devices").querySelector("button")?.focus();
});
document.addEventListener("click",event=>{if(!event.target.closest(".endpoint"))closePicker();});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("devices").hidden){closePicker();$("choose-device").focus();}});
function liveSchema(){return snap.info?.telemetry?.signals || snap.info?.signals || {};}
function deriveSignals(schema, rows) {
  const metadata = new Set(["seq", "t", "host_t", "host_time", "received_at", "received_ns", "received", "device_ms"]);
  const keys = Object.keys(schema);
  return (keys.length ? keys : Object.keys(rows.at(-1) || {})).filter(k=> !metadata.has(k));
}
function initialSelection(keys) {
  if (keys.includes("raw") && keys.includes("filtered")) return new Set(["raw","filtered"]);
  return new Set(keys.slice(0, Math.min(3, keys.length)));
}
function renderChips(target, keys, selected, schema, redraw) {
  const fragment = document.createDocumentFragment();
  for (const [i, key] of keys.entries()) {
    const unit = schema[key]?.unit;
    const button = node("button", key + (unit ? " · "+unit : ""), "signal-chip");
    button.type = "button";
    button.title = schema[key]?.description || key;
    button.style.setProperty("--chip-color",colors[i % colors.length]);
    button.setAttribute("aria-pressed",String(selected.has(key)));
    button.addEventListener("click",()=> {
      if (selected.has(key)) selected.delete(key);
      else selected.add(key);
      button.setAttribute("aria-pressed",String(selected.has(key)));
      redraw();
    });
    fragment.append(button);
  }
  target.replaceChildren(fragment);
}

function drawLive() {
  const schema = liveSchema();
  const rows = frozenRows || snap.stream || [];
  const msg = !snap.uri ? "disconnectedPlot" : liveSignals.length && !liveSelection.size ? "chooseSignals" :
        snap.state === "unknown" || serviceLost ? "unknown" : !snap.uri.startsWith("sim://") && !snap.info?.telemetry ? "noPreview" : "waiting";
  livePlot.set({tracks:[rows], signalNames:liveSignals, schema, selection:liveSelection,
    labels:[""], windowSeconds:Number($("window").value), emptyMessage:tr(msg), timeLabel:tr("measured")});
}
function drawOverlay() {
  overlayPlot.set({tracks:overlay?.tracks || [], signalNames:overlaySignals, schema:overlay?.schema || {},
    selection:overlaySelection, labels:[tr("baseline"),tr("candidate")], windowSeconds:0,
    emptyMessage:tr(overlay && !overlaySelection.size ? "chooseSignals" : "noOverlay"), timeLabel:tr("relative")});
}

function makeField(key, spec, value, prefix, includeEffective) {
  const wrapper = node("div",null,"form-field");
  const head = node("div",null,"field-head");
  const label = node("label", key);
  const input = document.createElement("input");
  input.type = "number";
  input.name = key;
  input.id = prefix + "-" + key;
  label.htmlFor = input.id;
  input.required = true;
  input.step = ["integer","int"].includes(spec.type) ? "1":"any";
  if (Number.isFinite(spec.min)) input.min = spec.min;
  if (Number.isFinite(spec.max)) input.max = spec.max;
  if (Number.isFinite(value)) input.value = value;
  input.title = spec.description || key;
  head.append(label);
  const line = node("div",null,"value-line");
  line.append(input);
  if (spec.unit) line.append(node("span",spec.unit));
  if (includeEffective) {
    const actual = node("small");
    actual.className = "actual";
    head.append(actual);
    input.dataset.dirty = "false";
    input.addEventListener("input",()=>{
      input.dataset.dirty = "true";
      syncControls();
    });
  }
  wrapper.append(head,line);
  return wrapper;
}
function buildParameters() {
  const values = snap.values || snap.last_confirmed?.values || {};
  const entries = Object.entries(snap.info?.parameters || {});
  $("params").replaceChildren(...entries.map(([key,spec])=>makeField(key,spec,values[key],"param",true)));
  $("params-empty").textContent = entries.length ? "" : tr(snap.uri ? "readOnly":"noParams");
  $("params-empty").hidden = entries.length > 0;
  $("apply").hidden = !entries.length;
}
function buildActions() {
  const select = $("action");
  const prior = select.value;
  const actions = Object.keys(snap.info?.actions || {});
  select.replaceChildren(...(actions.length ? actions.map(a=>option(a,a)) : [option("",tr("noAction"))]));
  if (actions.includes(prior)) select.value = prior;
  buildConditions();
}
function buildConditions() {
  const action = snap.info?.actions?.[$("action").value];
  $("action").title = action?.description || "";
  const entries = Object.entries(action?.conditions || {});
  $("fields").replaceChildren(...entries.map(([key,spec])=>makeField(key,spec,spec.default,"condition",false)));
  $("conditions").hidden = !entries.length;
}

function syncControls() {
  const connected = !!snap.connected && !serviceLost;
  const verified = connected && snap.state === "verified";
  const values = snap.values || snap.last_confirmed?.values || {};
  let changed = false;
  for (const input of $("params").querySelectorAll("input")) {
    const value = values[input.name];
    if (input.dataset.dirty !== "true" && Number.isFinite(value)) input.value = value;
    if (input.dataset.dirty === "true" && Number.isFinite(input.valueAsNumber) && input.valueAsNumber !== value) changed = true;
    input.disabled = pendingWrite || !verified;
    input.closest(".form-field").querySelector(".actual").textContent =
      tr(verified ? "value":"stale") + " " + displayNumber(value);
  }
  $("params-state").textContent = snap.uri ? tr(verified ? "verified" : "unknown") : "";
  $("confirmed-at").textContent = snap.last_confirmed?.time ? tr("lastConfirmed")+" · "+stamp(snap.last_confirmed.time) : "";
  $("apply").disabled = !verified || pendingWrite || !changed;
  $("action").disabled = !verified || !Object.keys(snap.info?.actions || {}).length;
  $("run").disabled = $("action").disabled || pendingRun || !!snap.active_run;
  $("stop").disabled = !snap.active_run || pendingStop || serviceLost;
  $("connect").disabled = pendingConnect;
  $("connect").textContent = tr(pendingConnect ? "connecting" : snap.uri && !connected ? "reconnect":"connect");
  $("disconnect").hidden = !snap.uri;
  $("disconnect").disabled = pendingConnect || serviceLost;
  $("freeze").textContent = tr(frozenRows ? "resume" : "freeze");
  $("freeze").disabled = !(snap.stream?.length || frozenRows);
  $("active-run").textContent = snap.active_run ? tr(pendingStop ? "stopping":"running") + " · " + snap.active_run :
    latestRun ? tr("runId")+" · "+latestRun : "";
  const badge = $("connection-badge");
  const warn = serviceLost || !!snap.uri && !verified;
  badge.className = "badge" + (warn ? " warn" : verified ? " on" : "");
  badge.lastElementChild.textContent = tr(serviceLost ? "serviceLost" : warn ? "unknown" : verified ? "online" : "offline");
  document.body.classList.toggle("connected",connected);
}
function displayStats() {
  const stats = snap.stats || {};
  for (const [id,key,unit] of [["sample-rate","sample_hz","Hz"],["update-rate","update_hz","Hz"],["missing","missing",""],["sample-age","age_s","s"]]) {
    const value = stats[key];
    const el = $(id);
    el.textContent = !serviceLost && Number.isFinite(value) ? formatNumber(value) : "—";
    if (!serviceLost && Number.isFinite(value) && unit) el.append(node("small",unit));
  }
}

function eventName(kind) {
  const translations = {
    sent:["Command sent","命令已发送"], write_sent:["Parameter write sent","参数指令已发送"], applied:["Device applied","设备已生效"],
    write_applied:["Device applied parameters","设备参数已生效"], verified:["Readback confirmed","独立回读已确认"],
    write_verified:["Parameter readback confirmed","参数回读已确认"], connected:["Device connected","已连接设备"],
    disconnected:["Device disconnected","设备已断开"], unknown:["Device state unknown","设备状态未知"],
    restored:["Previous settings restored","原配置已恢复"], run_started:["Trial started","实验已开始"], run_completed:["Trial completed","实验完成"],
    run_cancelled:["Trial cancelled","实验已取消"], run_failed:["Trial failed","实验失败"],
    cancel_requested:["Cancellation requested","已请求取消"], reconnected:["Device reconnected","设备已重连"]
  };
  return translations[kind]?.[lang()==="zh"?1:0] || String(kind || "?").replaceAll("_"," ");
}
function renderTimeline(force = false) {
  const events = snap.events || [];
  const signature = JSON.stringify([events.length,events.at(-1),events[0],lang()]);
  if (!force && signature === eventSignature && eventContainerSession === snap.session_id) return;
  const open = new Set(eventContainerSession === snap.session_id ?
    [...$("events").querySelectorAll("details[open]")].map(el=>el.dataset.seq) : []);
  eventContainerSession = snap.session_id;
  eventSignature = signature;
  const ordered = [...events].sort((a,b)=>b.seq-a.seq);
  const fragment = document.createDocumentFragment();
  for (const event of ordered.slice(0,100)) {
    const li=node("li"), details=node("details"), summary=node("summary");
    details.dataset.seq = String(event.seq);
    details.open = open.has(String(event.seq));
    const actor = String(event.actor || "system");
    const extra = event.details || {};
    const values = extra.values || extra.verified || extra.requested;
    const context = values && typeof values==="object" ?
      Object.entries(values).slice(0,4).map(([k,v])=>k+"="+v).join(" · ") :
      (extra.run_id || extra.id || extra.message || "");
    summary.append(node("time",stamp(event.time)),node("span",actor,"actor"),
      node("span",eventName(event.kind)+(context ? " · "+String(context) : ""),"event-text"));
    details.append(summary,node("pre",JSON.stringify(event,null,2)));
    li.append(details); fragment.append(li);
  }
  $("events").replaceChildren(fragment);
  $("event-count").textContent = events.length ? events.length+" "+tr(events.length===1?"event":"events") : "";
  $("events-empty").textContent = tr("noEvents");
  $("events-empty").hidden = !!events.length;
}
function applySnapshot(data,force = false) {
  const prev = snap, token = (data.session_id||"") + "|" + (data.uri||"") + "|" + (data.info?.id||"");
  const same = appliedSession === token;
  snap = data;
  if (!same) {
    appliedSession = token;
    frozenRows = null; latestRun = ""; eventSignature="";
    if (snap.uri) $("device-uri").value = snap.uri;
  }
  const signals = deriveSignals(liveSchema(), snap.stream || []);
  if (!same || JSON.stringify(signals) !== JSON.stringify(liveSignals)) {
    liveSignals = signals;
    liveSelection = initialSelection(signals);
    renderChips($("signals"),liveSignals,liveSelection,liveSchema(),drawLive);
  }
  if (!same || force) {
    buildParameters(); buildActions();
    $("device-detail").textContent = [snap.info?.source,snap.info?.version].filter(Boolean).join("  /  ");
    $("device-detail").hidden = !snap.info;
  }
  if (prev.active_run && !snap.active_run && same) { latestRun = prev.active_run; if (view==="compare") refreshRuns().catch(showError); }
  $("device-caption").textContent = snap.uri || tr("noDevice");
  syncControls(); displayStats(); renderTimeline(force); drawLive();
}
async function refresh() {
  if (refreshing || pendingConnect) return;
  refreshing = true;
  try {
    const current = appliedSession;
    const data = await api("snapshot");
    if (!pendingConnect && current === appliedSession) {
      serviceLost = false;
      applySnapshot(data);
      if (data.error && data.error!==refresh.lastError) showError(Error(String(data.error)));
      refresh.lastError = data.error;
    }
  } catch {
    serviceLost = true; syncControls(); displayStats(); drawLive();
  } finally { refreshing = false; }
}

$("connect-form").addEventListener("submit",async event=>{
  event.preventDefault(); clearError();
  const uri=$("device-uri").value.trim();
  if (!uri || pendingConnect) return;
  pendingConnect=true; syncControls();
  try { applySnapshot(await api("connect",{uri})); serviceLost=false; }
  catch(error) { showError(error); }
  finally { pendingConnect=false; syncControls(); await refresh(); }
});
$("disconnect").addEventListener("click",async()=>{
  clearError(); pendingConnect=true; syncControls();
  try { applySnapshot(await api("disconnect")); }
  catch(error) {showError(error);}
  finally {pendingConnect=false; syncControls(); await refresh();}
});
$("scan").addEventListener("click",()=>scan().catch(showError));
$("action").addEventListener("change",buildConditions);
$("param-form").addEventListener("submit",async event=>{
  event.preventDefault(); clearError();
  const values = {};
  for(const input of $("params").querySelectorAll("input")) {
    if (input.dataset.dirty==="true" && Number.isFinite(input.valueAsNumber) && input.valueAsNumber!==snap.values?.[input.name]) values[input.name]=input.valueAsNumber;
  }
  if (!Object.keys(values).length) return;
  pendingWrite=true; syncControls();
  try {
    await api("apply_parameters",{uri:snap.uri,values});
    for(const input of $("params").querySelectorAll("input")) input.dataset.dirty="false";
    applySnapshot(await api("snapshot"));
  } catch(error) {showError(error);}
  finally {pendingWrite=false; syncControls();}
});
$("run-form").addEventListener("submit",async event=>{
  event.preventDefault(); clearError();
  const conditions={};
  for(const input of $("fields").querySelectorAll("input")) if(Number.isFinite(input.valueAsNumber)) conditions[input.name]=input.valueAsNumber;
  pendingRun=true; syncControls();
  try {
    const result=await api("run_experiment",{uri:snap.uri,action:$("action").value,conditions,background:true});
    latestRun=result.id; applySnapshot(await api("snapshot"));
    if(view==="compare") await refreshRuns();
  } catch(error) {showError(error);}
  finally {pendingRun=false; syncControls();}
});
$("stop").addEventListener("click",async()=>{
  const id=snap.active_run;
  if(!id) return;
  clearError(); pendingStop=true; syncControls();
  try {await api("cancel_run",{run_id:id}); applySnapshot(await api("snapshot"));}
  catch(error) {showError(error);}
  finally {pendingStop=false; syncControls();}
});
$("window").addEventListener("change",drawLive);
$("freeze").addEventListener("click",()=>{
  frozenRows = frozenRows ? null : (snap.stream || []).slice();
  syncControls(); drawLive();
});

async function refreshRuns(force=false) {
  const runs=await api("list_runs",{limit:80});
  knownRecords = runs.filter(run=>run.status==="completed");
  const signature=JSON.stringify(knownRecords.map(r=>r.id));
  if(!force && signature===recordSignature) return;
  recordSignature=signature;
  const previous=[$("baseline").value,$("candidate").value];
  for(const [index,id] of ["baseline","candidate"].entries()) {
    const select=$(id);
    select.replaceChildren(option("",tr(knownRecords.length?"chooseRun":"incomplete")),...knownRecords.map(r=>{
      const label=[r.id.slice(0,8),r.source,r.action].filter(Boolean).join(" · ");
      const o=option(r.id,label); o.title=r.id; return o;
    }));
    if(knownRecords.some(r=>r.id===previous[index])) select.value=previous[index];
    else if(knownRecords.length>=2) select.value=knownRecords[index===0?1:0].id;
  }
  $("compare-button").disabled=knownRecords.length<2;
  if(knownRecords.length<2) $("compare-note").textContent=tr("emptyRuns");
  else if(!overlay) $("compare-note").textContent="";
}
function resetOverlay() {
  overlayEpoch++;
  overlay=null; overlaySignals=[]; overlaySelection=new Set();
  $("overlay-signals").replaceChildren();
  $("metrics-block").hidden=true; $("overlay-legend").hidden=true;
  $("overlay-count").textContent=""; $("compare-note").textContent="";
  drawOverlay();
}
function showOverlay() {
  if(!overlay){drawOverlay();return;}
  renderChips($("overlay-signals"),overlaySignals,overlaySelection,overlay.schema,drawOverlay);
  $("overlay-legend").hidden=false; $("metrics-block").hidden=false;
  $("overlay-count").textContent=overlay.counts.join(" / ")+" "+tr("points");
  const [a,b]=overlay.records;
  const body=$("metrics"); body.replaceChildren();
  for(const [key,delta] of Object.entries(overlay.comparison.delta || {})){
    const row=node("tr"), unit=b.metric_units?.[key] || a.metric_units?.[key] || "";
    row.append(node("td",key+(unit?" ("+unit+")":"")),node("td",displayNumber(a.metrics?.[key])),node("td",displayNumber(b.metrics?.[key])),
      node("td",(delta>0?"+":"")+displayNumber(delta)));
    body.append(row);
  }
  drawOverlay();
}
for(const id of ["baseline","candidate"]) $(id).addEventListener("change",resetOverlay);
$("compare-form").addEventListener("submit",async event=>{
  event.preventDefault(); resetOverlay(); clearError();
  const first=$("baseline").value, second=$("candidate").value;
  if(first===second){$("compare-note").textContent=tr("different");return;}
  const epoch=overlayEpoch;
  $("compare-button").disabled=true;
  try {
    const comparison=await api("compare",{first,second});
    const [ta,tb,a,b]=await Promise.all([
      api("plot_trace",{run_id:first}),api("plot_trace",{run_id:second}),api("get_run",{run_id:first}),api("get_run",{run_id:second})]);
    if(epoch!==overlayEpoch) return;
    const schema=ta.signals && !Array.isArray(ta.signals) ? ta.signals : a.signals || {};
    overlay={tracks:[ta.rows,tb.rows],schema,comparison,records:[a,b],counts:[ta.total,tb.total]};
    const keys=deriveSignals(schema,ta.rows);
    overlaySignals=keys.filter(k=>ta.rows.some(r=>Number.isFinite(r[k]))&&tb.rows.some(r=>Number.isFinite(r[k])));
    overlaySelection=initialSelection(overlaySignals);
    showOverlay();
  } catch(error) { if(epoch===overlayEpoch) $("compare-note").textContent=error.message; }
  finally {$("compare-button").disabled=knownRecords.length<2;}
});
$("refresh-runs").addEventListener("click",()=>refreshRuns(true).catch(showError));

function navigate() {
  view=location.hash==="#compare"?"compare":"live";
  for(const key of ["live","compare"]) {
    $(key+"-panel").hidden=key!==view;
    if(key===view) $(key+"-tab").setAttribute("aria-current","page"); else $(key+"-tab").removeAttribute("aria-current");
  }
  if(view==="compare"){refreshRuns().catch(showError);drawOverlay();}
  else drawLive();
}
$("language").addEventListener("click",()=>{
  switchLanguage(); localize(); updateControlsToggle();
  applySnapshot(snap,true); showOverlay();
  if(view==="compare") refreshRuns(true).catch(showError);
});
window.addEventListener("hashchange",navigate);
localize(); updateControlsToggle(); applySnapshot({}); navigate();
scan().catch(showError); refresh();
setInterval(refresh,450);
setInterval(()=>{if(view==="compare" && !document.hidden)refreshRuns().catch(showError);},4000);
