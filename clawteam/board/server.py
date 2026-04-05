"""Lightweight HTTP server for the Web UI dashboard (stdlib only)."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from clawteam.board.collector import BoardCollector

_STATIC_DIR = Path(__file__).parent / "static"


class BoardHandler(BaseHTTPRequestHandler):
    """HTTP handler for the board Web UI."""

    collector: BoardCollector
    default_team: str = ""
    interval: float = 2.0

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/" or path == "/index.html":
            self._serve_static("index.html", "text/html")
        elif path.startswith("/") and (_STATIC_DIR / path.lstrip("/")).exists():
            filename = path.lstrip("/")
            content_type = "text/plain"
            if filename.endswith(".js"):
                content_type = "application/javascript"
            elif filename.endswith(".css"):
                content_type = "text/css"
            elif filename.endswith(".html"):
                content_type = "text/html"
            self._serve_static(filename, content_type)
        elif path == "/api/overview":
            self._serve_json(self.collector.collect_overview())
        elif path.startswith("/api/board/"):
            team_name = path[len("/api/board/"):].strip("/")
            if not team_name:
                self.send_error(400, "Team name required")
                return
            self._serve_team(team_name)
        elif path.startswith("/api/team/"):
            team_name = path[len("/api/team/"):].strip("/")
            if not team_name:
                self.send_error(400, "Team name required")
                return
            self._serve_team(team_name)
        elif path.startswith("/api/teams/"):
            self._serve_team_api(path[len("/api/teams/"):])
        elif path.startswith("/api/events/"):
            team_name = path[len("/api/events/"):].strip("/")
            if not team_name:
                self.send_error(400, "Team name required")
                return
            self._serve_sse(team_name)
        else:
            self.send_error(404)

    def _serve_static(self, filename: str, content_type: str):
        filepath = _STATIC_DIR / filename
        if not filepath.exists():
            self.send_error(404, f"Static file not found: {filename}")
            return
        content = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _serve_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_team(self, team_name: str):
        try:
            data = self.collector.collect_team(team_name)
            self._serve_json(data)
        except ValueError as e:
            self._serve_json_error(404, str(e))

    def _serve_team_api(self, suffix: str):
        parts = [unquote(part) for part in suffix.strip("/").split("/") if part]
        if not parts:
            self._serve_json_error(400, "Team name required")
            return
        team_name = parts[0]
        route = parts[1:]
        try:
            if not route:
                self._serve_json(self.collector.collect_team(team_name))
            elif route == ["workers"]:
                data = self.collector.collect_team(team_name)
                self._serve_json({"teamName": team_name, "workers": data["runtimeConsole"]["workers"]})
            elif route == ["tasks"]:
                data = self.collector.collect_team(team_name)
                self._serve_json(
                    {
                        "teamName": team_name,
                        "summary": data["taskSummary"],
                        "grouped": data["tasks"],
                        "tasks": data["runtimeConsole"]["tasks"],
                        "faults": data.get("taskReadFaults", []),
                    }
                )
            elif route == ["coding", "jobs"]:
                self._serve_json(self.collector.collect_coding_jobs(team_name))
            elif len(route) == 3 and route[:2] == ["coding", "jobs"]:
                self._serve_json(self.collector.collect_coding_job(team_name, route[2]))
            elif len(route) == 4 and route[:2] == ["coding", "jobs"] and route[3] == "events":
                self._serve_json(self.collector.collect_coding_job_events(team_name, route[2]))
            elif len(route) == 4 and route[:2] == ["coding", "jobs"] and route[3] == "result":
                self._serve_json(self.collector.collect_coding_job_result(team_name, route[2]))
            elif len(route) == 4 and route[:2] == ["coding", "jobs"] and route[3] == "artifacts":
                self._serve_json(self.collector.collect_coding_job_artifacts(team_name, route[2]))
            elif len(route) == 5 and route[:2] == ["coding", "jobs"] and route[3] == "artifacts":
                self._serve_json(
                    self.collector.collect_coding_job_artifact_preview(team_name, route[2], route[4])
                )
            elif route == ["coding", "sessions"]:
                self._serve_json(self.collector.collect_provider_sessions(team_name))
            elif len(route) == 3 and route[:2] == ["coding", "sessions"]:
                self._serve_json(self.collector.collect_provider_session(team_name, route[2]))
            elif len(route) == 4 and route[:2] == ["coding", "sessions"] and route[3] == "jobs":
                self._serve_json(self.collector.collect_provider_session_jobs(team_name, route[2]))
            elif len(route) == 4 and route[:2] == ["coding", "sessions"] and route[3] == "events":
                self._serve_json(self.collector.collect_provider_session_events(team_name, route[2]))
            elif route == ["callbacks"]:
                self._serve_json(self.collector.collect_callbacks(team_name))
            elif route == ["faults"]:
                self._serve_json(self.collector.collect_faults(team_name))
            elif route == ["timeline"]:
                self._serve_json(self.collector.collect_timeline(team_name))
            else:
                self._serve_json_error(404, f"Unknown API route: /api/teams/{'/'.join(parts)}")
        except ValueError as exc:
            self._serve_json_error(404, str(exc))

    def _serve_json_error(self, status: int, message: str):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self, team_name: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            while True:
                try:
                    data = self.collector.collect_team(team_name)
                except ValueError as e:
                    data = {"error": str(e)}
                payload = json.dumps(data, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(self.interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, format, *args):
        # Suppress default stderr logging for SSE connections
        first = str(args[0]) if args else ""
        if "/api/events/" not in first:
            super().log_message(format, *args)


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    default_team: str = "",
    interval: float = 2.0,
):
    """Start the Web UI server."""
    collector = BoardCollector()
    BoardHandler.collector = collector
    BoardHandler.default_team = default_team
    BoardHandler.interval = interval

    server = ThreadingHTTPServer((host, port), BoardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
