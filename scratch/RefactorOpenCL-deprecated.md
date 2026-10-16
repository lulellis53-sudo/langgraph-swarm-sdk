# RefactorOpenCL folder is deprecated

OpenCL code now lives in **`Core/Sdk/swarm_sdk/opencl/`** (canonical). Compatibility shims:

- `swarm_sdk.gpu.opencl_math`
- `swarm_sdk.gpu._opencl_utils`

The `RefactorOpenCL/` tree at the workspace root is a stale full-repo copy (~755 MB). Safe to archive under `scratch/` after you confirm nothing unique remains:

```bash
tar --zstd -cf scratch/RefactorOpenCL-$(date +%Y%m%d).tar.zst RefactorOpenCL
/bin/rm -rf RefactorOpenCL
```

Do not use `mv` on git worktrees; this copy no longer has a `.git` link.
