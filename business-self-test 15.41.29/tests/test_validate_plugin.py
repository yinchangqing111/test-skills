#!/usr/bin/env python3
"""Focused schema checks for the plugin validator."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


VALIDATOR_PATH = Path(__file__).with_name("validate_plugin.py")
SPEC = importlib.util.spec_from_file_location("validate_plugin", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)

TP_FIELDS = [
    "标题/目标",
    "依据",
    "优先级",
    "角色与前置",
    "操作",
    "预期",
    "来源映射",
    "目标等级",
]
TP_STATES = ["PASS", "FAIL", "BLOCKED", "NOT_RUN"]
SKILLS = ["make-business-test-points", "check-code-with-business-tests"]


def write_plugin(
    root: Path,
    fields: list[str] = TP_FIELDS,
    states: list[str] = TP_STATES,
    *,
    include_managed_block: bool = True,
    managed_ignore_lines: list[str] | None = None,
) -> None:
    (root / ".codex-plugin").mkdir()
    (root / ".codex-plugin/plugin.json").write_text("{}\n", encoding="utf-8")
    for skill in SKILLS:
        (root / "skills" / skill).mkdir(parents=True)
    (root / "references").mkdir()
    tp_rows = ["| 字段 | 内容 |", "|---|---|"] + [f"| {field} | value |" for field in fields]
    state_rows = ["| 结果 | 判定 |", "|---|---|"] + [f"| {state} | value |" for state in states]
    if managed_ignore_lines is None:
        managed_ignore_lines = [".self-test/"]
    managed_block = (
        ["# BEGIN business-self-test managed", *managed_ignore_lines, "# END business-self-test managed"]
        if include_managed_block
        else []
    )
    (root / "skills/business-test-contract.md").write_text(
        "\n".join(
            [
                *managed_block,
                "",
                "## 测试点 Markdown",
                *tp_rows,
                "",
                "## 本轮确认门禁",
                "确认载荷 SHA-256 必须位于两行载荷标记之外，不参与自身摘要计算。",
                "",
                "快照 manifest 固定记录算法版本、扫描根、基准、规范化文件条目和逐文件 SHA-256；B 必须沿用相同扫描根和算法复算，并检测新增、删除、重命名和内容变化。",
                "完整 snapshot manifest 必须位于 confirmation payload 内，以 `snapshot-v1`、UTF-8 和 LF 规范化序列化；`.gitignore` 摘要只删除唯一 managed block 的起止标记行及其中内容，保留 block 外字节。",
                "测试点保存到 `runs/<confirmation-run-id>/test-points.md`，执行报告保存到 `runs/<confirmation-run-id>/executions/<run-id>/test-report.md`，所有文件不可变且不覆盖。",
                "用户确认后另写不可变的 `runs/<confirmation-run-id>/confirmation.md`，不得回写 `test-points.md`。",
                "Git 项目默认由 A 在 `.git/info/exclude` 维护 managed block；若现有忽略规则已精确覆盖产物目录，则直接复用且不修改任何忽略文件。",
                "只有用户明确选择团队共享忽略规则时，A 才可修改项目 `.gitignore`；该选择不得从已有规则、历史操作或普通自测请求推定。",
                "B 只校验产物路径已被忽略且未被跟踪；B 不修改 `.git/info/exclude` 或项目 `.gitignore`，失败时停止写入并回 A 修复。",
                "",
                "## 报告与结论",
                "报告首节必须记录 execution run-id、confirmation-run-id、payload SHA-256、代码快照 manifest、业务版本、确认时间和耗时。",
                "",
                "`PROD` 和 `UNKNOWN` 仅允许只读检查，禁止任何真实写入；用户确认、已有凭据或时间压力都不能解除该禁令。",
                "| 环境 | 普通真实写入 | 高风险真实写入 |",
                "|---|---|---|",
                "| `NON_PROD` | 允许 | 有条件允许 |",
                "| `PROD` | 禁止 | 禁止 |",
                "| `UNKNOWN` | 禁止 | 禁止 |",
                "",
                *state_rows,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "skills/make-business-test-points/SKILL.md").write_text(
        "---\n"
        "name: make-business-test-points\n"
        "description: Use when developers explicitly request pre-handoff business self-test design or regression planning for requirements, code, diffs, or existing cases that are not yet confirmed in the current interaction.\n"
        "---\n"
        "[BI](../../references/bi-report-api-testing.md)\n"
        "[Contract](../business-test-contract.md)\n"
        "## 快速参考\n"
        "| 状态 | 动作 |\n|---|---|\n| 待确认 | 展示 |\n"
        "## 常见错误\n"
        "| 错误 | 处理 |\n|---|---|\n| 旧确认 | 重建 |\n",
        encoding="utf-8",
    )
    (root / "skills/check-code-with-business-tests/SKILL.md").write_text(
        "---\n"
        "name: check-code-with-business-tests\n"
        "description: Use only when running developer pre-handoff self-tests.\n"
        "---\n"
        "[BI](../../references/bi-report-api-testing.md)\n"
        "[Contract](../business-test-contract.md)\n"
        "**REQUIRED SUB-SKILL:** 使用 `make-business-test-points`；按名称定位并完整读取其 SKILL.md。\n"
        "## 快速参考\n"
        "| 状态 | 动作 |\n|---|---|\n| 不匹配 | 回 A |\n"
        "## 常见错误\n"
        "| 错误 | 处理 |\n|---|---|\n| 旧确认 | 回 A |\n",
        encoding="utf-8",
    )
    (root / "references/bi-report-api-testing.md").write_text("reference\n", encoding="utf-8")
    payment_dir = root / "skills/check-code-with-business-tests/references"
    payment_dir.mkdir()
    (payment_dir / "payment.md").write_text("payment\n", encoding="utf-8")
    with (root / "skills/check-code-with-business-tests/SKILL.md").open("a") as skill:
        skill.write("[Payment](references/payment.md)\n")
    (root / "tests/skill-evals").mkdir(parents=True)
    (root / "tests/skill-evals/with-skill.md").write_text(
        "# 当前行为评估\n\n"
        "无指导对照组：5 个 fresh-context 样本。\n"
        "有技能组：5 个 fresh-context 样本。\n"
        "记录模型、推理等级、完整用户输入和逐样本判定。\n",
        encoding="utf-8",
    )
    (root / "tests/README.md").write_text(
        "[Evaluation](skill-evals/with-skill.md)\n"
        "每个变体包含无指导对照和有技能样本，每组至少 5 次。\n",
        encoding="utf-8",
    )
    (root / "tests/skill-evals/scenarios.md").write_text(
        "每个变体包含无指导对照和有技能样本，每组至少 5 次。\n",
        encoding="utf-8",
    )


class ValidatePluginTest(unittest.TestCase):
    def validate(
        self,
        fields: list[str] = TP_FIELDS,
        states: list[str] = TP_STATES,
        **write_plugin_kwargs: object,
    ) -> list[str]:
        with tempfile.TemporaryDirectory(prefix="business-self-test-validator-") as temporary:
            root = Path(temporary)
            write_plugin(root, fields, states, **write_plugin_kwargs)
            return VALIDATOR.validate(root)

    def test_minimal_compliant_contract_passes(self) -> None:
        self.assertEqual(self.validate(), [])

    def test_extra_ninth_tp_field_fails(self) -> None:
        violations = self.validate(TP_FIELDS + ["额外字段"])
        self.assertTrue(any(item.startswith("canonical_target_level:") for item in violations))

    def test_duplicate_tp_field_fails(self) -> None:
        violations = self.validate(TP_FIELDS + ["目标等级"])
        self.assertTrue(any(item.startswith("canonical_target_level:") for item in violations))

    def test_extra_pending_state_fails(self) -> None:
        violations = self.validate(states=TP_STATES + ["PENDING"])
        self.assertTrue(any(item.startswith("four_tp_states:") for item in violations))

    def test_missing_managed_ignore_block_fails(self) -> None:
        violations = self.validate(include_managed_block=False)
        self.assertTrue(any(item.startswith("managed_ignore_block:") for item in violations))

    def test_managed_ignore_block_without_self_test_rule_fails(self) -> None:
        violations = self.validate(managed_ignore_lines=[".qa-agent/cases/run-123/"])
        self.assertTrue(any(item.startswith("managed_ignore_block:") for item in violations))

    def test_exact_future_artifact_rule_is_allowed(self) -> None:
        violations = self.validate(
            managed_ignore_lines=[".self-test/", "qa-output/order/"]
        )
        self.assertEqual(violations, [])

    def test_forbidden_managed_ignore_rule_fails(self) -> None:
        violations = self.validate(managed_ignore_lines=[".self-test/", "tests/"])
        self.assertTrue(any(item.startswith("no_broad_ignore_rules:") for item in violations))

    def test_all_common_source_and_test_roots_are_forbidden(self) -> None:
        for rule in ["tests/", "src/test/", "specs/", "test/", "src/", "app/", "lib/"]:
            with self.subTest(rule=rule):
                violations = self.validate(managed_ignore_lines=[".self-test/", rule])
                self.assertTrue(any(item.startswith("no_broad_ignore_rules:") for item in violations))

    def test_repository_root_and_equivalent_paths_are_rejected(self) -> None:
        for rule in ["/", "./", ".", "./tests/", "src/../src/", "tests//", "src/test/./"]:
            with self.subTest(rule=rule):
                self.assertTrue(self.validate(managed_ignore_lines=[".self-test/", rule]))

    def test_each_required_skill_must_exist(self) -> None:
        for name in SKILLS:
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                (root / "skills" / name / "SKILL.md").unlink()
                self.assertTrue(any(item.startswith("required_skills:") for item in VALIDATOR.validate(root)))

    def test_each_required_skill_must_link_bi_reference(self) -> None:
        for name in SKILLS:
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                (root / "skills" / name / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
                self.assertTrue(any(item.startswith("bi_links_exist:") for item in VALIDATOR.validate(root)))

    def test_missing_local_link_targets_are_rejected(self) -> None:
        mutations = [
            ("skills/make-business-test-points/SKILL.md", "../business-test-contract.md", "../missing-contract.md"),
            ("skills/check-code-with-business-tests/SKILL.md", "../../references/bi-report-api-testing.md", "../../missing/bi-report-api-testing.md"),
            ("skills/check-code-with-business-tests/SKILL.md", "references/payment.md", "references/missing-payment.md"),
            ("tests/README.md", "skill-evals/with-skill.md", "skill-evals/missing.md"),
        ]
        for source, original, missing in mutations:
            with self.subTest(source=source, target=missing), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                path = root / source
                path.write_text(path.read_text().replace(original, missing), encoding="utf-8")
                violations = VALIDATOR.validate(root)
                self.assertTrue(any(item.startswith("local_links_exist:") and source in item for item in violations))

    def test_reference_style_links_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            (root / "tests/README.md").write_text(
                "[Evaluation][run]\n\n[run]: skill-evals/missing.md\n", encoding="utf-8"
            )
            self.assertTrue(any(item.startswith("local_links_exist:") for item in VALIDATOR.validate(root)))

    def test_external_anchors_and_code_examples_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            (root / "tests/README.md").write_text(
                '[Evaluation](<skill-evals/with-skill.md#results> "Results")\n'
                "每个变体包含无指导对照和有技能样本，每组至少 5 次。\n"
                "[HTTP](http://example.com/missing) [HTTPS](https://example.com/missing)\n"
                "[Email](mailto:test@example.com) [Anchor](#missing)\n"
                "```md\n[Example](missing-fenced.md)\n```\n"
                "~~~md\n[Example](missing-tilde.md)\n~~~\n"
                "    [Example](missing-indented.md)\n"
                "`[Example](missing-inline.md)`\n", encoding="utf-8"
            )
            self.assertEqual(VALIDATOR.validate(root), [])

    def test_non_exact_managed_ignore_rules_fail(self) -> None:
        non_exact_rules = [
            "*",
            "**",
            "tests/**",
            ".qa-agent/cases/*",
            "src/test/**",
            "!qa-output/order/",
            "../qa-output/order/",
            "qa-output/../order/",
            "/qa-output/order/",
        ]
        for rule in non_exact_rules:
            with self.subTest(rule=rule):
                violations = self.validate(managed_ignore_lines=[".self-test/", rule])
                self.assertTrue(
                    any(item.startswith("non_exact_managed_ignore_rule:") for item in violations)
                )

    def test_confirmation_hash_must_be_outside_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "确认载荷 SHA-256 必须位于两行载荷标记之外，不参与自身摘要计算。",
                    "确认载荷 SHA-256 位于确认载荷内。",
                ),
                encoding="utf-8",
            )
            violations = VALIDATOR.validate(root)
            self.assertTrue(any(item.startswith("non_self_referential_payload_hash:") for item in violations))

    def test_production_and_unknown_environments_must_be_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "`PROD` 和 `UNKNOWN` 仅允许只读检查，禁止任何真实写入；用户确认、已有凭据或时间压力都不能解除该禁令。",
                    "`PROD` 默认只读，用户单独确认后可以真实写入。",
                ),
                encoding="utf-8",
            )
            violations = VALIDATOR.validate(root)
            self.assertTrue(any(item.startswith("strict_production_read_only:") for item in violations))

    def test_production_policy_rejects_conflicting_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8")
                + "\n生产环境的例外写入可在单独确认后执行。\n",
                encoding="utf-8",
            )
            violations = VALIDATOR.validate(root)
            self.assertTrue(any(item.startswith("strict_production_read_only:") for item in violations))

    def test_snapshot_manifest_rule_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "快照 manifest 固定记录算法版本、扫描根、基准、规范化文件条目和逐文件 SHA-256；B 必须沿用相同扫描根和算法复算，并检测新增、删除、重命名和内容变化。",
                    "快照记录相关文件。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("deterministic_snapshot_manifest:") for item in VALIDATOR.validate(root)))

    def test_immutable_artifact_layout_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "测试点保存到 `runs/<confirmation-run-id>/test-points.md`，执行报告保存到 `runs/<confirmation-run-id>/executions/<run-id>/test-report.md`，所有文件不可变且不覆盖。",
                    "测试点保存到 `test-points.md`。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("immutable_artifact_layout:") for item in VALIDATOR.validate(root)))

    def test_confirmation_receipt_must_not_mutate_test_points(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "用户确认后另写不可变的 `runs/<confirmation-run-id>/confirmation.md`，不得回写 `test-points.md`。",
                    "用户确认后把确认记录回写到 `test-points.md`。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("immutable_confirmation_receipt:") for item in VALIDATOR.validate(root)))

    def test_only_a_may_repair_managed_gitignore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "B 只校验产物路径已被忽略且未被跟踪；B 不修改 `.git/info/exclude` 或项目 `.gitignore`，失败时停止写入并回 A 修复。",
                    "A 和 B 都可以修改 managed ignore block。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("managed_ignore_owner:") for item in VALIDATOR.validate(root)))

    def test_git_info_exclude_is_the_default_local_ignore_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "Git 项目默认由 A 在 `.git/info/exclude` 维护 managed block；若现有忽略规则已精确覆盖产物目录，则直接复用且不修改任何忽略文件。",
                    "Git 项目默认由 A 修改项目 `.gitignore`。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("local_ignore_default:") for item in VALIDATOR.validate(root)))

    def test_project_gitignore_requires_explicit_team_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "只有用户明确选择团队共享忽略规则时，A 才可修改项目 `.gitignore`；该选择不得从已有规则、历史操作或普通自测请求推定。",
                    "A 可以按需修改项目 `.gitignore`。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("team_gitignore_opt_in:") for item in VALIDATOR.validate(root)))

    def test_a_description_requires_explicit_self_test_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            skill = root / "skills/make-business-test-points/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "Use when developers explicitly request pre-handoff business self-test design or regression planning for requirements, code, diffs, or existing cases that are not yet confirmed in the current interaction.",
                    "Use when developers provide requirements, code, diffs, or existing cases.",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("explicit_a_trigger:") for item in VALIDATOR.validate(root)))

    def test_b_declares_required_a_sub_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            skill = root / "skills/check-code-with-business-tests/SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace("**REQUIRED SUB-SKILL:**", "参考："),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("required_a_fallback:") for item in VALIDATOR.validate(root)))

    def test_report_traceability_fields_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace("execution run-id、", ""),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("report_traceability:") for item in VALIDATOR.validate(root)))

    def test_each_skill_has_quick_reference_and_common_mistakes(self) -> None:
        for name in SKILLS:
            with self.subTest(skill=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                skill = root / "skills" / name / "SKILL.md"
                skill.write_text(
                    skill.read_text(encoding="utf-8").replace("## 常见错误", "## 其他"),
                    encoding="utf-8",
                )
                self.assertTrue(any(item.startswith("skill_scan_sections:") for item in VALIDATOR.validate(root)))

    def test_generated_self_test_directory_under_tests_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            (root / "tests/src/.self-test").mkdir(parents=True)
            self.assertTrue(any(item.startswith("no_generated_artifacts:") for item in VALIDATOR.validate(root)))

    def test_snapshot_manifest_must_be_canonical_and_inside_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            contract.write_text(
                contract.read_text(encoding="utf-8").replace(
                    "完整 snapshot manifest 必须位于 confirmation payload 内，以 `snapshot-v1`、UTF-8 和 LF 规范化序列化；`.gitignore` 摘要只删除唯一 managed block 的起止标记行及其中内容，保留 block 外字节。",
                    "snapshot manifest 可保存为外部路径引用。",
                ),
                encoding="utf-8",
            )
            self.assertTrue(any(item.startswith("snapshot_payload_binding:") for item in VALIDATOR.validate(root)))

    def test_conflicting_rules_are_rejected_across_contract_and_skills(self) -> None:
        mutations = [
            ("skills/business-test-contract.md", "待确认文件可以原地覆盖更新。"),
            ("skills/check-code-with-business-tests/SKILL.md", "B 可以修改 managed `.gitignore` block。"),
            ("skills/make-business-test-points/SKILL.md", "用户只要提供代码或 diff 就自动触发本技能。"),
            ("skills/business-test-contract.md", "snapshot manifest 可以只保存路径引用，不放入确认载荷。"),
        ]
        for relative_path, conflicting_rule in mutations:
            with self.subTest(rule=conflicting_rule), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                path = root / relative_path
                path.write_text(path.read_text(encoding="utf-8") + "\n" + conflicting_rule + "\n", encoding="utf-8")
                self.assertTrue(any(item.startswith("conflicting_rules:") for item in VALIDATOR.validate(root)))

    def test_report_fields_must_be_in_report_section(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            contract = root / "skills/business-test-contract.md"
            content = contract.read_text(encoding="utf-8")
            trace_line = "报告首节必须记录 execution run-id、confirmation-run-id、payload SHA-256、代码快照 manifest、业务版本、确认时间和耗时。\n"
            contract.write_text(trace_line + content.replace(trace_line, ""), encoding="utf-8")
            self.assertTrue(any(item.startswith("report_traceability:") for item in VALIDATOR.validate(root)))

    def test_scan_sections_must_have_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            skill = root / "skills/make-business-test-points/SKILL.md"
            content = skill.read_text(encoding="utf-8")
            start = content.index("## 快速参考")
            end = content.index("## 常见错误")
            skill.write_text(content[:start] + "## 快速参考\n\n" + content[end:], encoding="utf-8")
            self.assertTrue(any(item.startswith("skill_scan_sections:") for item in VALIDATOR.validate(root)))

    def test_common_generated_metadata_is_rejected(self) -> None:
        generated_paths = [".DS_Store", "tests/__pycache__/module.pyc"]
        for generated_path in generated_paths:
            with self.subTest(path=generated_path), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                write_plugin(root)
                path = root / generated_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"generated")
                self.assertTrue(any(item.startswith("no_generated_artifacts:") for item in VALIDATOR.validate(root)))

    def test_behavior_evaluation_requires_repeated_controls_and_auditable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_plugin(root)
            evaluation = root / "tests/skill-evals/with-skill.md"
            evaluation.write_text("单次有技能样本通过。\n", encoding="utf-8")
            self.assertTrue(any(item.startswith("behavior_evaluation_protocol:") for item in VALIDATOR.validate(root)))


if __name__ == "__main__":
    unittest.main()
