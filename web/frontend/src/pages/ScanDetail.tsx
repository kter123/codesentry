import React, { useEffect, useRef, useState } from 'react'
import { Card, Steps, Table, Tag, Button } from 'antd'

interface TimelineRow { node: string; started: string; duration_ms: number; tokens: number; status: string; error: string }

const ScanDetail: React.FC<{ id: number }> = ({ id }) => {
  const [info, setInfo] = useState<{ status: string; repo_path: string; timeline: TimelineRow[] } | null>(null)
  const [events, setEvents] = useState<string[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    fetch(`/api/scans/${id}`).then(r => r.json()).then(setInfo)
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/scans/${id}`)
    ws.onmessage = (m) => { setEvents((prev) => [...prev, m.data]);
        try { const e = JSON.parse(m.data); if (e.event === 'scan_done' || e.event === 'node_end') fetch(`/api/scans/${id}`).then(r=>r.json()).then(setInfo)} catch { /* noop */ } }
    wsRef.current = ws
    return () => ws.close()
  }, [id])

  if (!info) return <Card loading />

  return (
    <div>
      <Card title={`扫描 #${id}`} extra={<Tag color={info.status === 'done' ? 'green' : 'blue'}>{info.status}</Tag>}>
        <div>仓库：{info.repo_path}</div>
      </Card>
      <Card title="节点时间线（node_runs + WebSocket 实时）" style={{ marginTop: 16 }}>
        <Steps
          direction="vertical"
          size="small"
          current={info.timeline.length}
          items={info.timeline.map((t) => ({
            title: t.node,
            description: `${t.duration_ms}ms · ${t.tokens} tok ${t.error ? '· ' + t.error : ''}`,
            status: t.status === 'ok' ? 'finish' : 'error',
          }))}
        />
        {events.length > 0 && (
          <Table
            style={{ marginTop: 12 }}
            size="small"
            rowKey={(r, i) => String(i)}
            dataSource={events.map((e, i) => ({ i, e }))}
            columns={[{ title: '事件流', dataIndex: 'e' }]}
          />
        )}
      </Card>
    </div>
  )
}

export default ScanDetail
