# Vendored model assets

## `minilm-tokenizer.json`

The `tokenizer.json` of [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) (Apache 2.0), at revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, downloaded 2026-10-26.

`services/rag/chunking.py` loads it with the `tokenizers` library to count chunk sizes for every ingestion profile (docs/design-rag.md §7.2). It's vendored so the backend never downloads it at runtime and unit tests run offline. `settings.CHUNK_TOKENIZER` names the model it came from.

To update it, download `tokenizer.json` from a newer revision of the same model, replace this file, and record the new revision here. Changing it changes chunk boundaries, so re-sync every profile afterwards.
