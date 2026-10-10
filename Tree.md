                      SDK
                      . LangGraph
                      . Project Configs
                      . Share
                      . src
                      # Python 3.15
                      # pyproject.toml
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
 # Make a copy of the branch if want to benchmark A/B test
