"""LLM agent (qwen3:8b via local Ollama) for BioEnv with two memory policies.

    full     every round the prompt re-presents the full results table (tested
             non-hits + hits with scores), mirroring BDA's stateless rebuild.
    summary  BDA-style lossy policy: once n_tested > --threshold, the table is
             replaced by two LLM summaries (non-hits, hits) produced each round
             from the full table, plus the cumulative-hit history and the BDA
             line "You will not be shown the results until the end".
    retrieval  compact state plus lookup: the prompt shows only the hits table and
             counts; before proposing, the agent lists candidate IDs after
             'Check:' and the experiment log answers tested/score for each (one
             extra call per round). Stand-in for an external memory harness.

Repeat diagnosis (--diagnose 1, default): after each round, every gene the agent
re-proposed is asked back under the SAME memory view it proposed with
("was this tested?"). yes -> knew_but_repeated (an action failure: the fact
was available and recalled but not used); no -> forgot (a memory failure).

Each round: one proposal call ("Lookup:" up to 4 IDs whose neighbour lists are
shown next round, and "Solution:" the batch). If the batch is short after env
rejection, one BDA-style retry listing the rejected IDs. After each round, one
recall-probe call (same memory view the agent will see next round) asks about
genes tested d = 1, 2, 4, 8 rounds earlier plus one never-tested decoy.

Every LLM call is appended to <out>/calls.jsonl (prompt, response, timing,
token counts). Environment log -> <out>/run.json.

Usage:
    bio/.venv/bin/python -I bio/llm_agent.py --policy full --rounds 12 --batch 32 \
        --screen IFNG --anonymize --out bio/runs/llm_full
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env import DATA_DIR, BioEnv  # noqa: E402

OLLAMA = "http://localhost:11434/api/chat"
MODEL = "qwen3:8b"
PROBE_DELAYS = (1, 2, 4, 8)
CLAUDE_BIN = "claude"
NUM_PREDICT = 1024  # output-token cap; longest normal response seen is ~170 tokens


class LLM:
    def __init__(self, log_path: Path, temperature: float = 0.7, seed: int = 0, backend: str = "ollama",
                 model: str = MODEL):
        self.log_path, self.temperature, self.seed = log_path, temperature, seed
        self.backend, self.model = backend, model
        self.n = 0

    def _ollama(self, prompt: str, kind: str, round_: int) -> dict:
        # Native endpoint so thinking can be disabled; num_ctx left at the server
        # default so we do not force a model reload on the shared server.
        body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "stream": False,
                "think": False, "options": {"temperature": self.temperature, "seed": self.seed + self.n,
                                             "num_predict": NUM_PREDICT}}
        req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
        # Week 3: 4/9 overnight runs died on a 900 s timeout (runaway generation, no output cap).
        # Cap output tokens and retry once with a new seed; a second failure returns "" (logged).
        r = None
        for attempt in range(2):
            try:
                r = json.load(urllib.request.urlopen(req, timeout=600))
                break
            except (TimeoutError, OSError) as e:
                print(f"  [{kind} r{round_}] call failed ({e!r}), attempt {attempt + 1}", flush=True)
                body["options"]["seed"] += 7919
                req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
        if r is None:
            r = {"message": {"content": ""}, "failed": True}
        return r

    def _claude(self, prompt: str, kind: str, round_: int) -> dict:
        """Plain-model call through `claude -p`: no tools, no user settings/MCP/skills, fresh session.

        Runs from an empty temp dir so the model cannot see project files (the ground truth lives
        there). The minimal flags cut per-call overhead from ~198K to ~620 tokens (measured 2026-11-06).
        Uses the logged-in plan's usage; total_cost_usd is a reported figure, logged for planning."""
        cmd = [CLAUDE_BIN, "-p", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
               "--system-prompt", "You are a helpful assistant.", "--disable-slash-commands",
               "--no-session-persistence", "--output-format", "json", "--model", self.model]
        for attempt in range(4):
            if attempt:
                time.sleep(30 * attempt)  # e.g. Claude Code auto-update swaps the binary mid-run
            try:
                with tempfile.TemporaryDirectory() as empty:
                    out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, cwd=empty)
                d = json.loads(out.stdout)
                if d.get("is_error"):
                    raise RuntimeError(str(d.get("result"))[:200])
                u = d["usage"]
                return {"message": {"content": d["result"]},
                        "prompt_eval_count": u["input_tokens"] + u["cache_creation_input_tokens"]
                        + u["cache_read_input_tokens"],
                        "eval_count": u["output_tokens"], "cost_usd": d.get("total_cost_usd"),
                        "models": list(d.get("modelUsage", {}))}
            except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, RuntimeError, OSError) as e:
                print(f"  [{kind} r{round_}] claude call failed ({e!r}), attempt {attempt + 1}", flush=True)
        return {"message": {"content": ""}, "failed": True}

    def __call__(self, prompt: str, kind: str, round_: int) -> str:
        t0 = time.time()
        call = self._claude if self.backend == "claude" else self._ollama
        r = call(prompt, kind, round_)
        dt = time.time() - t0
        text = r["message"]["content"]
        rec = {"i": self.n, "kind": kind, "round": round_, "wall_s": round(dt, 2),
               "prompt_tokens": r.get("prompt_eval_count"), "completion_tokens": r.get("eval_count"),
               "prompt": prompt, "response": text, "failed": bool(r.get("failed")),
               "backend": self.backend, "model": self.model, "cost_usd": r.get("cost_usd"), "models": r.get("models")}
        with open(self.log_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        self.n += 1
        print(f"  [{kind} r{round_}] {dt:.1f}s in={rec['prompt_tokens']} out={rec['completion_tokens']}", flush=True)
        return text


ID_RE = re.compile(r"\bG\d{5}\b")


def parse_ids(text: str, tag: str) -> list[str]:
    m = re.search(rf"{tag}\s*:(.*?)(?:\n\s*\w+\s*:|\Z)", text, re.S | re.I)
    return ID_RE.findall(m.group(1)) if m else []


def table(env: BioEnv, ids) -> str:
    return "\n".join(f"{g}  {env.log[env.tested[g]].revealed[g]:.4f}" for g in ids) or "(none)"


def memory_view(env: BioEnv, policy: str, threshold: int, llm: LLM, task: str, hits_hist: list[int]) -> str:
    if not env.log:
        return ""
    hits = [g for l in env.log for g in l.hits]
    non = [g for l in env.log for g in l.accepted if g not in set(hits)]
    if policy == "retrieval":
        return (f"\nThis is not your first round. {len(env.tested)} genes have been tested so far; the full results "
                f"are stored in an experiment log that you can query (see 'Check' below). You have identified "
                f"{len(hits)} hits so far. The results for the hits are:\n{table(env, hits)}\n")
    if policy == "full" or len(env.tested) <= threshold:
        return (f"\nThis is not your first round. All tested genes that are NOT hits and their measured score:\n"
                f"{table(env, non)}\n\nYou have successfully identified {len(hits)} hits so far over all "
                f"experiment cycles! The results for the hits are:\n{table(env, hits)}\n")
    neg = llm(f"{task}\nTill now, these are all tested genes that are not hits along with their scores:\n"
              f"{table(env, non)}\nSummarize this in a few lines to find some common pattern in these which will "
              f"aid in the next steps of experimental design to maximize your cumulative hits.", "sum_neg", env.round)
    pos = llm(f"{task}\nTill now, you have identified the following genes as hits along with their scores:\n"
              f"{table(env, hits)}\nSummarize this in a few lines to find some common pattern in these which will "
              f"aid in the next steps of experimental design to maximize your cumulative hits.", "sum_pos", env.round)
    return (f"\nThis is not your first round. The summary of all tested genes and their measured scores is:\n{neg}\n"
            f"The summary of these hits is the following: {pos}\n"
            f"Till now, the progression of the number of cumulative hits is: {', '.join(map(str, hits_hist))}\n"
            f"You have successfully identified {len(hits)} hits so far over all experiment cycles! You will not be "
            f"shown the results until the end of all the rounds, so design your strategy accordingly.\n")


def run(a) -> None:
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "calls.jsonl").exists() or (out / "run.json").exists():
        raise FileExistsError(f"Run output already exists: {out}; choose a new --out")
    llm = LLM(out / "calls.jsonl", seed=a.seed, backend=a.backend, model=a.model or MODEL)
    env = BioEnv(a.screen, rounds=a.rounds, batch=a.batch, anonymize=a.anonymize, seed=a.seed, features=a.features)
    tp = json.loads((DATA_DIR / "task_prompts" / f"{a.screen}.json").read_text())
    n = len(env.ids)
    id_desc = (f"Genes are identified by opaque IDs G00000..G{n - 1:05d} (gene names are hidden; you cannot use "
               f"prior biological knowledge of gene names)." if a.anonymize else "Use HGNC gene symbols.")
    task = (f"You are running a pooled CRISPR screen to {tp['Task']}. The measured score is {tp['Measurement']}. "
            f"There are {n} genes; about 5% are hits (largest |score|). Each round you choose {a.batch} genes to "
            f"perturb; you only learn scores of genes you test. Maximize the cumulative number of hits over "
            f"{a.rounds} rounds. Never re-test a gene. {id_desc}")
    sim_src = ("knockout-effect profile across ~1,000 cancer cell lines (DepMap)" if a.features == "depmap"
               else "profile across OTHER, related CRISPR screens")
    tool_desc = ("You have a lookup tool: list up to 4 IDs after 'Lookup:' and next round you will see the 8 most "
                 f"similar genes to each (similarity = {sim_src}; similar genes often behave alike).")
    rng = random.Random(a.seed)
    lookups: list[str] = []
    hits_hist: list[int] = []
    probes = []
    diagnoses = []
    check_log: list[dict] = []
    t_start = time.time()
    view = ""

    def checkpoint(complete=False):
        # Atomic replacement preserves the last valid snapshot if interrupted.
        res = {"args": vars(a), "wall_s": round(time.time() - t_start, 1), "n_calls": llm.n,
               "status": "complete" if complete else "partial", "totals": env.totals(),
               "curve": [l.hit_ratio for l in env.log], "rounds": [asdict(l) for l in env.log],
               "probes": probes, "diagnoses": diagnoses, "checks": check_log, "tested": env.tested}
        tmp = out / "run.json.tmp"
        tmp.write_text(json.dumps(res))
        tmp.replace(out / "run.json")
        return res

    checkpoint()
    while not env.done:
        r = env.round
        print(f"round {r + 1}/{a.rounds} tested={len(env.tested)}", flush=True)
        look_txt = ""
        if lookups:
            look_txt = "\nLookup results (requested last round):\n" + "\n".join(
                f"{g}: " + ", ".join(h for h, _ in env.lookup(g)) for g in lookups) + "\n"
        menu_txt = ""
        if a.menu:  # BDA's gene_choices_prompt: offer a list of remaining genes to pick from
            pool = [g for g in env.ids if g not in env.tested]
            menu_txt = (f"\nA random sample of {a.menu} untested IDs you may choose from (you may also choose "
                        f"lookup results or other untested IDs):\n" + ", ".join(rng.sample(pool, a.menu)) + "\n")
        check_txt = ""
        if a.policy == "retrieval" and env.log:
            cq = (f"Step {r}\n{task}\n{view}{look_txt}{menu_txt}\nBefore proposing, you may query the experiment log. "
                  f"List up to {2 * a.batch} candidate IDs you are considering. Reply exactly:\nCheck: <IDs>")
            cids = [g for g in dict.fromkeys(ID_RE.findall(llm(cq, "check", r))) if g in env.index][:2 * a.batch]
            check_txt = "\nExperiment-log results for the IDs you checked:\n" + "\n".join(
                f"{g}: tested=yes score={env.log[env.tested[g]].revealed[g]:.4f}" if g in env.tested
                else f"{g}: tested=no" for g in cids) + "\n"
            check_log.append({"round": r, "checked": cids, "already_tested": [g for g in cids if g in env.tested]})
        prompt = (f"Step {r}\n{task}\n{tool_desc}\n{view}{look_txt}{menu_txt}{check_txt}\nPropose exactly {a.batch} new, untested gene "
                  f"IDs for round {r + 1}. Reply in this format and nothing else:\nLookup: <up to 4 IDs>\n"
                  f"Solution: <{a.batch} comma-separated IDs>")
        resp = llm(prompt, "propose", r)
        lookups = [g for g in parse_ids(resp, "Lookup") if g in env.index][:4]
        cur = env.propose(parse_ids(resp, "Solution"))
        for _ in range(a.retries):  # BDA re-prompts up to 20x; we cap lower to save calls
            if env.remaining_in_batch() == 0:
                break
            rejected = cur.invalid + cur.repeats + cur.dup_in_batch
            retry = (prompt + f"\n\nYour previous answer:\n{resp}\n\nYou have so far predicted {len(cur.accepted)} "
                     f"out of the required {a.batch} genes for this round. These were:\n{cur.accepted}\nPlease add "
                     f"{env.remaining_in_batch()} more genes. Remember not to include previously tested or invalid "
                     f"genes including:\n{rejected}\nSolution:")
            resp2 = llm(retry, "retry", r)
            ids2 = parse_ids(resp2, "Solution") or ID_RE.findall(resp2)
            env.propose(ids2)
        log = env.end_round()
        hits_hist.append(log.cum_hits)
        checkpoint()
        reps = list(dict.fromkeys(log.repeats))
        if a.diagnose and reps:
            # Ask back under the exact context the agent proposed with (view + lookup/menu/check text).
            sample = reps if len(reps) <= a.diagnose_max else rng.sample(reps, a.diagnose_max)
            ctx = f"{task}\n{view}{look_txt}{menu_txt}{check_txt}"
            dresp = llm(f"{ctx}\nMemory check (do not propose genes now). For each ID below, answer whether it was "
                        f"already tested in an earlier round. One line per ID, exactly:\n<ID>: tested=<yes|no>\n\n"
                        + "\n".join(sample), "diagnose", r)
            for g in sample:
                m = re.search(rf"{g}\s*:\s*tested\s*=\s*(yes|no)", dresp, re.I)
                said = m.group(1).lower() if m else None
                diagnoses.append({"round": r, "gene": g, "tested_round": env.tested[g],
                                  "age": r - env.tested[g], "said": said,
                                  "label": {"yes": "knew_but_repeated", "no": "forgot"}.get(said, "unparsed")})
        print(f"  accepted={len(log.accepted)} hits+={len(log.hits)} cum={log.cum_hits} ratio={log.hit_ratio:.4f} "
              f"invalid={len(log.invalid)} repeats={len(log.repeats)} dup={len(log.dup_in_batch)}", flush=True)
        checkpoint()
        if env.done:
            break
        view = memory_view(env, a.policy, a.threshold, llm, task, hits_hist)
        # ---- recall probe, same memory view the agent sees next round ----
        if a.probes:
            qs = []
            for d in PROBE_DELAYS:
                src = env.round - d  # round index (0-based) tested d rounds ago
                if src >= 0 and env.log[src].accepted:
                    qs.append((rng.choice(env.log[src].accepted), src, d))
            untested = [g for g in env.ids if g not in env.tested]
            qs.append((rng.choice(untested), None, None))
            rng.shuffle(qs)
            qtxt = "\n".join(f"{g}" for g, _, _ in qs)
            presp = llm(f"{task}\n{view}\nMemory check (do not propose genes now). For each ID below, answer whether "
                        f"it was already tested and, if so, its measured score. One line per ID, exactly:\n"
                        f"<ID>: tested=<yes|no> score=<number or NA>\n\n{qtxt}", "probe", env.round)
            for g, src, d in qs:
                m = re.search(rf"{g}\s*:\s*tested\s*=\s*(yes|no)[^\n]*?score\s*=\s*(-?\d*\.?\d+(?:e-?\d+)?|NA)",
                              presp, re.I)
                said_tested = bool(m) and m.group(1).lower() == "yes"
                score = float(m.group(2)) if m and m.group(2).upper() != "NA" else None
                truth = env.log[src].revealed[g] if src is not None else None
                probes.append({"step": env.round, "gene": g, "obs_round": src, "delay": d, "parsed": bool(m),
                               "said_tested": said_tested, "said_score": score, "truth_score": truth})
        checkpoint()
    res = checkpoint(complete=True)
    print(json.dumps({k: res[k] for k in ("wall_s", "n_calls", "totals")}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", choices=["full", "summary", "retrieval"], required=True)
    ap.add_argument("--screen", default="IFNG")
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--threshold", type=int, default=96, help="summary policy: n_tested above which table -> summary")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--probes", type=int, default=1)
    ap.add_argument("--menu", type=int, default=0, help="show N random untested IDs each round (BDA gene_choices)")
    ap.add_argument("--diagnose", type=int, default=1, help="ask back each re-proposed gene (forgot vs knew)")
    ap.add_argument("--diagnose-max", type=int, default=12, help="cap on genes diagnosed per round")
    ap.add_argument("--backend", choices=["ollama", "claude"], default="ollama")
    ap.add_argument("--model", default=None, help="model id; default qwen3:8b for ollama (required for claude)")
    ap.add_argument("--anonymize", action="store_true")
    ap.add_argument("--features", choices=["screens", "depmap"], default="screens")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.backend == "claude" and not args.model:
        ap.error("--backend claude needs an explicit --model, so every run records its model")
    run(args)
