# Independent review of the synthetic TURN measurement candidate

This review is local and read-only with respect to the infrastructure. No online measurement, guest input, approval, or deployment was performed by the reviewer.

## Candidate and verification

- Initial measurement release SHA-256: `99d2c0fe014ec0ec34c49803436ae41c372dee704ede1857f657b55d0c0784d5`.
- All initial sealed sources matched their manifest. The referenced runtime release also matched `53555a0c830300a07acf58f2e8d7ae0cfe553b5c73e7bbdfc493882c0a148b1a` at review time.
- Independently ran the two synthetic loopback H264/SCTP tests: both passed. These exercise fixed-action acceptance, unexpected input rejection, and source release on disconnect; they do not exercise the public TURN route or real guest workloads.
- The initial candidate is **not accepted for execution**. Its author is preparing a revised candidate; no revised release has yet been independently verified.

## Findings requiring closure

1. A successful protocol input acknowledgement did not require the synthetic page's tap/scroll counters to advance. A missed target could therefore still produce a completed result. The Linux tap's fixed 87% horizontal position also appears to miss the right-aligned Action button in the existing fixture layout.
2. Reported FPS used the interval between received frames rather than the full requested measurement window. Video gaps omitted the window boundaries; warm-up acknowledgements and measured acknowledgements were combined. Raw arrival times were discarded despite the plan describing their retention.
3. The measurement runner, workload launcher, and peer did not enforce the reservation's absolute expiry. A per-peer duration bound is not a substitute for that reservation deadline.
4. Separate scenario/iteration journals did not provide mutual exclusion across runners operating the same four fixtures.
5. Killing the `runuser` wrapper on timeout did not prove that its media subprocess tree had stopped. Success/failure cleanup also needs to distinguish peer release, synthetic workload shutdown, and host sampler termination.
6. The measurement release contained a runtime release hash, but the runner did not explicitly verify that binding. Error reports also accepted arbitrary `ValueError` text rather than a fixed safe code.
7. The host sampler included the fixed control VM in addition to the four fixture VMs. The plan must disclose that read-only background-load observation. Process identity/start ticks must remain stable before attributing samples to a VM, and sampler subprocesses need bounded exit handling.

The author acknowledged these findings and is adding narrowly scoped fixes and regression tests. The approved cache/runtime artifacts remain separate and must not be silently changed by this measurement revision.

## Evidence boundary

The candidate uses four identity-free operator fixtures and fixed synthetic gestures. It does not create an account, device Owner, user pairing, or product takeover. TURN credentials and SDP were inspected in source flow only: they are passed in memory through pinned SSH pipes, not intentionally retained in reports. No secret file contents were read for this review.

Even a successful revised run would measure synthetic rendering and the media path. It would not certify simultaneous production users: simultaneous Core/model tasks, representative third-party apps, owner-backed authorization, and the real iPhone client remain outside this benchmark. The frozen report must preserve that limitation and failed/unknown outcomes.

## Final revised candidate review

Final release SHA-256: `909a521a1562dc2c4f2cf048c574cbac21da49a5a156c0f4c57e497d0ab30910`. All six sealed source hashes match. Independent local test rerun: **20 passed in 15.82 seconds**.

The initial blockers were corrected: actual fixture UI counters gate acknowledged input, FPS and gaps use the full fixed measurement window, raw numeric timings remain available, all scenarios share an exclusive lock, absolute expiry gates native operations, peer and process-group cleanup is bounded and checked, and the actual nominated ICE pair must include the fixed TURN relay. Host/relay and relay/peer-reflexive paths are accurately labelled; SDP filtering is not represented as proof that both selected candidates are relay candidates. No remaining execution blocker was reproduced within this bounded review.

This is a limited code and local-test conclusion, **not authorization to execute**. No online TURN experiment, production capacity acceptance, real user identity, real mobile app, third-party application workload, or Core model workload was exercised by this reviewer. The fixture data-channel/H264 tests demonstrate local mechanics only. Root controls the separate execution gate and any conclusion about measured concurrent users.

### Final topology/background amendment

Superseding sealed release: `0ff7fbdb02b0163ec71f422a6f222855d384939a28d3c7e5212946063f75208a`; all source hashes verified. Narrow changes reviewed: each declared single scenario contains one Linux and one Android according to the immutable manifest (1911/1912 and 1921/1922); optional background Core 1401 is sampled only after its exact private root reservation SHA and VM description match. The running VM/PID/start-tick set must remain stable. Independent rerun: **22 passed in 16.02 seconds**. No new blocker in these changes. All preceding limits, including no live TURN or full-user capacity claim, remain.
