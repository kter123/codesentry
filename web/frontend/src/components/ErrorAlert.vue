<template>
  <el-alert
    v-if="message"
    class="error-alert"
    type="error"
    show-icon
    :closable="false"
    :title="message"
  >
    <template v-if="retryable" #default>
      <el-button size="small" plain @click="$emit('retry')">重试</el-button>
    </template>
  </el-alert>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    message?: string
    retryable?: boolean
  }>(),
  { message: '', retryable: true },
)

defineEmits<{ retry: [] }>()
</script>

<style scoped>
.error-alert {
  margin-bottom: 14px;
}
</style>
