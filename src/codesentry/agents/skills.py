"""SKILL.md 目录包解析与注入（agent.md FR-12/D23/D34）。"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# 单 Skill 正文上限（token 估：字符/4；en 可调）
DEFAULT_SKILL_MAX_PER = 8192
DEFAULT_SKILL_TOTAL = 32768


@dataclass
class Skill:
    name: str
    description: str
    body: str
    body_tokens_est: int = 0
    references: list[str] = field(default_factory=list)  # 附加参考文件相对路径（渐进披露）


_FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def parse_skill_md(text: str) -> Skill:
    m = _FRONT.match(text.strip())
    if not m:
        raise ValueError("SKILL.md 缺 frontmatter（需 --- 包围的 name/description）")
    meta_raw, body = m.group(1), m.group(2)
    name = ""
    description = ""
    refs: list[str] = []
    for line in meta_raw.splitlines():
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    if not name:
        raise ValueError("frontmatter 缺 name")
    # 正文里的引用（渐进披露标记：@ref:xxx）
    refs = re.findall(r"@ref:([^\s]+)", body)
    return Skill(name=name, description=description, body=body, body_tokens_est=len(body) // 4, references=refs)


def load_skill_dir(path: str) -> Skill:
    p = Path(path)
    doc = p / "SKILL.md"
    if not doc.is_file():
        raise FileNotFoundError(f"SKILL.md not found in {path}")
    return parse_skill_md(doc.read_text(encoding="utf-8"))


def cap_body(body: str, max_per: int = DEFAULT_SKILL_MAX_PER) -> tuple[str, bool]:
    """截断并返回 (截断后, 是否被截)。token 估 = 字符/4。"""
    est = len(body) // 4
    if est <= max_per:
        return body, False
    chars = max_per * 4
    return body[:chars], True


def build_context_block(skills: list[Skill], max_per: int = DEFAULT_SKILL_MAX_PER, max_total: int = DEFAULT_SKILL_TOTAL) -> tuple[str, list[str]]:
    """拼进 agent system 的 Skills 段落；超限截断并返回告警列表（进 messages）。"""
    warnings: list[str] = []
    parts: list[str] = []
    total = 0
    for s in skills:
        body, truncated = cap_body(s.body, max_per)
        if truncated:
            warnings.append(f"skill '{s.name}' 超 {max_per} token 上限，已截断")
        if total + s.body_tokens_est > max_total:
            warnings.append(f"skill '{s.name}' 触达单 agent 注入总量上限 {max_total}，跳过")
            continue
        parts.append(f"### Skill: {s.name}\n{body}")
        total += s.body_tokens_est
    if not parts:
        return "", warnings
    block = "\n\n---\n".join(parts)
    return f"\n\n# Skills（按需参考）\n{block}", warnings
