"""Tests for the MCP watch tool and _WatchRebuildHandler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

try:
    import watchdog  # noqa: F401
    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False


class TestMCPWatch:
    def test_watch_invalid_directory(self):
        """watch on a non-existent directory should return an error."""
        from codeloom.mcp_server import watch

        result = watch("/nonexistent/path_xyz")
        assert "not a valid directory" in result

    @pytest.mark.skipif(not _HAS_WATCHDOG, reason="watchdog not installed")
    def test_watch_with_real_watchdog(self):
        """watch should return status when watchdog is available."""
        import codeloom.mcp_server as mod
        from codeloom.mcp_server import watch
        mod._store = None
        mod._graph = None

        with patch("codeloom.mcp_server._get_db_path", return_value="/fake/db"):
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                result = watch(td)

        assert "Watching" in result
        assert "Status" in result


# ---------------------------------------------------------------------------
# _WatchRebuildHandler tests (no watchdog or sys.modules needed)
# ---------------------------------------------------------------------------


class TestWatchRebuildHandler:
    """Tests for the _WatchRebuildHandler class directly."""

    def test_handler_triggers_build_on_py_file(self, tmp_path):
        """A .py file event should trigger run_pipeline."""
        from codeloom.mcp_server import _WatchRebuildHandler

        handler = _WatchRebuildHandler(str(tmp_path))
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(tmp_path / "test.py")

        with (
            patch(
                "codeloom.core.pipeline.run_pipeline"
            ) as mock_run,
            patch("codeloom.mcp_server._reload"),
        ):
            handler.on_modified(mock_event)
            mock_run.assert_called_once()

    def test_handler_skips_directory(self, tmp_path):
        """Directory events should be ignored."""
        from codeloom.mcp_server import _WatchRebuildHandler

        handler = _WatchRebuildHandler(str(tmp_path))
        mock_event = MagicMock()
        mock_event.is_directory = True

        with patch("codeloom.core.pipeline.run_pipeline") as mock_run:
            handler.on_modified(mock_event)
            mock_run.assert_not_called()

    def test_handler_skips_unknown_extension(self, tmp_path):
        """Unrecognised file extensions should be ignored."""
        from codeloom.mcp_server import _WatchRebuildHandler

        handler = _WatchRebuildHandler(str(tmp_path))
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(tmp_path / "random.xyz123")

        with patch("codeloom.core.pipeline.run_pipeline") as mock_run:
            handler.on_modified(mock_event)
            mock_run.assert_not_called()

    def test_handler_cooldown_prevents_rapid_triggers(self, tmp_path):
        """Multiple rapid events should only trigger one build."""
        import time

        from codeloom.mcp_server import _WatchRebuildHandler
        handler = _WatchRebuildHandler(str(tmp_path))
        handler.last_rebuild = time.time()  # Just rebuilt = cooldown active

        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(tmp_path / "test.py")

        with patch("codeloom.core.pipeline.run_pipeline") as mock_run:
            handler.on_modified(mock_event)
            mock_run.assert_not_called()

    def test_handler_build_error_logged(self, tmp_path):
        """A failing build should not crash the handler."""
        from codeloom.mcp_server import _WatchRebuildHandler

        handler = _WatchRebuildHandler(str(tmp_path))
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(tmp_path / "test.py")

        with (
            patch(
                "codeloom.core.pipeline.run_pipeline",
                side_effect=RuntimeError("build failed"),
            ),
            patch("codeloom.mcp_server.logger") as mock_logger,
        ):
            handler.on_modified(mock_event)
            mock_logger.error.assert_called_once()

    def test_handler_calls_reload_after_build(self, tmp_path):
        """After a successful build, _reload should be called."""
        from codeloom.mcp_server import _WatchRebuildHandler

        handler = _WatchRebuildHandler(str(tmp_path))
        mock_event = MagicMock()
        mock_event.is_directory = False
        mock_event.src_path = str(tmp_path / "test.py")

        with (
            patch(
                "codeloom.core.pipeline.run_pipeline"
            ),
            patch("codeloom.mcp_server._reload") as mock_reload,
        ):
            handler.on_modified(mock_event)
            mock_reload.assert_called_once()
