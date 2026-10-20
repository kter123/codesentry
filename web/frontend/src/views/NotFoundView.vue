<template>
  <el-result icon="warning" title="404" sub-title="页面不存在或已被移除。">
    <template #extra>
      <el-button type="primary" @click="$router.push('/')">返回概览</el-button>
      <el-button @click="$router.back()">返回上一页</el-button>
    </template>
  </el-result>
</template>
