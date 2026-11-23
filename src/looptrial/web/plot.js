export const colors = ["#65e4bd", "#ffbe79", "#7cb7ff", "#e2a5ed", "#f4db7d", "#7bd3e0", "#fc949c", "#b0d378"];

export function formatNumber(value, digits = 3) {
  if (!Number.isFinite(value)) return "—";
  if (value === 0) return "0";
  if (Math.abs(value) < .001 || Math.abs(value) >= 1e7) return value.toExponential(2);
  return String(Number(value.toPrecision(digits)));
}

// Retain enough decimals to distinguish adjacent ticks even on an offset axis.
export function tickLabel(value, spacing) {
  if (!(spacing > 0)) return String(value);
  const digits = Math.max(0, 1 - Math.floor(Math.log10(spacing)));
  return digits <= 14 ? String(Number(value.toFixed(digits))) : String(value);
}

function element(tag, className) {
  const el = document.createElement(tag);
  el.className = className;
  return el;
}

function nearest(rows, time) {
  let lo = 0, hi = rows.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (rows[mid].t < time) lo = mid + 1;
    else hi = mid;
  }
  if (lo === 0) return rows[0];
  if (lo === rows.length) return rows[lo - 1];
  return time - rows[lo-1].t < rows[lo].t - time ? rows[lo-1] : rows[lo];
}

// A batch can contain several device samples with one receive time. Associate the
// host event with the last sample of the nearest batch, only within observed times.
export function matchEvents(events, rows, selectedSeq) {
  const batches = [];
  for (const row of rows) {
    const ms = Date.parse(row.received_at);
    if (!Number.isFinite(ms)) continue;
    if (batches.length && batches.at(-1).ms === ms) batches.at(-1).t = row.t;
    else batches.push({ms,t:row.t});
  }
  if (!batches.length) return [];
  const result = [];
  for (const event of events) {
    const ms = Date.parse(event.time);
    if (ms < batches[0].ms || ms > batches.at(-1).ms || !Number.isFinite(ms)) continue;
    const selected = selectedSeq === String(event.seq);
    if (!selected && !["verified","restored","run_started","run_completed","run_failed","run_cancelled"].includes(event.kind)) continue;
    let best = batches[0];
    for (const batch of batches) {
      if (Math.abs(batch.ms-ms) < Math.abs(best.ms-ms)) best = batch;
      if (batch.ms >= ms) break;
    }
    result.push({t:best.t, seq:event.seq, selected});
  }
  return result;
}

export class TracePlot {
  constructor(host) {
    this.host = host;
    this.canvas = document.createElement("canvas");
    this.canvas.setAttribute("role", "img");
    this.message = element("div", "plot-message");
    this.tooltip = element("div", "probe");
    this.tooltip.hidden = true;
    host.append(this.canvas, this.message, this.tooltip);
    this.canvas.addEventListener("pointermove", (event) => {
      const bounds = this.canvas.getBoundingClientRect();
      this.pointer = {x:event.clientX - bounds.left, y:event.clientY - bounds.top};
      this.paint();
    });
    this.canvas.addEventListener("pointerleave", () => {
      this.pointer = null;
      this.paint();
    });
    new ResizeObserver(() => this.paint()).observe(host);
  }

  set(options) {
    this.options = options;
    this.paint();
  }

  paint() {
    const width = this.host.clientWidth;
    if (!this.options || !width) return;
    const {tracks, signalNames, schema, selection, labels, windowSeconds, emptyMessage, timeLabel} = this.options;
    const groups = new Map();
    for (const name of signalNames) {
      if (!selection.has(name)) continue;
      const unit = schema[name]?.unit || "1";
      if (!groups.has(unit)) groups.set(unit, []);
      groups.get(unit).push(name);
    }
    const groupList = [...groups];
    const height = Math.max(width < 510 ? 230 : 268, Math.max(1, groups.size) * 105 + 34);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const pixelsWide = Math.round(width * dpr), pixelsHigh = Math.round(height * dpr);
    if (this.canvas.width !== pixelsWide || this.canvas.height !== pixelsHigh) {
      this.canvas.width = pixelsWide;
      this.canvas.height = pixelsHigh;
      this.canvas.style.height = height + "px";
    }
    const ctx = this.canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#0e2431";
    ctx.fillRect(0, 0, width, height);
    ctx.font = "11px Consolas, monospace";
    const left = width < 480 ? 60 : 72, right = width - 16;
    const markers = this.options.markers || [];
    const top = markers.length ? 28 : 13, bottom = height - 33;
    let first = Infinity, last = -Infinity;
    for (const track of tracks) {
      if (!track.length) continue;
      first = Math.min(first, track[0].t);
      last = Math.max(last, track[track.length - 1].t);
    }
    const hasTime = Number.isFinite(first) && Number.isFinite(last);
    const end = hasTime ? last : 1;
    const start = hasTime ? (windowSeconds ? Math.max(first, end - windowSeconds) : first) : 0;
    const span = Math.max(.001, end - start);
    const x = (t) => left + (t - start) / span * (right - left);
    const count = width < 480 ? 4 : 8;
    for (let tick = 0; tick <= count; tick++) {
      const xx = left + (right - left) * tick / count;
      ctx.beginPath(); ctx.moveTo(xx, top); ctx.lineTo(xx, bottom);
      ctx.strokeStyle = "#28414c"; ctx.lineWidth = 1; ctx.stroke();
      if (hasTime) {
        ctx.fillStyle = "#9cb6be"; ctx.textAlign = tick === count ? "right" : tick === 0 ? "left" : "center";
        ctx.fillText(tickLabel(start + span * tick / count, span / count), xx, bottom + 15);
      }
    }
    const groupsToDraw = groupList.length ? groupList : [["", []]];
    const views = tracks.map((rows) => windowSeconds ? rows.filter((row) => row.t >= start) : rows);
    let hasSignal = false;
    for (const [index, [unit, keys]] of groupsToDraw.entries()) {
      const regionHeight = (bottom - top) / groupsToDraw.length;
      const yTop = top + index * regionHeight + 15, yBottom = top + (index + 1) * regionHeight - 5;
      let min = Infinity, max = -Infinity;
      for (const rows of views) for (const row of rows) for (const key of keys) {
        const value = row[key];
        if (Number.isFinite(value)) {
          min = Math.min(value, min);
          max = Math.max(value, max);
        }
      }
      const hasValues = Number.isFinite(min);
      hasSignal ||= hasValues;
      if (!hasValues) { min = 0; max = 1; }
      const pad = (max - min || Math.abs(max) || 1) * .1;
      min -= pad; max += pad;
      const y = (value) => yBottom - (value-min)/(max-min)*(yBottom-yTop);
      ctx.fillStyle = "#c8dce1"; ctx.textAlign = "left";
      ctx.fillText(unit, 6, yTop - 5);
      const ticks = groupsToDraw.length === 1 ? 4 : 2;
      for (let tick = 0; tick <= ticks; tick++) {
        const value = min + (max-min)*tick/ticks, yy = y(value);
        ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy);
        ctx.strokeStyle = "#29404d"; ctx.lineWidth = 1; ctx.stroke();
        if (hasValues) {
          ctx.fillStyle="#a3bcc4"; ctx.textAlign="right";
          ctx.fillText(tickLabel(value, (max-min)/ticks), left-6, yy+3, left-9);
        }
      }
      ctx.save();
      ctx.beginPath(); ctx.rect(left-1, yTop-2, right-left+2, yBottom-yTop+5); ctx.clip();
      for (const [trackIndex, rows] of views.entries()) {
        ctx.setLineDash(trackIndex === 0 ? [] : [6, 4]);
        ctx.lineWidth = trackIndex === 0 ? 1.8 : 2.2;
        for (const key of keys) {
          ctx.strokeStyle = colors[signalNames.indexOf(key) % colors.length];
          ctx.beginPath();
          let previous = null;
          for (const row of rows) {
            const value = row[key];
            if (!Number.isFinite(value)) { previous = null; continue; }
            const gap = previous && Number.isFinite(row.seq) && Number.isFinite(previous.seq) && row.seq !== previous.seq + 1;
            if (!previous || gap || row.t < previous.t) ctx.moveTo(x(row.t), y(value));
            else ctx.lineTo(x(row.t), y(value));
            previous = row;
          }
          ctx.stroke();
        }
      }
      ctx.restore();
    }
    this.canvas.setAttribute("aria-label", timeLabel + (hasTime ? " · " + start + "–" + end + " s · " + [...selection].join(", ") : ""));
    ctx.textAlign = "right"; ctx.fillStyle = "#9cb6be"; ctx.fillText(timeLabel, right, height-3);
    const visibleMarkers = markers.filter(m => m.t >= start && m.t <= end).sort((a,b) => a.t-b.t);
    const clusters = [];
    for (const marker of visibleMarkers) {
      const xx = x(marker.t);
      if (clusters.length && xx-clusters.at(-1).x < 46) clusters.at(-1).items.push(marker);
      else clusters.push({x:xx,items:[marker]});
    }
    this.host.dataset.markers = String(visibleMarkers.length);
    for (const cluster of clusters) {
      const chosen = cluster.items.find(m=>m.selected) || cluster.items[0];
      const xx = x(chosen.t);
      ctx.strokeStyle = chosen.selected ? "#ffda89" : "#6d8a91";
      ctx.lineWidth = chosen.selected ? 1.5 : 1;
      ctx.setLineDash([3,4]); ctx.beginPath(); ctx.moveTo(xx,21); ctx.lineTo(xx,bottom); ctx.stroke(); ctx.setLineDash([]);
      ctx.textAlign = xx+44 > right ? "right" : "left";
      ctx.fillStyle = chosen.selected ? "#ffda89" : "#b7cdd2";
      const last = cluster.items.at(-1);
      ctx.fillText("#"+chosen.seq+(!chosen.selected && last.seq!==chosen.seq ? "–"+last.seq : ""),xx,15);
    }
    this.message.textContent = emptyMessage;
    this.message.hidden = hasSignal;
    this.tooltip.hidden = true;
    if (hasSignal && this.pointer && this.pointer.x >= left && this.pointer.x <= right) {
      const {x:xx, y:yy} = this.pointer;
      const targetTime = start+(xx-left)/(right-left)*span;
      ctx.beginPath(); ctx.moveTo(xx,top); ctx.lineTo(xx,bottom); ctx.strokeStyle="#91aaab"; ctx.lineWidth=1; ctx.stroke();
      const lines = [];
      for (const [i, rows] of views.entries()) {
        const row = nearest(rows, targetTime);
        if (!row) continue;
        lines.push((labels[i] ? labels[i] + " · " : "") + formatNumber(row.t, 5) + " s");
        for (const key of selection) {
          if (Number.isFinite(row[key])) lines.push(key + "  " + formatNumber(row[key],5) + " " + (schema[key]?.unit || ""));
        }
      }
      this.tooltip.textContent = lines.join("\n");
      this.tooltip.hidden = !lines.length;
      this.tooltip.style.left = Math.min(Math.max(3,xx+10),Math.max(3,width-this.tooltip.offsetWidth-4))+"px";
      this.tooltip.style.top = Math.min(Math.max(3,yy+8),Math.max(3,height-this.tooltip.offsetHeight-4))+"px";
    }
  }
}
