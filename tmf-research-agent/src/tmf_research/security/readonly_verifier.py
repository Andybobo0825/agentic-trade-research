from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


_FORBIDDEN_SYMBOLS = (
    "activate" + "_ca",
    "place" + "_order",
    "update" + "_order",
    "update" + "_price",
    "update" + "_qty",
    "cancel" + "_order",
    "Futures" + "Order",
    "Stock" + "Order",
    "Reserve" + "Order",
    "Touch" + "Price",
    "Order" + "Executor",
    "Live" + "Broker",
    "Shioaji" + "Broker",
)
_FORBIDDEN_PAPER_CLASS_NAMES = frozenset(
    (
        "Broker",
        "Execution" + "Broker",
        "Live" + "Execution",
        "Order" + "Gateway",
        "Real" + "Broker",
    )
)
_ALLOWED_ADAPTER_PATH = Path(
    "tmf_research/infrastructure/shioaji_market_data.py"
)
_RAW_ADAPTER_MODULE = ".".join(
    ("tmf_research", "infrastructure", "shioaji_market_data")
)
_SDK_IMPORT_ROOTS = frozenset(("shioaji",))
_NETWORK_IMPORT_ROOTS = frozenset(
    ("aiohttp", "http", "httpx", "requests", "socket", "urllib")
)


@dataclass(frozen=True, order=True, slots=True)
class ReadonlyFinding:
    path: str
    line: int
    rule: str
    symbol: str
    column: int = 0
    message: str = ""

    def render(self) -> str:
        location = f"{self.path}:{self.line}:{self.column}"
        return f"{location} [{self.rule}] {self.symbol}: {self.message}"


@dataclass(frozen=True, slots=True)
class ReadonlyReport:
    source_root: Path
    findings: tuple[ReadonlyFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def render(self) -> str:
        if self.ok:
            return "READONLY VERIFIED"
        return "\n".join(finding.render() for finding in self.findings)


def verify_readonly(source_root: Path) -> ReadonlyReport:
    """Scan one Python source tree and fail closed on unsafe capabilities."""

    root = source_root.resolve()
    if not root.is_dir():
        finding = ReadonlyFinding(
            path=str(root),
            line=0,
            column=0,
            rule="invalid-source-root",
            symbol="src",
            message="source root does not exist or is not a directory",
        )
        return ReadonlyReport(root, (finding,))

    findings: set[ReadonlyFinding] = set()
    for source_file in sorted(root.rglob("*.py")):
        findings.update(_scan_file(root, source_file))
    return ReadonlyReport(root, tuple(sorted(findings)))


def _scan_file(source_root: Path, source_file: Path) -> set[ReadonlyFinding]:
    relative = source_file.relative_to(source_root)
    relative_text = relative.as_posix()
    findings: set[ReadonlyFinding] = set()
    try:
        source = source_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        findings.add(
            ReadonlyFinding(
                path=relative_text,
                line=0,
                column=0,
                rule="source-read-error",
                symbol=source_file.name,
                message=str(error),
            )
        )
        return findings

    findings.update(_scan_raw_text(relative_text, source))
    try:
        tree = ast.parse(source, filename=relative_text)
    except SyntaxError as error:
        findings.add(
            ReadonlyFinding(
                path=relative_text,
                line=error.lineno or 0,
                column=error.offset or 0,
                rule="syntax-error",
                symbol=error.msg,
                message="invalid Python cannot be safety-verified",
            )
        )
        return findings

    findings.update(_scan_ast(relative, tree))
    return findings


def _scan_raw_text(path: str, source: str) -> set[ReadonlyFinding]:
    findings: set[ReadonlyFinding] = set()
    for line_number, line in enumerate(source.splitlines(), start=1):
        for symbol in _FORBIDDEN_SYMBOLS:
            column = line.find(symbol)
            if column >= 0:
                findings.add(
                    ReadonlyFinding(
                        path=path,
                        line=line_number,
                        column=column + 1,
                        rule="forbidden-symbol",
                        symbol=symbol,
                        message="forbidden capability appears in production source",
                    )
                )
    return findings


def _scan_ast(relative: Path, tree: ast.AST) -> set[ReadonlyFinding]:
    path = relative.as_posix()
    is_adapter = relative == _ALLOWED_ADAPTER_PATH
    is_paper = "paper" in relative.parts
    findings: set[ReadonlyFinding] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ClassDef)
            and node.name in _FORBIDDEN_PAPER_CLASS_NAMES
        ):
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    rule="forbidden-paper-class",
                    symbol=node.name,
                    message="PaperBroker is the only permitted trading boundary",
                )
            )
        symbol = _forbidden_node_symbol(node)
        if symbol is not None:
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0) + 1,
                    rule="forbidden-symbol",
                    symbol=symbol,
                    message="forbidden capability is executable syntax",
                )
            )
        if not is_adapter and _is_raw_api_access(node):
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0) + 1,
                    rule="raw-api-access",
                    symbol="_api",
                    message="raw API state is private to the market-data adapter",
                )
            )

    for module, line, column in _iter_imports(tree):
        import_root = module.split(".", maxsplit=1)[0]
        if import_root in _SDK_IMPORT_ROOTS and not is_adapter:
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=line,
                    column=column,
                    rule="sdk-import-boundary",
                    symbol=module,
                    message="SDK imports are allowed only in the raw adapter",
                )
            )
        if not is_adapter and (
            module == _RAW_ADAPTER_MODULE
            or module.startswith(f"{_RAW_ADAPTER_MODULE}.")
        ):
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=line,
                    column=column,
                    rule="raw-adapter-dependency",
                    symbol=module,
                    message="consumers must depend on MarketDataGateway",
                )
            )
        if is_paper and import_root in _NETWORK_IMPORT_ROOTS:
            findings.add(
                ReadonlyFinding(
                    path=path,
                    line=line,
                    column=column,
                    rule="paper-network-boundary",
                    symbol=module,
                    message="paper modules cannot import network transports",
                )
            )
    return findings


def _forbidden_node_symbol(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SYMBOLS:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_SYMBOLS:
        return node.attr
    if isinstance(node, ast.alias):
        final_name = node.name.rsplit(".", maxsplit=1)[-1]
        if final_name in _FORBIDDEN_SYMBOLS:
            return final_name
    return None


def _is_raw_api_access(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Name)
        and node.id == "_api"
        or isinstance(node, ast.Attribute)
        and node.attr == "_api"
        or isinstance(node, ast.arg)
        and node.arg in ("api", "raw_api", "shioaji_api")
    )


def _iter_imports(tree: ast.AST) -> Iterator[tuple[str, int, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno, node.col_offset + 1
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                yield (
                    f"{node.module}.{alias.name}",
                    node.lineno,
                    node.col_offset + 1,
                )
        elif isinstance(node, ast.Call) and node.args:
            imported = _dynamic_import_name(node)
            if imported is not None:
                yield imported, node.lineno, node.col_offset + 1


def _dynamic_import_name(node: ast.Call) -> str | None:
    first_argument = node.args[0]
    if not isinstance(first_argument, ast.Constant) or not isinstance(
        first_argument.value, str
    ):
        return None
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        return first_argument.value
    if isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
        return first_argument.value
    return None
