# multiple_llm_eval

Pipeline đánh giá và so sánh nhiều LLM cùng lúc: chạy ma trận **N model × M benchmark**, chấm điểm bằng LLM-as-a-judge, xuất bảng số liệu + biểu đồ so sánh + báo cáo HTML.

> Ví dụ kết quả thực tế: xem [REPORT.md](REPORT.md) — 5 model nhỏ (0.5B–1.7B) chạy trên 5 benchmark, GPU A10.

## Pipeline hoạt động thế nào

```mermaid
flowchart LR
    A[benchmark_config.yaml<br/>+ benchmarks/*.jsonl] --> B[Runner]
    B -->|"câu hỏi"| C[Model cần test<br/>(Ollama / vLLM / API cloud / model tự code)]
    C -->|"câu trả lời"| D[Judge LLM<br/>(chấm 1-10 theo tiêu chí, ép JSON schema)]
    D --> E[results/raw/*.json<br/>(cache resume)]
    E --> F[metrics.json + summary.csv]
    F --> G[4 chart PNG + comparison_report.html]
```

Với mỗi cặp model × benchmark, runner gửi từng câu hỏi đến model, lấy câu trả lời, rồi nhờ **judge LLM** chấm theo các tiêu chí riêng của benchmark đó (mỗi tiêu chí: điểm nguyên 1–10 + một câu giải thích). Output của judge bị **ép đúng JSON schema** nên không bao giờ nhận điểm rác; nếu vẫn parse hỏng thì có fallback trích JSON từ văn bản, tệ nhất là ghi điểm 0 và bị loại khỏi trung bình (không kéo tụt điểm).

**Điểm tổng hợp:** điểm một ô model×benchmark = trung bình mọi điểm tiêu chí của các câu; điểm chung cuộc của model = trung bình các benchmark (trọng số bằng nhau).

## Cài đặt

```bash
git clone https://github.com/HiepDema/multiple_llm_eval.git
cd multiple_llm_eval
pip install requests pyyaml jinja2 matplotlib numpy
# hoặc dùng Poetry: poetry install
```

## Chạy thử ngay (không cần server nào)

```bash
PYTHONPATH=src python3 -m eval_llm.benchmark benchmark_config.yaml --mock
# Windows PowerShell:
#   $env:PYTHONPATH="src"; python -m eval_llm.benchmark benchmark_config.yaml --mock
```

`--mock` sinh câu trả lời + điểm giả (deterministic) để kiểm tra toàn bộ pipeline và xem trước report/chart mà không cần LLM nào. Mở `results/comparison_report.html` để xem.

## Chạy thật

### Cách 1 — Ollama trên máy có GPU (khuyên dùng, ví dụ Lambda A10)

```bash
bash setup_a10.sh        # cài Ollama + pull 5 model test + judge (~12GB)
PYTHONPATH=src python3 -m eval_llm.benchmark benchmark_config.yaml --fresh
```

Chạy từ laptop mà GPU ở máy khác? Mở SSH tunnel rồi chạy như bình thường (config để nguyên `localhost:11434`):

```bash
ssh -L 11434:localhost:11434 ubuntu@<ip-máy-gpu>
```

### Cách 2 — API cloud (Groq, OpenRouter, Together... — mọi endpoint OpenAI-compatible)

```yaml
models:
  - name: "Llama-3.1-8B"
    base_url: "https://api.groq.com/openai"
    api: openai-chat
    model: "llama-3.1-8b-instant"
    api_key_env: GROQ_API_KEY      # đọc key từ biến môi trường
```

## File cấu hình (`benchmark_config.yaml`)

```yaml
evaluator:                          # judge — nên mạnh hơn hẳn các model được test
  base_url: "http://localhost:11434"
  api: openai-chat
  model: "qwen2.5:14b"

models:                             # bao nhiêu model cũng được (chart hỗ trợ tối đa 8)
  - name: "Qwen2.5-1.5B"            # tên hiển thị trên chart/bảng
    base_url: "http://localhost:11434"
    api: openai-chat                # openai-chat | simple
    model: "qwen2.5:1.5b"           # tên model phía server (bỏ qua nếu api: simple)
    # api_key: "..."                # hoặc api_key_env: TÊN_BIẾN_MÔI_TRƯỜNG

benchmarks:
  - name: "Math"
    file: "benchmarks/math.jsonl"
    criteria: ["Accuracy", "Reasoning", "Clarity"]   # tiêu chí chấm riêng từng benchmark

global_criteria: ["Correctness", "Clarity"]   # dùng khi benchmark không khai criteria
output_dir: "results"
```

Hai kiểu API được hỗ trợ cho cả model lẫn judge:

| `api` | Request | Response | Dùng cho |
|---|---|---|---|
| `openai-chat` | `POST {base_url}/v1/chat/completions` | `choices[0].message.content` | Ollama, vLLM, llama.cpp server, LM Studio, mọi API cloud OpenAI-compatible |
| `simple` | `POST {base_url}` body `{"prompt": ...}` | `{"output": ...}` | Model tự code, server tự bọc |

## Đưa model vào bằng cách nào

**Model public có weights** (Hugging Face, GGUF): serve bằng Ollama (`ollama pull`), vLLM (`vllm serve <repo-hf>`), llama.cpp server hoặc LM Studio → khai `api: openai-chat`.

**Model public qua cloud**: chỉ cần `base_url` + `api_key_env` (xem Cách 2 ở trên).

**Model bạn tự train:**
- Fine-tune chuẩn HF transformers / LoRA → serve bằng vLLM, hoặc convert sang GGUF (`convert_hf_to_gguf.py` của llama.cpp) rồi `ollama create` với Modelfile.
- Model kiến trúc tự chế (PyTorch thuần) → bọc một HTTP server ~15 dòng theo format `simple`:

```python
# my_model_server.py  ->  uvicorn my_model_server:app --port 8010
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
model = load_my_model()            # code của bạn

class Req(BaseModel):
    prompt: str

@app.post("/")
def generate(req: Req):
    return {"output": model.generate(req.prompt)}
```

```yaml
  - name: "My-Custom-Model"
    base_url: "http://localhost:8010"
    api: simple
```

## Đưa benchmark vào bằng cách nào

Mỗi benchmark là một file **JSONL** — mỗi dòng một câu hỏi mở:

```json
{"id": 1, "question": "Nội dung câu hỏi..."}
```

Tạo file trong `benchmarks/`, thêm entry vào config với `name` + `file` + `criteria` (tiêu chí đặt tên tùy ý — schema chấm điểm, bảng CSV, chart đều sinh tự động theo). Repo có sẵn 7 bộ mẫu (~6 câu/bộ): General Knowledge, Math, Reasoning, Vietnamese, Medical, Coding, Summarization.

Lưu ý khi **đổi ruột benchmark mà giữ nguyên tên**: cache trong `results/raw/` đặt theo tên, pipeline sẽ tưởng đã chạy rồi — hãy dùng `--fresh` hoặc xóa `results/` trước.

## Tuần tự hay song song?

- **Giữa các cặp model×benchmark: tuần tự** — chủ đích, để resume theo cặp đơn giản và tránh việc một GPU phải swap nhiều model cùng lúc (Ollama swap model liên tục còn chậm hơn tuần tự).
- **Trong một cặp: song song** — flag `--workers N` (mặc định **4**) chạy N câu hỏi đồng thời bằng thread pool. Kết hợp với batching phía server của Ollama (`OLLAMA_NUM_PARALLEL`, mặc định 4) và việc GPU đủ VRAM giữ judge + model test cùng lúc, thực tế nhanh hơn tuần tự ~2–3× trên một GPU. Thứ tự kết quả và xử lý lỗi từng câu được giữ nguyên; `--workers 1` để về tuần tự hoàn toàn.
- **Scale nhiều máy**: mỗi máy chạy config với vài model, xong gom hết `results/raw/` về một chỗ và chạy `--charts-only` để tổng hợp — không cần sửa code.

**Resume:** mỗi cặp xong là ghi ngay `results/raw/<model>__<benchmark>.json`; đứt mạng/tắt máy giữa chừng thì chạy lại, các cặp đã xong tự bỏ qua.

## Tham số dòng lệnh

| Flag | Ý nghĩa |
|---|---|
| `--mock` | Chạy giả lập, không cần server — để test pipeline/xem trước report |
| `--limit N` | Chỉ chạy N câu đầu mỗi benchmark (chạy nháp nhanh) |
| `--workers N` | Số câu hỏi đồng thời trong một cặp (mặc định 4; `1` = tuần tự) |
| `--fresh` | Bỏ qua cache, chạy lại toàn bộ các cặp |
| `--charts-only` | Không chạy inference; dựng lại metrics + chart từ `results/raw/` |

## Kết quả sau khi chạy

```
results/
├── raw/                          # 1 file JSON / cặp: câu hỏi, nguyên văn trả lời,
│                                 #   điểm + giải thích của judge (đồng thời là cache resume)
├── metrics.json                  # điểm trung bình từng ô + từng tiêu chí + điểm chung cuộc
├── summary.csv                   # bảng phẳng model,benchmark,criterion,avg_score (mở bằng Excel)
├── charts/
│   ├── overall_ranking.png       # xếp hạng chung cuộc
│   ├── overall_by_benchmark.png  # grouped bar so model theo từng benchmark
│   ├── heatmap_model_benchmark.png
│   └── criteria_by_benchmark.png # điểm từng tiêu chí (small multiples)
└── comparison_report.html        # báo cáo tự chứa: toàn bộ chart + bảng điểm trong 1 file
```

## Hạn chế nên biết

1. Điểm là **LLM-as-a-judge** — chủ quan theo judge, không so sánh được với leaderboard chuẩn (MMLU, GSM8K); judge có thể thoáng tay với câu trả lời trôi chảy nhưng sai ý, và có nguy cơ thiên vị model cùng họ.
2. Bộ mẫu chỉ ~6 câu/benchmark — đủ thấy khác biệt lớn, không đủ phân định các model sát điểm nhau; muốn kết luận chắc hơn hãy tăng lên 20–30 câu.
3. Chạy 1 lần, temperature 0 — ổn định nhưng không đo độ dao động giữa các lần sinh.

## Cấu trúc project

```
├── benchmark_config.yaml       # cấu hình ma trận (model, judge, benchmark)
├── benchmarks/*.jsonl          # bộ câu hỏi
├── setup_a10.sh                # cài Ollama + pull model trên máy GPU
├── src/eval_llm/
│   ├── benchmark.py            # runner: gọi model, chấm điểm, tổng hợp metrics
│   ├── charts.py               # vẽ 4 chart + render report HTML
│   └── __main__.py             # tool gốc: đánh giá 1 model đơn lẻ (eval-llm config.yaml)
├── REPORT.md                   # báo cáo phân tích lần chạy mẫu trên A10
└── results/                    # output (gitignore mặc định)
```

Repo phát triển từ [eval-llm](https://github.com/lee-b/eval_llm) của Lee Braiden (MIT). Tool gốc đánh giá một model (`poetry run eval-llm config.yaml -o report.html`) vẫn dùng được.

## License

MIT — xem [LICENSE.txt](LICENSE.txt).
