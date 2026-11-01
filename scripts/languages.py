"""Language detection and generated/vendored-file heuristics for codereview-ops.

Deliberately data-driven and dependency-free so that adding a language is a one-line change.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

# extension (lower-case, with dot) -> language name
EXTENSIONS: dict[str, str] = {
    # Systems
    ".c": "C", ".h": "C/C++ header", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".c++": "C++",
    ".hh": "C++", ".hpp": "C++", ".hxx": "C++", ".ipp": "C++", ".inl": "C++",
    ".cu": "CUDA", ".cuh": "CUDA", ".rs": "Rust", ".go": "Go", ".zig": "Zig", ".nim": "Nim",
    ".d": "D", ".m": "Objective-C/MATLAB", ".mm": "Objective-C++", ".asm": "Assembly", ".s": "Assembly",
    ".S": "Assembly", ".ll": "LLVM IR", ".cl": "OpenCL", ".metal": "Metal", ".hip": "HIP",
    ".glsl": "GLSL", ".hlsl": "HLSL", ".wgsl": "WGSL", ".v": "Verilog", ".vh": "Verilog",
    ".sv": "SystemVerilog", ".svh": "SystemVerilog", ".vhd": "VHDL", ".vhdl": "VHDL",
    ".sdc": "SDC/Tcl", ".xdc": "XDC/Tcl", ".tcl": "Tcl", ".upf": "UPF/Tcl", ".lib": "Liberty",
    # JVM / .NET
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".sc": "Scala",
    ".groovy": "Groovy", ".gradle": "Groovy (Gradle)", ".clj": "Clojure", ".cljs": "ClojureScript",
    ".cs": "C#", ".fs": "F#", ".fsx": "F#", ".vb": "Visual Basic",
    # Scripting
    ".py": "Python", ".pyi": "Python", ".pyx": "Cython", ".ipynb": "Jupyter Notebook",
    ".rb": "Ruby", ".erb": "Ruby (ERB)", ".rake": "Ruby", ".php": "PHP", ".pl": "Perl", ".pm": "Perl",
    ".lua": "Lua", ".r": "R", ".R": "R", ".jl": "Julia", ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hrl": "Erlang", ".hs": "Haskell", ".ml": "OCaml", ".mli": "OCaml",
    ".dart": "Dart", ".swift": "Swift", ".cr": "Crystal", ".rkt": "Racket", ".lisp": "Lisp",
    ".el": "Emacs Lisp", ".scm": "Scheme", ".f90": "Fortran", ".f95": "Fortran", ".f": "Fortran",
    ".for": "Fortran", ".cob": "COBOL", ".cbl": "COBOL", ".pas": "Pascal", ".ada": "Ada",
    ".adb": "Ada", ".ads": "Ada", ".sol": "Solidity", ".move": "Move", ".cairo": "Cairo",
    ".vy": "Vyper", ".mojo": "Mojo", ".gd": "GDScript",
    # Shell
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".fish": "Fish", ".ksh": "Shell",
    ".ps1": "PowerShell", ".psm1": "PowerShell", ".bat": "Batch", ".cmd": "Batch",
    # Web
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript", ".tsx": "TypeScript (TSX)",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less", ".elm": "Elm",
    ".coffee": "CoffeeScript", ".hbs": "Handlebars", ".njk": "Nunjucks", ".jinja": "Jinja",
    ".j2": "Jinja", ".twig": "Twig", ".liquid": "Liquid", ".ejs": "EJS", ".pug": "Pug",
    # Data / query / IDL
    ".sql": "SQL", ".prisma": "Prisma", ".graphql": "GraphQL", ".gql": "GraphQL",
    ".proto": "Protocol Buffers", ".thrift": "Thrift", ".avsc": "Avro", ".capnp": "Cap'n Proto",
    # Config / infra
    ".json": "JSON", ".jsonc": "JSON", ".json5": "JSON5", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".ini": "INI", ".cfg": "INI", ".conf": "Config", ".xml": "XML",
    ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL", ".nix": "Nix", ".bzl": "Starlark",
    ".star": "Starlark", ".cmake": "CMake", ".mk": "Makefile", ".nomad": "HCL", ".cue": "CUE",
    ".rego": "Rego", ".dhall": "Dhall", ".jsonnet": "Jsonnet", ".libsonnet": "Jsonnet",
    ".env": "dotenv", ".properties": "Properties",
    # Docs
    ".md": "Markdown", ".mdx": "MDX", ".rst": "reStructuredText", ".adoc": "AsciiDoc",
    ".tex": "LaTeX", ".txt": "Text",
}

FILENAMES: dict[str, str] = {
    "dockerfile": "Dockerfile", "containerfile": "Dockerfile", "makefile": "Makefile",
    "gnumakefile": "Makefile", "cmakelists.txt": "CMake", "jenkinsfile": "Groovy (Jenkins)",
    "vagrantfile": "Ruby", "gemfile": "Ruby", "rakefile": "Ruby", "podfile": "Ruby",
    "build": "Starlark", "build.bazel": "Starlark", "workspace": "Starlark", "module.bazel": "Starlark",
    "justfile": "Just", "procfile": "Procfile", ".bashrc": "Shell", ".zshrc": "Shell",
    ".profile": "Shell", ".gitlab-ci.yml": "YAML (GitLab CI)", "meson.build": "Meson",
    "sconstruct": "Python (SCons)", "sconscript": "Python (SCons)", "tiltfile": "Starlark",
}

SHEBANGS: list[tuple[str, str]] = [
    ("python", "Python"), ("node", "JavaScript"), ("deno", "TypeScript"), ("bun", "JavaScript"),
    ("ruby", "Ruby"), ("perl", "Perl"), ("php", "PHP"), ("bash", "Shell"), ("zsh", "Shell"),
    ("/sh", "Shell"), ("env sh", "Shell"), ("fish", "Fish"), ("lua", "Lua"), ("tclsh", "Tcl"),
    ("Rscript", "R"), ("julia", "Julia"), ("pwsh", "PowerShell"), ("elixir", "Elixir"),
]

# Rough family used for picking checklist sections.
FAMILY: dict[str, str] = {
    "C": "native", "C/C++ header": "native", "C++": "native", "CUDA": "native", "Rust": "native",
    "Zig": "native", "Objective-C++": "native", "Assembly": "native", "HIP": "native", "OpenCL": "native",
    "Go": "managed", "Java": "managed", "Kotlin": "managed", "Scala": "managed", "C#": "managed",
    "F#": "managed", "Swift": "managed", "Dart": "managed",
    "Python": "dynamic", "Ruby": "dynamic", "PHP": "dynamic", "Perl": "dynamic", "Lua": "dynamic",
    "JavaScript": "dynamic", "JavaScript (JSX)": "dynamic", "TypeScript": "dynamic",
    "TypeScript (TSX)": "dynamic", "Elixir": "dynamic", "R": "dynamic", "Julia": "dynamic",
    "Shell": "shell", "PowerShell": "shell", "Batch": "shell", "Fish": "shell",
    "SQL": "query", "GraphQL": "query", "Prisma": "query",
    "Verilog": "hdl", "SystemVerilog": "hdl", "VHDL": "hdl", "SDC/Tcl": "hdl", "XDC/Tcl": "hdl",
    "Dockerfile": "infra", "Terraform": "infra", "HCL": "infra", "YAML": "config",
    "YAML (GitLab CI)": "infra", "Nix": "infra", "Starlark": "build", "CMake": "build",
    "Makefile": "build", "Solidity": "contract", "Vyper": "contract", "Move": "contract",
}

DEFAULT_IGNORE = [
    "node_modules/**", "**/node_modules/**", "vendor/**", "**/vendor/**", "third_party/**",
    "**/third_party/**", "dist/**", "build/**", "out/**", "target/**", ".venv/**", "venv/**",
    "**/__pycache__/**", ".git/**", "**/*.min.js", "**/*.min.css", "**/*.map",
    "package-lock.json", "**/package-lock.json", "yarn.lock", "**/yarn.lock", "pnpm-lock.yaml",
    "**/pnpm-lock.yaml", "Cargo.lock", "**/Cargo.lock", "poetry.lock", "**/poetry.lock",
    "go.sum", "**/go.sum", "Gemfile.lock", "**/Gemfile.lock", "composer.lock", "uv.lock",
    "**/*_pb2.py", "**/*_pb2_grpc.py", "**/*.pb.go", "**/*.pb.cc", "**/*.pb.h", "**/*.g.dart",
    "**/*.generated.*", "**/generated/**", "**/*.snap",
]

GENERATED_MARKERS = re.compile(
    r"@generated|DO NOT EDIT|Code generated .* DO NOT EDIT|auto-?generated|This file was automatically generated",
    re.IGNORECASE,
)

BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip", ".gz", ".tgz", ".xz",
    ".bz2", ".7z", ".jar", ".war", ".class", ".so", ".dylib", ".dll", ".exe", ".o", ".a", ".obj",
    ".bin", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4", ".mov", ".wav", ".ogg",
    ".sqlite", ".db", ".pyc", ".whl", ".pt", ".onnx", ".h5", ".npy", ".npz", ".parquet", ".gds",
    ".oas", ".fsdb", ".vcd", ".fst",
}


def detect_language(path: str, head: str | None = None) -> str:
    p = Path(path)
    name = p.name.lower()
    if name in FILENAMES:
        return FILENAMES[name]
    if name.startswith("dockerfile") or name.endswith(".dockerfile"):
        return "Dockerfile"
    if name.startswith(".env"):
        return "dotenv"
    if ".github/workflows/" in path.replace("\\", "/"):
        return "YAML (GitHub Actions)"
    suffix = p.suffix
    if suffix in EXTENSIONS:  # case-sensitive first (.S vs .s, .R)
        return EXTENSIONS[suffix]
    if suffix.lower() in EXTENSIONS:
        return EXTENSIONS[suffix.lower()]
    if head and head.startswith("#!"):
        first = head.splitlines()[0]
        for needle, lang in SHEBANGS:
            if needle in first:
                return lang
    return "Unknown"


def family(language: str) -> str:
    return FAMILY.get(language, "other")


def is_binary(path: str, sample: bytes | None = None) -> bool:
    if Path(path).suffix.lower() in BINARY_EXT:
        return True
    if sample is not None and b"\x00" in sample[:8192]:
        return True
    return False


def matches_any(path: str, patterns: list[str]) -> bool:
    path = path.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(path, pat[3:]):
            return True
        # allow "dir/**" to match the directory prefix and bare names to match any depth
        if pat.endswith("/**") and (path + "/").startswith(pat[:-2]):
            return True
        if "/" not in pat and fnmatch.fnmatch(Path(path).name, pat):
            return True
    return False


def looks_generated(head: str) -> bool:
    return bool(GENERATED_MARKERS.search(head[:2000]))
