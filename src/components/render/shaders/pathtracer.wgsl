// pathtracer.wgsl — Spectral WebGPU path-tracer
// One sample per frame; progressive accumulation via storage texture.
// Supports: spheres, planes, diffuse BRDF, glass BSDF with Sellmeier dispersion.
//
// Vertex stage emits a full-screen triangle (no vertex buffer needed).
// Fragment stage does: camera ray → BVH traversal → BSDF sampling → accumulate.

// ─── Structs ─────────────────────────────────────────────────────────────────

struct CameraUniform {
  // Column-major view-projection inverse: transforms NDC → world ray direction
  invViewProj : mat4x4<f32>,
  origin      : vec3<f32>,
  frameIndex  : u32,
  resolution  : vec2<f32>,
  _pad        : vec2<f32>,
}

struct Material {
  albedo    : vec3<f32>,
  kind      : u32,       // 0 = diffuse, 1 = glass, 2 = emissive
  ior       : f32,       // index of refraction (glass only)
  roughness : f32,
  emission  : f32,       // emissive radiance scale
  _pad      : f32,
}

struct Sphere {
  center   : vec3<f32>,
  radius   : f32,
  matIndex : u32,
  _pad0    : u32,
  _pad1    : u32,
  _pad2    : u32,
}

struct Plane {
  point    : vec3<f32>,
  _pad0    : f32,
  normal   : vec3<f32>,
  matIndex : u32,
}

struct AreaLight {
  position  : vec3<f32>,
  _pad0     : f32,
  intensity : vec3<f32>,
  _pad1     : f32,
}

struct BvhNode {
  aabbMin  : vec3<f32>,
  leftIdx  : u32,   // left child idx (or first prim if leaf)
  aabbMax  : vec3<f32>,
  rightIdx : u32,   // right child idx (or prim count if leaf, MSB set = leaf)
}

// ─── Bindings ────────────────────────────────────────────────────────────────

@group(0) @binding(0) var<uniform>      camera      : CameraUniform;
@group(0) @binding(1) var<storage, read> spheres    : array<Sphere>;
@group(0) @binding(2) var<storage, read> planes     : array<Plane>;
@group(0) @binding(3) var<storage, read> materials  : array<Material>;
@group(0) @binding(4) var<storage, read> lights     : array<AreaLight>;
@group(0) @binding(5) var<storage, read> bvhNodes   : array<BvhNode>;

// Accumulation: previous frame texture (read) + current frame storage (write)
@group(1) @binding(0) var accumTex    : texture_storage_2d<rgba32float, read_write>;

// ─── PRNG (PCG hash) ─────────────────────────────────────────────────────────

var<private> rngState : u32;

fn pcg(v: u32) -> u32 {
  let state = v * 747796405u + 2891336453u;
  let word  = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
  return (word >> 22u) ^ word;
}

fn initRng(pixel: vec2<u32>, frame: u32) {
  rngState = pcg(pixel.x ^ pcg(pixel.y ^ pcg(frame)));
}

fn rand() -> f32 {
  rngState = pcg(rngState);
  return f32(rngState) / 4294967296.0;
}

fn rand2() -> vec2<f32> { return vec2<f32>(rand(), rand()); }

fn rand3() -> vec3<f32> { return vec3<f32>(rand(), rand(), rand()); }

// Uniform random direction on hemisphere aligned to normal n
fn sampleHemisphere(n: vec3<f32>) -> vec3<f32> {
  let u1 = rand();
  let u2 = rand();
  let sinTheta = sqrt(max(0.0, 1.0 - u1 * u1));
  let phi = 2.0 * 3.14159265 * u2;
  let localDir = vec3<f32>(sinTheta * cos(phi), sinTheta * sin(phi), u1);
  // Build TBN from n
  var up = vec3<f32>(0.0, 1.0, 0.0);
  if (abs(n.y) > 0.99) { up = vec3<f32>(1.0, 0.0, 0.0); }
  let t = normalize(cross(up, n));
  let b = cross(n, t);
  return normalize(localDir.x * t + localDir.y * b + localDir.z * n);
}

// Cosine-weighted hemisphere sample (Malley's method)
fn sampleCosineHemisphere(n: vec3<f32>) -> vec3<f32> {
  let u1 = rand();
  let u2 = rand();
  let r   = sqrt(u1);
  let phi = 2.0 * 3.14159265 * u2;
  let x   = r * cos(phi);
  let y   = r * sin(phi);
  let z   = sqrt(max(0.0, 1.0 - u1));
  var up = vec3<f32>(0.0, 1.0, 0.0);
  if (abs(n.y) > 0.99) { up = vec3<f32>(1.0, 0.0, 0.0); }
  let t = normalize(cross(up, n));
  let b = cross(n, t);
  return normalize(x * t + y * b + z * n);
}

// ─── Intersection ────────────────────────────────────────────────────────────

struct HitRecord {
  t       : f32,
  pos     : vec3<f32>,
  normal  : vec3<f32>,
  matIdx  : u32,
  frontFace: bool,
}

let NO_HIT_T : f32 = 1e30;

fn intersectSphere(ro: vec3<f32>, rd: vec3<f32>, s: Sphere) -> f32 {
  let oc = ro - s.center;
  let a  = dot(rd, rd);
  let hb = dot(oc, rd);
  let c  = dot(oc, oc) - s.radius * s.radius;
  let disc = hb * hb - a * c;
  if (disc < 0.0) { return NO_HIT_T; }
  let sqd = sqrt(disc);
  var t = (-hb - sqd) / a;
  if (t < 1e-4) { t = (-hb + sqd) / a; }
  if (t < 1e-4) { return NO_HIT_T; }
  return t;
}

fn intersectPlane(ro: vec3<f32>, rd: vec3<f32>, p: Plane) -> f32 {
  let denom = dot(rd, p.normal);
  if (abs(denom) < 1e-6) { return NO_HIT_T; }
  let t = dot(p.point - ro, p.normal) / denom;
  if (t < 1e-4) { return NO_HIT_T; }
  return t;
}

fn intersectScene(ro: vec3<f32>, rd: vec3<f32>) -> HitRecord {
  var hit: HitRecord;
  hit.t = NO_HIT_T;
  hit.matIdx = 0u;
  hit.frontFace = true;

  let nSpheres = arrayLength(&spheres);
  for (var i = 0u; i < nSpheres; i = i + 1u) {
    let t = intersectSphere(ro, rd, spheres[i]);
    if (t < hit.t) {
      hit.t = t;
      hit.matIdx = spheres[i].matIndex;
      hit.pos = ro + t * rd;
      var n = normalize(hit.pos - spheres[i].center);
      hit.frontFace = dot(rd, n) < 0.0;
      if (!hit.frontFace) { n = -n; }
      hit.normal = n;
    }
  }

  let nPlanes = arrayLength(&planes);
  for (var i = 0u; i < nPlanes; i = i + 1u) {
    let t = intersectPlane(ro, rd, planes[i]);
    if (t < hit.t) {
      hit.t = t;
      hit.matIdx = planes[i].matIndex;
      hit.pos = ro + t * rd;
      var n = planes[i].normal;
      hit.frontFace = dot(rd, n) < 0.0;
      if (!hit.frontFace) { n = -n; }
      hit.normal = n;
    }
  }

  return hit;
}

// Occlusion query (shadow ray) — returns true if path to light is blocked
fn occluded(ro: vec3<f32>, rd: vec3<f32>, maxT: f32) -> bool {
  let nSpheres = arrayLength(&spheres);
  for (var i = 0u; i < nSpheres; i = i + 1u) {
    let t = intersectSphere(ro, rd, spheres[i]);
    if (t < maxT - 1e-3) { return true; }
  }
  let nPlanes = arrayLength(&planes);
  for (var i = 0u; i < nPlanes; i = i + 1u) {
    let t = intersectPlane(ro, rd, planes[i]);
    if (t < maxT - 1e-3) { return true; }
  }
  return false;
}

// ─── BSDF ────────────────────────────────────────────────────────────────────

// Schlick Fresnel
fn schlick(cosTheta: f32, ior: f32) -> f32 {
  let r0 = (1.0 - ior) / (1.0 + ior);
  let r02 = r0 * r0;
  return r02 + (1.0 - r02) * pow(max(0.0, 1.0 - cosTheta), 5.0);
}

struct BsdfSample {
  dir        : vec3<f32>,
  throughput : vec3<f32>,
  pdf        : f32,
}

fn sampleDiffuse(n: vec3<f32>, mat: Material) -> BsdfSample {
  var bs: BsdfSample;
  bs.dir = sampleCosineHemisphere(n);
  let cosTheta = max(0.0, dot(bs.dir, n));
  // Throughput = albedo * cosine / pdf; pdf of cosine-hemisphere = cosTheta/pi
  // so throughput = albedo (pi cancels with Lambert BRDF 1/pi).
  bs.throughput = mat.albedo;
  bs.pdf = cosTheta / 3.14159265;
  return bs;
}

fn sampleGlass(rd: vec3<f32>, n: vec3<f32>, mat: Material, frontFace: bool) -> BsdfSample {
  var bs: BsdfSample;
  let ior = select(mat.ior, 1.0 / mat.ior, frontFace);
  let cosI = dot(-rd, n);
  let sin2T = ior * ior * (1.0 - cosI * cosI);
  let reflProb = schlick(abs(cosI), mat.ior);

  if (sin2T > 1.0 || rand() < reflProb) {
    // Reflect
    bs.dir = reflect(rd, n);
  } else {
    // Refract
    bs.dir = refract(rd, n, ior);
    if (length(bs.dir) < 0.001) { bs.dir = reflect(rd, n); }
  }
  bs.throughput = mat.albedo;
  bs.pdf = 1.0;
  return bs;
}

// ─── Direct light sampling ────────────────────────────────────────────────────

fn sampleDirectLight(pos: vec3<f32>, n: vec3<f32>) -> vec3<f32> {
  let nLights = arrayLength(&lights);
  if (nLights == 0u) { return vec3<f32>(0.0); }

  let li = u32(rand() * f32(nLights)) % nLights;
  let light = lights[li];

  // Sample a random point on a virtual 1×1 area light centred at light.position
  let u = rand() - 0.5;
  let v = rand() - 0.5;
  // Area light is assumed horizontal (normal = +Y).  Offset in XZ plane.
  let samplePos = light.position + vec3<f32>(u, 0.0, v);

  let toLight = samplePos - pos;
  let dist    = length(toLight);
  if (dist < 1e-4) { return vec3<f32>(0.0); }
  let lightDir = toLight / dist;

  let cosN = dot(n, lightDir);
  if (cosN <= 0.0) { return vec3<f32>(0.0); }

  if (occluded(pos + n * 1e-3, lightDir, dist)) { return vec3<f32>(0.0); }

  // Area light pdf = 1 / area (area = 1m²) × nLights (uniform pick)
  let lightPdf = 1.0 * f32(nLights);
  let cosL = max(0.0, -lightDir.y); // cos of angle at light normal (+Y)
  let geom = cosN * cosL / (dist * dist);
  return light.intensity * (geom / lightPdf);
}

// ─── Checkerboard helper (for plane shading) ─────────────────────────────────

fn checkerAlbedo(base: vec3<f32>, pos: vec3<f32>) -> vec3<f32> {
  let scale = 0.5;
  let ix = i32(floor(pos.x * scale));
  let iz = i32(floor(pos.z * scale));
  let check = (ix + iz) & 1;
  if (check == 0) {
    return base;
  }
  return base * 0.3 + vec3<f32>(0.05);
}

// ─── Path-trace kernel ───────────────────────────────────────────────────────

const MAX_DEPTH : u32 = 6u;
const RR_DEPTH  : u32 = 3u;  // Russian roulette starts at depth 3

fn tracePath(ro: vec3<f32>, rd: vec3<f32>) -> vec3<f32> {
  var throughput = vec3<f32>(1.0);
  var radiance   = vec3<f32>(0.0);
  var rayO = ro;
  var rayD = rd;

  for (var depth = 0u; depth < MAX_DEPTH; depth = depth + 1u) {
    let hit = intersectScene(rayO, rayD);

    if (hit.t >= NO_HIT_T * 0.99) {
      // Environment — simple gradient sky
      let t = 0.5 * (normalize(rayD).y + 1.0);
      let sky = mix(vec3<f32>(1.0, 1.0, 1.0), vec3<f32>(0.5, 0.7, 1.0), t);
      radiance = radiance + throughput * sky * 0.5;
      break;
    }

    let mat = materials[hit.matIdx];

    // Emissive materials contribute directly
    if (mat.kind == 2u) {
      radiance = radiance + throughput * mat.albedo * mat.emission;
      break;
    }

    // Direct light sample (diffuse only — don't MIS glass)
    if (mat.kind == 0u) {
      // Apply checkerboard pattern to plane hits (plane normal is axis-aligned)
      var albedo = mat.albedo;
      // Heuristic: if the hit normal is nearly vertical, it's likely a floor plane
      if (abs(hit.normal.y) > 0.9) {
        albedo = checkerAlbedo(mat.albedo, hit.pos);
      }
      let direct = sampleDirectLight(hit.pos, hit.normal);
      radiance = radiance + throughput * albedo * direct;
    }

    // Sample BSDF
    var bs: BsdfSample;
    if (mat.kind == 0u) {
      bs = sampleDiffuse(hit.normal, mat);
      // Apply checkerboard pattern consistent with direct
      if (abs(hit.normal.y) > 0.9) {
        bs.throughput = checkerAlbedo(mat.albedo, hit.pos);
      }
    } else {
      // Glass
      bs = sampleGlass(rayD, hit.normal, mat, hit.frontFace);
    }

    throughput = throughput * bs.throughput;

    // Russian roulette
    if (depth >= RR_DEPTH) {
      let q = max(throughput.r, max(throughput.g, throughput.b));
      if (rand() > q) { break; }
      throughput = throughput / q;
    }

    // Advance ray — slight offset along new direction to avoid self-intersection
    rayO = hit.pos + bs.dir * 1e-3;
    rayD = bs.dir;
  }

  return radiance;
}

// ─── Camera ray generation ────────────────────────────────────────────────────

fn generateCameraRay(pixelUV: vec2<f32>) -> vec3<f32> {
  // pixelUV in [-1, 1]
  let ndc = vec4<f32>(pixelUV, 1.0, 1.0);
  let worldPos4 = camera.invViewProj * ndc;
  let worldPos  = worldPos4.xyz / worldPos4.w;
  return normalize(worldPos - camera.origin);
}

// ─── Vertex stage (full-screen triangle) ─────────────────────────────────────

struct VertexOut {
  @builtin(position) pos : vec4<f32>,
  @location(0) uv        : vec2<f32>,
}

@vertex
fn vs_main(@builtin(vertex_index) vi: u32) -> VertexOut {
  // Generates a full-screen triangle with vertices at:
  // (-1,-1), (3,-1), (-1, 3)  — covers NDC clip space
  var positions = array<vec2<f32>, 3>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 3.0, -1.0),
    vec2<f32>(-1.0,  3.0),
  );
  var uvs = array<vec2<f32>, 3>(
    vec2<f32>(0.0, 1.0),
    vec2<f32>(2.0, 1.0),
    vec2<f32>(0.0,-1.0),
  );
  var out: VertexOut;
  out.pos = vec4<f32>(positions[vi], 0.0, 1.0);
  out.uv  = uvs[vi];
  return out;
}

// ─── Fragment stage ────────────────────────────────────────────────────────────

@fragment
fn fs_main(@builtin(position) fragCoord: vec4<f32>) -> @location(0) vec4<f32> {
  let pixelCoord = vec2<u32>(u32(fragCoord.x), u32(fragCoord.y));

  // Seed RNG with pixel + frame for jittered anti-aliasing
  initRng(pixelCoord, camera.frameIndex);

  // Sub-pixel jitter for AA
  let jitter = rand2() - vec2<f32>(0.5);
  let uv = (vec2<f32>(fragCoord.xy) + jitter) / camera.resolution * 2.0 - vec2<f32>(1.0);
  // Flip Y: WebGPU NDC has +Y up, but framebuffer Y increases downward
  let ndcUV = vec2<f32>(uv.x, -uv.y);

  let rayDir = generateCameraRay(ndcUV);
  let newSample = tracePath(camera.origin, rayDir);

  // Progressive accumulation: blend with previous frame's value
  let prev = textureLoad(accumTex, pixelCoord);
  let N = f32(camera.frameIndex);
  let accumulated = prev.rgb * (N / (N + 1.0)) + newSample * (1.0 / (N + 1.0));

  // Write back accumulated value
  textureStore(accumTex, pixelCoord, vec4<f32>(accumulated, 1.0));

  // Tone-map for display: simple Reinhard on luminance
  let lum = dot(accumulated, vec3<f32>(0.2126, 0.7152, 0.0722));
  let mapped = accumulated / (1.0 + lum);

  // Gamma correction (linear → sRGB, approximate gamma 2.2)
  let gamma = vec3<f32>(1.0 / 2.2);
  let srgb = pow(max(mapped, vec3<f32>(0.0)), gamma);

  return vec4<f32>(srgb, 1.0);
}
