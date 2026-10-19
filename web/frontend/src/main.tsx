import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, Layout, Menu, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ScansPage from './pages/ScansPage'
import ScanDetail from './pages/ScanDetail'

const { Header, Sider, Content } = Layout

const App: React.FC = () => {
  const route = window.location.pathname
  let page: React.ReactNode = <ScansPage />
  if (route.startsWith('/scans/')) page = <ScanDetail id={Number(route.split('/')[2])} />
  return (
    <ConfigProvider locale={zhCN}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="light">
          <Typography.Title level={4} style={{ margin: 16 }}>CodeSentry</Typography.Title>
          <Menu
            mode="inline"
            defaultSelectedKeys={['scans']}
            items={[
              { key: 'scans', label: <a href="/scans">扫描管理</a> },
              { key: 'agents', label: 'Agent 控制台（M5.3）' },
              { key: 'rules', label: '规则管理（M5.3）' },
              { key: 'skills', label: 'Skill 管理（M5.3）' },
              { key: 'prompts', label: 'Prompt 管理（M5.3）' },
              { key: 'reviews', label: '复核队列（M5.3）' },
            ]}
          />
        </Sider>
        <Content style={{ padding: 24 }}>{page}</Content>
      </Layout>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
