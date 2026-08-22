import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.abspath(os.path.join(BASE, ".."))

VERDICT_RE = re.compile(r"\*\*Verdict:\s*([A-Z-]+)\*\*")
CLASSES_RE = re.compile(r"\*\*Ambiguity classes:\*\*\s*(.+)")
SUMMARY_RE = re.compile(r"## Task summary\s*\n\n(.+?)(?:\n\n##|\Z)", re.S)


def load_json(*parts):
    path = os.path.join(AUDIT, *parts)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_tasks():
    sample = load_json("sample_20_final.json")
    metric1 = load_json("results", "metric1.json")
    determinate_ids = set(metric1["determinate_ids"])

    tasks = []
    for t in sample["tasks"]:
        tid = t["id"]

        screen_path = os.path.join(AUDIT, "results", "screen", f"{tid}.json")
        screen = None
        if os.path.exists(screen_path):
            with open(screen_path, encoding="utf-8") as f:
                screen = json.load(f)

        final_verdict = "DETERMINATE" if tid in determinate_ids else "INDETERMINATE"
        final_classes = []
        summary_excerpt = None

        adj_path = os.path.join(AUDIT, "results", "adjudication", f"{tid}.md")
        if os.path.exists(adj_path):
            with open(adj_path, encoding="utf-8") as f:
                adj_text = f.read()
            m = VERDICT_RE.search(adj_text)
            if m:
                final_verdict = m.group(1)
            m = CLASSES_RE.search(adj_text)
            if m:
                final_classes = [c.strip(" `") for c in m.group(1).split(",")]
            m = SUMMARY_RE.search(adj_text)
            if m:
                summary_excerpt = " ".join(m.group(1).split())
        else:
            final_verdict = "REFERENCE-PRODUCTION-FAILED"

        tasks.append({
            "id": tid,
            "difficulty": t["difficulty"],
            "source": t["source"],
            "ticker": t["ticker"],
            "yf_symbol": t["yf_symbol"],
            "timeframe": t["timeframe"],
            "prompt": t["reformulated_task"],
            "screen": {
                "rubric": screen["rubric"] if screen else None,
                "predicted_class": screen["predicted_class"] if screen else None,
                "predicted_ambiguity_classes": screen["predicted_ambiguity_classes"] if screen else [],
            },
            "final": {
                "verdict": final_verdict,
                "ambiguity_classes": final_classes,
                "summary": summary_excerpt,
            },
        })
    return tasks


def main():
    tasks = build_tasks()
    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f:
        template = f.read()

    json_text = json.dumps(tasks, ensure_ascii=False).replace("</script", "<\\/script")
    output = template.replace("__TASKS_JSON__", json_text)

    out_path = os.path.join(BASE, "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)

    print(f"wrote {out_path} with {len(tasks)} tasks")


if __name__ == "__main__":
    main()
