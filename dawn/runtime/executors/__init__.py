from .base import Executor, RunResult
from .local import LocalExecutor
from .subprocess import SubprocessExecutor
from .docker import DockerExecutor

def get_executor(name: str = "local", **kwargs) -> Executor:
    if name == "local":
        return LocalExecutor(**kwargs)
    elif name == "subprocess":
        return SubprocessExecutor(**kwargs)
    elif name == "docker":
        return DockerExecutor(**kwargs)
    else:
        raise ValueError(f"Unknown executor: {name}")
