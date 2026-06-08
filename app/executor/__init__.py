"""Generic, domain-agnostic Arazzo workflow engine.

The engine reads the canonical Arazzo spec and drives it: sequential steps with
``onSuccess``/``onFailure`` + ``goto``/``end`` branching, runtime-expression evaluation,
and output extraction. It hard-codes no ANNCSU rules; those live in the spec.
Output coalescing and ``foreach`` (the ``x-executor`` blocks) are handled separately.
"""
