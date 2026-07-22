"""Benchmark matrix runner: N models x M benchmarks -> metrics + comparison charts.

Usage:
    eval-llm-benchmark benchmark_config.yaml
    eval-llm-benchmark benchmark_config.yaml --mock          # no servers needed
    eval-llm-benchmark benchmark_config.yaml --charts-only   # re-render from saved results
"""

import argparse
import csv
import hashlib
import json
import os
import re

import requests
import yaml


# ---------------------------------------------------------------------------
# Config / IO helpers
# ---------------------------------------------------------------------------

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_jsonl(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def slugify(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


# ---------------------------------------------------------------------------
# LLM calls (two API styles: 'simple' = this repo's format, 'openai-chat')
# ---------------------------------------------------------------------------

def _auth_headers(cfg):
    """API key from config: `api_key: "..."` or `api_key_env: ENV_VAR_NAME`."""
    key = cfg.get('api_key') or os.environ.get(cfg.get('api_key_env', ''), '')
    return {'Authorization': f'Bearer {key}'} if key else {}


def call_model(model_cfg, prompt, timeout=300):
    api = model_cfg.get('api', 'simple')
    base_url = model_cfg['base_url']

    if api == 'openai-chat':
        response = requests.post(
            base_url.rstrip('/') + '/v1/chat/completions',
            headers=_auth_headers(model_cfg),
            json={
                'model': model_cfg.get('model', ''),
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': model_cfg.get('temperature', 0),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']

    response = requests.post(base_url, headers=_auth_headers(model_cfg),
                             json={'prompt': prompt}, timeout=timeout)
    response.raise_for_status()
    return response.json()['output']


def build_evaluation_schema(criteria):
    properties = {}
    for criterion in criteria:
        properties[criterion] = {
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 10},
                "justification": {"type": "string"},
            },
            "required": ["score", "justification"],
        }
    return {"type": "object", "properties": properties, "required": list(criteria)}


def build_evaluation_prompt(question, model_output, criteria):
    return f"""
You are an expert evaluator. Assess the following answer based on the criteria provided: {', '.join(criteria)}.

Question:
{question}

Model's Answer:
{model_output}

For each criterion, provide:
- A score from 1 to 10 (integer).
- A brief justification (one or two sentences).

Output your response in JSON format that matches the provided schema.
"""


def parse_evaluation_json(output_text, criteria):
    try:
        return json.loads(output_text)
    except json.JSONDecodeError:
        pass
    # Fallback: pull the first {...} block out of surrounding prose
    match = re.search(r'\{.*\}', output_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    print(f"  ! Could not parse evaluation output: {output_text[:120]!r}")
    return {c: {'score': 0, 'justification': 'Invalid JSON output.'} for c in criteria}


def evaluate_output(evaluator_cfg, question, model_output, criteria, timeout=300):
    schema = build_evaluation_schema(criteria)
    prompt = build_evaluation_prompt(question, model_output, criteria)
    api = evaluator_cfg.get('api', 'simple')
    base_url = evaluator_cfg['base_url']

    if api == 'openai-chat':
        response = requests.post(
            base_url.rstrip('/') + '/v1/chat/completions',
            headers=_auth_headers(evaluator_cfg),
            json={
                'model': evaluator_cfg.get('model', ''),
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0,
                'response_format': {
                    'type': 'json_schema',
                    'json_schema': {'name': 'evaluation', 'strict': True, 'schema': schema},
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        output_text = response.json()['choices'][0]['message']['content']
    else:
        response = requests.post(
            base_url,
            headers=_auth_headers(evaluator_cfg),
            json={
                'prompt': prompt,
                'response_format': {'type': 'json_schema', 'schema': schema},
            },
            timeout=timeout,
        )
        response.raise_for_status()
        output_text = response.json()['output']

    evaluation = parse_evaluation_json(output_text, criteria)
    # Keep only expected criteria; fill anything the evaluator dropped
    cleaned = {}
    for criterion in criteria:
        details = evaluation.get(criterion)
        if isinstance(details, dict) and isinstance(details.get('score'), int):
            cleaned[criterion] = {
                'score': max(1, min(10, details['score'])),
                'justification': str(details.get('justification', '')),
            }
        else:
            cleaned[criterion] = {'score': 0, 'justification': 'Missing from evaluator output.'}
    return cleaned


# ---------------------------------------------------------------------------
# Mock mode (deterministic, no servers required)
# ---------------------------------------------------------------------------

def _stable_unit(*parts):
    """Deterministic pseudo-random float in [0, 1) from string parts."""
    digest = hashlib.md5('||'.join(parts).encode('utf-8')).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def mock_answer(model_name, question):
    return f"[mock answer from {model_name}] {question[:60]}..."


def mock_evaluation(model_name, benchmark_name, question, criteria, model_index, model_count):
    # Spread model quality across a band so comparison charts are meaningful
    if model_count > 1:
        base = 8.5 - 3.5 * (model_index / (model_count - 1))
    else:
        base = 7.0
    bench_shift = (_stable_unit(model_name, benchmark_name) - 0.5) * 2.5
    evaluation = {}
    for criterion in criteria:
        noise = (_stable_unit(model_name, benchmark_name, question, criterion) - 0.5) * 3.0
        score = int(round(max(1, min(10, base + bench_shift + noise))))
        evaluation[criterion] = {'score': score, 'justification': f'Mock score for {criterion}.'}
    return evaluation


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_pair(model_cfg, benchmark, evaluator_cfg, entries, mock, model_index, model_count):
    results = []
    criteria = benchmark['criteria']
    for entry in entries:
        question = entry['question']
        entry_id = entry.get('id', '')

        if mock:
            model_output = mock_answer(model_cfg['name'], question)
            evaluation = mock_evaluation(
                model_cfg['name'], benchmark['name'], question,
                criteria, model_index, model_count,
            )
        else:
            try:
                model_output = call_model(model_cfg, question)
            except Exception as e:
                print(f"  ! Error calling {model_cfg['name']}: {e}")
                model_output = "Error generating output."
            try:
                evaluation = evaluate_output(evaluator_cfg, question, model_output, criteria)
            except Exception as e:
                print(f"  ! Error during evaluation: {e}")
                evaluation = {c: {'score': 0, 'justification': 'Error during evaluation.'} for c in criteria}

        results.append({
            'id': entry_id,
            'question': question,
            'model_output': model_output,
            'evaluation': evaluation,
        })
    return results


def aggregate(raw, models, benchmarks):
    """raw[model][benchmark] -> list of entries. Returns the metrics structure."""
    metrics = {'models': [m['name'] for m in models],
               'benchmarks': [b['name'] for b in benchmarks],
               'criteria': {b['name']: b['criteria'] for b in benchmarks},
               'cells': {}}
    for model in models:
        for benchmark in benchmarks:
            entries = raw.get(model['name'], {}).get(benchmark['name'], [])
            crit_scores = {c: [] for c in benchmark['criteria']}
            for entry in entries:
                for criterion, details in entry['evaluation'].items():
                    if criterion in crit_scores and details['score'] > 0:
                        crit_scores[criterion].append(details['score'])
            per_criterion = {
                c: (sum(v) / len(v) if v else 0.0) for c, v in crit_scores.items()
            }
            all_scores = [s for v in crit_scores.values() for s in v]
            metrics['cells'][f"{model['name']}||{benchmark['name']}"] = {
                'overall': sum(all_scores) / len(all_scores) if all_scores else 0.0,
                'per_criterion': per_criterion,
                'n_questions': len(entries),
                'n_scored': len(all_scores),
            }
    # Per-model overall = mean of its benchmark overalls (equal benchmark weight)
    metrics['model_overall'] = {}
    for model in models:
        overalls = [metrics['cells'][f"{model['name']}||{b['name']}"]['overall'] for b in benchmarks]
        metrics['model_overall'][model['name']] = sum(overalls) / len(overalls) if overalls else 0.0
    return metrics


def write_summary_csv(metrics, path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['model', 'benchmark', 'criterion', 'avg_score'])
        for model in metrics['models']:
            for benchmark in metrics['benchmarks']:
                cell = metrics['cells'][f"{model}||{benchmark}"]
                writer.writerow([model, benchmark, 'OVERALL', f"{cell['overall']:.2f}"])
                for criterion, score in cell['per_criterion'].items():
                    writer.writerow([model, benchmark, criterion, f"{score:.2f}"])


def main():
    parser = argparse.ArgumentParser(description='Run a model x benchmark evaluation matrix')
    parser.add_argument('config', help='Path to benchmark YAML configuration file')
    parser.add_argument('--limit', type=int, default=None,
                        help='Max questions per benchmark (quick runs)')
    parser.add_argument('--mock', action='store_true',
                        help='Simulate model answers and scores (no servers needed)')
    parser.add_argument('--charts-only', action='store_true',
                        help='Skip running; rebuild metrics and charts from saved raw results')
    parser.add_argument('--fresh', action='store_true',
                        help='Ignore saved raw results and re-run every pair')
    args = parser.parse_args()

    config = load_config(args.config)
    config_dir = os.path.dirname(os.path.abspath(args.config))

    models = config['models']
    benchmarks = config['benchmarks']
    evaluator_cfg = config.get('evaluator', {})
    global_criteria = config.get('global_criteria', [])
    for benchmark in benchmarks:
        benchmark.setdefault('criteria', global_criteria)

    output_dir = os.path.join(config_dir, config.get('output_dir', 'results'))
    raw_dir = os.path.join(output_dir, 'raw')
    os.makedirs(raw_dir, exist_ok=True)

    total = len(models) * len(benchmarks)
    print(f"Matrix: {len(models)} models x {len(benchmarks)} benchmarks = {total} tests")

    raw = {}
    done = 0
    for model_index, model in enumerate(models):
        raw[model['name']] = {}
        for benchmark in benchmarks:
            done += 1
            pair_path = os.path.join(
                raw_dir, f"{slugify(model['name'])}__{slugify(benchmark['name'])}.json")

            if os.path.exists(pair_path) and not args.fresh:
                with open(pair_path, 'r', encoding='utf-8') as f:
                    raw[model['name']][benchmark['name']] = json.load(f)
                print(f"[{done}/{total}] {model['name']} x {benchmark['name']} (cached)")
                continue

            if args.charts_only:
                raw[model['name']][benchmark['name']] = []
                print(f"[{done}/{total}] {model['name']} x {benchmark['name']} (missing, skipped)")
                continue

            print(f"[{done}/{total}] {model['name']} x {benchmark['name']} ...")
            entries = load_jsonl(os.path.join(config_dir, benchmark['file']))
            if args.limit:
                entries = entries[:args.limit]
            results = run_pair(model, benchmark, evaluator_cfg, entries,
                               args.mock, model_index, len(models))
            raw[model['name']][benchmark['name']] = results
            with open(pair_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

    metrics = aggregate(raw, models, benchmarks)
    metrics_path = os.path.join(output_dir, 'metrics.json')
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    write_summary_csv(metrics, os.path.join(output_dir, 'summary.csv'))
    print(f"Metrics written to {metrics_path}")

    from eval_llm.charts import generate_charts, generate_html_report
    chart_paths = generate_charts(metrics, os.path.join(output_dir, 'charts'))
    report_path = generate_html_report(metrics, chart_paths,
                                       os.path.join(output_dir, 'comparison_report.html'))
    print(f"Charts written to {os.path.join(output_dir, 'charts')}")
    print(f"Report written to {report_path}")


if __name__ == '__main__':
    main()
