// EXPECT: vulnerable | CWE-1321 原型污染：for-in 合并无过滤
function merge(src, dst) {
  for (const k in src) {
    dst[k] = src[k];
  }
  return dst;
}
module.exports = { merge };
