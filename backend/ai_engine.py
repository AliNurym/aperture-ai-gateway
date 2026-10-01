import ast
import math
import time
import requests

MAX_SOURCE_BYTES = 32_000

_cached_sol_price: float | None = None
_last_sol_price_fetch = 0.0
MAX_SOL_PRICE_STALENESS_SECONDS = 30

def get_sol_price_from_pyth() -> float | None:
    """
    Fetch the SOL/USD reference price from Pyth, then Binance as a real-data fallback.
    Return a recent real price, or None if both sources fail or the cache is stale.
    """
    global _cached_sol_price, _last_sol_price_fetch
    now = time.time()
    if now - _last_sol_price_fetch < 5.0 and _cached_sol_price is not None:
        return _cached_sol_price

    try:
        # Pyth Network SOL/USD Price Feed ID
        price_id = "ef0d8b6fda2ceba41da15d4095d1da99f0e283034f2ff974b299a34f758f361b"
        url = f"https://hermes.pyth.network/v2/updates/price/latest?ids%5B%5D={price_id}"

        response = requests.get(url, timeout=2.5)
        if response.status_code == 200:
            data = response.json()
            price_info = data['parsed'][0]['price']
            raw_price = float(price_info['price'])
            exponent = float(price_info['expo'])
            price = raw_price * (10 ** exponent)
            if math.isfinite(price) and price > 0:
                _cached_sol_price = round(price, 2)
                _last_sol_price_fetch = now
                return _cached_sol_price
    except Exception as e:
        pass

    try:
        res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", timeout=2.5)
        if res.status_code == 200:
            price = float(res.json()['price'])
            if math.isfinite(price) and price > 0:
                _cached_sol_price = round(price, 2)
                _last_sol_price_fetch = now
                return _cached_sol_price
    except Exception as e:
        pass

    if _cached_sol_price is not None and now - _last_sol_price_fetch <= MAX_SOL_PRICE_STALENESS_SECONDS:
        return _cached_sol_price
    return None


def sigmoid(x: float) -> float:
    """Sigmoid function for the Aperture Penalty Scale (APS)."""
    try:
        return 1.0 / (1.0 + math.exp(-15.0 * (x - 0.4)))
    except OverflowError:
        return 0.0 if x < 0.4 else 1.0


def calculate_ast_quote_rate(complexity_sum: float, hw_power: float = 2.5, telemetry_delta: float = 0.0) -> float:
    """Return a bounded per-second SOL rate from configured complexity inputs.

    This deterministic heuristic is not a worker benchmark or a live market price.
    """
    # Base rate in SOL per second (converted to lamports by the caller).
    base_rate_sol = 0.00000150

    if complexity_sum <= 0:
        return 0.00000050  # Eco standby minimum (500 lamports/sec)

    # Scale according to algorithmic workload
    complexity_factor = max(0.2, complexity_sum / 30.0)

    rate_per_sec = (base_rate_sol * complexity_factor) / max(0.5, hw_power)

    # Aperture Penalty Scale (APS) for hardware pressure
    aps_multiplier = 1.0 + (2.0 * sigmoid(telemetry_delta))

    final_rate = round(rate_per_sec * aps_multiplier, 8)

    # Bounded safely between 0.00000050 SOL/sec (500 lamports) and 0.00002500 SOL/sec (25,000 lamports)
    return max(0.00000050, min(final_rate, 0.00002500))


class CodeComplexityVisitor(ast.NodeVisitor):
    """
    Python AST source-policy and workload-complexity analyzer.
    It flags selected syntax patterns; it is not a sandbox or a safety guarantee.
    """
    DANGEROUS_FUNCTIONS = {
        "eval", "exec", "__import__", "compile", "globals", "locals", "vars", "getattr", "setattr", "delattr", "exit", "quit",
        "system", "popen", "spawn", "fork", "kill", "rmdir", "remove", "unlink"
    }
    # The allowlist shapes the supported workload API; Docker provides the
    # execution boundary. NumPy is installed in the isolated CPU task image.
    HIGH_PERFORMANCE_MODULES = {"numpy", "aperture"}
    ALLOWED_MODULES = {"math", "random", "time", "hashlib", "statistics", "decimal", "fractions", "json"} | HIGH_PERFORMANCE_MODULES

    def __init__(self):
        self.security_violations = []
        self.loop_count = 0
        self.max_loop_depth = 0
        self._current_loop_depth = 0
        self.branch_count = 0
        self.math_ops_count = 0
        self.heavy_ops_count = 0  # matrix multiply, power, nested comprehensions
        self.imported_modules = set()
        self.functions_defined = set()
        self.functions_called = set()
        self.has_recursion = False

    def visit_Import(self, node):
        for alias in node.names:
            self.imported_modules.add(alias.name)
            base_module = alias.name.split('.')[0]
            if base_module not in self.ALLOWED_MODULES:
                self.security_violations.append(f"Module is not allowed: '{alias.name}' (line {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imported_modules.add(node.module)
            base_module = node.module.split('.')[0]
            if base_module not in self.ALLOWED_MODULES:
                self.security_violations.append(f"Module is not allowed: '{node.module}' (line {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node):
        # Check call name
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            self.functions_called.add(func_name)
            if func_name in self.DANGEROUS_FUNCTIONS:
                self.security_violations.append(f"Forbidden function call: '{func_name}' (line {node.lineno})")
            elif func_name == "open":
                self.security_violations.append(f"Filesystem access is forbidden: 'open' (line {node.lineno})")

        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            self.functions_called.add(attr_name)
            if attr_name in self.DANGEROUS_FUNCTIONS:
                self.security_violations.append(f"Forbidden method call: '{attr_name}' (line {node.lineno})")

        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id.startswith("__"):
            self.security_violations.append(f"Dunder access is forbidden: '{node.id}' (line {node.lineno})")
        elif node.id in self.DANGEROUS_FUNCTIONS:
            self.security_violations.append(f"Forbidden function reference: '{node.id}' (line {node.lineno})")
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # Private attributes commonly expose imported implementation modules
        # (for example random._os). They are not part of the workload API and
        # bypass a module-level allowlist, so permit public attributes only.
        if node.attr.startswith("_"):
            self.security_violations.append(f"Private attribute access is forbidden: '{node.attr}' (line {node.lineno})")
        self.generic_visit(node)

    def visit_For(self, node):
        self.loop_count += 1
        self._current_loop_depth += 1
        if self._current_loop_depth > self.max_loop_depth:
            self.max_loop_depth = self._current_loop_depth
        self.generic_visit(node)
        self._current_loop_depth -= 1

    def visit_While(self, node):
        self.loop_count += 1
        self._current_loop_depth += 1
        if self._current_loop_depth > self.max_loop_depth:
            self.max_loop_depth = self._current_loop_depth
        self.generic_visit(node)
        self._current_loop_depth -= 1

    def visit_If(self, node):
        self.branch_count += 1
        self.generic_visit(node)

    def visit_BinOp(self, node):
        if isinstance(node.op, (ast.MatMult, ast.Pow)):
            self.heavy_ops_count += 2
        elif isinstance(node.op, (ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)):
            self.math_ops_count += 1
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.functions_defined.add(node.name)
        # Check recursion
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Name):
                if subnode.func.id == node.name:
                    self.has_recursion = True
        self.generic_visit(node)


def analyze_code_ast(code_snippet: str) -> dict:
    """
    Performs deterministic AST-based source-policy checks and rough workload estimates.
    A passing result does not isolate execution or certify arbitrary Python as safe.
    """
    try:
        source_size = len(code_snippet.encode("utf-8")) if isinstance(code_snippet, str) else MAX_SOURCE_BYTES + 1
    except UnicodeEncodeError:
        return {
            "security": "DANGEROUS", "syntax_valid": False, "predicted_sec": 0,
            "cpu": 0, "ram": 0, "reason": "Payload rejected: source must be valid UTF-8"
        }
    if source_size > MAX_SOURCE_BYTES:
        return {
            "security": "DANGEROUS", "syntax_valid": False, "predicted_sec": 0,
            "cpu": 0, "ram": 0, "reason": "Payload rejected: maximum source size is 32,000 UTF-8 bytes"
        }

    try:
        tree = ast.parse(code_snippet)
    except SyntaxError as e:
        return {
            "security": "DANGEROUS",
            "syntax_valid": False,
            "error": f"Syntax Error: {e.msg} (line {e.lineno})",
            "predicted_sec": 0,
            "cpu": 0,
            "ram": 0,
            "reason": f"Payload rejected: Python Syntax Error at line {e.lineno}"
        }
    except (RecursionError, MemoryError, ValueError):
        return {
            "security": "DANGEROUS", "syntax_valid": False, "predicted_sec": 0,
            "cpu": 0, "ram": 0, "reason": "Payload rejected: Python source is too deeply nested or cannot be parsed"
        }

    if sum(1 for _ in ast.walk(tree)) > 5_000:
        return {
            "security": "DANGEROUS", "syntax_valid": True, "predicted_sec": 0,
            "cpu": 0, "ram": 0, "reason": "Payload rejected: AST is too large"
        }

    visitor = CodeComplexityVisitor()
    try:
        visitor.visit(tree)
    except RecursionError:
        return {
            "security": "DANGEROUS", "syntax_valid": True, "predicted_sec": 0,
            "cpu": 0, "ram": 0, "reason": "Payload rejected: Python source is too deeply nested"
        }

    # 1. Security check
    if visitor.security_violations:
        return {
            "security": "DANGEROUS",
            "syntax_valid": True,
            "violations": visitor.security_violations,
            "predicted_sec": 0,
            "cpu": 100,
            "ram": 10,
            "reason": f"AI Sentinel Sandbox Alert: {visitor.security_violations[0]}"
        }

    # 2. Check for infinite loops or heavy constructs
    extreme_loop = False
    if "while True" in code_snippet or "range(10**" in code_snippet or "10000000" in code_snippet:
        extreme_loop = True

    # 3. Workload estimation
    # Base load
    cpu_score = 15
    ram_score = 10
    predicted_sec = 2

    # Loop nesting exponential weight:
    if visitor.max_loop_depth >= 3:
        cpu_score += 45
        ram_score += 25
        predicted_sec += 7
    elif visitor.max_loop_depth == 2:
        cpu_score += 25
        ram_score += 15
        predicted_sec += 3
    elif visitor.max_loop_depth == 1:
        cpu_score += 10
        predicted_sec += 1

    # Heavy math & matrix operations
    cpu_score += min(visitor.heavy_ops_count * 5 + visitor.math_ops_count, 30)
    ram_score += min(visitor.heavy_ops_count * 4, 30)

    # Recursion multiplier
    if visitor.has_recursion:
        cpu_score += 20
        ram_score += 15
        predicted_sec += 3

    # Account for both `import numpy` and submodule imports such as
    # `import numpy.linalg`; only allowlisted modules can reach this point.
    if any(module.split(".", 1)[0] in visitor.HIGH_PERFORMANCE_MODULES for module in visitor.imported_modules):
        cpu_score += 15
        ram_score += 20
        predicted_sec += 2

    if extreme_loop:
        cpu_score = min(cpu_score * 2, 95)
        ram_score = min(ram_score * 2, 85)
        predicted_sec += 10

    cpu_score = max(5, min(cpu_score, 98))
    ram_score = max(5, min(ram_score, 95))
    predicted_sec = max(1, min(predicted_sec, 30))

    reasons = []
    if visitor.max_loop_depth > 1:
        reasons.append(f"Nested loops depth {visitor.max_loop_depth} (O(N^{visitor.max_loop_depth}))")
    if visitor.has_recursion:
        reasons.append("Recursive call stack")
    if visitor.heavy_ops_count > 0:
        reasons.append("Heavy matrix / power arithmetic")
    if visitor.imported_modules:
        reasons.append(f"Libraries: {', '.join(sorted(visitor.imported_modules))}")

    explanation = "; ".join(reasons) if reasons else "Standard linear compute sequence"
    if extreme_loop:
        explanation += " [High iteration scale detected]"

    return {
        "security": "SAFE",
        "syntax_valid": True,
        "predicted_sec": predicted_sec,
        "cpu": cpu_score,
        "ram": ram_score,
        "network": 0,
        "max_loop_depth": visitor.max_loop_depth,
        "reason": f"Aperture AST Audit: {explanation}"
    }


def analyze_code_complexity(code_snippet: str) -> dict:
    """
    Return bounded, deterministic workload estimates from local AST analysis.

    Submitted source is never sent to a third-party model provider.
    """
    ast_audit = analyze_code_ast(code_snippet)
    sol_price = get_sol_price_from_pyth()
    if ast_audit.get("security") != "SAFE":
        return {
            "status": "blocked",
            "security": ast_audit.get("security", "DANGEROUS"),
            "predicted_sec": 0,
            "complexity_score": 100,
            "scores": ast_audit,
            "calculated_rate_sol_sec": 0.0,
            "sol_market_price": sol_price,
            "reason": ast_audit.get("reason", "Malicious code detected.")
        }

    total_complexity = ast_audit["cpu"] + ast_audit["ram"]
    price_per_sec = calculate_ast_quote_rate(total_complexity, hw_power=2.5, telemetry_delta=0.0)

    return {
        "status": "success",
        "security": "SAFE",
        "predicted_sec": ast_audit["predicted_sec"],
        "complexity_score": total_complexity,
        "complexity_sum": total_complexity,
        "scores": ast_audit,
        "calculated_rate_sol_sec": price_per_sec,
        "calculated_rate_lamports_sec": int(price_per_sec * 1_000_000_000),
        "sol_market_price": sol_price
    }
