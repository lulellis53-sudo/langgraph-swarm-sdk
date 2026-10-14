"""gRPC transport for the swarm (``rpc`` extra).

Requires the generated stubs under ``langswarm.proto``; run the generation
command from the project README before starting this server.
"""

from langswarm.config import settings


def serve(port: int | None = None) -> None:
    """Build the swarm, bind a synchronous gRPC server, serve forever."""
    from concurrent import futures

    import grpc

    from langswarm.blueprint import load_blueprint
    from langswarm.proto import langswarm_pb2, langswarm_pb2_grpc
    from langswarm.runner import run_swarm
    from langswarm.swarm import build_from_blueprint

    graph = build_from_blueprint(load_blueprint(settings.config_path))

    class SwarmServicer(langswarm_pb2_grpc.SwarmServicer):
        def Chat(self, request, context):
            answer = run_swarm(
                graph,
                request.message,
                thread_id=request.thread_id or "grpc-thread",
            )
            return langswarm_pb2.ChatResponse(answer=answer)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    langswarm_pb2_grpc.add_SwarmServicer_to_server(SwarmServicer(), server)
    server.add_insecure_port(f"[::]:{port or settings.grpc_port}")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
