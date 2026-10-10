                      SDK
                      . LangGraph
                      . Project Configs
                      . Share
                      . src
                            |
      +-----------+---------+----------+-----------+
      |           |         |          |
      v           v         v          v
 +----------+ +----------+ +----------+ +----------+
 | Modules  | |  Agents  | |  Tools   | |  Vector  |
 +----------+ +----------+ +----------+ +----------+
      |            |            |
      +-- Newsletter +-- RAG      +-- Swarm
      +-- BotDeal    +-- Memory   +-- Prediction
      +-- TechNews                +-- WebSearch
                                  +-- WebScraper

 # Swarm       multi-orchestration agents
 # Prediction  algorithms; each module has its own forecast
 # WebSearch   WebSearch / WebFetch = agent tooling
