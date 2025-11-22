import math
import pytest

from merklelake import seal as S
from merklelake.proofs import merkle as M
from merklelake.proofs import chain as C

print("\nTesting seal_spec:")


def test_seal_determinism_and_mapping_spec():
    """
    SPEC:
    - Given events with ingest_ts 100,101,102:
          * seal_block returns (header, jsonl, levels)
          * Running twice yields identical jsonl and identical root
          * For each line i in jsonl, inclusion proof for that line verifies
    """
    print("  Test 1: seal_block determinism and leaf → line mapping...")

    events = [
        {"ingest_ts": 100, "msg": "alpha"},
        {"ingest_ts": 101, "msg": "beta"},
        {"ingest_ts": 102, "msg": "gamma"},
    ]

    # First seal
    header1, jsonl1, levels1 = S.seal_block(
        events=events,
        tenant_id="tenant-A",
        block_id="block-1",
    )

    # Second seal with identical inputs (determinism)
    header2, jsonl2, levels2 = S.seal_block(
        events=events,
        tenant_id="tenant-A",
        block_id="block-1",
    )

    # JSONL text must be identical
    assert jsonl1 == jsonl2

    # Roots must match
    root1 = M.root_of(levels1)
    root2 = M.root_of(levels2)
    assert root1 == root2

    # Basic sanity on returned headers
    assert header1.tenant_id == "tenant-A"
    assert header1.block_id == "block-1"
    assert header2.tenant_id == "tenant-A"
    assert header2.block_id == "block-1"

    # Each line i in JSONL must verify against the Merkle tree at leaf_idx i
    lines = jsonl1.split("\n")
    assert len(lines) == len(events)
    for i, line in enumerate(lines):
        leaf_bytes = line.encode("utf-8")
        proof = M.proof_for(levels1, i)
        assert M.verify_inclusion(leaf_bytes, proof, root1)

    print("  Test 1: PASSED")


def test_chain_prev_link_matches_spec():
    """
    SPEC:
    - Seal one block to get header1.link_hash_hex
    - Seal second block with prev_link_hash_hex = header1.link_hash_hex
    - header2.prev_link_hash_hex == header1.link_hash_hex
    - If header1 fields change, the recomputed link must no longer match header2.prev_link_hash_hex
    """
    print("  Test 2: chain prev_link wiring and link_hash sensitivity...")

    # First block
    events1 = [
        {"ingest_ts": 100, "msg": "first-block-event"},
    ]
    header1, jsonl1, levels1 = S.seal_block(
        events=events1,
        tenant_id="tenant-A",
        block_id="block-1",
    )

    # Second block, chained to the first
    events2 = [
        {"ingest_ts": 200, "msg": "second-block-event"},
    ]
    header2, jsonl2, levels2 = S.seal_block(
        events=events2,
        tenant_id="tenant-A",
        block_id="block-2",
        prev_link_hash_hex=header1.link_hash_hex,
    )

    # header2 must point back to header1
    assert header2.prev_link_hash_hex == header1.link_hash_hex

    # Recomputing header1's link hash should give the same value
    link1_recomputed = C.link_hash(header1)
    assert link1_recomputed == header1.link_hash_hex
    assert link1_recomputed == header2.prev_link_hash_hex

    # Now "change" header1 by constructing a logically different header
    # (e.g., different root_hash_hex) and recomputing its link.
    mutated_header1 = C.make_header(
        tenant_id=header1.tenant_id,
        block_id=header1.block_id,
        ts_start=header1.ts_start,
        ts_end=header1.ts_end,
        # Flip the root hash so the link must change.
        root_hash_hex="0" * len(header1.root_hash_hex),
        prev_link_hash_hex=header1.prev_link_hash_hex,
    )
    mutated_link = C.link_hash(mutated_header1)

    # The mutated link must no longer match what header2 stores as prev_link_hash_hex
    assert mutated_link != header2.prev_link_hash_hex

    print("  Test 2: PASSED")
