import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Switch, Button, Modal, Input, message, Steps, Typography } from 'antd'

function AgentsPage(): React.ReactElement {
  const [agents, setAgents] = useState<any[]>([])
  useEffect(() => { fetch('/api/agents').then(r => r.json()).then(d => setAgents(d.agents)) }, [])
  return (
    <Card title="Agent 控制台">
      <Table rowKey="name" dataSource={agents} columns={[
        { title: 'agent', dataIndex: 'name' },
        { title: 'model_role', dataIndex: 'model_role' },
        { title: 'enabled', dataIndex: 'enabled', render: (v) => <Switch checked={v} size="small" /> },
      ]} />
    </Card>
  )
}

function PromptsPage(): React.ReactElement {
  const [prompts, setPrompts] = useState<any[]>([])
  const [editor, setEditor] = useState<{ name: string; body: string } | null>(null)
  const refresh = () => fetch('/api/prompts').then(r => r.json()).then(d => setPrompts(d.prompts))
  useEffect(() => { refresh() }, [])
  const save = async () => {
    if (!editor) return
    const r = await fetch('/api/prompts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editor) }).then(r => r.json())
    message.success(`已保存 ${r.name} v${r.version}`)
    setEditor(null); refresh()
  }
  return (
    <Card title="Prompt 管理" extra={<Button onClick={() => setEditor({ name: '', body: '' })}>新建</Button>}>
      <Table rowKey="name" dataSource={prompts} columns={[
        { title: 'agent', dataIndex: 'name' },
        { title: '最新版本', dataIndex: 'latest_version' },
        { title: '预览', dataIndex: 'preview', ellipsis: true },
        { title: '', render: (_: any, r: any) => <Button size="small" onClick={() => fetch(`/api/prompts/${r.name}/versions`).then(x => x.json()).then(v => setEditor({ name: r.name, body: v.versions[0].body }))}>编辑</Button> },
      ]} />
      <Modal open={!!editor} onOk={save} onCancel={() => setEditor(null)} title="Prompt 编辑">
        <Input placeholder="agent 名" value={editor?.name} onChange={(e) => setEditor((ed) => (ed ? { ...ed, name: e.target.value } : ed))} />
        <Input.TextArea rows={10} style={{ marginTop: 8 }} value={editor?.body} onChange={(e) => setEditor((ed) => (ed ? { ...ed, body: e.target.value } : ed))} />
      </Modal>
    </Card>
  )
}

function SkillsPage(): React.ReactElement {
  const [skills, setSkills] = useState<any[]>([])
  const [uploadModal, setUploadModal] = useState(false)
  const [body, setBody] = useState('')
  const refresh = () => fetch('/api/skills').then(r => r.json()).then(d => setSkills(d.skills))
  useEffect(() => { refresh() }, [])
  const upload = async () => {
    const r = await fetch('/api/skills/upload', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'x', body }) }).then(r => r.json())
    if (r.detail) message.error(r.detail)
    else { message.success(`上传成功 ${r.name} v${r.version}`); setUploadModal(false); refresh() }
  }
  const assign = async (name: string, agent: string, enabled: boolean) => {
    await fetch(`/api/skills/${name}/assign`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ agent, enabled }) })
    refresh()
  }
  return (
    <Card title="Skill 管理" extra={<Button type="primary" onClick={() => setUploadModal(true)}>上传 SKILL.md</Button>}>
      <Table rowKey="name" dataSource={skills} columns={[
        { title: 'name', dataIndex: 'name' },
        { title: 'versions', dataIndex: 'versions' },
        { title: 'description', dataIndex: 'description', ellipsis: true },
        { title: '指派 agents', dataIndex: 'assigned',
          render: (assigned: Record<string, boolean>, r: any) => ['recon', 'scan', 'retrieval', 'triage', 'poc_gen', 'report'].map((a) => (
            <span key={a} style={{ marginRight: 6 }}>
              <Tag color={assigned?.[a] ? 'green' : 'default'} style={{ cursor: 'pointer' }} onClick={() => assign(r.name, a, !assigned?.[a])}>{a}{assigned?.[a] ? ' ✓' : ''}</Tag>
            </span>
          )) },
      ]} />
      <Modal open={uploadModal} onOk={upload} onCancel={() => setUploadModal(false)} title="粘贴 SKILL.md 内容">
        <Input.TextArea rows={12} value={body} onChange={(e) => setBody(e.target.value)} placeholder={'---\nname: xxx\ndescription: yyy\n---\n正文'} />
      </Modal>
    </Card>
  )
}

function RulesPage(): React.ReactElement {
  const [rules, setRules] = useState<any[]>([])
  const [yamlPreview, setYamlPreview] = useState<string | null>(null)
  useEffect(() => { fetch('/api/rules').then(r => r.json()).then(d => setRules(d.rules)) }, [])
  return (
    <Card title="规则管理（codesentry-core）">
      <Table rowKey="id" dataSource={rules} columns={[
        { title: 'id', dataIndex: 'id' },
        { title: 'languages', dataIndex: 'languages', render: (v: string[]) => v.join(', ') },
        { title: 'severity', dataIndex: 'severity', render: (s) => <Tag color={s === 'ERROR' ? 'red' : 'orange'}>{s}</Tag> },
        { title: 'CWE', dataIndex: 'cwe' },
        { title: '', render: (_: any, r: any) => <Button size="small" onClick={() => fetch(`/api/rules/${r.id}`).then(x => x.json()).then(d => setYamlPreview('<pre>' + JSON.stringify(d.rule, null, 2) + '</pre>'))}>详情</Button> },
      ]} />
      <Modal open={!!yamlPreview} onCancel={() => setYamlPreview(null)} footer={null} title="规则详情（v1.1 编辑器）">
        <div dangerouslySetInnerHTML={{ __html: yamlPreview ?? '' }} />
      </Modal>
    </Card>
  )
}

function ReviewsPage(): React.ReactElement {
  const [queue, setQueue] = useState<any[]>([])
  useEffect(() => { fetch('/api/reviews').then(r => r.json()).then(d => setQueue(d.queue)) }, [])
  return (
    <Card title="复核队列（interrupted 扫描）">
      {queue.length === 0 ? <Typography.Text type="secondary">队列为空——发起扫描并开 CODESENTRY_HUMAN_REVIEW=true 即可产生复核项</Typography.Text> :
        <Table rowKey="id" dataSource={queue} columns={[
          { title: 'scan', dataIndex: 'id', render: (v) => <a href={`/review/${v}`}>{v}</a> },
          { title: 'repo', dataIndex: 'repo_path', ellipsis: true },
          { title: '状态', dataIndex: 'status' },
        ]} />}
    </Card>
  )
}

export { AgentsPage, PromptsPage, SkillsPage, RulesPage, ReviewsPage }
