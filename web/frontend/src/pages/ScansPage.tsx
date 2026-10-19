import React, { useEffect, useRef, useState } from 'react'
import { Card, Col, Row, Table, Tabs, Tag, Upload, Input, Button, message } from 'antd'

interface ScanRow { id: number; repo_path: string; OSS: boolean; status: string; mode: string }

const api = {
  list: () => fetch('/api/scans').then(r => r.json()),
  upload: (form: FormData) => fetch('/api/scans', { method: 'POST', body: form }).then(r => r.json()),
}

const statusColor = (s: string) => (s === 'done' ? 'green' : s === 'failed' ? 'red' : 'blue')

const ScansPage: React.FC = () => {
  const [rows, setRows] = useState<ScanRow[]>([])
  const [gitUrl, setGitUrl] = useState('')
  const [diff, setDiff] = useState('')
  const timer = useRef<ReturnType<typeof setInterval>>()

  const refresh = () => api.list().then(setRows)
  useEffect(() => {
    refresh()
    timer.current = setInterval(refresh, 4000)
    return () => clearInterval(timer.current)
  }, [])

  const uploadZip = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('oss', 'true')
    try {
      const r = await api.upload(fd)
      message.success(`扫描已发起 scan_id=${r.scan_id}`)
      refresh()
    } catch (e) {
      message.error('上传失败')
    }
  }

  const startGit = async () => {
    const fd = new FormData()
    fd.append('git_url', gitUrl)
    const r = await api.upload(fd)
    if (r.detail) message.error(r.detail)
    else { message.success(`scan_id=${r.scan_id}`); refresh() }
  }

  const startDiff = async () => {
    const fd = new FormData()
    fd.append('diff_text', diff)
    const r = await api.upload(fd)
    if (r.detail) message.error(r.detail)
    else { message.success(`scan_id=${r.scan_id}`); refresh() }
  }

  return (
    <div>
      <Row gutter={16}>
        <Col span={24}>
          <Card title="发起扫描">
            <Tabs
              items={[
                {
                  key: 'zip', label: '上传源码包',
                  children: <Upload.Dragger beforeUpload={(f) => { uploadZip(f); return false }} accept=".zip,.tgz,.gz">
                    点击或拖拽 zip / tar.gz 到此处（≤500MB）
                  </Upload.Dragger>,
                },
                {
                  key: 'git', label: 'Git URL',
                  children: <div style={{ display: 'flex', gap: 8 }}>
                    <Input placeholder="https://github.com/owner/repo" value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} />
                    <Button type="primary" onClick={startGit}>拉取并扫描</Button>
                  </div>,
                },
                {
                  key: 'diff', label: '粘贴 diff',
                  children: <div style={{ display: 'flex', gap: 8, flexDirection: 'column' }}>
                    <Input.TextArea rows={6} placeholder="unified diff" value={diff} onChange={(e) => setDiff(e.target.value)} />
                    <Button type="primary" onClick={startDiff}>发起增量扫描</Button>
                  </div>,
                },
              ]}
            />
          </Card>
        </Col>
      </Row>
      <Card title="扫描历史" style={{ marginTop: 16 }}>
        <Table<ScanRow>
          rowKey="id"
          dataSource={rows}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: 'ID', dataIndex: 'id', render: (v) => <a href={`/scans/${v}`}>{v}</a> },
            { title: '仓库', dataIndex: 'repo_path', ellipsis: true },
            { title: 'OSS', dataIndex: 'OSS', render: (v) => (v ? <Tag>开源</Tag> : <Tag color="gold">闭源</Tag>) },
            { title: '状态', dataIndex: 'status', render: (s) => <Tag color={statusColor(s)}>{s}</Tag> },
            { title: '模式', dataIndex: 'mode' },
          ]}
        />
      </Card>
    </div>
  )
}

export default ScansPage
