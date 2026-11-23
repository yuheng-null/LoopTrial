// 噪声模型 (仿真替身, 非固件移植) — 模拟真实环境的传感器噪声。
// 纯函数, 可 Node 单测。图像噪声用于检验 Core 二值化滤波 + 扫线的抗噪能力。

// 可复现 PRNG (mulberry32) — 固定种子调试用; 仿真默认可用 Math.random。
export function makeRng(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// 标准正态分布 (Box-Muller)
export function gaussian(rng) {
  let u = 0, v = 0;
  while (u === 0) u = rng();
  while (v === 0) v = rng();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

// 图像加噪 (就地修改行主序灰度 gray, w×h):
//   - sigma:   每像素高斯噪声标准差 (灰度值)
//   - lightAmp: 光照不均幅度 (0~1); 竖直渐变增益 [1-amp, 1+amp] (顶暗底亮)
export function applyImageNoise(gray, w, h, params, rng) {
  const sigma = params.sigma || 0;
  const lightAmp = params.lightAmp || 0;
  if (sigma <= 0 && lightAmp <= 0) return gray;
  const denom = h > 1 ? (h - 1) : 1;
  for (let y = 0; y < h; y++) {
    const gain = lightAmp > 0 ? (1 - lightAmp + 2 * lightAmp * (y / denom)) : 1;
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      let val = gray[i] * gain;
      if (sigma > 0) val += gaussian(rng) * sigma;
      val = val < 0 ? 0 : (val > 255 ? 255 : val);
      gray[i] = val | 0;
    }
  }
  return gray;
}
