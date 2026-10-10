# Tree — `swarm_sdk` square

```
+==================================================================================+
|                                  swarm_sdk                                       |
|                              src/swarm_sdk/                                      |
+==================================================================================+
|                                                                                  |
|     +------------+   +------------+   +------------+   +------------+            |
|     |   agents   |   |  commands  |   |   config   |   |    core    |            |
|     | manifests  |   | CLI verbs  |   | settings   |   | graph /    |            |
|     | YAML       |   |            |   | providers  |   | allocator  |            |
|     +------------+   +------------+   +------------+   +------------+            |
|                                                                                  |
|     +------------+   +------------+   +------------+   +------------+            |
|     | execution  |   |    gpu     |   |    math    |   |   memory   |            |
|     | GIL caps   |   | OpenCL     |   | calcs      |   | stores     |            |
|     +------------+   +------------+   +------------+   +------------+            |
|                                                                                  |
|     +------------+   +------------+   +------------+   +------------+            |
|     |   models   |   |observabilit|   |orchestrator|   |     pb     |            |
|     | chat /     |   | metrics    |   | plan spawn |   | protobuf   |            |
|     | breaker    |   | traces     |   | workers    |   |            |            |
|     +------------+   +------------+   +------------+   +------------+            |
|                                                                                  |
|     +------------+   +------------+   +------------+   +------------+            |
|     | prediction |   | prompting  |   | retrieval  |   |   search   |            |
|     | forecast   |   | budget     |   | hybrid RAG |   | DDG /      |            |
|     |            |   | pruner     |   | gate cache |   | perplexity |            |
|     +------------+   +------------+   +------------+   +------------+            |
|                                                                                  |
|     +------------+   +------------+   +------------+                             |
|     |   server   |   |  serving   |   |   tuning   |                             |
|     | HTTP graphs|   | HTTP/gRPC  |   | study      |                             |
|     +------------+   +------------+   +------------+                             |
|                                                                                  |
|     vault.py   cli.py   netguard.py   redact.py   protocols.py   decorators.py   |
|                                                                                  |
+==================================================================================+
```
