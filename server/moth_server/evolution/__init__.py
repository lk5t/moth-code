"""MOTH model evolution: continued training, experiments, evaluation and safe promotion.

One evolution **cycle** (``engine``)::

    approved training data (datasets) ─► training memory (memory) ─► experiment planning (planner)
      ─► compute scheduling (compute) ─► continued training (backends: local process or MOTH workers)
      ─► evaluation against the deployed model (evaluation) ─► candidate promotion ─► deployment
      ─► monitoring with automatic rollback ─► next cycle (scheduled)

Everything is persisted in the database (``evolution_*``, ``training_datasets``, ``model_lineage``,
``evaluation_reports``) so a cycle survives restarts and upgrades. Candidates are new model releases:
the active model is never overwritten, and the existing release gate (``moth_server.models``) and
deployment (integrity check, inference health check, atomic switch) are reused, not duplicated.
"""
