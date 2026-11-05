"""Opt-in community learning network (protocol ``moth-community/1``).

Participants contribute computing power, never their data: they train the
current community checkpoint on a *public* data shard supplied by the
coordinator and upload only the resulting weight delta. Local projects,
credentials and personal data are never read for, or included in, a
contribution.
"""
