# Benchmark datasets

## fever_dev_sample.jsonl (150 claims)
- **Origin:** FEVER 1.0 shared-task dev set, downloaded from the official site:
  https://fever.ai/download/fever/shared_task_dev.jsonl (19,998 claims: 6,666 per label).
- **Paper:** Thorne, Vlachos, Christodoulopoulos & Mittal (2018), *FEVER: a large-scale dataset for Fact Extraction and VERification*, NAACL-HLT.
- **License:** CC BY-SA 3.0 (claims are derived from Wikipedia). Attribution retained here.
- **Sampling:** stratified random sample, 50 claims per label, `random.Random(42)`; rebuild with
  `python backend/evaluation/build_fever_sample.py --seed 42 --per-label 50`.
- **Fields:** `id` (FEVER id), `claim`, `label` (TRUE / FALSE / NEI), `fever_label` (SUPPORTS / REFUTES / NOT ENOUGH INFO),
  `wiki_pages` (gold evidence pages, empty for NEI), `source`.
- **Caveats:**
  - Claims were written against a **2017 Wikipedia dump**. Time-sensitive claims (office holders, records, "currently ...")
    may have changed since, so TruthLens can be right today and still be scored wrong.
  - FEVER's "NOT ENOUGH INFO" means *the 2017 Wikipedia dump* could not settle the claim; live Wikipedia today sometimes can.
  - Claims are often synthetic mutations ("X is not a Y") and skew toward entertainment/biography topics.

## ../benchmark_dataset.json (10 claims)
Hand-written smoke set from the original repo, relabelled to TRUE / FALSE / NEI with the reason in `note`.
Too small for an accuracy figure; use it as a sanity check.
