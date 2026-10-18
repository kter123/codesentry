function merge(target, source) {
  for (const key of Object.keys(source)) {
    // CVE 模式：CWE-1321 Prototype Pollution——无 __proto__ 防护的递归合并
    target[key] = source[key]; // sink：line 4
  }
  return target;
}

module.exports = { merge };
