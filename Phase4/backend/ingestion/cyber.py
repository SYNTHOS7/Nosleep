"""Conservative extraction of explicit cyber assertions; never executes input."""
import re

TOKEN = r"[A-Za-z][A-Za-z0-9_-]*"
PATTERN = re.compile(
    rf"^({TOKEN})\s+(?:(does not|cannot)\s+|(may)\s+)?"
    rf"(exploits?|targets?|communicates with|access(?:es)?|mitigates?|exfiltrates?)\s+"
    rf"({TOKEN})(?:\s+(if\s+[^.!?]+))?[.!?]?$", re.I,
)
PREDICATES = {
    "exploit": "EXPLOITS", "target": "TARGETS", "communicates with": "COMMUNICATES_WITH",
    "access": "ACCESSES", "mitigate": "MITIGATES", "exfiltrate": "EXFILTRATES",
}


def label(name, default="Asset"):
    if re.fullmatch(r"CVE-\d{4}-\d{4,}", name, re.I):
        return "Vulnerability"
    if re.fullmatch(r"T\d{4}(?:_\d{3})?", name):
        return "Technique"
    return default


def extract_cyber_sentence(text):
    # Preserve suspicious instructions as an artifact, not factual assertions.
    if re.search(r"ignore (?:all |previous )?instructions|system override|mark .*benign", text, re.I):
        return {"entities": [{"name": text, "label": "AttackPayload", "properties": {"untrusted": True}}],
                "values": [], "relations": []}
    match = PATTERN.fullmatch(text)
    if not match:
        return None
    source, negative, possible, verb, target, condition = match.groups()
    verb = verb.lower()
    predicate = PREDICATES.get(verb) or PREDICATES.get(verb.removesuffix("s"))
    if verb == "accesses":
        predicate = "ACCESSES"
    if not predicate:
        return None
    source_label = label(source, "ThreatActor" if predicate == "EXPLOITS" else "Asset")
    target_label = label(target)
    return {
        "entities": [{"name": source, "label": source_label}, {"name": target, "label": target_label}],
        "values": [],
        "relations": [{"source_entity_name": source, "source_entity_label": source_label,
                       "predicate": predicate, "target_entity_name": target, "target_entity_label": target_label,
                       "polarity": "NEGATIVE" if negative else "AFFIRMATIVE",
                       "modality": "CONDITIONAL" if condition else "POSSIBLE" if possible else "CERTAIN",
                       "condition": condition, "exact_quote": text}],
    }
