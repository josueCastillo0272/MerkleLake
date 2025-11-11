import pytest

from merklelake import seal as S


@pytest.mark.skip(reason="Implement sealing pipeline (ordering, jsonl, levels, header)")
def test_seal_determinism_and_mapping_spec():
    """
    SPEC:
    - Given events with ingest_ts 100,101,102:
          * seal_block returns (header, jsonl, levels)
          * Running twice yields identical jsonl and identical root
          * For each line i in jsonl, inclusion proof for that line verifies
    """
    ...


@pytest.mark.skip(reason="Implement link-hash header assembly")
def test_chain_prev_link_matches_spec():
    """
    SPEC:
    - Seal one block to get header1.link_hash_hex
    - Seal second block with prev_link_hash_hex = header1.link_hash_hex
    - header2.prev_link_hash_hex == header1.link_hash_hex
    - If header1 fields change, the recomputed link must no longer match header2.prev_link_hash_hex
    """
    ...
