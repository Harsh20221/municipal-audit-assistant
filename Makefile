PY ?= python

.PHONY: setup generate-data test evaluate

setup:
	$(PY) -m pip install -e ".[dev]"

generate-data:
	$(PY) -m evaluation.generate_data

test:
	$(PY) -m pytest

evaluate:
	$(PY) -m evaluation.score
