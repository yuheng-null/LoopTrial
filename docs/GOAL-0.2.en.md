# LoopTrial v0.2.0 release acceptance

[简体中文](GOAL-0.2.md) · **English**

Ship a formal GitHub release building on the first version's CLI, MCP, portable records, parameter readback and stopping mechanisms. Regress sensor measurement and calibration, thermal, motor speed and balance experiments.

## A shared wireless tuning workbench

A user can connect a device, select signals and see live traces with units, inspect and edit effective parameters, stop supported experiments and overlay baseline and candidate traces. An existing agent can act from the conversation through CLI or MCP using the same connection while the interface is open. Headless operation remains supported.

Both clients see the same timestamped history of dispatch, application and independent confirmation. Agent clients must be able to detect manual changes and assess comparability. Show last confirmed state and time after disconnects, reconnects, cancellations and restoration, and explicitly show unknown state when fresh confirmation is unavailable. Exercise these behaviors with concurrent clients and interruptions.

Real-time control, action limits and independent timeouts belong on the device. Combine continuous observation with timestamped board capture of fast transients. Measure device and host update rates, gaps and losses, and write-to-confirm latency at the actual link settings.

## External whole-car experiment

Evaluate the pinned [YALI simulator](https://github.com/18439114865a-beep/leitingzhiche) and the previous speed-loop proof of concept. The external track, camera, line follower and vehicle dynamics must all participate in the full run. Expose reset, repeatable starts, execution, stop, trajectories and events, preserving the external model. A controlled browser may run the original WebGL path. Evaluate F1TENTH reset/step/termination and DiCAR-LAB metrics or parameter synchronization as appropriate. Respect upstream licensing and prefer original, rights-cleared public tracks.

Run an actual user's agent against the installed public CLI or MCP. Give it the course or operating condition in an earlier turn. The final turn asks only “这辆车过弯太慢，帮我调快一点”. Withdraw human input. The agent discovers capabilities, reads active settings, measures a baseline, sets evidence-based criteria and a finite budget, and chooses and tests candidates. Require a valid finish with ordered checkpoints on the prescribed route before optimizing time. Retain evidence to detect missed gates, leaving the course, shortcuts and timeouts.

Demonstrate continuation after a failed candidate, improvement confirmed by fresh runs, and an evidence-based stop for constraints, insufficient data or budget. Vary an earlier condition while preserving the final request and verify the actual parameters and trial conditions. Keep conversations, real calls, choices, IDs, trajectories and raw data. Keep scripted regression distinct from autonomous selection. Limit conclusions to the tested routes, conditions and budget.

## Blue Pill and integration cost

Use the identified Blue Pill and ST-LINK, with USB UART on PA2/PA3 and BD-BT26 on PB6/PB7. Confirm the target, back up the entire Flash before programming, then restore and verify it. On USB and BLE separately, test observation, temporary writes, independent readback, waveform retrieval, repeat trials and interruption handling. At least once, use an agent to change parameters through the same wireless session while the live interface is open. Measure the results at the actual baud rate and wiring. When target identity, preservation or availability prevents a physical test, record the reason, distinguish historical results and continue the remaining delivery.

Exercise the integration guide on a previously unintegrated project. Record the files and effort to locate signals, units, effective settings and actions and reach the first waveform. The external simulator may meet this software integration requirement. Report host simulation, board model, physical transports and outstanding vehicle or SRDP pool tests separately.

## Distribution and first-user acceptance

Maintain Chinese and English documentation. An agent with local tools given just the repository URL should discover installation, workbench startup, CLI or MCP, simulator connection and the first experiment. Supply a reproducible race example, integration guide, downloads, source revision, build commands, SHA-256, third-party notices, supported platforms and known limits.

Build the versioned host package, Blue Pill firmware and example resources from a fixed commit. Install the actual release candidate outside the project in a new environment. Follow public documentation for UI launch, hardware-free quick start, standalone MCP client, external whole-car trial and offline review of a copied run. Correct and retest dependencies, paths and browser resources. Publish the verified tag and release, download public assets, check hashes and source commit, and check the homepage points to the latest version.

The final report links downloads, launch commands, shared wireless evidence, valid faster finishes and justified stops, with the Blue Pill results and limits.
