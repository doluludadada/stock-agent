import asyncio
import os
from collections.abc import Sequence
from itertools import batched
from pathlib import Path
from typing import TYPE_CHECKING, override

import numpy
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

from a_domain.ports.ai.text_embedder import ITextEmbedder
from a_domain.ports.system.logging_provider import ILoggingProvider
from a_domain.types.enums import EmbeddingPooling
from b_application.config.collect_config import EmbeddingConfig

if TYPE_CHECKING:
    from onnxruntime import InferenceSession

# ONNX Runtime uploads usage telemetry to Microsoft from the moment it is imported unless this is set first, and its
# upload thread aborts the process when the interpreter exits during an upload. The site reports nothing about itself
# to a third party. Set here, at the start, it also covers Chroma's own later import of the runtime.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")


class OnnxTextEmbedder(ITextEmbedder):
    """
    A sentence embedding model run with ONNX Runtime on the server's CPU: the runtime and the tokenizer Chroma itself
    installs, with a model that reads Chinese. Its two files come from the Hugging Face repository at the pinned
    revision into `folder`, once: a file already there is opened without a request, so only the first use of a server
    needs the network. The runtime is imported and the model opened at the first text, not at the start, so a site that
    embeds nothing pays nothing. One batch runs at a time, on `threads` CPU threads and without ONNX Runtime's memory
    arena, which would keep the largest batch's memory for the life of the process. Each vector has length 1.
    """

    def __init__(self, embedding: EmbeddingConfig, folder: Path, logger: ILoggingProvider) -> None:
        self._embedding = embedding
        self._folder = folder
        self._logger = logger
        self._model: tuple[Tokenizer, InferenceSession] | None = None
        self._embedding_one_batch = asyncio.Lock()

    @override
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []

        async with self._embedding_one_batch:
            for batch in batched(texts, self._embedding.batch_size, strict=False):
                if self._model is None:
                    self._model = await asyncio.to_thread(opened_model, self._embedding, self._folder, self._logger)

                vectors.extend(await asyncio.to_thread(batch_vectors, batch, *self._model, self._embedding.pooling))

        return vectors


def batch_vectors(
    texts: Sequence[str], tokenizer: Tokenizer, session: InferenceSession, pooling: EmbeddingPooling
) -> list[list[float]]:
    """The vectors of one batch, computed on the calling thread."""
    encoded = tokenizer.encode_batch(list(texts))
    mask = numpy.array([item.attention_mask for item in encoded], dtype=numpy.int64)
    given = {
        "input_ids": numpy.array([item.ids for item in encoded], dtype=numpy.int64),
        "attention_mask": mask,
        "token_type_ids": numpy.zeros_like(mask),
    }
    inputs = {item.name: given[item.name] for item in session.get_inputs()}
    tokens = numpy.asarray(session.run(None, inputs)[0], dtype=numpy.float32)

    match pooling:
        case EmbeddingPooling.CLS:
            pooled = tokens[:, 0]
        case EmbeddingPooling.MEAN:
            pooled = (tokens * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)

    return (pooled / numpy.linalg.norm(pooled, axis=1, keepdims=True)).tolist()


def opened_model(embedding: EmbeddingConfig, folder: Path, logger: ILoggingProvider) -> tuple[Tokenizer, InferenceSession]:
    """The model's tokenizer and session, its files fetched into the server's folder first when they are not there yet."""
    import onnxruntime

    logger.info(f"Opening the text embedding model {embedding.repository} at {embedding.revision[:12]}.")
    files = [
        hf_hub_download(embedding.repository, name, revision=embedding.revision, cache_dir=folder)
        for name in (embedding.tokenizer_file, embedding.model_file)
    ]
    tokenizer = Tokenizer.from_file(files[0])
    tokenizer.enable_truncation(embedding.max_tokens)
    tokenizer.enable_padding()
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = embedding.threads
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False
    return tokenizer, onnxruntime.InferenceSession(files[1], options, providers=["CPUExecutionProvider"])
