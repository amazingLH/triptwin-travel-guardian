"""Exercise the public Gradio golden path three times through HTTP."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from gradio_client import Client, handle_file


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_PATH = ROOT / "docs" / "evidence" / "stage5-ui" / "smoke-result.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    results = []
    for run_number in range(1, args.runs + 1):
        client = Client(args.url, verbose=False)
        image, load_status = client.predict(api_name="/load_example")
        client.predict(handle_file(image), api_name="/build_twin")
        risks = client.predict(True, api_name="/check_risks")
        plan_b, trace = client.predict(True, api_name="/generate_plan_b")
        passed = (
            "5 个风险" in risks
            and "已验证 Plan B" in plan_b
            and "7 条" in trace
            and "已载入" in load_status
        )
        results.append({"run": run_number, "passed": passed})
        print(f"RUN {run_number}: {'PASS' if passed else 'FAIL'}")
    evidence = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "url": args.url,
        "runs": results,
        "all_passed": all(result["passed"] for result in results),
        "cloud_model_reinvoked": False,
    }
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if evidence["all_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
