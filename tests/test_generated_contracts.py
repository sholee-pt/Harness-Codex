from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/harness/scripts"
sys.path.insert(0, str(SCRIPTS))
import harness_agent_contract as contract
import harness_apply as apply
import harness_frontmatter as frontmatter
import harness_metadata as metadata
import harness_plan_builder as builder
import harness_state as state
import validate_harness
import test_runtime_teamplay as runtime_fixtures
from test_harness_tools import minimal_plan


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def full_topology():
    return json.loads((ROOT / "tests/fixtures/coordinated-cross-contract-plan.json").read_text())["topology"]


def coordinated(root):
    shutil.copytree(ROOT / "tests/fixtures/coordinated-cross-contract", root, dirs_exist_ok=True)
    draft = runtime_fixtures.DeterministicPlanBuilderTests()._draft("coordinated-cross-contract-plan.json")
    return builder.materialize_plan(draft, root=root)


def write_and_reseal(root, path, text):
    target = root / path
    target.write_text(text, encoding="utf-8", newline="\n")
    manifest_path = root / ".harness/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["managedFiles"]:
        if entry["path"] == path:
            entry["sha256"] = state.digest_bytes(target.read_bytes())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def legacy_installation(root, plan):
    apply.apply_application(apply.build_application(root, plan))
    for agent in plan["topology"]["agents"]:
        path = root / agent["path"]
        text = path.read_text(encoding="utf-8")
        instructions = tomllib.loads(text)["developer_instructions"].replace(contract.render(agent, plan["topology"]), "")
        write_and_reseal(root, agent["path"], contract.replace_instructions(text, instructions))
    path = root / ".harness/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["schemaVersion"] = metadata.PREVIOUS_MANIFEST_SCHEMA_VERSION
    manifest["workspace"]["scope"] = "local-only"
    manifest["workspace"]["gitProtection"] = {"mode": "not-applicable", "patterns": []}
    manifest.pop("artifactContractVersion")
    manifest["generator"]["version"] = "7.6"
    path.write_text(json.dumps(manifest), encoding="utf-8")


class FrontmatterTests(unittest.TestCase):
    def test_documented_acceptance_and_rejection_corpus(self):
        cases = json.loads((ROOT / "tests/fixtures/frontmatter-cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                if case["expected"] is None:
                    with self.assertRaises(frontmatter.FrontmatterError):
                        frontmatter.parse(case["header"])
                else:
                    self.assertEqual(frontmatter.parse(case["header"]), case["expected"])
                    rendered = frontmatter.render(**case["expected"])
                    self.assertEqual(frontmatter.parse(rendered), case["expected"])

    def test_invalid_inputs_fail_before_writes_and_after_hash_resealing(self):
        cases = json.loads((ROOT / "tests/fixtures/frontmatter-cases.json").read_text())["cases"]
        for case in cases:
            # Raw surrogate strings cannot be written as UTF-8 at all.
            if case["id"] == "raw-surrogate":
                continue
            with self.subTest(case=case["id"]), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = minimal_plan(root)
                original = plan["artifacts"][0]["content"]
                content = case["header"] + original.split("---\n", 2)[2]
                changed = copy.deepcopy(plan)
                changed["artifacts"][0]["content"] = content
                before = snapshot(root)
                if case["expected"] is None:
                    with self.assertRaises(apply.PlanError):
                        apply.build_application(root, changed)
                    self.assertEqual(snapshot(root), before)
                else:
                    self.assertTrue(apply.build_application(root, changed)["report"]["valid"])
                apply.apply_application(apply.build_application(root, plan))
                write_and_reseal(root, ".agents/skills/project-harness/SKILL.md", content)
                report = validate_harness.Validator(root).run()
                self.assertEqual(report["valid"], case["expected"] is not None, report["errors"])
                if case["expected"] is None:
                    self.assertEqual(report["installationStatus"], "invalid")
                    self.assertTrue(any("invalid skill" in error for error in report["errors"]))

    def test_builder_also_rejects_invalid_skill_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            draft = minimal_plan(root)
            draft["authoringContractVersion"] = metadata.AUTHORING_CONTRACT_VERSION
            draft["artifacts"][0]["content"] = draft["artifacts"][0]["content"].replace("description: Coordinate fixture work when repository-wide routing is needed.", "description: [bad]")
            with self.assertRaises(builder.PlanBuilderError):
                builder.materialize_plan(draft, root=root)


class AgentContractTests(unittest.TestCase):
    def test_full_builder_supports_escaped_toml_strings_and_repeated_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "tests/fixtures/coordinated-cross-contract", root, dirs_exist_ok=True)
            draft = runtime_fixtures.DeterministicPlanBuilderTests()._draft("coordinated-cross-contract-plan.json")
            for artifact in draft["artifacts"]:
                if artifact["path"].startswith(".codex/agents/"):
                    instructions = tomllib.loads(artifact["content"])["developer_instructions"]
                    artifact["content"] = contract.replace_instructions(artifact["content"], instructions)
            plan = builder.materialize_plan(draft, root=root)
            self.assertTrue(apply.build_application(root, plan)["report"]["valid"])
            repeated = copy.deepcopy(plan)
            repeated["authoringContractVersion"] = metadata.AUTHORING_CONTRACT_VERSION
            self.assertEqual(builder.materialize_plan(repeated, root=root), plan)

    def test_replacement_ignores_a_fake_field_inside_another_multiline_setting(self):
        topology = full_topology()
        source = 'description = """Example:\ndeveloper_instructions = "fake"\n"""\n"developer_instructions" = "' + contract.PLACEHOLDER + '"\n'
        rendered = contract.materialize(source, topology["agents"][0], topology)
        self.assertEqual(tomllib.loads(source)["description"], tomllib.loads(rendered)["description"])
        contract.validate(tomllib.loads(rendered)["developer_instructions"], topology["agents"][0], topology)

    def test_partial_duplicate_and_unmaterialized_contracts_fail(self):
        topology = full_topology()
        agent = topology["agents"][0]
        block = contract.render(agent, topology)
        for value in (contract.BEGIN, contract.END, block + block, contract.PLACEHOLDER):
            with self.subTest(value=value[:60]), self.assertRaises(contract.AgentContractError):
                contract.validate(value, agent, topology, allow_missing=True)

    def test_builder_preserves_other_toml_settings_and_decoded_instruction_values(self):
        topology = full_topology()
        agent = topology["agents"][0]
        for quote in ('"""', "'''", '"'):
            with self.subTest(quote=quote):
                instructions = "Use the contract. " + contract.PLACEHOLDER
                value = json.dumps(instructions) if quote == '"' else quote + instructions + quote
                source = 'name = "api_producer"\ndescription = "Review \\u03b1"\nmodel = "fixture-model"\nsandbox_mode = "read-only"\ndeveloper_instructions = ' + value + '\n[settings]\npaths = ["a", "b"]\n'
                original = tomllib.loads(source)
                result = contract.materialize(source, agent, topology)
                parsed = tomllib.loads(result)
                contract.validate(parsed["developer_instructions"], agent, topology)
                parsed.pop("developer_instructions")
                original.pop("developer_instructions")
                self.assertEqual(parsed, original)
                self.assertEqual(contract.materialize(result, agent, topology), result)

    def test_placeholder_in_other_field_or_comment_is_not_a_contract(self):
        topology = full_topology()
        agent = topology["agents"][0]
        for location in (f'description = "{contract.PLACEHOLDER}"', f'# {contract.PLACEHOLDER}'):
            source = location + '\ndeveloper_instructions = "Nothing here."\n'
            with self.subTest(location=location), self.assertRaises(contract.AgentContractError):
                contract.materialize(source, agent, topology)

    def test_topology_changes_invalidate_the_bound_contract(self):
        topology = full_topology()
        agent = topology["agents"][0]
        instructions = contract.render(agent, topology)
        mutations = [
            lambda a, t: a.update(responsibility="A different responsibility."),
            lambda a, t: a.update(scope="cross-boundary"),
            lambda a, t: a["boundaryRefs"].append("storage-contract"),
            lambda a, t: a["skills"].append("project-harness"),
            lambda a, t: a["fileAccess"][0].update(scope="elsewhere/**"),
            lambda a, t: a["fileAccess"][0].update(mode="read"),
            lambda a, t: a["fileAccess"][0].update(concurrencyGroup="other"),
            lambda a, t: t["executionPhases"][0].update(order=3),
            lambda a, t: t["handoffs"][0].update(verification="A new check."),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                changed = copy.deepcopy(topology)
                altered = changed["agents"][0]
                mutate(altered, changed)
                with self.assertRaises(contract.AgentContractError):
                    contract.validate(instructions, altered, changed)

    def test_stale_block_is_not_silently_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            plan["topology"]["agents"][0]["responsibility"] = "Changed responsibility."
            with self.assertRaises(apply.PlanError):
                apply.build_application(root, plan)
            plan["authoringContractVersion"] = metadata.AUTHORING_CONTRACT_VERSION
            with self.assertRaises(builder.PlanBuilderError):
                builder.materialize_plan(plan, root=root)

    def test_installed_contract_tampering_fails_with_matching_file_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            apply.apply_application(apply.build_application(root, plan))
            agent = plan["topology"]["agents"][0]
            source = (root / agent["path"]).read_text(encoding="utf-8")
            instructions = tomllib.loads(source)["developer_instructions"].replace('"contracts/**"', '"outside/**"')
            write_and_reseal(root, agent["path"], contract.replace_instructions(source, instructions))
            report = validate_harness.Validator(root).run()
            self.assertEqual(report["installationStatus"], "invalid")
            self.assertTrue(any("differs from topology" in error for error in report["errors"]))

    def test_free_prose_is_not_claimed_to_be_semantically_verified(self):
        topology = full_topology()
        agent = topology["agents"][0]
        contract.validate(contract.render(agent, topology) + "\nYou may also edit elsewhere/**.", agent, topology)


class UpgradeTests(unittest.TestCase):
    def test_unknown_and_inconsistent_generator_metadata_fails(self):
        for generator, marker in (({"version": "9.0"}, 1), ({"version": "7.6"}, 1), ({"version": []}, 1), (None, 1)):
            with self.subTest(generator=generator), self.assertRaises(ValueError):
                metadata.artifact_contract_state({"generator": generator, "artifactContractVersion": marker})

    def test_clean_legacy_installation_requires_upgrade_then_updates_without_rewriting_on_noop(self):
        for primary_only in (True, False):
            with self.subTest(primary_only=primary_only), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                plan = minimal_plan(root) if primary_only else coordinated(root)
                legacy_installation(root, plan)
                before = snapshot(root)
                report = validate_harness.Validator(root).run()
                self.assertEqual(report["installationStatus"], "upgrade-required", report["errors"])
                self.assertFalse(report["valid"])
                self.assertTrue(report["integrityValid"])
                self.assertEqual(report["errors"], [])
                self.assertEqual(snapshot(root), before)
                application = apply.build_application(root, plan)
                self.assertEqual(snapshot(root), before)
                apply.apply_application(application)
                self.assertTrue(validate_harness.Validator(root).run()["valid"])
                updated = snapshot(root)
                self.assertEqual(apply.apply_application(apply.build_application(root, plan))["writes"], 0)
                self.assertEqual(snapshot(root), updated)

    def test_legacy_invalid_frontmatter_is_not_hidden_by_upgrade_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = minimal_plan(root)
            legacy_installation(root, plan)
            text = plan["artifacts"][0]["content"].replace("description: Coordinate fixture work when repository-wide routing is needed.", "description: [bad]")
            write_and_reseal(root, plan["artifacts"][0]["path"], text)
            report = validate_harness.Validator(root).run()
            self.assertEqual(report["installationStatus"], "invalid")
            self.assertFalse(report["integrityValid"])

    def test_external_edits_are_not_hidden_or_overwritten_by_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            legacy_installation(root, plan)
            path = root / plan["topology"]["agents"][0]["path"]
            path.write_text(path.read_text() + "\n# User edit\n")
            before = snapshot(root)
            self.assertEqual(validate_harness.Validator(root).run()["installationStatus"], "invalid")
            with self.assertRaises(apply.PlanError):
                apply.build_application(root, plan)
            self.assertEqual(snapshot(root), before)

    def test_missing_or_invalid_current_contract_metadata_is_an_error(self):
        for value in (None, True, 1, "2"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                apply.apply_application(apply.build_application(root, minimal_plan(root)))
                path = root / ".harness/manifest.json"
                manifest = json.loads(path.read_text())
                if value is None:
                    manifest.pop("artifactContractVersion")
                else:
                    manifest["artifactContractVersion"] = value
                path.write_text(json.dumps(manifest))
                report = validate_harness.Validator(root).run()
                self.assertEqual(report["installationStatus"], "invalid")

    def test_missing_current_agent_block_is_not_a_legacy_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = coordinated(root)
            legacy_installation(root, plan)
            path = root / ".harness/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["generator"]["version"] = metadata.HARNESS_VERSION
            manifest["artifactContractVersion"] = metadata.ARTIFACT_CONTRACT_VERSION
            manifest["schemaVersion"] = metadata.MANIFEST_SCHEMA_VERSION
            manifest["workspace"]["scope"] = "project-local"
            manifest["workspace"]["gitProtection"] = {"mode": "not-managed", "patterns": []}
            path.write_text(json.dumps(manifest))
            self.assertEqual(validate_harness.Validator(root).run()["installationStatus"], "invalid")

    def test_cli_upgrade_exit_status_is_distinct_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy_installation(root, minimal_plan(root))
            before = snapshot(root)
            for script, args in (("validate_harness.py", [str(root)]), ("harness_doctor.py", ["--root", str(root)])):
                with self.subTest(script=script):
                    result = subprocess.run([sys.executable, "-B", str(SCRIPTS / script), *args], capture_output=True, text=True, encoding="utf-8")
                    self.assertEqual(result.returncode, 2, result.stderr)
                    report = json.loads(result.stdout)
                    self.assertEqual(report["installationStatus"], "upgrade-required")
                    self.assertFalse(report["valid"])
            self.assertEqual(snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
