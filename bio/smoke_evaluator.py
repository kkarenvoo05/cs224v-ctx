"""Real-data two-round API smoke; no model calls or claim of agent isolation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=False)
    episode = a.out / "evaluator"
    log = (a.out / "service.log").open("x")
    process = subprocess.Popen([
        sys.executable, "-I", str(Path(__file__).with_name("evaluator_service.py")),
        "--out", str(episode), "--rounds", "2", "--batch", "16"], stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 30
        while not (episode / "connection.json").exists():
            if process.poll() is not None:
                raise RuntimeError(f"Evaluator exited: see {a.out / 'service.log'}")
            if time.monotonic() > deadline:
                raise TimeoutError("Evaluator startup timed out")
            time.sleep(0.1)
        config = json.loads((episode / "connection.json").read_text())
        counter = 0

        def call(action, **args):
            nonlocal counter
            counter += 1
            req = Request(config["url"], method="POST", data=json.dumps({
                "request_id": str(counter), "action": action, "args": args}).encode(),
                headers={"Authorization": "Bearer " + config["token"]})
            try:
                with urlopen(req, timeout=10) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.load(exc)

        ids = call("catalog")[1]["ids"]
        assert call("history")[1]["observations"] == []
        for action in ("read_file", "scores", "id_to_symbol", "hits"):
            assert call(action)[0] == 400
        assert call("lookup", id=ids[0], k=8)[0] == 200
        assert call("propose", ids=ids[:16])[0] == 200
        assert call("end_round")[1]["completed_round"] == 1
        response = call("propose", ids=[ids[0], *ids[16:31]])[1]
        assert response["repeats"] == [ids[0]] and response["remaining"] == 1
        assert call("propose", ids=[ids[31]])[1]["remaining"] == 0
        assert call("end_round")[1]["done"] is True
        assert call("end_round")[0] == 400
        observations = call("history")[1]["observations"]
        assert len(observations) == 32
        state = json.loads((episode / "run.json").read_text())
        assert state["totals"]["hit_ratio"] == state["independent_hit_ratio"]
        assert state["totals"]["repeats"] == 1 and state["totals"]["short_batches"] == 0
        expected = [{"id": g, "round": r["round"] + 1, "score": r["revealed"][g],
                     "hit": g in r["hits"]} for r in state["rounds"] for g in r["accepted"]]
        assert observations == expected
        report = {"api_smoke": "passed", "rounds": 2, "tested": 32,
                  "hidden_actions_denied": True, "observations_match": True,
                  "scorers_agree": True, "model_calls": 0,
                  "prototype_adapter_tested": False, "agent_filesystem_isolation_tested": False}
        (a.out / "smoke.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
