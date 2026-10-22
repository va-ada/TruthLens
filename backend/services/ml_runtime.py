import threading

# One lock for every local torch model (embedder, reranker, NLI). Loading or running these from
# several threads at once (parallel retrieval + background news sync) segfaults torch, so model
# work is serialised while network I/O around it stays parallel.
MODEL_LOCK = threading.RLock()
