import math
import pytest

from merklelake.proofs import merkle as M

print("\nTesting merkle_spec:")


def test_single_leaf_root_equals_leaf_hash_spec():
    """
    SPEC:
    - Given one leaf payload b"alpha", build_levels returns levels with:
        levels[0] length == 1
        root_of(levels) == SHA256(b"alpha")
    - proof_for(levels, 0) verifies with verify_inclusion.
    """
    print("  Test 1: single leaf → root equals leaf hash and proof verifies...")

    leaf = b"alpha"
    levels = M.build_levels([leaf])

    # Level-0 checks
    assert len(levels) >= 1
    assert len(levels[0]) == 1

    # Root equals hash of the only leaf
    root = M.root_of(levels)
    assert root == M.h(leaf)

    # Inclusion proof verifies
    proof = M.proof_for(levels, 0)
    assert M.verify_inclusion(leaf, proof, root)

    print("  Test 1: PASSED")


def test_three_leaves_padding_and_sides_spec():
    """
    SPEC:
    - For leaves [b"a", b"b", b"c"]:
          * padding duplicates last node at level 0
          * proof_for(levels, 1) returns 2 steps with correct left/right
          * verify_inclusion(b"b", proof, root) is True
    """
    print("  Test 2: three leaves → padding rule and left/right sides...")

    leaves = [b"a", b"b", b"c"]
    levels = M.build_levels(leaves)

    # Level-0 hashes
    assert len(levels[0]) == 3
    h_a, h_b, h_c = levels[0]

    # Padding: last node duplicated when forming level 1
    assert len(levels[1]) == 2
    expected_padded_parent = M.h(h_c + h_c)
    assert levels[1][1] == expected_padded_parent

    root = M.root_of(levels)

    # Proof for middle leaf (index 1, value b"b")
    proof = M.proof_for(levels, 1)
    assert len(proof) == 2

    (sib0, side0), (sib1, side1) = proof

    # First step: sibling is "a" on the left
    assert side0 == "left"
    assert sib0 == h_a

    # Second step: sibling is the padded parent on the right
    assert side1 == "right"
    assert sib1 == levels[1][1]

    # Proof verifies
    assert M.verify_inclusion(b"b", proof, root)

    print("  Test 2: PASSED")


def test_large_tree_smoke_spec():
    """
    SPEC:
    - For 10_000 leaves [b"0", b"1", ...], build_levels returns valid levels,
        root exists, and proof length ≈ ceil(log2(n)) for a middle index.
    """
    print("  Test 3: large tree smoke test (10_000 leaves)...")

    n = 10_000
    leaves = [str(i).encode("ascii") for i in range(n)]

    levels = M.build_levels(leaves)

    # Root exists
    root = M.root_of(levels)
    assert isinstance(root, bytes)
    assert len(root) == 32  # SHA-256 digest size

    # Pick a middle index
    idx = n // 2
    proof = M.proof_for(levels, idx)

    assert M.verify_inclusion(leaves[idx], proof, root)

    expected_depth = math.ceil(math.log2(n))
    assert len(proof) == expected_depth

    print("  Test 3: PASSED")
