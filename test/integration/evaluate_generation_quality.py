#!/usr/bin/env python3
"""Opt-in generation plus task comparison from an unconfigured held-out project."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / '.agents/skills/harness/scripts'))

import harness_eval as evaluation
import harness_eval_capture as capture
import harness_eval_types as types
import harness_metadata
import harness_state
from validate_harness import Validator
from harness_cli.paths import checked_path, project_root
from harness_cli.project import _configuration_prompt
from harness_cli.project_installer import install

MAX_FILES = 4096
MAX_BYTES = 64 * 1024 * 1024
SKIP = {'.git', '__pycache__', '.pytest_cache'}


def snapshot(root, *, generated=False):
    """Bound the selected input and reject links instead of following outside sources."""
    entries, total, pending = {}, 0, [root]
    while pending:
        current = pending.pop()
        for path in sorted(current.iterdir()):
            if path.name in SKIP:
                continue
            checked_path(path)
            before = path.stat()
            name = path.relative_to(root).as_posix()
            if len(entries) >= MAX_FILES + (2048 if generated else 0):
                raise ValueError('Select a held-out project with at most 4096 file/directory entries.')
            if stat.S_ISDIR(before.st_mode):
                entries[name] = (None, stat.S_IMODE(before.st_mode))
                pending.append(path)
                continue
            if not stat.S_ISREG(before.st_mode) or before.st_size > 8 * 1024 * 1024 or total + before.st_size > MAX_BYTES + (16 * 1024 * 1024 if generated else 0):
                raise ValueError('Held-out input requires regular files, at most 8 MiB/file and 64 MiB total.')
            with path.open('rb') as stream:
                data = stream.read(8 * 1024 * 1024 + 1)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or len(data) != before.st_size:
                raise ValueError('Project changed while reading; choose a stable held-out snapshot.')
            entries[name] = (data, stat.S_IMODE(before.st_mode))
            total += len(data)
    return entries


def materialize(root, entries):
    root.mkdir(parents=True)
    for name, (data, mode) in entries.items():
        path = root / name
        if data is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)
    for name, (data, mode) in reversed(list(entries.items())):
        if data is None:
            (root / name).chmod(mode)


def text_input(path):
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError('Brief and task inputs must be regular UTF-8 files of at most 64 KiB.')
    value = path.read_text(encoding='utf-8-sig')
    if not value.strip() or '\0' in value:
        raise ValueError('Brief and task inputs must contain nonempty text without NUL.')
    return value


def experiment_identity(brief, task, profile):
    """Bind reports to actual inputs and guidance without retaining their content."""
    guidance = snapshot(REPO / '.agents/skills/harness', generated=True)
    helpers = snapshot(REPO / 'harness_cli', generated=True)
    def fingerprint(entries):
        return types.digest_bytes(types.canonical_bytes({name: [types.digest_bytes(data) if data is not None else None, mode]
            for name, (data, mode) in entries.items()}))
    return {'contract': 'fresh-generation-inputs-v1', 'harnessVersion': harness_metadata.HARNESS_VERSION,
            'briefSha256': types.digest_bytes(brief.encode('utf-8')),
            'taskSha256': types.digest_bytes(task.encode('utf-8')),
            'verificationSha256': types.digest_bytes(types.canonical_bytes(profile)),
            'generatorSha256': fingerprint(guidance), 'managementSha256': fingerprint(helpers),
            'runnerSha256': types.digest_bytes(Path(__file__).read_bytes())}


def retain_generation(root, before, destination, *, instruction_names=()):
    """Retain only bounded generated candidates in an explicitly selected private directory."""
    after = snapshot(root, generated=True)
    names = {name for name, (data, _) in after.items() if data is not None and after[name] != before.get(name)
        and (name.startswith('.harness/') or name.startswith('.codex/agents/')
             or (name.startswith('.agents/skills/') and not name.startswith('.agents/skills/harness/')))}
    retained = {name: after[name][0] for name in names}
    if '.harness/manifest.json' in after:
        try:
            manifest = json.loads(after['.harness/manifest.json'][0])
            managed = manifest.get('managedFiles', []) if isinstance(manifest, dict) else []
            for item in managed if isinstance(managed, list) else []:
                name = item.get('path') if isinstance(item, dict) else None
                if (isinstance(name, str) and name in instruction_names and item.get('kind') == 'managed-block'
                        and name in after and after[name][0] is not None and after[name] != before.get(name)):
                    try:
                        retained[name] = harness_state.extract_managed_block(after[name][0].decode('utf-8')).encode('utf-8')
                    except (harness_state.StateError, UnicodeError):
                        pass
        except (ValueError, UnicodeError):
            pass
    destination.mkdir(mode=0o700)
    total = 0
    for name in sorted(retained):
        path = destination / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = retained[name]
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(data)
        total += len(data)
    return {'state': 'retained', 'fileCount': len(retained), 'bytes': total,
            'content': 'Generated candidates, including failed drafts; retention does not establish validity.'}


def isolated_home(source, destination):
    """Reuse only the explicitly selected authentication, never mutable user settings."""
    evaluation._assert_clean_codex_home(source)
    destination.mkdir(mode=0o700, parents=True)
    auth = checked_path(source / 'auth.json')
    if auth.exists():
        if not auth.is_file() or auth.stat().st_size > 64 * 1024:
            raise ValueError('The dedicated authentication file is not a bounded regular file.')
        with auth.open('rb') as stream:
            data = stream.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ValueError('The dedicated authentication file exceeds its bound.')
        target = destination / 'auth.json'
        with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
            stream.write(data)
    return destination


def invoke(args, root, prompt, home):
    codex_home = home / 'codex'
    started = time.monotonic()
    credential_cleanup = True
    capture_attempted = False
    try:
        isolated_home(args.codex_home, codex_home)
        capture_attempted = True
        summary, code, elapsed, cleanup, version = capture.run_codex_jsonl(
            repository=root, prompt=prompt, sandbox='workspace-write', timeout_seconds=args.timeout,
            codex_binary=args.codex_binary, codex_home=codex_home, user_home=home / 'user',
            model=args.model, reasoning_effort=args.reasoning_effort,
            extra_args=['--skip-git-repo-check'])
        result = {'state': 'completed' if code == 0 and summary.completion == 'completed' and cleanup else 'failed',
                'processExitCode': code, 'wallTimeMs': elapsed, 'processCleanupVerified': cleanup,
                'codexVersion': version, 'terminalEventObserved': summary.terminal_event_observed,
                'parserCompatibility': summary.parser_compatibility, 'reportedUsage': summary.usage,
                'observedCounts': summary.counts, 'observedSubagentEvents': summary.counts.get('subagent'),
                'usageCoverage': 'Reported terminal counters; child and account-wide coverage not established.'}
    except (OSError, ValueError, types.EvaluationError) as exc:
        result = {'state': 'failed', 'failureKind': type(exc).__name__,
                'wallTimeMs': int((time.monotonic() - started) * 1000), 'processCleanupVerified': False,
                'reportedUsage': {}, 'observedCounts': {}, 'observedSubagentEvents': None}
    finally:
        try:
            (codex_home / 'auth.json').unlink(missing_ok=True)
            credential_cleanup = not (codex_home / 'auth.json').exists()
        except OSError:
            credential_cleanup = False
    result['credentialCleanupVerified'] = credential_cleanup
    result['captureAttempted'] = capture_attempted
    if not credential_cleanup:
        result['state'] = 'failed'
        result['processCleanupVerified'] = False
    return result


def generation_preserved(root, before):
    """A generation phase must not solve the held-out task by editing application code."""
    after = snapshot(root, generated=True)
    manifest = json.loads((root / '.harness/manifest.json').read_text(encoding='utf-8'))
    owned = {item['path']: item.get('kind', 'file') for item in manifest['managedFiles']}
    for name, (data, mode) in before.items():
        if data is None:
            if after.get(name) != (None, mode):
                return False
            continue
        current = after.get(name)
        if owned.get(name) == 'managed-block' and current is not None:
            if (harness_state.instruction_user_content(current[0]) != data
                    or current[1] != mode):
                return False
        elif current != (data, mode):
            return False
    for name, (data, _) in after.items():
        if data is not None and name not in before and name not in owned and not name.startswith(('.harness/', '.agents/skills/harness/')):
            return False
    return True


def verify(root, profile):
    started = time.monotonic()
    try:
        before = snapshot(root, generated=True)
        result, cleanup = evaluation._run_verification(root=root, profile=profile,
            profile_digest=types.digest_bytes(types.canonical_bytes(profile)), check_ref='held-out-check')
        after = snapshot(root, generated=True)
        time.sleep(evaluation.VERIFICATION_QUIESCENCE_SECONDS)
        stable = after == snapshot(root, generated=True)
        unchanged = before == after and stable
        return {'result': result['result'], 'exitCode': result['exitCode'], 'cleanupVerified': cleanup,
                'workspaceUnchanged': unchanged, 'passed': result['result'] == 'passed' and cleanup and unchanged,
                'wallTimeMs': int((time.monotonic() - started) * 1000)}
    except (OSError, ValueError, types.EvaluationError) as exc:
        return {'result': 'failed', 'passed': False, 'failureKind': type(exc).__name__,
                'wallTimeMs': int((time.monotonic() - started) * 1000)}


def matches(root, expected, *, generated=False):
    try:
        return snapshot(root, generated=generated) == expected
    except (OSError, ValueError):
        return False


def same_experiment(identity, brief, task, profile):
    try:
        return experiment_identity(brief, task, profile) == identity
    except (OSError, ValueError):
        return False


def skipped_state(report):
    reason = report.get('stoppedReason')
    return 'skipped-cleanup-unverified' if reason == 'process-cleanup-unverified' else 'skipped-' + reason


def run(args):
    started = time.monotonic()
    root = project_root(args.project)
    for name in ('.harness', '.agents/skills/harness', '.agents/skills/project-harness'):
        if os.path.lexists(root / name):
            raise ValueError('Select a raw held-out project without a generated Harness installation.')
    if not 1 <= args.repetitions <= 10 or not math.isfinite(args.timeout) or not 0 < args.timeout <= 3600:
        raise ValueError('Use 1-10 repetitions and a per-phase timeout of at most 3600 seconds.')
    for path in (args.task_file, args.verification):
        if Path(path).resolve().is_relative_to(root):
            raise ValueError('Keep the held-out task and verification profile outside the generation project.')
    if args.output is not None:
        output = checked_path(args.output)
        if output.is_relative_to(root) or output.exists():
            raise ValueError('Choose a new report path outside the source project.')
    evidence_dir = checked_path(args.evidence_dir) if args.evidence_dir is not None else None
    if evidence_dir is not None:
        if evidence_dir.exists() or evidence_dir.is_relative_to(root) or root.is_relative_to(evidence_dir):
            raise ValueError('Choose a new private evidence directory separate from the source project.')
        if args.output is not None and (checked_path(args.output).is_relative_to(evidence_dir)
                                        or evidence_dir.is_relative_to(checked_path(args.output))):
            raise ValueError('Keep the metadata report separate from generated artifact evidence.')
    brief, task = text_input(args.brief_file), text_input(args.task_file)
    profile = evaluation._verification_profile(checked_path(args.verification))
    if not math.isfinite(profile['timeoutSeconds']) or profile['timeoutSeconds'] > 300:
        raise ValueError('Verification must have a finite timeout of at most 300 seconds.')
    source = snapshot(root)
    try:
        instruction_names = harness_state.project_instruction_candidates(root)
    except (OSError, harness_state.StateError):
        instruction_names = list(harness_state.DEFAULT_INSTRUCTION_CANDIDATES)
    fingerprint = hashlib.sha256(types.canonical_bytes({name: [hashlib.sha256(data).hexdigest() if data is not None else None, mode]
        for name, (data, mode) in source.items()})).hexdigest()
    orders = evaluation._paired_arm_orders(args.repetitions, args.order, args.seed)
    if args.order == 'counterbalanced' and random.Random(args.seed).getrandbits(1):
        orders = [list(reversed(order)) for order in orders]
    report = {'schemaVersion': 1, 'evaluation': 'generation-and-task-quality', 'dryRun': not args.live,
              'liveCodexInvoked': False, 'requestedPairs': args.repetitions, 'generationDenominator': args.repetitions,
              'maxCodexRuns': 3 * args.repetitions, 'sourceFingerprint': fingerprint,
              'maxCodexRunSeconds': 3 * args.repetitions * args.timeout,
              'maxVerificationSeconds': 2 * args.repetitions * profile['timeoutSeconds'],
              'requestedModel': args.model or 'native default', 'requestedReasoningEffort': args.reasoning_effort,
              'seed': args.seed,
              'experimentIdentity': experiment_identity(brief, task, profile),
              'artifactRetention': {'enabled': evidence_dir is not None,
                                    'maxBytes': args.repetitions * (MAX_BYTES + 16 * 1024 * 1024) if evidence_dir is not None else 0},
              'fileCount': sum(data is not None for data, _ in source.values()), 'orders': orders,
              'rawPromptsStored': False, 'semanticBenefit': 'not-measured', 'automaticImprovement': False,
              'scope': 'Static generation validity and one user-selected task/check per pair; descriptive evidence only.',
              'limitations': ['Held-out provenance is supplied by the user, not independently certified.',
                              'Passing the supplied check is not a semantic-quality or cost-effectiveness guarantee.',
                              'Subagent event counts do not establish native skill discovery or successful delegation.',
                              'Failed or interrupted inference can incur usage without returning counters.',
                              'The native-run limit does not bound provider requests or child inference within a run.',
                              'External services used by the selected project or check are not simulated.'], 'pairs': []}
    if not args.live:
        return report
    if args.codex_home is None:
        raise ValueError('--live requires an existing dedicated --codex-home with authentication only.')
    args.codex_home = checked_path(args.codex_home)
    evaluation._assert_clean_codex_home(args.codex_home)
    if args.codex_home.is_relative_to(root) or root.is_relative_to(args.codex_home):
        raise ValueError('Dedicated Codex authentication must be separate from the source project.')
    if args.output is not None and checked_path(args.output).is_relative_to(args.codex_home):
        raise ValueError('Keep evaluation reports outside the dedicated authentication directory.')
    if evidence_dir is not None:
        if evidence_dir.is_relative_to(args.codex_home) or args.codex_home.is_relative_to(evidence_dir):
            raise ValueError('Keep generated artifact evidence separate from dedicated authentication.')
        evidence_dir.mkdir(mode=0o700, parents=True)
    report['isolationGaps'] = evaluation._known_skill_isolation_gaps(codex_home=args.codex_home,
        user_home=Path(tempfile.gettempdir()) / 'harness-generation-uncreated-home')
    if '.codex/config.toml' in source:
        report['isolationGaps'].append('project-config-load-unverified')
    if any(name.startswith('.codex/agents/') and data is not None for name, (data, _) in source.items()):
        report['isolationGaps'].append('project-agent-load-unverified')
    with tempfile.TemporaryDirectory(prefix='harness-generation-quality-') as folder:
        base = Path(folder)
        for index, order in enumerate(orders, 1):
            if not same_experiment(report['experimentIdentity'], brief, task, profile):
                report['stoppedReason'] = 'experiment-sources-changed'
            if report.get('stoppedReason'):
                report['pairs'].append({'index': index, 'order': order,
                    'generation': {'state': skipped_state(report), 'passed': False},
                    'arms': {arm: {'state': skipped_state(report), 'passed': False} for arm in order},
                    'isolationPreserved': False, 'endToEndHarnessPassed': False})
                continue
            pair_root = base / str(index)
            arms = {name: pair_root / name for name in ('baseline', 'harness')}
            for arm in arms.values():
                materialize(arm, source)
            pair = {'index': index, 'order': order, 'generation': {}, 'arms': {}, 'isolationPreserved': True}
            report['pairs'].append(pair)
            generation_started = time.monotonic()
            try:
                install(arms['harness'], source=REPO / '.agents/skills/harness')
                generation = invoke(args, arms['harness'], _configuration_prompt(brief), pair_root / 'generation-home')
                report['liveCodexInvoked'] |= generation['captureAttempted']
                pair['generation'] = generation
                if not generation.get('processCleanupVerified'):
                    report['stoppedReason'] = 'process-cleanup-unverified'
                    generation['passed'] = False
                else:
                    validation = Validator(arms['harness']).run()
                    generation['valid'] = bool(validation.get('valid'))
                    generation['validationErrorCount'] = len(validation.get('errors', []))
                    generation['projectPreserved'] = generation['valid'] and generation_preserved(arms['harness'], source)
                    generation['passed'] = generation['state'] == 'completed' and generation['valid'] and generation['projectPreserved']
            except (OSError, ValueError, types.EvaluationError) as exc:
                pair['generation'].update(state='failed', passed=False, failureKind=type(exc).__name__)
            if not same_experiment(report['experimentIdentity'], brief, task, profile):
                report['stoppedReason'] = 'experiment-sources-changed'
                pair['generation']['passed'] = False
            pair['generation']['totalPhaseWallTimeMs'] = int((time.monotonic() - generation_started) * 1000)
            if evidence_dir is not None:
                if report.get('stoppedReason'):
                    pair['generation']['artifactRetention'] = {'state': skipped_state(report)}
                else:
                    try:
                        pair['generation']['artifactRetention'] = retain_generation(arms['harness'], source, evidence_dir / ('pair-' + str(index)), instruction_names=instruction_names)
                    except (OSError, ValueError) as exc:
                        pair['generation']['artifactRetention'] = {'state': 'failed', 'failureKind': type(exc).__name__}
            states = {}
            try:
                states = {arm: snapshot(path, generated=True) for arm, path in arms.items()}
                pair['isolationPreserved'] = not report.get('stoppedReason') and states['baseline'] == source and snapshot(root) == source
            except (OSError, ValueError):
                pair['isolationPreserved'] = False
            if not pair['isolationPreserved']:
                pair['generation']['passed'] = False
            for arm in order:
                if not same_experiment(report['experimentIdentity'], brief, task, profile):
                    report['stoppedReason'] = 'experiment-sources-changed'
                    pair['isolationPreserved'] = False
                if not pair['isolationPreserved']:
                    pair['arms'][arm] = {'state': skipped_state(report) if report.get('stoppedReason') else 'skipped-pair-contaminated', 'passed': False}
                    continue
                if arm == 'harness' and not pair['generation'].get('passed'):
                    pair['arms'][arm] = {'state': 'skipped-generation-failed', 'passed': False}
                    continue
                peer = 'harness' if arm == 'baseline' else 'baseline'
                if not (matches(arms[arm], states[arm], generated=True)
                        and matches(arms[peer], states[peer], generated=True) and matches(root, source)):
                    pair['isolationPreserved'] = False
                    pair['arms'][arm] = {'state': 'skipped-pair-contaminated', 'passed': False}
                    continue
                outcome = invoke(args, arms[arm], task, pair_root / (arm + '-task-home'))
                report['liveCodexInvoked'] |= outcome['captureAttempted']
                if not outcome.get('processCleanupVerified'):
                    report['stoppedReason'] = 'process-cleanup-unverified'
                if not same_experiment(report['experimentIdentity'], brief, task, profile):
                    report['stoppedReason'] = 'experiment-sources-changed'
                pair['isolationPreserved'] = not report.get('stoppedReason') and matches(arms[peer], states[peer], generated=True) and matches(root, source)
                outcome['verification'] = (verify(arms[arm], profile) if outcome.get('processCleanupVerified') and pair['isolationPreserved'] else
                    {'result': 'not-run', 'passed': False, 'reason': 'inference-cleanup-or-isolation-unverified'})
                if outcome['verification']['result'] != 'not-run' and not outcome['verification'].get('cleanupVerified'):
                    report['stoppedReason'] = 'process-cleanup-unverified'
                    pair['isolationPreserved'] = False
                outcome['passed'] = outcome['state'] == 'completed' and outcome['verification']['passed']
                pair['arms'][arm] = outcome
                try:
                    pair['isolationPreserved'] = pair['isolationPreserved'] and matches(arms[peer], states[peer], generated=True) and matches(root, source)
                    states[arm] = snapshot(arms[arm], generated=True)
                except (OSError, ValueError):
                    pair['isolationPreserved'] = False
                if not same_experiment(report['experimentIdentity'], brief, task, profile):
                    report['stoppedReason'] = 'experiment-sources-changed'
                    pair['isolationPreserved'] = False
            if not pair['isolationPreserved']:
                for outcome in pair['arms'].values():
                    outcome['passed'] = False
                    outcome['comparisonExcluded'] = report.get('stoppedReason', 'peer-or-source-changed')
            pair['endToEndHarnessPassed'] = bool(pair['generation'].get('passed') and pair['arms']['harness']['passed'])
        report['sourceUnchanged'] = matches(root, source)
        report['experimentSourcesUnchanged'] = same_experiment(report['experimentIdentity'], brief, task, profile)
    report['generationPassed'] = sum(pair['generation'].get('passed', False) for pair in report['pairs'])
    report['generationFailed'] = args.repetitions - report['generationPassed']
    report['baselineVerifiedPassed'] = sum(pair['arms']['baseline']['passed'] for pair in report['pairs'])
    report['endToEndHarnessPassed'] = sum(pair['endToEndHarnessPassed'] for pair in report['pairs'])
    report['generationSuccessRate'] = report['generationPassed'] / args.repetitions
    report['endToEndHarnessSuccessRate'] = report['endToEndHarnessPassed'] / args.repetitions
    report['codexRunAttempts'] = sum(int(pair['generation'].get('captureAttempted', False)) +
        sum(arm.get('captureAttempted', False) for arm in pair['arms'].values()) for pair in report['pairs'])
    report['runnerWallTimeMs'] = int((time.monotonic() - started) * 1000)
    return report


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--project', required=True, type=Path)
    value.add_argument('--brief-file', required=True, type=Path)
    value.add_argument('--task-file', required=True, type=Path)
    value.add_argument('--verification', required=True, type=Path)
    mode = value.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='Explicitly allow generation, task inference and the selected verification command.')
    mode.add_argument('--dry-run', action='store_true', help='Validate inputs only; the default performs no cloning, inference, checks or state writes.')
    value.add_argument('--codex-home', type=Path)
    value.add_argument('--codex-binary', default='codex', help='Official Codex executable used for every phase.')
    value.add_argument('--model')
    value.add_argument('--reasoning-effort', type=types.reasoning_effort, default='unknown')
    value.add_argument('--timeout', type=float, default=900)
    value.add_argument('--repetitions', type=int, default=1)
    value.add_argument('--order', choices=('counterbalanced', 'randomized'), default='counterbalanced')
    value.add_argument('--seed', type=int, default=0)
    value.add_argument('--output', type=Path, help='New metadata-only JSON report outside the source; written only with --live.')
    value.add_argument('--evidence-dir', type=Path, help='Explicitly retain private generated artifacts, including failed candidates, in a new separate directory; --live only.')
    return value


def main():
    args = parser().parse_args()
    try:
        report = run(args)
        text = json.dumps(report, indent=2) + '\n'
        if args.live and args.output is not None:
            path = checked_path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                os.chmod(path, 0o600)
                stream.write(text)
        print(text, end='')
        return 0 if not args.live or report.get('sourceUnchanged') and report.get('experimentSourcesUnchanged') else 1
    except (OSError, ValueError, types.EvaluationError) as exc:
        print(json.dumps({'valid': False, 'error': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
