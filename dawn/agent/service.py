"""
DAWN Agent Service

Local HTTP service for generating patchsets from requirements.

Architecture:
- Receives: requirements_map.json + optional context
- Generates: patchset.json + capabilities_manifest.json
- Model: Rule-based (v1) → Ollama integration (v2)

Run:
    uvicorn service:app --host 127.0.0.1 --port 9411
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import hashlib
import json

app = FastAPI(
    title="DAWN Agent Service",
    version="0.1.0",
    description="Local patchset generation service"
)


# ============================================================================
# Request/Response Models
# ============================================================================

class GenerateRequest(BaseModel):
    """Request to generate patchset from requirements"""
    schema_version: str = Field(default="1.0.0")
    project_id: str
    pipeline_id: str = Field(default="app_mvp")
    input: Dict[str, Any]
    constraints: Dict[str, Any] = Field(default_factory=dict)
    generation: Dict[str, Any] = Field(default_factory=dict)


class GenerateResponse(BaseModel):
    """Generated patchset + capabilities manifest"""
    schema_version: str = Field(default="1.0.0")
    generator: Dict[str, Any]
    patchset: Dict[str, Dict[str, str]]
    capabilities_manifest: Dict[str, Any]
    trace: Dict[str, Any]


# ============================================================================
# Core Generation Logic
# ============================================================================

def generate_code_from_requirements(requirements: List[Dict]) -> Dict[str, Dict[str, str]]:
    """
    Generate patchset from requirements.
    
    V1: Rule-based (deterministic, fast)
    V2: Will use Ollama integration
    """
    # Extract operators
    operators = sorted([r["value"] for r in requirements if r["type"] == "operator"])
    examples = [r for r in requirements if r["type"] == "example"]
    
    # Generate files
    patchset = {}
    
    # 1. __init__.py
    patchset["calculator_cli/__init__.py"] = {
        "content": '"""Calculator CLI - A simple command-line calculator"""\n__version__ = "0.1.0"'
    }
    
    # 2. parser.py (generates based on operators)
    parser_code = generate_parser_code(operators)
    patchset["calculator_cli/parser.py"] = {"content": parser_code}
    
    # 3. cli.py
    cli_code = generate_cli_code()
    patchset["calculator_cli/cli.py"] = {"content": cli_code}
    
    # 4. tests
    test_code = generate_test_code(examples)
    patchset["tests/test_calculator.py"] = {"content": test_code}
    
    # 5. setup.py
    setup_code = generate_setup_code()
    patchset["setup.py"] = {"content": setup_code}
    
    return patchset


def generate_parser_code(operators: List[str]) -> str:
    """Generate parser supporting specified operators"""
    # Build operator precedence
    ops_str = ", ".join([f"'{op}'" for op in operators])
    
    # Determine which operators are supported
    has_add_sub = '+' in operators or '-' in operators
    has_mul_div = '*' in operators or '/' in operators
    has_exp = '^' in operators
    
    code = f'''"""Expression parser for calculator"""

from typing import Union

class ParseError(Exception):
    """Exception raised for parsing errors"""
    pass

def tokenize(expression: str) -> list:
    """Tokenize mathematical expression"""
    expression = expression.replace(" ", "")
    tokens = []
    current_num = ""
    
    for char in expression:
        if char.isdigit() or char == '.':
            current_num += char
        else:
            if current_num:
                tokens.append(current_num)
                current_num = ""
            if char in [{ops_str}, '(', ')']:
                tokens.append(char)
    
    if current_num:
        tokens.append(current_num)
    
    return tokens

def parse_expression(tokens: list) -> Union[int, float]:
    """Parse and evaluate expression using recursive descent"""
    
    class Parser:
        def __init__(self, tokens):
            self.tokens = tokens
            self.pos = 0
        
        def parse(self):
            result = self.parse_term()'''
    
    if has_add_sub:
        code += '''
            while self.pos < len(self.tokens) and self.tokens[self.pos] in ['+', '-']:
                op = self.tokens[self.pos]
                self.pos += 1
                right = self.parse_term()
                if op == '+':
                    result += right
                else:
                    result -= right'''
    
    code += '''
            return result
        
        def parse_term(self):
            result = self.parse_factor()'''
    
    if has_mul_div:
        code += '''
            while self.pos < len(self.tokens) and self.tokens[self.pos] in ['*', '/']:
                op = self.tokens[self.pos]
                self.pos += 1
                right = self.parse_factor()
                if op == '*':
                    result *= right
                else:
                    if right == 0:
                        raise ParseError("Division by zero")
                    result /= right'''
    
    code += '''
            return result
        
        def parse_factor(self):'''
    
    if has_exp:
        code += '''
            result = self.parse_primary()
            if self.pos < len(self.tokens) and self.tokens[self.pos] == '^':
                self.pos += 1
                exponent = self.parse_factor()
                result = result ** exponent
            return result
        
        def parse_primary(self):'''
    
    code += '''
            token = self.tokens[self.pos]
            
            if token == '(':
                self.pos += 1
                result = self.parse()
                if self.pos >= len(self.tokens) or self.tokens[self.pos] != ')':
                    raise ParseError("Mismatched parentheses")
                self.pos += 1
                return result
            
            try:
                num = float(token) if '.' in token else int(token)
                self.pos += 1
                return num
            except ValueError:
                raise ParseError(f"Invalid token: {{token}}")
    
    parser = Parser(tokens)
    return parser.parse()

def evaluate(expression: str) -> Union[int, float]:
    """Evaluate mathematical expression"""
    tokens = tokenize(expression)
    return parse_expression(tokens)
'''
    
    return code


def generate_cli_code() -> str:
    """Generate CLI entry point"""
    return '''"""Command-line interface for calculator"""

import sys
from .parser import evaluate, ParseError

def main():
    """Main CLI entry point"""
    if len(sys.argv) < 2:
        print("Usage: calc <expression>")
        return
    
    expression = sys.argv[1]
    
    try:
        result = evaluate(expression)
        if isinstance(result, float) and result.is_integer():
            print(int(result))
        else:
            print(result)
    except ParseError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
'''


def generate_test_code(examples: List[Dict]) -> str:
    """Generate tests from example requirements"""
    tests = []
    
    for example in examples:
        expr = example["expr"]
        expected = example["expected"]
        test_name = f"test_{expr.replace(' ', '_').replace('(', '').replace(')', '').replace('*', 'mul').replace('/', 'div').replace('+', 'add').replace('-', 'sub').replace('^', 'exp')}"
        
        tests.append(f'''
def {test_name}():
    """Test: {expr} → {expected}"""
    result = evaluate("{expr}")
    assert result == {expected}, f"Expected {expected}, got {{result}}"
''')
    
    test_code = '''"""Tests for calculator"""

import pytest
from calculator_cli.parser import evaluate, ParseError

''' + '\n'.join(tests) + '''

def test_invalid_expression():
    """Test invalid expression raises ParseError"""
    with pytest.raises(ParseError):
        evaluate("2 ++ 2")
'''
    
    return test_code


def generate_setup_code() -> str:
    """Generate setup.py"""
    return '''from setuptools import setup, find_packages

setup(
    name='calculator-cli',
    version='0.1.0',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'calc=calculator_cli.cli:main',
        ],
    },
)
'''


# ============================================================================
# API Endpoint
# ============================================================================

@app.post("/v1/patchset:generate", response_model=GenerateResponse)
async def generate_patchset(request: GenerateRequest):
    """
    Generate patchset from requirements.
    
    Input: requirements_map + optional context
    Output: patchset + capabilities_manifest
    """
    try:
        # Extract requirements
        requirements_map = request.input.get("requirements_map")
        if not requirements_map:
            raise HTTPException(
                status_code=400,
                detail="Missing required input: requirements_map"
            )
        
        requirements = requirements_map.get("requirements", [])
        
        # Generate code
        patchset = generate_code_from_requirements(requirements)
        
        # Compute SHA256 for each file
        for path, patch in patchset.items():
            content = patch["content"]
            patch["sha256"] = hashlib.sha256(content.encode()).hexdigest()
        
        # Generate capabilities manifest
        operators = sorted([r["value"] for r in requirements if r["type"] == "operator"])
        
        capabilities_manifest = {
            "schema_version": "1.0.0",
            "project_type": "calculator",
            "generator_id": "impl.generate_patchset",
            "generator_version": "1.0.0",
            "capabilities": {
                "operators_supported": operators,
                "syntax_supported": ["parentheses", "whitespace"],
                "constraints": []
            }
        }
        
        # Build response
        return GenerateResponse(
            schema_version="1.0.0",
            generator={
                "id": "local_agent",
                "version": "0.1.0",
                "model": request.generation.get("model", "rule-based-v1"),
                "deterministic": True
            },
            patchset=patchset,
            capabilities_manifest=capabilities_manifest,
            trace={
                "summary": f"Generated {len(patchset)} files for calculator CLI",
                "notes": [f"Operators: {', '.join(operators)}"],
                "warnings": []
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "DAWN Agent Service",
        "version": "0.1.0",
        "endpoints": {
            "generate": "POST /v1/patchset:generate",
            "health": "GET /health"
        }
    }
