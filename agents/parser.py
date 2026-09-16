# agents/parser.py
"""
Legacy Code Parser — Planner Agent, Part 1
Extracts structure (classes, functions, imports) and flags
Python 2-specific syntax from a legacy source file.
"""

import ast
import json
import re


def parse_legacy_file(filepath: str) -> dict:
    """
    Reads a Python file and extracts its structure.
    Returns a dict summarizing classes, functions, imports, and Python 2 flags.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    result = {
        "filepath": filepath,
        "classes": [],
        "functions": [],
        "imports": [],
        "python2_flags": [],
    }

    # --- Detect Python 2-specific syntax using regex first ---
    # (we do this BEFORE ast.parse because ast.parse will actually
    # fail/error on real Python 2 print-statement syntax in Python 3)
    result["python2_flags"] = detect_python2_patterns(source)

    # --- Try to parse with ast for structure ---
    # If the file has Python 2 print statements, ast.parse (Python 3)
    # will throw a SyntaxError. We catch that and fall back to
    # regex-based structure extraction instead.
    try:
        tree = ast.parse(source)
        _extract_structure_ast(tree, result)
    except SyntaxError:
        _extract_structure_regex(source, result)

    return result


def detect_python2_patterns(source: str) -> list:
    """Flags common Python 2-only syntax patterns."""
    flags = []

    if re.search(r'\bprint\s+["\']', source):
        flags.append("print_statement (Python 2 print, not print())")

    if re.search(r'\bxrange\s*\(', source):
        flags.append("xrange (removed in Python 3, use range())")

    if re.search(r'except\s+\w+\s*,\s*\w+\s*:', source):
        flags.append("old_except_syntax (except X, e: -> except X as e:)")

    if re.search(r'\bunicode\s*\(', source):
        flags.append("unicode() (removed in Python 3, str is unicode by default)")

    if re.search(r'\.has_key\s*\(', source):
        flags.append("dict.has_key() (removed, use 'in' operator)")

    if re.search(r'\bimport\s+urllib2\b', source):
        flags.append("urllib2 (renamed to urllib.request in Python 3)")

    return flags


def _extract_structure_ast(tree, result):
    """Extract structure using Python's built-in ast module (works when file is valid Python 3 syntax)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
            result["classes"].append({"name": node.name, "methods": methods})

        elif isinstance(node, ast.FunctionDef) and not _is_inside_class(tree, node):
            args = [a.arg for a in node.args.args]
            result["functions"].append({"name": node.name, "args": args})

        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            result["imports"].append(node.module)


def _is_inside_class(tree, target_node):
    """Checks if a function node is a method inside a class (to avoid double-counting)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if target_node in node.body:
                return True
    return False


def _extract_structure_regex(source, result):
    """
    Fallback structure extraction using regex, for files with
    Python 2 syntax that fail ast.parse entirely.
    Less precise than AST but works on any text.
    """
    class_pattern = re.compile(r'^class\s+(\w+)', re.MULTILINE)
    func_pattern = re.compile(r'^\s{0,4}def\s+(\w+)\s*\(([^)]*)\)', re.MULTILINE)
    import_pattern = re.compile(r'^(?:import|from)\s+([\w.]+)', re.MULTILINE)

    for match in class_pattern.finditer(source):
        result["classes"].append({"name": match.group(1), "methods": []})

    for match in func_pattern.finditer(source):
        args = [a.strip().split('=')[0].strip() for a in match.group(2).split(',') if a.strip()]
        result["functions"].append({"name": match.group(1), "args": args})

    for match in import_pattern.finditer(source):
        result["imports"].append(match.group(1))


if __name__ == "__main__":
    output = parse_legacy_file("legacy_samples/inventory.py")
    print(json.dumps(output, indent=2))