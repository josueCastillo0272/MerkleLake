# Vision

## What this system is

- This system takes in logs, seals them cryptographically using Merkle trees with Certificate Transparency, then stores them
  in cloud storage and indexes them for search, providing proofs for any query.

## What problem is solved

- We want to make sure that logs cannot be modified without a client being able to detect it.

## What happens to a log entry

1. Client sends entry  
2. Logs get batched  
3. Logs are hashed  
4. Build Merkle tree and get root hash  
5. On search, return result and proof  
6. Client verifies using hashes
