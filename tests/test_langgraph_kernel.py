"""LangGraph 内核专项测试（M6）：checkpointer 恢复、interrupt/resume、time travel、Send 并行。"""


from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from codesentry.agents.state import new_state
from codesentry.orchestrator.graph import build_graph


def test_checkpointer_survives_process_restart_semantics():
    """同 thread_id 二次 invoke 必须复用 checkpointer 内的状态（进程级模拟：重建图）。"""
    cp = MemorySaver()
    holder = {"scan_id": 7, "budget": None}

    def recon(state):
        return {"profile": {"languages": ["python"]}, "messages": ["recon-run"]}

    g1 = build_graph(
        recon_agent=recon,
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=lambda s: {"triaged_findings": [], "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=cp,
        scan_id_holder=holder,
    )
    st = new_state("/r", OSS=False, scan_id=7)
    cfg = {"configurable": {"thread_id": "scan-7"}}
    final1 = g1.invoke(st, config=cfg)
    assert final1["phase"] == "done"
    assert any("recon-run" in m for m in final1["messages"])

    # 重建图（模拟进程重启），同 thread_id 继续：checkpointer 应保留已有 tuples
    g2 = build_graph(
        recon_agent=recon,
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=lambda s: {"triaged_findings": [], "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=cp,
        scan_id_holder=holder,
    )
    snap = g2.get_state(cfg)
    assert snap is not None and snap.values.get("phase") == "done"


def test_state_history_lists_updates():
    cp = MemorySaver()
    g = build_graph(
        recon_agent=lambda s: {"profile": {"languages": ["python"]}},
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=lambda s: {"triaged_findings": [], "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=cp,
        scan_id_holder={"scan_id": 0, "budget": None},
    )
    cfg = {"configurable": {"thread_id": "scan-hist"}}
    g.invoke(new_state("/r", OSS=False), config=cfg)
    history = list(g.get_state_history(cfg))
    assert len(history) >= 5  # 每个节点至少一条
    nodes = [h.values.get("phase") for h in history if h.values]
    assert "done" in nodes


def test_interrupt_and_resume_roundtrip():
    from codesentry.orchestrator.human_review import human_review_node

    cp = MemorySaver()
    captured: dict = {}

    def poc(state):
        captured["poc"] = True
        return {"poc_results": {"x@1": {"verdict": "plausible"}}, "phase": "human_review"}

    g = build_graph(
        recon_agent=lambda s: {"profile": {}},
        scan_agent=lambda s: {"engine_findings": [{"rule_id": "x", "line": 1, "confidence": 0.5}]},
        retrieval_agent=lambda s: {"evidence": {}},
        triage_agent=lambda s: {"triaged_findings": [{"rule_id": "x", "line": 1}], "phase": "human_review"},
        poc_agent=poc,
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=cp,
        scan_id_holder={"scan_id": 0, "budget": None},
        human_review_node=human_review_node,
    )
    import os as _os

    cfg = {"configurable": {"thread_id": "scan-int"}, "recursion_limit": 30}
    _os.environ["CODESENTRY_HUMAN_REVIEW"] = "true"
    try:
        res1 = g.invoke(new_state("/r", OSS=False), config=cfg)
        assert res1.get("__interrupt__") or g.get_state(cfg).next
        res2 = g.invoke(Command(resume=[{"verdict": "keep"}]), config=cfg)
        assert res2["phase"] == "done"
        assert captured.get("poc") is True
    finally:
        _os.environ["CODESENTRY_HUMAN_REVIEW"] = "false"


def test_budget_breach_routes_to_report():
    g = build_graph(
        recon_agent=lambda s: {"profile": {}},
        scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
        retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
        triage_agent=lambda s: {"triaged_findings": [], "budget": {"phase": "breach",
                                "tokens": 0, "tool_calls": 0, "cost_usd": 0}, "phase": "poc_gen"},
        poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
        report_agent_fn=lambda s: {"phase": "done"},
        checkpointer=None,
        scan_id_holder={"scan_id": 0, "budget": None},
    )
    final = g.invoke(new_state("/r", OSS=False), config={"recursion_limit": 20})
    assert final["phase"] == "done"


def test_stub_nodes_with_only_state_still_compile():
    """基座兼容红线：只接受 state 的 lambda stub 不被 runtime 注入破坏。"""
    g = build_graph(
        recon_agent=lambda s: {"profile": {}},
        scan_agent=lambda s: {"engine_findings": []},
        retrieval_agent=lambda s: {"evidence": {}},
        triage_agent=lambda s: {"triaged_findings": []},
        poc_agent=lambda s: {"poc_results": {}},
        report_agent_fn=lambda s: {"phase": "done"},
    )
    final = g.invoke(new_state("/r", OSS=False), config={"recursion_limit": 20})
    assert final["phase"] == "done"


def test_artifacts_written_per_node(tmp_path):
    from codesentry.control.bootstrap import ensure_control_schema
    from codesentry.db.pool import get_conn

    ensure_control_schema()
    with get_conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO scans (repo_path, license_oss, license_declared_at) VALUES ('/tmp/lg',false,now()) RETURNING id"
        )
        sid = int(cur.fetchone()[0]); c.commit()
    try:
        g = build_graph(
            recon_agent=lambda s: {"profile": {}},
            scan_agent=lambda s: {"engine_findings": [], "phase": "retrieval"},
            retrieval_agent=lambda s: {"evidence": {}, "phase": "triage"},
            triage_agent=lambda s: {"triaged_findings": [], "phase": "poc_gen"},
            poc_agent=lambda s: {"poc_results": {}, "phase": "report"},
            report_agent_fn=lambda s: {"phase": "done"},
            checkpointer=None,
            scan_id_holder={"scan_id": sid, "budget": None},
        )
        g.invoke(new_state("/tmp/lg", OSS=False, scan_id=sid), config={"recursion_limit": 20})
        with get_conn() as c, c.cursor() as cur:
            cur.execute("SELECT node FROM agent_artifacts WHERE scan_id=%s ORDER BY seq", (sid,))
            nodes = [r[0] for r in cur.fetchall()]
        assert nodes, "artifacts must be written per node"
        assert nodes[0] == "recon"
    finally:
        with get_conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM agent_artifacts WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM node_runs WHERE scan_id=%s", (sid,))
            cur.execute("DELETE FROM scans WHERE id=%s", (sid,))
            c.commit()
