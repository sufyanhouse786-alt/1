"""Minimal cTrader MCP client over streamable HTTP (stdlib only)."""
import json
import os
import urllib.request

URL = os.environ.get("CTRADER_MCP_URL", "https://mcp.ctrader.com/trading/mcp")


class CTrader:
    def __init__(self, token=None):
        self.token = token or os.environ["CTRADER_MCP_TOKEN"]
        self.sid = None
        self.n = 0
        self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "eurusd-bot", "version": "1"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _post(self, body):
        h = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(URL, json.dumps(body).encode(), h, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            self.sid = r.headers.get("Mcp-Session-Id") or self.sid
            raw = r.read().decode()
        if not raw.strip():
            return None
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
        msgs = [json.loads(l[5:]) for l in raw.splitlines() if l.startswith("data:")]
        return msgs[-1] if msgs else None

    def _rpc(self, method, params):
        self.n += 1
        res = self._post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        if "error" in res:
            raise RuntimeError(res["error"])
        return res["result"]

    def call(self, tool, **args):
        res = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = "".join(c.get("text", "") for c in res.get("content", []))
        if res.get("isError"):
            raise RuntimeError("%s: %s" % (tool, text))
        try:
            return json.loads(text)
        except ValueError:
            return text
