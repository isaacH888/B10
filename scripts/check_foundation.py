"""Check the shared contract, examples, links, templates and workflow locally or in CI."""

import csv
import io
import json
import re
import subprocess
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate_spec
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_URI = "urn:popssibilities:contract"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    spec = json.loads((ROOT / "docs/api/openapi.json").read_text())
    bundle = json.loads((ROOT / "docs/api/examples.json").read_text())
    validate_spec(spec)
    registry = Registry().with_resource(CONTRACT_URI, Resource.from_contents(spec, default_specification=DRAFT202012))

    def check_example(value, schema):
        # References resolve inside the contract rather than through the network.
        target = {"$ref": CONTRACT_URI + schema["$ref"]} if "$ref" in schema else schema
        Draft202012Validator(target, registry=registry, format_checker=FormatChecker()).validate(value)

    checked = 0
    operation_ids = set()
    for route, path in spec["paths"].items():
        for method, operation in path.items():
            identifier = operation["operationId"]
            require(identifier not in operation_ids, "Duplicate operation ID")
            operation_ids.add(identifier)
            require(operation.get("x-owner"), "Operation owner is missing")
            contents = list(operation.get("requestBody", {}).get("content", {}).values())
            for response in operation["responses"].values():
                contents.extend(response.get("content", {}).values())
            for content in contents:
                examples = [item["value"] for item in content.get("examples", {}).values()]
                if "example" in content:
                    examples.append(content["example"])
                for value in examples:
                    check_example(value, content["schema"])
                    checked += 1
    mappings = {
        "quote_request": "QuoteRequest", "quote_requires_review_response": "QuoteResponse",
        "quote_priced_fixture_response": "QuoteResponse", "quote_outside_radius_response": "QuoteResponse",
        "order_request": "SubmitOrderRequest", "order_response": "OrderResponse",
        "minimum_quantity_error": "ErrorResponse", "deposit_request": "UpdateDepositRequest",
        "deposit_response": "AdminOrderResponse",
    }
    for key, name in mappings.items():
        check_example(bundle[key], {"$ref": "#/components/schemas/" + name})
        checked += 1
    for key in ("quote_priced_fixture_response", "order_response", "deposit_response"):
        pricing = bundle[key]["data"]["pricing"]
        require(sum(item["amount_cents"] for item in pricing["line_items"]) == pricing["total_cents"], "Fixture line-item mismatch")
        require(pricing["deposit_due_cents"] * 2 == pricing["total_cents"], "Fixture deposit mismatch")
    csv_data = spec["paths"]["/orders/export"]["get"]["responses"]["200"]["content"]["text/csv"]["example"]
    require(all(len(row) == 10 for row in csv.reader(io.StringIO(csv_data))), "CSV fixture column mismatch")

    link_count = 0
    documents = [ROOT / "readme.md", *ROOT.joinpath("docs").rglob("*.md"), *ROOT.joinpath(".github").rglob("*.md")]
    for document in documents:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
            if "://" in target or target.startswith(("mailto:", "#")):
                continue
            require((document.parent / target.split("#", 1)[0]).exists(), "Broken file link: " + target)
            link_count += 1
    config_text = (ROOT / "docs/configuration.md").read_text()
    for template in (ROOT / ".env.example", ROOT / "backend/.env.example", ROOT / "frontend/.env.example"):
        seen = set()
        for line in template.read_text().splitlines():
            if not line or line.startswith("#"):
                continue
            name, value = line.split("=", 1)
            require(name not in seen, "Duplicate template key: " + name)
            seen.add(name)
            require(name in config_text, "Undocumented setting: " + name)
            if any(term in name for term in ("SECRET", "PASSWORD", "API_KEY", "TOKEN", "CREDENTIALS")):
                require(not value, "Credential placeholder must be empty: " + name)
        if template.parent.name == "frontend":
            require(seen == {"VITE_API_BASE_URL"}, "Frontend template contains private settings")

    workflow = yaml.safe_load((ROOT / ".github/workflows/foundation-checks.yml").read_text())
    require(workflow["permissions"] == {"contents": "read"}, "Unexpected CI token permissions")
    require("pull_request" in workflow["on"], "PR checks are missing")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    require(compose["services"]["mysql"]["ports"] == ["127.0.0.1:3306:3306"], "Development DB must bind locally")
    require("environment" not in workflow["jobs"]["foundation"], "Foundation CI must not deploy")

    files = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    text_suffixes = {".md", ".py", ".json", ".js", ".jsx", ".css", ".html", ".yml", ".yaml", ".in", ".txt", ".ini"}
    for filename in files:
        path = ROOT / filename
        if not path.is_file() or (path.suffix not in text_suffixes and path.name not in {".gitignore", ".env.example", ".node-version", ".python-version"}):
            continue
        if filename == "docs/project-charter.md":
            continue
        text = path.read_text()
        require(text.endswith("\n"), "Missing final newline: " + filename)
        require(all(line.rstrip(" \t") == line for line in text.splitlines()), "Trailing whitespace: " + filename)
        require(not re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", text), "Emoji in shared file: " + filename)
    print("PASS: OpenAPI standards validation; %d operations; %d schema-valid examples; %d local file links." % (len(operation_ids), checked, link_count))
    print("PASS: configuration placeholders, fixture money/CSV, workflow/Compose structure, whitespace and code style.")
    print("Scope: shared foundation only; no business feature conformance or external deployment.")


if __name__ == "__main__":
    main()
