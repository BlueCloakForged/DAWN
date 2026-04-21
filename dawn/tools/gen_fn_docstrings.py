"""
gen_fn_docstrings.py — Inject minimal docstrings into undocumented public functions.

Reads each .py file in dawn/links/, finds public functions without a docstring,
and injects a one-line docstring derived from the function name (snake_case → readable).
Skips functions that already have a docstring.
"""

import ast
from pathlib import Path


def _name_to_doc(name: str) -> str:
    """Convert a snake_case function name to a readable docstring sentence."""
    words = name.replace('__', ' ').split('_')
    words = [w for w in words if w]
    if not words:
        return 'Execute function logic.'
    sentence = ' '.join(words).capitalize() + '.'
    return sentence


def _find_undocumented(src: str):
    """Return list of (lineno, col_offset, name) for undocumented public functions."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private/dunder helpers
            if node.name.startswith('_') and not node.name.startswith('__'):
                continue
            has_doc = (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            )
            if not has_doc:
                results.append((node.lineno, node.col_offset, node.name, node.body[0].lineno if node.body else node.lineno + 1))
    # Process in reverse order so line insertions don't shift subsequent line numbers
    results.sort(key=lambda x: -x[0])
    return results


def _insert_docstring(lines: list, body_first_lineno: int, fn_col: int, doc_text: str) -> list:
    """
    Insert a docstring line before body_first_lineno (1-indexed).
    Indentation = fn_col + 4 spaces (one extra indent level).
    """
    indent = ' ' * (fn_col + 4)
    docstring_line = f'{indent}"""{doc_text}"""\n'
    insert_at = body_first_lineno - 1  # convert to 0-indexed
    lines.insert(insert_at, docstring_line)
    return lines


def patch_file(filepath: Path) -> int:
    """Patch a single file; returns number of docstrings inserted."""
    src = filepath.read_text(encoding='utf-8', errors='replace')
    undoc = _find_undocumented(src)
    if not undoc:
        return 0

    lines = src.splitlines(keepends=True)
    # Process in descending lineno order so lower insertions don't shift upper lines.
    for fn_lineno, fn_col, fn_name, body_lineno in undoc:
        doc_text = _name_to_doc(fn_name)
        doc_text = doc_text.replace('"""', "'''")
        lines = _insert_docstring(lines, body_lineno, fn_col, doc_text)

    filepath.write_text(''.join(lines), encoding='utf-8')
    return len(undoc)


def main():
    links_dir = Path(__file__).resolve().parent.parent / 'links'
    runtime_dir = Path(__file__).resolve().parent.parent / 'runtime'

    total_inserted = 0
    files_patched = 0

    for search_dir in [links_dir, runtime_dir]:
        for py_file in sorted(search_dir.rglob('*.py')):
            if py_file.name == '__init__.py':
                continue
            if any(part.startswith(('.', '_')) for part in py_file.parts):
                continue
            if '__pycache__' in str(py_file):
                continue

            n = patch_file(py_file)
            if n > 0:
                rel = py_file.relative_to(links_dir.parent)
                print(f'  +{n:>3} docstrings  {rel}')
                total_inserted += n
                files_patched += 1

    print(f'\nDone. {total_inserted} docstrings inserted across {files_patched} files.')


if __name__ == '__main__':
    main()
