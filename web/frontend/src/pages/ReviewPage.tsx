import React, { useEffect, useRef, useState } from 'react'
import { Card, Col, Drawer, Input, Row, Select, Table, Tag, Typography, Button, InputNumber } from 'antd'
import { Graph } from '@antv/g6'

export interface GraphNode {
  id: string; kind: string; file: string; name: string
  start: number; end: number; findings: any[]
}
export interface GraphEdge { source: string; target: string; kind: string }

const TaintPlayer: React.FC<{ path: any[] }> = ({ path }) => {
  const [step, setStep] = useState(0)
  useEffect(() => { setStep(0) }, [path])
  if (!path.length) return <Typography.Text type="secondary">无污点链（finding 无 exploit_chain）</Typography.Text>
  return (
    <div>
      <Button size="small" onClick={() => setStep((s) => (s + 1) % (path.length + 1))}>播放下一步</Button>
      <div style={{ marginTop: 8 }}>
        {path.slice(0, step).map((p: any, i) => (
          <div key={i}><Tag color="orange">{i + 1}</Tag>{typeof p === 'string' ? p : JSON.stringify(p)}</div>
        ))}
      </div>
    </div>
  )
}

const NodeDrawer: React.FC<{ scanId: number; file: string; start: number; node: GraphNode | null; onClose: () => void }> =
  ({ scanId, file, start, node, onClose }) => {
    const [src, setSrc] = useState<any>(null)
    useEffect(() => {
      if (!node) return
      const st = Math.max(1, node.start || start || 1)
      fetch(`/api/scans/${scanId}/source?path=${encodeURIComponent(node.file)}&start=${st}&end=${st + 40}`)
        .then(r => r.json()).then(setSrc)
    }, [node, scanId])
    return (
      <Drawer open={!!node} onClose={onClose} title={node?.file} width={720}>
        {node && (
          <div>
            <Typography.Title level={5}>{node.kind} {node.name}</Typography.Title>
            {node.findings.map((f: any) => (
              <div key={f.rule_id} style={{ margin: '8px 0', padding: 8, background: '#fff7e6' }}>
                <Tag color="red">CWE-{f.cwe}</Tag><b>{f.severity}</b> {f.message}
                <div><Typography.Text type="secondary">{f.rule_id}</Typography.Text></div>
                {f.exploit_chain?.length ? (
                  <div style={{ marginTop: 8 }}>
                    <Typography.Text strong>污点链</Typography.Text>
                    <TaintPlayer path={f.exploit_chain} />
                  </div>
                ) : null}
              </div>
            ))}
            {src?.lines && (
              <pre style={{ background: '#f6f6f6', padding: 12, overflowX: 'auto' }}>
                {src.lines.map((l: any) => (
                  <div key={l.no} style={l.no >= (node.start || 0) && l.no <= (node.end || 0) ? { background: '#faecd8' } : {}}>
                    <span style={{ color: '#999', display: 'inline-block', width: 40 }}>{l.no}</span>
                    {l.text}
                  </div>
                ))}
              </pre>
            )}
          </div>
        )}
      </Drawer>
    )
  }

const ReviewPage: React.FC<{ scanId: number }> = ({ scanId }) => {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[]; mode: string } | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [cweFilter, setCweFilter] = useState<number | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const gRef = useRef<Graph | null>(null)

  useEffect(() => { fetch(`/api/scans/${scanId}/graph`).then(r => r.json()).then(setGraph) }, [scanId])

  useEffect(() => {
    if (!graph || !containerRef.current) return
    const shown = graph.nodes.filter((n) => !cweFilter || n.findings.some((f: any) => f.cwe === cweFilter))
    const showIds = new Set(shown.map((n) => n.id))
    const data = {
      nodes: shown.map((n) => ({
        id: n.id,
        label: n.name,
        style: { size: n.findings.length ? 32 : 20, fill: n.findings.length ? '#cf1322' : '#91caff' },
      })),
      edges: graph.edges.filter((e) => showIds.has(e.source) && showIds.has(e.target)).map((e) => ({ source: e.source, target: e.target })),
    }
    const g = new Graph({ container: containerRef.current, data, autoFit: 'view' })
    window.addEventListener('resize', () => { /* noop for now */ })
    gRef.current = g
    try {
      const ig = g as unknown as { render: () => Promise<any>; on: (ev: string, cb: (e: any) => void) => void }
      ig.render()
      ig.on('node:click', (e) => {
        const id = e?.target?.id ?? e?.target?.pluck?.('id')
        const n = graph.nodes.find((x) => x.id === id)
        if (n) setSelected(n)
      })
    } catch (err) { console.error(err) }
    return () => { gRef.current?.destroy?.(); gRef.current = null }
  }, [graph, cweFilter])

  const cwes = Array.from(new Set((graph?.nodes ?? []).flatMap((n) => n.findings.map((f: any) => f.cwe)))).sort()

  return (
    <div>
      <Row gutter={12}>
        <Col span={6}>
          <Card title={<div>Finding 过滤<Select
            allowClear placeholder="CWE"
            style={{ width: 110 }}
            value={cweFilter ?? undefined}
            onChange={(v) => setCweFilter(v ?? null)}
            options={cwes.map((c) => ({ value: c, label: `CWE-${c}` }))}
          /></div>}>
            <Input.Search placeholder="关键词" />
            <Table
              size="small"
              rowKey={(r: any) => r.rule_id + r.line}
              dataSource={(graph?.nodes ?? []).flatMap((n) => n.findings)}
              columns={[
                { title: '规则', dataIndex: 'rule_id', ellipsis: true, render: (v: string) => <a href="#">{v.split('.').pop()}</a> },
                { title: '文件', dataIndex: 'file_rel', ellipsis: true },
                { title: 'CWE', dataIndex: 'cwe', render: (v: any) => <Tag>CWE-{v}</Tag> },
              ]}
            />
        </Card>
        </Col>
        <Col span={18}>
          <Card title={`调用图（mode=${graph?.mode ?? 'loading'}）`} extra={<Typography.Text type="secondary">点节点看源码与详情</Typography.Text>}>
            <div ref={containerRef} style={{ height: 620 }} />
          </Card>
        </Col>
      </Row>
      <NodeDrawer scanId={scanId} file="" start={1} node={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

export default ReviewPage
