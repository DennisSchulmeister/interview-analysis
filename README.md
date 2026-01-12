Interview Analysis
==================

1. [Overview](#overview)
1. [Important Commands](#important-commands)
1. [Start a New Coding Project](#start-a-new-coding-project)
1. [Transcript Format](#transcript-format)
1. [Configuration (interviews.yaml)](#configuration-interviewsyaml)
1. [Run a Full Analysis](#run-a-full-analysis)
1. [Cleaning the Work Directory](#cleaning-the-work-directory)
1. [Output File Contents](#output-file-contents)
1. [Copyright](#copyright)

Overview
--------

This project is a small CLI tool to support **non-interpretive interview coding**.
It takes interview transcripts (ODT, TXT, MD files), splits them into overlapping text segments,
uses an LLM to assign **topics** and **orientations** to statements, and finally
creates an `.ods` spreadsheet report with an aggregated summary and a per-transcript
track record.

The workflow is configuration-driven via `interviews.yaml` and produces intermediate
work files in a configured work directory (e.g. `work/segments/` and `work/analysis/`).

Important Commands
------------------

### Short version

* `poetry install`: install dependencies
* `poetry run app --help`: show CLI help
* `poetry run app template`: create a template `interviews.yaml`
* `poetry run app segment`: generate segmentation work files
* `poetry run app analyze`: run the LLM coding and write analysis work files
* `poetry run app write-output`: generate the final `.ods` report
* `poetry run app clean`: delete intermediate work files (with safety prompts)

### Poetry basics

This project uses [Poetry](https://python-poetry.org/) for dependency and virtual
environment management. The main project metadata lives in `pyproject.toml`.
Common commands:

| Command | Meaning |
|--------|---------|
| `poetry install` | Install dependencies from `pyproject.toml` |
| `poetry add xyz` | Add a dependency |
| `poetry remove xyz` | Remove a dependency |
| `poetry show --tree` | Show dependency tree |
| `poetry shell` | Open a shell with the venv activated |
| `poetry run …` | Run a command inside the venv |

The CLI entrypoint is registered in `[tool.poetry.scripts]` as `app`, so you can run:

```sh
poetry run app --help
```

Environment variables
---------------------

The tool loads environment variables via `python-dotenv`.
Copy `.env.template` to `.env` and adjust values for your OpenAI-compatible endpoint.

Supported variables (see [interview_analysis/ai_llm.py](interview_analysis/ai_llm.py)):

* `LLM_OPENAI_API_KEY` (required): API key for the endpoint
* `LLM_OPENAI_MODEL` (required): model identifier (must support structured outputs)
* `LLM_OPENAI_BASE_URL` (optional, preferred): base URL for the API (for the OpenAI SDK)
	- example: `https://api.openai.com/v1`
* `LLM_OPENAI_HOST` (required if `LLM_OPENAI_BASE_URL` is not set): hostname
	- example: `api.openai.com`
* `LLM_OPENAI_PATH` (optional, legacy): path used to derive the base URL
	- historically this may point to a full endpoint like `/v1/chat/completions`

Example:

```dotenv
LLM_OPENAI_BASE_URL=https://api.openai.com/v1
LLM_OPENAI_MODEL=gpt-5
LLM_OPENAI_API_KEY=...
```

Start a New Coding Project
--------------------------

1. Create a new directory for your coding project.
2. Create a template configuration:

	 ```sh
	 poetry run app template
	 ```

	 This writes `./interviews.yaml`.
3. Create a transcript folder:

	 ```sh
	 mkdir -p transcripts
	 ```

4. Put your transcript files into `transcripts/` (`.odt`, `.txt`, or `.md`).
5. Edit `interviews.yaml`:
	 - set `include` to match your transcript files (e.g. `"transcripts/**/*"` or `"transcripts/**/*.{odt,txt,md}"`)
	 - adjust `topics` and their allowed `orientations`
	 - optionally tune `segmentation` and `analysis`

Transcript Format
-----------------

Transcripts can be **ODT**, **TXT**, or **Markdown** (`.md`) files.

ODT transcripts:

* Each statement is in its **own paragraph**.
* Each paragraph should start with a speaker label:

	```
	Name: What was said
	```

* Optional (recommended if you want to exclude interviewer statements): add exactly
	one metadata paragraph near the top of the document:

	```
	interviewer = Name1, Name2
	```

	The program uses this to identify interviewer labels and can exclude their
	statements from coding when configured.

TXT/Markdown transcripts:

* Statements are separated by **at least one empty line**.
* Each statement should start with a label like `Name: ...`.
* If a block does *not* start with a label, it is treated as a continuation of
  the previous statement.
* Optional metadata block (recommended if you want to exclude interviewer statements):

	```
	interviewer = Name1, Name2
	```

	Place it as its own block (surrounded by empty lines), near the top.

Configuration (interviews.yaml)
-------------------------------

Required top-level options:

* `include` (string or list of strings): glob pattern(s) for transcripts to include
* `workdir` (string): work directory for intermediate files (e.g. `./work`)
* `outfile` (string): path to the final `.ods` report (e.g. `results.ods`)
* `topics` (list): a list of topic definitions (the codebook)

Optional top-level options:

* `exclude` (string or list of strings): glob pattern(s) to exclude files (e.g. `"private/**"`)

Optional sections:

### segmentation

* `segmentation.segment_paragraphs` (int, default: 12)
	- number of paragraphs per segment
* `segmentation.overlap_paragraphs` (int, default: 3)
	- number of paragraphs repeated from the previous segment (context only)

### analysis

* `analysis.exclude_interviewer` (bool, default: false)
	- if `true`, statements attributed to the interviewer are excluded from coding
	- requires an interviewer metadata paragraph in the transcript
* `analysis.strategy` (string, default: `segment`)
	- `segment`: one LLM call per segment with the full codebook
	- `topic`: one LLM call per segment per topic (more robust, more costly)

### topics (codebook)

Each entry in `topics` can be written in one of these formats:

1) Simple mapping (topic -> orientations):

	```yaml
	topics:
	  - My Topic: [Positive, Negative]
	```

2) Topic without orientations:

	```yaml
	topics:
	  - "My Topic"
	```

3) Expanded topic object with optional descriptions:

	```yaml
	topics:
	  - topic: "My Topic"
	    allow_multiple_orientations: false
	    description: "When to apply this topic"
	    orientations:
	      # When allow_multiple_orientations is false, list orientations from
	      # highest rank to lowest rank. If multiple orientations are returned
	      # anyway, the highest-ranked one is kept.
	      - "Positive"
	      - label: "Negative"
	        description: "Only if the statement explicitly expresses criticism"
	```

Notes:

* Orientation entries may be plain strings, or mappings with `label` and optional `description`.
* `allow_multiple_orientations` is optional per topic (default: `false`). If `false`, at most one orientation is kept per topic per statement, using the configured orientation order as ranking (highest → lowest). Extra orientations returned by the model are dropped.
* Changing `topics` (including descriptions) forces a re-run of `analyze` because the analysis work files store a `codebook_hash` for incremental change detection.

Run a Full Analysis
-------------------

Typical command sequence:

```sh
poetry run app template
# edit interviews.yaml and place .odt transcripts in ./transcripts/

poetry run app segment
poetry run app analyze
poetry run app write-output
```

Cleaning the Work Directory
---------------------------

The work directory contains intermediate YAML work files.
If the input transcripts change too much (e.g. paragraph ordering changes), or if
the program runs into errors and you want to restart from a clean state, you can
remove all intermediate files with:

```sh
poetry run app clean
```

This command is safety-focused (prompts in an interactive terminal).

Output File Contents
--------------------

The output is an OpenDocument Spreadsheet (`.ods`) with:

* A `Summary` sheet: topic/orientation counts plus an example quote.
* One sheet per transcript: a chronological evidence track record with columns:
	- Topic
	- Orientation
	- Where Found (paragraph identifier; transcript is implied by the sheet)
	- Evidence Quote

Copyright
---------

**Interview Analysis**  \
**© 2026 Dennis Schulmeister-Zimolong** <[dennis@wpvs.de](mailto:dennis@wpvs.de)>  \
Licensed under the BSD 3-Clause License (see `LICENSE`).

