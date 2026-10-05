import html
import json
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement


def write_reports(report: dict, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    esc = html.escape
    metrics = "".join(
        f"<tr><th>{esc(name)}</th><td>{value:.4f}</td></tr>"
        if value is not None
        else f"<tr><th>{esc(name)}</th><td>n/a</td></tr>"
        for name, value in report["metrics"].items()
    )
    cases = "".join(
        "<details><summary>"
        + esc(row["id"] + " — " + row["question"])
        + "</summary><pre>"
        + esc(json.dumps(row, indent=2))
        + "</pre></details>"
        for row in report["cases"]
    )
    failures = "".join("<li>" + esc(f) + "</li>" for f in report["failures"])
    status = "PASS" if report["passed"] else "FAIL"
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Evidence Gate: {esc(report["suite"])}</title>
<style>body{{max-width:960px;margin:48px auto;padding:0 24px;font:16px/1.6 system-ui;color:#152d36}}
h1{{font-size:32px}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 12px;border-bottom:1px solid #d4dce0;text-align:left}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f7;padding:16px;font-size:13px}}
details{{margin:16px 0}}summary{{cursor:pointer}}small{{color:#52636d}}</style>
<h1>Evidence Gate / {status}</h1><p>{esc(report["suite"])} · {report["case_count"]} cases · {esc(report["transport"])}</p>
<small>Fixture fingerprint: {esc(report["fingerprint"])}<br>{esc(report["created_at"])}</small>
<h2>Metrics</h2><table>{metrics}</table><ul>{failures}</ul><h2>Case details</h2>{cases}
<p>Quote integrity is an exact-span check. It does not prove that an answer is semantically correct.</p></html>"""
    (directory / "report.html").write_text(page)
    # JUnit represents suite-level quality gates; per-case diagnostics are in HTML/JSON.
    root = Element(
        "testsuite",
        name=report["suite"],
        tests=str(max(1, len(report["failures"]))),
        failures=str(len(report["failures"])),
    )
    if not report["failures"]:
        SubElement(root, "testcase", name="quality gates")
    for i, failure in enumerate(report["failures"], 1):
        case = SubElement(root, "testcase", name=f"quality gate {i}")
        SubElement(case, "failure", message=failure).text = failure
    ElementTree(root).write(directory / "junit.xml", encoding="unicode", xml_declaration=True)
