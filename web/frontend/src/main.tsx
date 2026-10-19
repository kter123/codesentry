import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, Layout, Menu, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import ScansPage from './pages/ScansPage'
import ScanDetail from './pages/ScanDetail'
import ReviewPage from './pages/ReviewPage'
import { AgentsPage, PromptsPage, SkillsPage, RulesPage, ReviewsPage } from './pages/AdminPages'

const { Sider, Content } = Layout

const PAGES: Record<string, (props: { id?: number; scanId?: number }) => React.ReactElement> = {
  scans: () => <ScansPage />,
  agents: () => <AgentsPage />,
  rules: () => <RulesPage />,
  skills: () => <SkillsPage />,
  prompts: () => <PromptsPage />,
  reviews: () => <ReviewsPage />,
}

const App: React.FC = () => {
  const route = window.location.pathname
  let key = 'scans'
  let page: React.ReactNode = <ScansPage />
  if (route.startsWith('/scans/')) { page = <ScanDetail id={Number(route.split('/')[2])} />; key = 'scans' }
  else if (route.startsWith('/review/')) { page = <ReviewPage scanId={Number(route.split('/')[2])} />; key = 'reviews' }
  else {
    const seg = route.replace(/^\//, '').split('/')[0]
    if (seg && PAGES[seg]) { key = seg; page = PAGES[seg]({}) }
  }
  return (
    <ConfigProvider locale={zhCN}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider theme="light">
          <Typography.Title level={4} style={{ margin: 16 }}>CodeSentry</Typography.Title>
          <Menu
            mode="inline"
            defaultSelectedKeys={[key]}
            items={[
              { key: 'scans', label: <a href="/scans">扫描管理</a> },
              { key: 'agents', label: <a href="/agents">Agent 控制台</a> },
              { key: 'rules', label: <a href="/rules">规则管理</a> },
              { key: 'skills', label: <a href="/skills">Skill 管理</a> },
              { key: 'prompts', label: <a href="/prompts">Prompt 管理</a> },
              { key: 'reviews', label: <a href="/reviews">复核队列</a> },
            ]}
          />
        </Sider>
        <Content style={{ padding: 24 }}>{page}</Content>
      </Layout>
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
