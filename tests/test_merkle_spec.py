import pytest

from merklelake.proofs import merkle as M


@pytest.mark.skip(
    reason="Implement M.h, M.build_levels, M.root_of, M.proof_for, M.verify_inclusion"
)
def test_single_leaf_root_equals_leaf_hash_spec():
    """
    SPEC:
    - Given one leaf payload b"alpha", build_levels returns levels with:
        levels[0] length == 1
        root_of(levels) == SHA256(b"alpha")
    - proof_for(levels, 0) verifies with verify_inclusion.
    """
    ...


@pytest.mark.skip(reason="Implement build/proof/verify with padding rule")
def test_three_leaves_padding_and_sides_spec():
    """
    SPEC:
    - For leaves [b"a", b"b", b"c"]:
          * padding duplicates last node at level 0
          * proof_for(levels, 1) returns 2 steps with correct left/right
          * verify_inclusion(b"b", proof, root) is True
    """
    ...


@pytest.mark.skip(reason="Implement input validation and performance sanity")
def test_large_tree_smoke_spec():
    """
    SPEC:
    - For 10_000 leaves [b"0", b"1", ...], build_levels returns valid levels,
        root exists, and proof length ≈ ceil(log2(n)) for a middle index.
    """
    ...
