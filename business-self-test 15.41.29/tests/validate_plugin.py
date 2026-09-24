#!/usr/bin/env python3
"""Validate the business-self-test plugin's repository-level contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


BI_REFERENCE = "bi-report-api-testing.md"
CANONICAL_CONTRACT = Path("skills/business-test-contract.md")
REQUIRED_SKILLS = (
    Path("skills/make-business-test-points/SKILL.md"),
    Path("skills/check-code-with-business-tests/SKILL.md"),
)
FORBIDDEN_IGNORE_RULES = {
    ".qa-agent/cases/",
    ".qa-agent/current/",
    ".qa-agent/reports/",
    ".qa-agent/runs/",
    "src/test/",
    "tests/",
    "specs/",
    "test/",
    "src/",
    "app/",
    "lib/",
    "/",
    "./",
    ".",
    "seed.spec.*",
}
GITIGNORE_META_CHARACTERS = frozenset("*?[]!")
TP_STATES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
TP_FIELDS = {
    "标题/目标",
    "依据",
    "优先级",
    "角色与前置",
    "操作",
    "预期",
    "来源映射",
    "目标等级",
}
PAYLOAD_HASH_OUTSIDE_RULE = "确认载荷 SHA-256 必须位于两行载荷标记之外，不参与自身摘要计算。"
STRICT_PRODUCTION_READ_ONLY_RULE = (
    "`PROD` 和 `UNKNOWN` 仅允许只读检查，禁止任何真实写入；"
    "用户确认、已有凭据或时间压力都不能解除该禁令。"
)
SNAPSHOT_MANIFEST_RULE = (
    "快照 manifest 固定记录算法版本、扫描根、基准、规范化文件条目和逐文件 SHA-256；"
    "B 必须沿用相同扫描根和算法复算，并检测新增、删除、重命名和内容变化。"
)
SNAPSHOT_PAYLOAD_BINDING_RULE = (
    "完整 snapshot manifest 必须位于 confirmation payload 内，以 `snapshot-v1`、UTF-8 和 LF 规范化序列化；"
    "`.gitignore` 摘要只删除唯一 managed block 的起止标记行及其中内容，保留 block 外字节。"
)
IMMUTABLE_ARTIFACT_RULE = (
    "测试点保存到 `runs/<confirmation-run-id>/test-points.md`，执行报告保存到 "
    "`runs/<confirmation-run-id>/executions/<run-id>/test-report.md`，所有文件不可变且不覆盖。"
)
IMMUTABLE_CONFIRMATION_RECEIPT_RULE = (
    "用户确认后另写不可变的 `runs/<confirmation-run-id>/confirmation.md`，不得回写 `test-points.md`。"
)
LOCAL_IGNORE_DEFAULT_RULE = (
    "Git 项目默认由 A 在 `.git/info/exclude` 维护 managed block；"
    "若现有忽略规则已精确覆盖产物目录，则直接复用且不修改任何忽略文件。"
)
TEAM_GITIGNORE_OPT_IN_RULE = (
    "只有用户明确选择团队共享忽略规则时，A 才可修改项目 `.gitignore`；"
    "该选择不得从已有规则、历史操作或普通自测请求推定。"
)
MANAGED_IGNORE_OWNER_RULE = (
    "B 只校验产物路径已被忽略且未被跟踪；B 不修改 `.git/info/exclude` 或项目 `.gitignore`，"
    "失败时停止写入并回 A 修复。"
)
REPORT_TRACEABILITY_FIELDS = {
    "execution run-id",
    "confirmation-run-id",
    "payload SHA-256",
    "代码快照 manifest",
    "业务版本",
    "确认时间",
    "耗时",
}
PRODUCTION_CONFLICT_PHRASES = (
    "生产环境的例外写入",
    "`PROD` 默认只读，任何真实写入必须单独确认",
    "`PROD` 默认只读，用户单独确认后可以真实写入",
)
CONFLICTING_RULE_PHRASES = (
    "待确认文件可以原地覆盖更新。",
    "B 可以修改 managed `.gitignore` block。",
    "Git 项目默认由 A 修改项目 `.gitignore`。",
    "A 是 managed `.gitignore` block 的唯一修改者",
    "A 可以按需修改项目 `.gitignore`。",
    "用户只要提供代码或 diff 就自动触发本技能。",
    "snapshot manifest 可以只保存路径引用，不放入确认载荷。",
    "用户确认后把确认记录回写到 `test-points.md`。",
)


def extract_managed_ignore_lines(contract: str) -> set[str] | None:
    """Return managed ignore rules, or None when the required block is absent."""
    match = re.search(
        r"^\s*# BEGIN business-self-test managed\s*$([\s\S]*?)^\s*# END business-self-test managed\s*$",
        contract,
        flags=re.MULTILINE,
    )
    if not match:
        return None
    return {
        line.strip()
        for line in match.group(1).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def is_exact_repository_relative_directory_rule(rule: str) -> bool:
    """Whether a managed ignore rule names one canonical relative directory."""
    if (
        not rule.endswith("/")
        or rule.startswith("/")
        or "\\" in rule
        or any(character in GITIGNORE_META_CHARACTERS for character in rule)
    ):
        return False

    path_parts = rule[:-1].split("/")
    return bool(path_parts) and all(
        part and part not in {".", ".."} for part in path_parts
    )


def extract_tp_table(contract: str) -> str:
    """Return the test-point field table, excluding later prose mentions."""
    section = contract.split("## 本轮确认门禁", 1)[0]
    table_start = section.find("| 字段 | 内容 |")
    if table_start == -1:
        return ""
    table_lines = []
    for line in section[table_start:].splitlines():
        if table_lines and not line.startswith("|"):
            break
        table_lines.append(line)
    return "\n".join(table_lines)


def extract_result_state_table(contract: str) -> str:
    """Return the result-status table, excluding state mentions in prose."""
    table_start = contract.find("| 结果 | 判定 |")
    if table_start == -1:
        return ""
    table_lines = []
    for line in contract[table_start:].splitlines():
        if table_lines and not line.startswith("|"):
            break
        table_lines.append(line)
    return "\n".join(table_lines)


def parse_table_first_column(table: str) -> list[str]:
    """Parse the first cell from data rows in a two-column Markdown table."""
    values = []
    for line in table.splitlines()[2:]:
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if cells:
            values.append(cells[0])
    return values


def extract_table_rows(contract: str, header_prefix: str) -> list[list[str]]:
    """Return parsed Markdown table rows beginning at the matching header."""
    lines = contract.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(header_prefix):
            rows = []
            for table_line in lines[index:]:
                if not table_line.strip().startswith("|"):
                    break
                rows.append([cell.strip() for cell in table_line.split("|")[1:-1]])
            return rows
    return []


def production_write_matrix_is_strict(contract: str) -> bool:
    """Require every write column to prohibit PROD and UNKNOWN mutations."""
    rows = extract_table_rows(contract, "| 环境 |")
    if len(rows) < 4:
        return False
    headers = rows[0]
    write_columns = [index for index, value in enumerate(headers) if "写入" in value]
    by_environment = {row[0]: row for row in rows[2:] if row}
    return bool(write_columns) and all(
        environment in by_environment
        and all(
            index < len(by_environment[environment])
            and by_environment[environment][index] == "禁止"
            for index in write_columns
        )
        for environment in ("`PROD`", "`UNKNOWN`")
    )


def frontmatter_description(content: str) -> str:
    """Read the single-line description from YAML frontmatter."""
    match = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n", content)
    if not match:
        return ""
    description = re.search(r"^description:\s*(.+)$", match.group(1), flags=re.MULTILINE)
    return description.group(1).strip() if description else ""


def heading_section(content: str, heading: str) -> str:
    """Return content below one level-2 heading up to the next level-2 heading."""
    match = re.search(
        rf"^## {re.escape(heading)}\s*$\n([\s\S]*?)(?=^## |\Z)",
        content,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else ""


def schema_details(actual: list[str], expected: set[str]) -> str:
    """Describe missing, extra, and duplicate values in a strict table schema."""
    actual_set = set(actual)
    missing = sorted(expected - actual_set)
    extra = sorted(actual_set - expected)
    duplicate = sorted({value for value in actual if actual.count(value) > 1})
    details = [f"expected exactly {len(expected)} values", f"found {len(actual)}: {actual!r}"]
    if missing:
        details.append(f"missing {missing!r}")
    if extra:
        details.append(f"extra {extra!r}")
    if duplicate:
        details.append(f"duplicate {duplicate!r}")
    return "; ".join(details)


def markdown_prose(content: str) -> str:
    """Remove fenced/indented code and inline code before inspecting links."""
    lines = []
    fence = None
    for line in content.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
        elif not line.startswith(("    ", "\t")):
            lines.append(line)
    return re.sub(r"(`+).*?\1", "", "\n".join(lines), flags=re.DOTALL)


def markdown_link_targets(content: str) -> list[str]:
    """Read inline and reference-style destinations in the package's Markdown."""
    prose = markdown_prose(content)
    destination = r'(?:<([^>\n]+)>|((?:\\.|[^\s()<>]|\([^()\n]*\))+))'
    inline = re.compile(r"!?\[[^\]\n]*\]\(\s*" + destination + r'(?:\s+"[^"\n]*"|\s+\'[^\'\n]*\'|\s+\([^()\n]*\))?\s*\)')
    targets = [match[1] or match[2] for match in inline.finditer(prose)]
    definitions = {
        " ".join(match[1].lower().split()): match[2] or match[3]
        for match in re.finditer(r"^ {0,3}\[([^]\n]+)\]:\s*" + destination, prose, flags=re.MULTILINE)
    }
    for match in re.finditer(r"!?\[([^]\n]+)\](?:\[([^]\n]*)\])?(?!\(|:)", prose):
        key = " ".join((match[2] or match[1]).lower().split())
        if key in definitions:
            targets.append(definitions[key])
    return targets


def resolve_local_links(plugin_root: Path) -> list[tuple[Path, Path]]:
    """Resolve local relative links from every Markdown document in the plugin."""
    links: list[tuple[Path, Path]] = []
    for document in sorted(plugin_root.rglob("*.md")):
        for target in markdown_link_targets(document.read_text(encoding="utf-8")):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            path = unquote(re.sub(r"\\([\\() ])", r"\1", parsed.path))
            links.append((document, (document.parent / path).resolve()))
    return links


def validate(plugin_root: Path) -> list[str]:
    """Return contract violations; an empty list means the contract passes."""
    if not plugin_root.is_dir():
        return [f"plugin root does not exist or is not a directory: {plugin_root}"]

    manifest_paths = sorted(plugin_root.rglob("plugin.json"))
    contract_path = plugin_root / CANONICAL_CONTRACT
    if not contract_path.is_file():
        return [f"canonical contract is missing: {contract_path}"]

    contract = contract_path.read_text(encoding="utf-8")
    skill_contents = {
        path: (plugin_root / path).read_text(encoding="utf-8")
        for path in REQUIRED_SKILLS
        if (plugin_root / path).is_file()
    }
    contract_lines = extract_managed_ignore_lines(contract)
    managed_ignore_lines = contract_lines or set()
    non_exact_ignore_rules = sorted(
        rule
        for rule in managed_ignore_lines
        if not is_exact_repository_relative_directory_rule(rule)
    )
    canonical_tp_table = extract_tp_table(contract)
    parsed_tp_fields = parse_table_first_column(canonical_tp_table)
    parsed_states = parse_table_first_column(extract_result_state_table(contract))
    resolved_links = resolve_local_links(plugin_root)
    missing_skills = [path for path in REQUIRED_SKILLS if not (plugin_root / path).is_file()]
    skills_without_bi = [
        path for path in REQUIRED_SKILLS
        if not any(
            source == plugin_root / path and target.name == BI_REFERENCE and target.is_file()
            for source, target in resolved_links
        )
    ]
    missing_links = [(source, target) for source, target in resolved_links if not target.exists()]
    tests_root = plugin_root / "tests"
    generated_runs = sorted((tests_root / "artifacts").glob("run-*"))
    generated_self_test_dirs = sorted(
        path for path in tests_root.rglob(".self-test") if path.is_dir()
    ) if tests_root.is_dir() else []
    generated_metadata = sorted(
        {
            *plugin_root.rglob(".DS_Store"),
            *plugin_root.rglob("*.pyc"),
            *(path for path in plugin_root.rglob("__pycache__") if path.is_dir()),
        }
    )
    generated_artifacts = [*generated_runs, *generated_self_test_dirs, *generated_metadata]
    a_skill = skill_contents.get(REQUIRED_SKILLS[0], "")
    b_skill = skill_contents.get(REQUIRED_SKILLS[1], "")
    a_description = frontmatter_description(a_skill)
    skills_missing_scan_sections = [
        path
        for path, content in skill_contents.items()
        if not heading_section(content, "快速参考")
        or not heading_section(content, "常见错误")
    ]
    all_governance_text = "\n".join([contract, *skill_contents.values()])
    conflicting_rules = [
        phrase for phrase in CONFLICTING_RULE_PHRASES if phrase in all_governance_text
    ]
    report_section = heading_section(contract, "报告与结论")
    behavior_readme_path = plugin_root / "tests/README.md"
    behavior_scenarios_path = plugin_root / "tests/skill-evals/scenarios.md"
    behavior_results_path = plugin_root / "tests/skill-evals/with-skill.md"
    behavior_readme = behavior_readme_path.read_text(encoding="utf-8") if behavior_readme_path.is_file() else ""
    behavior_scenarios = behavior_scenarios_path.read_text(encoding="utf-8") if behavior_scenarios_path.is_file() else ""
    behavior_results = behavior_results_path.read_text(encoding="utf-8") if behavior_results_path.is_file() else ""
    behavior_protocol_terms = ("无指导对照", "有技能", "至少 5")
    behavior_result_terms = (
        "无指导对照组",
        "有技能组",
        "5 个 fresh-context",
        "模型",
        "推理等级",
        "完整用户输入",
        "逐样本判定",
    )
    strict_production_policy = (
        STRICT_PRODUCTION_READ_ONLY_RULE in contract
        and production_write_matrix_is_strict(contract)
        and not any(phrase in contract for phrase in PRODUCTION_CONFLICT_PHRASES)
    )

    checks = {
        "single_manifest": len(manifest_paths) == 1,
        "required_skills": not missing_skills,
        "bi_links_exist": not skills_without_bi,
        "local_links_exist": not missing_links,
        "managed_ignore_block": contract_lines is not None and ".self-test/" in contract_lines,
        "exact_managed_ignore_rules": not non_exact_ignore_rules,
        "no_broad_ignore_rules": not FORBIDDEN_IGNORE_RULES.intersection(managed_ignore_lines),
        "canonical_target_level": len(parsed_tp_fields) == len(TP_FIELDS)
        and set(parsed_tp_fields) == TP_FIELDS,
        "four_tp_states": len(parsed_states) == len(TP_STATES)
        and set(parsed_states) == TP_STATES,
        "non_self_referential_payload_hash": PAYLOAD_HASH_OUTSIDE_RULE in contract,
        "strict_production_read_only": strict_production_policy,
        "deterministic_snapshot_manifest": SNAPSHOT_MANIFEST_RULE in contract,
        "snapshot_payload_binding": SNAPSHOT_PAYLOAD_BINDING_RULE in contract,
        "immutable_artifact_layout": IMMUTABLE_ARTIFACT_RULE in contract,
        "immutable_confirmation_receipt": IMMUTABLE_CONFIRMATION_RECEIPT_RULE in contract,
        "local_ignore_default": LOCAL_IGNORE_DEFAULT_RULE in contract,
        "team_gitignore_opt_in": TEAM_GITIGNORE_OPT_IN_RULE in contract,
        "managed_ignore_owner": MANAGED_IGNORE_OWNER_RULE in contract,
        "explicit_a_trigger": a_description.startswith(
            "Use when developers explicitly request pre-handoff business self-test"
        ),
        "required_a_fallback": "**REQUIRED SUB-SKILL:**" in b_skill
        and "`make-business-test-points`" in b_skill
        and "完整读取" in b_skill,
        "report_traceability": all(field in report_section for field in REPORT_TRACEABILITY_FIELDS),
        "skill_scan_sections": not skills_missing_scan_sections,
        "conflicting_rules": not conflicting_rules,
        "behavior_evaluation_protocol": all(
            term in behavior_readme and term in behavior_scenarios
            for term in behavior_protocol_terms
        ) and all(term in behavior_results for term in behavior_result_terms),
        "no_generated_artifacts": not generated_artifacts,
    }

    violations: list[str] = []
    if not checks["single_manifest"]:
        violations.append(
            "single_manifest: expected exactly one plugin.json, found "
            + str(len(manifest_paths))
            + ": "
            + ", ".join(str(path.relative_to(plugin_root)) for path in manifest_paths)
        )
    if not checks["required_skills"]:
        violations.append("required_skills: missing skill document(s): " + ", ".join(map(str, missing_skills)))
    if not checks["bi_links_exist"]:
        violations.append(
            "bi_links_exist: each required skill must link to an existing BI reference: "
            + ", ".join(map(str, skills_without_bi))
        )
    if not checks["local_links_exist"]:
        violations.append(
            "local_links_exist: missing local Markdown target(s): "
            + "; ".join(f"{source.relative_to(plugin_root)} -> {target}" for source, target in missing_links)
        )
    if not checks["managed_ignore_block"]:
        violations.append(
            "managed_ignore_block: missing required managed block"
            if contract_lines is None
            else "managed_ignore_block: missing required .self-test/ rule"
        )
    if not checks["exact_managed_ignore_rules"]:
        violations.append(
            "non_exact_managed_ignore_rule: managed entries must be canonical "
            "repository-relative directory rules: "
            + ", ".join(non_exact_ignore_rules)
        )
    if not checks["no_broad_ignore_rules"]:
        violations.append(
            "no_broad_ignore_rules: forbidden managed ignore rule(s): "
            + ", ".join(sorted(FORBIDDEN_IGNORE_RULES.intersection(managed_ignore_lines)))
        )
    if not checks["canonical_target_level"]:
        violations.append(
            "canonical_target_level: canonical test-point schema violation: "
            + schema_details(parsed_tp_fields, TP_FIELDS)
        )
    if not checks["four_tp_states"]:
        violations.append(
            "four_tp_states: result-status schema violation: "
            + schema_details(parsed_states, TP_STATES)
        )
    if not checks["non_self_referential_payload_hash"]:
        violations.append(
            "non_self_referential_payload_hash: confirmation payload SHA-256 must be "
            "stored outside the payload markers and excluded from its own digest"
        )
    if not checks["strict_production_read_only"]:
        violations.append(
            "strict_production_read_only: PROD and UNKNOWN environments must remain "
            "read-only without a confirmation-based write exception"
        )
    if not checks["deterministic_snapshot_manifest"]:
        violations.append(
            "deterministic_snapshot_manifest: contract must freeze roots and entries, "
            "then detect additions, deletions, renames, and content changes"
        )
    if not checks["snapshot_payload_binding"]:
        violations.append(
            "snapshot_payload_binding: canonical snapshot manifest must be embedded "
            "inside the confirmation payload with deterministic .gitignore handling"
        )
    if not checks["immutable_artifact_layout"]:
        violations.append(
            "immutable_artifact_layout: test points and reports must use immutable "
            "confirmation/execution run paths"
        )
    if not checks["immutable_confirmation_receipt"]:
        violations.append(
            "immutable_confirmation_receipt: confirmation must be written to a separate "
            "immutable receipt without modifying test-points.md"
        )
    if not checks["local_ignore_default"]:
        violations.append(
            "local_ignore_default: Git repositories must reuse an exact existing ignore "
            "rule or default to a managed .git/info/exclude block"
        )
    if not checks["team_gitignore_opt_in"]:
        violations.append(
            "team_gitignore_opt_in: project .gitignore changes require an explicit "
            "user choice to share the ignore rule with the team"
        )
    if not checks["managed_ignore_owner"]:
        violations.append(
            "managed_ignore_owner: skill B must not modify .git/info/exclude or project .gitignore"
        )
    if not checks["explicit_a_trigger"]:
        violations.append(
            "explicit_a_trigger: skill A description must require explicit business "
            "self-test or regression intent"
        )
    if not checks["required_a_fallback"]:
        violations.append(
            "required_a_fallback: skill B must declare make-business-test-points as a "
            "required sub-skill and require reading it completely"
        )
    if not checks["report_traceability"]:
        violations.append(
            "report_traceability: report contract must include execution run-id, "
            "confirmation binding, snapshot, version, confirmation time, and duration"
        )
    if not checks["skill_scan_sections"]:
        violations.append(
            "skill_scan_sections: missing Quick Reference/Common Mistakes sections: "
            + ", ".join(map(str, skills_missing_scan_sections))
        )
    if not checks["conflicting_rules"]:
        violations.append(
            "conflicting_rules: contradictory governance phrase(s) found: "
            + ", ".join(conflicting_rules)
        )
    if not checks["behavior_evaluation_protocol"]:
        violations.append(
            "behavior_evaluation_protocol: require 5+ no-guidance and with-skill "
            "fresh-context samples plus model, prompt, and per-sample judgments"
        )
    if not checks["no_generated_artifacts"]:
        violations.append(
            "no_generated_artifacts: committed/generated run artifact(s) found: "
            + ", ".join(str(path.relative_to(plugin_root)) for path in generated_artifacts)
        )
    return violations


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {Path(argv[0]).name} PLUGIN_ROOT", file=sys.stderr)
        return 1

    violations = validate(Path(argv[1]).resolve())
    if violations:
        for violation in violations:
            print(f"VIOLATION {violation}")
        return 1
    print("PASS plugin structure contract")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
