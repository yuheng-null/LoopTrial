// SPDX-License-Identifier: GPL-3.0-or-later
// Image-track plane, camera readback, cascaded controller and odometry adapted from
// leitingzhiche/index.html (MIT, upstream/LICENSE). This course is drawn here.
import {createPlant} from "./upstream/plant.js";
import {createVisionState, runVision} from "./upstream/vision.js";
import {createController} from "./upstream/control.js";
import {defaultCameraParams, defaultControlParams} from "./upstream/params.js";
import {makeRng} from "./upstream/noise.js";

const W = 188, H = 120, DT = 0.01;

function imageTrack(radius, halfStraight) {
  const scale = 48, span = 2 * (radius + halfStraight + 7);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = Math.ceil(span * scale);
  const pen = canvas.getContext("2d");
  pen.fillStyle = "#061a3a";
  pen.fillRect(0, 0, canvas.width, canvas.height);
  pen.translate(canvas.width / 2, canvas.height / 2);
  pen.scale(canvas.width / span, canvas.height / span);
  pen.strokeStyle = "#ffffff";
  pen.lineWidth = 0.65;
  pen.beginPath();
  pen.moveTo(-radius, halfStraight);
  pen.lineTo(-radius, -halfStraight);
  pen.arc(0, -halfStraight, radius, Math.PI, 2 * Math.PI);
  pen.lineTo(radius, halfStraight);
  pen.arc(0, halfStraight, radius, 0, Math.PI);
  pen.closePath();
  pen.stroke();
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(span, span),
    new THREE.MeshStandardMaterial({map: new THREE.CanvasTexture(canvas), roughness: 0.85}));
  mesh.rotation.x = -Math.PI / 2;
  return mesh;
}

function makeCamera(course) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#061a3a");
  scene.add(imageTrack(course.radius, course.half_straight));
  scene.add(new THREE.AmbientLight(0xffffff, 1.15));
  const car = new THREE.Group();
  scene.add(car);
  const vfov = 2 * Math.atan(Math.tan(Math.PI / 3) / (W / H)) * 180 / Math.PI;
  const camera = new THREE.PerspectiveCamera(vfov, W / H, 0.05, 250);
  car.add(camera);
  camera.position.set(0, 2.7, -3);
  camera.rotation.x = -55 * Math.PI / 180;
  const renderer = new THREE.WebGLRenderer({antialias:false});
  renderer.setSize(W,H);
  const target = new THREE.WebGLRenderTarget(W, H, {format: THREE.RGBAFormat, type: THREE.UnsignedByteType});
  const rgba = new Uint8Array(W * H * 4);
  const gray = new Uint8Array(W * H);
  return (x,z,yaw) => {
    car.position.set(x,0,z);
    car.rotation.y = yaw;
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.readRenderTargetPixels(target, 0, 0, W, H, rgba);
    for (let y=0; y<H; y++) {
      for (let x=0; x<W; x++) {
        const p = (y*W + W-1-x)*4;
        gray[y*W+x] = (rgba[p]+rgba[p+1]+rgba[p+2])/3;
      }
    }
    return gray;
  };
}

function vehicle({course, settings, conditions}) {
  const camera = makeCamera(course);
  const cpu = defaultControlParams();
  cpu.MAX_PWM_DUTY = 10000;
  Object.assign(cpu.steer, {kp:settings.steer_gain, kp2:0, kd:0});
  Object.assign(cpu.omega, {kp:1.3, ki:0});
  for (const motor of [cpu.motorL, cpu.motorR]) Object.assign(motor, {kp:18, ki:2.15});
  Object.assign(cpu.diff, {kw_ff:0.29, acc_ff_l:0.77, acc_ff_r:0.77, base_speed:settings.drive_speed});
  cpu.maxDeltaWPerMs = 2.5;
  const ctrl = createController(cpu);
  const plant = createPlant({vMaxEnc:360, motorDt:0.001, pwmDelaySteps:1, loadTorque:10,
    staticFriction:60, coulombFriction:30, gyroNoiseSigma:0.8});
  plant.rng = makeRng(conditions.seed);
  const filters = defaultCameraParams();
  const vision = createVisionState();
  let x = -course.radius, z = 0, yaw = 0, traveled = 0, yawAccum = 0, tick = 0, result;
  const frames = [], encoders = [];
  return () => {
    if (tick % 2 === 0) {
      result = runVision(vision, camera(x,z,yaw), filters,
        {gyroZ:plant.gyroDeg, yawAccum, encoderDistDelta:traveled});
      traveled = 0;
    }
    frames.push(result);
    encoders.push([plant.encL,plant.encR]);
    if (frames.length > 4) frames.shift();
    if (encoders.length > 2) encoders.shift();
    const seen = frames[0];
    const motor = ctrl.update10ms({error:seen.error, lateralError:seen.lateralError,
      farError:seen.errFar, ffW:seen.ffW, gyro:plant.gyroDeg,
      speedL:encoders[0][0], speedR:encoders[0][1], junc:seen.juncType, targetBaseV:seen.targetBaseV});
    const motion = plant.step(motor.pwmL,motor.pwmR,DT);
    yawAccum += motion.gyroDeg * Math.PI / 180 * DT;
    traveled += motion.vWorld * DT * 10;
    yaw -= motion.omegaRad * DT;
    x -= Math.sin(yaw) * motion.vWorld * DT;
    z -= Math.cos(yaw) * motion.vWorld * DT;
    tick++;
    return {t:tick/100, x_m:x/10, z_m:z/10, yaw_rad:yaw, speed_m_s:motion.vWorld/10,
      visual_error_px:result.error, visible_rows:vision.valid_rows_count,
      pwm_l:motor.pwmL, pwm_r:motor.pwmR};
  };
}

async function main() {
  const config = await (await fetch("config")).json();
  const step = vehicle(config);
  while (true) {
    const reply = await fetch("frames", {method:"POST", body:JSON.stringify(Array.from({length:25},step))});
    if (!reply.ok || !(await reply.json()).more) return;
  }
}
main().catch(error => fetch("error", {method:"POST",body:String(error.stack || error)}));
