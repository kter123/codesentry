// EXPECT: clean | hasOwnProperty + __proto__ 过滤
function merge(src, dst) {
  for (const k of Object.keys(src)) {
    if (k === "__proto__" || k === "constructor") continue;
    dst[k] = src[k];
  }
  return dst;
}
module.exports = { merge };
