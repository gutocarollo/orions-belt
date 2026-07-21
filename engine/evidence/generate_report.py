#!/usr/bin/env python3
"""Render a validated evidence manifest as a self-contained static HTML report."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from .manifest import EvidenceValidationError, assert_valid_manifest, canonical_hash
except ImportError:
    from manifest import EvidenceValidationError, assert_valid_manifest, canonical_hash


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _href(uri: str) -> str | None:
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme not in {"http", "https", "file"}:
        return None
    return _e(uri)


def _refs(values: list[str]) -> str:
    return ", ".join(f'<code><a href="#{_e(value)}">{_e(value)}</a></code>' for value in values) or "—"


def render_report(manifest: dict[str, Any]) -> str:
    assert_valid_manifest(manifest)
    digest = canonical_hash(manifest)
    counts = {status: sum(claim["status"] == status for claim in manifest["claims"]) for status in ("PASS", "FAIL", "UNVERIFIED")}
    claims = "".join(
        "<tr id=\"{id}\"><td><code>{id}</code></td><td>{statement}</td><td><span class=\"status {status_class}\">{status}</span></td><td>{activities}</td><td>{entities}</td><td>{valid}</td></tr>".format(
            id=_e(item["id"]), statement=_e(item["statement"]), status=_e(item["status"]), status_class=_e(item["status"].lower()),
            activities=_refs(item["activities"]), entities=_refs(item["entities"]), valid=_e(item["valid_at"]),
        ) for item in manifest["claims"]
    )
    activities = "".join(
        "<tr id=\"{id}\"><td><code>{id}</code></td><td>{type}</td><td><code>{agent}</code></td><td><code>{command}</code></td><td>{exit}</td><td>{used}</td><td>{generated}</td></tr>".format(
            id=_e(item["id"]), type=_e(item["type"]), agent=_e(item["agent_id"]),
            command=_e(" ".join(item.get("command", [])) or "—"), exit=_e(item.get("exit_code", "—")),
            used=_refs(item["used"]), generated=_refs(item["generated"]),
        ) for item in manifest["activities"]
    )
    entity_rows: list[str] = []
    for item in manifest["entities"]:
        href = _href(item["uri"])
        uri = f'<a href="{href}">{_e(item["uri"])}</a>' if href else _e(item["uri"])
        context = " · ".join(filter(None, (item.get("route"), item.get("theme")))) or "—"
        entity_rows.append(
            "<tr id=\"{id}\"><td><code>{id}</code></td><td>{type}</td><td>{uri}</td><td><code>{sha}</code></td><td><span class=\"trust {trust}\">{trust}</span></td><td>{context}</td></tr>".format(
                id=_e(item["id"]), type=_e(item["type"]), uri=uri, sha=_e(item["sha256"]),
                trust=_e(item["trust"]), context=_e(context),
            )
        )
    agents = "".join(
        f'<tr id="{_e(item["id"])}"><td><code>{_e(item["id"])}</code></td><td>{_e(item["name"])}</td><td>{_e(item["type"])}</td><td>{_e(item.get("version", "—"))}</td></tr>'
        for item in manifest["agents"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:;">
<title>{_e(manifest['title'])}</title><style>
:root{{--bg:#f7f7f8;--panel:#fff;--text:#18181b;--muted:#666;--line:#ddd;--pass:#176b36;--fail:#a51d2d;--warn:#8a5a00}}
body{{font:14px/1.5 system-ui,sans-serif;margin:0;background:var(--bg);color:var(--text)}}main{{max-width:1180px;margin:auto;padding:32px}}section{{background:var(--panel);padding:20px;margin:16px 0;border:1px solid var(--line);border-radius:8px;overflow:auto}}h1,h2{{margin-top:0}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}code{{font-size:12px;word-break:break-all}}.meta{{color:var(--muted)}}.summary{{display:flex;gap:12px;flex-wrap:wrap}}.card{{padding:10px 16px;border:1px solid var(--line);border-radius:6px}}.status,.trust{{font-weight:700}}.pass,.trusted,.validated{{color:var(--pass)}}.fail,.quarantined{{color:var(--fail)}}.unverified,.untrusted{{color:var(--warn)}}a{{color:inherit}}
</style></head><body><main>
<h1>{_e(manifest['title'])}</h1><p class="meta">Report <code>{_e(manifest['report_id'])}</code> · git <code>{_e(manifest['git_sha'])}</code> · valid {_e(manifest['valid_at'])} · recorded {_e(manifest['recorded_at'])}</p>
<p class="meta">Canonical manifest digest: <code>sha256:{digest}</code></p>
<div class="summary"><div class="card"><b>{counts['PASS']}</b> pass</div><div class="card"><b>{counts['FAIL']}</b> fail</div><div class="card"><b>{counts['UNVERIFIED']}</b> unverified</div></div>
<section><h2>Claims</h2><table><thead><tr><th>ID</th><th>Statement</th><th>Status</th><th>Activities</th><th>Entities</th><th>Valid at</th></tr></thead><tbody>{claims}</tbody></table></section>
<section><h2>Activities</h2><table><thead><tr><th>ID</th><th>Type</th><th>Agent</th><th>Command</th><th>Exit</th><th>Used</th><th>Generated</th></tr></thead><tbody>{activities}</tbody></table></section>
<section><h2>Entities / artifacts / sources</h2><table><thead><tr><th>ID</th><th>Type</th><th>URI</th><th>SHA-256</th><th>Trust</th><th>Route / theme</th></tr></thead><tbody>{''.join(entity_rows)}</tbody></table></section>
<section><h2>Agents</h2><table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Version</th></tr></thead><tbody>{agents}</tbody></table></section>
</main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--verify-files", action="store_true")
    args = parser.parse_args()
    try:
        value = json.loads(args.manifest.read_text(encoding="utf-8"))
        assert_valid_manifest(value, args.manifest.parent, args.verify_files)
        rendered = render_report(value)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    except (OSError, json.JSONDecodeError, EvidenceValidationError) as exc:
        print(f"REPORT FAILED: {exc}")
        return 2
    print(f"REPORT: {args.output} sha256:{canonical_hash(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
