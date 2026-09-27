"""gRPC Run and Recall service."""

from __future__ import annotations

import asyncio
import concurrent.futures

import grpc

from swarm_sdk.config import Settings
from swarm_sdk.pb import swarm_pb2, swarm_pb2_grpc
from swarm_sdk.swarm import SwarmSDK


class SwarmServicer(swarm_pb2_grpc.SwarmServiceServicer):
    def __init__(self, sdk: SwarmSDK) -> None:
        self.sdk = sdk

    def Run(
        self,
        request: swarm_pb2.RunRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.RunResponse:
        del context
        result = asyncio.run(self.sdk.run(request.text, request.thread_id or "default"))
        return swarm_pb2.RunResponse(
            text=result.text,
            cached=result.cached,
            active_agent=result.active_agent,
            tokens=result.tokens,
            mode=result.mode,
        )

    def Recall(
        self,
        request: swarm_pb2.RecallRequest,
        context: grpc.ServicerContext | None,
    ) -> swarm_pb2.RecallResponse:
        del context
        hits = self.sdk.recall(request.query, request.top_k or 4)
        return swarm_pb2.RecallResponse(
            hits=[
                swarm_pb2.MemoryHit(id=hit.id, text=hit.text, score=hit.score) for hit in hits
            ]
        )


def serve(sdk: SwarmSDK, host: str = "127.0.0.1", port: int = 50051) -> grpc.Server:
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=8))
    swarm_pb2_grpc.add_SwarmServiceServicer_to_server(SwarmServicer(sdk), server)
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    return server


def main() -> None:
    settings = Settings()
    server = serve(SwarmSDK.from_settings(), settings.api_host, settings.grpc_port)
    server.wait_for_termination()
