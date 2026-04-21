"""
gen_run_docstrings.py — Add module-level docstrings to link run.py files.

Reads each link's link.yaml description and injects it as a module docstring
into run.py if one is missing. Does not touch files that already have a docstring.
"""

import ast
import re
from pathlib import Path


def _extract_description(content: str) -> str:
    """Pull the description from link.yaml content."""
    lines = content.splitlines()
    desc_lines = []
    in_desc = False
    desc_indent = 0

    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Inline description
        m = re.match(r'^\s*description:\s*(.+)', line)
        if m and not in_desc:
            val = m.group(1).strip().strip('"\'><-').strip()
            if val:
                return val
            in_desc = True
            desc_indent = indent + 2
            continue

        if in_desc:
            if not stripped:
                desc_lines.append('')
                continue
            if indent >= desc_indent or not desc_lines:
                desc_lines.append(stripped)
            else:
                break

    return ' '.join(l for l in desc_lines if l).strip()


def main():
    links_dir = Path(__file__).resolve().parent.parent / 'links'
    patched = 0
    skipped_has_doc = 0
    skipped_no_run = 0

    for link_dir in sorted(links_dir.iterdir()):
        if not link_dir.is_dir() or link_dir.name.startswith(('.', '_')):
            continue

        run_py = link_dir / 'run.py'
        if not run_py.exists():
            skipped_no_run += 1
            continue

        src = run_py.read_text(encoding='utf-8', errors='replace')

        # Check if already has module docstring
        try:
            tree = ast.parse(src)
            has_doc = (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
            )
        except SyntaxError:
            print(f'  SKIP (syntax error): {link_dir.name}')
            continue

        if has_doc:
            skipped_has_doc += 1
            continue

        # Build docstring from link.yaml
        link_yaml = link_dir / 'link.yaml'
        description = ''
        if link_yaml.exists():
            description = _extract_description(link_yaml.read_text(encoding='utf-8', errors='replace'))

        if not description:
            description = f'Executes the {link_dir.name} step in the DAWN pipeline.'

        # Escape any triple-quotes in description (rare but safe)
        description = description.replace('"""', "'''")

        # Prepend docstring as the first line(s)
        new_src = f'"""{description}"""\n' + src
        run_py.write_text(new_src, encoding='utf-8')
        patched += 1
        print(f'  PATCHED  {link_dir.name}/run.py')

    print(f'\nDone. Patched: {patched}  Already had docstring: {skipped_has_doc}  No run.py: {skipped_no_run}')


if __name__ == '__main__':
    main()
