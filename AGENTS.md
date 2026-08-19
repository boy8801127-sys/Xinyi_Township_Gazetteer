# Repository Guidelines

## Project Structure & Module Organization

This is a Python pipeline for building the Xinyi Township Gazetteer corpus and its RAG demo. Source code lives in `src/`: PDF extraction and paragraph export, `src/data/` corpus and migration tools, `src/rag/` indexing/querying, `src/langchain_pipeline/` experiments, and `src/finetune/` optional QLoRA work. `paper/`, `books/`, `output/`, `results/`, and `vectorstore/` are local data or generated artifacts and are intentionally ignored. The Cloud Run Gradio copy is an independent deployment repository under `deploy/rag_space/`; it is not automatically synchronized with `src/`.

## Development Commands

Create a working Python environment before running commands:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.run_pipeline --max-pdfs 3
python -m src.data.build_labeled_corpus
python -m src.rag.query_engine --ask "問題"
```

`main.py` provides the interactive PDF workflow. Fine-tuning dependencies are separate: `pip install -r requirements-finetune.txt`. Confirm that `.venv\Scripts\python.exe` is usable before relying on any automation.

## Architecture and Data Rules

Keep the keyword PDF-classification workflow separate from the Notion semantic-classification workflow. Downstream RAG, LangChain, and fine-tuning modules consume the labeled corpus, not keyword-classification CSVs. Reuse the ID and source conventions in `src/data/source_codes.py`; IDs follow `{source-code}-{document}-{paragraph}`, for example `98-11-200`.

Prefer adding a new downstream module over altering an earlier experiment. Do not overwrite `results/`, `src/data/labeled_corpus.jsonl`, or `vectorstore/` without first creating and verifying a backup.

## Coding and Testing

Use Python 3, four-space indentation, UTF-8 source files, `snake_case` functions/modules, and `PascalCase` classes. This repository has no automated test suite. Validate changes with the narrowest relevant CLI command; for parsers, use a small PDF or `--max-pdfs 3`, and report what was run.

## Commits, Review, and Safety

Use concise Traditional Chinese imperative commit subjects, matching history (for example, `新增期刊論文擷取流程`). Keep commits scoped. Before committing, inspect `git status` and avoid adding `.env`, source documents, generated output, or local settings.

Ask for explicit confirmation before paid API calls, Notion writes, deletions, force pushes, pushes to `master`, corpus/index rebuilds, or deployment. Before Cloud Run deployment, review the change, verify the deployment copy, use an explicit memory setting (currently `--memory=2Gi`), and update any affected static data snapshots. Treat model pricing and `*-latest` model behavior as time-sensitive.
