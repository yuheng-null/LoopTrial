const strings = {
  devices:["Discovered devices","已发现设备"],
  sameParams:["Parameters match","两轮生效参数一致"], changedParams:["Parameter changes","生效参数变化"], racePreview:["Start a trial to see the vehicle signals","开始整车试跑后将显示车辆信号"],
  alignment:["Event markers use the nearest host-received batch. The horizontal axis shows device time.","事件标记对齐到主机收包时间最接近的一批样本，横轴为设备时间。"],
  workbench: ["Workbench", "调参工作台"], deviceControls:["Device controls","设备控制"], view:["View","视图"], dismiss:["Dismiss","关闭提示"],
  connection:["Connection","设备连接"], refresh:["Refresh","刷新"], deviceUri:["Device URI","设备 URI"], connect:["Connect","连接设备"], reconnect:["Reconnect","重新连接"], connecting:["Connecting…","连接中…"], disconnect:["Disconnect","断开"],
  parameters:["Parameters","参数"], apply:["Apply changes","应用修改"], experiment:["Experiment","实验"], action:["Action","实验动作"], conditions:["Trial conditions","实验工况"], run:["Run trial","开始实验"], stop:["Stop","停止"],
  monitor:["Live monitor","实时监测"], compare:["Run comparison","实验对比"], liveHeading:["Signal monitor","信号监测"], waveform:["Waveform","实时波形"], window:["Window","时间窗"],
  livePlot:["Live waveform","实时波形"], sampleRate:["Device sample rate","设备采样率"], updateRate:["Host update rate","主机更新率"], missing:["Missing samples","缺失样本"], sampleAge:["Last update age","距上次更新"],
  compareHeading:["Compare runs","实验对比"], compareHint:["Compare completed trials under matching conditions.","叠加相同工况下的两次完整实验。"], baseline:["Baseline","基线"], candidate:["Candidate","候选"], overlay:["Overlay","叠加比较"],
  overlayTitle:["Trace overlay","波形叠加"], metrics:["Metric changes","指标变化"], metric:["Metric","指标"], change:["Change","差值"],
  timeline:["Session timeline","会话时间轴"], offline:["Disconnected","未连接"], online:["Connected","已连接"], unknown:["State unknown","状态未知"], serviceLost:["Workbench unavailable","服务不可用"],
  verified:["Verified","已回读"], lastConfirmed:["Last confirmed","上次确认"], waiting:["Awaiting samples","等待设备采样"], chooseSignals:["Select a signal to plot","选择要显示的信号"],
  disconnectedPlot:["Connect a device to view its signals","连接设备后显示实时波形"], noEvents:["Session events appear here after connection.","连接后可在此查看会话事件。"],
  noParams:["Connect to inspect effective parameters.","连接设备以查看生效参数。"], readOnly:["This device exposes no writable parameters.","该设备未声明可写参数。"],
  noDevice:["No device selected","尚未连接设备"], chooseAction:["Select an action","选择实验动作"], chooseRun:["Select a run","选择实验记录"],
  noAction:["No declared action","无可用实验动作"], noConditions:["No configurable conditions.","此实验无可调工况。"],
  freeze:["Freeze view","冻结画面"], resume:["Resume view","恢复显示"], value:["Confirmed","回读值"], stale:["Last known","上次确认值"],
  filtered:["Limited display","显示抽样"], noOverlay:["Choose two runs to overlay their signals","选择两份实验记录以叠加波形"], emptyRuns:["There are fewer than two completed runs.","至少需要两次已完成的实验。"],
  different:["Select two different run IDs.","请选择两个不同的实验编号。"], controls:["Parameters & experiment","参数与实验"], hideControls:["Collapse controls","收起控制面板"],
  session:["Session","会话"], runId:["Run","实验"], stopping:["Cancellation requested","已请求取消"], requestFailed:["Request failed","请求失败"], points:["samples","点"],
  temporary:["Temporary configuration","临时参数"], event:["event","事件"], events:["events","事件"], noPreview:["Live preview unavailable for this device","此设备没有实时预览"], selectCompare:["Select two runs","选择两份实验记录"],
  incomplete:["No completed records","无已完成记录"], output:["Result","结果"], pending:["Pending","待确认"], noChange:["Effective values already match.","参数已经生效。"], secondsAgo:["s ago","秒前"],
  changed:["changed","已变更"], idle:["Idle","空闲"], running:["Running","进行中"], applied:["Applied","已生效"], sent:["Sent","已发送"], failed:["Failed","失败"],
  measured:["Device time (s)","设备时间 (s)"], relative:["Trial time (s)","实验时间 (s)"], service:["Workbench","工作台"], human:["Operator","操作员"]
};
let language;
try { language = localStorage.getItem("looptrial.language"); } catch {}
if (language !== "en" && language !== "zh") language = navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
export const lang = () => language;
export function tr(key) { return strings[key]?.[language === "zh" ? 1 : 0] || key; }
export function switchLanguage() {
  language = language === "zh" ? "en" : "zh";
  try { localStorage.setItem("looptrial.language", language); } catch {}
}
export function localize() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  document.title = "LoopTrial · " + tr("workbench");
  for (const el of document.querySelectorAll("[data-i]")) el.textContent = tr(el.dataset.i);
  for (const el of document.querySelectorAll("[data-ia]")) el.setAttribute("aria-label", tr(el.dataset.ia));
  document.getElementById("language").textContent = language === "zh" ? "English" : "中文";
}
