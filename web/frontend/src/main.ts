import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import type { Component } from 'vue'

import 'element-plus/dist/index.css'
import '@/styles.css'

import App from '@/App.vue'
import router from '@/router'

const app = createApp(App)

for (const [name, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(name, component as Component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.mount('#root')
