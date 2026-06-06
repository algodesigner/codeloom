"""Tests for file detection and classification."""

from codeloom.core.detect import (
    EXT_TO_LANG,
    NAME_TO_LANG,
    detect,
    get_file_info,
)


class TestDetect:
    def test_detects_python_files(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "util.js").write_text("console.log('hi')")
        result = detect(tmp_path)
        langs = {f.language for f in result.files}
        assert "python" in langs
        assert "javascript" in langs
        assert len(result.files) == 2

    def test_skips_hidden_dirs(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("x")
        (tmp_path / "app.py").write_text("x = 1")
        result = detect(tmp_path)
        assert len(result.files) == 1
        assert result.files[0].language == "python"

    def test_skips_large_files(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_text("x" * 2_000_000)
        result = detect(tmp_path, max_file_size=1_000_000)
        assert len(result.files) == 0
        assert any("too_large" in s for s in result.skipped)

    def test_skips_sensitive_files(self, tmp_path):
        (tmp_path / ".env").write_text("SECRET=x")
        (tmp_path / "app.py").write_text("x = 1")
        result = detect(tmp_path)
        assert len(result.files) == 1
        assert any("sensitive" in s for s in result.skipped)

    def test_respects_ignore_file(self, tmp_path):
        (tmp_path / ".codeloom-ignore").write_text("vendor\n")
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "lib.py").write_text("x")
        (tmp_path / "app.py").write_text("x")
        result = detect(tmp_path)
        assert len(result.files) == 1

    def test_ext_to_lang_coverage(self):
        assert EXT_TO_LANG[".py"] == "python"
        assert EXT_TO_LANG[".ts"] == "typescript"
        assert EXT_TO_LANG[".go"] == "go"
        assert EXT_TO_LANG[".rs"] == "rust"

    def test_empty_directory(self, tmp_path):
        result = detect(tmp_path)
        assert len(result.files) == 0


class TestNameToLang:
    def test_extensionless_dockerfile(self, tmp_path):
        p = tmp_path / "Dockerfile"
        p.write_text("FROM ubuntu\n")
        info = get_file_info(p)
        assert info is not None
        assert info.language == "dockerfile"

    def test_extensionless_makefile(self, tmp_path):
        p = tmp_path / "Makefile"
        p.write_text("all:\n\techo ok\n")
        info = get_file_info(p)
        assert info is not None
        assert info.language == "make"

    def test_dockerfile_dot_ext(self, tmp_path):
        p = tmp_path / "web.dockerfile"
        p.write_text("FROM nginx\n")
        info = get_file_info(p)
        assert info is not None
        assert info.language == "dockerfile"

    def test_cmakelists_detected(self, tmp_path):
        p = tmp_path / "CMakeLists.txt"
        p.write_text("cmake_minimum_required(VERSION 3.0)\n")
        info = get_file_info(p)
        assert info is not None
        assert info.language == "cmake"

    def test_new_extensions_detected(self, tmp_path):
        cases = [
            (".hs", "haskell"),
            (".jl", "julia"),
            (".zig", "zig"),
            (".sol", "solidity"),
            (".nix", "nix"),
            (".css", "css"),
            (".sql", "sql"),
            (".cmake", "cmake"),
            (".lisp", "commonlisp"),
            (".graphql", "graphql"),
            (".pl", "perl"),
        ]
        for ext, expected in cases:
            p = tmp_path / f"test{ext}"
            p.write_text("x")
            info = get_file_info(p)
            assert info is not None, f"{ext} should be detected"
            assert info.language == expected, f"{ext} → {expected}"

    def test_mapping_coverage(self):
        assert NAME_TO_LANG["dockerfile"] == "dockerfile"
        assert NAME_TO_LANG["makefile"] == "make"
        assert NAME_TO_LANG["gnumakefile"] == "make"
