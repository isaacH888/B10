"""Reject an old rerun when a newer DEV commit has already passed all release checks."""

import argparse
import json
import os
from urllib.request import Request, urlopen

REQUIRED_JOBS = {
    "Python formatting and lint",
    "Contract and backend integration",
    "Frontend formatting, build and browser tests",
    "Cognito configuration validation",
    "Build website Lambda package",
}


def api(path):
    request = Request(
        "https://api.github.com/repos/isaacH888/B10/" + path,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def check_candidate(commit, run_number):
    for page in range(1, 101):
        runs = api(
            f"actions/workflows/foundation-checks.yml/runs?branch=dev&per_page=100&page={page}"
        )["workflow_runs"]
        if not runs:
            return
        for run in runs:
            if run["run_number"] <= run_number:
                continue
            if run["head_sha"] == commit or run["event"] not in {"push", "workflow_dispatch"}:
                continue
            jobs = {}
            # Failed-job reruns inherit prerequisites from earlier attempts.
            # Read attempts explicitly; API job ordering is not a version order.
            for attempt in range(run["run_attempt"], 0, -1):
                for job_page in range(1, 101):
                    items = api(
                        f"actions/runs/{run['id']}/attempts/{attempt}/jobs"
                        f"?per_page=100&page={job_page}"
                    )["jobs"]
                    for job in items:
                        jobs.setdefault(job["name"], job["conclusion"])
                    if len(items) < 100:
                        break
                if REQUIRED_JOBS <= jobs.keys():
                    break
            if all(jobs.get(name) == "success" for name in REQUIRED_JOBS):
                raise RuntimeError(
                    f"A newer DEV commit {run['head_sha']} passed all checks. "
                    f"Rerun its deployment at {run['html_url']} instead."
                )
        if len(runs) < 100:
            return
    raise RuntimeError("Could not establish the latest passing DEV candidate; no deployment")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    check_candidate(args.commit, int(os.environ["GITHUB_RUN_NUMBER"]))
    print(f"No newer passing DEV release supersedes {args.commit}")


if __name__ == "__main__":
    main()
