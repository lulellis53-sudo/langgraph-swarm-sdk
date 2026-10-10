                                   SDK
                                   . LangGraph
                                   . Project Configs
                                   . Share
                                   . src
                                        |
           +----------------------------+----------------------------+
           |                    |                    |               |
           v                    v                    v               v
     +---------+          +--------+           +-------+      +----------+
     | Modules |          | Agents |           | Tools |      |  Vector  |
     +---------+          +--------+           +-------+      +----------+
           |                                       |
           |                                       +-----> +------------+
           |                                       |       |   Swarm    |  #1 multi-orchestration agents
           +-----> +------------+                  |       +------------+
           |       | Newsletter |                  |
           |       +------------+                  +-----> +------------+
           |                                       |       | Prediction |  # algorithms; each module has its own forecast
           +-----> +---------+                     |       +------------+
           |       | BotDeal |                     |
           |       +---------+                     +-----> +------------+
           |                                       |       | WebSearch  |  # WebSearch / WebFetch = agent tooling
           +-----> +----------+                    |       +------------+
                   | TechNews |                    |
                   +----------+                    +-----> +------------+
                                                           | WebScraper |
                                                           +------------+
