"""
gen_readmes.py — Generate DAWN Layer 2 compliant README.md stubs for link directories.

Reads each link.yaml and produces a README.md that satisfies the self-describing
requirements from Layer 2 of the Dark Code Management Framework. Skips directories
that already have a README.md or manifest.md.
"""

import re
from pathlib import Path
from typing import Optional


def _extract_field(content: str, key: str) -> Optional[str]:
    """Pull a scalar value for a given YAML key (handles inline and block scalar)."""
    # Match key: value (inline, possibly quoted)
    pattern = rf'^\s*{re.escape(key)}:\s*[">]?\s*(.+?)["\'<]?\s*$'
    for line in content.splitlines():
        m = re.match(rf'^\s*{re.escape(key)}:\s*(.+)', line)
        if m:
            val = m.group(1).strip().strip('"').strip("'").strip(">-").strip()
            if val:
                return val
    return None


def _extract_description(content: str) -> str:
    """Extract description from metadata or spec block, handling multi-line."""
    lines = content.splitlines()
    desc_lines = []
    in_desc = False
    desc_indent = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Look for description: under metadata or spec
        if re.match(r'^\s*description:\s*[>|]?\s*$', line):
            in_desc = True
            desc_indent = len(line) - len(line.lstrip()) + 2
            continue
        elif re.match(r'^\s*description:\s*.+', line):
            val = re.sub(r'^\s*description:\s*', '', line).strip().strip('"').strip("'").strip(">-").strip()
            if val:
                return val
            in_desc = True
            desc_indent = len(line) - len(line.lstrip()) + 2
            continue

        if in_desc:
            if not stripped:
                desc_lines.append('')
                continue
            indent = len(line) - len(line.lstrip())
            if indent >= desc_indent or not desc_lines:
                desc_lines.append(stripped)
            else:
                break

    return ' '.join(l for l in desc_lines if l).strip() or ''


def _extract_list_section(content: str, key: str) -> list:
    """Extract a list of artifact IDs or names from a YAML list section."""
    lines = content.splitlines()
    items = []
    in_section = False
    section_indent = 0

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if re.match(rf'^\s*{re.escape(key)}:\s*', line):
            in_section = True
            section_indent = indent
            # Check for inline empty list
            if '[]' in line:
                return []
            continue

        if in_section:
            if not stripped:
                continue
            if stripped.startswith('- ') and indent > section_indent:
                # Extract artifact/artifactId name
                m = re.search(r'artifact(?:Id)?:\s*["\']?([^\s"\'#,]+)', stripped)
                if m:
                    items.append(m.group(1))
                else:
                    # Plain list item
                    val = stripped.lstrip('- ').strip().strip('"').strip("'")
                    if val:
                        items.append(val)
            elif indent <= section_indent and stripped and not stripped.startswith('-'):
                break

    return items


def _extract_runtime(content: str) -> dict:
    """Extract runtime config (timeout, retries) from link.yaml."""
    result = {}
    in_runtime = False
    runtime_indent = 0

    for line in content.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        if re.match(r'^\s*runtime:\s*$', line):
            in_runtime = True
            runtime_indent = indent
            continue

        if in_runtime:
            if not stripped:
                continue
            if indent <= runtime_indent and stripped:
                break
            m = re.match(r'\s*(timeoutSeconds|retries|alwaysRun|always_run):\s*(.+)', line)
            if m:
                result[m.group(1)] = m.group(2).strip()

    return result


def _infer_failure_modes(name: str, requires: list, produces: list, runtime: dict) -> list:
    """Generate sensible default failure mode rows from link metadata."""
    modes = []

    timeout = runtime.get('timeoutSeconds', '600')
    if timeout and timeout != '0':
        modes.append((
            f"Execution exceeds `timeoutSeconds: {timeout}`",
            "Returns `FAILED` with timeout diagnostic",
            "Retry or increase timeout in `link.yaml`"
        ))

    if requires:
        modes.append((
            "Required input artifact not found",
            "Returns `FAILED` with missing-artifact error",
            "Verify upstream link ran and produced the artifact"
        ))

    retries = runtime.get('retries', '0')
    if retries and retries != '0':
        modes.append((
            "Transient runtime error (first attempt)",
            f"Retries up to `{retries}` time(s) automatically",
            "Inspect link log if all retries exhausted"
        ))

    if not modes:
        modes.append((
            "Runtime error or unhandled exception",
            "Returns `FAILED` with stack trace in pipeline log",
            "Inspect error and fix upstream inputs or link config"
        ))

    return modes


def _build_readme(name: str, content: str) -> str:
    """Build a DAWN Layer 2 compliant README.md from link.yaml content."""
    description = _extract_description(content)
    if not description:
        description = f"Executes the `{name}` step in the DAWN pipeline."

    requires = _extract_list_section(content, 'requires')
    produces = _extract_list_section(content, 'produces')
    runtime = _extract_runtime(content)

    timeout = runtime.get('timeoutSeconds', '600')
    retries = runtime.get('retries', '0')
    always_run = runtime.get('alwaysRun', runtime.get('always_run', 'false'))

    failure_modes = _infer_failure_modes(name, requires, produces, runtime)

    # Build requires section
    if requires:
        req_lines = '\n'.join(f'- `{r}`' for r in requires)
    else:
        req_lines = '- *(none — runs standalone)*'

    # Build produces section
    if produces:
        prod_lines = '\n'.join(f'- `{p}`' for p in produces)
    else:
        prod_lines = '- *(no artifacts produced — side-effect only)*'

    # Build failure modes table
    fm_rows = '\n'.join(
        f'| {c} | {b} | {a} |'
        for c, b, a in failure_modes
    )

    runtime_notes = []
    if timeout and timeout != '0':
        runtime_notes.append(f'- **Timeout:** `{timeout}s`')
    if retries and retries != '0':
        runtime_notes.append(f'- **Retries:** `{retries}`')
    if always_run.lower() in ('true', '1'):
        runtime_notes.append('- **Always runs:** yes (not skipped on pipeline skip-mode)')
    runtime_section = '\n'.join(runtime_notes) if runtime_notes else '- Default timeout / no retries'

    return f"""# Module: {name}

## Purpose
{description}

## Dependencies (Requires)
{req_lines}

## Produces
{prod_lines}

## Failure Modes
| Condition | Behavior | Caller Action |
|-----------|----------|---------------|
{fm_rows}

## Runtime
{runtime_section}
"""


def main():
    links_dir = Path(__file__).resolve().parent.parent / 'links'
    if not links_dir.exists():
        print(f"ERROR: links dir not found at {links_dir}")
        return

    created = 0
    skipped = 0

    for link_dir in sorted(links_dir.iterdir()):
        if not link_dir.is_dir():
            continue
        if link_dir.name.startswith(('.', '_')):
            continue

        readme = link_dir / 'README.md'
        manifest = link_dir / 'manifest.md'

        if readme.exists() or manifest.exists():
            skipped += 1
            continue

        link_yaml = link_dir / 'link.yaml'
        if link_yaml.exists():
            content = link_yaml.read_text(encoding='utf-8', errors='replace')
        else:
            content = ''

        name = link_dir.name
        readme_content = _build_readme(name, content)
        readme.write_text(readme_content, encoding='utf-8')
        created += 1
        print(f'  CREATED  {name}/README.md')

    print(f'\nDone. Created: {created}  Skipped (already had manifest): {skipped}')


if __name__ == '__main__':
    main()
