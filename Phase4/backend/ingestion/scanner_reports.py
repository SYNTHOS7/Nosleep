"""Offline scanner adapters. Findings are reported observations, never exploitability proof."""
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

from backend.contracts.models import CandidateGraph, Entity, Relation, Provenance

FORMATS = {"trivy", "osv", "sarif"}


def text(value, limit=240):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float)):
        raise ValueError("Invalid scanner field")
    value = re.sub(r"[\x00-\x1f]", " ", str(value))[:limit]
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"}:
            value = urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
    return value


def normalize_report(content, format_name):
    if format_name not in FORMATS or len(content) > 5 * 1024 * 1024:
        raise ValueError("Unsupported scanner format or report exceeds 5 MiB")
    report = json.loads(content.decode("utf-8"))
    if not isinstance(report, dict):
        raise ValueError("Report must be an object")
    findings = []

    def add(tool, artifact, vulnerability, package="", version="", fixed="", severity="UNKNOWN", description="", line=None, aliases=None, ecosystem=""):
        finding = {"tool": text(tool, 60), "artifact": text(artifact), "vulnerability": text(vulnerability, 100),
                   "package": text(package, 120), "version": text(version, 80), "fixed": text(fixed, 80),
                   "severity": text(severity, 30).upper(), "description": text(description)}
        if package:
            finding["ecosystem"] = text(ecosystem or tool, 60)
        if aliases:
            if not isinstance(aliases, list) or len(aliases) > 100:
                raise ValueError("Invalid vulnerability aliases")
            finding["aliases"] = sorted({alias for alias in aliases if isinstance(alias, str)
                                         and re.fullmatch(r"CVE-[0-9]{4}-[0-9]{4,19}", alias)})[:10]
        if line is not None:
            if not isinstance(line, int) or line < 1:
                raise ValueError("Invalid source line")
            finding["line"] = line
        if not finding["vulnerability"] or not finding["artifact"]:
            raise ValueError("Finding requires a rule/vulnerability ID and artifact")
        # Tool + artifact + package version + finding ID distinguishes observations.
        encoded = json.dumps(finding, sort_keys=True, ensure_ascii=True, allow_nan=False)
        finding["id"] = hashlib.sha256(encoded.encode()).hexdigest()[:24]
        findings.append(finding)
        if len(findings) > 2000:
            raise ValueError("At most 2000 findings per report")

    if format_name == "trivy":
        if not isinstance(report.get("Results"), list):
            raise ValueError("Expected Trivy JSON Results")
        for result in report["Results"]:
            for item in result.get("Vulnerabilities") or []:
                target = result.get("Target") or report.get("ArtifactName")
                if report.get("ArtifactName") and result.get("Target"):
                    target = text(report["ArtifactName"], 100) + " :: " + text(result["Target"], 120)
                add("Trivy", target, item.get("VulnerabilityID"),
                    item.get("PkgName"), item.get("InstalledVersion"), item.get("FixedVersion"),
                    item.get("Severity", "UNKNOWN"), item.get("Title"), ecosystem=result.get("Type", ""))
    elif format_name == "osv":
        if not isinstance(report.get("results"), list):
            raise ValueError("Expected OSV-Scanner JSON results")
        for result in report["results"]:
            artifact = result.get("source", {}).get("path")
            for entry in result.get("packages", []):
                package = entry.get("package", {})
                for item in entry.get("vulnerabilities", []):
                    severity = item.get("database_specific", {}).get("severity", "UNKNOWN")
                    add("OSV-Scanner", artifact, item.get("id"), package.get("name"), package.get("version"),
                        severity=severity, description=item.get("summary"), aliases=item.get("aliases"), ecosystem=package.get("ecosystem", ""))
    else:
        if report.get("version") != "2.1.0" or not isinstance(report.get("runs"), list):
            raise ValueError("Expected SARIF 2.1.0")
        for run in report["runs"]:
            tool = run.get("tool", {}).get("driver", {}).get("name", "SARIF")
            # Secret reports need a dedicated redaction pipeline; never ingest their snippets.
            if any(name in str(tool).lower() for name in ("gitleaks", "secret", "betterleaks")):
                raise ValueError("Secret-scanner reports are not accepted")
            for item in run.get("results", []):
                for location in item.get("locations", []):
                    physical = location.get("physicalLocation", {})
                    artifact = physical.get("artifactLocation", {}).get("uri")
                    add(tool, artifact, item.get("ruleId"), severity=item.get("level", "warning"),
                        description=item.get("message", {}).get("text", ""),
                        line=physical.get("region", {}).get("startLine"))
    if not findings:
        raise ValueError("No supported vulnerability/code findings found; this does not certify a clean scan")
    findings = sorted({f["id"]: f for f in findings}.values(), key=lambda f: f["id"])
    canonical = json.dumps(findings, sort_keys=True, ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    lines = ["SCANNER REPORT IMPORT: Uploaded observations are unverified and do not prove exploitability.",
             "Only selected fields are retained; source snippets, secrets and raw network requests are omitted."]
    lines.extend("FINDING_RECORD: " + json.dumps(f, sort_keys=True, ensure_ascii=True) for f in findings)
    from backend.ingestion.chunker import count_tokens
    if any(count_tokens(line) > 600 for line in lines):
        raise ValueError("A finding exceeds the evidence chunk limit; shorten its descriptive fields")
    return {"document_id": f"scan-{digest[:24]}", "text": "\n\n".join(lines),
            "count": len(findings), "format": format_name}


def extract_scanner_chunk(chunk):
    entities, relations = {}, []
    for match in re.finditer(r"FINDING_RECORD: (\{[^\n]+\})", chunk.text):
        finding = json.loads(match.group(1))
        artifact = "artifact:" + finding["artifact"]
        vulnerability = finding["vulnerability"]
        package = f"package:{finding.get('ecosystem', finding['tool'])}:{finding['package']}@{finding['version']}" if finding["package"] else None
        for name, label in [(artifact, "Artifact"), (vulnerability, "Vulnerability" if re.fullmatch(r"CVE-\d{4}-\d{4,19}", vulnerability) else "Concept"), (package, "Concept")]:
            if name:
                entities[name] = Entity(id="scanner-" + hashlib.sha256(name.encode()).hexdigest()[:20],
                    name=name, label=label, source_chunk_id=chunk.id, properties={"reported_by": finding["tool"]})
        pairs = [(artifact, vulnerability, "REPORTS_FINDING")]
        if package:
            pairs += [(artifact, package, "REPORTS_PACKAGE"), (package, vulnerability, "REPORTS_FINDING")]
        for alias in finding.get("aliases", []):
            if alias == vulnerability:
                continue
            entities[alias] = Entity(id="scanner-" + hashlib.sha256(alias.encode()).hexdigest()[:20],
                name=alias, label="Vulnerability", source_chunk_id=chunk.id, properties={"reported_by": finding["tool"]})
            pairs.append((vulnerability, alias, "REPORTED_ALIAS"))
        for source, target, predicate in pairs:
            identity = hashlib.sha256(f"{source}\0{target}".encode()).hexdigest()[:12]
            relations.append(Relation(id=f"scan-{finding['id']}-{predicate}-{identity}",
                source_entity_name=source, source_entity_label=entities[source].label, predicate=predicate,
                target_entity_name=target, target_entity_label=entities[target].label,
                provenance=Provenance(source_chunk_id=chunk.id, exact_quote=match.group(0),
                                      char_start=match.start(), char_end=match.end(), extraction_method="scanner-report-adapter")))
    return CandidateGraph(chunk_id=chunk.id, entities=list(entities.values()), relations=relations,
                          warnings=["Scanner observations are not verified exploit paths."], is_empty=not entities)
